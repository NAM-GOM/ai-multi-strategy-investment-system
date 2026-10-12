"""SIMULATED_TEST only: real Frozen decisions/SQLite, mock Testnet, zero order calls."""

import asyncio
import json
import math
import os
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from test_collector import successful_recovery
from test_execution import NOW, TARGET
from test_execution import m04_source as m04_source
from test_observer import forward
from test_testnet import Exchange
from test_websocket import FakeSocket, monitor_fixture

from trading_system.binance.websocket import StreamConfig
from trading_system.config import SYMBOLS
from trading_system.execution.config import TestnetConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.models import Quote
from trading_system.execution.order_manager import OrderManager
from trading_system.observer.audit import source_audit
from trading_system.observer.model import FREEZE_MS
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.records import DAY_MS, INTERVAL_MS, epoch_ms, now_ms
from trading_system.persistence.store import MarketStore, PersistenceError, WriterLease
from trading_system.runtime import cli
from trading_system.runtime.bridge import PreviewBridge, ReadOnlyTestnetClient
from trading_system.runtime.collector import (
    CONTINUOUS_HORIZON,
    RuntimeCollector,
    continuous_config,
)
from trading_system.runtime.common import (
    RuntimePaths,
    StatusSink,
    atomic_json,
    disabled_environment,
    readonly_database,
)
from trading_system.runtime.observer import RuntimeObserver
from trading_system.runtime.preflight import protected_sources
from trading_system.testnet.client import TestnetError


@pytest.fixture
def runtime(tmp_path, m04_source):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "e01" / "testnet_execution.sqlite")
    for original, target in zip(m04_source, (paths.market, paths.observer), strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(original) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        source.close()
        dest.close()
    clock = [NOW]
    sinks = {
        role: StatusSink(paths, role, clock=lambda: clock[0])
        for role in ("collector", "observer", "bridge")
    }
    for role in ("collector", "observer"):
        sinks[role].publish("READY", force=True)
    exchange = Exchange()
    exchange.balances["USDT"] = Decimal("1000")

    def response(request):
        result = exchange.handler(request)
        if request.url.path == "/api/v3/account":
            return httpx.Response(
                200, json={**result.json(), "canTrade": True, "accountType": "SPOT"}
            )
        return result

    client = ReadOnlyTestnetClient(
        TestnetConfig("test-key", "test-secret"), transport=httpx.MockTransport(response)
    )
    store = ExecutionStore(paths.execution)
    engine = OrderManager(client, store, clock=lambda: clock[0])
    engine.reconcile()
    # An existing manual verification record is unowned and never allocated by M05.
    store.db.execute(
        "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "manual-baseline",
            engine.sid,
            NOW - 10000,
            "BTCUSDT",
            "BUY",
            "0.00009000",
            "83091.56",
            "7.47824040",
            "FILLED",
            NOW - 10000,
            NOW - 10000,
        ),
    )
    quote = Quote("SOLUSDT", Decimal("1000"), Decimal("1000"), NOW, 1)
    bridge = PreviewBridge(paths, sinks["bridge"], clock=lambda: clock[0])
    # Simulate a persisted preview watermark taken just before the last mock 4H close.
    with readonly_database(paths.observer) as db:
        point = {
            "observer_path": str(paths.observer),
            "market_path": str(paths.market),
            "execution_path": str(paths.execution),
            "activated_ms": NOW - 2000,
            "last_rowid": 108,
            "first_hash": db.execute(
                "SELECT decision_hash FROM signal_decisions WHERE rowid=1"
            ).fetchone()[0],
            "anchor_hash": db.execute(
                "SELECT decision_hash FROM signal_decisions WHERE rowid=108"
            ).fetchone()[0],
        }
    atomic_json(bridge.cursor_path, point)
    yield paths, clock, sinks, exchange, client, store, engine, quote, bridge
    client.close()
    store.close()
    for sink in sinks.values():
        sink.close()


def preview(runtime, *, capital="1000", online=False):
    _, _, _, exchange, client, _, _, quote, bridge = runtime
    return bridge.cycle(
        client,
        online=online,
        quotes={"SOLUSDT": quote},
        info=exchange.info,
        balances=[
            {"asset": a, "free": str(v), "locked": "0"} for a, v in exchange.balances.items()
        ],
        capital=capital,
    )


