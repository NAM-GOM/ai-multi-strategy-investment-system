import logging
from datetime import datetime
from enum import StrEnum

from trading_system.config import SYMBOLS

logger = logging.getLogger("trading_system.health")


class ConnectionState(StrEnum):
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    STALE = "STALE"
    RECONNECTING = "RECONNECTING"
    DISCONNECTED = "DISCONNECTED"
    STOPPED = "STOPPED"


class HealthMonitor:
    def __init__(self, price_stale_after: float = 10, candle_stale_after: float = 30) -> None:
        self.price_stale_after = price_stale_after
        self.candle_stale_after = candle_stale_after
        self.state = ConnectionState.DISCONNECTED
        self.generation = 0
        self.price_received: dict[str, tuple[float, datetime, int]] = {}
        self.candle_received: dict[str, tuple[float, datetime, int]] = {}

    def begin_connection(self, *, reconnect: bool) -> None:
        self.generation += 1
        self.state = ConnectionState.RECONNECTING if reconnect else ConnectionState.CONNECTING

    def record(self, symbol: str, *, price: bool, now: float, event_time: datetime) -> None:
        target = self.price_received if price else self.candle_received
        target[symbol] = now, event_time, self.generation

    def age(self, symbol: str, *, price: bool, now: float, utc_now: datetime) -> float | None:
        value = (self.price_received if price else self.candle_received).get(symbol)
        if value is None or value[2] != self.generation:
            return None
        # Monotonic arrival freshness plus exchange event age; wall clock must be correct.
        return max(0.0, now - value[0], (utc_now - value[1]).total_seconds())

    def fresh(self, symbol: str, *, price: bool, now: float, utc_now: datetime) -> bool:
        age = self.age(symbol, price=price, now=now, utc_now=utc_now)
        return age is not None and age <= (
            self.price_stale_after if price else self.candle_stale_after
        )

    def evaluate(self, now: float, utc_now: datetime) -> ConnectionState:
        if self.state not in (ConnectionState.CONNECTED, ConnectionState.STALE):
            return self.state
        fresh = all(
            self.fresh(symbol, price=price, now=now, utc_now=utc_now)
            for symbol in SYMBOLS
            for price in (True, False)
        )
        updated = ConnectionState.CONNECTED if fresh else ConnectionState.STALE
        if updated != self.state:
            logger.warning("data stale warning state=%s", updated) if not fresh else logger.info(
                "data freshness recovered state=%s",
                updated,
            )
        self.state = updated
        return updated
