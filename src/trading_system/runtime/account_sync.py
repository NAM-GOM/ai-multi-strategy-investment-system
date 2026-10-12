"""Continuous GET-only E01 reconciliation; never submit orders or allocate capital."""

import argparse
import json
import math
import signal
import sqlite3
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from trading_system.execution.config import TestnetConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.order_manager import OrderManager
from trading_system.persistence.records import now_ms
from trading_system.persistence.store import PersistenceError, WriterLease
from trading_system.testnet.client import TestnetError

from .bridge import ReadOnlyTestnetClient
from .common import (
    EXECUTION_PATH,
    STATE_ROOT,
    RuntimePaths,
    StatusSink,
    atomic_json,
    disabled_environment,
    readonly_database,
)

TRANSIENT_ERRORS = frozenset({"UNKNOWN_TRANSPORT", "RATE_LIMIT_HOLD"})


class AccountSync:
    """Reconcile in a disposable copy; publish one bounded account snapshot JSON."""

    def __init__(self, paths, client, sink, *, clock=now_ms):
        disabled_environment()
        self.paths, self.client, self.sink, self.clock = paths, client, sink, clock
        self.lease = None
        self.snapshot_path = paths.role_dir("account") / "latest-account.json"
        self.hold_path = paths.role_dir("account") / "account-hold.json"
        try:
            # No empty/missing/foreign journal initialization or new account epoch.
            with readonly_database(paths.execution) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise TestnetError("EXECUTION_DB_INTEGRITY")
                if not db.execute("SELECT 1 FROM testnet_sessions WHERE active=1").fetchone():
                    raise TestnetError("EXISTING_E01_SESSION_REQUIRED")
            self.lease = WriterLease(paths.role_dir("account") / "account_snapshot")
        except BaseException:
            self.close()
            raise

    def cycle(self):
        disabled_environment()
        if self.hold_path.exists():
            raise TestnetError("ACCOUNT_RECONCILIATION_REVIEW_REQUIRED")
        try:
            report = self._snapshot()
        except TestnetError as error:
            if error.kind not in TRANSIENT_ERRORS:
                atomic_json(self.hold_path, {"category": error.kind, "timestamp_ms": self.clock()})
            raise
        atomic_json(self.snapshot_path, report)
        self.sink.publish(
            "READY",
            force=True,
            **{
                k: report[k]
                for k in ("mode", "balance_timestamp_ms", "execution_enabled", "order_calls")
            },
        )
        return report

    def _snapshot(self):
        with tempfile.TemporaryDirectory(prefix="m05-account-") as directory:
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
                session = store.session()
                if not session or session["hold"]:
                    raise TestnetError("ACCOUNT_RECONCILIATION_REVIEW_REQUIRED")
                if store.rows(
                    "SELECT client_id FROM order_intents WHERE state IN "
                    "('SUBMITTING','UNKNOWN_EXECUTION','CANCELING')"
                ):
                    raise TestnetError("UNKNOWN_EXECUTION_REVIEW_REQUIRED")
                engine = OrderManager(self.client, store, clock=self.clock)
                engine.reconcile()
                latest = store.rows(
                    "SELECT max(time_ms) AS timestamp_ms FROM balance_snapshots WHERE session_id=?",
                    (engine.sid,),
                )[0]["timestamp_ms"]
                if not 0 <= self.clock() - latest <= 30_000:
                    raise TestnetError("ACCOUNT_SNAPSHOT_CLOCK_UNCERTAINTY")
                stamp = datetime.fromtimestamp(latest / 1000, UTC).isoformat()
                balances = store.rows(
                    "SELECT asset,free,locked FROM balance_snapshots WHERE session_id=? "
                    "AND snapshot_id=(SELECT snapshot_id FROM balance_snapshots WHERE session_id=? "
                    "ORDER BY time_ms DESC,rowid DESC LIMIT 1) ORDER BY asset",
                    (engine.sid, engine.sid),
                )
                orders = store.rows(
                    "SELECT o.symbol,o.order_id,o.status,o.executed_qty,o.updated_ms,"
                    "i.side,i.quantity,i.price,r.strategy_id FROM exchange_orders o "
                    "LEFT JOIN order_intents i ON o.session_id=i.session_id "
                    "AND o.client_id=i.client_id "
                    "LEFT JOIN signal_receipts r ON r.session_id=o.session_id "
                    "AND r.client_id=o.client_id "
                    "WHERE o.session_id=? ORDER BY o.updated_ms DESC LIMIT 100",
                    (engine.sid,),
                )
                fills = store.rows(
                    "SELECT symbol,trade_id,order_id,price,quantity,commission,"
                    "commission_asset,time_ms,is_buyer FROM executions "
                    "WHERE session_id=? ORDER BY time_ms DESC LIMIT 100",
                    (engine.sid,),
                )
                return self._report(latest, stamp, balances, orders, fills, session)
            finally:
                store.close()

    @staticmethod
    def _report(latest, stamp, balances, orders, fills, session):
        report = {
            "schemaVersion": 1,
            "mode": "READ_ONLY_TESTNET_ACCOUNT_SYNC",
            "balance_timestamp_ms": latest,
            "account_session_id": session["id"],
            "execution_enabled": False,
            "order_calls": 0,
            "kill_preserved": bool(session["kill"]),
            "hold_preserved": bool(session["hold"]),
            "real_journal_modified": False,
            "balances": [{**b, "time": stamp} for b in balances],
            "reconciled_orders": orders,
            "reconciled_fills": fills,
        }
        if len(json.dumps(report).encode("utf-8")) > 1_000_000:
            raise TestnetError("ACCOUNT_SNAPSHOT_SIZE_HOLD")
        return report

    def close(self):
        if self.lease:
            self.lease.close()
            self.lease = None


