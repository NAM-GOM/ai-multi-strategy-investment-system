"""Read immutable M04 decisions; validate provenance, hashes and next-bar timing."""

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from trading_system.observer.adapter import StrategyAdapter
from trading_system.observer.audit import source_audit
from trading_system.observer.gate import WarmupLoader
from trading_system.observer.model import (
    STRATEGIES,
    ObserverError,
    SignalDecision,
    classify,
    digest,
)
from trading_system.persistence.records import INTERVAL_MS
from trading_system.persistence.repository import MarketRepository
from trading_system.persistence.store import PersistenceError
from trading_system.testnet.client import TestnetError
from trading_system.testnet.risk import dec

from .config import EXPERIMENT, T1, SafetyConfig
from .risk_engine import RiskEngine


@contextmanager
def observer_reader(path):
    target = Path(path).resolve()
    if not target.is_file():
        raise TestnetError("OBSERVER_NOT_INITIALIZED")
    connection = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TestnetError("OBSERVER_DB_INTEGRITY")
        yield connection
    except sqlite3.Error:
        raise TestnetError("OBSERVER_DB_UNAVAILABLE") from None
    finally:
        connection.close()


class SignalRouter:
    def __init__(self, manager, observer_path, market_path, *, safety=None):
        self.manager, self.store, self.sid = manager, manager.store, manager.sid
        self.observer_path, self.market_path = (
            str(Path(observer_path).resolve()),
            str(Path(market_path).resolve()),
        )
        self.safety = safety or SafetyConfig()
        self.risk = RiskEngine(self.safety)
        execution_path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        paths = [Path(p).resolve() for p in (execution_path, observer_path, market_path)]
        if len(set(paths)) != 3 or any(
            a.exists() and b.exists() and a.samefile(b)
            for i, a in enumerate(paths)
            for b in paths[i + 1 :]
        ):
            raise TestnetError("DATABASE_PATH_COLLISION")

    def checkpoint(self):
        rows = self.store.rows("SELECT * FROM router_checkpoints WHERE session_id=?", (self.sid,))
        if not rows:
            raise TestnetError("ROUTER_NOT_INITIALIZED")
        point = rows[0]
        if point["observer_path"] != self.observer_path or point["market_path"] != self.market_path:
            raise TestnetError("ROUTER_SOURCE_CHANGED")
        return point

    def initialize(self, now):
        with self.store.transaction():
            existing = self.store.rows(
                "SELECT * FROM router_checkpoints WHERE session_id=?", (self.sid,)
            )
            if existing:
                return self.checkpoint()
            with observer_reader(self.observer_path) as db:
                last = db.execute("SELECT coalesce(max(rowid),0) FROM signal_decisions").fetchone()[
                    0
                ]
            self.store.db.execute(
                "INSERT INTO router_checkpoints VALUES(?,?,?,?,?)",
                (self.sid, self.observer_path, self.market_path, now, last),
            )
            self.store.event(self.sid, now, "ROUTER_INITIALIZED_NO_RETROACTIVE_ORDERS", last)
        return self.checkpoint()

    def health(self, db):
        run = db.execute(
            "SELECT * FROM observer_runs ORDER BY started_at DESC,rowid DESC LIMIT 1"
        ).fetchone()
        if not run or run["ended_at"] is not None or run["status"] != "OBSERVING":
            raise TestnetError("M04_NOT_OBSERVING")
        stopped = db.execute(
            "SELECT 1 FROM observer_health WHERE observer_state IN "
            "('RULE_MISMATCH_STOP','PERSISTENCE_STOP') LIMIT 1"
        ).fetchone()
        health = db.execute(
            "SELECT * FROM observer_health WHERE run_id=? "
            "ORDER BY timestamp DESC,rowid DESC LIMIT 1",
            (run["run_id"],),
        ).fetchone()
        if (
            stopped
            or not health
            or health["observer_state"] != "OBSERVING"
            or health["data_state"] != "VALIDATED"
        ):
            raise TestnetError("M04_DATA_HOLD_OR_STOP")
        return run

    def validate_row(self, db, row, now):
        try:
            d = SignalDecision(**json.loads(row["record"]))
            columns = {
                "strategy_id": d.strategy_id,
                "version": d.strategy_version,
                "symbol": d.symbol,
                "bar_open_ms": d.evaluated_bar_open_ms,
                "decision": d.decision,
                "signal_reason": d.signal_reason,
                "evaluated_at": d.evaluation_time_ms,
                "source": d.data_provenance["source"],
                "input_hash": d.input_data_hash,
                "mode": d.observation_mode,
                "decision_hash": d.decision_hash,
            }
            if (
                any(row[k] != v for k, v in columns.items())
                or json.loads(row["indicators"]) != d.indicator_snapshot
            ):
                raise TestnetError("SIGNAL_HASH_MISMATCH")
            if d.strategy_id not in STRATEGIES or d.strategy_version != "0.1":
                raise TestnetError("STRATEGY_NOT_FROZEN")
            if (
                d.timeframe != "4h"
                or d.evaluated_bar_open_ms % INTERVAL_MS
                or d.evaluated_bar_close_ms != d.evaluated_bar_open_ms + INTERVAL_MS - 1
            ):
                raise TestnetError("UNCONFIRMED_4H_BAR")
            next_bar = d.evaluated_bar_open_ms + INTERVAL_MS
            if (
                not next_bar <= d.evaluation_time_ms <= now
                or not 0 <= now - next_bar <= self.safety.max_signal_age_ms
            ):
                raise TestnetError("STALE_OR_UNCONFIRMED_SIGNAL")
            if next_bar < self.checkpoint()["activated_ms"]:
                raise TestnetError("PREACTIVATION_SIGNAL")
            if d.observation_mode != "LIVE_OBSERVATION" or d.data_provenance["source"] != "WS_LIVE":
                raise TestnetError("NON_LIVE_OR_FORMAL_SIGNAL")
            run = self.health(db)
            if (
                classify(
                    d.evaluated_bar_open_ms,
                    d.data_provenance,
                    run["live_floor_ms"],
                    d.evaluation_time_ms,
                )
                != "LIVE_OBSERVATION"
            ):
                raise TestnetError("PRELAUNCH_OR_RECOVERED_SIGNAL")
            batch = db.execute(
                "SELECT * FROM evaluation_batches WHERE batch_id=?", (row["batch_id"],)
            ).fetchone()
            members = db.execute(
                "SELECT * FROM signal_decisions WHERE batch_id=?", (row["batch_id"],)
            ).fetchall()
            if (
                not batch
                or batch["status"] != "COMMITTED"
                or batch["run_id"] != run["run_id"]
                or batch["bar_open_ms"] != d.evaluated_bar_open_ms
                or len(members) != 9
                or {(r["strategy_id"], r["symbol"]) for r in members}
                != {(s, a) for s in STRATEGIES for a in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
                or batch["batch_hash"] != digest(sorted(r["decision_hash"] for r in members))
            ):
                raise TestnetError("INVALID_COMMITTED_BATCH")
            audit = source_audit()
            manifest = db.execute(
                "SELECT * FROM strategy_manifests WHERE strategy_id=? AND version='0.1'",
                (d.strategy_id,),
            ).fetchone()
            if (
                not manifest
                or manifest["manifest_hash"] != audit["manifest_hash"]
                or run["strategy_manifest_hash"] != audit["manifest_hash"]
                or d.strategy_code_hash != audit["source_hash"]
                or d.parameter_hash != audit["parameter_hash"]
            ):
                raise TestnetError("STRATEGY_HASH_MISMATCH")
            with MarketRepository(self.market_path) as repository:
                repository.connection.execute("BEGIN")
                frames, provenance, hashes = WarmupLoader(audit["data_hashes"]).load(
                    repository,
                    d.evaluated_bar_open_ms,
                    d.evaluation_time_ms,
                )
                reference = repository.recent_prices(d.symbol, 1)
            if hashes[d.symbol] != d.input_data_hash or provenance[d.symbol] != d.data_provenance:
                raise TestnetError("INPUT_HASH_MISMATCH")
            regenerated = StrategyAdapter(audit).evaluate(
                d.strategy_id,
                d.symbol,
                frames[d.symbol],
                {
                    "input_hash": hashes[d.symbol],
                    "provenance": provenance[d.symbol],
                    "target_ms": d.evaluated_bar_open_ms,
                    "evaluated_at": d.evaluation_time_ms,
                    "mode": d.observation_mode,
                },
            )
            if asdict(regenerated) != asdict(d):
                raise TestnetError("FROZEN_DECISION_MISMATCH")
            if not reference or reference[-1].source != "binance_spot":
                raise TestnetError("PRODUCTION_REFERENCE_REQUIRED")
            if not 0 <= now - reference[-1].event_time_ms <= self.safety.max_reference_age_ms:
                raise TestnetError("STALE_PRODUCTION_REFERENCE")
            return d, reference[-1]
        except ObserverError, PersistenceError:
            raise TestnetError("M04_INPUT_OR_FROZEN_HOLD") from None
        except KeyError, TypeError, ValueError:
            raise TestnetError("INVALID_SIGNAL_RECORD") from None

    def status(self):
        return {
            "checkpoint": self.checkpoint(),
            "automation": "DISABLED"
            if not self.safety.automated_enabled
            else "EXPLICIT_UNLOCK_REQUIRED",
            "strategy": T1,
            "T2_T3": "SHADOW_SIGNAL_ONLY",
            "classification": EXPERIMENT,
        }

    def route(self, now, quotes, info, balances, *, dry_run=True):
        point = self.initialize(now)
        reports = []
        with observer_reader(self.observer_path) as db:
            self.health(db)
            rows = db.execute(
                "SELECT rowid AS sequence,* FROM signal_decisions WHERE rowid>? ORDER BY rowid",
                (point["last_rowid"],),
            ).fetchall()
            for row in rows:
                key = digest(
                    [row["strategy_id"], row["version"], row["symbol"], row["bar_open_ms"]]
                )
                if self.store.rows("SELECT * FROM signal_receipts WHERE signal_key=?", (key,)):
                    reports.append({"state": "DUPLICATE_SIGNAL", "signal": key})
                    continue
                try:
                    d, reference = self.validate_row(db, row, now)
                    if d.decision == "NO_ACTION":
                        raise TestnetError("NO_ACTION")
                    if d.decision not in ("ENTRY_CANDIDATE", "EXIT_CANDIDATE"):
                        raise TestnetError("UNSUPPORTED_SIGNAL")
                    if d.strategy_id != T1:
                        raise TestnetError("SHADOW_SIGNAL_ONLY")
                    quote = quotes.get(d.symbol)
                    if not quote or quote.symbol != d.symbol:
                        raise TestnetError("TESTNET_QUOTE_REQUIRED")
                    difference = self.risk.prices(
                        quote, reference.price, reference.received_at_ms, now
                    )
                    references = {d.symbol: reference.price}
                    with MarketRepository(self.market_path) as repository:
                        for p in self.manager.positions():
                            if dec(p["quantity"]) > 0:
                                prices = repository.recent_prices(p["symbol"], 1)
                                if (
                                    not prices
                                    or not 0
                                    <= now - prices[-1].received_at_ms
                                    <= self.safety.max_reference_age_ms
                                ):
                                    raise TestnetError("STALE_POSITION_MARK")
                                references[p["symbol"]] = prices[-1].price
                    with self.store.transaction():
                        self.manager.verify()
                        if self.store.session()["kill"] or self.store.session()["hold"]:
                            raise TestnetError("EXECUTION_HOLD_OR_KILL")
                        side, qty, price = self.risk.size(d, self.manager, quote, references)
                        opens = self.store.rows(
                            "SELECT * FROM exchange_orders WHERE session_id=? "
                            "AND status IN ('NEW','PARTIALLY_FILLED')",
                            (self.sid,),
                        )
                        start = now - now % 86_400_000
                        attempts = self.store.rows(
                            "SELECT * FROM order_intents WHERE attempted_ms>=?", (start,)
                        )
                        order = self.risk.validate(
                            d.symbol, side, qty, price, info, balances, opens, attempts
                        )
                        client_id = None if dry_run else "e01_" + key[:32]
                        outcome = "DRY_RUN_APPROVED" if dry_run else "INTENT_CREATED"
                        if client_id:
                            self.store.db.execute(
                                "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)",
                                (
                                    client_id,
                                    self.sid,
                                    now,
                                    d.symbol,
                                    side,
                                    str(order.quantity),
                                    str(order.price),
                                    str(order.notional),
                                    "INTENT_CREATED",
                                ),
                            )
                        self.store.db.execute(
                            "INSERT INTO signal_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                key,
                                d.decision_hash,
                                self.sid,
                                d.strategy_id,
                                d.symbol,
                                d.evaluated_bar_open_ms,
                                outcome,
                                client_id,
                                str(d.indicator_snapshot["atr"]),
                                str(reference.price),
                                str(price),
                                quote.received_ms,
                                EXPERIMENT,
                            ),
                        )
                        if dry_run:
                            self.store.gate(self.sid, "A", now, key)
                        self.store.event(
                            self.sid,
                            now,
                            outcome,
                            {
                                "signal": key,
                                "price_difference": str(difference),
                                "quote_age_ms": now - quote.received_ms,
                            },
                        )
                    reports.append(
                        {
                            "state": outcome,
                            "signal": key,
                            "client_id": client_id,
                            "side": side,
                            "quantity": str(order.quantity),
                            "notional": str(order.notional),
                            "classification": EXPERIMENT,
                        }
                    )
                except TestnetError as error:
                    if error.kind == "DB_FAILED":
                        raise
                    reports.append({"state": error.kind, "signal": key})
                    with self.store.transaction():
                        self.store.db.execute(
                            "INSERT OR IGNORE INTO signal_receipts "
                            "VALUES(?,?,?,?,?,?,?,NULL,'0','0','0',0,?)",
                            (
                                key,
                                row["decision_hash"],
                                self.sid,
                                row["strategy_id"],
                                row["symbol"],
                                row["bar_open_ms"],
                                error.kind,
                                EXPERIMENT,
                            ),
                        )
                with self.store.transaction():
                    self.store.db.execute(
                        "UPDATE router_checkpoints SET last_rowid=? WHERE session_id=?",
                        (row["sequence"], self.sid),
                    )
        return reports
