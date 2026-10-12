"""Read-only activation evidence; operator acceptance is separate from CI evidence."""

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from trading_system.execution.config import TestnetConfig
from trading_system.execution.execution_store import ExecutionStore
from trading_system.execution.order_manager import OrderManager
from trading_system.observer.model import digest
from trading_system.persistence.records import now_ms
from trading_system.runtime.bridge import ReadOnlyTestnetClient
from trading_system.runtime.common import readonly_database, require_health
from trading_system.runtime.preflight import protected_sources
from trading_system.testnet.client import TestnetError

from .control import Control
from .gates import allocation, baseline, gate_evidence
from .policy import CAPITAL, ORDER_CAP, AutomationRisk, protection_budget

ROOT = Path(__file__).resolve().parents[3]


def operator_review(paths, directory):
    """Read-only digest for explicit binding/kill recovery; never an ON approval."""
    control = Control(directory)
    with readonly_database(paths.execution) as db:
        value = {
            "paths": [str(paths.market), str(paths.observer), str(paths.execution)],
            "session": [
                dict(r)
                for r in db.execute(
                    "SELECT id,fingerprint,hold,kill FROM testnet_sessions WHERE active=1"
                )
            ],
            "intents": [
                dict(r)
                for r in db.execute(
                    "SELECT client_id,state,quantity,price,attempted_ms "
                    "FROM order_intents ORDER BY client_id"
                )
            ],
            "positions": [dict(r) for r in db.execute("SELECT * FROM positions ORDER BY symbol")],
            "checkpoint": [dict(r) for r in db.execute("SELECT * FROM router_checkpoints")],
            "epoch": control.mode()["epoch"],
            "emergency": json.loads(control.stop_path.read_text()) if control.killed() else None,
        }
    return digest(value)


def frozen_sources():
    result = protected_sources()
    manifest = json.loads((ROOT / "docs/DEV-E02-source-manifest.json").read_text())
    for path, expected in manifest["sha256_lf"].items():
        if (
            hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            != expected
        ):
            raise ValueError("E02_BASELINE_SOURCE_CHANGED")
    return {**result, "e02_protected_files": len(manifest["sha256_lf"])}


def m05_acceptance(path, paths):
    try:
        value = json.loads(Path(path).read_text())
        if (
            value["status"] != "PASS"
            or value["classification"] != "ACTUAL_NUC"
            or value["base_sha"] != "3e37b0b81b05906e1cee858671f67a4c5a719566"
            or value["market_path"] != str(paths.market)
            or value["observer_path"] != str(paths.observer)
            or value["execution_path"] != str(paths.execution)
            or not value["approved_by"]
            or not value["evidence_references"]
            or any(value["tests"][f"TEST-{n:02d}"] != "PASS" for n in range(2, 8))
        ):
            raise ValueError
    except OSError, KeyError, TypeError, ValueError:
        raise TestnetError("M05_ACTUAL_ACCEPTANCE_REQUIRED") from None
    return digest(value)


def writer_permissions(path):
    path = Path(path)
    if sys.platform != "linux" or not hasattr(os, "getuid"):
        raise TestnetError("NUC_WRITER_HANDOFF_NOT_VERIFIED")
    if os.getuid() == 0:
        raise TestnetError("UNPRIVILEGED_EXECUTOR_REQUIRED")
    for item in (
        path.parent,
        path,
        *[p for p in (Path(str(path) + "-wal"), Path(str(path) + "-shm")) if p.exists()],
    ):
        if item.stat().st_uid != os.getuid() or item.stat().st_mode & 0o022:
            raise TestnetError("E02_EXCLUSIVE_WRITER_PERMISSIONS_REQUIRED")


def activation_evidence(manager, paths, acceptance_path, *, host=True, quotes=None):
    if host:
        writer_permissions(paths.execution)
        trusted = Path(acceptance_path)
        if (
            trusted.stat().st_uid != 0
            or trusted.stat().st_mode & 0o022
            or trusted.parent.stat().st_uid != 0
            or trusted.parent.stat().st_mode & 0o022
        ):
            raise TestnetError("M05_ACCEPTANCE_NOT_OPERATOR_PROTECTED")
    sources = frozen_sources()
    accepted = m05_acceptance(acceptance_path, paths)
    manager.guard()
    account = manager.client.request("GET", "/api/v3/account")
    if account.get("canTrade") is not True:
        raise TestnetError("ACCOUNT_TRADING_DISABLED")
    if manager.control.killed():
        raise TestnetError("E02_EMERGENCY_STOP")
    pending = manager.store.rows(
        "SELECT state FROM order_intents WHERE state IN "
        "('SUBMITTING','UNKNOWN_EXECUTION','CANCELING')"
    )
    if pending:
        raise TestnetError("UNKNOWN_EXECUTION")
    health = {r: require_health(paths, r, manager.clock()) for r in ("collector", "observer")}
    gates = gate_evidence(manager)
    alloc = allocation(manager)
    manual = baseline(manager.store, manager.sid)
    point = manager.store.rows(
        "SELECT * FROM router_checkpoints WHERE session_id=?", (manager.sid,)
    )
    if (
        not point
        or point[0]["market_path"] != str(paths.market)
        or point[0]["observer_path"] != str(paths.observer)
    ):
        raise TestnetError("ROUTER_SOURCE_CHANGED")
    if not quotes or set(quotes) != {"BTCUSDT", "ETHUSDT", "SOLUSDT"}:
        raise TestnetError("E02_PREFLIGHT_QUOTES_REQUIRED")
    for symbol, quote in quotes.items():
        reference = manager._reference(symbol, paths.market)
        if quote.symbol != symbol:
            raise TestnetError("INVALID_TESTNET_QUOTE")
        manager.risk.prices(quote, reference.price, reference.received_at_ms, manager.clock())
    info = manager.client.request("GET", "/api/v3/exchangeInfo")
    protection = protection_budget(manager, quotes, info, account["balances"])
    # Stable evidence fields; repeated GET reconciliation timestamps do not change approval.
    value = {
        "session_id": manager.sid,
        "account_fingerprint": manager.store.session()["fingerprint"],
        "sources": sources,
        "m05_acceptance": accepted,
        "allocation_initial": alloc["initial_capital"],
        "projection_hash": alloc["projection_hash"],
        "gates": gates,
        "manual_baseline": manual,
        "paths": {
            "market": str(paths.market),
            "observer": str(paths.observer),
            "execution": str(paths.execution),
        },
        "dependencies": {r: health[r]["instance"] for r in health},
        "capital": str(CAPITAL),
        "order_cap": str(ORDER_CAP),
        "protection_budget": protection,
        "daily_attempts": [
            {k: a[k] for k in ("client_id", "attempted_ms", "notional", "state")}
            for a in manager.attempts()
        ],
    }
    return value


