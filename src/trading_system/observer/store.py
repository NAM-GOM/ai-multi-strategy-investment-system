"""Immutable nine-decision batches and checkpoints commit atomically."""

import json
import sqlite3
import uuid
from dataclasses import asdict
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.observer.model import (
    STRATEGIES,
    ObserverError,
    ObserverState,
    SignalDecision,
    canonical,
    digest,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_manifests (
 strategy_id TEXT, version TEXT, source_hash TEXT, parameter_hash TEXT,
 baseline_hash TEXT, verification_status TEXT, manifest_hash TEXT,
 PRIMARY KEY(strategy_id,version));
CREATE TABLE IF NOT EXISTS observer_runs (
 run_id TEXT PRIMARY KEY, started_at INTEGER, ended_at INTEGER, status TEXT,
 market_data_commit TEXT, strategy_manifest_hash TEXT, evaluated_bars INTEGER DEFAULT 0,
 errors TEXT, live_floor_ms INTEGER);
CREATE TABLE IF NOT EXISTS evaluation_batches (
 batch_id TEXT PRIMARY KEY, bar_open_ms INTEGER, status TEXT, batch_hash TEXT,
 run_id TEXT REFERENCES observer_runs, evaluated_at INTEGER, error_category TEXT);
CREATE TABLE IF NOT EXISTS signal_decisions (
 strategy_id TEXT, version TEXT, symbol TEXT, bar_open_ms INTEGER, decision TEXT,
 signal_reason TEXT, indicators TEXT, evaluated_at INTEGER, source TEXT,
 input_hash TEXT, mode TEXT, decision_hash TEXT, record TEXT,
 batch_id TEXT REFERENCES evaluation_batches,
 PRIMARY KEY(strategy_id,version,symbol,bar_open_ms));
CREATE TABLE IF NOT EXISTS processing_checkpoints (
 strategy_id TEXT, version TEXT, symbol TEXT, last_committed_bar_open_ms INTEGER,
 last_decision_hash TEXT, PRIMARY KEY(strategy_id,version,symbol));
CREATE TABLE IF NOT EXISTS observer_health (
 run_id TEXT REFERENCES observer_runs, timestamp INTEGER, data_state TEXT,
 observer_state TEXT, error_category TEXT);
"""


class ObserverStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        for table in (
            "strategy_manifests",
            "evaluation_batches",
            "signal_decisions",
            "observer_health",
        ):
            for action in ("UPDATE", "DELETE"):
                self.db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} "
                    f"BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable'); END"
                )
        self.db.commit()
        self.recover()

    def close(self):
        self.db.close()

    def recover(self):
        if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ObserverError("OBSERVER_DB_INTEGRITY", ObserverState.PERSISTENCE_STOP)
        if self.db.execute("PRAGMA foreign_key_check").fetchone():
            raise ObserverError("STATE_RECOVERY_FAILED", ObserverState.PERSISTENCE_STOP)
        for row in self.db.execute("SELECT * FROM processing_checkpoints"):
            saved = self.db.execute(
                "SELECT decision_hash FROM signal_decisions WHERE strategy_id=? AND version=? "
                "AND symbol=? AND bar_open_ms=?",
                (
                    row["strategy_id"],
                    row["version"],
                    row["symbol"],
                    row["last_committed_bar_open_ms"],
                ),
            ).fetchone()
            if not saved or saved[0] != row["last_decision_hash"]:
                raise ObserverError("STATE_RECOVERY_FAILED", ObserverState.PERSISTENCE_STOP)
            latest = self.db.execute(
                "SELECT max(bar_open_ms) FROM signal_decisions WHERE strategy_id=? "
                "AND version=? AND symbol=?",
                (row["strategy_id"], row["version"], row["symbol"]),
            ).fetchone()[0]
            if latest != row["last_committed_bar_open_ms"]:
                raise ObserverError("STATE_RECOVERY_FAILED", ObserverState.PERSISTENCE_STOP)
        keys = self.db.execute(
            "SELECT DISTINCT strategy_id,version,symbol FROM signal_decisions"
        ).fetchall()
        if (
            len(keys)
            != self.db.execute("SELECT count(*) FROM processing_checkpoints").fetchone()[0]
        ):
            raise ObserverError("STATE_RECOVERY_FAILED", ObserverState.PERSISTENCE_STOP)
        for row in self.db.execute("SELECT record,decision_hash FROM signal_decisions"):
            try:
                decision = SignalDecision(**json.loads(row[0]))
                if decision.decision_hash != row[1]:
                    raise ValueError("decision hash")
            except ValueError, TypeError, KeyError:
                raise ObserverError(
                    "STATE_RECOVERY_FAILED", ObserverState.PERSISTENCE_STOP
                ) from None
        for batch in self.db.execute(
            "SELECT batch_id FROM evaluation_batches WHERE status='COMMITTED'"
        ):
            count = self.db.execute(
                "SELECT count(*) FROM signal_decisions WHERE batch_id=?", batch
            ).fetchone()[0]
            if count != 9:
                raise ObserverError("INCOMPLETE_COMMITTED_BATCH", ObserverState.PERSISTENCE_STOP)

    def start(self, audit, timestamp):
        self.recover()
        stopped = self.db.execute(
            "SELECT observer_state FROM observer_health WHERE observer_state IN "
            "('RULE_MISMATCH_STOP','PERSISTENCE_STOP') LIMIT 1"
        ).fetchone()
        if stopped:
            raise ObserverError(
                "PERSISTENT_STOP_REQUIRES_NEW_AUDITED_DB", ObserverState(stopped[0])
            )
        with self.db:
            self.db.execute(
                "UPDATE observer_runs SET ended_at=?,status='STOPPED',errors='CRASH_INTERRUPTED' "
                "WHERE ended_at IS NULL",
                (timestamp,),
            )
            for strategy_id in STRATEGIES:
                values = (
                    strategy_id,
                    "0.1",
                    audit["source_hash"],
                    audit["parameter_hash"],
                    audit["baseline_hash"],
                    audit["verification_status"],
                    audit["manifest_hash"],
                )
                row = self.db.execute(
                    "SELECT * FROM strategy_manifests WHERE strategy_id=? AND version=?", values[:2]
                ).fetchone()
                if row and tuple(row) != values:
                    raise ObserverError("MANIFEST_CHANGED", ObserverState.RULE_MISMATCH_STOP)
                self.db.execute(
                    "INSERT OR IGNORE INTO strategy_manifests VALUES(?,?,?,?,?,?,?)", values
                )
            run_id = str(uuid.uuid4())
            self.db.execute(
                "INSERT INTO observer_runs VALUES(?,?,NULL,?,?,?,0,NULL,?)",
                (
                    run_id,
                    timestamp,
                    "INITIALIZING",
                    audit["market_data_commit"],
                    audit["manifest_hash"],
                    timestamp,
                ),
            )
        return run_id

    def health(self, run_id, timestamp, state, category=None):
        with self.db:
            self.db.execute(
                "INSERT INTO observer_health VALUES(?,?,?,?,?)",
                (
                    run_id,
                    timestamp,
                    "DATA_BLOCKED" if category else "VALIDATED",
                    str(state),
                    category,
                ),
            )
            self.db.execute(
                "UPDATE observer_runs SET status=?,errors=? WHERE run_id=?",
                (str(state), category, run_id),
            )

    def commit_batch(self, decisions, run_id, timestamp):
        identities = {(d.strategy_id, d.symbol) for d in decisions}
        expected = {(s, a) for s in STRATEGIES for a in SYMBOLS}
        if (
            len(decisions) != 9
            or identities != expected
            or len({d.evaluated_bar_open_ms for d in decisions}) != 1
        ):
            raise ObserverError("INCOMPLETE_SHARED_BATCH")
        bar = decisions[0].evaluated_bar_open_ms
        batch_id = digest(
            {
                "bar": bar,
                "manifest": decisions[0].strategy_code_hash,
                "parameters": decisions[0].parameter_hash,
            }
        )
        batch_hash = digest(sorted(d.decision_hash for d in decisions))
        try:
            with self.db:
                existing = self.db.execute(
                    "SELECT batch_hash FROM evaluation_batches WHERE batch_id=?", (batch_id,)
                ).fetchone()
                if existing:
                    if existing[0] != batch_hash:
                        raise ObserverError(
                            "DUPLICATE_DECISION_CONFLICT", ObserverState.RULE_MISMATCH_STOP
                        )
                    self.recover()
                    return False
                self.db.execute(
                    "INSERT INTO evaluation_batches VALUES(?,?,?,?,?,?,NULL)",
                    (batch_id, bar, "COMMITTED", batch_hash, run_id, timestamp),
                )
                for d in decisions:
                    checkpoint = self.db.execute(
                        "SELECT last_committed_bar_open_ms FROM processing_checkpoints "
                        "WHERE strategy_id=? AND version=? AND symbol=?",
                        (d.strategy_id, d.strategy_version, d.symbol),
                    ).fetchone()
                    if checkpoint and checkpoint[0] >= bar:
                        raise ObserverError(
                            "CHECKPOINT_REGRESSION", ObserverState.RULE_MISMATCH_STOP
                        )
                    self.db.execute(
                        "INSERT INTO signal_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            d.strategy_id,
                            d.strategy_version,
                            d.symbol,
                            bar,
                            d.decision,
                            d.signal_reason,
                            canonical(d.indicator_snapshot),
                            timestamp,
                            d.data_provenance["source"],
                            d.input_data_hash,
                            d.observation_mode,
                            d.decision_hash,
                            canonical(asdict(d)),
                            batch_id,
                        ),
                    )
                    self.db.execute(
                        "INSERT INTO processing_checkpoints VALUES(?,?,?,?,?) "
                        "ON CONFLICT(strategy_id,version,symbol) DO UPDATE SET "
                        "last_committed_bar_open_ms=excluded.last_committed_bar_open_ms,"
                        "last_decision_hash=excluded.last_decision_hash",
                        (d.strategy_id, d.strategy_version, d.symbol, bar, d.decision_hash),
                    )
                self.db.execute(
                    "UPDATE observer_runs SET evaluated_bars=evaluated_bars+1 WHERE run_id=?",
                    (run_id,),
                )
            return True
        except sqlite3.Error:
            raise ObserverError(
                "SIGNAL_DB_TRANSACTION_FAILURE", ObserverState.PERSISTENCE_STOP
            ) from None

    def blocked_batch(self, bar, run_id, timestamp, category):
        # Failed attempts are append-only, do not move a processing checkpoint.
        with self.db:
            self.db.execute(
                "INSERT INTO evaluation_batches VALUES(?,?,?,NULL,?,?,?)",
                (str(uuid.uuid4()), bar, "DATA_BLOCKED", run_id, timestamp, category),
            )

    def finish(self, run_id, timestamp):
        with self.db:
            self.db.execute(
                "UPDATE observer_runs SET ended_at=? WHERE run_id=?", (timestamp, run_id)
            )

    def status(self):
        return {
            "runs": [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM observer_runs ORDER BY started_at DESC LIMIT 5"
                )
            ],
            "health": [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM observer_health ORDER BY timestamp DESC LIMIT 5"
                )
            ],
            "decisions": [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT record FROM signal_decisions "
                    "ORDER BY bar_open_ms DESC,strategy_id,symbol LIMIT 9"
                )
            ],
            "decision_count": self.db.execute("SELECT count(*) FROM signal_decisions").fetchone()[
                0
            ],
            "checkpoints": [
                dict(r) for r in self.db.execute("SELECT * FROM processing_checkpoints")
            ],
            "formal_w04_started": False,
        }
