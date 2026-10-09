"""A thread-owned SQLite writer with explicit transactions and a local run journal."""

import hashlib
import json
import logging
import os
import platform
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from trading_system.market_data.models import PriceEvent
from trading_system.persistence.config import database_path
from trading_system.persistence.records import (
    INTERVAL_MS,
    CandleRecord,
    candle_from_row,
    decimal_text,
    epoch_ms,
    now_ms,
    validate_ms,
)

logger = logging.getLogger("trading_system.persistence")
SCHEMA_VERSION = 1
RUN_COUNTERS = (
    "messages_received",
    "price_snapshots_written",
    "candles_written",
    "duplicate_candles",
    "gaps_detected",
    "gaps_resolved",
    "reconnect_count",
)
RUN_COLUMNS = (
    "run_id",
    "started_at_ms",
    "ended_at_ms",
    "execution_environment",
    "status",
    *RUN_COUNTERS,
    "error_category",
)
RUN_STATUSES = (
    "RUNNING",
    "COMPLETED",
    "INCOMPLETE",
    "PERSISTENCE_FAILURE",
    "BLOCKED_ENVIRONMENT",
    "INTERRUPTED",
)
ERROR_CATEGORIES = (
    None,
    "persistence_failure",
    "abrupt_shutdown",
    "incomplete_rest_page",
    "recovery_budget_exceeded",
    "recovery_range_exceeded",
    "candle_conflict",
    "network_timeout",
    "connection_error",
    "http_4xx",
    "http_5xx",
    "rate_limit",
    "ip_ban",
    "invalid_response",
    "http_redirect_rejected",
    "stream_failure",
    "interrupted",
    "incomplete_data",
    "unexpected_recovery_failure",
)


class PersistenceError(RuntimeError):
    def __init__(self, kind="persistence_failure"):
        self.kind = kind
        super().__init__(kind)


class WriterLease:
    """OS advisory lock survives as a file, but releases on process exit/crash."""

    def __init__(self, path: Path):
        self.file = None
        try:
            fd = os.open(str(path) + ".writer.lock", os.O_RDWR | os.O_CREAT, 0o600)
            self.file = os.fdopen(fd, "r+b")
            if not self.file.read(1):
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self.file:
                self.file.close()
            raise PersistenceError("writer_unavailable") from None

    def close(self):
        if self.file and not self.file.closed:
            self.file.close()


def validate_schema(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise PersistenceError("unsupported_schema_version")
    expected = {
        "price_snapshots": (
            "symbol",
            "bucket_start_ms",
            "price_text",
            "event_time_ms",
            "received_at_ms",
            "source",
        ),
        "candles_4h": (
            "symbol",
            "interval",
            "open_time_ms",
            "close_time_ms",
            "open_text",
            "high_text",
            "low_text",
            "close_text",
            "volume_text",
            "event_time_ms",
            "ingested_at_ms",
            "source",
        ),
        "data_gaps": (
            "gap_id",
            "symbol",
            "interval",
            "start_time_ms",
            "end_time_ms",
            "detected_at_ms",
            "detected_reason",
            "status",
            "resolution_source",
            "resolved_at_ms",
        ),
        "ingestion_runs": RUN_COLUMNS,
        "candle_conflicts": (
            "symbol",
            "interval",
            "open_time_ms",
            "incoming_fingerprint",
            "existing_data",
            "incoming_data",
            "detected_at_ms",
        ),
    }
    for table, columns in expected.items():
        # Identifiers are static internal schema names, never user input.
        if tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})")) != columns:
            raise PersistenceError("schema_mismatch")


