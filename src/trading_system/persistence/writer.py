"""One worker thread / one DB connection / one outstanding operation."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from trading_system.persistence.records import CandleRecord, epoch_ms
from trading_system.persistence.store import MarketStore

logger = logging.getLogger("trading_system.writer")


class AsyncWriter:
    def __init__(self, path):
        self.path = path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="market-data-writer")
        self.gate = asyncio.Semaphore(1)
        self.store = None

    async def _execute(self, function, *args):
        async with self.gate:
            future = asyncio.get_running_loop().run_in_executor(self.executor, function, *args)
            try:
                return await asyncio.shield(future)
            except asyncio.CancelledError:
                # A submitted SQLite commit must finish before connection shutdown.
                await future
                raise

    async def __aenter__(self):
        try:
            self.store = await self._execute(MarketStore, self.path)
        except BaseException:
            self.executor.shutdown(wait=True)
            raise
        return self

    async def __aexit__(self, *_):
        try:
            await self._execute(self.store.close)
        finally:
            self.executor.shutdown(wait=True)

    async def call(self, operation, *args):
        return await self._execute(lambda: operation(self.store, *args))

    async def flush(self, market, prices, *, snapshot_at_ms, snapshot_seconds=60, write_clock=None):
        pending = market.peek_closed(64)
        if not pending and not prices:
            return {}

        def write(store):
            actual_at = write_clock() if write_clock else snapshot_at_ms
            # A slightly slow local clock must not turn a genuine close into a failure.
            ready = []
            for event in pending:
                until_close = epoch_ms(event.close_time) - actual_at
                if 0 <= until_close <= 1000:
                    break
                ready.append(event)
            candles = tuple(CandleRecord.from_ws(event, actual_at) for event in ready)
            stats = store.write_batch(
                candles=candles,
                prices=prices,
                snapshot_at_ms=actual_at,
                snapshot_seconds=snapshot_seconds,
            )
            bucket = actual_at // (snapshot_seconds * 1000)
            receipts = {}
            for event in prices:
                event_ms = epoch_ms(event.event_time)
                row = store.connection.execute(
                    "SELECT event_time_ms FROM price_snapshots "
                    "WHERE symbol=? AND bucket_start_ms=?",
                    (event.symbol, bucket * snapshot_seconds * 1000),
                ).fetchone()
                accepted = row is not None and row[0] >= event_ms
                if accepted:
                    receipts[event.symbol] = bucket
                outcome = (
                    "committed"
                    if accepted
                    else "future_event"
                    if event_ms > actual_at
                    else "not_stored"
                )
                logger.info(
                    "price snapshot symbol=%s bucket=%d write_at_ms=%d event_time_ms=%d "
                    "received_at_ms=%d outcome=%s",
                    event.symbol,
                    bucket,
                    actual_at,
                    event_ms,
                    epoch_ms(event.received_at),
                    outcome,
                )
            stats["price_snapshot_buckets"] = receipts
            return stats, tuple(ready)

        stats, ready = await self.call(write)
        # No dequeue on rollback, disk error, or cancellation. A persisted conflict is explicit.
        market.ack_closed(ready)
        return stats
