"""Real temporary SQLite files; no exchange/network dependencies."""

import asyncio
import sqlite3
import threading
from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal

import pytest
from test_market_data import BASE, START, candle_payload, event, price_payload

from trading_system.config import SYMBOLS
from trading_system.market_data.state import MarketState
from trading_system.persistence.config import PersistenceConfig, database_path
from trading_system.persistence.records import INTERVAL_MS, CandleRecord, epoch_ms, utc_datetime
from trading_system.persistence.repository import (
    MarketRepository,
    backup_database,
    restore_database,
)
from trading_system.persistence.store import MarketStore, PersistenceError
from trading_system.persistence.writer import AsyncWriter


def record(symbol="BTCUSDT", start=START, source="WS_LIVE"):
    result = CandleRecord.from_ws(
        event(candle_payload(symbol, start=start, closed=True)), start + INTERVAL_MS
    )
    return replace(
        result, source=source, event_time_ms=None if source != "WS_LIVE" else result.event_time_ms
    )


def test_first_initialization_reopen_version_pragmas_and_single_writer(tmp_path):
    path = tmp_path / "market.sqlite"
    with MarketStore(path) as store:
        for pragma, expected in (
            ("user_version", 1),
            ("journal_mode", "wal"),
            ("synchronous", 2),
            ("busy_timeout", 5000),
            ("foreign_keys", 1),
        ):
            assert store.connection.execute(f"PRAGMA {pragma}").fetchone()[0] == expected
        with pytest.raises(PersistenceError, match="writer_unavailable"):
            MarketStore(path)
        store.write_batch(candles=[record()])
    with MarketStore(path) as store:
        assert store.connection.execute("SELECT count(*) FROM candles_4h").fetchone()[0] == 1
    with MarketRepository(path) as repository:
        assert repository.integrity()
        assert repository.last_candle("BTCUSDT") == record()


def test_schema_mismatch_and_unknown_version_never_reset_data(tmp_path):
    path = tmp_path / "unknown.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE user_data(value TEXT)")
        connection.execute("INSERT INTO user_data VALUES ('preserve')")
    with pytest.raises(PersistenceError, match="schema_mismatch"):
        MarketStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM user_data").fetchone()[0] == "preserve"
    other = tmp_path / "version.sqlite"
    with MarketStore(other) as store:
        store.connection.execute("PRAGMA user_version=99")
    with pytest.raises(PersistenceError, match="unsupported_schema_version"):
        MarketStore(other)


def test_price_snapshot_precision_upsert_latest_and_no_stale_relabel(tmp_path):
    path = tmp_path / "prices.sqlite"
    precision = "123.123456789012345678901234567890"
    first = event(price_payload(price=precision))
    newer = event(
        price_payload(millis=START + 1000, price="124.123456789012345678901234567890"),
        BASE + timedelta(seconds=1),
    )
    with MarketStore(path) as store:
        assert (
            store.write_batch(prices=[first], snapshot_at_ms=START)["price_snapshots_written"] == 1
        )
        assert (
            store.write_batch(prices=[newer], snapshot_at_ms=START + 1000)[
                "price_snapshots_written"
            ]
            == 1
        )
        assert (
            store.write_batch(prices=[first], snapshot_at_ms=START + 1000)[
                "price_snapshots_written"
            ]
            == 0
        )
        assert (
            store.write_batch(prices=[newer], snapshot_at_ms=START + 60000)[
                "price_snapshots_written"
            ]
            == 0
        )
        assert (
            store.write_batch(prices=[newer], snapshot_at_ms=START)["price_snapshots_written"] == 0
        )
        rows = store.connection.execute(
            "SELECT price_text,typeof(price_text) FROM price_snapshots"
        ).fetchall()
        assert len(rows) == 1 and rows[0][1] == "text"
    with MarketRepository(path) as repository:
        snapshots = repository.recent_prices("BTCUSDT")
        assert len(snapshots) == 1 and snapshots[0].price == newer.price
        assert snapshots[0].received_at_ms == START + 1000 and snapshots[0].bucket_start_ms == START


def test_utc_integer_milliseconds_without_float_rounding():
    local = BASE.astimezone(timezone(timedelta(hours=9)))
    assert epoch_ms(local) == START
    assert utc_datetime(START) == BASE
    assert epoch_ms(BASE + timedelta(microseconds=123456)) == START + 123
    with pytest.raises(ValueError):
        epoch_ms(BASE.replace(tzinfo=None))


