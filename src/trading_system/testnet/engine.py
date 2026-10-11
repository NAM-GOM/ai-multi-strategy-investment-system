"""Persist-before-send lifecycle and fail-closed reconciliation."""

import hashlib
import json
from decimal import Decimal
from functools import wraps
from time import time
from uuid import uuid4

from .client import SYMBOLS, TestnetError
from .risk import RiskEngine, dec

STATES = frozenset({"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "REJECTED"})
TERMINAL = frozenset({"FILLED", "CANCELED", "EXPIRED", "REJECTED"})
PENDING = ("SUBMITTING", "UNKNOWN_EXECUTION", "NEW", "PARTIALLY_FILLED")


def journal_failures(operation):
    @wraps(operation)
    def run(self, *args, **kwargs):
        try:
            return operation(self, *args, **kwargs)
        except TestnetError as error:
            self._failure(error)
            raise

    return run


class ExecutionEngine:
    def __init__(self, client, store, *, clock=None, acknowledge_reset=False):
        self.client, self.store = client, store
        self.clock = clock or (lambda: int(time() * 1000))
        self.risk = RiskEngine()
        fingerprint = hashlib.sha256(client.config.api_key.encode()).hexdigest()
        self.sid = store.start_session(
            fingerprint, self.clock(), acknowledge_reset=acknowledge_reset
        )

    def _failure(self, error):
        if self.store.failed or error.kind == "DB_FAILED":
            return
        with self.store.transaction():
            self.store.db.execute(
                "INSERT INTO risk_events(session_id,time_ms,kind) VALUES(?,?,?)",
                (self.sid, self.clock(), error.kind),
            )
            if error.kind in ("BLOCKED_ENVIRONMENT", "RATE_LIMIT_HOLD"):
                self.store.db.execute(
                    "UPDATE testnet_sessions SET hold=? WHERE id=?",
                    (error.kind, self.sid),
                )
                self.store.event(self.sid, self.clock(), error.kind)

    def guard(self):
        session = self.store.session()
        if self.store.failed or not session or session["id"] != self.sid:
            raise TestnetError("DB_OR_SESSION_CHANGED")
        if session["kill"]:
            raise TestnetError("KILL_SWITCH")
        if session["hold"]:
            raise TestnetError(session["hold"])

    def intent(self, client_id):
        rows = self.store.rows(
            "SELECT * FROM order_intents WHERE client_id=? AND session_id=?", (client_id, self.sid)
        )
        if not rows:
            raise TestnetError("INTENT_NOT_FOUND")
        return rows[0]

    def attempts(self):
        now = self.clock()
        start = now - now % 86_400_000  # UTC day; consistent across Windows/Linux.
        return self.store.rows(
            "SELECT * FROM order_intents WHERE attempted_ms>=?", (start,)
        )  # Limits span session changes too.

    @journal_failures
    def create(self, symbol, side, quantity, price):
        qty, px = dec(quantity), dec(price)
        if symbol not in SYMBOLS or side not in ("BUY", "SELL") or qty <= 0 or px <= 0:
            raise TestnetError("INVALID_INTENT")
        client_id = "e01_" + uuid4().hex
        with self.store.transaction():
            self.guard()
            self.store.db.execute(
                "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)",
                (
                    client_id,
                    self.sid,
                    self.clock(),
                    symbol,
                    side,
                    str(qty),
                    str(px),
                    str(qty * px),
                    "INTENT_CREATED",
                ),
            )
            self.store.event(self.sid, self.clock(), "INTENT_CREATED", client_id)
        return client_id

    def _validate(self, intent, info, account, opens):
        if not account.get("canTrade", True):
            raise TestnetError("ACCOUNT_TRADING_DISABLED")
        return self.risk.validate(
            intent["symbol"],
            intent["side"],
            intent["quantity"],
            intent["price"],
            info,
            account["balances"],
            opens,
            self.attempts(),
        )

    @journal_failures
    def check(self, client_id, *, confirm_test=False):
        self.guard()
        intent = self.intent(client_id)
        if intent["attempted_ms"] is not None:
            raise TestnetError("DUPLICATE_SUBMISSION")
        if not (self.client.config.trading_enabled and confirm_test):
            if dec(intent["notional"]) > self.risk.max_order:
                raise TestnetError("ORDER_LIMIT")
            return {
                "state": "DRY_RUN",
                "client_id": client_id,
                "exchange_validation": "NOT_REQUESTED",
            }
        self.reconcile()
        self.guard()
        info = self.client.request("GET", "/api/v3/exchangeInfo")
        account = self.client.request("GET", "/api/v3/account")
        opens = self.client.request("GET", "/api/v3/openOrders")
        order = self._validate(intent, info, account, opens)
        self.client.request("POST", "/api/v3/order/test", order.params(client_id), confirm=True)
        with self.store.transaction():
            self.guard()
            if self.intent(client_id)["attempted_ms"] is not None:
                raise TestnetError("DUPLICATE_SUBMISSION")
            self.store.db.execute(
                "UPDATE order_intents SET state='VALIDATED',quantity=?,price=?,notional=?,"
                "checked_ms=? WHERE client_id=?",
                (
                    str(order.quantity),
                    str(order.price),
                    str(order.notional),
                    self.clock(),
                    client_id,
                ),
            )
            self.store.event(self.sid, self.clock(), "ORDER_TEST_PASSED", client_id)
        return {"state": "VALIDATED", "client_id": client_id, "quantity": str(order.quantity)}

    @journal_failures
    def submit(self, client_id, *, confirm_order=False):
        self.guard()
        if not (self.client.config.trading_enabled and confirm_order):
            return {"state": "DRY_RUN", "client_id": client_id}
        initial = self.intent(client_id)
        if initial["attempted_ms"] is not None:
            raise TestnetError("DUPLICATE_SUBMISSION")
        if initial["checked_ms"] is None or self.clock() - initial["checked_ms"] > 300_000:
            raise TestnetError("RECENT_ORDER_TEST_REQUIRED")
        self.reconcile()
        # Serialize validation + durable reservation. A second process sees SUBMITTING.
        with self.store.transaction():
            self.guard()
            intent = self.intent(client_id)
            if intent["attempted_ms"] is not None:
                raise TestnetError("DUPLICATE_SUBMISSION")
            pending = self.store.rows(
                "SELECT state FROM order_intents WHERE session_id=? AND state IN (?,?,?,?)",
                (self.sid, *PENDING),
            )
            if pending:
                raise TestnetError("PENDING_ORDER_BLOCK")
            info = self.client.request("GET", "/api/v3/exchangeInfo")
            account = self.client.request("GET", "/api/v3/account")
            opens = self.client.request("GET", "/api/v3/openOrders")
            order = self._validate(intent, info, account, opens)
            if order.quantity != dec(intent["quantity"]) or order.price != dec(intent["price"]):
                raise TestnetError("FILTER_CHANGED_REPEAT_ORDER_TEST")
            self.store.db.execute(
                "UPDATE order_intents SET state='SUBMITTING',attempted_ms=? WHERE client_id=?",
                (self.clock(), client_id),
            )
            self.store.event(self.sid, self.clock(), "SUBMITTING", client_id)
        # No transaction wraps POST: SUBMITTING survives process loss before/after send.
        try:
            self.guard()
            response = self.client.request(
                "POST", "/api/v3/order", order.params(client_id), confirm=True
            )
            with self.store.transaction():
                self._record_order(response, client_id)
        except TestnetError as error:
            if error.kind == "DB_FAILED":
                raise
            self._failure(error)
            # Even API errors never manufacture REJECTED. Query the same ID, never re-POST.
            return self._resolve_uncertain(client_id)
        self.reconcile()
        return self.intent(client_id)

    def _resolve_uncertain(self, client_id):
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE order_intents SET state='UNKNOWN_EXECUTION' WHERE client_id=?", (client_id,)
            )
            self.store.event(self.sid, self.clock(), "UNKNOWN_EXECUTION", client_id)
        try:
            self.status(client_id)
            self.reconcile()
            return self.intent(client_id)
        except TestnetError as error:
            if error.kind == "DB_FAILED":
                raise
            self.store.hold(self.sid, self.clock(), "UNKNOWN_EXECUTION")
            raise TestnetError("UNKNOWN_EXECUTION") from None

    def _record_order(self, data, client_id=None):
        try:
            symbol, oid, cid = data["symbol"], data["orderId"], data["clientOrderId"]
            state = data["status"]
            qty = dec(data["executedQty"])
            quote = dec(data["cummulativeQuoteQty"])
            if symbol not in SYMBOLS or type(oid) is not int or state not in STATES:
                raise TestnetError("INVALID_ORDER_RESPONSE")
            if client_id and cid != client_id:
                known_order = self.store.rows(
                    "SELECT * FROM exchange_orders WHERE session_id=? AND symbol=? AND order_id=?",
                    (self.sid, symbol, oid),
                )
                # Cancellation assigns a new exchange client ID. Preserve the local
                # intent ID and validate the returned original ID or recorded alias.
                cancellation = data.get("origClientOrderId") == client_id
                known_alias = bool(known_order) and (
                    known_order[0]["client_id"] == client_id
                    and json.loads(known_order[0]["payload"])["clientOrderId"] == cid
                )
                canceled_by_id = bool(known_order) and (
                    known_order[0]["client_id"] == client_id and state == "CANCELED"
                )
                if not (cancellation or known_alias or canceled_by_id):
                    raise TestnetError("ORDER_ID_MISMATCH")
                cid = client_id
            intent = self.intent(cid)
            if symbol != intent["symbol"] or data["side"] != intent["side"]:
                raise TestnetError("ORDER_ID_MISMATCH")
            if data["type"] != "LIMIT" or dec(data["origQty"]) != dec(intent["quantity"]):
                raise TestnetError("ORDER_ID_MISMATCH")
            if dec(data["price"]) != dec(intent["price"]) or not 0 <= qty <= dec(
                intent["quantity"]
            ):
                raise TestnetError("INVALID_ORDER_RESPONSE")
            if quote < 0 or (state == "FILLED" and qty != dec(intent["quantity"])):
                raise TestnetError("INVALID_ORDER_RESPONSE")
            if (
                (state == "NEW" and qty != 0)
                or (state == "PARTIALLY_FILLED" and not 0 < qty < dec(intent["quantity"]))
                or (qty == 0 and quote != 0)
                or (qty > 0 and quote <= 0)
            ):
                raise TestnetError("INVALID_ORDER_RESPONSE")
            previous = self.store.rows(
                "SELECT * FROM exchange_orders WHERE session_id=? AND client_id=?", (self.sid, cid)
            )
            if previous and (
                previous[0]["order_id"] != oid
                or dec(previous[0]["executed_qty"]) > qty
                or dec(previous[0]["quote_qty"]) > quote
                or (previous[0]["status"] in TERMINAL and previous[0]["status"] != state)
            ):
                raise TestnetError("RESET_OR_ORDER_REGRESSION")
            other = self.store.rows(
                "SELECT client_id FROM exchange_orders "
                "WHERE session_id=? AND symbol=? AND order_id=?",
                (self.sid, symbol, oid),
            )
            if other and other[0]["client_id"] != cid:
                raise TestnetError("DUPLICATE_ORDER_ID")
            self.store.db.execute(
                "INSERT INTO exchange_orders VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(session_id,symbol,order_id) DO UPDATE SET "
                "status=excluded.status,executed_qty=excluded.executed_qty,"
                "quote_qty=excluded.quote_qty,updated_ms=excluded.updated_ms,payload=excluded.payload",
                (
                    self.sid,
                    symbol,
                    oid,
                    cid,
                    state,
                    str(qty),
                    str(quote),
                    self.clock(),
                    json.dumps(
                        {
                            k: data[k]
                            for k in (
                                "symbol",
                                "orderId",
                                "clientOrderId",
                                "status",
                                "side",
                                "type",
                                "origQty",
                                "price",
                                "executedQty",
                                "cummulativeQuoteQty",
                            )
                        },
                        sort_keys=True,
                    ),
                ),
            )
            self.store.db.execute(
                "UPDATE order_intents SET state=? WHERE client_id=?", (state, cid)
            )
            self.store.event(self.sid, self.clock(), "ORDER_STATUS", {"id": cid, "status": state})
        except KeyError, TypeError, ValueError:
            raise TestnetError("INVALID_ORDER_RESPONSE") from None

    @journal_failures
    def status(self, client_id):
        intent = self.intent(client_id)
        data = self.client.request("GET", "/api/v3/order", self._order_query(intent))
        with self.store.transaction():
            self._record_order(data, client_id)
        return self.intent(client_id)

    def _order_query(self, intent):
        known = self.store.rows(
            "SELECT order_id FROM exchange_orders WHERE session_id=? AND client_id=?",
            (self.sid, intent["client_id"]),
        )
        if known:
            return dict(symbol=intent["symbol"], orderId=known[0]["order_id"])
        return dict(symbol=intent["symbol"], origClientOrderId=intent["client_id"])

    @journal_failures
    def cancel(self, client_id, *, confirm_cancel=False):
        # Cancellation remains available while kill/hold is active to reduce exposure.
        intent = self.intent(client_id)
        if not (self.client.config.trading_enabled and confirm_cancel):
            return {"state": "DRY_RUN", "client_id": client_id}
        self.status(client_id)
        try:
            data = self.client.request(
                "DELETE",
                "/api/v3/order",
                self._order_query(intent),
                confirm=True,
            )
            with self.store.transaction():
                self._record_order(data, client_id)
        except TestnetError as error:
            if error.kind == "DB_FAILED":
                raise
            self._failure(error)
            return self._resolve_uncertain(client_id)
        self.reconcile()
        return self.intent(client_id)

    def _trades(self, symbol, *, order_id=None):
        params = dict(symbol=symbol, limit=1000)
        if order_id is not None:
            params["orderId"] = order_id
            params["fromId"] = 0  # Start at oldest fill, not the default latest 1000.
        result = []
        for _ in range(100):
            page = self.client.request("GET", "/api/v3/myTrades", params)
            if not isinstance(page, list):
                raise TestnetError("INVALID_TRADES")
            result.extend(page)
            if len(page) < 1000:
                return result
            next_id = max(t["id"] for t in page) + 1
            if next_id <= params.get("fromId", -1):
                break
            params["fromId"] = next_id
        raise TestnetError("TRADE_HISTORY_INCOMPLETE")

    @journal_failures
    def reconcile(self):
        try:
            return self._reconcile()
        except TestnetError as error:
            if error.kind != "DB_FAILED":
                self.store.hold(self.sid, self.clock(), error.kind)
            raise
        except KeyError, TypeError, ValueError:
            self.store.hold(self.sid, self.clock(), "INVALID_RECONCILIATION_RESPONSE")
            raise TestnetError("INVALID_RECONCILIATION_RESPONSE") from None

    def _reconcile(self):
        # One SQLite writer across read/compare/journal prevents concurrent snapshots.
        with self.store.transaction():
            session = self.store.session()
            if session["id"] != self.sid:
                raise TestnetError("SESSION_CHANGED")
            opens = self.client.request("GET", "/api/v3/openOrders")
            intents = self.store.rows(
                "SELECT * FROM order_intents WHERE session_id=? AND attempted_ms IS NOT NULL",
                (self.sid,),
            )
            known = {i["client_id"] for i in intents}
            stored_orders = self.store.rows(
                "SELECT symbol,order_id FROM exchange_orders WHERE session_id=?", (self.sid,)
            )
            known_ids = {(o["symbol"], o["order_id"]) for o in stored_orders}
            if any(
                o["clientOrderId"] not in known
                and (o.get("symbol"), o.get("orderId")) not in known_ids
                for o in opens
            ):
                raise TestnetError("EXTERNAL_OPEN_ORDER")
            # Check terminal anchors too: missing historical orders imply reset/retention ambiguity.
            for intent in intents:
                try:
                    data = self.client.request(
                        "GET",
                        "/api/v3/order",
                        self._order_query(intent),
                    )
                except TestnetError as error:
                    if error.code == -2013:
                        raise TestnetError(
                            "UNKNOWN_EXECUTION"
                            if intent["state"] in ("SUBMITTING", "UNKNOWN_EXECUTION")
                            else "RESET_SUSPECTED"
                        ) from None
                    raise
                self._record_order(data, intent["client_id"])
            orders = self.store.rows(
                "SELECT * FROM exchange_orders WHERE session_id=?", (self.sid,)
            )
            active = {(o["symbol"], o["order_id"]) for o in orders if o["status"] not in TERMINAL}
            if active != {(o["symbol"], o["orderId"]) for o in opens}:
                raise TestnetError("OPEN_ORDER_MISMATCH")
            previous_exec = self.store.rows(
                "SELECT * FROM executions WHERE session_id=?", (self.sid,)
            )
            seen_trades = {(t["symbol"], t["trade_id"]) for t in previous_exec}
            known_orders = {(o["symbol"], o["order_id"]) for o in orders}
            order_sides = {
                (o["symbol"], o["order_id"]): self.intent(o["client_id"])["side"] for o in orders
            }
            existing_trades = {(t["symbol"], t["trade_id"]): t for t in previous_exec}
            trades = []
            for symbol in sorted(SYMBOLS):
                trades.extend(self._trades(symbol))
            for order in orders:
                trades.extend(self._trades(order["symbol"], order_id=order["order_id"]))
            delta = {}

            def change(asset, amount):
                delta[asset] = delta.get(asset, Decimal(0)) + amount

            for trade in trades:
                symbol, tid = trade["symbol"], trade["id"]
                if (symbol, trade["orderId"]) not in known_orders:
                    if trade["time"] >= session["created_ms"]:
                        raise TestnetError("EXTERNAL_EXECUTION")
                    continue  # Historical activity belongs to an earlier epoch.
                quantity, price = dec(trade["qty"]), dec(trade["price"])
                quote, fee = dec(trade["quoteQty"]), dec(trade["commission"])
                if quantity <= 0 or price <= 0 or quote <= 0 or fee < 0:
                    raise TestnetError("INVALID_EXECUTION")
                if (
                    type(tid) is not int
                    or type(trade["isBuyer"]) is not bool
                    or type(trade["orderId"]) is not int
                    or order_sides[(symbol, trade["orderId"])]
                    != ("BUY" if trade["isBuyer"] else "SELL")
                ):
                    raise TestnetError("INVALID_EXECUTION")
                if (symbol, tid) in seen_trades:
                    old = existing_trades[(symbol, tid)]
                    if (
                        old["order_id"] != trade["orderId"]
                        or dec(old["quantity"]) != quantity
                        or dec(old["price"]) != price
                        or dec(old["quote_qty"]) != quote
                        or dec(old["commission"]) != fee
                        or old["commission_asset"] != trade["commissionAsset"]
                        or bool(old["is_buyer"]) != trade["isBuyer"]
                    ):
                        raise TestnetError("TRADE_ID_CONFLICT")
                    continue
                self.store.db.execute(
                    "INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        self.sid,
                        symbol,
                        tid,
                        trade["orderId"],
                        str(price),
                        str(quantity),
                        str(quote),
                        str(fee),
                        trade["commissionAsset"],
                        trade["time"],
                        int(trade["isBuyer"]),
                    ),
                )
                seen_trades.add((symbol, tid))
                existing_trades[(symbol, tid)] = {
                    "order_id": trade["orderId"],
                    "quantity": str(quantity),
                    "price": str(price),
                    "quote_qty": str(quote),
                    "commission": str(fee),
                    "commission_asset": trade["commissionAsset"],
                    "is_buyer": trade["isBuyer"],
                }
                direction = 1 if trade["isBuyer"] else -1
                change(symbol.removesuffix("USDT"), quantity * direction)
                change("USDT", -quote * direction)
                change(trade["commissionAsset"], -fee)
            all_exec = self.store.rows("SELECT * FROM executions WHERE session_id=?", (self.sid,))
            for order in orders:
                matched = [
                    t
                    for t in all_exec
                    if t["symbol"] == order["symbol"] and t["order_id"] == order["order_id"]
                ]
                if sum((dec(t["quantity"]) for t in matched), Decimal(0)) != dec(
                    order["executed_qty"]
                ) or sum((dec(t["quote_qty"]) for t in matched), Decimal(0)) != dec(
                    order["quote_qty"]
                ):
                    raise TestnetError("EXECUTION_MISMATCH")
            account = self.client.request("GET", "/api/v3/account")
            current = {}
            for b in account["balances"]:
                free, locked = dec(b["free"]), dec(b["locked"])
                if free < 0 or locked < 0 or b["asset"] in current:
                    raise TestnetError("INVALID_BALANCES")
                current[b["asset"]] = free + locked
            latest = self.store.rows(
                "SELECT snapshot_id FROM balance_snapshots WHERE session_id=? "
                "ORDER BY time_ms DESC,rowid DESC LIMIT 1",
                (self.sid,),
            )
            if latest:
                previous = self.store.rows(
                    "SELECT * FROM balance_snapshots WHERE session_id=? AND snapshot_id=?",
                    (self.sid, latest[0]["snapshot_id"]),
                )
                totals = {b["asset"]: dec(b["free"]) + dec(b["locked"]) for b in previous}
                for asset in current.keys() | totals.keys() | delta.keys():
                    if current.get(asset, Decimal(0)) != (
                        totals.get(asset, Decimal(0)) + delta.get(asset, Decimal(0))
                    ):
                        raise TestnetError("RESET_OR_BALANCE_MISMATCH")
            snapshot = uuid4().hex
            for b in account["balances"]:
                self.store.db.execute(
                    "INSERT INTO balance_snapshots VALUES(?,?,?,?,?,?)",
                    (
                        self.sid,
                        snapshot,
                        self.clock(),
                        b["asset"],
                        str(dec(b["free"])),
                        str(dec(b["locked"])),
                    ),
                )
            self.store.event(
                self.sid,
                self.clock(),
                "RECONCILED",
                {
                    "open_orders": len(opens),
                    "orders": len(orders),
                    "executions": len(all_exec),
                    "balance_delta": {k: str(v) for k, v in delta.items()},
                },
            )
        return {"state": "RECONCILED", "session": self.sid, "hold": self.store.session()["hold"]}
