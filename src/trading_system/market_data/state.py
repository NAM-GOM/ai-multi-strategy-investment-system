"""Latest prices coalesce; closed candles use a bounded, fail-closed delivery queue."""

import logging
from collections import deque
from datetime import timedelta

from trading_system.config import SYMBOLS
from trading_system.market_data.models import CandleEvent, PriceEvent

logger = logging.getLogger("trading_system.market_data")


class DataLossError(RuntimeError):
    pass


class MarketState:
    def __init__(self, closed_queue_size: int = 128) -> None:
        if type(closed_queue_size) is not int or not 1 <= closed_queue_size <= 4096:
            raise ValueError("closed_queue_size must be 1..4096.")
        self.closed_queue_size = closed_queue_size
        self.prices: dict[str, PriceEvent] = {}
        self.in_progress: dict[str, CandleEvent] = {}
        self.closed: dict[str, CandleEvent] = {}
        self.closed_events: deque[CandleEvent] = deque()
        # Fixed 4h stream: one monotonically increasing key per symbol, bounded forever.
        self.closed_highwater: dict[str, CandleEvent] = {}
        self.duplicates = 0
        self.out_of_order = 0
        self.closed_emitted = 0
        self.queue_overflows = 0
        self.candle_gaps = 0
        self.data_loss = False

    def apply(self, event: PriceEvent | CandleEvent) -> bool:
        if not isinstance(event, (PriceEvent, CandleEvent)) or event.symbol not in SYMBOLS:
            raise ValueError("Unsupported market event.")
        if isinstance(event, CandleEvent) and event.interval != "4h":
            raise ValueError("Unsupported candle interval.")
        if isinstance(event, PriceEvent):
            previous = self.prices.get(event.symbol)
            if previous and event.event_time <= previous.event_time:
                self.out_of_order += 1
                return False
            self.prices[event.symbol] = event
            return True
        watermark = self.closed_highwater.get(event.symbol)
        if watermark and event.open_time <= watermark.open_time:
            if event.open_time == watermark.open_time:
                self.duplicates += int(event.is_closed)
            elif event.is_closed:
                self.out_of_order += 1
                self.data_loss = True
                logger.error(
                    "late closed candle rejected symbol=%s; delivery gap possible", event.symbol
                )
            return False
        current = self.in_progress.get(event.symbol)
        if event.is_closed:
            if len(self.closed_events) >= self.closed_queue_size:
                self.queue_overflows += 1
                self.data_loss = True
                raise DataLossError("Closed candle queue full; verification must stop.")
            if watermark and event.open_time > watermark.open_time + timedelta(hours=4):
                self._gap(event.symbol)
            self.closed_highwater[event.symbol] = event
            self.closed[event.symbol] = event
            self.closed_events.append(event)
            self.closed_emitted += 1
            if current and current.open_time <= event.open_time:
                self.in_progress.pop(event.symbol)
            logger.info(
                "candle closed symbol=%s interval=4h open_time=%s",
                event.symbol,
                event.open_time.isoformat(),
            )
            return True
        if current and (
            event.open_time < current.open_time or event.event_time < current.event_time
        ):
            self.out_of_order += 1
            return False
        if current and event.open_time > current.open_time:
            # An in-progress candle disappeared without its final x=true event.
            self._gap(event.symbol)
        elif (
            not current and watermark and event.open_time > watermark.open_time + timedelta(hours=4)
        ):
            self._gap(event.symbol)
        self.in_progress[event.symbol] = event
        return True

    def _gap(self, symbol: str) -> None:
        self.candle_gaps += 1
        self.data_loss = True
        logger.error("closed candle continuity gap symbol=%s; no backfill performed", symbol)

    def drain_closed(self) -> list[CandleEvent]:
        events = list(self.closed_events)
        self.closed_events.clear()
        return events
