"""Opt-in Windows supervisor for one future real close; public M03 + read-only M04."""

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.observer.audit import reproduction_gate
from trading_system.observer.model import STRATEGIES
from trading_system.persistence.records import INTERVAL_MS, now_ms
from trading_system.persistence.repository import MarketRepository


def save(folder, report):
    temporary = folder / "result.json.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(folder / "result.json")


def launch(folder, name, command):
    with (
        (folder / f"{name}.stdout.log").open("w") as stdout,
        (folder / f"{name}.stderr.log").open("w") as stderr,
    ):
        return subprocess.Popen(
            [sys.executable, "-m", "trading_system.cli", *command], stdout=stdout, stderr=stderr
        )


def wait_until(timestamp):
    while now_ms() < timestamp:
        time.sleep(min(30, (timestamp - now_ms()) / 1000))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-close-ms", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    close = args.target_close_ms
    if close % INTERVAL_MS or close <= now_ms() + 660_000:
        raise ValueError("Requires a future real 4H close at least eleven minutes away")
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "LIVE_NOT_OBSERVED",
        "supervisor_pid": os.getpid(),
        "scheduled_target_close_ms": close,
        "started_at_ms": now_ms(),
        "formal_w04_started": False,
        "execution_performed": False,
        "credentials_used": False,
        "source_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    save(folder, report)
    collector = observer = None
    keep_awake = os.name == "nt"
    try:
        if keep_awake:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000003)
        report["audit"] = reproduction_gate()
        save(folder, report)
        wait_until(close - 600_000)
        market, signals = folder / "market.sqlite", folder / "observer.sqlite"
        collector = launch(
            folder,
            "collector",
            [
                "collect",
                "--duration",
                "1020",
                "--bootstrap-days",
                "9",
                "--db-path",
                str(market),
                "--report-file",
                str(folder / "collector.json"),
            ],
        )
        report["collector_pid"] = collector.pid
        save(folder, report)
        wait_until(close - 300_000)
        observer = launch(
            folder,
            "observer",
            [
                "observe",
                "--duration",
                "600",
                "--db-path",
                str(market),
                "--observer-db",
                str(signals),
                "--report-file",
                str(folder / "observer.json"),
            ],
        )
        report["observer_pid"] = observer.pid
        save(folder, report)
        observer_code = observer.wait(timeout=660)
        collector_code = collector.wait(timeout=180)
        report.update(observer_exit_code=observer_code, collector_exit_code=collector_code)
        if observer_code or collector_code:
            report["status"] = "LIVE_VALIDATION_FAILED"
            save(folder, report)
            return 2
        import sqlite3

        with MarketRepository(market) as repository:
            rows = {
                s: repository.candles(s, close - INTERVAL_MS, close - INTERVAL_MS) for s in SYMBOLS
            }
            report["candle_sources"] = {s: [c.source for c in r] for s, r in rows.items()}
            if not all(len(r) == 1 and r[0].source == "WS_LIVE" for r in rows.values()):
                report["status"] = "LIVE_NOT_OBSERVED"
                save(folder, report)
                return 2
            report["market_quality"] = repository.verify(now_ms())
        db = sqlite3.connect(signals.as_uri() + "?mode=ro", uri=True)
        try:
            saved = db.execute(
                "SELECT strategy_id,symbol,decision_hash,record FROM signal_decisions "
                "WHERE bar_open_ms=?",
                (close - INTERVAL_MS,),
            ).fetchall()
            report["decisions"] = [json.loads(r[3]) for r in saved]
            report["decision_hashes_before_restart"] = [r[2] for r in saved]
        finally:
            db.close()
        if {(r[0], r[1]) for r in saved} != {(s, a) for s in STRATEGIES for a in SYMBOLS}:
            raise RuntimeError("Shared batch incomplete")
        restart = launch(
            folder,
            "restart",
            [
                "observe",
                "--duration",
                "10",
                "--db-path",
                str(market),
                "--observer-db",
                str(signals),
                "--report-file",
                str(folder / "restart.json"),
            ],
        )
        report["restart_pid"] = restart.pid
        if restart.wait(timeout=60):
            raise RuntimeError("Restart failed")
        db = sqlite3.connect(signals.as_uri() + "?mode=ro", uri=True)
        try:
            after = db.execute(
                "SELECT decision_hash FROM signal_decisions WHERE bar_open_ms=?",
                (close - INTERVAL_MS,),
            ).fetchall()
            report["observer_integrity"] = db.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            db.close()
        report["restart_idempotent"] = [r[0] for r in after] == [r[2] for r in saved]
        report["modes"] = sorted({d["observation_mode"] for d in report["decisions"]})
        report["no_action_count"] = sum(d["decision"] == "NO_ACTION" for d in report["decisions"])
        report["status"] = (
            "LIVE_OBSERVER_PASS" if report["restart_idempotent"] else "LIVE_VALIDATION_FAILED"
        )
        report["completed_at_ms"] = now_ms()
        save(folder, report)
        return 0 if report["status"] == "LIVE_OBSERVER_PASS" else 2
    except Exception as error:
        report.update(status="LIVE_VALIDATION_FAILED", error_category=type(error).__name__)
        save(folder, report)
        return 2
    finally:
        for process in (observer, collector):
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=20)
        if keep_awake:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == "__main__":
    raise SystemExit(main())
