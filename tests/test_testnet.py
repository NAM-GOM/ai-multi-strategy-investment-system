"""All Testnet execution tests use deterministic, network-free exchange simulation."""

import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from trading_system.testnet.cli import main
from trading_system.testnet.client import (
    ALLOWED,
    HOST,
    TestnetConfig,
    TestnetError,
    TestnetExecutionClient,
    sandbox_policy,
    signature,
)
from trading_system.testnet.engine import ExecutionEngine
from trading_system.testnet.risk import RiskEngine, dec, floor_step
from trading_system.testnet.store import Store

NOW = 1_800_000_000_000
INFO = {
    "symbols": [
        {
            "symbol": symbol,
            "status": "TRADING",
            "isSpotTradingAllowed": True,
            "orderTypes": ["LIMIT", "MARKET"],
            "baseAsset": symbol[:-4],
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
                {
                    "filterType": "MARKET_LOT_SIZE",
                    "minQty": "0.01",
                    "maxQty": "1",
                    "stepSize": "0.01",
                },
                {
                    "filterType": "PRICE_FILTER",
                    "minPrice": "0.01",
                    "maxPrice": "1000000",
                    "tickSize": "0.01",
                },
                {"filterType": "MIN_NOTIONAL", "minNotional": "5", "applyToMarket": True},
                {"filterType": "NOTIONAL", "minNotional": "5", "maxNotional": "100"},
                {"filterType": "MAX_NUM_ORDERS", "maxNumOrders": 5},
            ],
        }
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    ],
    "exchangeFilters": [{"filterType": "EXCHANGE_MAX_NUM_ORDERS", "maxNumOrders": 10}],
    "rateLimits": [{"rateLimitType": "ORDERS", "interval": "DAY", "limit": 100}],
}


class Exchange:
    def __init__(self):
        self.orders, self.trades, self.requests = {}, [], []
        self.balances = {
            "USDT": Decimal("100"),
            "BTC": Decimal("1"),
            "ETH": Decimal("1"),
            "SOL": Decimal("1"),
        }
        self.fail_post = None
        self.accept_timeout = False
        self.post_count = 0
        self.info = json.loads(json.dumps(INFO))

    def fill(self, cid, quantity, *, fee="0.01"):
        order = self.orders[cid]
        qty, px = Decimal(quantity), Decimal(order["price"])
        executed = Decimal(order["executedQty"]) + qty
        order["executedQty"] = str(executed)
        order["cummulativeQuoteQty"] = str(Decimal(order["cummulativeQuoteQty"]) + qty * px)
        order["status"] = "FILLED" if executed == Decimal(order["origQty"]) else "PARTIALLY_FILLED"
        symbol = order["symbol"]
        buyer = order["side"] == "BUY"
        self.trades.append(
            dict(
                symbol=symbol,
                id=len(self.trades) + 1,
                orderId=order["orderId"],
                qty=str(qty),
                price=str(px),
                quoteQty=str(qty * px),
                commission=fee,
                commissionAsset="USDT",
                time=NOW + len(self.trades),
                isBuyer=buyer,
            )
        )
        direction = 1 if buyer else -1
        self.balances[symbol[:-4]] += qty * direction
        self.balances["USDT"] -= qty * px * direction + Decimal(fee)

    def handler(self, request):
        sandbox_policy(request)
        self.requests.append(request)
        path, method = request.url.path, request.method
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if path not in ("/api/v3/time", "/api/v3/exchangeInfo"):
            assert request.headers["X-MBX-APIKEY"] == "test-key"
            raw, sig = request.url.query.decode().rsplit("&signature=", 1)
            assert sig == signature(raw, "test-secret")
        if path == "/api/v3/time":
            result = {"serverTime": NOW}
        elif path == "/api/v3/exchangeInfo":
            result = self.info
        elif path == "/api/v3/account":
            result = {
                "balances": [
                    dict(asset=a, free=str(v), locked="0") for a, v in self.balances.items()
                ]
            }
        elif path == "/api/v3/openOrders":
            result = [o for o in self.orders.values() if o["status"] in ("NEW", "PARTIALLY_FILLED")]
        elif path == "/api/v3/myTrades":
            result = [
                t
                for t in self.trades
                if t["symbol"] == params["symbol"]
                and ("orderId" not in params or t["orderId"] == int(params["orderId"]))
            ]
        elif path == "/api/v3/order/test":
            result = {}
        elif method == "POST":
            self.post_count += 1
            if self.fail_post and not self.accept_timeout:
                raise self.fail_post
            cid = params["newClientOrderId"]
            assert cid not in self.orders
            self.orders[cid] = dict(
                symbol=params["symbol"],
                side=params["side"],
                type=params["type"],
                orderId=len(self.orders) + 1,
                clientOrderId=cid,
                status="NEW",
                origQty=params["quantity"],
                price=params["price"],
                executedQty="0",
                cummulativeQuoteQty="0",
            )
            if self.fail_post:
                raise self.fail_post
            result = self.orders[cid]
        else:
            matches = [
                o
                for o in self.orders.values()
                if (
                    o["orderId"] == int(params["orderId"])
                    if "orderId" in params
                    else o["clientOrderId"] == params["origClientOrderId"]
                )
            ]
            if not matches:
                return httpx.Response(400, json={"code": -2013})
            result = matches[0]
            if method == "DELETE":
                original_id = result["clientOrderId"]
                result["status"] = "CANCELED"
                result["clientOrderId"] = "cancel_" + original_id
                result = dict(result, origClientOrderId=original_id)
        return httpx.Response(200, json=result)


