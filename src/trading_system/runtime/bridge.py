"""Observation-only E01 Preview: write to an expendable copy, never the order ledger."""

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.execution.cli import AssumedPositionManager
from trading_system.execution.config import SafetyConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.order_manager import OrderManager
from trading_system.execution.signal_router import SignalRouter, observer_reader
from trading_system.execution.testnet_client import TestnetExecutionClient
from trading_system.persistence.records import now_ms
from trading_system.testnet.client import TestnetError

from .common import atomic_json, disabled_environment, readonly_database, require_health

TRANSIENT_HOLDS = frozenset(
    {
        "INPUT_DB_MISSING",
        "OBSERVER_NOT_INITIALIZED",
        "COLLECTOR_HEARTBEAT_HOLD",
        "OBSERVER_HEARTBEAT_HOLD",
        "M04_NOT_OBSERVING",
        "M04_DATA_HOLD_OR_STOP",
        "UNKNOWN_TRANSPORT",
        "RATE_LIMIT_HOLD",
        "TESTNET_QUOTE_UNAVAILABLE",
        "DEPENDENCY_RESTART_UNCERTAINTY",
    }
)


class ReadOnlyTestnetClient(TestnetExecutionClient):
    """Keep E01 host/signing/TLS rules; additionally forbid every HTTP mutation."""

    def __init__(self, config, *, transport=None):
        if config.trading_enabled:
            raise TestnetError("RUNTIME_EXECUTION_UNLOCK_DENIED")
        super().__init__(config, transport=transport)
        self._http.event_hooks["request"].append(self.read_only_boundary)

    @staticmethod
    def read_only_boundary(request):
        if request.method != "GET":
            raise TestnetError("PREVIEW_MUTATION_DENIED")

    def request(self, method, path, params=None, *, confirm=False):
        if method != "GET":
            raise TestnetError("PREVIEW_MUTATION_DENIED")
        return super().request(method, path, params, confirm=False)