def ledger_dump(path):
    with readonly_database(path) as db:
        return list(db.iterdump())


def test_preview_nine_decisions_risk_and_ledger_preservation(runtime):
    paths, _, _, exchange, _, store, _, _, _ = runtime
    before = ledger_dump(paths.execution), ledger_dump(paths.observer), ledger_dump(paths.market)
    result = preview(runtime)
    assert result["classification"] == "SIMULATED_TEST"
    assert result["execution_enabled"] is False and result["order_calls"] == 0
    assert len(result["validations"]) == len(result["signals"]) == 9
    assert {v["validation"] for v in result["validations"]} == {"VALIDATED"}
    assert len([v for v in result["validations"] if v["policy"] == "SHADOW_SIGNAL_ONLY"]) == 6
    approved = [s for s in result["signals"] if s["state"] == "DRY_RUN_APPROVED"]
    assert len(approved) == 1 and Decimal(approved[0]["notional"]) <= 20
    assert before == (
        ledger_dump(paths.execution),
        ledger_dump(paths.observer),
        ledger_dump(paths.market),
    )
    assert store.rows("SELECT * FROM router_checkpoints") == []
    assert store.rows("SELECT * FROM signal_receipts") == []
    assert store.rows("SELECT * FROM strategy_allocations") == []
    assert exchange.post_count == 0


def test_without_allocation_candidate_is_blocked_but_no_action_is_validated(runtime):
    result = preview(runtime, capital=None)
    assert result["classification"] == "OBSERVATION_PREVIEW"
    assert "STRATEGY_ALLOCATION_REQUIRED" in {s["state"] for s in result["signals"]}
    assert any(
        v["decision"] == "NO_ACTION" and v["validation"] == "VALIDATED"
        for v in result["validations"]
    )
    assert not any(s["state"] == "DRY_RUN_APPROVED" for s in result["signals"])


def test_preview_restart_and_original_router_checkpoint_unchanged(runtime):
    paths, clock, sinks, _, client, store, engine, _, _ = runtime
    store.db.execute(
        "INSERT INTO router_checkpoints VALUES(?,?,?,?,?)",
        (engine.sid, str(paths.observer), str(paths.market), NOW - 2000, 108),
    )
    original = store.rows("SELECT * FROM router_checkpoints")
    preview(runtime)
    restart = PreviewBridge(paths, sinks["bridge"], clock=lambda: clock[0])
    assert restart.cycle(client)["signals"] == []
    assert store.rows("SELECT * FROM router_checkpoints") == original
    assert restart.point(clock[0])["last_rowid"] == 117


def test_new_preview_start_skips_all_existing_signals(runtime):
    _, clock, _, _, client, _, _, _, bridge = runtime
    bridge.cursor_path.unlink()
    assert bridge.point(clock[0])["last_rowid"] == 117
    assert bridge.cycle(client)["signals"] == []


@pytest.mark.parametrize("role", ["collector", "observer"])
@pytest.mark.parametrize(
    "state,age", [("STOPPED", 0), ("HOLD", 0), ("READY", 30001), ("READY", -1)]
)
def test_failed_or_stale_heartbeat_blocks_preview(runtime, role, state, age):
    paths, clock, sinks, _, _, _, _, _, bridge = runtime
    sinks[role].publish(state, force=True)
    record = json.loads(paths.health(role).read_text())
    record["timestamp_ms"] = clock[0] - age
    atomic_json(paths.health(role), record)
    before = bridge.cursor_path.read_bytes()
    with pytest.raises(TestnetError, match=role.upper() + "_HEARTBEAT_HOLD"):
        preview(runtime)
    assert bridge.cursor_path.read_bytes() == before


@pytest.mark.parametrize("gate", ["kill", "hold", "unknown"])
def test_execution_uncertainty_blocks_all_routes(runtime, gate):
    paths, _, _, exchange, _, store, _, _, bridge = runtime
    if gate == "unknown":
        store.db.execute("UPDATE order_intents SET state='SUBMITTING'")
    elif gate == "kill":
        store.db.execute("UPDATE testnet_sessions SET kill=1")
    else:
        store.db.execute("UPDATE testnet_sessions SET hold='RECONCILIATION_MISMATCH'")
    before = ledger_dump(paths.execution), bridge.cursor_path.read_bytes()
    with pytest.raises(TestnetError, match="EXECUTION_HOLD_KILL_OR_UNKNOWN"):
        preview(runtime)
    assert before == (ledger_dump(paths.execution), bridge.cursor_path.read_bytes())
    assert exchange.post_count == 0


