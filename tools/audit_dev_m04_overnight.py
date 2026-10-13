"""Independent offline, read-only audit of the two completed M04 live windows."""

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.observer.adapter import StrategyAdapter
from trading_system.observer.audit import reproduction_gate
from trading_system.observer.gate import WarmupLoader
from trading_system.observer.model import STRATEGIES, SignalDecision, digest
from trading_system.observer.store import ObserverStore
from trading_system.persistence.records import INTERVAL_MS, utc_datetime
from trading_system.persistence.repository import MarketRepository


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_window(folder, close, audit):
    evidence = {
        name: json.loads((folder / f"{name}.json").read_text())
        for name in ("result", "collector", "observer", "restart")
    }
    result, collector, observer, restart = (evidence[n] for n in evidence)
    protected = {
        p.name: sha(p)
        for p in folder.iterdir()
        if p.is_file() and not p.name.endswith(("-shm", ".writer.lock"))
    }
    assert result["status"] == "LIVE_OBSERVER_PASS"
    assert collector["status"] == observer["status"] == restart["status"] == "COMPLETED"
    assert collector["conflicts"] == collector["pending_closed"] == 0
    assert collector["websocket"]["closed_candles"] == 3
    assert collector["websocket"]["live_status"] == "LIVE_PASS"
    assert observer["formal_w04_started"] is False
    assert observer["execution_performed"] is False
    assert restart["batches"][0]["status"] == "ALREADY_COMMITTED"
    assert result["observer_pid"] != result["restart_pid"]
    db = sqlite3.connect((folder / "observer.sqlite").resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        reader = ObserverStore.__new__(ObserverStore)
        reader.db = db
        reader.recover()  # Only SELECT/PRAGMA integrity operations.
        rows = db.execute(
            "SELECT * FROM signal_decisions WHERE bar_open_ms=?", (close - INTERVAL_MS,)
        ).fetchall()
        assert len(rows) == 9
        decisions = [SignalDecision(**json.loads(r["record"])) for r in rows]
        assert {(d.strategy_id, d.symbol) for d in decisions} == {
            (s, a) for s in STRATEGIES for a in SYMBOLS
        }
        assert {d.observation_mode for d in decisions} == {"LIVE_OBSERVATION"}
        assert all(d.evaluated_bar_close_ms == close - 1 for d in decisions)
        assert all(d.evaluation_time_ms >= close for d in decisions)
        assert all(d.data_provenance["source"] == "WS_LIVE" for d in decisions)
        batch_ids = {r["batch_id"] for r in rows}
        assert len(batch_ids) == 1
        batch = db.execute(
            "SELECT * FROM evaluation_batches WHERE batch_id=?", (next(iter(batch_ids)),)
        ).fetchone()
        assert batch["status"] == "COMMITTED"
        assert batch["batch_hash"] == digest(sorted(d.decision_hash for d in decisions))
        assert all(
            d.decision_hash == r["decision_hash"] for d, r in zip(decisions, rows, strict=True)
        )
        checkpoints = db.execute("SELECT * FROM processing_checkpoints").fetchall()
        assert len(checkpoints) == 9
        assert all(r["last_committed_bar_open_ms"] == close - INTERVAL_MS for r in checkpoints)
        assert db.execute("SELECT count(*) FROM signal_decisions").fetchone()[0] == 18
        assert not db.execute(
            "SELECT * FROM signal_decisions WHERE mode='FORMAL_W04_ELIGIBLE'"
        ).fetchone()
        manifests = [dict(r) for r in db.execute("SELECT * FROM strategy_manifests")]
        assert all(
            r["source_hash"] == audit["source_hash"]
            and r["parameter_hash"] == audit["parameter_hash"]
            for r in manifests
        )
        health = [dict(r) for r in db.execute("SELECT * FROM observer_health")]
        runs = [dict(r) for r in db.execute("SELECT * FROM observer_runs ORDER BY started_at")]
    finally:
        db.close()
    with MarketRepository(folder / "market.sqlite") as repository:
        quality = repository.verify(result["completed_at_ms"])
        assert quality["data_status"] == "COMPLETE"
        assert not repository.connection.execute("SELECT * FROM candle_conflicts").fetchone()
        candles = [
            repository.candles(s, close - INTERVAL_MS, close - INTERVAL_MS)[0] for s in SYMBOLS
        ]
        for candle in candles:
            candle.validate()
            assert candle.source == "WS_LIVE" and candle.event_time_ms >= close
            assert candle.close_time_ms == close - 1
        at = decisions[0].evaluation_time_ms
        frames, provenance, hashes = WarmupLoader(audit["data_hashes"]).load(
            repository, close - INTERVAL_MS, at
        )
        adapter = StrategyAdapter(audit)
        for decision in decisions:
            context = {
                "target_ms": close - INTERVAL_MS,
                "evaluated_at": decision.evaluation_time_ms,
                "input_hash": hashes[decision.symbol],
                "provenance": provenance[decision.symbol],
                "mode": decision.observation_mode,
            }
            replay = adapter.evaluate(
                decision.strategy_id, decision.symbol, frames[decision.symbol], context
            )
            assert replay.decision_hash == decision.decision_hash
            assert replay.indicator_snapshot == decision.indicator_snapshot
        sources = repository.summary()["candle_sources"]
        ingestion_runs = list(repository.runs())
    assert protected == {name: sha(folder / name) for name in protected}
    return {
        "status": "INDEPENDENT_LIVE_AUDIT_PASS",
        "close_utc": utc_datetime(close).isoformat(),
        "completed_utc": utc_datetime(result["completed_at_ms"]).isoformat(),
        "decisions": [asdict(d) for d in decisions],
        "decision_count": 9,
        "no_action_count": sum(d.decision == "NO_ACTION" for d in decisions),
        "batch_hash": batch["batch_hash"],
        "checkpoint_count": len(checkpoints),
        "total_decision_count_including_prelaunch": 18,
        "restart_added_decisions": 0,
        "observer_pid": result["observer_pid"],
        "restart_pid": result["restart_pid"],
        "frozen_live_replay_exact": True,
        "input_data_hashes_exact": True,
        "original_files_unchanged": True,
        "protected_file_hashes": protected,
        "market_quality_as_of_completion": quality,
        "candle_sources": sources,
        "observer_runs": runs,
        "observer_health": health,
        "market_ingestion_runs": ingestion_runs,
        "collector_counters": collector["counters"],
        "ws_uptime_seconds": collector["websocket"]["uptime_seconds"],
        "actual_ws_closed_candles": collector["websocket"]["closed_candles"],
        "network_duplicate_closures": collector["websocket"]["duplicate_closures"],
        "formal_w04_started": False,
        "execution_performed": False,
    }


def main():
    audit = reproduction_gate()
    windows = [
        audit_window(Path(f"data/m04-live-20261010T{tag}"), close, audit)
        for tag, close in (("010000", 1791561600000), ("050000", 1791576000000))
    ]
    report = {
        "classification": "DEV-M04_PASS_WITH_FLAGS",
        "source_audit": audit,
        "windows": windows,
        "coverage": "TWO_SEPARATE_LIVE_WINDOWS_NOT_CONTINUOUS",
        "flags": [
            "NO_INDEPENDENT_FULL_BAR_W03_INDICATOR_DUMP",
            "NETWORK_DUPLICATE_CLOSE_DELIVERY_NOT_OBSERVED",
        ],
        "formal_w04_started": False,
        "execution_performed": False,
    }
    Path("docs/DEV-M04-overnight-audit.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "classification": report["classification"],
                "windows": [
                    {
                        k: w[k]
                        for k in (
                            "status",
                            "close_utc",
                            "decision_count",
                            "no_action_count",
                            "restart_added_decisions",
                        )
                    }
                    for w in windows
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