@pytest.fixture
def setup(tmp_path):
    exchange = Exchange()
    client = TestnetExecutionClient(
        TestnetConfig("test-key", "test-secret", True),
        transport=httpx.MockTransport(exchange.handler),
    )
    store = Store(tmp_path / "testnet_execution.sqlite")
    engine = ExecutionEngine(client, store, clock=lambda: NOW)
    yield exchange, client, store, engine
    store.close()
    client.close()


def checked(engine, **kwargs):
    cid = engine.create("BTCUSDT", kwargs.get("side", "BUY"), kwargs.get("qty", "0.1"), "100")
    assert engine.check(cid, confirm_test=True)["state"] == "VALIDATED"
    return cid


@pytest.mark.parametrize(
    "url",
    [
        "https://api.binance.com/api/v3/order",
        "https://api1.binance.com/api/v3/order",
        "https://demo-api.binance.com/api/v3/order",
        "http://testnet.binance.vision/api/v3/order",
        "https://testnet.binance.vision.evil.org/api/v3/order",
        "https://testnet.binance.vision:444/api/v3/order",
        "https://u:p@testnet.binance.vision/api/v3/order",
        "https://testnet.binance.vision/sapi/v1/margin/order",
    ],
)
@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_production_order_structurally_denied(url, method):
    with pytest.raises(TestnetError, match="NETWORK_POLICY_DENIED"):
        sandbox_policy(httpx.Request(method, url))