def test_stale_or_rest_signal_is_never_promoted(runtime):
    _, clock, sinks, _, _, _, _, _, _ = runtime
    clock[0] += 60001
    for role in ("collector", "observer"):
        sinks[role].publish("READY", force=True)
    result = preview(runtime)
    assert {v["validation"] for v in result["validations"]} == {"STALE_OR_UNCONFIRMED_SIGNAL"}
    assert not any(r["state"] == "DRY_RUN_APPROVED" for r in result["signals"])


def test_dependency_restart_during_routing_keeps_preview_cursor(runtime, monkeypatch):
    _, _, sinks, _, _, _, _, _, bridge = runtime
    from trading_system.execution.signal_router import SignalRouter

    original = SignalRouter.route

    def restarted(*args, **kwargs):
        result = original(*args, **kwargs)
        sinks["collector"].instance = "replacement-process"
        sinks["collector"].publish("READY", force=True)
        return result

    monkeypatch.setattr(SignalRouter, "route", restarted)
    before = bridge.cursor_path.read_bytes()
    with pytest.raises(TestnetError, match="DEPENDENCY_RESTART_UNCERTAINTY"):
        preview(runtime)
    assert bridge.cursor_path.read_bytes() == before


def test_online_mock_reconcile_is_read_only_and_preserves_manual_ledger(runtime):
    paths, _, _, exchange, _, _, _, _, _ = runtime
    # The mock exchange does not contain the seeded manual fill. Offline preservation
    # remains checked above; an online mismatch must fail closed without repairing it.
    before = ledger_dump(paths.execution)
    with pytest.raises(TestnetError):
        preview(runtime, capital=None, online=True)
    assert ledger_dump(paths.execution) == before and exchange.post_count == 0


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT"])
def test_read_only_client_blocks_mutations_at_call_and_http_boundary(runtime, method):
    _, _, _, exchange, client, *_ = runtime
    with pytest.raises(TestnetError, match="PREVIEW_MUTATION_DENIED"):
        client.request(method, "/api/v3/order", confirm=True)
    with pytest.raises(TestnetError, match="PREVIEW_MUTATION_DENIED"):
        client.read_only_boundary(
            httpx.Request(method, "https://testnet.binance.vision/api/v3/order")
        )
    assert exchange.post_count == 0


@pytest.mark.parametrize(
    "variable", ["BINANCE_TESTNET_TRADING_ENABLED", "BINANCE_TESTNET_AUTOMATED_ENABLED"]
)
def test_environment_unlock_is_rejected(monkeypatch, variable):
    monkeypatch.setenv(variable, "YES_TESTNET_ONLY")
    with pytest.raises(TestnetError, match="RUNTIME_EXECUTION_UNLOCK_DENIED"):
        disabled_environment()


def test_paths_reject_protected_directory_and_hardlink_collision(tmp_path):
    with pytest.raises(TestnetError, match="PROTECTED_VALIDATION_PATH"):
        RuntimePaths(tmp_path / "close-validation-01", tmp_path / "testnet_execution.sqlite")
    paths = RuntimePaths(tmp_path / "c", tmp_path / "e" / "testnet_execution.sqlite")
    paths.market.parent.mkdir(parents=True)
    paths.execution.parent.mkdir(parents=True)
    paths.market.touch()
    os.link(paths.market, paths.execution)
    with pytest.raises(TestnetError, match="DATABASE_PATH_COLLISION"):
        RuntimePaths(paths.root, paths.execution)


def test_source_manifest_and_continuity_bootstrap():
    assert protected_sources()["protected_files"] == 72
    config = continuous_config(Path("/tmp/mock-market.sqlite"), FREEZE_MS + 10 * DAY_MS)
    assert config.bootstrap_days >= 11 and config.snapshot_seconds == 10
    assert math.isfinite(CONTINUOUS_HORIZON) and CONTINUOUS_HORIZON > 100 * 365 * 86400


