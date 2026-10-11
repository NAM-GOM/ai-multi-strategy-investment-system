"""Read-only, ordered queries expose the original market-data provenance."""

import os
import sqlite3
from decimal import Decimal, InvalidOperation

from trading_system.config import SYMBOLS
from trading_system.persistence.config import database_path
from trading_system.persistence.records import (
    INTERVAL_MS,
    PriceSnapshot,
    candle_from_row,
    decimal_text,
    now_ms,
    validate_ms,
)
from trading_system.persistence.store import PersistenceError, validate_schema


class MarketRepository:
    def __init__(self, path="data/market_data.sqlite"):
        self.path = database_path(path)
        self.connection = None
        if not self.path.is_file():
            raise PersistenceError("database_not_initialized")
        try:
            self.connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA busy_timeout=5000")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA query_only=ON")
            validate_schema(self.connection)
        except sqlite3.Error:
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
        if self.connection:
            self.connection.close()
            self.connection = None

    def _symbol(self, symbol):
        if symbol not in SYMBOLS:
            raise ValueError("Unsupported symbol.")

    def recent_prices(self, symbol, limit=10):
        self._symbol(symbol)
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Invalid query limit.")
        rows = self.connection.execute(
            "SELECT * FROM price_snapshots WHERE symbol=? ORDER BY bucket_start_ms DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return tuple(
            PriceSnapshot(
                r["symbol"],
                r["bucket_start_ms"],
                Decimal(r["price_text"]),
                r["event_time_ms"],
                r["received_at_ms"],
                r["source"],
            )
            for r in reversed(rows)
        )

    def candles(self, symbol, start_ms, end_ms):
        self._symbol(symbol)
        validate_ms(start_ms)
        validate_ms(end_ms)
        if end_ms < start_ms:
            raise ValueError("Invalid query range.")
        return tuple(
            candle_from_row(r)
            for r in self.connection.execute(
                "SELECT * FROM candles_4h WHERE symbol=? AND interval='4h' "
                "AND open_time_ms BETWEEN ? AND ? ORDER BY open_time_ms",
                (symbol, start_ms, end_ms),
            )
        )

    def last_candle(self, symbol):
        self._symbol(symbol)
        row = self.connection.execute(
            "SELECT * FROM candles_4h WHERE symbol=? AND interval='4h' "
            "ORDER BY open_time_ms DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return candle_from_row(row) if row else None

    def gaps(self, symbol=None):
        if symbol is not None:
            self._symbol(symbol)
        return tuple(
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM data_gaps WHERE (? IS NULL OR symbol=?) "
                "ORDER BY start_time_ms,gap_id",
                (symbol, symbol),
            )
        )

    def runs(self, limit=20):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("Invalid query limit.")
        rows = self.connection.execute(
            "SELECT * FROM ingestion_runs ORDER BY started_at_ms DESC,run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return tuple(dict(row) for row in reversed(rows))

    def integrity(self):
        try:
            result = [row[0] for row in self.connection.execute("PRAGMA integrity_check")]
            foreign_errors = len(self.connection.execute("PRAGMA foreign_key_check").fetchall())
        except sqlite3.Error:
            raise PersistenceError("integrity_failure") from None
        return result == ["ok"] and foreign_errors == 0

    def verify(self, as_of_ms=None):
        as_of = now_ms() if as_of_ms is None else as_of_ms
        validate_ms(as_of)
        expected_end = as_of // INTERVAL_MS * INTERVAL_MS - INTERVAL_MS
        missing, invalid = [], 0
        for symbol in SYMBOLS:
            rows = self.connection.execute(
                "SELECT * FROM candles_4h WHERE symbol=? ORDER BY open_time_ms",
                (symbol,),
            )
            expected = None
            for row in rows:
                try:
                    candle = candle_from_row(row)
                    candle.validate()
                    if candle.close_time_ms >= as_of:
                        invalid += 1
                except ValueError, TypeError, InvalidOperation:
                    invalid += 1
                    continue
                if expected is not None and candle.open_time_ms > expected:
                    missing.append(
                        dict(
                            symbol=symbol,
                            start_time_ms=expected,
                            end_time_ms=candle.open_time_ms - INTERVAL_MS,
                        )
                    )
                if expected is not None and candle.open_time_ms < expected:
                    invalid += 1
                expected = candle.open_time_ms + INTERVAL_MS
            if expected is None:
                missing.append(dict(symbol=symbol, start_time_ms=None, end_time_ms=expected_end))
            elif expected <= expected_end:
                missing.append(
                    dict(symbol=symbol, start_time_ms=expected, end_time_ms=expected_end)
                )
        for row in self.connection.execute("SELECT * FROM price_snapshots"):
            try:
                decimal_text(Decimal(row["price_text"]))
                for key in ("bucket_start_ms", "event_time_ms", "received_at_ms"):
                    validate_ms(row[key])
            except ValueError, TypeError, InvalidOperation:
                invalid += 1
        unresolved = sum(g["status"] != "RESOLVED" for g in self.gaps())
        integrity = self.integrity()
        return dict(
            sqlite_integrity="PASS" if integrity else "FAIL",
            invalid_rows=invalid,
            missing_ranges=missing,
            unresolved_gaps=unresolved,
            data_status="COMPLETE"
            if integrity and not invalid and not missing and not unresolved
            else "INCOMPLETE",
            checked_through_open_ms=expected_end,
        )

    def summary(self):
        counts = {}
        for table in (
            "price_snapshots",
            "candles_4h",
            "data_gaps",
            "ingestion_runs",
            "candle_conflicts",
        ):
            counts[table] = self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        latest = {s: (c.open_time_ms if (c := self.last_candle(s)) else None) for s in SYMBOLS}
        sources = dict(
            self.connection.execute("SELECT source,count(*) FROM candles_4h GROUP BY source")
        )
        return dict(
            schema_version=1,
            counts=counts,
            candle_sources=sources,
            latest_candle_open_ms=latest,
            latest_runs=self.runs(5),
            db_size_bytes=self.path.stat().st_size,
            wal_size_bytes=self.path.with_name(self.path.name + "-wal").stat().st_size
            if self.path.with_name(self.path.name + "-wal").exists()
            else 0,
            verification=self.verify(),
        )


def backup_database(source, destination):
    """Online SQLite Backup API, exclusive destination, integrity checked; no raw file copy."""
    destination = database_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with MarketRepository(source) as repository:
            if not repository.integrity():
                raise PersistenceError("integrity_failure")
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
            created = True
            with sqlite3.connect(destination) as target:
                repository.connection.backup(target, pages=256, sleep=0.05)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise PersistenceError("integrity_failure")
                validate_schema(target)
            # sqlite3's context manager commits but does not close the handle (Windows matters).
            target.close()
    except OSError, sqlite3.Error:
        raise PersistenceError("backup_failure") from None
    finally:
        if created and "target" in locals():
            target.close()
    return destination


def restore_database(backup, destination):
    # Same official API in the other direction; existing DB/WAL is never overwritten.
    return backup_database(backup, destination)