def online_readonly(
    paths,
    config=None,
    *,
    transport=None,
    directory=None,
    acceptance_path=None,
    clock=now_ms,
    quote_provider=None,
    host=True,
):
    """Reconcile an expendable Backup API copy; never turn GET checks into Gate C."""
    config = config or TestnetConfig.from_env()
    config = TestnetConfig(config.api_key, config.api_secret, False)
    client = ReadOnlyTestnetClient(config, transport=transport)
    try:
        with tempfile.TemporaryDirectory(prefix="e02-get-preflight-") as temporary:
            copy = Path(temporary) / "testnet_execution.sqlite"
            with readonly_database(paths.execution) as source:
                original_session = source.execute(
                    "SELECT * FROM testnet_sessions WHERE active=1"
                ).fetchone()
                if (
                    not original_session
                    or original_session["fingerprint"]
                    != hashlib.sha256(config.api_key.encode()).hexdigest()
                ):
                    raise TestnetError("ACCOUNT_CHANGED_NEW_SESSION_REQUIRED")
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("EXECUTION_DB_INTEGRITY")
                if (
                    original_session["hold"]
                    or original_session["kill"]
                    or source.execute(
                        "SELECT 1 FROM order_intents WHERE state IN "
                        "('SUBMITTING','UNKNOWN_EXECUTION','CANCELING')"
                    ).fetchone()
                ):
                    raise TestnetError("EXECUTION_HOLD_KILL_OR_UNKNOWN")
                target = sqlite3.connect(copy)
                try:
                    source.backup(target)
                finally:
                    target.close()
            store = ExecutionStore(copy)
            try:
                manager = OrderManager(client, store, clock=clock)
                manager.risk = AutomationRisk(manager.safety)
                manager.control = Control(directory or Path(copy).parent / "control", clock=clock)
                manager.paths = paths
                original_gates = store.rows("SELECT * FROM execution_gates")
                manager.reconcile()
                with store.transaction():
                    store.db.execute("DELETE FROM execution_gates")
                    for g in original_gates:
                        store.db.execute(
                            "INSERT INTO execution_gates VALUES(?,?,?,?)",
                            tuple(g[k] for k in ("session_id", "gate", "completed_ms", "evidence")),
                        )
                account = client.request("GET", "/api/v3/account")
                if account.get("canTrade") is not True:
                    raise TestnetError("ACCOUNT_TRADING_DISABLED")
                result = {
                    "state": "GET_RECONCILIATION_PASS",
                    "original_gates": original_gates,
                    "can_trade": account["canTrade"],
                    "order_calls": 0,
                    "original_journal_modified": False,
                    "classification": "SIMULATED_TEST" if transport else "ACTUAL_TESTNET_GET",
                }
                quotes = None
                if quote_provider:
                    quotes = quote_provider()
                    from trading_system.persistence.repository import MarketRepository

                    with MarketRepository(paths.market) as market:
                        for symbol, quote in quotes.items():
                            reference = market.recent_prices(symbol, 1)
                            if not reference:
                                raise TestnetError("PRODUCTION_REFERENCE_REQUIRED")
                            AutomationRisk().prices(
                                quote, reference[-1].price, reference[-1].received_at_ms, clock()
                            )
                    result["testnet_quotes"] = "FRESH_FIXED_HOST_WS"
                if acceptance_path is not None:
                    evidence = activation_evidence(
                        manager, paths, acceptance_path, host=host, quotes=quotes
                    )
                    result.update(
                        activation_token=digest(evidence),
                        activation_evidence=evidence,
                        state="ACTIVATION_PREFLIGHT_PASS",
                    )
                return result
            finally:
                store.close()
    finally:
        client.close()
