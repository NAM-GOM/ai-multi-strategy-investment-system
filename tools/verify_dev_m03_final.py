"""Opt-in public-only final DEV-M03 recovery and real 4H close evidence."""

import argparse
import asyncio
import ctypes
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from trading_system.binance.client import BinanceClient
from trading_system.binance.public import PublicAPI
from trading_system.binance.websocket import WebSocketMonitor
from trading_system.config import SYMBOLS, Config
from trading_system.market_data.parser import parse_message
from trading_system.persistence.collector import Collector
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.records import INTERVAL_MS, CandleRecord, now_ms
from trading_system.persistence.recovery import Backfill
from trading_system.persistence.repository import MarketRepository
from trading_system.persistence.store import MarketStore


def save(folder, report):
    temporary = folder / "result.json.tmp"
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(folder / "result.json")


def protect(directory):
    if directory is None:
        return {}
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.iterdir())
        if p.is_file() and not p.name.endswith(("-shm", ".writer.lock"))
    }


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def values(record):
    return tuple(
        str(getattr(record, field)) for field in ("open", "high", "low", "close", "volume")
    )


class ObservedStore(MarketStore):
    def __init__(self, path):
        super().__init__(path)
        self.transitions = []

    def record_gap(self, *args, **kwargs):
        gap_id, created = super().record_gap(*args, **kwargs)
        if created:
            self.transitions.append({"gap_id": gap_id, "status": "OPEN", "at_ms": now_ms()})
        return gap_id, created

    def set_gap_status(self, gap_id, status, source=None):
        super().set_gap_status(gap_id, status, source)
        row = self.connection.execute(
            "SELECT status,resolution_source FROM data_gaps WHERE gap_id=?", (gap_id,)
        ).fetchone()
        self.transitions.append(
            {"gap_id": gap_id, "status": row[0], "source": row[1], "at_ms": now_ms()}
        )


def recovery(folder, report):
    db = folder / "recovery-fixture.sqlite"
    config = PersistenceConfig(db_path=db)
    with ObservedStore(db) as store, BinanceClient(Config()) as client:
        public = PublicAPI(client)
        seeded = Backfill(store, public, config).run()
        if seeded["data_status"] != "COMPLETE":
            report.update(status="BLOCKED_ENVIRONMENT", recovery=seeded)
            return
        target = store.connection.execute(
            "SELECT max(open_time_ms)-? FROM candles_4h WHERE symbol='BTCUSDT'",
            (2 * INTERVAL_MS,),
        ).fetchone()[0]
        expected = public.candles_range(
            "BTCUSDT", start_time_ms=target, end_time_ms=target + INTERVAL_MS - 1
        )[0]
        other_rows = [
            tuple(row)
            for row in store.connection.execute(
                "SELECT * FROM candles_4h WHERE NOT(symbol='BTCUSDT' AND open_time_ms=?) "
                "ORDER BY symbol,open_time_ms",
                (target,),
            )
        ]
        # Delete only from this new fixture; never open original live DBs writable.
        with store.transaction():
            store.connection.execute(
                "DELETE FROM candles_4h WHERE symbol='BTCUSDT' AND open_time_ms=?", (target,)
            )
        assert (
            store.connection.execute(
                "SELECT count(*) FROM candles_4h WHERE symbol='BTCUSDT' AND open_time_ms=?",
                (target,),
            ).fetchone()[0]
            == 0
        )
        store.transitions.clear()
        recovered = Backfill(store, public, config).run()
        after_other_rows = [
            tuple(row)
            for row in store.connection.execute(
                "SELECT * FROM candles_4h WHERE NOT(symbol='BTCUSDT' AND open_time_ms=?) "
                "ORDER BY symbol,open_time_ms",
                (target,),
            )
        ]
        assert fingerprint(other_rows) == fingerprint(after_other_rows)
        transitions = list(store.transitions)
    with MarketRepository(db) as repository:
        actual = repository.candles("BTCUSDT", target, target)[0]
        assert actual.source == "REST_RECOVERY"
        assert actual.event_time_ms is None
        assert values(actual) == values(expected)
        assert recovered["candles_written"] == 1
        assert [t["status"] for t in transitions] == ["OPEN", "RECOVERING", "RESOLVED"]
        verified = repository.verify()
        assert repository.integrity() and verified["data_status"] == "COMPLETE"
        report.update(
            status="PASS",
            fixture_path=str(db),
            missing_row_absence_verified=True,
            target_symbol="BTCUSDT",
            target_open_ms=target,
            target_open_utc=datetime.fromtimestamp(target / 1000, UTC).isoformat(),
            transitions=transitions,
            recovery=recovered,
            source=actual.source,
            expected_public_rest_ohlcv=values(expected),
            stored_ohlcv=values(actual),
            other_fixture_rows_unchanged=True,
            other_fixture_rows_sha256=fingerprint(other_rows),
            verification=verified,
        )


