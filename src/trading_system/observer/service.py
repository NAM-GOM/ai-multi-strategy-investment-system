"""Shared closed-bar observation. No W04 clock or execution imports."""

import sqlite3
from pathlib import Path

from trading_system.config import SYMBOLS
from trading_system.observer.adapter import StrategyAdapter
from trading_system.observer.audit import source_audit
from trading_system.observer.gate import WarmupLoader
from trading_system.observer.model import STRATEGIES, ObserverError, ObserverState, classify
from trading_system.persistence.repository import MarketRepository
from trading_system.persistence.store import PersistenceError


class BatchProcessor:
    def __init__(self, market_path, store, audit, run_id, live_floor_ms):
        if store.path == Path(market_path).resolve():
            raise ObserverError("OBSERVER_MARKET_PATH_COLLISION", ObserverState.PERSISTENCE_STOP)
        self.market_path, self.store, self.audit = market_path, store, audit
        self.run_id, self.live_floor_ms = run_id, live_floor_ms
        self.loader, self.adapter = WarmupLoader(audit["data_hashes"]), StrategyAdapter(audit)
        self.state = ObserverState.INITIALIZING

    def evaluate(self, target_ms, evaluated_at):
        try:
            current = source_audit()
            if current["manifest_hash"] != self.audit["manifest_hash"]:
                raise ObserverError("MANIFEST_CHANGED", ObserverState.RULE_MISMATCH_STOP)
            if self.state in (ObserverState.RULE_MISMATCH_STOP, ObserverState.PERSISTENCE_STOP):
                raise ObserverError("PERSISTENT_STOP", self.state)
            with MarketRepository(self.market_path) as repository:
                repository.connection.execute("BEGIN")
                frames, provenance, hashes = self.loader.load(repository, target_ms, evaluated_at)
                repository.connection.rollback()
            self.state = ObserverState.WARMING_UP
            decisions = []
            for strategy_id in STRATEGIES:
                for symbol in SYMBOLS:
                    mode = classify(target_ms, provenance[symbol], self.live_floor_ms, evaluated_at)
                    previous = self.store.db.execute(
                        "SELECT mode FROM signal_decisions WHERE strategy_id=? AND version='0.1' "
                        "AND symbol=? AND bar_open_ms=?",
                        (strategy_id, symbol, target_ms),
                    ).fetchone()
                    # An existing immutable classification belongs to its original observation.
                    if previous:
                        mode = previous[0]
                    decisions.append(
                        self.adapter.evaluate(
                            strategy_id,
                            symbol,
                            frames[symbol],
                            {
                                "input_hash": hashes[symbol],
                                "provenance": provenance[symbol],
                                "target_ms": target_ms,
                                "evaluated_at": evaluated_at,
                                "mode": mode,
                            },
                        )
                    )
            self.state = ObserverState.READY
            committed = self.store.commit_batch(decisions, self.run_id, evaluated_at)
            self.state = ObserverState.OBSERVING
            self.store.health(self.run_id, evaluated_at, self.state)
            return {
                "status": "COMMITTED" if committed else "ALREADY_COMMITTED",
                "bar_open_ms": target_ms,
                "decisions": len(decisions),
                "modes": sorted({d.observation_mode for d in decisions}),
            }
        except ObserverError as error:
            self.state = error.state
            self.store.blocked_batch(target_ms, self.run_id, evaluated_at, error.category)
            self.store.health(self.run_id, evaluated_at, self.state, error.category)
            raise
        except sqlite3.Error, OSError, PersistenceError:
            self.state = ObserverState.PERSISTENCE_STOP
            raise ObserverError("PERSISTENCE_FAILURE", self.state) from None

    def latest_expected_bar(self, evaluated_at):
        from trading_system.persistence.records import INTERVAL_MS

        return evaluated_at // INTERVAL_MS * INTERVAL_MS - INTERVAL_MS