def test_collector_one_session_spans_24h_and_stops_gracefully(tmp_path):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "testnet_execution.sqlite")
    monitor, clock, factory = monitor_fixture(
        StreamConfig(
            price_stale_after=100_000, candle_stale_after=100_000, stale_reconnect_after=100_000
        )
    )
    sink = StatusSink(paths, "collector", clock=lambda: epoch_ms(clock.utc_now()))

    async def scenario():
        stop = asyncio.Event()
        for _ in range(3):
            socket = FakeSocket(clock, step=3600)
            original = socket.recv

            async def receive(recv=original):
                value = await recv()
                if clock.now > 25 * 3600:
                    stop.set()
                return value

            socket.recv = receive
            factory.sessions.append(socket)
        collector = RuntimeCollector(
            PersistenceConfig(db_path=paths.market),
            sink,
            monitor=monitor,
            recovery=successful_recovery,
            clock_ms=lambda: epoch_ms(clock.utc_now()),
            tick_seconds=0.001,
        )
        await collector.serve(stop)
        assert clock.now > 24 * 3600 and monitor.reconnect_count >= 1
        with readonly_database(paths.market) as db:
            assert db.execute("SELECT count(*) FROM ingestion_runs").fetchone()[0] == 1

    try:
        asyncio.run(asyncio.wait_for(scenario(), timeout=10))
    finally:
        sink.close()


def test_observer_writer_lease_and_checkpoint_restart(runtime):
    paths, clock, sinks, *_ = runtime
    service = RuntimeObserver(
        paths, sinks["observer"], clock=lambda: clock[0], audit=source_audit()
    )
    try:
        assert service.target == TARGET + INTERVAL_MS
        assert service.tick()["state"] == "WAITING_NEXT_4H_BAR"
        with pytest.raises(PersistenceError, match="writer_unavailable"):
            RuntimeObserver(paths, sinks["observer"], clock=lambda: clock[0], audit=source_audit())
        before = ledger_dump(paths.observer)
        with readonly_database(paths.observer) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert db.execute("SELECT count(*) FROM signal_decisions").fetchone()[0] == 117
        assert before == ledger_dump(paths.observer)
    finally:
        service.close()
    restart = RuntimeObserver(
        paths, sinks["observer"], clock=lambda: clock[0] + 1000, audit=source_audit()
    )
    assert restart.target == TARGET + INTERVAL_MS
    restart.close()


def test_writer_lease_releases_after_real_process_crash(tmp_path):
    target = tmp_path / "service"
    code = (
        "from trading_system.persistence.store import WriterLease\n"
        "from pathlib import Path\nimport sys,time\n"
        "lock=WriterLease(Path(sys.argv[1]))\n"
        "print('LOCKED',flush=True)\ntime.sleep(30)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(target)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert process.stdout.readline().strip() == "LOCKED"
        with pytest.raises(PersistenceError):
            WriterLease(target)
        process.kill()
        process.wait(timeout=10)
        lease = WriterLease(target)
        lease.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def test_cli_offline_preflight_and_no_activation_options(capsys):
    assert cli.main(["preflight"]) == 0
    assert json.loads(capsys.readouterr().out)["network_requests"] == 0
    with pytest.raises(SystemExit):
        cli.main(["bridge", "--confirm-automated-testnet"])


def test_observer_catchup_keeps_every_nine_decision_batch_and_restart_provenance(tmp_path):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "testnet_execution.sqlite")
    clock = [FREEZE_MS + 1000]
    sinks = {r: StatusSink(paths, r, clock=lambda: clock[0]) for r in ("collector", "observer")}
    with MarketStore(paths.market):
        pass
    service = RuntimeObserver(
        paths, sinks["observer"], clock=lambda: clock[0], audit=source_audit()
    )
    try:
        with MarketStore(paths.market) as writer:
            writer.write_batch(candles=[forward(s) for s in SYMBOLS])
        clock[0] = FREEZE_MS + INTERVAL_MS + 1000
        sinks["collector"].publish("READY", force=True)
        assert service.tick()["modes"] == ["LIVE_OBSERVATION"]
        service.close()
        # Two bars arrive while the observer process is stopped.
        with MarketStore(paths.market) as writer:
            writer.write_batch(
                candles=[forward(s, FREEZE_MS + i * INTERVAL_MS) for i in (1, 2) for s in SYMBOLS]
            )
        clock[0] = FREEZE_MS + 3 * INTERVAL_MS + 1000
        sinks["collector"].publish("READY", force=True)
        service = RuntimeObserver(
            paths, sinks["observer"], clock=lambda: clock[0], audit=source_audit()
        )
        for _ in range(2):
            assert service.tick()["modes"] == ["PRELAUNCH_STATE_BACKFILL"]
        assert service.target == FREEZE_MS + 3 * INTERVAL_MS
        assert service.store.db.execute("SELECT count(*) FROM signal_decisions").fetchone()[0] == 27
        assert (
            service.store.db.execute(
                "SELECT count(*) FROM evaluation_batches WHERE status='COMMITTED'"
            ).fetchone()[0]
            == 3
        )
    finally:
        service.close()
        for sink in sinks.values():
            sink.close()


