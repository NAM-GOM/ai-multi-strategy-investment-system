"""Offline audit/replay and read-only market observation commands."""

import json
import math
import sqlite3
import time
from pathlib import Path

from trading_system.observer.audit import historical_frames, reproduction_gate
from trading_system.observer.model import ObserverError, ObserverState, canonical
from trading_system.observer.service import BatchProcessor
from trading_system.observer.store import ObserverStore
from trading_system.persistence.records import INTERVAL_MS, now_ms
from trading_system.persistence.store import PersistenceError, WriterLease


def emit(args, result):
    print(canonical(result), flush=True)
    if args.report_file:
        path = Path(args.report_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def run_observer_cli(args):
    store, run_id, lease = None, None, None
    try:
        # Detect collision before opening the observer DB (including existing symlinks).
        observer_path, market_path = Path(args.observer_db).resolve(), Path(args.db_path).resolve()
        if observer_path == market_path or (
            observer_path.exists() and market_path.exists() and observer_path.samefile(market_path)
        ):
            raise ObserverError("OBSERVER_MARKET_PATH_COLLISION", ObserverState.PERSISTENCE_STOP)
        if args.command == "observer-status":
            path = Path(args.observer_db).resolve()
            if not path.is_file():
                raise ObserverError("OBSERVER_NOT_INITIALIZED")
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            try:
                reader = ObserverStore.__new__(ObserverStore)
                reader.db = db
                emit(args, reader.status())
            finally:
                db.close()
            return 0
        if args.command == "observe":
            duration = 600 if args.duration is None else args.duration
            if not math.isfinite(duration) or duration <= 0:
                raise ObserverError("INVALID_DURATION")
        audit = reproduction_gate()
        if args.command == "strategy-audit":
            emit(args, audit)
            return 0
        observer_path.parent.mkdir(parents=True, exist_ok=True)
        lease = WriterLease(observer_path)
        store = ObserverStore(observer_path)
        started = now_ms()
        run_id = store.start(audit, started)
        processor = BatchProcessor(args.db_path, store, audit, run_id, started)
        results = []
        if args.command == "strategy-replay":
            manifest, frames = historical_frames()
            import pandas as pd

            start = (
                args.start_ms
                if args.start_ms is not None
                else int(pd.Timestamp(manifest["primary_start"]).value // 1_000_000)
            )
            end = (
                args.end_ms
                if args.end_ms is not None
                else int(frames["BTCUSDT"].index[-1].value // 1_000_000)
            )
            if start > end or start % INTERVAL_MS or end % INTERVAL_MS:
                raise ObserverError("INVALID_REPLAY_RANGE")
            if end + INTERVAL_MS > 1790942400000:
                raise ObserverError("REPLAY_REQUIRES_FROZEN_HISTORICAL_RANGE")
            for target in range(start, end + 1, INTERVAL_MS):
                results.append(processor.evaluate(target, now_ms()))
        else:
            deadline = time.monotonic() + duration
            attempted = None
            while time.monotonic() < deadline:
                timestamp = now_ms()
                target = processor.latest_expected_bar(timestamp)
                # Allow the M03 bounded early-close clock retry to commit before reading.
                if timestamp % INTERVAL_MS < 1000:
                    time.sleep(0.1)
                    continue
                if target != attempted:
                    try:
                        result = processor.evaluate(target, timestamp)
                        results.append(result)
                        attempted = target
                        print(canonical(result), flush=True)
                    except ObserverError as error:
                        print(
                            canonical({"status": str(error.state), "error": error.category}),
                            flush=True,
                        )
                        if error.state != ObserverState.DATA_HOLD:
                            raise
                        # Recovered old bars remain state backfill.
                        processor.live_floor_ms = max(processor.live_floor_ms, timestamp)
                time.sleep(min(1, max(0, deadline - time.monotonic())))
        if processor.state == ObserverState.DATA_HOLD:
            raise ObserverError("LIVE_DATA_NOT_READY")
        store.health(run_id, now_ms(), ObserverState.STOPPED)
        emit(
            args,
            {
                "status": "COMPLETED",
                "run_id": run_id,
                "batches": results,
                "formal_w04_started": False,
                "execution_performed": False,
                "audit_manifest_hash": audit["manifest_hash"],
            },
        )
        return 0
    except ObserverError as error:
        emit(
            args,
            {
                "status": str(error.state),
                "error": error.category,
                "formal_w04_started": False,
                "execution_performed": False,
            },
        )
        return 2
    except OSError, sqlite3.Error, PersistenceError:
        emit(
            args,
            {
                "status": "PERSISTENCE_STOP",
                "error": "PERSISTENCE_FAILURE",
                "formal_w04_started": False,
                "execution_performed": False,
            },
        )
        return 2
    except KeyboardInterrupt:
        return 130
    finally:
        if store:
            try:
                if run_id:
                    store.finish(run_id, now_ms())
            finally:
                store.close()
        if lease:
            lease.close()
