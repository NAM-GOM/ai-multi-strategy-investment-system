"""Windows/Linux CLI; offline by default, manual approval and T1 activation are distinct."""

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec

from .config import SafetyConfig, TestnetConfig
from .execution_store import ExecutionStore
from .models import Quote
from .order_manager import OrderManager
from .position_manager import PositionManager
from .signal_router import SignalRouter
from .testnet_client import TestnetExecutionClient, read_quote

COMMANDS = (
    "testnet-status",
    "testnet-balances",
    "testnet-order-check",
    "testnet-order-submit",
    "testnet-order-status",
    "testnet-order-cancel",
    "testnet-reconcile",
    "testnet-kill-switch",
    "testnet-router-status",
    "testnet-router-dry-run",
    "testnet-router-run",
    "testnet-allocate",
)


class AssumedPositionManager(PositionManager):
    def __init__(self, store, sid, capital):
        super().__init__(store, sid)
        self.capital = dec(capital)
        if self.capital <= 0:
            raise TestnetError("INVALID_ASSUMED_CAPITAL")

    def verify(self, strategy=None):
        pass

    def allocation(self, strategy=None):
        return {"cash": str(self.capital), "initial_capital": str(self.capital)}

    def positions(self, strategy=None):
        return []

    def reserved(self, strategy=None):
        return dec(0), {}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Integrated M04 / Spot TESTNET execution")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--db", default="data/testnet_execution.sqlite")
    parser.add_argument("--observer-db", default="data/strategy_observer.sqlite")
    parser.add_argument("--market-db", default="data/market_data.sqlite")
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    parser.add_argument("--side", choices=("BUY", "SELL"))
    parser.add_argument("--quantity")
    parser.add_argument("--price")
    parser.add_argument("--client-id")
    parser.add_argument("--confirm-test-request", action="store_true")
    parser.add_argument("--confirm-testnet-order", action="store_true")
    parser.add_argument("--approval-token")
    parser.add_argument("--confirm-testnet-cancel", action="store_true")
    parser.add_argument("--confirm-automated-testnet", action="store_true")
    parser.add_argument("--kill", choices=("on", "off"), default="on")
    parser.add_argument("--new-session", action="store_true")
    parser.add_argument("--acknowledge-reset", action="store_true")
    parser.add_argument(
        "--capital", help="Explicit T1 allocation after verified account reconciliation"
    )
    parser.add_argument("--assumed-capital", help="DRY_RUN only; no actual positions or balances")
    parser.add_argument(
        "--assumptions", help="Offline JSON: exchangeInfo, balances, quotes; never credentials"
    )
    args = parser.parse_args(argv)
    if args.new_session != args.acknowledge_reset or (
        args.new_session and (not args.online or args.command != "testnet-reconcile")
    ):
        parser.error("new session needs online reconciliation and explicit reset acknowledgement")
    if args.assumed_capital and args.command != "testnet-router-dry-run":
        parser.error("assumed capital is only available for router DRY_RUN")
    if args.command == "testnet-allocate" and (not args.capital or not args.online):
        parser.error("allocation requires --capital and --online")
    if (
        args.command in ("testnet-order-submit", "testnet-order-status", "testnet-order-cancel")
        and not args.client_id
    ):
        parser.error("--client-id is required")
    if (
        args.command == "testnet-order-check"
        and not args.client_id
        and not all((args.symbol, args.side, args.quantity, args.price))
    ):
        parser.error("order check requires symbol, side, quantity and price")
    store = client = engine = None
    try:
        config, safety = TestnetConfig.from_env(), SafetyConfig.from_env()
        store = ExecutionStore(args.db)
        client = TestnetExecutionClient(config)
        engine = OrderManager(client, store, acknowledge_reset=args.new_session, safety=safety)
        command = args.command
        if command == "testnet-status":
            if args.online:
                engine.reconcile()
            result = {
                "mode": "DRY_RUN" if not config.trading_enabled else "TESTNET_UNLOCKED",
                "automation": "DISABLED" if not safety.automated_enabled else "GATES_REQUIRED",
                "session": store.session(),
                "gates": store.rows(
                    "SELECT * FROM execution_gates WHERE session_id=?", (engine.sid,)
                ),
                "intents": store.rows(
                    "SELECT * FROM order_intents WHERE session_id=?", (engine.sid,)
                ),
                "allocations": store.rows(
                    "SELECT * FROM strategy_allocations WHERE session_id=?", (engine.sid,)
                ),
                "positions": engine.positions.report({}),
                "local_balance_totals": {
                    k: str(v) for k, v in engine.positions.latest_balances().items()
                },
                "balance_source": "RECONCILED_NOW" if args.online else "LOCAL_LAST_SNAPSHOT",
            }
        elif command == "testnet-kill-switch":
            store.kill(engine.sid, engine.clock(), args.kill == "on")
            result = {"kill": args.kill}
        elif command.startswith("testnet-router-"):
            manager = engine.positions
            if args.assumed_capital:
                manager = AssumedPositionManager(store, engine.sid, args.assumed_capital)
            router = SignalRouter(manager, args.observer_db, args.market_db, safety=safety)
            router.initialize(engine.clock())
            if command == "testnet-router-status":
                result = router.status()
            else:
                quotes, info, balances = {}, {"symbols": []}, []
                if args.online:
                    engine.reconcile()
                    info = client.request("GET", "/api/v3/exchangeInfo")
                    balances = client.request("GET", "/api/v3/account")["balances"]
                    quotes = {
                        symbol: asyncio.run(read_quote(symbol))
                        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
                    }
                elif args.assumptions:
                    data = json.loads(Path(args.assumptions).read_text(encoding="utf-8"))
                    info, balances = data["exchangeInfo"], data["balances"]
                    quotes = {q["s"]: Quote.parse(q, q["received_ms"]) for q in data["quotes"]}
                if command == "testnet-router-run":
                    if not args.online:
                        raise TestnetError("AUTOMATION_REQUIRES_ONLINE_RECONCILIATION")
                    engine.enable_automation(confirm=args.confirm_automated_testnet)
                    engine.automation_guard()
                    protective = engine.protective_intents(router, quotes, info, balances)
                else:
                    protective = []
                reports = router.route(
                    engine.clock(), quotes, info, balances, dry_run=command != "testnet-router-run"
                )
                if command == "testnet-router-run":
                    reports = protective + reports
                    for report in reports:
                        if report.get("client_id"):
                            engine.check(report["client_id"], confirm_test=True)
                            report["execution"] = engine.submit(
                                report["client_id"], confirm_order=True, automated=True
                            )
                result = {
                    "signals": reports,
                    "assumed_capital": args.assumed_capital,
                    "run_scope": "ONE_CYCLE_NO_BACKGROUND_PROCESS",
                }
        elif command == "testnet-order-check":
            cid = args.client_id or engine.create(args.symbol, args.side, args.quantity, args.price)
            result = engine.check(cid, confirm_test=args.online and args.confirm_test_request)
            result["review"] = engine.review(cid)
        elif not args.online:
            result = {"state": "DRY_RUN", "network": "NOT_REQUESTED"}
        elif command == "testnet-order-submit":
            print(json.dumps(engine.review(args.client_id), sort_keys=True), flush=True)
            result = engine.submit(
                args.client_id,
                confirm_order=args.confirm_testnet_order,
                approval_token=args.approval_token,
            )
        elif command == "testnet-order-cancel":
            result = engine.cancel(args.client_id, confirm_cancel=args.confirm_testnet_cancel)
        elif command == "testnet-order-status":
            engine.reconcile()
            result = engine.status(args.client_id)
        elif command == "testnet-allocate":
            engine.reconcile()
            engine.guard()
            engine.positions.allocate(args.capital, engine.clock())
            result = engine.positions.allocation()
        elif command == "testnet-reconcile":
            result = engine.reconcile()
        else:
            engine.reconcile()
            result = client.request("GET", "/api/v3/account")["balances"]
        print(json.dumps(result, sort_keys=True))
        return 0
    except TestnetError as error:
        if engine and store and not store.failed:
            try:
                engine._failure(error)
            except TestnetError:
                error = TestnetError("DB_FAILED")
        print(json.dumps({"state": error.kind, "code": error.code}))
        return 2
    except OSError, sqlite3.Error:
        print('{"state":"DB_OR_FILE_FAILED"}')
        return 2
    except KeyError, TypeError, ValueError:
        print('{"state":"INVALID_OFFLINE_ASSUMPTIONS"}')
        return 2
    finally:
        if client:
            client.close()
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