class PreviewBridge:
    def __init__(self, paths, sink, *, clock=now_ms):
        self.paths, self.sink, self.clock = paths, sink, clock
        self.cursor_path = paths.role_dir("bridge") / "preview-cursor.json"
        self.hold_path = paths.role_dir("bridge") / "preview-hold.json"

    def latch(self, category):
        if not self.hold_path.exists():
            atomic_json(
                self.hold_path,
                {
                    "category": category,
                    "timestamp_ms": self.clock(),
                    "state": "PERSISTENT_HOLD_REQUIRES_OPERATOR_REVIEW",
                    "execution_enabled": False,
                },
            )

    def point(self, now):
        with observer_reader(self.paths.observer) as db:
            maximum = db.execute("SELECT coalesce(max(rowid),0) FROM signal_decisions").fetchone()[
                0
            ]
            first = db.execute(
                "SELECT decision_hash FROM signal_decisions ORDER BY rowid LIMIT 1"
            ).fetchone()
            first_hash = first[0] if first else None
            if self.cursor_path.exists():
                point = json.loads(self.cursor_path.read_text(encoding="utf-8"))
                if (
                    point["observer_path"] != str(self.paths.observer.resolve())
                    or point["market_path"] != str(self.paths.market.resolve())
                    or point["execution_path"] != str(self.paths.execution)
                    or not 0 <= point["last_rowid"] <= maximum
                    or not 0 <= point["activated_ms"] <= now
                    or (point["first_hash"] and point["first_hash"] != first_hash)
                ):
                    raise TestnetError("PREVIEW_SOURCE_OR_CLOCK_CHANGED")
                anchor = db.execute(
                    "SELECT decision_hash FROM signal_decisions WHERE rowid=?",
                    (point["last_rowid"],),
                ).fetchone()
                if point["last_rowid"] and (not anchor or anchor[0] != point["anchor_hash"]):
                    raise TestnetError("PREVIEW_RESTART_UNCERTAINTY")
                return point
            anchor = db.execute(
                "SELECT decision_hash FROM signal_decisions WHERE rowid=?", (maximum,)
            ).fetchone()
            point = {
                "observer_path": str(self.paths.observer.resolve()),
                "market_path": str(self.paths.market.resolve()),
                "execution_path": str(self.paths.execution),
                "activated_ms": now,
                "last_rowid": maximum,
                "first_hash": first_hash,
                "anchor_hash": anchor[0] if anchor else None,
            }
        atomic_json(self.cursor_path, point)
        self.sink.publish("HOLD", "PREVIEW_INITIALIZED_NO_RETROACTIVE_SIGNALS", force=True)
        return point

    def cycle(self, client, *, online=False, quotes=None, info=None, balances=None, capital=None):
        try:
            if self.hold_path.exists():
                raise TestnetError("PREVIEW_PERSISTENT_HOLD")
            return self._cycle(
                client, online=online, quotes=quotes, info=info, balances=balances, capital=capital
            )
        except TestnetError as error:
            if error.kind not in TRANSIENT_HOLDS:
                self.latch(error.kind)
            raise

    def _cycle(self, client, *, online=False, quotes=None, info=None, balances=None, capital=None):
        disabled_environment()
        if online and capital is not None:
            raise TestnetError("SIMULATED_CAPITAL_ONLINE_DENIED")
        now = self.clock()
        point = self.point(now)  # Record the startup watermark even during M04 warm-up.
        collector = require_health(self.paths, "collector", now)
        observer = require_health(self.paths, "observer", now)
        with tempfile.TemporaryDirectory(prefix="m05-preview-") as directory:
            target = Path(directory) / "testnet_execution.sqlite"
            with readonly_database(self.paths.execution) as source:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise TestnetError("EXECUTION_DB_INTEGRITY")
                destination = sqlite3.connect(target)
                try:
                    source.backup(destination, pages=256)
                finally:
                    destination.close()
            store = ExecutionStore(target)
            try:
                if not online:
                    # Offline Preview must not need the account key to open an
                    # already-bound E01 ledger. Rebind only the expendable copy;
                    # no account identity/reconciliation is claimed by this mode.
                    store.db.execute(
                        "UPDATE testnet_sessions SET fingerprint=? WHERE active=1",
                        (hashlib.sha256(client.config.api_key.encode()).hexdigest(),),
                    )
                engine = OrderManager(client, store, clock=self.clock, safety=SafetyConfig())
                if online:
                    engine.reconcile()  # GET only; reconciliation writes only to the copy.
                    info = client.request("GET", "/api/v3/exchangeInfo")
                    balances = client.request("GET", "/api/v3/account")["balances"]
                    if quotes is None:
                        raise TestnetError("TESTNET_QUOTE_REQUIRED")
                session = store.session()
                uncertain = store.rows(
                    "SELECT state FROM order_intents WHERE state IN "
                    "('SUBMITTING','UNKNOWN_EXECUTION','CANCELING')"
                )
                if session["kill"] or session["hold"] or uncertain:
                    raise TestnetError("EXECUTION_HOLD_KILL_OR_UNKNOWN")
                manual_baseline = store.rows(
                    "SELECT symbol,order_id,executed_qty,quote_qty FROM exchange_orders o "
                    "WHERE NOT EXISTS(SELECT 1 FROM signal_receipts r "
                    "WHERE r.client_id=o.client_id)"
                )
                manager = engine.positions
                if capital is not None:
                    manager = AssumedPositionManager(store, engine.sid, capital)
                with store.transaction():
                    store.db.execute(
                        "DELETE FROM router_checkpoints WHERE session_id=?", (engine.sid,)
                    )
                    store.db.execute(
                        "INSERT INTO router_checkpoints VALUES(?,?,?,?,?)",
                        (
                            engine.sid,
                            point["observer_path"],
                            point["market_path"],
                            point["activated_ms"],
                            point["last_rowid"],
                        ),
                    )
                router = SignalRouter(manager, self.paths.observer, self.paths.market)
                # Explicit validation reports for NO_ACTION and both shadow strategies.
                validations = []
                with observer_reader(self.paths.observer) as db:
                    rows = db.execute(
                        "SELECT rowid AS sequence,* FROM signal_decisions "
                        "WHERE rowid>? ORDER BY rowid",
                        (point["last_rowid"],),
                    ).fetchall()
                    for row in rows:
                        try:
                            d, _ = router.validate_row(db, row, self.clock())
                            validation = "VALIDATED"
                            mode = d.observation_mode
                        except TestnetError as error:
                            validation, mode = error.kind, row["mode"]
                        validations.append(
                            {
                                "sequence": row["sequence"],
                                "strategy": row["strategy_id"],
                                "symbol": row["symbol"],
                                "decision": row["decision"],
                                "mode": mode,
                                "validation": validation,
                                "policy": "T1_PAPER_CANDIDATE"
                                if row["strategy_id"] == "trend_ma_v0.1"
                                else "SHADOW_SIGNAL_ONLY",
                            }
                        )
                fatal_states = {
                    "SIGNAL_HASH_MISMATCH",
                    "STRATEGY_HASH_MISMATCH",
                    "INPUT_HASH_MISMATCH",
                    "FROZEN_DECISION_MISMATCH",
                    "STRATEGY_NOT_FROZEN",
                    "INVALID_COMMITTED_BATCH",
                    "INVALID_SIGNAL_RECORD",
                    "UNCONFIRMED_4H_BAR",
                }
                for validation in validations:
                    if validation["validation"] in fatal_states:
                        raise TestnetError(validation["validation"])
                # Obtain WS quotes after the provenance audit, so audit CPU time
                # does not consume E01's unchanged five-second quote freshness.
                if online and callable(quotes):
                    quotes = quotes()
                reports = router.route(
                    self.clock(),
                    quotes or {},
                    info or {"symbols": []},
                    balances or [],
                    dry_run=True,
                )
                next_point = dict(point)
                next_point["last_rowid"] = router.checkpoint()["last_rowid"]
                with observer_reader(self.paths.observer) as db:
                    first = db.execute(
                        "SELECT decision_hash FROM signal_decisions ORDER BY rowid LIMIT 1"
                    ).fetchone()
                    anchor = db.execute(
                        "SELECT decision_hash FROM signal_decisions WHERE rowid=?",
                        (next_point["last_rowid"],),
                    ).fetchone()
                    next_point["first_hash"] = first[0] if first else None
                    next_point["anchor_hash"] = anchor[0] if anchor else None
                # A dependency restart/hold during slow risk evaluation invalidates the
                # cycle. Its cursor is not advanced, and the next cycle revalidates.
                for role, before in (("collector", collector), ("observer", observer)):
                    after = require_health(self.paths, role, self.clock())
                    if after["instance"] != before["instance"]:
                        raise TestnetError("DEPENDENCY_RESTART_UNCERTAINTY")
                result = {
                    "mode": "READ_ONLY_TESTNET_CONNECTED" if online else "DRY_RUN_SIGNAL_ROUTING",
                    "classification": "SIMULATED_TEST"
                    if capital is not None
                    else "OBSERVATION_PREVIEW",
                    "execution_enabled": False,
                    "order_calls": 0,
                    "real_ledger_modified": False,
                    "account_identity": "READ_ONLY_RECONCILED_COPY"
                    if online
                    else "NOT_VERIFIED_OFFLINE",
                    "actual_t1_allocation_created": False,
                    "manual_baseline": {
                        "classification": "MANUAL_BASELINE",
                        "orders": manual_baseline,
                        "t1_attribution": False,
                    },
                    "risk_state": "E01_LIMITS_UNCHANGED_NO_ALLOCATION_ASSUMED"
                    if capital is None
                    else "HYPOTHETICAL_FLAT_CAPITAL",
                    "signals": reports,
                    "validations": validations,
                    "routing_state": "WAITING_NEW_SIGNAL"
                    if not validations
                    else "INPUTS_VALIDATED"
                    if all(v["validation"] == "VALIDATED" for v in validations)
                    else "VALIDATION_HOLD",
                    "symbols": list(SYMBOLS),
                    "preview_checkpoint": next_point,
                }
                # Persist evidence before watermark. A crash can repeat PREVIEW reports
                # but cannot consume an execution signal or send an order.
                atomic_json(self.paths.role_dir("bridge") / "latest-preview.json", result)
                rejected = result["routing_state"] == "VALIDATION_HOLD"
                self.sink.publish(
                    "HOLD" if rejected else "READY",
                    "ROUTER_SIGNAL_REJECTED" if rejected else None,
                    force=bool(reports),
                    report=result,
                )
                atomic_json(self.cursor_path, next_point)
                return result
            finally:
                store.close()
