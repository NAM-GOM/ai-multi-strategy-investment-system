"""Reuse verified lifecycle; integrated orders require strategy ownership and fresh signals."""

import asyncio
from contextlib import nullcontext

from trading_system.observer.model import digest
from trading_system.testnet.client import TestnetError
from trading_system.testnet.engine import ExecutionEngine
from trading_system.testnet.risk import dec

from .config import EXPERIMENT, T1, SafetyConfig
from .position_manager import PositionManager
from .risk_engine import RiskEngine
from .signal_router import SignalRouter, observer_reader
from .testnet_client import read_quote


class OrderManager(ExecutionEngine):
    def __init__(
        self,
        client,
        store,
        *,
        clock=None,
        acknowledge_reset=False,
        safety=None,
        quote_provider=None,
    ):
        super().__init__(client, store, clock=clock, acknowledge_reset=acknowledge_reset)
        self.safety = safety or SafetyConfig()
        self.risk = RiskEngine(self.safety)
        self.positions = PositionManager(store, self.sid)
        self.quote_provider = quote_provider or (lambda symbol: asyncio.run(read_quote(symbol)))
        self._approved_market = None
        self.client._execution_send_guard = self._send_guard

    def _send_guard(self, client_id):
        self.guard()
        owners = self.store.rows("SELECT * FROM signal_receipts WHERE client_id=?", (client_id,))
        if not owners:
            return
        if not self._approved_market or self._approved_market[0] != client_id:
            raise TestnetError("VALIDATED_QUOTE_REQUIRED")
        _, quote, reference = self._approved_market
        self.risk.prices(quote, reference.price, reference.received_at_ms, self.clock())
        if not 0 <= self.clock() - reference.event_time_ms <= self.safety.max_reference_age_ms:
            raise TestnetError("STALE_PRODUCTION_REFERENCE")
        point = self.store.rows("SELECT * FROM router_checkpoints WHERE session_id=?", (self.sid,))[
            0
        ]
        router = SignalRouter(
            self.positions, point["observer_path"], point["market_path"], safety=self.safety
        )
        with observer_reader(point["observer_path"]) as db:
            router.health(db)
        owner = owners[0]
        if owner["outcome"] != "RISK_STOP_INTENT":
            if (
                not 0
                <= self.clock() - owner["bar_open_ms"] - 14_400_000
                <= self.safety.max_signal_age_ms
            ):
                raise TestnetError("STALE_OR_UNCONFIRMED_SIGNAL")

    def _validate(self, intent, info, account, opens):
        order = super()._validate(intent, info, account, opens)
        owners = self.store.rows(
            "SELECT * FROM signal_receipts WHERE client_id=?", (intent["client_id"],)
        )
        allocations = self.store.rows(
            "SELECT * FROM strategy_allocations WHERE session_id=?", (self.sid,)
        )
        if not owners:
            if allocations:
                raise TestnetError("UNATTRIBUTED_ORDER_BLOCKED")
            # Faucet balances aren't strategy positions; prohibit adding to locally owned buys.
            fills = self.store.rows(
                "SELECT * FROM executions WHERE session_id=? AND symbol=?", (self.sid, order.symbol)
            )
            owned = sum((dec(f["quantity"]) * (1 if f["is_buyer"] else -1) for f in fills), dec(0))
            if order.side == "BUY" and owned > 0:
                raise TestnetError("NO_PYRAMIDING")
            return self._risk_approved(intent, order)
        owner = owners[0]
        if owner["session_id"] != self.sid or owner["strategy_id"] != T1:
            raise TestnetError("STRATEGY_NOT_ENABLED")
        self.positions.verify(T1)
        point = self.store.rows("SELECT * FROM router_checkpoints WHERE session_id=?", (self.sid,))[
            0
        ]
        router = SignalRouter(
            self.positions, point["observer_path"], point["market_path"], safety=self.safety
        )
        if owner["outcome"] == "RISK_STOP_INTENT":
            with observer_reader(point["observer_path"]) as db:
                router.health(db)
            from trading_system.observer.audit import source_audit

            source_audit()
            reference = self._reference(order.symbol, point["market_path"])
            quote = self.quote_provider(order.symbol)
            self.risk.prices(quote, reference.price, reference.received_at_ms, self.clock())
            self._approved_market = (intent["client_id"], quote, reference)
            position = next(
                (p for p in self.positions.positions() if p["symbol"] == order.symbol), None
            )
            if (
                order.side != "SELL"
                or not position
                or order.quantity > dec(position["quantity"])
                or reference.price > dec(position["initial_stop"])
                or abs(order.price / quote.bid - 1) > self.safety.max_spread
            ):
                raise TestnetError("RISK_STOP_NOT_EXECUTABLE")
            return self._risk_approved(intent, order)
        with observer_reader(point["observer_path"]) as db:
            row = db.execute(
                "SELECT rowid AS sequence,* FROM signal_decisions WHERE strategy_id=? "
                "AND symbol=? AND bar_open_ms=? AND version='0.1'",
                (T1, owner["symbol"], owner["bar_open_ms"]),
            ).fetchone()
            if not row or row["decision_hash"] != owner["decision_hash"]:
                raise TestnetError("SIGNAL_HASH_MISMATCH")
            decision, reference = router.validate_row(db, row, self.clock())
        quote = self.quote_provider(order.symbol)
        if quote.symbol != order.symbol:
            raise TestnetError("INVALID_TESTNET_QUOTE")
        self.risk.prices(quote, reference.price, reference.received_at_ms, self.clock())
        self._approved_market = (intent["client_id"], quote, reference)
        executable = quote.ask if order.side == "BUY" else quote.bid
        if abs(order.price / executable - 1) > self.safety.max_spread:
            raise TestnetError("INTENT_PRICE_CHANGED")
        if (decision.decision == "ENTRY_CANDIDATE") != (order.side == "BUY"):
            raise TestnetError("SIGNAL_SIDE_MISMATCH")
        position = next(
            (p for p in self.positions.positions() if p["symbol"] == order.symbol), None
        )
        owned = dec(position["quantity"]) if position else dec(0)
        if order.side == "BUY":
            if owned > 0:
                raise TestnetError("NO_PYRAMIDING")
            if dec(self.positions.allocation()["cash"]) < order.notional * dec("1.01"):
                raise TestnetError("INSUFFICIENT_STRATEGY_CAPITAL")
            # Execution ceilings cannot override the frozen risk or allocation caps.
            atr = dec(owner["atr"])
            capital = dec(self.positions.allocation()["cash"])
            for p in self.positions.positions():
                if dec(p["quantity"]) > 0:
                    from trading_system.persistence.repository import MarketRepository

                    with MarketRepository(point["market_path"]) as repository:
                        prices = repository.recent_prices(p["symbol"], 1)
                    if (
                        not prices
                        or not 0
                        <= self.clock() - prices[-1].received_at_ms
                        <= self.safety.max_reference_age_ms
                    ):
                        raise TestnetError("STALE_POSITION_MARK")
                    capital += dec(p["quantity"]) * prices[-1].price
            if order.quantity * 3 * atr > capital * dec("0.005") or order.notional > capital * dec(
                "0.333"
            ):
                raise TestnetError("FROZEN_RISK_CAP")
        elif order.quantity > owned:
            raise TestnetError("STRATEGY_OVERSOLD")
        return self._risk_approved(intent, order)

    def _risk_approved(self, intent, order):
        context = nullcontext() if self.store.db.in_transaction else self.store.transaction()
        with context:
            self.guard()
            self.store.db.execute(
                "INSERT INTO risk_events(session_id,time_ms,kind,client_id) VALUES(?,?,?,?)",
                (self.sid, self.clock(), "RISK_APPROVED", intent["client_id"]),
            )
            if intent["checked_ms"] is None and intent["attempted_ms"] is None:
                self.store.db.execute(
                    "UPDATE order_intents SET state='RISK_APPROVED' WHERE client_id=?",
                    (intent["client_id"],),
                )
        return order

    def _reference(self, symbol, market_path):
        from trading_system.persistence.repository import MarketRepository

        with MarketRepository(market_path) as repository:
            prices = repository.recent_prices(symbol, 1)
            if not repository.integrity() or any(
                g["status"] != "RESOLVED" for g in repository.gaps()
            ):
                raise TestnetError("M03_DATA_HOLD")
        if (
            not prices
            or prices[-1].source != "binance_spot"
            or not 0 <= self.clock() - prices[-1].event_time_ms <= self.safety.max_reference_age_ms
        ):
            raise TestnetError("STALE_PRODUCTION_REFERENCE")
        return prices[-1]

    def protective_intents(self, router, quotes, info, balances):
        """Frozen initial 3 ATR stop; risk authority creates its own attributed exit intent."""
        self.automation_guard()
        from trading_system.observer.audit import source_audit

        source_audit()
        with observer_reader(router.observer_path) as db:
            router.health(db)
        created = []
        for position in self.positions.positions():
            quantity = dec(position["quantity"])
            if quantity <= 0:
                continue
            symbol = position["symbol"]
            reference = self._reference(symbol, router.market_path)
            quote = quotes.get(symbol)
            if quote is None or quote.symbol != symbol:
                raise TestnetError("TESTNET_QUOTE_REQUIRED")
            self.risk.prices(quote, reference.price, reference.received_at_ms, self.clock())
            if reference.price > dec(position["initial_stop"]):
                continue
            with self.store.transaction():
                self.guard()
                self.positions.verify()
                cash, assets = self.positions.reserved()
                if cash or assets:
                    raise TestnetError("STRATEGY_PENDING_INTENT")
                key = digest(
                    [
                        self.sid,
                        T1,
                        symbol,
                        "FROZEN_INITIAL_STOP",
                        self.positions.projection_hash(T1),
                    ]
                )
                cid = "e01_" + key[:32]
                if self.store.rows("SELECT * FROM signal_receipts WHERE signal_key=?", (key,)):
                    continue
                order = self.risk.validate(
                    symbol, "SELL", quantity, quote.bid, info, balances, [], self.attempts()
                )
                self.store.db.execute(
                    "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)",
                    (
                        cid,
                        self.sid,
                        self.clock(),
                        symbol,
                        "SELL",
                        str(order.quantity),
                        str(order.price),
                        str(order.notional),
                        "INTENT_CREATED",
                    ),
                )
                self.store.db.execute(
                    "INSERT INTO signal_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        key,
                        self.sid,
                        T1,
                        symbol,
                        0,
                        "RISK_STOP_INTENT",
                        cid,
                        "0",
                        str(reference.price),
                        str(quote.bid),
                        quote.received_ms,
                        EXPERIMENT,
                    ),
                )
                self.store.event(self.sid, self.clock(), "RISK_STOP_INTENT", cid)
                created.append({"state": "RISK_STOP_INTENT", "client_id": cid, "symbol": symbol})
        return created

    def check(self, client_id, *, confirm_test=False):
        result = super().check(client_id, confirm_test=confirm_test)
        if result["state"] == "VALIDATED":
            with self.store.transaction():
                self.store.gate(self.sid, "B", self.clock(), client_id)
        return result

    def review(self, client_id):
        intent = self.intent(client_id)
        report = {
            "environment": "TESTNET",
            "symbol": intent["symbol"],
            "side": intent["side"],
            "quantity": intent["quantity"],
            "expected_notional_usdt": intent["notional"],
            "price": intent["price"],
            "client_id": client_id,
            "limits": {
                "per_order_usdt": "20",
                "daily_count": 3,
                "daily_usdt": "40",
                "open_orders": 1,
            },
        }
        return {**report, "approval_token": digest(report)}

    def submit(self, client_id, *, confirm_order=False, approval_token=None, automated=False):
        if not confirm_order or not self.client.config.trading_enabled:
            return {"state": "DRY_RUN", "client_id": client_id}
        if automated:
            self.automation_guard()
            owners = self.store.rows(
                "SELECT * FROM signal_receipts WHERE client_id=?", (client_id,)
            )
            if not owners:
                raise TestnetError("AUTOMATION_REQUIRES_M04_SIGNAL")
        else:
            if approval_token != self.review(client_id)["approval_token"]:
                raise TestnetError("EXPLICIT_REVIEW_APPROVAL_REQUIRED")
            with self.store.transaction():
                self.store.gate(self.sid, "MANUAL:" + client_id, self.clock(), approval_token)
        return super().submit(client_id, confirm_order=True)

    def automation_guard(self):
        self.guard()
        if not self.safety.automated_enabled or not self.client.config.trading_enabled:
            raise TestnetError("AUTOMATION_DISABLED")
        gates = {
            g["gate"]
            for g in self.store.rows(
                "SELECT * FROM execution_gates WHERE session_id=?", (self.sid,)
            )
        }
        if not {"A", "B", "C", "D"} <= gates:
            raise TestnetError("AUTOMATION_GATES_INCOMPLETE")
        self.positions.verify()

    def enable_automation(self, *, confirm=False):
        if (
            not confirm
            or not self.safety.automated_enabled
            or not self.client.config.trading_enabled
        ):
            raise TestnetError("AUTOMATION_DISABLED")
        self.reconcile()
        gates = {
            g["gate"]
            for g in self.store.rows(
                "SELECT * FROM execution_gates WHERE session_id=?", (self.sid,)
            )
        }
        if not {"A", "B", "C"} <= gates:
            raise TestnetError("AUTOMATION_GATES_INCOMPLETE")
        self.positions.verify()
        with self.store.transaction():
            self.guard()
            self.store.gate(self.sid, "D", self.clock(), "EXPLICIT_T1_TESTNET_ACTIVATION")

    def reconcile(self):
        result = super().reconcile()
        try:
            self.positions.reconcile()
            with self.store.transaction():
                stale = self.store.rows(
                    "SELECT i.client_id,r.bar_open_ms,r.outcome FROM order_intents i "
                    "JOIN signal_receipts r USING(client_id) WHERE i.session_id=? "
                    "AND i.attempted_ms IS NULL AND i.state IN "
                    "('INTENT_CREATED','RISK_APPROVED','VALIDATED')",
                    (self.sid,),
                )
                for intent in stale:
                    if (
                        intent["outcome"] != "RISK_STOP_INTENT"
                        and self.clock() - intent["bar_open_ms"] - 14_400_000
                        > self.safety.max_signal_age_ms
                    ):
                        self.store.db.execute(
                            "UPDATE order_intents SET state='INTENT_EXPIRED' WHERE client_id=?",
                            (intent["client_id"],),
                        )
                        self.store.event(
                            self.sid, self.clock(), "INTENT_EXPIRED", intent["client_id"]
                        )
                manual = self.store.rows(
                    "SELECT i.client_id,i.state FROM order_intents i JOIN execution_gates g "
                    "ON g.gate='MANUAL:' || i.client_id AND g.session_id=i.session_id "
                    "WHERE i.session_id=? AND i.state IN ('FILLED','CANCELED')",
                    (self.sid,),
                )
                for order in manual:
                    self.store.gate(self.sid, "C", self.clock(), order["client_id"])
        except TestnetError as error:
            if error.kind != "DB_FAILED":
                self.store.hold(self.sid, self.clock(), "RECONCILIATION_HOLD")
                self._failure(error)
            raise
        return {**result, "classification": EXPERIMENT}
