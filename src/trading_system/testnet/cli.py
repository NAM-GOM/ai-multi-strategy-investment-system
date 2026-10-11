"""Separate manual CLI; default operation is offline DRY_RUN."""

import argparse
import json
import sqlite3

from .client import TestnetConfig, TestnetError, TestnetExecutionClient
from .engine import ExecutionEngine
from .store import Store

COMMANDS = (
    "testnet-status",
    "testnet-balances",
    "testnet-order-check",
    "testnet-order-submit",
    "testnet-order-status",
    "testnet-order-cancel",
    "testnet-reconcile",
    "testnet-kill-switch",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manual Spot Testnet; no production integration")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--db", default="data/testnet_execution.sqlite")
    parser.add_argument("--online", action="store_true", help="Permit Testnet read-only preflight")
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    parser.add_argument("--side", choices=("BUY", "SELL"))
    parser.add_argument("--quantity")
    parser.add_argument("--price")
    parser.add_argument("--client-id")
    parser.add_argument("--confirm-test-request", action="store_true")
    parser.add_argument("--confirm-testnet-order", action="store_true")
    parser.add_argument("--confirm-testnet-cancel", action="store_true")
    parser.add_argument("--kill", choices=("on", "off"), default="on")
    parser.add_argument("--new-session", action="store_true")
    parser.add_argument("--acknowledge-reset", action="store_true")
    args = parser.parse_args(argv)
    if args.new_session != args.acknowledge_reset:
        parser.error("--new-session requires --acknowledge-reset (and conversely)")
    if args.new_session and args.command != "testnet-reconcile":
        parser.error("new session is only available with testnet-reconcile")
    if args.new_session and not args.online:
        parser.error("new session requires --online")
    if args.command == "testnet-order-check" and not args.client_id:
        if not all((args.symbol, args.side, args.quantity, args.price)):
            parser.error("order check needs symbol, side, quantity and price")
    if args.command in ("testnet-order-submit", "testnet-order-status", "testnet-order-cancel"):
        if not args.client_id:
            parser.error("--client-id is required")
    config = TestnetConfig.from_env()
    store = client = engine = None
    try:
        store = Store(args.db)
        client = TestnetExecutionClient(config)
        engine = ExecutionEngine(client, store, acknowledge_reset=args.new_session)
        command = args.command
        if command == "testnet-status":
            result = {
                "mode": "TESTNET_ENABLED" if config.trading_enabled else "DRY_RUN",
                "live_validation": "TESTNET_LIVE_NOT_TESTED",
                "session": store.session(),
                "intents": store.rows(
                    "SELECT * FROM order_intents WHERE session_id=?", (engine.sid,)
                ),
            }
        elif command == "testnet-kill-switch":
            store.kill(engine.sid, engine.clock(), args.kill == "on")
            result = {"kill": args.kill}
        elif not args.online:
            # No HTTP, including public requests, unless explicitly requested.
            if command == "testnet-order-check":
                cid = args.client_id or engine.create(
                    args.symbol, args.side, args.quantity, args.price
                )
                result = engine.check(cid)
            else:
                result = {"state": "DRY_RUN", "network": "NOT_REQUESTED"}
        elif command == "testnet-order-check":
            cid = args.client_id or engine.create(args.symbol, args.side, args.quantity, args.price)
            result = engine.check(cid, confirm_test=args.confirm_test_request)
        elif command == "testnet-order-submit":
            result = engine.submit(args.client_id, confirm_order=args.confirm_testnet_order)
        elif command == "testnet-order-cancel":
            result = engine.cancel(args.client_id, confirm_cancel=args.confirm_testnet_cancel)
        elif command == "testnet-order-status":
            engine.reconcile()
            result = engine.status(args.client_id)
        elif command == "testnet-reconcile":
            result = engine.reconcile()
        else:
            engine.reconcile()
            result = client.request("GET", "/api/v3/account")["balances"]
        print(json.dumps(result, sort_keys=True))
        return 0
    except TestnetError as error:
        try:
            if store and engine and not store.failed:
                if error.kind in ("BLOCKED_ENVIRONMENT", "RATE_LIMIT_HOLD", "UNKNOWN_EXECUTION"):
                    store.hold(engine.sid, engine.clock(), error.kind)
                else:
                    with store.transaction():
                        store.db.execute(
                            "INSERT INTO risk_events(session_id,time_ms,kind,client_id) "
                            "VALUES(?,?,?,?)",
                            (engine.sid, engine.clock(), error.kind, args.client_id),
                        )
        except TestnetError, sqlite3.Error:
            error = TestnetError("DB_FAILED")
        print(json.dumps({"state": error.kind, "code": error.code}))
        return 2
    except OSError, sqlite3.Error:
        print('{"state":"DB_FAILED"}')
        return 2
    finally:
        if client:
            client.close()
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
