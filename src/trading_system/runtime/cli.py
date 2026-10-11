"""Explicit continuous/smoke modes; no submission, allocation or activation options."""

import argparse
import asyncio
import json
import logging
import math
import signal
import sqlite3
import threading
import time
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.execution.config import TestnetConfig
from trading_system.execution.models import Quote
from trading_system.execution.testnet_client import read_quote
from trading_system.observer.model import ObserverError, canonical
from trading_system.persistence.records import now_ms
from trading_system.persistence.store import PersistenceError, WriterLease
from trading_system.testnet.client import TestnetError

from .bridge import TRANSIENT_HOLDS, PreviewBridge, ReadOnlyTestnetClient
from .collector import RuntimeCollector, continuous_config
from .common import (
    EXECUTION_PATH,
    STATE_ROOT,
    RuntimePaths,
    StatusSink,
    disabled_environment,
    public_environment,
)
from .observer import RuntimeObserver
from .preflight import preflight

EX_CONFIG = 78  # systemd RestartPreventExitStatus


async def quotes_now():
    values = await asyncio.gather(*(read_quote(symbol) for symbol in SYMBOLS))
    return {q.symbol: q for q in values}


def main(argv=None):
    parser = argparse.ArgumentParser(description="DEV-M05 continuous runtime / READ-ONLY preview")
    parser.add_argument("role", choices=("collector", "observer", "bridge", "preflight", "status"))
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--execution-db", type=Path, default=EXECUTION_PATH)
    parser.add_argument("--smoke-seconds", type=float, help="Explicit bounded smoke run only")
    parser.add_argument("--online", action="store_true", help="Bridge GET-only Testnet connection")
    parser.add_argument("--once", action="store_true", help="One bridge preview cycle")
    parser.add_argument("--assumptions", type=Path, help="Offline mock filters/balances/quotes")
    parser.add_argument("--assumed-capital", help="Hypothetical flat capital; SIMULATED_TEST only")
    parser.add_argument(
        "--host-check", action="store_true", help="Read-only NUC installation checks"
    )
    args = parser.parse_args(argv)
    if args.smoke_seconds is not None and (
        not math.isfinite(args.smoke_seconds) or args.smoke_seconds <= 0
    ):
        parser.error("smoke-seconds must be finite and positive")
    if args.role != "bridge" and (
        args.online or args.once or args.assumptions or args.assumed_capital
    ):
        parser.error("connection/preview options are only valid for bridge")
    if args.online and (args.assumptions or args.assumed_capital):
        parser.error("SIMULATED_TEST assumptions cannot be combined with an online run")
    sink = service = lease = client = None
    stopping = threading.Event()
    handlers = {}

    def stop_requested(*_):
        stopping.set()

    try:
        disabled_environment()
        paths = RuntimePaths(args.state_root, args.execution_db)
        if args.role == "preflight":
            print(canonical(preflight(paths, host_check=args.host_check)))
            return 0
        if args.role == "status":
            result = {}
            for role in ("collector", "observer", "bridge"):
                try:
                    record = json.loads(paths.health(role).read_text())
                    record["age_ms"] = now_ms() - record["timestamp_ms"]
                    result[role] = record
                except OSError:
                    result[role] = {"state": "NOT_STARTED"}
            print(canonical(result))
            return 0
        # Never configure HTTP/frame logging. Errors are fixed local categories only.
        logging.getLogger("httpx").disabled = True
        logging.getLogger("httpcore").disabled = True
        paths.role_dir(args.role).mkdir(parents=True, exist_ok=True)
        # Take ownership before writing shared health/log artifacts. Collector and
        # Observer also retain their original SQLite WriterLease inside M03/M04.
        lease = WriterLease(paths.role_dir(args.role) / "service")
        sink = StatusSink(paths, args.role)
        sink.publish("STARTING", force=True)
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, stop_requested)
        if args.role == "collector":
            public_environment()

            async def collect():
                stop = asyncio.Event()

                async def watch_signal():
                    while not stopping.is_set():
                        await asyncio.sleep(0.1)
                    stop.set()

                watcher = asyncio.create_task(watch_signal())
                try:
                    collector = RuntimeCollector(continuous_config(paths.market), sink)
                    return await collector.serve(stop, smoke_seconds=args.smoke_seconds)
                finally:
                    watcher.cancel()
                    await asyncio.gather(watcher, return_exceptions=True)

            result = asyncio.run(collect())
            expected = stopping.is_set() or args.smoke_seconds is not None
            ok = result["status"] == "COMPLETED" or (
                stopping.is_set() and not result["error_category"]
            )
            sink.publish(
                "STOPPED" if expected and ok else "FAILED",
                None if expected and ok else "COLLECTOR_UNEXPECTED_OR_FAILED_EXIT",
                force=True,
                summary=result,
            )
            return 0 if expected and ok else 1
        if args.role == "observer":
            public_environment()
            service = RuntimeObserver(paths, sink)
        else:
            service = PreviewBridge(paths, sink)
            config = TestnetConfig.from_env() if args.online else TestnetConfig()
            client = ReadOnlyTestnetClient(config)
        deadline = None if args.smoke_seconds is None else time.monotonic() + args.smoke_seconds
        retry_delay = 5 if args.role == "bridge" else 1
        while not stopping.is_set() and (deadline is None or time.monotonic() < deadline):
            try:
                if args.role == "observer":
                    service.tick()
                else:
                    data = json.loads(args.assumptions.read_text()) if args.assumptions else {}
                    quotes = {
                        q["s"]: Quote.parse(q, q["received_ms"]) for q in data.get("quotes", [])
                    }
                    service.cycle(
                        client,
                        online=args.online,
                        quotes=(lambda: asyncio.run(quotes_now())) if args.online else quotes,
                        info=data.get("exchangeInfo"),
                        balances=data.get("balances"),
                        capital=args.assumed_capital,
                    )
                retry_delay = 5 if args.role == "bridge" else 1
                if args.once:
                    break
            except TestnetError as error:
                sink.publish("HOLD", error.kind, force=True)
                if args.once:
                    return 2
                if error.kind not in TRANSIENT_HOLDS:
                    return EX_CONFIG
                retry_delay = min(60, max(5, retry_delay * 2))
            delay = retry_delay
            if deadline is not None:
                delay = min(delay, max(0, deadline - time.monotonic()))
            stopping.wait(delay)
        sink.publish("STOPPED", force=True)
        return 0
    except ObserverError as error:
        if sink:
            sink.publish("FAILED", error.category, force=True)
        return EX_CONFIG
    except TestnetError as error:
        print(canonical({"state": "HOLD", "category": error.kind, "execution_enabled": False}))
        if sink:
            sink.publish("FAILED", error.kind, force=True)
        return EX_CONFIG
    except PersistenceError as error:
        if sink:
            sink.publish("FAILED", error.kind, force=True)
        return EX_CONFIG if error.kind == "writer_unavailable" else 1
    except OSError, sqlite3.Error, ValueError, KeyError, TypeError:
        print('{"state":"LOCAL_STATE_FAILURE","execution_enabled":false}')
        if sink:
            sink.publish("FAILED", "LOCAL_STATE_FAILURE", force=True)
        return EX_CONFIG
    finally:
        try:
            if isinstance(service, RuntimeObserver):
                service.close()
        finally:
            if client:
                client.close()
            if sink:
                sink.close()
            if lease:
                lease.close()
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
