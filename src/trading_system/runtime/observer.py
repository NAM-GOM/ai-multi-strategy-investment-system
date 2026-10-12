"""Sequential checkpoint recovery over the unchanged Frozen M04 BatchProcessor."""

import sqlite3

from trading_system.observer.audit import reproduction_gate
from trading_system.observer.model import FREEZE_MS, ObserverError, ObserverState
from trading_system.observer.service import BatchProcessor
from trading_system.observer.store import ObserverStore
from trading_system.persistence.records import INTERVAL_MS, now_ms
from trading_system.persistence.store import WriterLease
from trading_system.testnet.client import TestnetError

from .common import require_health


class RuntimeObserver:
    def __init__(self, paths, sink, *, clock=now_ms, audit=None):
        self.paths, self.sink, self.clock = paths, sink, clock
        self.lease = self.store = self.processor = None
        self.run_id = None
        self.last_health = 0
        try:
            paths.observer.parent.mkdir(parents=True, exist_ok=True)
            self.lease = WriterLease(paths.observer)
            self.store = ObserverStore(paths.observer)
            self.store.db.execute("PRAGMA journal_mode=WAL")
            self.store.db.execute("PRAGMA synchronous=FULL")
            self.store.db.execute("PRAGMA busy_timeout=5000")
            self.store.db.execute("PRAGMA wal_autocheckpoint=1000")
            audit = audit or reproduction_gate()
            self.run_id = self.store.start(audit, clock())
            self.processor = BatchProcessor(paths.market, self.store, audit, self.run_id, clock())
            points = list(self.store.db.execute("SELECT * FROM processing_checkpoints"))
            if points and (
                len(points) != 9 or len({p["last_committed_bar_open_ms"] for p in points}) != 1
            ):
                raise ObserverError("CHECKPOINT_BATCH_MISMATCH", ObserverState.PERSISTENCE_STOP)
            self.target = (
                points[0]["last_committed_bar_open_ms"] + INTERVAL_MS if points else FREEZE_MS
            )
        except BaseException:
            self.close()
            raise

    def health(self, state, now, category=None, *, force=False):
        if force or now - self.last_health >= 10_000:
            self.store.health(self.run_id, now, state, category)
            self.last_health = now
        self.sink.publish("READY" if state == ObserverState.OBSERVING else "HOLD", category)

    def hold(self, category, now):
        self.processor.live_floor_ms = max(self.processor.live_floor_ms, now)
        with self.store.db:
            self.store.db.execute(
                "UPDATE observer_runs SET live_floor_ms=? WHERE run_id=?",
                (self.processor.live_floor_ms, self.run_id),
            )
        self.health(ObserverState.DATA_HOLD, now, category, force=True)

    def tick(self):
        now = self.clock()
        try:
            require_health(self.paths, "collector", now)
        except TestnetError as error:
            self.hold(error.kind, now)
            return {"state": "DATA_HOLD", "category": error.kind}
        latest = self.processor.latest_expected_bar(now)
        if self.target > latest:
            self.health(ObserverState.OBSERVING, now)
            return {"state": "WAITING_NEXT_4H_BAR"}
        if now % INTERVAL_MS < 1000:
            return {"state": "WAITING_CLOSE_COMMIT"}
        try:
            result = self.processor.evaluate(self.target, now)
        except ObserverError as error:
            if error.state != ObserverState.DATA_HOLD:
                raise
            self.hold(error.category, now)
            return {"state": "DATA_HOLD", "category": error.category}
        self.target += INTERVAL_MS
        self.last_health = now
        # Catch-up decisions are persisted, but Bridge health is withheld until
        # every pending bar is committed and no gap remains.
        if self.target <= latest:
            self.health(ObserverState.DATA_HOLD, now, "CATCHING_UP", force=True)
        else:
            self.health(ObserverState.OBSERVING, now, force=True)
        self.sink.publish(
            "READY" if self.target > latest else "HOLD",
            None if self.target > latest else "CATCHING_UP",
            force=True,
            batch=result,
            run_id=self.run_id,
        )
        return result

    def close(self):
        try:
            if self.store:
                try:
                    if self.run_id:
                        self.store.health(self.run_id, self.clock(), ObserverState.STOPPED)
                        self.store.finish(self.run_id, self.clock())
                        self.store.db.execute("PRAGMA wal_checkpoint(PASSIVE)")
                finally:
                    self.store.close()
        except sqlite3.Error:
            raise TestnetError("OBSERVER_SHUTDOWN_DB_FAILED") from None
        finally:
            if self.lease:
                self.lease.close()
