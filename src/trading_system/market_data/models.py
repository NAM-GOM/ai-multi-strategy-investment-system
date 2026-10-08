from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PriceEvent:
    symbol: str
    price: Decimal
    event_time: datetime
    received_at: datetime
    source: str = field(default="binance_spot", init=False)
    event_type: str = field(default="MARKET_PRICE_UPDATE", init=False)


@dataclass(frozen=True, slots=True)
class CandleEvent:
    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool
    event_time: datetime
    received_at: datetime
    source: str = field(default="binance_spot", init=False)

    @property
    def event_type(self) -> str:
        return "CLOSED_CANDLE" if self.is_closed else "IN_PROGRESS_CANDLE"

    @property
    def key(self) -> tuple[str, str, datetime]:
        return self.symbol, self.interval, self.open_time


@dataclass(frozen=True, slots=True)
class ServerShutdown:
    event_time: datetime
