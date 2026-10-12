"""SIMULATED_TEST: GET-only ongoing account snapshots; original journal never changes."""

import json
import sqlite3
import time

import httpx
import pytest
from test_testnet import Exchange

from trading_system.execution.config import TestnetConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.order_manager import OrderManager
from trading_system.runtime.account_sync import AccountSync, main
from trading_system.runtime.bridge import ReadOnlyTestnetClient
from trading_system.runtime.common import RuntimePaths, StatusSink, readonly_database
from trading_system.testnet.client import TestnetError


@pytest.fixture
def account(tmp_path):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "e01" / "testnet_execution.sqlite")
    clock = [1791726852000]
    exchange = Exchange()

    def handler(request):
        response = exchange.handler(request)
        if request.url.path == "/api/v3/account":
            return httpx.Response(
                200, json={**response.json(), "canTrade": True, "accountType": "SPOT"}
            )
        return response

    client = ReadOnlyTestnetClient(
        TestnetConfig("test-key", "test-secret"), transport=httpx.MockTransport(handler)
    )
    store = ExecutionStore(paths.execution)
    engine = OrderManager(client, store, clock=lambda: clock[0])
    engine.reconcile()
    sink = StatusSink(paths, "account", clock=lambda: clock[0])
    service = AccountSync(paths, client, sink, clock=lambda: clock[0])
    yield paths, clock, exchange, client, sink, service, store
    service.close()
    store.close()
    client.close()
    sink.close()


def dump(path):
    with readonly_database(path) as db:
        return list(db.iterdump())


def test_fresh_account_snapshots_do_not_write_the_original_journal_or_consume_signals(account):
    paths, clock, exchange, _, _, service, store = account
    before = dump(paths.execution)
    for _ in range(2):
        clock[0] += 30000
        report = service.cycle()
        assert report["balance_timestamp_ms"] == clock[0]
        assert report["order_calls"] == 0 and report["execution_enabled"] is False
        assert json.loads(service.snapshot_path.read_text())["balances"] == report["balances"]
        assert dump(paths.execution) == before
    assert store.rows("SELECT count(DISTINCT snapshot_id) AS n FROM balance_snapshots")[0]["n"] == 1
    assert exchange.post_count == 0 and {r.method for r in exchange.requests} == {"GET"}


def test_existing_kill_switch_is_preserved_while_read_only_balances_refresh(account):
    paths, clock, _, _, _, service, store = account
    store.kill(store.session()["id"], clock[0], True)
    before = dump(paths.execution)
    clock[0] += 30000
    assert service.cycle()["kill_preserved"] is True
    assert dump(paths.execution) == before


def test_unexplained_account_change_latches_without_replacing_last_good_snapshot(account):
    paths, clock, exchange, _, _, service, _ = account
    service.cycle()
    previous = dump(paths.execution), service.snapshot_path.read_bytes()
    exchange.balances["USDT"] += 1
    clock[0] += 30000
    with pytest.raises(TestnetError, match="RESET_OR_BALANCE_MISMATCH"):
        service.cycle()
    assert previous == (dump(paths.execution), service.snapshot_path.read_bytes())
    with pytest.raises(TestnetError, match="ACCOUNT_RECONCILIATION_REVIEW_REQUIRED"):
        service.cycle()
    assert json.loads(service.hold_path.read_text())["category"] == "RESET_OR_BALANCE_MISMATCH"


def test_missing_journal_is_not_created_and_offline_cli_never_creates_it(tmp_path, capsys):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "testnet_execution.sqlite")
    client = ReadOnlyTestnetClient(TestnetConfig(), transport=httpx.MockTransport(lambda r: None))
    sink = StatusSink(paths, "account")
    try:
        with pytest.raises(TestnetError, match="INPUT_DB_MISSING"):
            AccountSync(paths, client, sink)
        assert not paths.execution.exists()
        assert main(["--execution-db", str(paths.execution)]) == 0
        assert not paths.execution.exists()
        assert "NO_NETWORK_NO_JOURNAL_WRITE" in capsys.readouterr().out
    finally:
        client.close()
        sink.close()


def test_rate_limit_retains_backoff_and_last_good_snapshot(account):
    paths, _, _, client, _, service, _ = account
    service.cycle()
    previous = dump(paths.execution), service.snapshot_path.read_bytes()
    client._http.close()
    client._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(429, headers={"Retry-After": "180"}, json={"code": -1003})
        )
    )
    with pytest.raises(TestnetError, match="RATE_LIMIT_HOLD"):
        service.cycle()
    assert client.blocked_until - time.monotonic() > 175
    assert previous == (dump(paths.execution), service.snapshot_path.read_bytes())
    assert not service.hold_path.exists()


def test_second_account_snapshot_writer_is_refused(account):
    paths, _, _, client, sink, _, _ = account
    from trading_system.persistence.store import PersistenceError

    with pytest.raises(PersistenceError, match="writer_unavailable"):
        AccountSync(paths, client, sink)


def test_unknown_real_execution_stops_before_exchange_requests(account):
    paths, clock, exchange, _, _, service, store = account
    store.db.execute(
        "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "manual-unknown",
            store.session()["id"],
            clock[0],
            "BTCUSDT",
            "BUY",
            "0.00009",
            "83091.56",
            "7.47824040",
            "UNKNOWN_EXECUTION",
            clock[0],
            clock[0],
        ),
    )
    before, count = dump(paths.execution), len(exchange.requests)
    with pytest.raises(TestnetError, match="UNKNOWN_EXECUTION_REVIEW_REQUIRED"):
        service.cycle()
    assert len(exchange.requests) == count and dump(paths.execution) == before


def test_manual_history_is_not_reclassified_or_overwritten(account):
    paths, clock, _, _, _, service, store = account
    store.db.execute(
        "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "manual-unattempted",
            store.session()["id"],
            clock[0],
            "BTCUSDT",
            "BUY",
            "0.00009",
            "83091.56",
            "7.47824040",
            "INTENT_CREATED",
            None,
            None,
        ),
    )
    previous = dump(paths.execution)
    service.cycle()
    assert previous == dump(paths.execution)
    assert store.rows("SELECT * FROM position_fills") == []


def test_foreign_journal_is_not_initialized(tmp_path):
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "testnet_execution.sqlite")
    with sqlite3.connect(paths.execution) as db:
        db.execute("CREATE TABLE foreign_table(secret TEXT)")
    client = ReadOnlyTestnetClient(TestnetConfig(), transport=httpx.MockTransport(lambda r: None))
    sink = StatusSink(paths, "account")
    try:
        with pytest.raises(sqlite3.OperationalError):
            AccountSync(paths, client, sink)
        with sqlite3.connect(paths.execution) as db:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            assert tables == [("foreign_table",)]
    finally:
        client.close()
        sink.close()
