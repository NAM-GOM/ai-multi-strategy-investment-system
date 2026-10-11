"""Offline integration uses real M03/M04 SQLite and Frozen T1 signals, fake Testnet only."""

import json
import sqlite3
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from test_testnet import INFO, Exchange

from trading_system.execution import cli
from trading_system.execution.config import EXPERIMENT, T1, TestnetConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.models import Balance, ExchangeOrder, Quote
from trading_system.execution.order_manager import OrderManager
from trading_system.execution.risk_engine import RiskEngine
from trading_system.execution.signal_router import SignalRouter
from trading_system.execution.testnet_client import FixedTestnetConnect, TestnetExecutionClient
from trading_system.observer.audit import source_audit
from trading_system.observer.model import FREEZE_MS, SignalDecision
from trading_system.observer.service import BatchProcessor
from trading_system.observer.store import ObserverStore
from trading_system.persistence.records import INTERVAL_MS, CandleRecord
from trading_system.persistence.store import MarketStore
from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec
from trading_system.testnet.store import Store

TARGET = FREEZE_MS + 12 * INTERVAL_MS
NOW = TARGET + INTERVAL_MS + 1000


@pytest.fixture(autouse=True)
def no_testnet_websocket(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline tests cannot open Testnet WebSocket")

    monkeypatch.setattr("trading_system.execution.testnet_client.FixedTestnetConnect", denied)


@pytest.fixture(scope="module")
def m04_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("real_m04")
    market, observer = root / "market.sqlite", root / "observer.sqlite"
    audit = source_audit()
    store = ObserverStore(observer)
    run = store.start(audit, FREEZE_MS)
    processor = BatchProcessor(market, store, audit, run, FREEZE_MS)
    # Twelve low closed bars, then SOL upward EMA crossover. Sources remain WS_LIVE.
    with MarketStore(market) as writer:
        for index in range(13):
            bar = FREEZE_MS + index * INTERVAL_MS
            value = Decimal("1000" if index == 12 else "1")
            candles = [
                CandleRecord(
                    symbol,
                    "4h",
                    bar,
                    bar + INTERVAL_MS - 1,
                    value,
                    value + Decimal("0.01"),
                    value - Decimal("0.01"),
                    value,
                    Decimal(50),
                    bar + INTERVAL_MS + 10,
                    bar + INTERVAL_MS + 20,
                    "WS_LIVE",
                )
                for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
            ]
            writer.write_batch(candles=candles)
            processor.evaluate(bar, bar + INTERVAL_MS + 1000)
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            writer.connection.execute(
                "INSERT INTO price_snapshots VALUES(?,?,?,?,?,?)",
                (symbol, NOW - NOW % 60000, "1000", NOW, NOW, "binance_spot"),
            )
        writer.connection.commit()
    row = store.db.execute(
        "SELECT decision FROM signal_decisions WHERE strategy_id=? "
        "AND symbol='SOLUSDT' AND bar_open_ms=?",
        (T1, TARGET),
    ).fetchone()
    assert row[0] == "ENTRY_CANDIDATE"
    store.close()
    return market, observer


@pytest.fixture
def integrated(tmp_path, m04_source):
    market, observer = tmp_path / "market.sqlite", tmp_path / "observer.sqlite"
    for source, destination in zip(m04_source, (market, observer), strict=True):
        with sqlite3.connect(source) as a, sqlite3.connect(destination) as b:
            a.backup(b)
        a.close()
        b.close()
    exchange = Exchange()
    exchange.balances["USDT"] = Decimal("1000")
    clock = [NOW]

    def handler(request):
        response = exchange.handler(request)
        if request.url.path == "/api/v3/account":
            return httpx.Response(
                200, json={**response.json(), "canTrade": True, "accountType": "SPOT"}
            )
        return response

    client = TestnetExecutionClient(
        TestnetConfig("test-key", "test-secret", True), transport=httpx.MockTransport(handler)
    )
    store = ExecutionStore(tmp_path / "testnet_execution.sqlite")
    quote = Quote("SOLUSDT", Decimal("1000"), Decimal("1000"), NOW, 1)
    manager = OrderManager(
        client,
        store,
        clock=lambda: clock[0],
        quote_provider=lambda _: replace(quote, received_ms=clock[0]),
    )
    manager.reconcile()
    router = SignalRouter(manager.positions, observer, market)
    # Represent startup before the final closed bar: prior rows are the startup watermark.
    with store.transaction():
        store.db.execute(
            "INSERT INTO router_checkpoints VALUES(?,?,?,?,?)",
            (
                manager.sid,
                str(observer.resolve()),
                str(market.resolve()),
                TARGET + INTERVAL_MS - 1000,
                12 * 9,
            ),
        )
    yield exchange, store, manager, router, clock, quote, market, observer
    client.close()
    store.close()


def route(integrated, *, dry_run=True):
    exchange, store, manager, router, clock, quote, *_ = integrated
    return router.route(
        clock[0],
        {"SOLUSDT": quote},
        exchange.info,
        [{"asset": a, "free": str(v), "locked": "0"} for a, v in exchange.balances.items()],
        dry_run=dry_run,
    )


def allocate(integrated):
    _, _, manager, _, clock, *_ = integrated
    manager.positions.allocate("1000", clock[0])


def manual_gate(integrated):
    _, store, manager, _, clock, *_ = integrated
    cid = manager.create("SOLUSDT", "BUY", "0.005", "1000")
    manager.check(cid, confirm_test=True)
    manager.submit(cid, confirm_order=True, approval_token=manager.review(cid)["approval_token"])
    manager.cancel(cid, confirm_cancel=True)
    assert {r["gate"] for r in store.rows("SELECT * FROM execution_gates")} >= {"B", "C"}
    # Phase A is separately tested against the real Frozen decision in the DRY_RUN test.
    with store.transaction():
        store.gate(manager.sid, "A", clock[0], "OFFLINE_PHASE_A_TEST_FIXTURE")


def test_dry_run_real_frozen_signal_no_network_or_observer_mutation(integrated):
    exchange, store, manager, router, clock, quote, market, observer = integrated
    allocate(integrated)
    before = observer.read_bytes(), market.read_bytes(), len(exchange.requests)
    reports = route(integrated)
    approved = [r for r in reports if r["state"] == "DRY_RUN_APPROVED"]
    assert len(approved) == 1 and approved[0]["classification"] == EXPERIMENT
    assert Decimal(approved[0]["notional"]) <= 20 and approved[0]["client_id"] is None
    assert before == (observer.read_bytes(), market.read_bytes(), len(exchange.requests))
    assert not store.rows("SELECT * FROM order_intents")
    assert "A" in {g["gate"] for g in store.rows("SELECT * FROM execution_gates")}
    assert route(integrated) == []
    restarted = SignalRouter(manager.positions, observer, market)
    assert restarted.initialize(clock[0] + 100)["last_rowid"] == 117


def test_startup_existing_signals_never_ordered(integrated):
    _, store, manager, router, clock, *_ = integrated
    store.db.execute("DELETE FROM router_checkpoints")
    allocate(integrated)
    assert router.initialize(clock[0])["last_rowid"] == 117
    assert route(integrated, dry_run=False) == []
    assert not store.rows("SELECT * FROM order_intents")


def test_manual_to_automated_t1_mock_lifecycle_partial_fill_restart(integrated):
    exchange, store, manager, router, clock, quote, market, observer = integrated
    manual_gate(integrated)
    allocate(integrated)
    manager.safety = replace(manager.safety, automated_enabled=True)
    manager.enable_automation(confirm=True)
    reports = route(integrated, dry_run=False)
    created = next(r for r in reports if r["state"] == "INTENT_CREATED")
    cid = created["client_id"]
    assert manager.positions.reserved()[0] == Decimal("20.20000")
    assert manager.check(cid, confirm_test=True)["state"] == "VALIDATED"
    assert manager.submit(cid, confirm_order=True, automated=True)["state"] == "NEW"
    exchange.fill(cid, "0.01")
    manager.reconcile()
    position = manager.positions.positions()[0]
    assert position["quantity"] == "0.01"
    assert dec(position["cost"]) == Decimal("10.01")
    assert dec(position["average_fill"]) == Decimal("1000")
    assert manager.positions.reserved()[0] == Decimal("10.10000")
    exchange.fill(cid, "0.01")
    manager.reconcile()
    assert dec(manager.positions.allocation()["cash"]) == Decimal("979.98")
    assert manager.positions.reserved() == (Decimal(0), {})
    other = ExecutionStore(Path(store.db.execute("PRAGMA database_list").fetchone()[2]))
    try:
        restart = OrderManager(
            manager.client,
            other,
            clock=manager.clock,
            quote_provider=manager.quote_provider,
            safety=manager.safety,
        )
        restart.reconcile()
        assert restart.positions.positions() == manager.positions.positions()
        assert SignalRouter(restart.positions, observer, market).route(clock[0], {}, INFO, []) == []
        with pytest.raises(TestnetError, match="DUPLICATE_SUBMISSION"):
            restart.submit(cid, confirm_order=True, automated=True)
    finally:
        other.close()
    assert exchange.post_count == 2  # One explicitly approved manual order, one T1 order.
    assert len(store.rows("SELECT * FROM position_fills WHERE strategy_id=?", (T1,))) == 2
    assert {
        r["strategy_id"]
        for r in store.rows("SELECT * FROM signal_receipts WHERE client_id IS NOT NULL")
    } == {T1}


@pytest.mark.parametrize(
    "mode", ["PRELAUNCH_STATE_BACKFILL", "FORMAL_W04_ELIGIBLE", "SEEN_HISTORICAL_DATA"]
)
def test_non_live_and_formal_records_are_blocked(integrated, mode):
    _, _, _, router, clock, _, _, observer = integrated
    with sqlite3.connect(observer) as db:
        db.execute("DROP TRIGGER immutable_signal_decisions_UPDATE")
        row = db.execute(
            "SELECT record FROM signal_decisions WHERE strategy_id=? "
            "AND symbol='SOLUSDT' AND bar_open_ms=?",
            (T1, TARGET),
        ).fetchone()
        d = replace(SignalDecision(**json.loads(row[0])), observation_mode=mode)
        from dataclasses import asdict

        db.execute(
            "UPDATE signal_decisions SET record=?,mode=?,decision_hash=? "
            "WHERE strategy_id=? AND symbol='SOLUSDT' AND bar_open_ms=?",
            (json.dumps(asdict(d)), mode, d.decision_hash, T1, TARGET),
        )
    reports = route(integrated)
    assert "NON_LIVE_OR_FORMAL_SIGNAL" in {r["state"] for r in reports}


@pytest.mark.parametrize(
    "change,expected",
    [
        ("record", "SIGNAL_HASH_MISMATCH"),
        ("input", "SIGNAL_HASH_MISMATCH"),
        ("batch", "INVALID_COMMITTED_BATCH"),
        ("manifest", "STRATEGY_HASH_MISMATCH"),
        ("health", "M04_NOT_OBSERVING"),
    ],
)
def test_tampered_metadata_fail_closed(integrated, change, expected):
    _, _, _, _, _, _, _, observer = integrated
    with sqlite3.connect(observer) as db:
        for table in ("signal_decisions", "evaluation_batches", "strategy_manifests"):
            db.execute(f"DROP TRIGGER immutable_{table}_UPDATE")
        if change == "record":
            db.execute("UPDATE signal_decisions SET decision_hash='bad' WHERE strategy_id=?", (T1,))
        elif change == "input":
            db.execute("UPDATE signal_decisions SET input_hash='bad' WHERE strategy_id=?", (T1,))
        elif change == "batch":
            db.execute("UPDATE evaluation_batches SET batch_hash='bad'")
        elif change == "manifest":
            db.execute("UPDATE strategy_manifests SET manifest_hash='bad'")
        else:
            db.execute("UPDATE observer_runs SET status='DATA_HOLD'")
    if change == "health":
        with pytest.raises(TestnetError, match=expected):
            route(integrated)
    else:
        assert expected in {r["state"] for r in route(integrated)}


def test_changed_market_input_rejected(integrated):
    _, _, _, _, _, _, market, _ = integrated
    with sqlite3.connect(market) as db:
        # Explicit corruption of the fixture, not an API for market DB mutation.
        db.execute(
            "UPDATE candles_4h SET volume_text='51' WHERE symbol='SOLUSDT' AND open_time_ms=?",
            (TARGET,),
        )
    assert "INPUT_HASH_MISMATCH" in {r["state"] for r in route(integrated)}


@pytest.mark.parametrize(
    "age,expected", [(60001, "STALE_OR_UNCONFIRMED_SIGNAL"), (-2000, "STALE_OR_UNCONFIRMED_SIGNAL")]
)
def test_stale_or_future_signal(integrated, age, expected):
    integrated[4][0] = TARGET + INTERVAL_MS + age
    assert expected in {r["state"] for r in route(integrated)}


@pytest.mark.parametrize(
    "delta,expected", [("0.03", "PRICE_DIVERGENCE"), ("0.01", "TESTNET_SPREAD")]
)
def test_price_divergence_and_spread(integrated, delta, expected):
    allocate(integrated)
    quote = replace(integrated[5], ask=Decimal(1000) * (1 + Decimal(delta)))
    reports = integrated[3].route(NOW, {"SOLUSDT": quote}, INFO, [])
    assert expected in {r["state"] for r in reports}


def test_stale_quote(integrated):
    allocate(integrated)
    reports = integrated[3].route(
        NOW, {"SOLUSDT": replace(integrated[5], received_ms=NOW - 5001)}, INFO, []
    )
    assert "STALE_TESTNET_QUOTE" in {r["state"] for r in reports}


def test_shadow_signal_never_creates_intent(integrated):
    allocate(integrated)
    reports = route(integrated, dry_run=False)
    states = {r["state"] for r in reports}
    assert "SHADOW_SIGNAL_ONLY" in states
    assert len(integrated[1].rows("SELECT * FROM order_intents")) == 1


def test_production_credentials_reuse_and_missing_rejected(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("BINANCE_API_KEY", "mock-production")
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "mock-production")
    with pytest.raises(TestnetError, match="PRODUCTION_CREDENTIAL_REUSE_DENIED"):
        TestnetConfig.from_env()
    assert cli.main(["testnet-status", "--db", str(tmp_path / "testnet_execution.sqlite")]) == 2
    assert "mock-production" not in capsys.readouterr().out
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY")
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    assert TestnetConfig.from_env().api_key == ""


def test_manual_review_required(integrated):
    exchange, _, manager, *_ = integrated
    cid = manager.create("SOLUSDT", "BUY", "0.005", "1000")
    manager.check(cid, confirm_test=True)
    with pytest.raises(TestnetError, match="EXPLICIT_REVIEW_APPROVAL_REQUIRED"):
        manager.submit(cid, confirm_order=True)
    assert exchange.post_count == 0
    review = manager.review(cid)
    assert review["environment"] == "TESTNET" and review["limits"]["per_order_usdt"] == "20"


def test_automation_default_disabled_and_missing_gates(integrated):
    _, _, manager, *_ = integrated
    with pytest.raises(TestnetError, match="AUTOMATION_DISABLED"):
        manager.enable_automation(confirm=True)
    manager.safety = replace(manager.safety, automated_enabled=True)
    with pytest.raises(TestnetError, match="AUTOMATION_GATES_INCOMPLETE"):
        manager.enable_automation(confirm=True)


def test_unattributed_manual_order_after_allocation_blocked(integrated):
    allocate(integrated)
    _, _, manager, *_ = integrated
    cid = manager.create("SOLUSDT", "BUY", "0.005", "1000")
    with pytest.raises(TestnetError, match="UNATTRIBUTED_ORDER_BLOCKED"):
        manager.check(cid, confirm_test=True)


def test_ledger_corruption_and_kill_block_router(integrated):
    allocate(integrated)
    _, store, manager, *_ = integrated
    store.db.execute("UPDATE strategy_allocations SET cash='1001'")
    with pytest.raises(TestnetError, match="POSITION_LEDGER_MISMATCH"):
        manager.reconcile()
    assert store.session()["hold"] == "RECONCILIATION_HOLD"
    assert "POSITION_LEDGER_MISMATCH" in {r["state"] for r in route(integrated, dry_run=False)}


def test_kill_persists_in_new_session(integrated):
    _, store, manager, _, clock, *_ = integrated
    store.kill(manager.sid, clock[0], True)
    restart = OrderManager(manager.client, store, clock=manager.clock, acknowledge_reset=True)
    assert store.session()["kill"] == 1
    assert not store.rows("SELECT * FROM execution_gates WHERE session_id=?", (restart.sid,))


def test_legacy_journal_migrates_but_legacy_engine_cannot_bypass(integrated, tmp_path):
    original = Store(tmp_path / "other" / "testnet_execution.sqlite")
    original.close()
    upgraded = ExecutionStore(tmp_path / "other" / "testnet_execution.sqlite")
    upgraded.close()
    with pytest.raises(TestnetError, match="FOREIGN_DB_REJECTED"):
        Store(tmp_path / "other" / "testnet_execution.sqlite")


def test_position_db_failure_blocks_no_post(integrated):
    allocate(integrated)
    exchange, store, *_ = integrated
    store.db.execute(
        "CREATE TRIGGER fail_intent BEFORE INSERT ON order_intents "
        "BEGIN SELECT RAISE(ABORT,'disk'); END"
    )
    with pytest.raises(TestnetError, match="DB_FAILED"):
        route(integrated, dry_run=False)
    assert store.failed and exchange.post_count == 0


def test_sqlite_dedup_transaction_replay(integrated):
    allocate(integrated)
    reports = route(integrated, dry_run=False)
    assert len(integrated[1].rows("SELECT * FROM order_intents")) == 1
    integrated[1].db.execute("UPDATE router_checkpoints SET last_rowid=108")
    replay = route(integrated, dry_run=False)
    assert all(r["state"] == "DUPLICATE_SIGNAL" for r in replay)
    assert len(integrated[1].rows("SELECT * FROM order_intents")) == 1
    assert any(r["client_id"] for r in reports if "client_id" in r)


def test_signal_becomes_stale_before_submit(integrated):
    allocate(integrated)
    _, _, manager, _, clock, *_ = integrated
    cid = next(r["client_id"] for r in route(integrated, dry_run=False) if r.get("client_id"))
    clock[0] += 60001
    with pytest.raises(TestnetError, match="STALE_OR_UNCONFIRMED_SIGNAL"):
        manager.check(cid, confirm_test=True)


@pytest.mark.parametrize(
    "constructor,value",
    [
        (Balance, {"asset": "USDT", "free": "NaN", "locked": "0"}),
        (ExchangeOrder, {"status": "FILLED"}),
        (Quote, {"s": "SOLUSDT", "b": "100", "a": "99", "B": "1", "A": "1", "u": 1}),
    ],
)
def test_invalid_typed_models(constructor, value):
    with pytest.raises(TestnetError):
        constructor.parse(value, NOW) if constructor is Quote else constructor.parse(value)


def test_websocket_redirect_denied_before_following():
    assert isinstance(
        FixedTestnetConnect.process_redirect(None, RuntimeError("redirect")), TestnetError
    )


def test_cli_offline_and_router_run_cannot_activate(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("BINANCE_TESTNET_TRADING_ENABLED", raising=False)
    path = str(tmp_path / "testnet_execution.sqlite")
    assert cli.main(["testnet-status", "--db", path]) == 0
    assert json.loads(capsys.readouterr().out)["automation"] == "DISABLED"
    assert (
        cli.main(
            [
                "testnet-order-check",
                "--db",
                path,
                "--symbol",
                "SOLUSDT",
                "--side",
                "BUY",
                "--quantity",
                "0.01",
                "--price",
                "1000",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["state"] == "DRY_RUN"
    assert cli.main(["testnet-order-submit", "--db", path, "--client-id", "absent"]) == 0
    assert json.loads(capsys.readouterr().out)["network"] == "NOT_REQUESTED"


def test_mock_stop_exit_and_realized_pnl(integrated):
    exchange, store, manager, router, clock, quote, market, _ = integrated
    manual_gate(integrated)
    manager.positions.allocate("400", clock[0])
    manager.safety = replace(manager.safety, automated_enabled=True)
    manager.enable_automation(confirm=True)
    cid = next(r["client_id"] for r in route(integrated, dry_run=False) if r.get("client_id"))
    manager.check(cid, confirm_test=True)
    manager.submit(cid, confirm_order=True, automated=True)
    quantity = manager.intent(cid)["quantity"]
    exchange.fill(cid, quantity)
    manager.reconcile()
    position = manager.positions.positions()[0]
    exit_price = dec(position["initial_stop"]).quantize(Decimal("0.01")) - 1
    exit_quote = replace(quote, bid=exit_price, ask=exit_price)
    manager.quote_provider = lambda _: exit_quote
    with sqlite3.connect(market) as db:
        db.execute(
            "UPDATE price_snapshots SET price_text=? WHERE symbol='SOLUSDT'", (str(exit_price),)
        )
    balances = [{"asset": a, "free": str(v), "locked": "0"} for a, v in exchange.balances.items()]
    stops = manager.protective_intents(router, {"SOLUSDT": exit_quote}, exchange.info, balances)
    assert len(stops) == 1
    stop_id = stops[0]["client_id"]
    manager.check(stop_id, confirm_test=True)
    manager.submit(stop_id, confirm_order=True, automated=True)
    exchange.fill(stop_id, quantity)
    manager.reconcile()
    closed = manager.positions.positions()[0]
    assert dec(closed["quantity"]) == 0 and dec(closed["cost"]) == 0
    expected = Decimal(quantity) * (exit_price - 1000) - Decimal("0.02")
    assert dec(closed["realized_pnl"]) == expected
    assert dec(manager.positions.allocation()["cash"]) == 400 + expected
    assert manager.positions.report({"SOLUSDT": exit_price})[0]["unrealized_pnl"] == "0.00000"


def test_manual_fills_are_baseline_not_strategy_performance(integrated):
    exchange, store, manager, _, clock, *_ = integrated
    cid = manager.create("SOLUSDT", "BUY", "0.005", "1000")
    manager.check(cid, confirm_test=True)
    manager.submit(cid, confirm_order=True, approval_token=manager.review(cid)["approval_token"])
    exchange.fill(cid, "0.005")
    manager.reconcile()
    manager.positions.allocate("400", clock[0])
    manager.reconcile()
    assert manager.positions.positions() == []
    assert manager.positions.allocation()["cash"] == "400"
    assert store.rows("SELECT * FROM position_fills")[0]["strategy_id"] == "MANUAL_BASELINE"


def test_unknown_execution_restart_never_reposts(integrated):
    exchange, store, manager, *_ = integrated
    cid = manager.create("SOLUSDT", "BUY", "0.005", "1000")
    manager.check(cid, confirm_test=True)
    exchange.fail_post = httpx.ReadTimeout("mock-disconnect")
    with pytest.raises(TestnetError, match="UNKNOWN_EXECUTION"):
        manager.submit(
            cid, confirm_order=True, approval_token=manager.review(cid)["approval_token"]
        )
    assert manager.intent(cid)["state"] == "UNKNOWN_EXECUTION" and store.session()["hold"]
    reopened = ExecutionStore(Path(store.db.execute("PRAGMA database_list").fetchone()[2]))
    try:
        restart = OrderManager(manager.client, reopened, clock=manager.clock)
        with pytest.raises(TestnetError, match="UNKNOWN_EXECUTION"):
            restart.reconcile()
        with pytest.raises(TestnetError):
            restart.submit(
                cid, confirm_order=True, approval_token=restart.review(cid)["approval_token"]
            )
        assert exchange.post_count == 1
    finally:
        reopened.close()


def test_duplicate_production_secret_rejected(monkeypatch):
    monkeypatch.setenv("BINANCE_API_SECRET", "mock-production-secret")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "mock-production-secret")
    with pytest.raises(TestnetError, match="PRODUCTION_CREDENTIAL_REUSE_DENIED"):
        TestnetConfig.from_env()


def test_ci_real_transport_cannot_send_orders(monkeypatch):
    monkeypatch.setenv("CI", "true")
    client = TestnetExecutionClient(TestnetConfig("mock-key", "mock-secret", True))
    try:
        with pytest.raises(TestnetError, match="CI_ORDER_BLOCKED"):
            client.request("POST", "/api/v3/order/test", {}, confirm=True)
    finally:
        client.close()


def test_prelaunch_misclassified_as_live_is_blocked(integrated):
    with sqlite3.connect(integrated[7]) as db:
        db.execute("UPDATE observer_runs SET live_floor_ms=?", (NOW,))
    assert "PRELAUNCH_OR_RECOVERED_SIGNAL" in {r["state"] for r in route(integrated)}


def test_stale_unsent_intent_expires_without_exchange_status(integrated):
    allocate(integrated)
    exchange, store, manager, _, clock, *_ = integrated
    cid = next(r["client_id"] for r in route(integrated, dry_run=False) if r.get("client_id"))
    clock[0] += 60001
    manager.reconcile()
    assert manager.intent(cid)["state"] == "INTENT_EXPIRED"
    assert manager.positions.reserved() == (Decimal(0), {})
    assert exchange.post_count == 0 and not store.rows("SELECT * FROM exchange_orders")


def test_freshness_requires_exchange_event_time(integrated):
    with sqlite3.connect(integrated[6]) as db:
        db.execute("UPDATE price_snapshots SET event_time_ms=?", (NOW - 30001,))
    assert "STALE_PRODUCTION_REFERENCE" in {r["state"] for r in route(integrated)}


def test_risk_precision_and_filter_limits():
    risk = RiskEngine()
    info = json.loads(json.dumps(INFO))
    info["symbols"][2]["baseAssetPrecision"] = 2
    balances = [{"asset": "USDT", "free": "100", "locked": "0"}]
    with pytest.raises(TestnetError, match="EXCHANGE_PRECISION"):
        risk.validate("SOLUSDT", "BUY", "0.019", "1000", info, balances, [], [])
    with pytest.raises(TestnetError, match="INVALID_EXCHANGE_FILTERS"):
        risk.validate("SOLUSDT", "BUY", "0.01", "1000", {}, balances, [], [])


def test_minimum_never_increases_execution_ceiling(integrated):
    allocate(integrated)
    for f in integrated[0].info["symbols"][2]["filters"]:
        if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
            f["minNotional"] = "21"
    reports = route(integrated, dry_run=False)
    assert "MIN_NOTIONAL" in {r["state"] for r in reports}
    assert not integrated[1].rows("SELECT * FROM order_intents")


def test_error_code_cannot_leak_remote_strings():
    client = TestnetExecutionClient(
        TestnetConfig(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400, json={"code": "signature=mock-sensitive", "msg": "mock-header"}
            )
        ),
    )
    try:
        with pytest.raises(TestnetError, match="INVALID_RESPONSE") as caught:
            client.request("GET", "/api/v3/exchangeInfo")
        assert caught.value.code is None and "mock-sensitive" not in str(caught.value)
    finally:
        client.close()


def test_quote_rechecked_at_wire_boundary_after_signing_delay(integrated, monkeypatch):
    allocate(integrated)
    exchange, _, manager, _, clock, *_ = integrated
    cid = next(r["client_id"] for r in route(integrated, dry_run=False) if r.get("client_id"))
    original = manager.client.request

    def delayed(method, path, params=None, *, confirm=False):
        if method == "POST":
            clock[0] += 6000
        return original(method, path, params, confirm=confirm)

    monkeypatch.setattr(manager.client, "request", delayed)
    with pytest.raises(TestnetError, match="STALE_TESTNET_QUOTE"):
        manager.check(cid, confirm_test=True)
    assert not any(r.method == "POST" for r in exchange.requests)
