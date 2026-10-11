"""E01 lifecycle reused with an independent final HTTP cap and operator controls."""

from contextlib import contextmanager

from trading_system.execution.config import T1, SafetyConfig
from trading_system.execution.order_manager import OrderManager
from trading_system.observer.model import digest
from trading_system.runtime.common import require_health
from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec

from .policy import AutomationRisk, notional_guard
from .preflight import frozen_sources, writer_permissions


class AutomationManager(OrderManager):
    def __init__(self, client, store, paths, control, **kwargs):
        super().__init__(client, store, safety=SafetyConfig(automated_enabled=True), **kwargs)
        self.paths, self.control = paths, control
        self.risk = AutomationRisk(self.safety)
        self.dependencies = None
        self.testing = self.canceling = None
        self.host_checks = True
        self.client._http.event_hooks["request"].append(self.http_boundary)

    def healthy(self):
        current = {
            r: require_health(self.paths, r, self.clock()) for r in ("collector", "observer")
        }
        if self.dependencies and any(
            current[r]["instance"] != self.dependencies[r]["instance"] for r in current
        ):
            raise TestnetError("DEPENDENCY_RESTART_UNCERTAINTY")
        return current

    def enabled(self):
        if self.control.killed():
            raise TestnetError("E02_EMERGENCY_STOP")
        if not self.control.mode()["enabled"]:
            raise TestnetError("AUTOMATION_DISABLED")
        self.automation_guard()
        self.healthy()

    @contextmanager
    def legacy_gates(self):
        saved = self.store.rows(
            "SELECT * FROM execution_gates WHERE session_id=? AND gate IN ('B','C')", (self.sid,)
        )
        try:
            yield
        finally:
            if saved and not self.store.failed:
                with self.store.transaction():
                    for gate in saved:
                        self.store.db.execute(
                            "INSERT OR REPLACE INTO execution_gates VALUES(?,?,?,?)",
                            tuple(
                                gate[k] for k in ("session_id", "gate", "completed_ms", "evidence")
                            ),
                        )
            if not self.store.failed and not any(g["gate"] == "C" for g in saved):
                with self.store.transaction():
                    self.store.db.execute(
                        "DELETE FROM execution_gates WHERE session_id=? AND gate='C'", (self.sid,)
                    )

    def reconcile(self):
        with self.legacy_gates():
            return super().reconcile()

    def check(self, client_id, *, confirm_test=False):
        with self.legacy_gates():
            return super().check(client_id, confirm_test=confirm_test)

    def _validate(self, intent, info, account, opens):
        notional_guard(intent["quantity"], intent["price"])
        if intent["side"] == "BUY":
            references = {
                p["symbol"]: self._reference(p["symbol"], self.paths.market).price
                for p in self.positions.positions()
                if dec(p["quantity"]) > 0
            }
            self.risk.reserve_exit_budget(
                self.attempts(), self.positions.positions(), references, dec(intent["notional"])
            )
        order = super()._validate(intent, info, account, opens)
        notional_guard(order.quantity, order.price)
        return order

    def submit(self, client_id, *, confirm_order=False, approval_token=None, automated=False):
        if not automated:
            raise TestnetError("E02_AUTOMATED_T1_ONLY")
        self.enabled()
        intent = self.intent(client_id)
        notional_guard(intent["quantity"], intent["price"])
        return super().submit(client_id, confirm_order=confirm_order, automated=True)

    def http_boundary(self, request):
        if request.method == "GET":
            return
        frozen_sources()
        if self.host_checks:
            writer_permissions(self.paths.execution)
        params = request.url.params
        if request.method == "DELETE":
            if not self.canceling:
                raise TestnetError("E02_CANCEL_NOT_APPROVED")
            expected = self._order_query(self.intent(self.canceling))
            if any(str(params.get(k)) != str(v) for k, v in expected.items()):
                raise TestnetError("E02_CANCEL_INTENT_MISMATCH")
            return
        if request.url.path not in ("/api/v3/order", "/api/v3/order/test"):
            raise TestnetError("NETWORK_POLICY_DENIED")
        cid = params.get("newClientOrderId")
        owner = self.store.rows("SELECT * FROM signal_receipts WHERE client_id=?", (cid,))
        if not owner or owner[0]["session_id"] != self.sid or owner[0]["strategy_id"] != T1:
            raise TestnetError("E02_UNATTRIBUTED_ORDER")
        if request.url.path == "/api/v3/order/test" and self.testing == cid:
            self.guard()
            self.healthy()
        else:
            self.enabled()
        notional_guard(params["quantity"], params["price"])
        intent = self.intent(cid)
        if (
            dec(params["quantity"]) != dec(intent["quantity"])
            or dec(params["price"]) != dec(intent["price"])
            or any(
                params.get(k) != v
                for k, v in {
                    "symbol": intent["symbol"],
                    "side": intent["side"],
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                }.items()
            )
        ):
            raise TestnetError("E02_HTTP_INTENT_MISMATCH")
        if request.url.path == "/api/v3/order" and (
            intent["state"] != "SUBMITTING" or intent["attempted_ms"] is None
        ):
            raise TestnetError("E02_DURABLE_ATTEMPT_REQUIRED")
        # Recheck age after hash/ownership work at the last HTTP hook.
        self._send_guard(cid)

    def cancel(self, client_id, *, confirm_cancel=False):
        owner = self.store.rows(
            "SELECT strategy_id,session_id FROM signal_receipts WHERE client_id=?", (client_id,)
        )
        if not owner or owner[0]["strategy_id"] != T1 or owner[0]["session_id"] != self.sid:
            raise TestnetError("MANUAL_BASELINE_CANCEL_DENIED")
        self.canceling = client_id
        try:
            return super().cancel(client_id, confirm_cancel=confirm_cancel)
        finally:
            self.canceling = None

    def protective_intents(self, router, quotes, info, balances):
        self.enabled()
        real = self.positions

        class StopView:
            def __getattr__(self, name):
                return getattr(real, name)

            def positions(self, strategy=T1):
                return [
                    dict(
                        p,
                        quantity=str(self_risk.capped(p["quantity"], quotes[p["symbol"]].bid)),
                    )
                    for p in real.positions(strategy)
                ]

            def projection_hash(self, strategy):
                return digest([real.projection_hash(strategy), activation_epoch])

        self_risk = self.risk
        activation_epoch = self.control.mode()["epoch"]
        self.positions = StopView()
        try:
            return super().protective_intents(router, quotes, info, balances)
        finally:
            self.positions = real
