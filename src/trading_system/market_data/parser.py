"""Strict combined-stream routing. No payloads are included in parsing errors."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from trading_system.config import SYMBOLS
from trading_system.market_data.models import CandleEvent, PriceEvent, ServerShutdown

STREAMS = tuple(
    f"{symbol.lower()}@{suffix}" for suffix in ("miniTicker", "kline_4h") for symbol in SYMBOLS
)
FOUR_HOURS_MS = 14_400_000


class ParseError(ValueError):
    pass


def timestamp(value: object) -> datetime:
    if type(value) is not int or value < 0:
        raise ParseError("Invalid millisecond timestamp.")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


def decimal(value: object, *, positive: bool = True) -> Decimal:
    if not isinstance(value, str) or len(value) > 100:
        raise ParseError("Invalid numeric string.")
    number = Decimal(value)
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        raise ParseError("Invalid numeric value.")
    if abs(number.as_tuple().exponent) > 30 or number.adjusted() > 30:
        raise ParseError("Numeric scale outside supported Spot data bounds.")
    return number


def parse_message(
    raw: str | bytes,
    received_at: datetime,
) -> PriceEvent | CandleEvent | ServerShutdown:
    try:
        if not isinstance(raw, (str, bytes)) or len(raw) > 65_536:
            raise ParseError("Invalid frame size/type.")
        if received_at.tzinfo is None:
            raise ParseError("received_at must be timezone-aware.")
        received_at = received_at.astimezone(UTC)
        wrapper = json.loads(raw)
        if not isinstance(wrapper, dict):
            raise ParseError("Expected object.")
        if wrapper.get("e") == "serverShutdown":
            return ServerShutdown(timestamp(wrapper["E"]))
        stream, data = wrapper["stream"], wrapper["data"]
        if not isinstance(data, dict):
            raise ParseError("Expected stream data object.")
        if stream == "!serverShutdown" and data.get("e") == "serverShutdown":
            return ServerShutdown(timestamp(data["E"]))
        if stream not in STREAMS:
            raise ParseError("Unsupported stream.")
        symbol = data["s"]
        if symbol not in SYMBOLS or not stream.startswith(symbol.lower() + "@"):
            raise ParseError("Mismatched symbol/stream.")
        event_time = timestamp(data["E"])
        if stream.endswith("@miniTicker"):
            if data["e"] != "24hrMiniTicker":
                raise ParseError("Unexpected price event type.")
            return PriceEvent(symbol, decimal(data["c"]), event_time, received_at)
        candle = data["k"]
        if data["e"] != "kline" or candle["s"] != symbol or candle["i"] != "4h":
            raise ParseError("Mismatched candle event.")
        if type(candle["x"]) is not bool:
            raise ParseError("Closure flag must be boolean.")
        start, end = candle["t"], candle["T"]
        open_time, close_time = timestamp(start), timestamp(end)
        if start % FOUR_HOURS_MS or end != start + FOUR_HOURS_MS - 1:
            raise ParseError("Invalid UTC 4h candle boundaries.")
        if event_time < open_time or (candle["x"] and event_time <= close_time):
            raise ParseError("Inconsistent candle event time.")
        opened, high, low, close = (decimal(candle[key]) for key in ("o", "h", "l", "c"))
        if high < max(opened, close) or low > min(opened, close) or high < low:
            raise ParseError("Inconsistent OHLC range.")
        return CandleEvent(
            symbol,
            "4h",
            open_time,
            close_time,
            opened,
            high,
            low,
            close,
            decimal(candle["v"], positive=False),
            candle["x"],
            event_time,
            received_at,
        )
    except ValueError, TypeError, KeyError, OverflowError, InvalidOperation, RecursionError:
        raise ParseError("Invalid public WebSocket message.") from None
