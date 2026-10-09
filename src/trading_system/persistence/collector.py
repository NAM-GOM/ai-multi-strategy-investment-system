"""Public WebSocket reception continues while the single worker persists or recovers data."""

import asyncio
import logging
import math
import time

from trading_system.binance.client import BinanceClient
from trading_system.binance.public import PublicAPI
from trading_system.binance.websocket import WebSocketMonitor
from trading_system.config import SYMBOLS, Config
from trading_system.market_data.health import ConnectionState
from trading_system.persistence.records import DAY_MS, now_ms
from trading_system.persistence.recovery import Backfill
from trading_system.persistence.store import RUN_COUNTERS, PersistenceError
from trading_system.persistence.writer import AsyncWriter

logger = logging.getLogger("trading_system.collector")


def public_recovery(store, config):
    # Config() does not read .env/process credentials. Only the official public data host is used.
    with BinanceClient(Config()) as client:
        return Backfill(store, PublicAPI(client), config).run()


class Collector:
    def __init__(
        self,
        config,
        *,
        monitor=None,
        recovery=public_recovery,
        writer_factory=AsyncWriter,
        clock_ms=now_ms,
        tick_seconds=1,
    ):
        self.config = config
        self.monitor = monitor or WebSocketMonitor()
        self.recovery = recovery
        self.writer_factory, self.clock_ms = writer_factory, clock_ms
        self.tick_seconds = tick_seconds
        self.counters = dict.fromkeys(RUN_COUNTERS, 0)
        self.conflicts = 0
        self.recovery_status = "INCOMPLETE"
        self.error_category = None
        self.persistence_failed = False
        self.interrupted = False
        self.snapshot_buckets = {}

    def _add(self, stats):
        for key in RUN_COUNTERS:
            self.counters[key] += stats.get(key, 0)
        self.conflicts += stats.get("conflicts", 0)

    async def _recover(self, writer):
        result = await writer.call(self.recovery, self.config)
        self._add(result)
        self.recovery_status = result["data_status"]
        self.error_category = result["error_category"]

    def _prices(self, final=False):
        monitor = self.monitor
        if monitor.health.state not in (ConnectionState.CONNECTED, ConnectionState.STALE) and not (
            final and monitor.final_data_fresh
        ):
            return ()
        return tuple(
            monitor.market.prices[symbol]
            for symbol in SYMBOLS
            if symbol in monitor.market.prices
            and monitor.health.fresh(
                symbol, price=True, now=monitor.monotonic(), utc_now=monitor.utc_now()
            )
        )

    async def _flush(self, writer, final=False):
        # Check state transitions/freshness without removing closed events.
        self.monitor.health.evaluate(self.monitor.monotonic(), self.monitor.utc_now())
        bucket = self.clock_ms() // (self.config.snapshot_seconds * 1000)
        prices = tuple(
            event
            for event in self._prices(final)
            if self.snapshot_buckets.get(event.symbol) != bucket
        )
        stats = await writer.flush(
            self.monitor.market,
            prices,
            snapshot_at_ms=self.clock_ms(),
            snapshot_seconds=self.config.snapshot_seconds,
            write_clock=self.clock_ms,
        )
        self._add(stats)
        if stats.get("price_snapshots_written", 0) == len(prices):
            for event in prices:
                self.snapshot_buckets[event.symbol] = bucket

    async def _flush_final(self, writer):
        # Reception has stopped. Drain the bounded queue in committed batches, including
        # a backlog larger than one batch; a failed batch stays pending and aborts shutdown.
        await self._flush(writer, final=True)
        while self.monitor.market.closed_events:
            await self._flush(writer, final=True)

    def _summary(self, monitor):
        snapshot = monitor.snapshot()
        print(
            f"DEV-M03 Collector Connection={snapshot['connection']} "
            f"messages={snapshot['messages_received']} snapshots_written="
            f"{self.counters['price_snapshots_written']} candles_written="
            f"{self.counters['candles_written']} pending_closed={snapshot['queue_depth']} "
            f"data_status={self.recovery_status} conflicts={self.conflicts}"
        )
        # Deliberately do not call DEV-M02 print_summary() / drain_closed().

    async def run(self, duration, *, stop=None):
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Collection duration must be finite and positive.")
        stop = stop or asyncio.Event()
        async with self.writer_factory(self.config.db_path) as writer:
            run_id = await writer.call(lambda store: store.start_run())
            task = None
            result = None
            try:
                await writer.call(
                    lambda store: store.retain_prices(
                        max(0, self.clock_ms() - self.config.retention_days * DAY_MS)
                    )
                )
                await self._recover(writer)
                # Start WS only after bootstrap. A second recovery closes the bootstrap/WS race.
                task = asyncio.create_task(
                    self.monitor.run(duration, stop=stop, on_summary=self._summary)
                )
                seen_generation = -1
                next_recovery = time.monotonic()
                next_retention = time.monotonic() + 3600
                while not task.done():
                    await self._flush(writer)
                    now = time.monotonic()
                    if self.monitor.connection_opens and (
                        self.monitor.health.generation != seen_generation or now >= next_recovery
                    ):
                        await self._recover(writer)
                        seen_generation = self.monitor.health.generation
                        next_recovery = time.monotonic() + self.config.recovery_interval_seconds
                    if now >= next_retention:
                        await writer.call(
                            lambda store: store.retain_prices(
                                max(0, self.clock_ms() - self.config.retention_days * DAY_MS)
                            )
                        )
                        next_retention = now + 3600
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=self.tick_seconds)
                    except TimeoutError:
                        pass
                    if stop.is_set():
                        await task
                result = await task
                # Final closed events commit before ACK, then cover any last close boundary.
                await self._flush_final(writer)
                await self._recover(writer)
            except asyncio.CancelledError:
                self.interrupted = True
                self.error_category = "interrupted"
                stop.set()
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                # All already submitted writes finish; closed queue remains until a final commit.
                try:
                    await self._flush_final(writer)
                except PersistenceError:
                    self.persistence_failed = True
                    self.error_category = "persistence_failure"
            except PersistenceError:
                self.persistence_failed = True
                self.error_category = "persistence_failure"
                logger.error("PERSISTENCE_FAILURE; unacknowledged events remain pending")
            except Exception:
                self.error_category = "stream_failure"
                logger.error("collection failed category=stream_failure; details omitted")
            finally:
                stop.set()
                if task and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                self.counters["messages_received"] = self.monitor.messages_received
                self.counters["reconnect_count"] = self.monitor.reconnect_count
                status = (
                    "PERSISTENCE_FAILURE"
                    if self.persistence_failed
                    else "INTERRUPTED"
                    if self.interrupted
                    else "BLOCKED_ENVIRONMENT"
                    if result and result["live_status"] == "BLOCKED_ENVIRONMENT"
                    else "COMPLETED"
                    if result
                    and result["final_data_fresh"]
                    and result["normal_shutdown"]
                    and result["all_symbols_observed"]
                    and not self.monitor.fatal_error
                    and self.recovery_status == "COMPLETE"
                    and not self.conflicts
                    and not self.monitor.market.closed_events
                    and self.counters["price_snapshots_written"] > 0
                    else "INCOMPLETE"
                )
                try:
                    await writer.call(
                        lambda store: store.finish_run(
                            run_id, status, self.counters, self.error_category
                        )
                    )
                except PersistenceError:
                    status = "PERSISTENCE_FAILURE"
                    self.error_category = "persistence_failure"
                    logger.error(
                        "PERSISTENCE_FAILURE recording run end; journal/DB may show INTERRUPTED"
                    )
            report = dict(
                run_id=run_id,
                status=status,
                counters=self.counters,
                conflicts=self.conflicts,
                recovery_status=self.recovery_status,
                error_category=self.error_category,
                pending_closed=len(self.monitor.market.closed_events),
                websocket=result or self.monitor.snapshot(),
            )
            logger.info(
                "ingestion exit status=%s snapshots=%d candles=%d pending_closed=%d",
                status,
                self.counters["price_snapshots_written"],
                self.counters["candles_written"],
                report["pending_closed"],
            )
            return report
