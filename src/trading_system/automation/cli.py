"""Operator requests and read-only status; no arbitrary order arguments or host override."""

import argparse
import asyncio
import json
import os
import signal
import threading
from pathlib import Path

from trading_system.execution.config import TestnetConfig
from trading_system.execution.testnet_client import TestnetExecutionClient, read_quote
from trading_system.persistence.store import PersistenceError
from trading_system.runtime.cli import quotes_now
from trading_system.runtime.common import RuntimePaths, readonly_database
from trading_system.testnet.client import TestnetError

from .control import COMMANDS, Control
from .executor import Executor
from .policy import CAPITAL, ORDER_CAP
from .preflight import frozen_sources, online_readonly, operator_review

DEFAULT_CONTROL = Path("/var/lib/CryptoAutoTrading/state/e02-executor")
DEFAULT_ACCEPTANCE = Path("/etc/CryptoAutoTrading/m05-acceptance.json")


def status(paths, directory):
    control = Control(directory)
    result = {
        "mode": control.mode(),
        "emergency_stop": control.killed(),
        "capital_usdt": str(CAPITAL),
        "order_cap_usdt": str(ORDER_CAP),
    }
    if paths.execution.is_file():
        result["operator_review_token"] = operator_review(paths, directory)
        with readonly_database(paths.execution) as db:
            result["session"] = [
                dict(r)
                for r in db.execute(
                    "SELECT id,active,hold,kill FROM testnet_sessions WHERE active=1"
                )
            ]
            for name in ("order_intents", "exchange_orders", "positions", "strategy_allocations"):
                result[name] = [dict(r) for r in db.execute("SELECT * FROM " + name)]
    health = Path(directory) / "health.json"
    if health.exists():
        result["runtime"] = json.loads(health.read_text())
    responses = Path(directory) / "responses"
    result["recent_commands"] = [
        json.loads(p.read_text())
        for p in sorted(responses.glob("*.json"), key=lambda p: p.stat().st_mtime_ns)[-10:]
    ]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="DEV-E02 T1 Spot Testnet executor; OFF on startup")
    parser.add_argument("command", choices=("serve", "status", "preflight", *sorted(COMMANDS)))
    parser.add_argument(
        "--state-root", type=Path, default=Path("/var/lib/CryptoAutoTrading/state/continuous-01")
    )
    parser.add_argument(
        "--execution-db",
        type=Path,
        default=Path("/var/lib/CryptoAutoTrading/state/testnet-e01/testnet_execution.sqlite"),
    )
    parser.add_argument("--control-dir", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--m05-acceptance", type=Path, default=DEFAULT_ACCEPTANCE)
    parser.add_argument("--online", action="store_true", help="Preflight GET only; no mutation")
    parser.add_argument(
        "--connection-only",
        action="store_true",
        help="GET reconciliation without activation approval",
    )
    parser.add_argument("--confirm", action="store_true", help="Explicit operator command request")
    parser.add_argument("--token", help="Activation review token from online preflight")
    parser.add_argument("--client-id", help="Existing attributed T1 intent for cancel only")
    parser.add_argument(
        "--once", action="store_true", help="One service cycle, still OFF initially"
    )
    args = parser.parse_args(argv)
    client = service = None
    stopping = threading.Event()
    handlers = {}
    try:
        paths = RuntimePaths(args.state_root, args.execution_db)
        if args.command == "status":
            print(json.dumps(status(paths, args.control_dir), sort_keys=True))
            return 0
        if args.command == "preflight":
            result = {
                "state": "OFFLINE_SOURCE_PASS",
                "sources": frozen_sources(),
                "execution_enabled": False,
                "live_acceptance": "NOT_TESTED",
            }
            if args.online:
                result = online_readonly(
                    paths,
                    directory=args.control_dir,
                    acceptance_path=None if args.connection_only else args.m05_acceptance,
                    quote_provider=lambda: asyncio.run(quotes_now()),
                )
            print(json.dumps(result, sort_keys=True))
            return 0
        if args.command in COMMANDS:
            if not args.confirm:
                raise TestnetError("EXPLICIT_OPERATOR_CONFIRMATION_REQUIRED")
            if args.command in {"on", "bind", "reset-kill"} and not args.token:
                raise TestnetError("E02_ACTIVATION_REVIEW_REQUIRED")
            if args.command == "cancel" and not args.client_id:
                raise TestnetError("E02_CANCEL_CLIENT_ID_REQUIRED")
            print(
                json.dumps(
                    Control(args.control_dir).enqueue(
                        args.command, token=args.token, client_id=args.client_id
                    ),
                    sort_keys=True,
                )
            )
            return 0
        config = TestnetConfig.from_env()
        # M05's two original unlocks remain OFF; E02 has a dedicated provisioning switch.
        if any(
            os.environ.get(k, "OFF") != "OFF"
            for k in ("BINANCE_TESTNET_TRADING_ENABLED", "BINANCE_TESTNET_AUTOMATED_ENABLED")
        ):
            raise TestnetError("E02_REQUIRES_LEGACY_UNLOCKS_OFF")
        config = TestnetConfig(
            config.api_key,
            config.api_secret,
            os.environ.get("E02_TESTNET_MUTATIONS_ALLOWED") == "YES_E02_TESTNET_ONLY",
        )
        client = TestnetExecutionClient(config)
        service = Executor(
            paths,
            args.control_dir,
            client,
            lambda s: asyncio.run(read_quote(s)),
            acceptance_path=args.m05_acceptance,
            batch_quote_provider=lambda: asyncio.run(quotes_now()),
        )
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, lambda *_: stopping.set())
        while not stopping.is_set():
            service.tick()
            if args.once:
                break
            stopping.wait(5 if service.control.mode()["enabled"] else 30)
        service.control.off()
        service.publish("STOPPED")
        return 0
    except (TestnetError, PersistenceError) as error:
        if service:
            service.control.off()
            service.publish("HOLD", error.kind)
        print(json.dumps({"state": "HOLD", "category": error.kind, "execution_enabled": False}))
        return 78
    except OSError, ValueError, KeyError, TypeError:
        if service:
            service.control.off()
        print('{"state":"LOCAL_STATE_FAILURE","execution_enabled":false}')
        return 78
    finally:
        if service:
            service.close()
        if client:
            client.close()
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