def test_missing_candle_hold_recovery_is_not_new_live_signal(tmp_path):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "testnet_execution.sqlite")
    clock = [FREEZE_MS + 1000]
    collector = StatusSink(paths, "collector", clock=lambda: clock[0])
    sink = StatusSink(paths, "observer", clock=lambda: clock[0])
    with MarketStore(paths.market):
        pass
    service = RuntimeObserver(paths, sink, clock=lambda: clock[0], audit=source_audit())
    try:
        clock[0] = FREEZE_MS + INTERVAL_MS + 1000
        collector.publish("READY", force=True)
        assert service.tick()["state"] == "DATA_HOLD"
        assert service.store.db.execute("SELECT count(*) FROM signal_decisions").fetchone()[0] == 0
        floor = service.store.db.execute("SELECT live_floor_ms FROM observer_runs").fetchone()[0]
        assert floor == clock[0]
        with MarketStore(paths.market) as writer:
            writer.write_batch(candles=[forward(s, source="REST_RECOVERY") for s in SYMBOLS])
        clock[0] += 1000
        assert service.tick()["modes"] == ["PRELAUNCH_STATE_BACKFILL"]
        assert service.store.db.execute("SELECT count(*) FROM signal_decisions").fetchone()[0] == 9
    finally:
        service.close()
        collector.close()
        sink.close()


def test_sqlite_locked_write_does_not_move_observer_checkpoint(runtime):
    paths, clock, sinks, *_ = runtime
    service = RuntimeObserver(
        paths, sinks["observer"], clock=lambda: clock[0], audit=source_audit()
    )
    locker = sqlite3.connect(paths.observer)
    try:
        before = service.target
        service.store.db.execute("PRAGMA busy_timeout=1")
        locker.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError):
            service.tick()
        assert service.target == before
    finally:
        locker.rollback()
        locker.close()
        service.close()


def test_online_read_only_mock_success_no_allocation_or_order_calls(runtime):
    paths, _, _, exchange, _, store, _, _, _ = runtime
    # Expendable fixture only: an empty reconciled Testnet account has no baseline intent.
    store.db.execute("DELETE FROM order_intents")
    before = ledger_dump(paths.execution)
    result = preview(runtime, capital=None, online=True)
    assert result["mode"] == "READ_ONLY_TESTNET_CONNECTED"
    assert result["account_identity"] == "READ_ONLY_RECONCILED_COPY"
    assert {request.method for request in exchange.requests} == {"GET"}
    assert exchange.post_count == 0 and before == ledger_dump(paths.execution)


def test_preview_offline_does_not_require_bound_account_key(runtime):
    paths, _, _, _, _, _, _, _, bridge = runtime
    client = ReadOnlyTestnetClient(TestnetConfig(), transport=httpx.MockTransport(lambda r: None))
    before = ledger_dump(paths.execution)
    try:
        result = bridge.cycle(client)
        assert result["account_identity"] == "NOT_VERIFIED_OFFLINE"
        assert before == ledger_dump(paths.execution)
    finally:
        client.close()


def test_rate_limit_failure_keeps_ledger_and_preview_watermark(runtime):
    paths, _, _, _, _, store, _, _, bridge = runtime
    store.db.execute("DELETE FROM order_intents")
    client = ReadOnlyTestnetClient(
        TestnetConfig("test-key", "test-secret"),
        transport=httpx.MockTransport(lambda r: httpx.Response(429, json={"code": -1003})),
    )
    before = ledger_dump(paths.execution), bridge.cursor_path.read_bytes()
    try:
        with pytest.raises(TestnetError, match="RATE_LIMIT"):
            bridge.cycle(client, online=True, quotes={})
        assert before == (ledger_dump(paths.execution), bridge.cursor_path.read_bytes())
    finally:
        client.close()


