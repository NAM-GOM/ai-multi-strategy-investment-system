"""Reuse M03's one writer, bounded WS queue, ACK-after-commit and REST recovery."""

import sys

from trading_system.market_data.health import ConnectionState
from trading_system.observer.model import FREEZE_MS
from trading_system.persistence.collector import Collector
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.records import DAY_MS, now_ms
from trading_system.testnet.client import TestnetError

# M03 and its monitor require a finite positive duration. Largest finite float
# removes any operational deadline without modifying their protected sources.
# Never loop/relaunch daily sessions. SIGTERM's stop event remains authoritative.
CONTINUOUS_HORIZON = sys.float_info.max


def continuous_config(path, timestamp=None):
    timestamp = now_ms() if timestamp is None else timestamp
    # A preserved continuous DB already includes Frozen-to-present history. Only
    # a first bootstrap needs the full horizon; normal restarts use M03 recovery.
    days = 7 if path.exists() else max(7, (timestamp - FREEZE_MS) // DAY_MS + 2)
    if days > 365:
        raise TestnetError("FROZEN_CONTINUITY_BOOTSTRAP_RANGE_HOLD")
    return PersistenceConfig(db_path=path, bootstrap_days=days, snapshot_seconds=10)


class RuntimeCollector(Collector):
    def __init__(self, config, sink, **kwargs):
        super().__init__(config, **kwargs)
        self.sink = sink
        self.recovered_generation = -1

    async def _recover(self, writer):
        if (
            self.recovery_status != "COMPLETE"
            or self.recovered_generation != self.monitor.health.generation
        ):
            self.sink.publish("HOLD", "RECOVERY_IN_PROGRESS", force=True)
        await super()._recover(writer)
        self.recovered_generation = self.monitor.health.generation

    async def _flush(self, writer, final=False):
        await super()._flush(writer, final=final)
        ready = (
            not final
            and self.monitor.health.state == ConnectionState.CONNECTED
            and self.recovery_status == "COMPLETE"
            and self.recovered_generation == self.monitor.health.generation
            and not self.conflicts
            and not self.monitor.market.data_loss
        )
        self.sink.publish(
            "READY" if ready else "HOLD",
            None if ready else "MARKET_NOT_READY",
            recovery=self.recovery_status,
            messages=self.monitor.messages_received,
            pending_closed=len(self.monitor.market.closed_events),
            conflicts=self.conflicts,
            connection=str(self.monitor.health.state),
        )

    async def serve(self, stop, *, smoke_seconds=None):
        # Caller tracks requested stop independently: M03 sets stop on every exit.
        return await self.run(
            CONTINUOUS_HORIZON if smoke_seconds is None else smoke_seconds, stop=stop
        )
