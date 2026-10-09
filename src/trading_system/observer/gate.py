"""Read-only market snapshot joined to W03's verified initialization history."""

import math
from dataclasses import asdict

import pandas as pd

from trading_system.config import SYMBOLS
from trading_system.observer.audit import historical_frames
from trading_system.observer.model import FREEZE_MS, ObserverError, digest
from trading_system.persistence.records import INTERVAL_MS, validate_ms


def history_hash(frame, provenance):
    return digest({"ohlcv": frame.to_csv(), "provenance": provenance})


class WarmupLoader:
    def __init__(self, data_hashes):
        _, self.historical = historical_frames()
        self.data_hashes = data_hashes

    def load(self, repository, target_ms, evaluated_at):
        validate_ms(target_ms)
        validate_ms(evaluated_at)
        if target_ms % INTERVAL_MS or target_ms + INTERVAL_MS > evaluated_at:
            raise ObserverError("UNCONFIRMED_OR_FUTURE_BAR")
        frames, provenance, input_hashes = {}, {}, {}
        # All symbols are read in the caller's single SQLite read transaction.
        if not repository.integrity():
            raise ObserverError("MARKET_DB_INTEGRITY")
        if any(g["status"] != "RESOLVED" for g in repository.gaps()):
            raise ObserverError("UNRESOLVED_GAP")
        if repository.connection.execute("SELECT count(*) FROM candle_conflicts").fetchone()[0]:
            raise ObserverError("MARKET_CANDLE_CONFLICT")
        for symbol in SYMBOLS:
            stamp = pd.Timestamp(target_ms, unit="ms", tz="UTC")
            base = self.historical[symbol].loc[:stamp].copy()
            records = (
                repository.candles(symbol, FREEZE_MS, target_ms) if target_ms >= FREEZE_MS else ()
            )
            serialized = []
            rows = []
            times = []
            for candle in records:
                try:
                    candle.validate()
                except ValueError, TypeError:
                    raise ObserverError("INVALID_OHLCV_PROVENANCE") from None
                if (
                    candle.close_time_ms >= evaluated_at
                    or candle.ingested_at_ms > evaluated_at
                    or (candle.event_time_ms is not None and candle.event_time_ms > evaluated_at)
                ):
                    raise ObserverError("FUTURE_INFORMATION")
                serialized.append(
                    {
                        k: str(v) if k in ("open", "high", "low", "close", "volume") else v
                        for k, v in asdict(candle).items()
                    }
                )
                rows.append(
                    [float(getattr(candle, k)) for k in ("open", "high", "low", "close", "volume")]
                )
                times.append(pd.Timestamp(candle.open_time_ms, unit="ms", tz="UTC"))
            if records:
                forward = pd.DataFrame(rows, index=pd.DatetimeIndex(times), columns=base.columns)
                base = pd.concat([base, forward])
            if base.empty or base.index[-1] != stamp:
                raise ObserverError("THREE_SYMBOL_BARRIER_MISSING")
            if base.index.has_duplicates or not base.index.is_monotonic_increasing:
                raise ObserverError("DUPLICATE_OR_UNORDERED_DATA")
            if not base.index.to_series().diff().iloc[1:].eq(pd.Timedelta(hours=4)).all():
                raise ObserverError("MISSING_CANDLE")
            for row in base.itertuples(index=False):
                if (
                    not all(math.isfinite(v) for v in row)
                    or min(row[:4]) <= 0
                    or row.volume < 0
                    or row.low > min(row.open, row.close)
                    or row.high < max(row.open, row.close)
                ):
                    raise ObserverError("INVALID_OHLCV")
            latest = (
                serialized[-1]
                if serialized
                else {
                    "source": "W03_FROZEN_HISTORICAL",
                    "ingested_at_ms": FREEZE_MS,
                    "event_time_ms": None,
                }
            )
            provenance[symbol] = {
                **latest,
                "frozen_data_hash": self.data_hashes[symbol],
                "history_source_hash": digest(serialized),
                "initialization_start": str(base.index[0]),
            }
            frames[symbol] = base
            input_hashes[symbol] = history_hash(base, provenance[symbol])
        return frames, provenance, input_hashes
