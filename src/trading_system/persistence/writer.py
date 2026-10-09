"""One worker thread / one DB connection / one outstanding operation."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from trading_system.persistence.records import CandleRecord
from trading_system.persistence.store import MarketStore


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
            candles = tuple(CandleRecord.from_ws(event, actual_at) for event in pending)
            return store.write_batch(
                candles=candles,
                prices=prices,
                snapshot_at_ms=actual_at,
                snapshot_seconds=snapshot_seconds,
            )

        stats = await self.call(write)
        # No dequeue on rollback, disk error, or cancellation. A persisted conflict is explicit.
        market.ack_closed(pending)
        return stats
