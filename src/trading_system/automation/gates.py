"""Gate evidence is read and verified, never synthesized from a previous trade."""

import json

import httpx

from trading_system.execution.config import T1
from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec

from .policy import CAPITAL, ORDER_CAP


def baseline(store, sid):
    orders = store.rows(
        "SELECT * FROM exchange_orders WHERE session_id=? AND order_id=1507111", (sid,)
    )
    if len(orders) != 1 or orders[0]["symbol"] != "BTCUSDT":
        raise TestnetError("MANUAL_BASELINE_1507111_REQUIRED")
    order = orders[0]
    if store.rows("SELECT * FROM signal_receipts WHERE client_id=?", (order["client_id"],)):
        raise TestnetError("MANUAL_BASELINE_MISATTRIBUTED")
    intent = store.rows("SELECT * FROM order_intents WHERE client_id=?", (order["client_id"],))[0]
    if (
        intent["side"] != "BUY"
        or order["status"] != "FILLED"
        or dec(order["executed_qty"]) != dec("0.00009000")
    ):
        raise TestnetError("MANUAL_BASELINE_MISMATCH")
    manual = store.rows(
        "SELECT * FROM execution_gates WHERE session_id=? AND gate=?",
        (sid, "MANUAL:" + order["client_id"]),
    )
    if not manual:
        raise TestnetError("MANUAL_APPROVAL_EVIDENCE_MISSING")
    return {
        "order_id": 1507111,
        "symbol": "BTCUSDT",
        "quantity": order["executed_qty"],
        "classification": "MANUAL_BASELINE",
        "client_id": order["client_id"],
    }


def allocation(manager):
    value = manager.positions.allocation()
    if dec(value["initial_capital"]) != CAPITAL or dec(value["cash"]) < 0:
        raise TestnetError("E02_ALLOCATION_MISMATCH")
    others = manager.store.rows(
        "SELECT * FROM strategy_allocations WHERE session_id=? AND strategy_id!=?",
        (manager.sid, T1),
    )
    if others:
        raise TestnetError("E02_OTHER_ALLOCATION_PRESENT")
    manager.positions.verify()
    return value


def gate_evidence(manager, *, require_a=True):
    store, sid = manager.store, manager.sid
    gates = {
        r["gate"]: r for r in store.rows("SELECT * FROM execution_gates WHERE session_id=?", (sid,))
    }
    required = {"B", "C"} | ({"A"} if require_a else set())
    if not required <= gates.keys():
        raise TestnetError("AUTOMATION_GATES_INCOMPLETE")
    if require_a:
        try:
            phase = json.loads(gates["A"]["evidence"])
            if (
                phase["kind"] != "E02_LIVE_DRY_RUN"
                or phase["order_cap"] != str(ORDER_CAP)
                or not phase["approved_decisions"]
                or phase["session_id"] != sid
                or phase["observer_path"] != str(manager.paths.observer)
                or phase["market_path"] != str(manager.paths.market)
                or (
                    phase["classification"] != "ACTUAL_TESTNET_PREVIEW"
                    and not isinstance(manager.client._http._transport, httpx.MockTransport)
                )
            ):
                raise ValueError
        except ValueError, KeyError, TypeError:
            raise TestnetError("E02_REAL_PHASE_A_REQUIRED") from None
    for gate, kind in (("B", "ORDER_TEST_PASSED"), ("C", None)):
        cid = gates[gate]["evidence"]
        intents = store.rows(
            "SELECT * FROM order_intents WHERE client_id=? AND session_id=?", (cid, sid)
        )
        if not intents:
            raise TestnetError("E02_GATE_EVIDENCE_MISSING")
        intent = intents[0]
        if gate == "B":
            events = store.rows(
                "SELECT details FROM reconciliation_events WHERE session_id=? AND kind=?",
                (sid, kind),
            )
            if intent["checked_ms"] is None or not any(
                json.loads(e["details"]) == cid for e in events
            ):
                raise TestnetError("E02_GATE_B_UNVERIFIED")
        else:
            orders = store.rows(
                "SELECT * FROM exchange_orders WHERE client_id=? AND session_id=?", (cid, sid)
            )
            if (
                intent["attempted_ms"] is None
                or intent["state"] not in {"FILLED", "CANCELED"}
                or not orders
            ):
                raise TestnetError("E02_GATE_C_UNVERIFIED")
    return {g: gates[g] for g in sorted(required)}