class MarketStore:
    def __init__(self, path="data/market_data.sqlite"):
        self.path = database_path(path)
        self.connection = self.lease = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.lease = WriterLease(self.path)
            self.connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA busy_timeout=5000")
            self.connection.execute("PRAGMA foreign_keys=ON")
            if self.connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise PersistenceError("wal_unavailable")
            self.connection.execute("PRAGMA synchronous=FULL")
            if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise PersistenceError("integrity_failure")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table'"
                ).fetchone():
                    raise PersistenceError("schema_mismatch")
                with self.transaction():
                    for statement in Path(__file__).with_name("schema.sql").read_text().split(";"):
                        if statement.strip():
                            self.connection.execute(statement)
            validate_schema(self.connection)
            self._restore_run_history()
        except OSError, sqlite3.Error:
            self.close()
            raise PersistenceError() from None
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        try:
            if self.connection:
                self.connection.close()
                self.connection = None
        finally:
            if self.lease:
                self.lease.close()

    def commit(self):
        self.connection.execute("COMMIT")

    @contextmanager
    def transaction(self):
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield
            self.commit()
        except BaseException as error:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            if isinstance(error, sqlite3.Error):
                raise PersistenceError() from None
            raise

    def missing_ranges(self, symbol, start, end):
        from trading_system.config import SYMBOLS

        if symbol not in SYMBOLS:
            raise ValueError("Unsupported symbol.")
        validate_ms(start)
        validate_ms(end)
        if start % INTERVAL_MS or end % INTERVAL_MS or end < start:
            raise ValueError("Invalid inclusive candle range.")
        rows = self.connection.execute(
            "SELECT open_time_ms FROM candles_4h WHERE symbol=? AND interval='4h' "
            "AND open_time_ms BETWEEN ? AND ? ORDER BY open_time_ms",
            (symbol, start, end),
        )
        expected, gaps = start, []
        for row in rows:
            actual = row[0]
            if actual > expected:
                gaps.append((expected, actual - INTERVAL_MS))
            expected = actual + INTERVAL_MS
        if expected <= end:
            gaps.append((expected, end))
        return gaps

    def _gap(self, symbol, start, end, reason, status="OPEN"):
        previous = self.connection.execute(
            "SELECT gap_id,status FROM data_gaps WHERE symbol=? AND interval='4h' "
            "AND start_time_ms=? AND end_time_ms=? AND detected_reason=?",
            (symbol, start, end, reason),
        ).fetchone()
        if previous:
            if status == "CONFLICT" or previous["status"] == "RESOLVED":
                self.connection.execute(
                    "UPDATE data_gaps SET status=?,resolution_source=NULL,resolved_at_ms=NULL "
                    "WHERE gap_id=?",
                    (status, previous["gap_id"]),
                )
            return previous["gap_id"], previous["status"] == "RESOLVED"
        cursor = self.connection.execute(
            "INSERT INTO data_gaps(symbol,interval,start_time_ms,end_time_ms,detected_at_ms,"
            "detected_reason,status) VALUES (?,'4h',?,?,?,?,?)",
            (symbol, start, end, now_ms(), reason, status),
        )
        return cursor.lastrowid, True

    def record_gap(self, symbol, start, end, reason="missing_closed_candles"):
        self.missing_ranges(symbol, start, end)  # Validate the identity and bounds.
        if reason not in ("missing_closed_candles", "last_candle_validation"):
            raise ValueError("Unsupported gap reason.")
        with self.transaction():
            return self._gap(symbol, start, end, reason)

    def set_gap_status(self, gap_id, status, source=None):
        if status not in ("RECOVERING", "RESOLVED", "FAILED", "CONFLICT"):
            raise ValueError("Invalid gap state.")
        if source not in (None, "REST_BOOTSTRAP", "REST_RECOVERY"):
            raise ValueError("Invalid resolution source.")
        with self.transaction():
            self.connection.execute(
                "UPDATE data_gaps SET status=?,resolution_source=?,resolved_at_ms=? "
                "WHERE gap_id=? AND status!='CONFLICT'",
                (
                    status,
                    source if status == "RESOLVED" else None,
                    now_ms() if status == "RESOLVED" else None,
                    gap_id,
                ),
            )

    def _save_candle(self, record: CandleRecord):
        previous = self.connection.execute(
            "SELECT * FROM candles_4h WHERE symbol=? AND interval=? AND open_time_ms=?",
            record.identity,
        ).fetchone()
        if previous:
            stored = candle_from_row(previous)
            if record.content == stored.content:
                return "duplicate"

            def payload(r):
                return json.dumps(
                    {
                        "ohlcv": [decimal_text(v, positive=False) for v in r.content[1:]],
                        "close_time_ms": r.close_time_ms,
                        "source": r.source,
                        "event_time_ms": r.event_time_ms,
                        "ingested_at_ms": r.ingested_at_ms,
                    },
                    sort_keys=True,
                )

            incoming = payload(record)
            # Metadata changes must not create unlimited copies of the same OHLCV conflict.
            content = json.dumps([record.close_time_ms, *(str(v) for v in record.content[1:])])
            fingerprint = hashlib.sha256(content.encode()).hexdigest()
            self.connection.execute(
                "INSERT OR IGNORE INTO candle_conflicts VALUES (?,?,?,?,?,?,?)",
                (*record.identity, fingerprint, payload(stored), incoming, now_ms()),
            )
            self._gap(
                record.symbol,
                record.open_time_ms,
                record.open_time_ms,
                "candle_data_conflict",
                "CONFLICT",
            )
            logger.error(
                "candle CONFLICT symbol=%s open_time_ms=%d", record.symbol, record.open_time_ms
            )
            return "conflict"
        self.connection.execute(
            "INSERT INTO candles_4h VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                *record.identity,
                record.close_time_ms,
                *(decimal_text(v, positive=False) for v in record.content[1:]),
                record.event_time_ms,
                record.ingested_at_ms,
                record.source,
            ),
        )
        return "written"

    def write_batch(
        self,
        candles=(),
        prices=(),
        *,
        snapshot_at_ms=None,
        snapshot_seconds=60,
        stale_after_seconds=10,
    ):
        for record in candles:
            record.validate()
        if type(snapshot_seconds) is not int or not 1 <= snapshot_seconds <= 3600:
            raise ValueError("Invalid snapshot bucket size.")
        stats = dict(candles_written=0, duplicate_candles=0, conflicts=0, price_snapshots_written=0)
        with self.transaction():
            for record in candles:
                outcome = self._save_candle(record)
                key = {
                    "written": "candles_written",
                    "duplicate": "duplicate_candles",
                    "conflict": "conflicts",
                }[outcome]
                stats[key] += 1
            for event in prices:
                if not isinstance(event, PriceEvent):
                    raise ValueError("Expected price event.")
                validate_ms(snapshot_at_ms)
                event_ms, received_ms = epoch_ms(event.event_time), epoch_ms(event.received_at)
                # Recheck freshness at the actual write boundary. Never relabel old data as new.
                if not all(
                    0 <= snapshot_at_ms - t <= stale_after_seconds * 1000
                    for t in (event_ms, received_ms)
                ):
                    continue
                price_text = decimal_text(event.price)
                bucket = snapshot_at_ms // (snapshot_seconds * 1000) * snapshot_seconds * 1000
                cursor = self.connection.execute(
                    "INSERT INTO price_snapshots VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(symbol,bucket_start_ms) DO UPDATE SET "
                    "price_text=excluded.price_text,"
                    "event_time_ms=excluded.event_time_ms,received_at_ms=excluded.received_at_ms "
                    "WHERE excluded.event_time_ms>price_snapshots.event_time_ms",
                    (event.symbol, bucket, price_text, event_ms, received_ms, event.source),
                )
                stats["price_snapshots_written"] += cursor.rowcount
        return stats

    def retain_prices(self, cutoff_ms):
        validate_ms(cutoff_ms)
        with self.transaction():
            return self.connection.execute(
                "DELETE FROM price_snapshots WHERE bucket_start_ms < ?",
                (cutoff_ms,),
            ).rowcount

    @property
    def journal_path(self):
        return Path(str(self.path) + ".runs.jsonl")

    def _validate_run(self, record):
        if set(record) != set(RUN_COLUMNS) or record["status"] not in RUN_STATUSES:
            raise PersistenceError("run_journal_invalid")
        if record["execution_environment"] not in ("Linux", "Windows", "Darwin", "test"):
            raise PersistenceError("run_journal_invalid")
        if record["error_category"] not in ERROR_CATEGORIES:
            raise PersistenceError("run_journal_invalid")
        try:
            uuid.UUID(record["run_id"])
            validate_ms(record["started_at_ms"])
            if record["ended_at_ms"] is not None:
                validate_ms(record["ended_at_ms"])
            if any(type(record[k]) is not int or record[k] < 0 for k in RUN_COUNTERS):
                raise ValueError
        except ValueError, TypeError, AttributeError:
            raise PersistenceError("run_journal_invalid") from None

    def _upsert_run(self, record):
        self.connection.execute(
            "INSERT INTO ingestion_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id) DO UPDATE SET ended_at_ms=excluded.ended_at_ms,"
            "status=excluded.status,messages_received=excluded.messages_received,"
            "price_snapshots_written=excluded.price_snapshots_written,candles_written=excluded.candles_written,"
            "duplicate_candles=excluded.duplicate_candles,gaps_detected=excluded.gaps_detected,"
            "gaps_resolved=excluded.gaps_resolved,reconnect_count=excluded.reconnect_count,"
            "error_category=excluded.error_category",
            tuple(record[k] for k in RUN_COLUMNS),
        )

    def _journal(self, record):
        self._validate_run(record)
        try:
            fd = os.open(self.journal_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise PersistenceError() from None

    def _restore_run_history(self):
        # Independent minimal journal preserves run history if just the DB is removed.
        # Removing both DB and journal still requires a verified backup.
        with self.transaction():
            if self.journal_path.exists():
                try:
                    with self.journal_path.open(encoding="utf-8") as stream:
                        for line in stream:
                            if len(line) > 8192:
                                raise PersistenceError("run_journal_invalid")
                            record = json.loads(line)
                            self._validate_run(record)
                            self._upsert_run(record)
                except OSError, ValueError, TypeError:
                    raise PersistenceError("run_journal_invalid") from None
            interrupted = self.connection.execute(
                "SELECT * FROM ingestion_runs WHERE ended_at_ms IS NULL",
            ).fetchall()
            for row in interrupted:
                record = dict(row)
                record.update(
                    ended_at_ms=now_ms(), status="INTERRUPTED", error_category="abrupt_shutdown"
                )
                self._journal(record)
                self._upsert_run(record)

    def start_run(self, environment=None):
        record = dict.fromkeys(RUN_COLUMNS)
        record.update(
            run_id=str(uuid.uuid4()),
            started_at_ms=now_ms(),
            ended_at_ms=None,
            execution_environment=environment or platform.system(),
            status="RUNNING",
        )
        record.update(dict.fromkeys(RUN_COUNTERS, 0))
        self._journal(record)
        with self.transaction():
            self._upsert_run(record)
        return record["run_id"]

    def finish_run(self, run_id, status, counters, error_category=None):
        row = self.connection.execute(
            "SELECT * FROM ingestion_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown ingestion run.")
        record = dict(row)
        record.update({key: counters.get(key, 0) for key in RUN_COUNTERS})
        record.update(ended_at_ms=now_ms(), status=status, error_category=error_category)
        self._journal(record)
        with self.transaction():
            self._upsert_run(record)