class ObservedMonitor(WebSocketMonitor):
    def __init__(self, folder):
        super().__init__()
        self.folder = folder
        self.closed_observations = []

    def _on_message(self, raw):
        result = super()._on_message(raw)
        message = json.loads(raw)
        data = message.get("data", message)
        if data.get("e") == "kline" and data.get("k", {}).get("x") is True:
            received = self.utc_now()
            parsed = parse_message(raw, received)
            self.closed_observations.append(parsed)
            with (self.folder / "actual-closed-ws.jsonl").open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"received_at_utc": received.isoformat(), "message": message}) + "\n"
                )
        return result


def closed_rows(path, events):
    with MarketRepository(path) as repository:
        return {
            event.symbol: repository.candles(
                event.symbol,
                int(event.open_time.timestamp() * 1000),
                int(event.open_time.timestamp() * 1000),
            )[0]
            for event in events
        }


def update_document(report):
    document = Path("docs/DEV-M03-final-validation.md")
    if not document.exists():
        return
    body = (
        f"\n상태: **{report['status']}**. 결과: `{report['output_dir']}/result.json`.\n\n"
        f"실제 k.x=true 수신 심볼: {', '.join(report.get('observed_symbols', [])) or '없음'}.\n"
        f"WS_LIVE 저장: {report.get('ws_live_persistence', 'NOT_TESTED')}; "
        f"동일 수신 이벤트 재처리: {report.get('captured_event_duplicate_replay', 'NOT_TESTED')}; "
        f"재시작 보존: {report.get('restart_preservation', 'NOT_TESTED')}.\n\n"
        "동일 이벤트 재처리는 실제 수신한 공개 WS payload를 다시 저장한 검사이며, "
        "새 네트워크 중복 수신을 관찰한 것으로 표시하지 않는다.\n"
    )
    if report.get("verification"):
        body += "\n```json\n" + json.dumps(report["verification"], indent=2) + "\n```\n"
    if report.get("runs"):
        body += "\n두 실제 수집 보고서: `run-1.json`, `run-2.json`.\n"
    body += (
        "\n승격 제안: 기능 검증 PASS 후보. 과거 12:47 사건의 정확한 이벤트별 재구성은 "
        "당시 진단 로그 부족으로 여전히 확정할 수 없다.\n"
        if report["status"] == "PASS"
        else "\n승격 제안: 보류. 관찰되지 않은 항목은 NOT_TESTED.\n"
    )
    text = document.read_text(encoding="utf-8")
    begin, end = "<!-- LIVE_RESULTS_START -->", "<!-- LIVE_RESULTS_END -->"
    assert begin in text and end in text
    text = text.split(begin)[0] + begin + body + end + text.split(end, 1)[1]
    document.write_text(text, encoding="utf-8", newline="\n")