def main(argv=None):
    parser = argparse.ArgumentParser(description="GET-only persistent Testnet account refresh")
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--execution-db", type=Path, default=EXECUTION_PATH)
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    if not math.isfinite(args.interval_seconds) or not 15 <= args.interval_seconds <= 300:
        parser.error("account interval must be 15..300 seconds")
    if not args.online:
        print('{"mode":"OFFLINE_NO_NETWORK_NO_JOURNAL_WRITE","execution_enabled":false}')
        return 0
    stopping = threading.Event()
    handlers = {}
    client = service = sink = role_lease = None
    try:
        disabled_environment()
        paths = RuntimePaths(args.state_root, args.execution_db)
        paths.role_dir("account").mkdir(parents=True, exist_ok=True)
        role_lease = WriterLease(paths.role_dir("account") / "service")
        sink = StatusSink(paths, "account")
        sink.publish("STARTING", force=True)
        client = ReadOnlyTestnetClient(TestnetConfig.from_env())
        service = AccountSync(paths, client, sink)
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, lambda *_: stopping.set())
        failures = 0
        while not stopping.is_set():
            try:
                service.cycle()
                failures = 0
                if args.once:
                    break
                delay = args.interval_seconds
            except TestnetError as error:
                sink.publish("HOLD", error.kind, force=True)
                if args.once or error.kind not in TRANSIENT_ERRORS:
                    return 78
                failures += 1
                # Keep one client: honor Binance Retry-After across every retry.
                delay = max(
                    args.interval_seconds,
                    min(300, 30 * 2 ** min(failures, 4)),
                    client.blocked_until - time.monotonic(),
                )
            stopping.wait(delay)
        sink.publish("STOPPED", force=True)
        return 0
    except TestnetError, PersistenceError, OSError, sqlite3.Error:
        if sink:
            sink.publish("FAILED", "ACCOUNT_SYNC_STARTUP_OR_SQLITE_HOLD", force=True)
        print(json.dumps({"state": "ACCOUNT_SYNC_HOLD", "execution_enabled": False}))
        return 78
    finally:
        if service:
            service.close()
        if client:
            client.close()
        if sink:
            sink.close()
        if role_lease:
            role_lease.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
