"""Opt-in local verification: fresh DB, two timed collections, restart, backup and restore.

Run from the repository root with uv run --frozen python tools/verify_dev_m03.py.
No credentials, existing DB overwrite, arbitrary SQL, or trading operations.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.persistence.records import SOURCES
from trading_system.persistence.repository import MarketRepository


def git_text(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def audit(text):
    values = [os.environ.get(name) for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET")]
    return not (
        any(value and value in text for value in values)
        or re.search(r'(?i)signature\s*=|X-MBX-APIKEY\s*[:=]|"balances"\s*:', text)
    )


def command(folder, label, *arguments):
    output, errors = folder / (label + ".stdout.log"), folder / (label + ".stderr.log")
    print(f"DEV-M03 verification: {label} started", flush=True)
    with output.open("x", encoding="utf-8") as stdout, errors.open("x", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            [sys.executable, "-m", "trading_system.cli", *arguments], stdout=stdout, stderr=stderr
        )
        started, next_progress = time.monotonic(), time.monotonic() + 10
        try:
            while process.poll() is None:
                time.sleep(1)
                if time.monotonic() >= next_progress:
                    print(f"{label}: running {int(time.monotonic() - started)}s", flush=True)
                    next_progress = time.monotonic() + 10
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    safe = audit(output.read_text(encoding="utf-8") + errors.read_text(encoding="utf-8"))
    if not safe:
        raise RuntimeError("secret_exposure_check_failed")
    if process.returncode:
        raise RuntimeError("verification_command_failed")
    print(f"{label}: PASS", flush=True)


def database_evidence(path):
    with MarketRepository(path) as repository:
        summary = repository.summary()
        prices = {s: repository.recent_prices(s, limit=10000) for s in SYMBOLS}
        candles = {s: repository.candles(s, 0, 253_402_300_799_999) for s in SYMBOLS}
        if not repository.integrity() or summary["verification"]["data_status"] != "COMPLETE":
            raise RuntimeError("database_validation_failed")
        if not all(prices[s] and candles[s] for s in SYMBOLS):
            raise RuntimeError("symbol_data_missing")
        if any(c.source not in SOURCES for values in candles.values() for c in values):
            raise RuntimeError("invalid_provenance")
    return summary, prices, candles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=600, help="Seconds for EACH collection")
    parser.add_argument(
        "--output-dir", type=Path, help="Must be a NEW directory; defaults under data/"
    )
    args = parser.parse_args()
    if not math.isfinite(args.duration) or args.duration < 120:
        parser.error("duration must be finite and at least 120s")
    folder = args.output_dir or Path("data") / (
        "dev-m03-validation-"
        + datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    folder.mkdir(parents=True, exist_ok=False)
    db = folder / "market_data.sqlite"
    report = dict(
        cycle="DEV-M03",
        execution_environment=platform.system(),
        github_actions=bool(os.environ.get("GITHUB_ACTIONS")),
        commit=git_text("rev-parse", "HEAD"),
        branch=git_text("branch", "--show-current"),
        started_at_utc=datetime.now(UTC).isoformat(),
        duration_per_run=args.duration,
        status="RUNNING",
        private_credentials_used=False,
    )
    before = git_text("status", "--porcelain")
    try:
        command(folder, "db-init", "db-init", "--db-path", str(db))
        for index in (1, 2):
            command(
                folder,
                f"collect-{index}",
                "collect",
                "--duration",
                str(args.duration),
                "--db-path",
                str(db),
                "--report-file",
                str(folder / f"run-{index}.json"),
            )
            command(folder, f"verify-{index}", "db-verify", "--db-path", str(db))
            summary, prices, candles = database_evidence(db)
            if index == 1:
                first_summary, first_prices, first_candles = summary, prices, candles
            else:
                for symbol in SYMBOLS:
                    current_prices = {p.bucket_start_ms: p for p in prices[symbol]}
                    if not all(
                        p.bucket_start_ms in current_prices
                        and current_prices[p.bucket_start_ms].event_time_ms >= p.event_time_ms
                        for p in first_prices[symbol]
                    ):
                        raise RuntimeError("price_restart_preservation_failed")
                    current_candles = {c.identity: c for c in candles[symbol]}
                    if not all(current_candles.get(c.identity) == c for c in first_candles[symbol]):
                        raise RuntimeError("candle_restart_preservation_failed")
        backup, restored = folder / "backup.sqlite", folder / "restored.sqlite"
        command(folder, "backup", "db-backup", "--db-path", str(db), "--backup-path", str(backup))
        command(
            folder,
            "restore",
            "db-restore",
            "--db-path",
            str(restored),
            "--backup-path",
            str(backup),
        )
        restored_summary, restored_prices, restored_candles = database_evidence(restored)
        if restored_prices != prices or restored_candles != candles:
            raise RuntimeError("backup_restore_data_mismatch")
        runs = [json.loads((folder / f"run-{index}.json").read_text()) for index in (1, 2)]
        if not all(r["status"] == "COMPLETED" for r in runs):
            raise RuntimeError("collection_not_complete")
        if len(summary["latest_runs"]) != 2 or restored_summary["counts"] != summary["counts"]:
            raise RuntimeError("run_history_mismatch")
        source_unchanged = before == git_text("status", "--porcelain")
        report.update(
            status="WINDOWS_LOCAL_LIVE_PASS"
            if platform.system() == "Windows"
            and not report["github_actions"]
            and args.duration >= 600
            and source_unchanged
            else "LIVE_PASS_WITH_FLAGS",
            first_db_summary=first_summary,
            final_db_summary=summary,
            backup_restore="PASS",
            restart_preservation="PASS",
            duplicate_primary_keys="NONE",
            source_unmodified=source_unchanged,
            source_dirty_at_start=bool(before),
            secret_exposure_check="PASS",
            ingestion_runs=runs,
            ws_closed_candle_live_observed=any(r["websocket"]["closed_candles"] > 0 for r in runs),
            candle_sources=summary["candle_sources"],
        )
    except KeyboardInterrupt:
        report.update(status="INTERRUPTED", error_category="interrupted")
    except Exception:
        # Exception values / subprocess output may contain sensitive data. Keep a fixed category.
        report.update(status="FAILED_VALIDATION", error_category="verification_failed")
    report["ended_at_utc"] = datetime.now(UTC).isoformat()
    payload = json.dumps(report, indent=2)
    if not audit(payload):
        report = dict(cycle="DEV-M03", status="FAILED_VALIDATION", secret_exposure_check="FAIL")
        payload = json.dumps(report, indent=2)
    output = folder / "DEV-M03-local-summary.json"
    output.write_text(payload + "\n", encoding="utf-8")
    print(f"DEV-M03 result: {report['status']}\nSummary: {output}")
    print(f"Summary SHA-256: {hashlib.sha256(payload.encode()).hexdigest()}")
    return 0 if report["status"] in ("WINDOWS_LOCAL_LIVE_PASS", "LIVE_PASS_WITH_FLAGS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