def live(folder, report, args):
    start = datetime.fromisoformat(args.start_at_utc).astimezone(UTC)
    report.update(status="WAITING_FOR_ACTUAL_4H_CLOSE", start_at_utc=start.isoformat())
    save(folder, report)
    while datetime.now(UTC) < start:
        time.sleep(min(20, max(0.01, (start - datetime.now(UTC)).total_seconds())))
    report.update(status="COLLECTING", actual_started_at_utc=datetime.now(UTC).isoformat())
    save(folder, report)
    db = folder / "live.sqlite"
    config = PersistenceConfig(db_path=db)
    monitor = ObservedMonitor(folder)
    first = asyncio.run(Collector(config, monitor=monitor).run(args.duration))
    (folder / "run-1.json").write_text(json.dumps(first, indent=2), encoding="utf-8")
    observations = {event.key: event for event in monitor.closed_observations}
    events = tuple(observations.values())
    report.update(observed_symbols=sorted({e.symbol for e in events}), first_collection=first)
    if first["status"] != "COMPLETED":
        report.update(status=first["status"], error_category=first["error_category"])
        return
    if set(report["observed_symbols"]) != set(SYMBOLS):
        report.update(status="NOT_TESTED", ws_live_persistence="NOT_TESTED")
        return
    before = closed_rows(db, events)
    report["confirmed_rows"] = {
        s: {
            "open_time_ms": r.open_time_ms,
            "source": r.source,
            "ohlcv": values(r),
            "event_time_ms": r.event_time_ms,
            "ingested_at_ms": r.ingested_at_ms,
        }
        for s, r in before.items()
    }
    if not all(row.source == "WS_LIVE" for row in before.values()):
        report.update(status="NOT_TESTED", ws_live_persistence="NOT_TESTED_REST_ARRIVED_FIRST")
        return
    report.update(status="RESTARTING", ws_live_persistence="PASS")
    save(folder, report)
    with MarketStore(db) as store:
        duplicates = store.write_batch(
            candles=tuple(CandleRecord.from_ws(e, now_ms()) for e in events)
        )
    assert duplicates["duplicate_candles"] == len(events)
    assert duplicates["candles_written"] == duplicates["conflicts"] == 0
    assert closed_rows(db, events) == before
    with (
        (folder / "restart.stdout.log").open("x", encoding="utf-8") as stdout,
        (folder / "restart.stderr.log").open("x", encoding="utf-8") as stderr,
    ):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "trading_system.cli",
                "collect",
                "--duration",
                str(args.restart_duration),
                "--db-path",
                str(db),
                "--report-file",
                str(folder / "run-2.json"),
            ],
            stdout=stdout,
            stderr=stderr,
        )
        report["restart_process_id"] = process.pid
        report["first_process_id"] = os.getpid()
        assert process.pid != os.getpid()
        assert process.wait() == 0
    second = json.loads((folder / "run-2.json").read_text(encoding="utf-8"))
    assert second["status"] == "COMPLETED"
    assert closed_rows(db, events) == before
    with MarketRepository(db) as repository:
        summary = repository.summary()
        assert repository.integrity() and summary["verification"]["data_status"] == "COMPLETE"
        assert len(repository.runs()) == 2
        assert summary["counts"]["candle_conflicts"] == 0
        assert all(r["status"] == "COMPLETED" for r in repository.runs())
    report.update(
        status="PASS",
        captured_event_duplicate_replay="PASS",
        duplicate_replay=duplicates,
        restart_preservation="PASS",
        two_completed_runs_preserved=True,
        runs=[first, second],
        verification=summary["verification"],
        final_db_summary=summary,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("recovery", "live"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protected-dir", type=Path)
    parser.add_argument("--start-at-utc", default=datetime.now(UTC).isoformat())
    parser.add_argument("--duration", type=float, default=900)
    parser.add_argument("--restart-duration", type=float, default=120)
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    folder.relative_to(Path("data").resolve())
    folder.mkdir(parents=True, exist_ok=False)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(folder / "public-validation.log", encoding="utf-8")],
    )
    protected = protect(args.protected_dir)
    report = dict(
        phase=args.phase,
        status="RUNNING",
        output_dir=str(args.output_dir),
        started_at_utc=datetime.now(UTC).isoformat(),
        private_api_called=False,
        credentials_used=False,
        dotenv_read=False,
        original_file_hashes=protected,
    )
    save(folder, report)
    try:
        if args.phase == "recovery":
            recovery(folder, report)
        else:
            live(folder, report, args)
    except Exception as error:
        report.update(status="FAILED_VALIDATION", error_category=type(error).__name__)
    report.update(
        original_files_unchanged=protect(args.protected_dir) == protected,
        ended_at_utc=datetime.now(UTC).isoformat(),
    )
    if not report["original_files_unchanged"]:
        report.update(status="FAILED_VALIDATION", error_category="original_files_changed")
    save(folder, report)
    if args.phase == "live":
        update_document(report)
    print(json.dumps({"status": report["status"], "result_path": str(folder / "result.json")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    # A temporary, process-scoped sleep request; no persistent power settings change.
    awake = False
    if os.name == "nt":
        awake = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
    try:
        raise SystemExit(main())
    finally:
        if awake:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
