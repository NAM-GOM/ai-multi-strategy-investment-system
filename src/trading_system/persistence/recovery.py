"""Bounded public REST bootstrap/recovery; resolution requires corroborated continuous data."""

import logging
import time

from trading_system.binance.client import BinanceError
from trading_system.config import SYMBOLS
from trading_system.persistence.records import DAY_MS, INTERVAL_MS, CandleRecord, epoch_ms, now_ms
from trading_system.persistence.store import PersistenceError

logger = logging.getLogger("trading_system.recovery")


class RecoveryError(RuntimeError):
    def __init__(self, kind):
        self.kind = kind
        super().__init__(kind)


class Backfill:
    def __init__(self, store, public, config, *, sleep=time.sleep, monotonic=time.monotonic):
        self.store, self.public, self.config = store, public, config
        self.sleep, self.monotonic = sleep, monotonic
        self.requests = 0
        self.next_request_at = 0.0
        self.stats = dict(
            candles_written=0,
            duplicate_candles=0,
            conflicts=0,
            price_snapshots_written=0,
            gaps_detected=0,
            gaps_resolved=0,
        )
        self.error_category = None
        self.blocked_kind = None

    def _request(self, function, *args, **kwargs):
        if self.blocked_kind:
            raise RecoveryError(self.blocked_kind)
        for attempt in range(self.config.rest_retries + 1):
            if self.requests >= self.config.max_rest_requests:
                raise RecoveryError("recovery_budget_exceeded")
            self.sleep(max(0, self.next_request_at - self.monotonic()))
            self.requests += 1
            self.next_request_at = self.monotonic() + self.config.rest_interval_seconds
            try:
                return function(*args, **kwargs)
            except BinanceError as error:
                if error.status in (418, 429, 451):
                    self.blocked_kind = error.kind
                # 429/418/451 do not trigger retries. Never print raw response data.
                if attempt >= self.config.rest_retries or error.kind not in (
                    "network_timeout",
                    "connection_error",
                    "http_5xx",
                ):
                    raise
                self.sleep(min(5, 2**attempt))
        raise RecoveryError("unexpected_recovery_failure")

    def _add_stats(self, stats):
        for key, value in stats.items():
            self.stats[key] = self.stats.get(key, 0) + value

    def _fetch_range(self, symbol, start, end, server_ms, source):
        if end - start + INTERVAL_MS > self.config.recovery_max_days * DAY_MS:
            raise RecoveryError("recovery_range_exceeded")
        cursor = start
        while cursor <= end:
            page_end = min(end, cursor + 999 * INTERVAL_MS)
            candles = self._request(
                self.public.candles_range,
                symbol,
                start_time_ms=cursor,
                end_time_ms=page_end + INTERVAL_MS - 1,
                limit=1000,
            )
            expected_count = (page_end - cursor) // INTERVAL_MS + 1
            if len(candles) != expected_count:
                raise RecoveryError("incomplete_rest_page")
            records = []
            for index, candle in enumerate(candles):
                start_ms, close_ms = epoch_ms(candle.open_time), epoch_ms(candle.close_time)
                if start_ms != cursor + index * INTERVAL_MS or close_ms >= server_ms:
                    raise RecoveryError("incomplete_rest_page")
                record = CandleRecord(
                    symbol,
                    "4h",
                    start_ms,
                    close_ms,
                    candle.open,
                    candle.high,
                    candle.low,
                    candle.close,
                    candle.volume,
                    None,
                    now_ms(),
                    source,
                )
                try:
                    record.validate()
                except ValueError:
                    raise RecoveryError("invalid_response") from None
                records.append(record)
            result = self.store.write_batch(candles=records)
            self._add_stats(result)
            if result["conflicts"]:
                raise RecoveryError("candle_conflict")
            cursor = page_end + INTERVAL_MS

    def run(self):
        try:
            server_ms = self._request(self.public.server_time_ms)
        except (BinanceError, RecoveryError) as error:
            # Record expected missing ranges even when the server clock is unavailable.
            self.error_category = error.kind
            approximate_end = now_ms() // INTERVAL_MS * INTERVAL_MS - INTERVAL_MS
            approximate_start = approximate_end + INTERVAL_MS - self.config.bootstrap_days * DAY_MS
            for symbol in SYMBOLS:
                for start, end in self.store.missing_ranges(
                    symbol, approximate_start, approximate_end
                ):
                    gap_id, created = self.store.record_gap(symbol, start, end)
                    self.stats["gaps_detected"] += created
                    self.store.set_gap_status(gap_id, "FAILED")
                latest = self.store.connection.execute(
                    "SELECT max(open_time_ms) FROM candles_4h WHERE symbol=?",
                    (symbol,),
                ).fetchone()[0]
                if latest is not None:
                    gap_id, created = self.store.record_gap(
                        symbol,
                        latest,
                        latest,
                        "last_candle_validation",
                    )
                    self.stats["gaps_detected"] += created
                    self.store.set_gap_status(gap_id, "FAILED")
            return self._result()
        last_closed = server_ms // INTERVAL_MS * INTERVAL_MS - INTERVAL_MS
        bootstrap_start = last_closed + INTERVAL_MS - self.config.bootstrap_days * DAY_MS
        for symbol in SYMBOLS:
            extremes = self.store.connection.execute(
                "SELECT min(open_time_ms),max(open_time_ms) FROM candles_4h WHERE symbol=?",
                (symbol,),
            ).fetchone()
            source = "REST_BOOTSTRAP" if extremes[0] is None else "REST_RECOVERY"
            start = (
                min(bootstrap_start, extremes[0]) if extremes[0] is not None else bootstrap_start
            )
            ranges = self.store.missing_ranges(symbol, start, last_closed)
            for gap_start, gap_end in ranges:
                _, created = self.store.record_gap(symbol, gap_start, gap_end)
                self.stats["gaps_detected"] += created
            pending = self.store.connection.execute(
                "SELECT * FROM data_gaps WHERE symbol=? "
                "AND status IN ('OPEN','RECOVERING','FAILED') "
                "AND end_time_ms<=? ORDER BY start_time_ms",
                (symbol, last_closed),
            ).fetchall()
            for gap in pending:
                gap_id = gap["gap_id"]
                self.store.set_gap_status(gap_id, "RECOVERING")
                try:
                    self._fetch_range(
                        symbol, gap["start_time_ms"], gap["end_time_ms"], server_ms, source
                    )
                    if self.store.missing_ranges(symbol, gap["start_time_ms"], gap["end_time_ms"]):
                        raise RecoveryError("incomplete_rest_page")
                    conflict = self.store.connection.execute(
                        "SELECT 1 FROM data_gaps WHERE symbol=? AND status='CONFLICT' "
                        "AND start_time_ms<=? AND end_time_ms>=?",
                        (symbol, gap["end_time_ms"], gap["start_time_ms"]),
                    ).fetchone()
                    if conflict:
                        raise RecoveryError("candle_conflict")
                    self.store.set_gap_status(gap_id, "RESOLVED", source)
                    self.stats["gaps_resolved"] += 1
                except (BinanceError, RecoveryError) as error:
                    self.error_category = error.kind
                    self.store.set_gap_status(
                        gap_id, "CONFLICT" if error.kind == "candle_conflict" else "FAILED"
                    )
                    logger.error(
                        "REST recovery incomplete symbol=%s category=%s", symbol, error.kind
                    )
                except PersistenceError:
                    raise
            # Always compare the DB's most recent closed candle against REST, even without holes.
            if extremes[1] is not None and extremes[1] <= last_closed:
                try:
                    self._fetch_range(symbol, extremes[1], extremes[1], server_ms, "REST_RECOVERY")
                except (BinanceError, RecoveryError) as error:
                    self.error_category = error.kind
                    gap_id, created = self.store.record_gap(
                        symbol,
                        extremes[1],
                        extremes[1],
                        "last_candle_validation",
                    )
                    self.stats["gaps_detected"] += created
                    self.store.set_gap_status(
                        gap_id, "CONFLICT" if error.kind == "candle_conflict" else "FAILED"
                    )
        return self._result()

    def _result(self):
        unresolved = self.store.connection.execute(
            "SELECT count(*) FROM data_gaps WHERE status!='RESOLVED'",
        ).fetchone()[0]
        result = dict(
            self.stats,
            rest_requests=self.requests,
            error_category=self.error_category,
            data_status="COMPLETE" if not unresolved and not self.error_category else "INCOMPLETE",
        )
        logger.info(
            "REST bootstrap/recovery status=%s candles=%d gaps_resolved=%d requests=%d",
            result["data_status"],
            result["candles_written"],
            result["gaps_resolved"],
            self.requests,
        )
        return result