def test_progress_rejected_and_duplicate_does_not_promote_provenance(tmp_path):
    with pytest.raises(ValueError, match="IN_PROGRESS"):
        CandleRecord.from_ws(event(candle_payload()), START + INTERVAL_MS)
    path = tmp_path / "sources.sqlite"
    bootstrap = record(source="REST_BOOTSTRAP")
    with MarketStore(path) as store:
        assert store.write_batch(candles=[bootstrap])["candles_written"] == 1
        assert store.write_batch(candles=[record()])["duplicate_candles"] == 1
        equivalent = replace(record(), open=Decimal("100.1"))
        assert store.write_batch(candles=[equivalent])["duplicate_candles"] == 1
    with MarketRepository(path) as repository:
        assert repository.last_candle("BTCUSDT") == bootstrap
        assert repository.last_candle("BTCUSDT").event_time_ms is None


def test_conflict_is_audited_not_overwritten_or_silently_resolved(tmp_path):
    path = tmp_path / "conflicts.sqlite"
    first = record()
    different = replace(first, close=Decimal("104.20"), source="REST_RECOVERY", event_time_ms=None)
    with MarketStore(path) as store:
        store.write_batch(candles=[first])
        assert store.write_batch(candles=[different])["conflicts"] == 1
        assert (
            store.write_batch(
                candles=[replace(different, ingested_at_ms=different.ingested_at_ms + 1)]
            )["conflicts"]
            == 1
        )
        assert store.connection.execute("SELECT count(*) FROM candle_conflicts").fetchone()[0] == 1
        gap_id = store.connection.execute("SELECT gap_id FROM data_gaps").fetchone()[0]
        store.set_gap_status(gap_id, "RESOLVED", "REST_RECOVERY")
    with MarketRepository(path) as repository:
        assert repository.last_candle("BTCUSDT") == first
        assert repository.gaps()[0]["status"] == "CONFLICT"
        assert repository.verify(START + INTERVAL_MS)["data_status"] == "INCOMPLETE"


def test_gaps_continuity_query_order_and_retention(tmp_path):
    path = tmp_path / "ranges.sqlite"
    with MarketStore(path) as store:
        store.write_batch(candles=[record(start=START + 2 * INTERVAL_MS), record()])
        assert store.missing_ranges("BTCUSDT", START, START + 2 * INTERVAL_MS) == [
            (START + INTERVAL_MS, START + INTERVAL_MS)
        ]
        gap_id, new = store.record_gap("BTCUSDT", START + INTERVAL_MS, START + INTERVAL_MS)
        assert new
        assert store.record_gap("BTCUSDT", START + INTERVAL_MS, START + INTERVAL_MS) == (
            gap_id,
            False,
        )
        store.write_batch(candles=[record(start=START + INTERVAL_MS)])
        assert store.missing_ranges("BTCUSDT", START, START + 2 * INTERVAL_MS) == []
        store.write_batch(prices=[event(price_payload())], snapshot_at_ms=START)
        assert store.retain_prices(START + 1) == 1
        assert store.connection.execute("SELECT count(*) FROM candles_4h").fetchone()[0] == 3
    with MarketRepository(path) as repository:
        values = repository.candles("BTCUSDT", START, START + 2 * INTERVAL_MS)
        assert [c.open_time_ms for c in values] == [
            START,
            START + INTERVAL_MS,
            START + 2 * INTERVAL_MS,
        ]
        assert (
            repository.gaps()[0]["status"] == "OPEN"
        )  # Filling alone is not corroborated recovery.


def test_transaction_rollback_on_commit_disk_failure_and_queue_not_acked(tmp_path, monkeypatch):
    async def scenario():
        market = MarketState()
        candle = event(candle_payload(closed=True))
        market.apply(candle)
        async with AsyncWriter(tmp_path / "failure.sqlite") as writer:

            def fail_commit():
                raise sqlite3.OperationalError("disk-full-fixture-sensitive-text")

            monkeypatch.setattr(writer.store, "commit", fail_commit)
            with pytest.raises(PersistenceError, match="persistence_failure"):
                await writer.flush(market, (), snapshot_at_ms=START + INTERVAL_MS)
            assert market.peek_closed() == (candle,)
            count = await writer.call(
                lambda store: store.connection.execute(
                    "SELECT count(*) FROM candles_4h"
                ).fetchone()[0]
            )
            assert count == 0

    asyncio.run(scenario())


def test_commit_before_ack_and_wrong_ack_keeps_pending(tmp_path):
    async def scenario():
        market = MarketState()
        candle = event(candle_payload(closed=True))
        market.apply(candle)
        with pytest.raises(ValueError):
            market.ack_closed((replace(candle, symbol="ETHUSDT"),))
        assert market.peek_closed() == (candle,)
        async with AsyncWriter(tmp_path / "ack.sqlite") as writer:
            stats = await writer.flush(market, (), snapshot_at_ms=START + INTERVAL_MS)
            assert stats["candles_written"] == 1 and market.peek_closed() == ()
        with MarketRepository(tmp_path / "ack.sqlite") as repository:
            assert repository.last_candle("BTCUSDT") == record()

    asyncio.run(scenario())


