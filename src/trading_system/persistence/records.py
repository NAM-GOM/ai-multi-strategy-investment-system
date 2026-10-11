from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_system.config import SYMBOLS
from trading_system.market_data.models import CandleEvent

INTERVAL_MS = 14_400_000
DAY_MS = 86_400_000
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_MS = 253_402_300_799_999
SOURCES = ("WS_LIVE", "REST_BOOTSTRAP", "REST_RECOVERY")


def epoch_ms(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("UTC conversion requires an aware datetime.")
    delta = value.astimezone(UTC) - EPOCH
    return delta.days * DAY_MS + delta.seconds * 1000 + delta.microseconds // 1000


def now_ms() -> int:
    return epoch_ms(datetime.now(UTC))


def utc_datetime(value: int) -> datetime:
    validate_ms(value)
    return EPOCH + timedelta(milliseconds=value)


def validate_ms(value):
    if type(value) is not int or not 0 <= value <= MAX_MS:
        raise ValueError("Invalid UTC milliseconds.")


def decimal_text(value: Decimal, *, positive=True) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Expected finite Decimal.")
    if (value <= 0 if positive else value < 0) or abs(value.as_tuple().exponent) > 30:
        raise ValueError("Invalid Decimal value/scale.")
    if value.adjusted() > 30:
        raise ValueError("Decimal magnitude outside supported bounds.")
    return format(value, "f")


@dataclass(frozen=True)
class CandleRecord:
    symbol: str
    interval: str
    open_time_ms: int
    close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    event_time_ms: int | None
    ingested_at_ms: int
    source: str

    def validate(self):
        if self.symbol not in SYMBOLS or self.interval != "4h" or self.source not in SOURCES:
            raise ValueError("Unsupported candle identity/source.")
        for value in (self.open_time_ms, self.close_time_ms, self.ingested_at_ms):
            validate_ms(value)
        if (
            self.open_time_ms % INTERVAL_MS
            or self.close_time_ms != self.open_time_ms + INTERVAL_MS - 1
        ):
            raise ValueError("Invalid UTC 4h boundaries.")
        if self.ingested_at_ms <= self.close_time_ms:
            raise ValueError("Candle must already be closed at ingestion.")
        if self.event_time_ms is not None:
            validate_ms(self.event_time_ms)
            if self.event_time_ms <= self.close_time_ms:
                raise ValueError("Candle event precedes closure.")
        if self.source == "WS_LIVE" and self.event_time_ms is None:
            raise ValueError("WS_LIVE requires its actual event timestamp.")
        for value in (self.open, self.high, self.low, self.close):
            decimal_text(value)
        decimal_text(self.volume, positive=False)
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Invalid OHLC range.")

    @property
    def identity(self):
        return self.symbol, self.interval, self.open_time_ms

    @property
    def content(self):
        # Numeric Decimal equality treats alternate formatting as the same market data.
        return self.close_time_ms, self.open, self.high, self.low, self.close, self.volume

    @classmethod
    def from_ws(cls, event: CandleEvent, ingested_at_ms: int):
        if not event.is_closed:
            raise ValueError("IN_PROGRESS candles cannot be persisted.")
        record = cls(
            event.symbol,
            event.interval,
            epoch_ms(event.open_time),
            epoch_ms(event.close_time),
            event.open,
            event.high,
            event.low,
            event.close,
            event.volume,
            epoch_ms(event.event_time),
            ingested_at_ms,
            "WS_LIVE",
        )
        record.validate()
        return record


@dataclass(frozen=True)
class PriceSnapshot:
    symbol: str
    bucket_start_ms: int
    price: Decimal
    event_time_ms: int
    received_at_ms: int
    source: str


def candle_from_row(row) -> CandleRecord:
    return CandleRecord(
        row["symbol"],
        row["interval"],
        row["open_time_ms"],
        row["close_time_ms"],
        *(Decimal(row[key + "_text"]) for key in ("open", "high", "low", "close", "volume")),
        row["event_time_ms"],
        row["ingested_at_ms"],
        row["source"],
    )