def test_source_policy_and_credentials(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "production-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "production-secret")
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_API_SECRET", raising=False)
    config = TestnetConfig.from_env()
    assert config.api_key == config.api_secret == ""
    source = Path(__file__).parents[1] / "src/trading_system/testnet"
    for file in source.glob("*.py"):
        content = file.read_text()
        assert "BINANCE_API_KEY" not in content and "BINANCE_API_SECRET" not in content
        assert "api.binance.com" not in content
    assert HOST == "https://testnet.binance.vision"
    assert len(ALLOWED) == 9
    with pytest.raises(TypeError):
        TestnetExecutionClient(config, base_url="https://api.binance.com")


def test_signature_known_vector():
    assert signature("what do ya want for nothing?", "Jefe") == (
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    )
    query = "symbol=BTCUSDT&side=BUY&timestamp=1800000000000"
    assert (
        signature(query, "secret")
        == hmac.new(b"secret", query.encode(), hashlib.sha256).hexdigest()
    )


@pytest.mark.parametrize("enabled,confirm", [(False, False), (False, True), (True, False)])
def test_two_locks(enabled, confirm):
    requests = []
    client = TestnetExecutionClient(
        TestnetConfig("k", "s", enabled),
        transport=httpx.MockTransport(lambda r: requests.append(r) or httpx.Response(200, json={})),
    )
    with pytest.raises(TestnetError, match="DRY_RUN"):
        client.request("POST", "/api/v3/order", {}, confirm=confirm)
    assert not requests
    client.close()


@pytest.mark.parametrize(
    "status,kind",
    [
        (302, "REDIRECT_REJECTED"),
        (451, "BLOCKED_ENVIRONMENT"),
        (403, "BLOCKED_ENVIRONMENT"),
        (429, "RATE_LIMIT_HOLD"),
        (418, "RATE_LIMIT_HOLD"),
        (503, "UNKNOWN_EXECUTION"),
    ],
)
def test_http_fail_closed(status, kind):
    requests = []

    def handler(r):
        requests.append(r)
        return httpx.Response(status, json={}, headers={"Location": "https://api.binance.com"})

    client = TestnetExecutionClient(TestnetConfig(), transport=httpx.MockTransport(handler))
    with pytest.raises(TestnetError, match=kind):
        client.request("GET", "/api/v3/time")
    if status in (418, 429):
        with pytest.raises(TestnetError, match="RATE_LIMIT_HOLD"):
            client.request("GET", "/api/v3/time")
    assert len(requests) == 1
    client.close()


def test_decimal_filters(setup):
    exchange, _, _, engine = setup
    cid = checked(engine, qty="0.100999")
    assert engine.intent(cid)["quantity"] == "0.100"
    assert floor_step(Decimal("0.3000000000000000001"), Decimal("0.1")) == Decimal("0.3")
    assert dec("0.1") + dec("0.2") == dec("0.3")
    for value in (0.1, "NaN", "Infinity"):
        with pytest.raises(TestnetError):
            dec(value)
    assert exchange.post_count == 0


@pytest.mark.parametrize(
    "qty,price,side,balances,attempts,opens,kind",
    [
        ("0.01", "100", "BUY", "100", [], [], "MIN_NOTIONAL"),
        ("0.3", "100", "BUY", "100", [], [], "ORDER_LIMIT"),
        ("0.1", "100", "BUY", "5", [], [], "INSUFFICIENT_BALANCE"),
        ("0.1", "100", "SELL", "0.01", [], [], "INSUFFICIENT_BALANCE"),
        ("0.1", "100", "BUY", "100", [{"notional": "10"}] * 3, [], "DAILY_COUNT"),
        ("0.2", "100", "BUY", "100", [{"notional": "15"}] * 2, [], "DAILY_NOTIONAL"),
        ("0.1", "100", "BUY", "100", [], [{"symbol": "BTCUSDT"}], "OPEN_ORDER_LIMIT"),
        ("0.0001", "100", "BUY", "100", [], [], "NON_POSITIVE_ORDER"),
    ],
)
def test_risk_limits(qty, price, side, balances, attempts, opens, kind):
    with pytest.raises(TestnetError, match=kind):
        RiskEngine().validate(
            "BTCUSDT",
            side,
            qty,
            price,
            INFO,
            [{"asset": "USDT" if side == "BUY" else "BTC", "free": balances}],
            opens,
            attempts,
        )


def test_submit_partial_fill_cancel_and_reconcile(setup):
    exchange, _, store, engine = setup
    cid = checked(engine)
    assert engine.submit(cid, confirm_order=True)["state"] == "NEW"
    exchange.fill(cid, "0.04")
    engine.reconcile()
    assert engine.intent(cid)["state"] == "PARTIALLY_FILLED"
    assert engine.cancel(cid, confirm_cancel=True)["state"] == "CANCELED"
    fills = store.rows("SELECT * FROM executions")
    assert len(fills) == 1 and fills[0]["quantity"] == "0.04"
    assert fills[0]["commission"] == "0.01" and fills[0]["commission_asset"] == "USDT"
    engine.reconcile()
    assert len(store.rows("SELECT * FROM executions")) == 1
    assert exchange.post_count == 1


def test_full_fill_and_restart(setup):
    exchange, client, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    exchange.fill(cid, "0.1")
    restarted = ExecutionEngine(client, store, clock=lambda: NOW)
    restarted.reconcile()
    assert restarted.intent(cid)["state"] == "FILLED"
    with pytest.raises(TestnetError, match="DUPLICATE_SUBMISSION"):
        restarted.submit(cid, confirm_order=True)
    assert exchange.post_count == 1


def test_preflight_required_and_dry_run(setup):
    exchange, _, _, engine = setup
    cid = engine.create("BTCUSDT", "BUY", "0.1", "100")
    assert engine.check(cid)["state"] == "DRY_RUN"
    assert engine.submit(cid)["state"] == "DRY_RUN"
    assert not exchange.requests
    with pytest.raises(TestnetError, match="RECENT_ORDER_TEST_REQUIRED"):
        engine.submit(cid, confirm_order=True)


@pytest.mark.parametrize("accepted", [False, True])
def test_timeout_query_without_repost(setup, accepted):
    exchange, _, store, engine = setup
    cid = checked(engine)
    exchange.fail_post = httpx.ReadTimeout("secret must not escape")
    exchange.accept_timeout = accepted
    if accepted:
        assert engine.submit(cid, confirm_order=True)["state"] == "NEW"
    else:
        with pytest.raises(TestnetError, match="UNKNOWN_EXECUTION"):
            engine.submit(cid, confirm_order=True)
        assert engine.intent(cid)["state"] == "UNKNOWN_EXECUTION"
        assert store.session()["hold"] == "UNKNOWN_EXECUTION"
        with pytest.raises(TestnetError):
            engine.create("ETHUSDT", "BUY", "0.1", "100")
    assert exchange.post_count == 1
    assert any(r.url.path == "/api/v3/order" and r.method == "GET" for r in exchange.requests)


def test_crash_reservation_restart(setup):
    exchange, client, store, engine = setup
    cid = checked(engine)
    with store.transaction():
        store.db.execute(
            "UPDATE order_intents SET state='SUBMITTING',attempted_ms=? WHERE client_id=?",
            (NOW, cid),
        )
    restarted = ExecutionEngine(client, store, clock=lambda: NOW)
    with pytest.raises(TestnetError, match="UNKNOWN_EXECUTION"):
        restarted.reconcile()
    with pytest.raises(TestnetError):
        restarted.submit(cid, confirm_order=True)
    assert exchange.post_count == 0


def test_reset_session_separation(setup):
    exchange, client, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    exchange.fill(cid, "0.1")
    engine.reconcile()
    exchange.orders.clear()
    exchange.trades.clear()
    with pytest.raises(TestnetError, match="RESET_SUSPECTED"):
        engine.reconcile()
    assert store.session()["hold"] == "RESET_SUSPECTED"
    new = ExecutionEngine(client, store, clock=lambda: NOW + 1, acknowledge_reset=True)
    new.reconcile()
    assert new.sid != engine.sid
    assert len(store.rows("SELECT * FROM executions")) == 1
    assert len(store.rows("SELECT * FROM testnet_sessions")) == 2


def test_unexplained_balance_change(setup):
    exchange, _, store, engine = setup
    engine.reconcile()
    exchange.balances["USDT"] += Decimal("1")
    with pytest.raises(TestnetError, match="RESET_OR_BALANCE_MISMATCH"):
        engine.reconcile()
    assert store.session()["hold"] == "RESET_OR_BALANCE_MISMATCH"


def test_kill_switch_survives_restart_and_cancel_allowed(setup):
    _, client, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    store.kill(engine.sid, NOW, True)
    restarted = ExecutionEngine(client, store, clock=lambda: NOW)
    with pytest.raises(TestnetError, match="KILL_SWITCH"):
        restarted.create("ETHUSDT", "BUY", "0.1", "100")
    assert restarted.cancel(cid, confirm_cancel=True)["state"] == "CANCELED"


def test_transaction_rollback_fail_closed(setup):
    exchange, _, store, engine = setup
    cid = checked(engine)
    with pytest.raises(TestnetError, match="DB_FAILED"):
        with store.transaction():
            store.db.execute(
                "UPDATE order_intents SET state='SUBMITTING' WHERE client_id=?", (cid,)
            )
            store.db.execute("INSERT INTO nonexistent VALUES(1)")
    assert engine.intent(cid)["state"] == "VALIDATED"
    with pytest.raises(TestnetError):
        engine.submit(cid, confirm_order=True)
    assert exchange.post_count == 0


def test_isolated_database(tmp_path):
    with pytest.raises(TestnetError, match="DEDICATED_DB_REQUIRED"):
        Store(tmp_path / "observer.sqlite")
    target = tmp_path / "testnet_execution.sqlite"
    with sqlite3.connect(target) as db:
        db.execute("CREATE TABLE paper_ledger(id)")
    with pytest.raises(TestnetError, match="FOREIGN_DB_REJECTED"):
        Store(target)


def test_cli_default_offline(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_TESTNET_TRADING_ENABLED", raising=False)
    args = ["--db", str(tmp_path / "testnet_execution.sqlite")]
    assert (
        main(
            [
                "testnet-order-check",
                *args,
                "--symbol",
                "BTCUSDT",
                "--side",
                "BUY",
                "--quantity",
                "0.1",
                "--price",
                "100",
            ]
        )
        == 0
    )
    assert "DRY_RUN" in capsys.readouterr().out
    assert main(["testnet-status", *args]) == 0
    assert "TESTNET_LIVE_NOT_TESTED" in capsys.readouterr().out


def test_market_and_forbidden_endpoints(setup):
    exchange, client, _, engine = setup
    cid = checked(engine)
    params = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"}
    with pytest.raises(TestnetError, match="UNSUPPORTED_ORDER"):
        client.request("POST", "/api/v3/order", params, confirm=True)
    for method, path in (
        ("DELETE", "/api/v3/openOrders"),
        ("POST", "/sapi/v1/asset/transfer"),
        ("GET", "/api/v3/allOrders"),
        ("POST", "/fapi/v1/order"),
    ):
        with pytest.raises(TestnetError, match="NETWORK_POLICY_DENIED"):
            client.request(method, path, confirm=True)
    assert engine.intent(cid)["state"] == "VALIDATED"
    assert exchange.post_count == 0


def test_real_request_hook_blocks_mutated_host(setup, monkeypatch):
    exchange, client, _, _ = setup
    monkeypatch.setattr("trading_system.testnet.client.HOST", "https://api.binance.com")
    with pytest.raises(TestnetError, match="NETWORK_POLICY_DENIED"):
        client.request("GET", "/api/v3/time")
    assert not exchange.requests


def test_tls_and_proxy_policy(monkeypatch):
    captured = {}

    class FakeHTTP:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(httpx, "Client", FakeHTTP)
    TestnetExecutionClient(TestnetConfig())
    assert captured["verify"] is True
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    assert captured["event_hooks"]["request"] == [sandbox_policy]


@pytest.mark.parametrize(
    "filter_name,key,value,kind",
    [
        ("LOT_SIZE", "maxQty", "0.01", "FILTER_MAXIMUM"),
        ("PRICE_FILTER", "minPrice", "101", "FILTER_MINIMUM"),
        ("PRICE_FILTER", "maxPrice", "99", "FILTER_MAXIMUM"),
        ("NOTIONAL", "maxNotional", "9", "MAX_NOTIONAL"),
        ("MIN_NOTIONAL", "minNotional", "21", "MIN_NOTIONAL"),
        ("MAX_NUM_ORDERS", "maxNumOrders", 0, "EXCHANGE_ORDER_LIMIT"),
    ],
)
def test_exchange_filter_cross_checks(setup, filter_name, key, value, kind):
    exchange, _, _, engine = setup
    for f in exchange.info["symbols"][0]["filters"]:
        if f["filterType"] == filter_name:
            f[key] = value
    with pytest.raises(TestnetError, match=kind):
        checked(engine)
    assert exchange.post_count == 0


def test_market_lot_does_not_change_limit_size(setup):
    exchange, _, _, engine = setup
    for f in exchange.info["symbols"][0]["filters"]:
        if f["filterType"] == "MARKET_LOT_SIZE":
            f.update(minQty="100", maxQty="1000", stepSize="100")
    cid = checked(engine)
    assert engine.intent(cid)["quantity"] == "0.1"


def test_exchange_global_and_rate_limits(setup):
    exchange, _, _, engine = setup
    exchange.info["exchangeFilters"][0]["maxNumOrders"] = 0
    with pytest.raises(TestnetError, match="EXCHANGE_ORDER_LIMIT"):
        checked(engine)
    exchange.info["exchangeFilters"][0]["maxNumOrders"] = 5
    exchange.info["rateLimits"][0]["limit"] = 0
    with pytest.raises(TestnetError, match="EXCHANGE_RATE_LIMIT"):
        checked(engine)


def test_stale_preflight(setup):
    exchange, _, _, engine = setup
    cid = checked(engine)
    engine.clock = lambda: NOW + 300_001
    with pytest.raises(TestnetError, match="RECENT_ORDER_TEST_REQUIRED"):
        engine.submit(cid, confirm_order=True)
    assert exchange.post_count == 0


def test_daily_budgets_persist(setup):
    exchange, client, store, engine = setup
    for _ in range(3):
        cid = checked(engine)
        engine.submit(cid, confirm_order=True)
        engine.cancel(cid, confirm_cancel=True)
    restarted = ExecutionEngine(client, store, clock=lambda: NOW)
    with pytest.raises(TestnetError, match="DAILY_COUNT"):
        checked(restarted)
    assert exchange.post_count == 3


def test_sell_held_asset_accounting(setup):
    exchange, _, store, engine = setup
    cid = checked(engine, side="SELL")
    engine.submit(cid, confirm_order=True)
    exchange.fill(cid, "0.1")
    engine.reconcile()
    assert engine.intent(cid)["state"] == "FILLED"
    assert store.rows("SELECT is_buyer FROM executions")[0]["is_buyer"] == 0


def test_missing_execution_and_fee_conflict_fail_closed(setup):
    exchange, _, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    exchange.fill(cid, "0.1")
    engine.reconcile()
    exchange.trades[0]["commission"] = "0.02"
    with pytest.raises(TestnetError, match="TRADE_ID_CONFLICT"):
        engine.reconcile()
    assert store.session()["hold"] == "TRADE_ID_CONFLICT"


def test_missing_fills_rollback(setup):
    exchange, _, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    exchange.orders[cid].update(status="FILLED", executedQty="0.1", cummulativeQuoteQty="10")
    with pytest.raises(TestnetError, match="EXECUTION_MISMATCH"):
        engine.reconcile()
    assert store.session()["hold"] == "EXECUTION_MISMATCH"
    assert engine.intent(cid)["state"] == "NEW"  # whole comparison transaction rolled back


def test_second_process_cannot_replay_reserved_intent(setup, tmp_path):
    exchange, client, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    other_store = Store(tmp_path / "testnet_execution.sqlite")
    try:
        other = ExecutionEngine(client, other_store, clock=lambda: NOW)
        with pytest.raises(TestnetError, match="DUPLICATE_SUBMISSION"):
            other.submit(cid, confirm_order=True)
    finally:
        other_store.close()
    assert exchange.post_count == 1


def test_db_ack_failure_preserves_reservation(setup, monkeypatch, tmp_path):
    exchange, client, store, engine = setup
    cid = checked(engine)
    original = engine._record_order

    def broken_record(*args, **kwargs):
        store.db.execute("INSERT INTO nonexistent VALUES(1)")

    monkeypatch.setattr(engine, "_record_order", broken_record)
    with pytest.raises(TestnetError, match="DB_FAILED"):
        engine.submit(cid, confirm_order=True)
    assert engine.intent(cid)["state"] == "SUBMITTING"
    reopened = Store(tmp_path / "testnet_execution.sqlite")
    try:
        restarted = ExecutionEngine(client, reopened, clock=lambda: NOW)
        restarted.reconcile()
        assert restarted.intent(cid)["state"] == "NEW"
    finally:
        reopened.close()
    monkeypatch.setattr(engine, "_record_order", original)
    assert exchange.post_count == 1


def test_key_change_is_hold_and_new_epoch_preserves_kill(setup):
    _, client, store, engine = setup
    store.kill(engine.sid, NOW, True)
    client.config = TestnetConfig("other-key", "other-secret", True)
    with pytest.raises(TestnetError, match="ACCOUNT_CHANGED_NEW_SESSION_REQUIRED"):
        ExecutionEngine(client, store, clock=lambda: NOW)
    new = ExecutionEngine(client, store, clock=lambda: NOW, acknowledge_reset=True)
    assert new.sid != engine.sid and store.session()["kill"] == 1


def test_offline_session_can_bind_dedicated_key(tmp_path):
    client = TestnetExecutionClient(TestnetConfig(), transport=httpx.MockTransport(lambda r: None))
    store = Store(tmp_path / "testnet_execution.sqlite")
    try:
        offline = ExecutionEngine(client, store, clock=lambda: NOW)
        client.config = TestnetConfig("test-key", "test-secret", True)
        authenticated = ExecutionEngine(client, store, clock=lambda: NOW)
        assert authenticated.sid == offline.sid
    finally:
        store.close()
        client.close()


def test_fresh_cli_process_reads_preserved_journal(setup, tmp_path):
    exchange, _, _, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    exchange.fill(cid, "0.1")
    engine.reconcile()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    env["BINANCE_TESTNET_API_KEY"] = "test-key"
    env["BINANCE_TESTNET_API_SECRET"] = "test-secret"
    env["BINANCE_TESTNET_TRADING_ENABLED"] = ""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "trading_system.testnet.cli",
            "testnet-status",
            "--db",
            str(tmp_path / "testnet_execution.sqlite"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    state = json.loads(result.stdout)
    assert state["mode"] == "DRY_RUN"
    assert state["intents"][0]["client_id"] == cid
    assert state["intents"][0]["state"] == "FILLED"
    assert "test-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("state", ["EXPIRED", "REJECTED"])
def test_exchange_confirmed_terminal_status(setup, state):
    exchange, _, _, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    exchange.orders[cid]["status"] = state
    engine.reconcile()
    assert engine.intent(cid)["state"] == state


def test_blocked_environment_is_persisted(setup):
    _, client, store, engine = setup
    client.close()
    client._http = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(451, json={"msg": "restricted location"})
        ),
        event_hooks={"request": [sandbox_policy]},
    )
    with pytest.raises(TestnetError, match="BLOCKED_ENVIRONMENT"):
        engine.reconcile()
    assert store.session()["hold"] == "BLOCKED_ENVIRONMENT"
    assert store.rows("SELECT kind FROM risk_events")[-1]["kind"] == "BLOCKED_ENVIRONMENT"


def test_risk_rejection_is_journaled(setup):
    _, _, store, engine = setup
    cid = engine.create("BTCUSDT", "BUY", "1", "100")
    with pytest.raises(TestnetError, match="ORDER_LIMIT"):
        engine.check(cid)
    assert store.rows("SELECT kind FROM risk_events")[-1]["kind"] == "ORDER_LIMIT"


def test_external_open_order_blocks_restart(setup):
    exchange, _, store, engine = setup
    exchange.orders["manual"] = {"clientOrderId": "manual", "status": "NEW"}
    with pytest.raises(TestnetError, match="EXTERNAL_OPEN_ORDER"):
        engine.reconcile()
    assert store.session()["hold"] == "EXTERNAL_OPEN_ORDER"


def test_second_pending_intent_is_blocked(setup):
    exchange, _, _, engine = setup
    first, second = checked(engine), checked(engine)
    engine.submit(first, confirm_order=True)
    with pytest.raises(TestnetError, match="PENDING_ORDER_BLOCK"):
        engine.submit(second, confirm_order=True)
    assert exchange.post_count == 1


def test_cancel_alias_is_kept_across_restart(setup):
    exchange, client, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    engine.cancel(cid, confirm_cancel=True)
    order = store.rows("SELECT * FROM exchange_orders")[0]
    assert order["client_id"] == cid
    assert json.loads(order["payload"])["clientOrderId"] == "cancel_" + cid
    restarted = ExecutionEngine(client, store, clock=lambda: NOW)
    assert restarted.status(cid)["state"] == "CANCELED"
    restarted.reconcile()
    assert exchange.post_count == 1


def test_cancel_ack_loss_queries_stable_order_id(setup, monkeypatch):
    exchange, client, store, engine = setup
    cid = checked(engine)
    engine.submit(cid, confirm_order=True)
    original = client.request

    def drop_ack(method, path, *args, **kwargs):
        response = original(method, path, *args, **kwargs)
        if method == "DELETE":
            raise TestnetError("UNKNOWN_TRANSPORT")
        return response

    monkeypatch.setattr(client, "request", drop_ack)
    assert engine.cancel(cid, confirm_cancel=True)["state"] == "CANCELED"
    assert store.session()["hold"] == ""
    assert exchange.post_count == 1


def test_order_fill_pagination_starts_at_oldest(setup, monkeypatch):
    _, client, _, engine = setup
    requests = []

    def page(method, path, params):
        requests.append(dict(params))
        start = params["fromId"]
        return [{"id": i} for i in range(start, min(start + 1000, 1001))]

    monkeypatch.setattr(client, "request", page)
    result = engine._trades("BTCUSDT", order_id=7)
    assert len(result) == 1001
    assert requests[0]["fromId"] == 0 and requests[1]["fromId"] == 1000
    assert all(p["orderId"] == 7 for p in requests)


def test_cli_handles_failure_to_journal_error(tmp_path, monkeypatch, capsys):
    def blocked(*args, **kwargs):
        raise TestnetError("BLOCKED_ENVIRONMENT")

    def failed(*args, **kwargs):
        raise TestnetError("DB_FAILED")

    monkeypatch.setattr(ExecutionEngine, "check", blocked)
    monkeypatch.setattr(Store, "hold", failed)
    monkeypatch.delenv("BINANCE_TESTNET_API_KEY", raising=False)
    assert (
        main(
            [
                "testnet-order-check",
                "--db",
                str(tmp_path / "testnet_execution.sqlite"),
                "--symbol",
                "BTCUSDT",
                "--side",
                "BUY",
                "--quantity",
                "0.1",
                "--price",
                "100",
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["state"] == "DB_FAILED"
