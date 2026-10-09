import asyncio
import sqlite3
import threading

import pytest
from test_market_data import START, candle_payload, event
from test_persistence import record
from test_websocket import FakeSocket, monitor_fixture

from trading_system.config import SYMBOLS
from trading_system.persistence.collector import Collector
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.records import INTERVAL_MS, epoch_ms
from trading_system.persistence.repository import MarketRepository
from trading_system.persistence.writer import AsyncWriter


def successful_recovery(store, config):
    stats = store.write_batch(
        candles=[record(s, start=START - INTERVAL_MS, source="REST_BOOTSTRAP") for s in SYMBOLS]
    )
    return dict(
        stats, data_status="COMPLETE", error_category=None, gaps_detected=0, gaps_resolved=0
    )


def test_collect_restart_default_buckets_and_counters(tmp_path):
    path = tmp_path / "collect.sqlite"
    for _ in range(2):
        monitor, clock, _ = monitor_fixture()
        collector = Collector(
            PersistenceConfig(db_path=path),
            monitor=monitor,
            recovery=successful_recovery,
            clock_ms=lambda: epoch_ms(clock.utc_now()),
            tick_seconds=0.001,
        )
        result = asyncio.run(collector.run(5))
        assert result["status"] == "COMPLETED" and result["pending_closed"] == 0
        assert result["counters"]["messages_received"] > 0
    with MarketRepository(path) as repository:
        assert len(repository.runs()) == 2
        assert all(len(repository.recent_prices(symbol)) == 1 for symbol in SYMBOLS)
        assert all(len(repository.candles(s, 0, START)) == 1 for s in SYMBOLS)
        assert repository.verify(START)["data_status"] == "COMPLETE"


def test_slow_writer_does_not_block_ws_reception(tmp_path):
    monitor, clock, factory = monitor_fixture()
    # Recovery blocks the dedicated worker after WS opens, while recv keeps advancing.
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def recovery(store, config):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(3)
        return successful_recovery(store, config)

    async def scenario():
        socket = FakeSocket(clock)
        original = socket.recv

        async def paced_recv():
            await asyncio.sleep(0.001)
            return await original()

        socket.recv = paced_recv
        factory.sessions.append(socket)
        collector = Collector(
            PersistenceConfig(db_path=tmp_path / "slow.sqlite"),
            monitor=monitor,
            recovery=recovery,
            clock_ms=lambda: epoch_ms(clock.utc_now()),
            tick_seconds=0.001,
        )
        task = asyncio.create_task(collector.run(10))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        initial = monitor.messages_received
        for _ in range(10):
            await asyncio.sleep(0.002)
        assert monitor.messages_received > initial
        release.set()
        result = await task
        assert result["status"] == "COMPLETED"

    asyncio.run(scenario())


def test_collector_disk_failure_preserves_unacked_candle_and_records_failure(tmp_path):
    path = tmp_path / "disk.sqlite"
    monitor, clock, _ = monitor_fixture()
    candle = event(candle_payload(start=START - INTERVAL_MS, closed=True))
    monitor.market.apply(candle)

    class FailingWriter(AsyncWriter):
        async def flush(self, *args, **kwargs):
            original = self.store.commit

            def fail():
                raise sqlite3.OperationalError("disk-full-sensitive-fixture")

            self.store.commit = fail
            try:
                return await super().flush(*args, **kwargs)
            finally:
                self.store.commit = original

    collector = Collector(
        PersistenceConfig(db_path=path),
        monitor=monitor,
        recovery=successful_recovery,
        writer_factory=FailingWriter,
        clock_ms=lambda: epoch_ms(clock.utc_now()),
    )
    result = asyncio.run(collector.run(10))
    assert result["status"] == "PERSISTENCE_FAILURE"
    assert result["pending_closed"] == 1 and monitor.market.peek_closed() == (candle,)
    with MarketRepository(path) as repository:
        assert repository.runs()[0]["status"] == "PERSISTENCE_FAILURE"


def test_incomplete_recovery_is_not_success(tmp_path):
    monitor, clock, _ = monitor_fixture()

    def incomplete(store, config):
        return dict(
            successful_recovery(store, config),
            data_status="INCOMPLETE",
            error_category="network_timeout",
        )

    collector = Collector(
        PersistenceConfig(db_path=tmp_path / "incomplete.sqlite"),
        monitor=monitor,
        recovery=incomplete,
        clock_ms=lambda: epoch_ms(clock.utc_now()),
        tick_seconds=0.001,
    )
    result = asyncio.run(collector.run(5))
    assert result["status"] == "INCOMPLETE" and result["error_category"] == "network_timeout"


def test_recovered_ws_delivery_gap_retains_flag_and_m02_behavior(tmp_path):
    monitor, clock, _ = monitor_fixture()
    monitor.market.data_loss = True
    collector = Collector(
        PersistenceConfig(db_path=tmp_path / "recovered.sqlite"),
        monitor=monitor,
        recovery=successful_recovery,
        clock_ms=lambda: epoch_ms(clock.utc_now()),
        tick_seconds=0.001,
    )
    result = asyncio.run(collector.run(5))
    assert result["status"] == "COMPLETED"
    assert result["websocket"]["data_loss"] and not result["websocket"]["success"]
    assert result["recovery_status"] == "COMPLETE" and result["websocket"]["final_data_fresh"]


def test_collection_cancel_graceful_and_run_interrupted(tmp_path):
    async def scenario():
        monitor, clock, factory = monitor_fixture()
        factory.sessions.append(FakeSocket(clock, blocking=True))
        path = tmp_path / "cancel.sqlite"
        collector = Collector(
            PersistenceConfig(db_path=path),
            monitor=monitor,
            recovery=successful_recovery,
            clock_ms=lambda: epoch_ms(clock.utc_now()),
            tick_seconds=0.001,
        )
        task = asyncio.create_task(collector.run(600))
        while not factory.calls:
            await asyncio.sleep(0.001)
        task.cancel()
        result = await task
        assert result["status"] == "INTERRUPTED"
        assert all(socket.closed for socket in factory.sockets)
        with MarketRepository(path) as repository:
            assert repository.runs()[0]["status"] == "INTERRUPTED"

    asyncio.run(scenario())


def test_database_cli_no_account_configuration_and_secret_output(tmp_path, monkeypatch, capsys):
    from trading_system import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BINANCE_API_KEY", "unit-test-api-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "unit-test-api-secret")

    def forbidden(*args, **kwargs):
        pytest.fail("Database commands must not load account/.env configuration")

    monkeypatch.setattr(cli, "load_config", forbidden)
    assert cli.main(["db-init"]) == 0
    assert cli.main(["db-status"]) == 0
    assert cli.main(["db-verify"]) == 1  # Initialized but no bootstrap => incomplete.
    assert cli.main(["db-backup", "--backup-path", "data/backup.sqlite"]) == 0
    assert (
        cli.main(
            [
                "db-restore",
                "--backup-path",
                "data/backup.sqlite",
                "--db-path",
                "data/restored.sqlite",
            ]
        )
        == 0
    )
    assert cli.main(["db-backup", "--backup-path", "data/backup.sqlite"]) == 1
    captured = capsys.readouterr()
    text = captured.out + captured.err + (tmp_path / "logs/app.log").read_text()
    assert "unit-test-api-key" not in text and "unit-test-api-secret" not in text
    for path in (tmp_path / "data").iterdir():
        content = path.read_bytes()
        assert b"unit-test-api-key" not in content and b"unit-test-api-secret" not in content
