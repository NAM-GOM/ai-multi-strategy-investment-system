"""SIMULATED_TEST only: actual Frozen calculations, SQLite and E01, MockTransport orders."""

import sqlite3
from decimal import Decimal

import httpx
import pytest
from test_execution import NOW, TARGET, m04_source  # noqa: F401
from test_testnet import Exchange

from trading_system.automation.control import Control
from trading_system.automation.executor import Executor
from trading_system.automation.gates import gate_evidence
from trading_system.automation.policy import AutomationRisk, notional_guard
from trading_system.automation.preflight import frozen_sources, online_readonly, operator_review
from trading_system.execution.config import T1, TestnetConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.models import Quote
from trading_system.execution.order_manager import OrderManager
from trading_system.execution.testnet_client import TestnetExecutionClient
from trading_system.observer.audit import source_audit
from trading_system.observer.model import digest
from trading_system.observer.service import BatchProcessor
from trading_system.observer.store import ObserverStore
from trading_system.persistence.records import INTERVAL_MS, CandleRecord
from trading_system.persistence.store import MarketStore, PersistenceError
from trading_system.runtime.common import RuntimePaths, atomic_json, boot_id
from trading_system.testnet.client import TestnetError


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("E02 offline tests must never reach the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr("trading_system.execution.testnet_client.FixedTestnetConnect", deny)


def copy_sqlite(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    a, b = sqlite3.connect(source), sqlite3.connect(target)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()


def health(paths, clock, *, role=None, state="READY", instance="mock"):
    for r in [role] if role else ["collector", "observer"]:
        atomic_json(
            paths.health(r),
            {
                "role": r,
                "state": state,
                "boot_id": boot_id(),
                "timestamp_ms": clock[0],
                "instance": instance + r,
            },
        )


@pytest.fixture
def runtime(tmp_path, m04_source):  # noqa: F811
    paths = RuntimePaths(tmp_path / "continuous", tmp_path / "e01/testnet_execution.sqlite")
    for source, target in zip(m04_source, (paths.market, paths.observer), strict=True):
        copy_sqlite(source, target)
    exchange = Exchange()
    exchange.balances["USDT"] = Decimal("2000")
    btc = exchange.info["symbols"][0]
    btc["filters"][0].update(minQty="0.000001", stepSize="0.000001")
    original_handler = exchange.handler

    def handler(request):
        response = original_handler(request)
        if request.url.path == "/api/v3/account":
            return httpx.Response(
                200, json={**response.json(), "canTrade": True, "accountType": "SPOT"}
            )
        if request.method == "POST" and request.url.path == "/api/v3/order":
            cid = request.url.params["newClientOrderId"]
            if (
                exchange.orders[cid]["symbol"] == "BTCUSDT"
                and exchange.orders[cid]["price"] == "83091.56"
            ):
                exchange.orders[cid]["orderId"] = 1507111
                return httpx.Response(200, json=exchange.orders[cid])
        return response

    clock = [NOW]
    prices = {s: Decimal("1000") for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}

    def quote(s):
        return Quote(s, prices[s], prices[s], clock[0], 1)

    client = TestnetExecutionClient(
        TestnetConfig("test-key", "test-secret", True), transport=httpx.MockTransport(handler)
    )
    paths.execution.parent.mkdir(parents=True)
    store = ExecutionStore(paths.execution)
    manager = OrderManager(client, store, clock=lambda: clock[0], quote_provider=quote)
    manager.reconcile()
    cid = manager.create("BTCUSDT", "BUY", "0.00009", "83091.56")
    manager.check(cid, confirm_test=True)
    manager.submit(cid, confirm_order=True, approval_token=manager.review(cid)["approval_token"])
    exchange.fill(cid, "0.00009")
    manager.reconcile()
    legacy = store.rows("SELECT * FROM execution_gates WHERE gate IN ('B','C')")
    # Explicitly simulated startup before the module fixture's final live candle.
    with store.transaction():
        store.db.execute(
            "INSERT INTO router_checkpoints VALUES(?,?,?,?,?)",
            (manager.sid, str(paths.observer), str(paths.market), TARGET + INTERVAL_MS - 1000, 108),
        )
    store.close()
    health(paths, clock)
    acceptance = tmp_path / "operator-acceptance.json"
    atomic_json(
        acceptance,
        {
            "status": "PASS",
            "classification": "ACTUAL_NUC",
            "base_sha": "3e37b0b81b05906e1cee858671f67a4c5a719566",
            "market_path": str(paths.market),
            "observer_path": str(paths.observer),
            "execution_path": str(paths.execution),
            "approved_by": "SIMULATED_TEST_FIXTURE",
            "evidence_references": ["not real evidence: isolated test fixture only"],
            "tests": {f"TEST-{n:02d}": "PASS" for n in range(2, 8)},
        },
    )
    service = Executor(
        paths,
        tmp_path / "executor",
        client,
        quote,
        acceptance_path=acceptance,
        clock=lambda: clock[0],
        host_checks=False,
    )
    yield service, exchange, clock, prices, legacy, acceptance, handler
    service.close()
    client.close()


def command(service, name, **values):
    return service.execute_command(
        {"command": name, "token": values.get("token"), "client_id": values.get("client_id")}
    )


def prepare(runtime):
    service, *_ = runtime
    command(service, "allocate")
    proof = command(service, "phase-a")
    assert proof["state"] == "E02_PHASE_A_VERIFIED"
    assert proof["reports"] and all(
        Decimal(r["notional"]) <= Decimal("8.31")
        for r in proof["reports"]
        if r["state"] == "DRY_RUN_APPROVED"
    )
    return digest(service.evidence())


def activate(runtime):
    service, *_ = runtime
    return command(service, "on", token=prepare(runtime))


def next_bar(runtime):
    service, _, clock, prices, *_ = runtime
    bar = TARGET + INTERVAL_MS
    clock[0] = bar + INTERVAL_MS + 1000
    prices.update(BTCUSDT=Decimal("1000000"), ETHUSDT=Decimal("1"), SOLUSDT=Decimal("1"))
    with MarketStore(service.paths.market) as market:
        market.write_batch(
            candles=[
                CandleRecord(
                    s,
                    "4h",
                    bar,
                    bar + INTERVAL_MS - 1,
                    v,
                    v + Decimal(".01"),
                    v - Decimal(".01"),
                    v,
                    Decimal(50),
                    clock[0] - 990,
                    clock[0] - 980,
                    "WS_LIVE",
                )
                for s, v in prices.items()
            ]
        )
        for s, v in prices.items():
            market.connection.execute(
                "INSERT INTO price_snapshots VALUES(?,?,?,?,?,?)",
                (s, clock[0] - clock[0] % 60000, str(v), clock[0], clock[0], "binance_spot"),
            )
        market.connection.commit()
    store = ObserverStore(service.paths.observer)
    try:
        run = store.db.execute(
            "SELECT * FROM observer_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        processor = BatchProcessor(
            service.paths.market, store, source_audit(), run["run_id"], run["live_floor_ms"]
        )
        assert processor.evaluate(bar, clock[0])["status"] == "COMMITTED"
        decision = store.db.execute(
            "SELECT decision FROM signal_decisions WHERE strategy_id=? "
            "AND symbol='BTCUSDT' AND bar_open_ms=?",
            (T1, bar),
        ).fetchone()[0]
        assert decision == "ENTRY_CANDIDATE"
    finally:
        store.close()
    health(service.paths, clock)


@pytest.mark.parametrize("notional", ["8.309999", "8.31"])
def test_cap_accepts_boundary(notional):
    notional_guard(notional, "1")


@pytest.mark.parametrize("notional", ["8.310001", "20", "1000"])
def test_cap_rejects_before_rounding(notional):
    with pytest.raises(TestnetError, match="E02_ORDER_LIMIT"):
        notional_guard(notional, "1")


def test_allocation_phase_a_preserve_manual_and_original_router(runtime):
    service, exchange, _, _, legacy, *_ = runtime
    before = service.store.rows("SELECT * FROM exchange_orders")
    checkpoint = service.store.rows("SELECT * FROM router_checkpoints")
    prepare(runtime)
    assert before == service.store.rows("SELECT * FROM exchange_orders")
    assert checkpoint == service.store.rows("SELECT * FROM router_checkpoints")
    assert service.store.rows("SELECT * FROM signal_receipts") == []
    assert service.store.rows("SELECT * FROM execution_gates WHERE gate IN ('B','C')") == legacy
    assert service.manager.positions.allocation()["initial_capital"] == "1000"
    assert service.manager.positions.positions() == []
    assert {p["strategy_id"] for p in service.store.rows("SELECT * FROM position_fills")} == {
        "MANUAL_BASELINE"
    }
    assert exchange.post_count == 1  # The seeded mock manual order only.


def test_off_and_activation_do_not_replay_existing_signal(runtime):
    service, exchange, *_ = runtime
    assert service.tick()["state"] == "OFF"
    activate(runtime)
    assert service.tick()["submissions"] == []
    assert exchange.post_count == 1


def test_new_frozen_live_signal_auto_order_partial_fill_cancel_dedup(runtime):
    service, exchange, clock, _, legacy, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    result = service.tick()
    assert result["state"] == "ON", result
    submissions = result["submissions"]
    assert len(submissions) == 1
    cid = submissions[0]["client_id"]
    assert submissions[0]["state"] == "NEW"
    assert Decimal(submissions[0]["notional"]) <= Decimal("8.31")
    assert service.tick()["submissions"] == []
    assert exchange.post_count == 2
    quantity = Decimal(exchange.orders[cid]["origQty"])
    exchange.fill(cid, str(quantity / 2))
    service.manager.reconcile()
    assert service.manager.positions.positions()[0]["quantity"] == str(quantity / 2)
    clock[0] += 60_000
    health(service.paths, clock)
    service.tick()
    assert service.manager.intent(cid)["state"] == "CANCELED"
    assert service.manager.positions.positions()[0]["quantity"] == str(quantity / 2)
    assert service.store.rows("SELECT * FROM execution_gates WHERE gate IN ('B','C')") == legacy


@pytest.mark.parametrize("role", ["collector", "observer"])
def test_dependency_stop_blocks_new_orders(runtime, role):
    service, exchange, clock, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    health(service.paths, clock, role=role, state="STOPPED")
    result = service.tick()
    assert result["state"] == "HOLD"
    assert exchange.post_count == 1


def test_bad_activation_token_and_missing_gate_do_not_enable(runtime):
    service, exchange, *_ = runtime
    prepare(runtime)
    with pytest.raises(TestnetError, match="ACTIVATION_REVIEW"):
        command(service, "on", token="incorrect")
    service.store.db.execute("DELETE FROM execution_gates WHERE gate='C'")
    service.manager.reconcile()
    assert not service.store.rows("SELECT * FROM execution_gates WHERE gate='C'")
    with pytest.raises(TestnetError, match="GATES_INCOMPLETE"):
        gate_evidence(service.manager)
    assert not service.control.mode()["enabled"] and exchange.post_count == 1


def test_duplicate_writer_and_restart_off_preserve_journal(runtime):
    service, exchange, clock, prices, _, acceptance, handler = runtime
    prepare(runtime)
    before = service.store.rows("SELECT * FROM executions")
    with pytest.raises(PersistenceError, match="writer_unavailable"):
        Executor(
            service.paths,
            service.directory,
            service.client,
            service.quote_provider,
            acceptance_path=acceptance,
            clock=lambda: clock[0],
            host_checks=False,
        )
    assert not service.control.mode()["enabled"]
    service.close()
    new_client = TestnetExecutionClient(
        TestnetConfig("test-key", "test-secret", True), transport=httpx.MockTransport(handler)
    )
    restart = Executor(
        service.paths,
        service.directory,
        new_client,
        service.quote_provider,
        acceptance_path=acceptance,
        clock=lambda: clock[0],
        host_checks=False,
    )
    try:
        assert not restart.control.mode()["enabled"]
        assert before == restart.store.rows("SELECT * FROM executions")
        assert exchange.post_count == 1
    finally:
        restart.close()
        new_client.close()


def test_unknown_and_reset_block_orders(runtime):
    service, exchange, *_ = runtime
    activate(runtime)
    service.store.db.execute("UPDATE testnet_sessions SET hold='UNKNOWN_EXECUTION'")
    assert service.tick()["state"] == "HOLD"
    assert exchange.post_count == 1


def test_emergency_is_immediate_and_manual_cancel_denied(runtime):
    service, exchange, *_ = runtime
    activate(runtime)
    service.control.enqueue("kill")
    with pytest.raises(TestnetError):
        service.manager.enabled()
    service.tick()
    assert service.store.session()["kill"] == 1 and not service.control.mode()["enabled"]
    cid = next(iter(exchange.orders))
    with pytest.raises(TestnetError, match="MANUAL_BASELINE_CANCEL_DENIED"):
        service.manager.cancel(cid, confirm_cancel=True)


def test_min_notional_above_cap_is_skipped(runtime):
    service, exchange, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    for symbol in exchange.info["symbols"]:
        for f in symbol["filters"]:
            if f["filterType"] in {"NOTIONAL", "MIN_NOTIONAL"}:
                f["minNotional"] = "10"
    result = service.tick()
    assert not result.get("submissions")
    assert exchange.post_count == 1


def test_exit_budget_never_relaxes_daily_limit():
    risk = AutomationRisk()
    with pytest.raises(TestnetError, match="PROTECTION_BUDGET"):
        risk.reserve_exit_budget([{"notional": "8"}] * 2, [], {}, Decimal("8.31"))


def test_off_racing_activation_cannot_be_overwritten(tmp_path):
    control = Control(tmp_path)
    control.off()
    epoch = control.mode()["epoch"]
    control.off()
    with pytest.raises(TestnetError, match="E02_CONTROL_CHANGED"):
        control.authorize({"review": "old"}, epoch)
    assert not control.mode()["enabled"]


def test_original_baseline_sources_unchanged():
    assert frozen_sources()["e02_protected_files"] == 109


def test_get_preflight_copy_preserves_original_gates_and_all_rows(runtime):
    service, exchange, clock, _, _, acceptance, handler = runtime
    prepare(runtime)
    before = list(service.store.db.iterdump())
    result = online_readonly(
        service.paths,
        service.client.config,
        transport=httpx.MockTransport(handler),
        directory=service.directory,
        acceptance_path=acceptance,
        clock=lambda: clock[0],
        host=False,
    )
    assert result["state"] == "ACTIVATION_PREFLIGHT_PASS"
    assert result["activation_token"] == digest(service.evidence())
    assert before == list(service.store.db.iterdump())
    assert exchange.post_count == 1


def test_get_copy_cannot_manufacture_missing_c(runtime):
    service, _, clock, _, _, acceptance, handler = runtime
    prepare(runtime)
    service.store.db.execute("DELETE FROM execution_gates WHERE gate='C'")
    with pytest.raises(TestnetError, match="GATES_INCOMPLETE"):
        online_readonly(
            service.paths,
            service.client.config,
            transport=httpx.MockTransport(handler),
            directory=service.directory,
            acceptance_path=acceptance,
            clock=lambda: clock[0],
            host=False,
        )
    assert not service.store.rows("SELECT * FROM execution_gates WHERE gate='C'")


def test_final_http_cap_independent_of_e01_guard(runtime):
    service, exchange, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    cid = next(r["client_id"] for r in service.route() if r["state"] == "INTENT_CREATED")
    service.client._execution_send_guard = lambda *_: None
    params = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": "9",
        "price": "1",
        "newClientOrderId": cid,
    }
    with pytest.raises(TestnetError, match="E02_ORDER_LIMIT"):
        service.client.request("POST", "/api/v3/order", params, confirm=True)
    assert exchange.post_count == 1


@pytest.mark.parametrize("accepted", [True, False])
def test_ambiguous_send_queries_same_id_never_reposts(runtime, accepted):
    service, exchange, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    exchange.fail_post = httpx.ReadTimeout("simulated ambiguous response")
    exchange.accept_timeout = accepted
    result = service.tick()
    assert exchange.post_count == 2
    if accepted:
        assert result["state"] == "ON"
        assert result["submissions"][0]["state"] == "NEW"
    else:
        assert result["state"] == "HOLD"
        assert service.store.session()["hold"] == "UNKNOWN_EXECUTION"
    service.tick()
    assert exchange.post_count == 2


def test_account_reset_is_not_reinitialized(runtime):
    service, exchange, *_ = runtime
    activate(runtime)
    original = service.store.session()["id"]
    exchange.orders.clear()
    result = service.tick()
    assert result["state"] == "HOLD"
    assert service.store.session()["id"] == original
    assert service.store.session()["hold"] == "RESET_SUSPECTED"


def test_partial_fill_dust_reports_protection_hold(runtime):
    service, exchange, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    cid = service.tick()["submissions"][0]["client_id"]
    exchange.fill(cid, "0.000004")
    service.manager.reconcile()
    service.manager.cancel(cid, confirm_cancel=True)
    result = service.tick()
    assert result["state"] == "HOLD" and result["category"] == "MIN_NOTIONAL"
    assert not service.control.mode()["enabled"]


def test_kill_reset_requires_review_and_stays_off(runtime):
    service, *_ = runtime
    prepare(runtime)
    service.control.enqueue("kill")
    service.tick()
    with pytest.raises(TestnetError, match="OPERATOR_REVIEW"):
        command(service, "reset-kill", token="bad")
    token = operator_review(service.paths, service.directory)
    assert command(service, "reset-kill", token=token)["state"] == "RECOVERED_OFF"
    assert service.store.session()["kill"] == 0
    assert not service.control.killed() and not service.control.mode()["enabled"]


def test_explicit_bind_audits_old_checkpoint_and_invalidates_a_d(runtime):
    service, *_ = runtime
    prepare(runtime)
    token = operator_review(service.paths, service.directory)
    command(service, "bind", token=token)
    assert not service.store.rows("SELECT * FROM execution_gates WHERE gate IN ('A','D')")
    assert service.store.rows(
        "SELECT * FROM reconciliation_events WHERE kind='E02_EXPLICIT_SOURCE_BIND'"
    )
    assert not service.control.mode()["enabled"]


def test_filter_floor_never_increases_order_cap(runtime):
    service, exchange, *_ = runtime
    risk = AutomationRisk()
    order = risk.validate(
        "BTCUSDT",
        "BUY",
        "0.00831",
        "1000",
        exchange.info,
        service.client.request("GET", "/api/v3/account")["balances"],
        [],
        [],
    )
    assert order.notional == Decimal("8.31000")
    with pytest.raises(TestnetError, match="E02_ORDER_LIMIT"):
        risk.validate(
            "BTCUSDT",
            "BUY",
            "0.0083109",
            "1000",
            exchange.info,
            service.client.request("GET", "/api/v3/account")["balances"],
            [],
            [],
        )


def test_atr_stop_uses_owned_quantity_under_cap_and_preserves_daily_limits(runtime):
    service, exchange, clock, prices, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    cid = service.tick()["submissions"][0]["client_id"]
    exchange.fill(cid, exchange.orders[cid]["origQty"])
    service.manager.reconcile()
    position = service.manager.positions.positions()[0]
    stop_price = (Decimal(position["initial_stop"]) * Decimal("0.99")).quantize(Decimal("0.01"))
    assert stop_price > 0
    prices["BTCUSDT"] = stop_price
    with MarketStore(service.paths.market) as market:
        market.connection.execute(
            "UPDATE price_snapshots SET price_text=? WHERE symbol='BTCUSDT'", (str(stop_price),)
        )
        market.connection.commit()
    result = service.tick()
    assert result["state"] == "ON", result
    sell = result["submissions"][0]
    assert sell["side"] == "SELL" and Decimal(sell["notional"]) <= Decimal("8.31")
    assert Decimal(sell["quantity"]) <= Decimal(position["quantity"])
    assert len(service.manager.attempts()) <= 3
    exchange.fill(sell["client_id"], exchange.orders[sell["client_id"]]["origQty"])
    service.manager.reconcile()
    assert Decimal(service.manager.positions.positions()[0]["quantity"]) == 0


def test_final_boundary_dependency_restart_blocks_send(runtime):
    service, exchange, clock, *_ = runtime
    activate(runtime)
    next_bar(runtime)
    service.manager.dependencies = service.manager.healthy()
    cid = next(r["client_id"] for r in service.route() if r["state"] == "INTENT_CREATED")
    service.manager.check(cid, confirm_test=True)
    health(service.paths, clock, instance="replacement")
    with pytest.raises(TestnetError, match="DEPENDENCY_RESTART"):
        service.manager.submit(cid, confirm_order=True, automated=True)
    assert exchange.post_count == 1