def test_cli_duplicate_role_does_not_overwrite_active_heartbeat(runtime):
    paths, *_ = runtime
    lease = WriterLease(paths.role_dir("bridge") / "service")
    before = paths.health("bridge").read_bytes() if paths.health("bridge").exists() else None
    try:
        assert (
            cli.main(
                [
                    "bridge",
                    "--state-root",
                    str(paths.root),
                    "--execution-db",
                    str(paths.execution),
                    "--once",
                ]
            )
            == 78
        )
        after = paths.health("bridge").read_bytes() if paths.health("bridge").exists() else None
        assert before == after
    finally:
        lease.close()


def test_new_cli_process_preserves_preview_cursor_and_real_order_ledger(runtime):
    paths, _, _, _, _, _, _, _, bridge = runtime
    # Only fixture health uses the process wall clock. Mock source candles remain
    # old and must be reported stale, never presented as real live validation.
    for role in ("collector", "observer"):
        health = json.loads(paths.health(role).read_text())
        health["timestamp_ms"] = now_ms()
        atomic_json(paths.health(role), health)
    before = ledger_dump(paths.execution)
    command = [
        sys.executable,
        "-m",
        "trading_system.runtime.cli",
        "bridge",
        "--once",
        "--state-root",
        str(paths.root),
        "--execution-db",
        str(paths.execution),
        "--assumed-capital",
        "1000",
    ]
    for attempt in range(2):
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stdout + completed.stderr
        report = json.loads((paths.role_dir("bridge") / "latest-preview.json").read_text())
        assert report["classification"] == "SIMULATED_TEST" and report["order_calls"] == 0
        if attempt == 0:
            assert len(report["signals"]) == 9
            assert {r["state"] for r in report["signals"]} == {"STALE_OR_UNCONFIRMED_SIGNAL"}
        else:
            assert report["signals"] == []
        assert ledger_dump(paths.execution) == before
    assert json.loads(bridge.cursor_path.read_text())["last_rowid"] == 117


def test_reconciliation_hold_survives_new_preview_instance(runtime):
    paths, clock, sinks, _, client, _, _, _, bridge = runtime
    bridge.latch("RESET_OR_BALANCE_MISMATCH")
    before = bridge.cursor_path.read_bytes(), ledger_dump(paths.execution)
    restart = PreviewBridge(paths, sinks["bridge"], clock=lambda: clock[0])
    with pytest.raises(TestnetError, match="PREVIEW_PERSISTENT_HOLD"):
        restart.cycle(client)
    assert json.loads(bridge.hold_path.read_text())["category"] == "RESET_OR_BALANCE_MISMATCH"
    assert before == (bridge.cursor_path.read_bytes(), ledger_dump(paths.execution))


def test_invalid_decision_hash_latches_before_preview_checkpoint_moves(runtime):
    paths, _, _, exchange, _, _, _, _, bridge = runtime
    # Corrupt only the isolated simulated fixture, never the real Observer/source.
    with sqlite3.connect(paths.observer) as db:
        db.execute("DROP TRIGGER immutable_signal_decisions_UPDATE")
        db.execute(
            "UPDATE signal_decisions SET input_hash='corrupt' WHERE bar_open_ms=?", (TARGET,)
        )
    before = bridge.cursor_path.read_bytes()
    with pytest.raises(TestnetError, match="SIGNAL_HASH_MISMATCH"):
        preview(runtime)
    assert json.loads(bridge.hold_path.read_text())["category"] == "SIGNAL_HASH_MISMATCH"
    assert before == bridge.cursor_path.read_bytes() and exchange.post_count == 0


def test_online_preview_cannot_resolve_real_journal_unknown_in_temporary_copy(runtime):
    paths, _, _, exchange, _, store, _, _, bridge = runtime
    store.db.execute("UPDATE order_intents SET state='SUBMITTING'")
    before = ledger_dump(paths.execution), bridge.cursor_path.read_bytes()
    request_count = len(exchange.requests)
    with pytest.raises(TestnetError, match="EXECUTION_HOLD_KILL_OR_UNKNOWN"):
        preview(runtime, online=True, capital=None)
    assert len(exchange.requests) == request_count
    assert before == (ledger_dump(paths.execution), bridge.cursor_path.read_bytes())
