"""Single journal writer, OFF startup, fresh signal scheduling and E01 recovery."""

import hashlib
import json
import logging
import sqlite3
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

from trading_system.execution.config import T1
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.signal_router import SignalRouter, observer_reader
from trading_system.observer.model import digest
from trading_system.persistence.records import now_ms
from trading_system.persistence.store import WriterLease
from trading_system.runtime.common import atomic_json, boot_id, readonly_database
from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec

from .control import Control
from .gates import allocation, baseline, gate_evidence
from .manager import AutomationManager
from .policy import CAPITAL
from .preflight import activation_evidence, frozen_sources, operator_review, writer_permissions


class Executor:
    def __init__(
        self,
        paths,
        directory,
        client,
        quote_provider,
        *,
        acceptance_path,
        clock=now_ms,
        host_checks=True,
        batch_quote_provider=None,
    ):
        self.paths, self.directory = paths, Path(directory).resolve()
        self.clock, self.client, self.quote_provider = clock, client, quote_provider
        self.batch_quote_provider = batch_quote_provider
        self.acceptance_path, self.host_checks = acceptance_path, host_checks
        self.lease = self.store = self.handler = None
        self.started = clock()
        self.instance = digest([self.started, time.monotonic_ns()])
        # E02 owns a separate control directory; no migrations in the existing E01 DB.
        if any(
            self.directory.is_relative_to(p) or p.is_relative_to(self.directory)
            for p in (
                paths.role_dir("collector"),
                paths.role_dir("observer"),
                paths.role_dir("bridge"),
                paths.execution.parent,
            )
        ):
            raise TestnetError("E02_CONTROL_PATH_COLLISION")
        self.control = Control(self.directory, clock=clock)
        try:
            frozen_sources()
            if host_checks:
                writer_permissions(paths.execution)
            with readonly_database(paths.execution) as db:
                session = db.execute("SELECT * FROM testnet_sessions WHERE active=1").fetchone()
                if (
                    not session
                    or session["fingerprint"]
                    != hashlib.sha256(client.config.api_key.encode()).hexdigest()
                ):
                    raise TestnetError("EXISTING_BOUND_E01_SESSION_REQUIRED")
            self.lease = WriterLease(paths.execution)
            self.directory.mkdir(parents=True, exist_ok=True)
            self.control.off()  # Every new process requires an explicit new activation.
            self.store = ExecutionStore(paths.execution)
            self.manager = AutomationManager(
                client, self.store, paths, self.control, clock=clock, quote_provider=quote_provider
            )
            self.manager.host_checks = host_checks
            self.router = SignalRouter(self.manager.positions, paths.observer, paths.market)
            self.router.risk = self.manager.risk
            points = self.store.rows(
                "SELECT * FROM router_checkpoints WHERE session_id=?", (self.manager.sid,)
            )
            if not points:
                self.router.initialize(clock())
            # Unsubmitted intents are abandoned, never replayed after process replacement.
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE order_intents SET state='INTENT_ABANDONED' WHERE attempted_ms IS NULL "
                    "AND client_id IN (SELECT client_id FROM signal_receipts "
                    "WHERE strategy_id=? AND session_id=?) "
                    "AND state IN ('INTENT_CREATED','RISK_APPROVED','VALIDATED')",
                    (T1, self.manager.sid),
                )
            self.logger = logging.Logger("e02." + self.instance)
            self.handler = RotatingFileHandler(
                self.directory / "executor.jsonl",
                maxBytes=10_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            self.logger.addHandler(self.handler)
            self.publish("OFF")
        except BaseException:
            self.close()
            raise

    def publish(self, state, category=None, **details):
        record = {
            "state": state,
            "category": category,
            "time_ms": self.clock(),
            "started_ms": self.started,
            "instance": self.instance,
            "boot_id": boot_id(),
            "execution_enabled": self.control.mode()["enabled"],
            **details,
        }
        atomic_json(self.directory / "health.json", record)
        if self.handler:
            self.logger.warning(json.dumps(record, sort_keys=True))
        print(json.dumps(record, sort_keys=True), flush=True)
        return record

    def evidence(self):
        return activation_evidence(
            self.manager, self.paths, self.acceptance_path, host=self.host_checks
        )

    def phase_a(self):
        """Run E01 Router only in a disposable copy; preserve original receipts/cursor."""
        self.manager.dependencies = self.manager.healthy()
        allocation(self.manager)
        baseline(self.store, self.manager.sid)
        quotes = self.quotes()
        info = self.client.request("GET", "/api/v3/exchangeInfo")
        balances = self.client.request("GET", "/api/v3/account")["balances"]
        with TemporaryDirectory(prefix="e02-phase-a-") as directory:
            target = Path(directory) / "testnet_execution.sqlite"
            copy_db = sqlite3.connect(target)
            try:
                self.store.db.backup(copy_db)
            finally:
                copy_db.close()
            store = ExecutionStore(target)
            try:
                # PositionManager is read/projected from the copy; no original routing receipts.
                from trading_system.execution.position_manager import PositionManager

                router = SignalRouter(
                    PositionManager(store, self.manager.sid), self.paths.observer, self.paths.market
                )
                router.risk = self.manager.risk
                reports = router.route(self.clock(), quotes, info, balances, dry_run=True)
                approved = [r for r in reports if r["state"] == "DRY_RUN_APPROVED"]
                if not approved or not any(r["state"] == "DRY_RUN_APPROVED" for r in reports):
                    return {"state": "WAITING_REAL_T1_PHASE_A", "reports": reports}
                hashes = [r["signal"] for r in approved]
            finally:
                store.close()
        self.manager.healthy()
        proof = {
            "kind": "E02_LIVE_DRY_RUN",
            "session_id": self.manager.sid,
            "order_cap": str(self.manager.risk.max_order),
            "approved_decisions": hashes,
            "time_ms": self.clock(),
            "observer_path": str(self.paths.observer),
            "market_path": str(self.paths.market),
            "classification": "SIMULATED_TEST"
            if self.client._http._transport.__class__.__name__ == "MockTransport"
            else "ACTUAL_TESTNET_PREVIEW",
        }
        with self.store.transaction():
            self.store.gate(self.manager.sid, "A", self.clock(), json.dumps(proof, sort_keys=True))
            self.store.event(self.manager.sid, self.clock(), "E02_PHASE_A_VERIFIED", proof)
        return {"state": "E02_PHASE_A_VERIFIED", "proof": proof, "reports": reports}

    def quotes(self):
        if self.batch_quote_provider:
            return self.batch_quote_provider()
        return {s: self.quote_provider(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}

    def execute_command(self, request):
        command = request["command"]
        if command in {"bind", "reset-kill"}:
            if self.control.mode()["enabled"]:
                raise TestnetError("E02_RECOVERY_REQUIRES_OFF")
            self.manager.reconcile()
            self.manager.healthy()
            baseline(self.store, self.manager.sid)
            session = self.store.session()
            if session["hold"] or self.store.rows(
                "SELECT 1 FROM order_intents WHERE state IN "
                "('SUBMITTING','UNKNOWN_EXECUTION','CANCELING','NEW','PARTIALLY_FILLED')"
            ):
                raise TestnetError("E02_RECOVERY_UNRESOLVED_EXECUTION")
            with self.control.lock():
                if request["token"] != operator_review(self.paths, self.directory):
                    raise TestnetError("E02_OPERATOR_REVIEW_REQUIRED")
                if command == "reset-kill":
                    allocation(self.manager)
                    gate_evidence(self.manager, require_a=False)
                    if self.control.killed():
                        atomic_json(
                            self.directory / "recovery" / f"kill-{time.monotonic_ns()}.json",
                            json.loads(self.control.stop_path.read_text()),
                        )
                        self.control.stop_path.unlink()
                    self.store.kill(self.manager.sid, self.clock(), False)
                    self.store.event(
                        self.manager.sid,
                        self.clock(),
                        "E02_EXPLICIT_KILL_RESET_OFF",
                        request["token"],
                    )
                else:
                    self.manager.guard()
                    old = self.store.rows(
                        "SELECT * FROM router_checkpoints WHERE session_id=?", (self.manager.sid,)
                    )
                    with observer_reader(self.paths.observer) as db:
                        self.router.health(db)
                        maximum = db.execute(
                            "SELECT coalesce(max(rowid),0) FROM signal_decisions"
                        ).fetchone()[0]
                    with self.store.transaction():
                        self.store.event(
                            self.manager.sid, self.clock(), "E02_EXPLICIT_SOURCE_BIND", old
                        )
                        self.store.db.execute(
                            "INSERT OR REPLACE INTO router_checkpoints VALUES(?,?,?,?,?)",
                            (
                                self.manager.sid,
                                str(self.paths.observer),
                                str(self.paths.market),
                                self.clock(),
                                maximum,
                            ),
                        )
                        self.store.db.execute(
                            "DELETE FROM execution_gates WHERE session_id=? AND gate IN ('A','D')",
                            (self.manager.sid,),
                        )
            return {"state": "RECOVERED_OFF", "command": command}
        if command in {"off", "kill"}:
            self.control.off()
            if command == "kill":
                self.store.kill(self.manager.sid, self.clock(), True)
            return {"state": "KILLED" if command == "kill" else "OFF"}
        if command == "cancel":
            return self.manager.cancel(request["client_id"], confirm_cancel=True)
        if command == "allocate":
            if self.control.mode()["enabled"]:
                raise TestnetError("ALLOCATION_REQUIRES_OFF")
            self.manager.reconcile()
            baseline(self.store, self.manager.sid)
            account = self.client.request("GET", "/api/v3/account")
            free = next(
                (dec(b["free"]) for b in account["balances"] if b["asset"] == "USDT"), dec(0)
            )
            if free < CAPITAL:
                raise TestnetError("INSUFFICIENT_ALLOCATABLE_CAPITAL")
            self.manager.positions.allocate(CAPITAL, self.clock())
            return {"state": "T1_ALLOCATED", "capital": str(CAPITAL)}
        if command == "phase-a":
            self.manager.reconcile()
            return self.phase_a()
        if command == "recover":
            self.control.off()
            return self.manager.reconcile()  # GET only; never clears real hold/kill.
        if command == "on":
            if self.control.mode()["enabled"]:
                raise TestnetError("E02_ACTIVATION_REQUIRES_OFF")
            if not self.client.config.trading_enabled:
                raise TestnetError("E02_MUTATIONS_NOT_PROVISIONED")
            epoch = self.control.mode()["epoch"]
            self.manager.reconcile()
            evidence = self.evidence()
            if request["token"] != digest(evidence):
                raise TestnetError("E02_ACTIVATION_REVIEW_REQUIRED")
            self.manager.enable_automation(confirm=True)
            # Existing and Phase A records are not live orders for this new activation.
            with observer_reader(self.paths.observer) as db:
                maximum = db.execute(
                    "SELECT coalesce(max(rowid),0) FROM signal_decisions"
                ).fetchone()[0]
            with self.store.transaction():
                abandoned = self.store.rows(
                    "SELECT i.client_id FROM order_intents i "
                    "JOIN signal_receipts r USING(client_id) "
                    "WHERE i.attempted_ms IS NULL AND i.state IN "
                    "('INTENT_CREATED','RISK_APPROVED','VALIDATED') "
                    "AND r.strategy_id=? AND r.session_id=?",
                    (T1, self.manager.sid),
                )
                for intent in abandoned:
                    self.store.db.execute(
                        "UPDATE order_intents SET state='INTENT_ABANDONED' WHERE client_id=?",
                        (intent["client_id"],),
                    )
                if abandoned:
                    self.store.event(
                        self.manager.sid, self.clock(), "E02_OLD_UNSUBMITTED_ABANDONED", abandoned
                    )
                self.store.db.execute(
                    "UPDATE router_checkpoints SET activated_ms=?,last_rowid=? WHERE session_id=?",
                    (self.clock(), maximum, self.manager.sid),
                )
                self.store.event(
                    self.manager.sid,
                    self.clock(),
                    "E02_ACTIVATED_NO_RETROACTIVE_ORDERS",
                    {"approval": digest(evidence), "watermark": maximum},
                )
            if self.control.mode()["epoch"] != epoch or self.control.killed():
                raise TestnetError("E02_CONTROL_CHANGED")
            self.control.authorize(evidence, epoch)
            return {"state": "ON_WAITING_NEW_LIVE_SIGNAL", "watermark": maximum}
        if command == "order-test":
            if self.control.mode()["enabled"]:
                raise TestnetError("E02_ORDER_TEST_REQUIRES_OFF")
            self.manager.dependencies = self.manager.healthy()
            allocation(self.manager)
            baseline(self.store, self.manager.sid)
            # Only a real fresh routed T1 candidate; no CLI symbol/quantity/manual order.
            reports = self.route()
            intent = next((r for r in reports if r["state"] == "INTENT_CREATED"), None)
            if not intent:
                return {"state": "WAITING_NEW_T1_TEST_SIGNAL", "reports": reports}
            cid = intent["client_id"]
            self.manager.testing = cid
            try:
                result = self.manager.check(cid, confirm_test=True)
            finally:
                self.manager.testing = None
                with self.store.transaction():
                    self.store.db.execute(
                        "UPDATE order_intents SET state='INTENT_ABANDONED' "
                        "WHERE client_id=? AND attempted_ms IS NULL",
                        (cid,),
                    )
            return result
        raise TestnetError("E02_UNSUPPORTED_COMMAND")

    def route(self):
        quotes = self.quotes()
        info = self.client.request("GET", "/api/v3/exchangeInfo")
        balances = self.client.request("GET", "/api/v3/account")["balances"]
        return self.router.route(self.clock(), quotes, info, balances, dry_run=False)

    def pending_orders(self):
        return self.store.rows(
            "SELECT i.* FROM order_intents i JOIN signal_receipts r USING(client_id) "
            "WHERE r.strategy_id=? AND r.session_id=? AND i.state IN ('NEW','PARTIALLY_FILLED')",
            (T1, self.manager.sid),
        )

    def protection_budget(self, quotes, info, balances):
        # Pending BUY remainder needs future exit capacity. An already submitted SELL
        # covers only its unfilled quantity and already consumes a daily attempt.
        inventory = {p["symbol"]: dict(p) for p in self.manager.positions.positions()}
        uncovered = {s: dict(p) for s, p in inventory.items()}
        for order in self.pending_orders():
            observed = self.store.rows(
                "SELECT executed_qty FROM exchange_orders WHERE client_id=?", (order["client_id"],)
            )[0]
            remaining = dec(order["quantity"]) - dec(observed["executed_qty"])
            p = inventory.setdefault(order["symbol"], {"symbol": order["symbol"], "quantity": "0"})
            p["quantity"] = str(
                max(dec(0), dec(p["quantity"]) + remaining * (1 if order["side"] == "BUY" else -1))
            )
            if order["side"] == "SELL" and order["symbol"] in uncovered:
                actual = uncovered[order["symbol"]]
                actual["quantity"] = str(max(dec(0), dec(actual["quantity"]) - remaining))
        marks = {s: self.manager._reference(s, self.paths.market).price for s in inventory}
        budget = self.manager.risk.reserve_exit_budget(
            self.manager.attempts(), list(inventory.values()), marks
        )
        # A hoped-for later fill cannot hide currently unprotectable partial-fill dust.
        for p in [*inventory.values(), *uncovered.values()]:
            if dec(p["quantity"]) > 0:
                symbol = p["symbol"]
                # Do not issue a test/order here; prove that a capped exit passes current filters.
                self.manager.risk.validate(
                    symbol,
                    "SELL",
                    min(dec(p["quantity"]), self.manager.risk.max_order / quotes[symbol].bid),
                    quotes[symbol].bid,
                    info,
                    balances,
                    [],
                    self.manager.attempts(),
                )
        return budget

    def tick(self):
        for path in self.control.pending():
            try:
                request = json.loads(path.read_text())
                if (
                    request["command"] not in {"off", "kill"}
                    and request.get("runtime_instance") != self.instance
                ):
                    raise TestnetError("E02_COMMAND_FROM_OLD_PROCESS")
                if not 0 <= self.clock() - request["created_ms"] <= 60_000:
                    raise TestnetError("E02_COMMAND_EXPIRED")
                result = self.execute_command(request)
            except TestnetError as error:
                self.control.off()
                result = {"state": "HOLD", "category": error.kind}
            self.control.finish(path, result)
        try:
            self.manager.reconcile()
            if self.control.killed():
                self.store.kill(self.manager.sid, self.clock(), True)
            # Pending GTC orders are canceled after 60 seconds; never chased/replaced.
            for intent in self.pending_orders():
                if self.clock() - intent["attempted_ms"] >= 60_000:
                    self.manager.cancel(intent["client_id"], confirm_cancel=True)
            if not self.control.mode()["enabled"]:
                return self.publish(
                    "OFF",
                    positions=self.manager.positions.positions(),
                    protection="SOFTWARE_STOP_PAUSED_NO_NEW_ORDERS",
                )
            self.manager.dependencies = self.manager.healthy()
            self.manager.enabled()
            unknown = self.store.rows(
                "SELECT state FROM order_intents WHERE state IN "
                "('SUBMITTING','UNKNOWN_EXECUTION','CANCELING')"
            )
            if unknown:
                raise TestnetError("UNKNOWN_EXECUTION")
            quotes = self.quotes()
            info = self.client.request("GET", "/api/v3/exchangeInfo")
            balances = self.client.request("GET", "/api/v3/account")["balances"]
            # Stop takes priority over ordinary entries, with all E01 limits intact.
            triggered = any(
                self.manager._reference(p["symbol"], self.paths.market).price
                <= dec(p["initial_stop"])
                for p in self.manager.positions.positions()
                if dec(p["quantity"]) > 0
            )
            if triggered:
                for intent in self.pending_orders():
                    if intent["side"] == "BUY":
                        self.manager.cancel(intent["client_id"], confirm_cancel=True)
                self.manager.reconcile()
                balances = self.client.request("GET", "/api/v3/account")["balances"]
            pending = self.pending_orders()
            stops = (
                []
                if pending
                else self.manager.protective_intents(self.router, quotes, info, balances)
            )
            reports = stops or (
                []
                if triggered or pending
                else self.router.route(self.clock(), quotes, info, balances, dry_run=False)
            )
            submissions = []
            for report in reports:
                if report["state"] not in {"INTENT_CREATED", "RISK_STOP_INTENT"}:
                    continue
                cid = report["client_id"]
                self.manager.check(cid, confirm_test=True)
                submissions.append(self.manager.submit(cid, confirm_order=True, automated=True))
            marks = {
                p["symbol"]: self.manager._reference(p["symbol"], self.paths.market).price
                for p in self.manager.positions.positions()
                if dec(p["quantity"]) > 0
            }
            budget = self.protection_budget(quotes, info, balances)
            return self.publish(
                "ON",
                reports=reports,
                submissions=submissions,
                protection=budget,
                positions=self.manager.positions.report(marks),
            )
        except TestnetError as error:
            self.control.off()
            return self.publish(
                "HOLD", error.kind, protection="UNAVAILABLE_REQUIRES_OPERATOR_REVIEW"
            )

    def close(self):
        if hasattr(self, "manager"):
            hooks = self.client._http.event_hooks["request"]
            if self.manager.http_boundary in hooks:
                hooks.remove(self.manager.http_boundary)
        if self.handler:
            self.handler.close()
        if self.store:
            self.store.close()
        if self.lease:
            self.lease.close()