def test_cancelled_write_finishes_transaction_but_does_not_ack(tmp_path):
    async def scenario():
        market = MarketState()
        candle = event(candle_payload(closed=True))
        market.apply(candle)
        entered, release = threading.Event(), threading.Event()
        async with AsyncWriter(tmp_path / "cancel.sqlite") as writer:
            original = writer.store.commit

            def commit():
                entered.set()
                assert release.wait(3)
                original()

            writer.store.commit = commit
            task = asyncio.create_task(writer.flush(market, (), snapshot_at_ms=START + INTERVAL_MS))
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert market.peek_closed() == (candle,)
        with MarketRepository(tmp_path / "cancel.sqlite") as repository:
            assert repository.last_candle("BTCUSDT") is not None

    asyncio.run(scenario())


def test_run_history_reopen_and_db_deletion_preserves_journal(tmp_path):
    path = tmp_path / "history.sqlite"
    with MarketStore(path) as store:
        completed = store.start_run("test")
        store.finish_run(completed, "COMPLETED", {"messages_received": 10})
        interrupted = store.start_run("test")
    with MarketStore(path):
        pass
    with MarketRepository(path) as repository:
        runs = {r["run_id"]: r for r in repository.runs()}
        assert runs[completed]["messages_received"] == 10
        assert runs[interrupted]["status"] == "INTERRUPTED"
    path.unlink()  # Only this test-owned DB. The independent journal stays.
    with MarketStore(path):
        pass
    with MarketRepository(path) as repository:
        assert {r["run_id"] for r in repository.runs()} == {completed, interrupted}


def test_backup_online_wal_restore_integrity_and_no_overwrite(tmp_path):
    source, backup, restored = [
        tmp_path / name for name in ("source.sqlite", "backup.sqlite", "restored.sqlite")
    ]
    with MarketStore(source) as store:
        store.write_batch(candles=[record()])
        assert source.with_name(source.name + "-wal").exists()
        backup_database(source, backup)
        before = backup.read_bytes()
        with pytest.raises(PersistenceError, match="backup_failure"):
            backup_database(source, backup)
        assert backup.read_bytes() == before
    restore_database(backup, restored)
    with MarketStore(restored):
        pass
    with MarketRepository(restored) as repository:
        assert repository.integrity() and repository.last_candle("BTCUSDT") == record()


@pytest.mark.parametrize(
    "path", [":memory:", "file:data.sqlite", "//server/file.sqlite", "data.txt", "bad\nname.sqlite"]
)
def test_path_validation(path):
    with pytest.raises(ValueError):
        database_path(path)


@pytest.mark.parametrize(
    "options",
    [
        {"bootstrap_days": 0},
        {"snapshot_seconds": True},
        {"rest_retries": 3},
        {"rest_interval_seconds": 0},
        {"recovery_max_days": 1},
        {"retention_days": -1},
    ],
)
def test_configuration_bounds(options, tmp_path):
    with pytest.raises(ValueError):
        PersistenceConfig(db_path=tmp_path / "config.sqlite", **options)


def test_sql_injection_rejected_and_no_credentials_in_db_journal(tmp_path, monkeypatch):
    key, secret = "unit-test-only-api-key", "unit-test-only-api-secret"
    monkeypatch.setenv("BINANCE_API_KEY", key)
    monkeypatch.setenv("BINANCE_API_SECRET", secret)
    path = tmp_path / "public.sqlite"
    with MarketStore(path) as store:
        store.write_batch(candles=[record()])
        run = store.start_run("test")
        store.finish_run(run, "COMPLETED", {})
        with pytest.raises(ValueError):
            store.record_gap("BTCUSDT'; DROP TABLE candles_4h;--", START, START)
    with MarketRepository(path) as repository:
        with pytest.raises(ValueError):
            repository.recent_prices("BTCUSDT'; DROP TABLE candles_4h;--")
        assert repository.last_candle("BTCUSDT") is not None
    for file in tmp_path.iterdir():
        assert key.encode() not in file.read_bytes() and secret.encode() not in file.read_bytes()


def test_all_symbols_ordered_and_complete_without_interpolation(tmp_path):
    path = tmp_path / "complete.sqlite"
    with MarketStore(path) as store:
        store.write_batch(candles=[record(symbol) for symbol in SYMBOLS])
    with MarketRepository(path) as repository:
        assert repository.verify(START + INTERVAL_MS)["data_status"] == "COMPLETE"
        assert repository.verify(START + 2 * INTERVAL_MS)["data_status"] == "INCOMPLETE"
        assert len(repository.candles("BTCUSDT", START, START + INTERVAL_MS)) == 1
