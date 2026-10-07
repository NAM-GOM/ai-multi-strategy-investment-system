"""Market data models and parsing. Money/quantities use Decimal, timestamps use UTC."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from trading_system.binance.client import BinanceClient, BinanceError
from trading_system.config import SYMBOLS


def amount(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("Expected decimal string.")
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError("Expected finite nonnegative number.")
    return number


def utc_time(value: Any) -> datetime:
    if type(value) is not int or value < 0:
        raise ValueError("Expected UTC epoch milliseconds.")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)


@dataclass(frozen=True)
class Ticker:
    symbol: str
    price: Decimal
    latency_ms: float


@dataclass(frozen=True)
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: datetime


@dataclass(frozen=True)
class Level:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class OrderBook:
    symbol: str
    bids: tuple[Level, ...]
    asks: tuple[Level, ...]
    latency_ms: float

    @property
    def best_bid(self) -> Decimal:
        return self.bids[0].price

    @property
    def best_ask(self) -> Decimal:
        return self.asks[0].price

    @property
    def spread(self) -> Decimal:
        return self.best_ask - self.best_bid

    @property
    def spread_percent(self) -> Decimal:
        return self.spread / self.best_bid * 100


class PublicAPI:
    def __init__(self, client: BinanceClient) -> None:
        self.client = client

    def ticker(self, symbol: str) -> Ticker:
        if symbol not in SYMBOLS:
            raise BinanceError("invalid_symbol", "/api/v3/ticker/price")
        response = self.client.get("/api/v3/ticker/price", {"symbol": symbol})
        try:
            if response.data["symbol"] != symbol:
                raise ValueError
            return Ticker(symbol, amount(response.data["price"]), response.latency_ms)
        except KeyError, TypeError, ValueError, InvalidOperation:
            raise BinanceError("invalid_response", "/api/v3/ticker/price") from None

    def candles(self) -> tuple[Candle, ...]:
        response = self.client.get(
            "/api/v3/klines",
            {
                "symbol": "BTCUSDT",
                "interval": "4h",
                "limit": 10,
            },
        )
        try:
            if not isinstance(response.data, list) or len(response.data) != 10:
                raise ValueError
            return tuple(
                Candle(
                    utc_time(row[0]),
                    *(amount(value) for value in row[1:6]),
                    utc_time(row[6]),
                )
                for row in response.data
            )
        except IndexError, KeyError, TypeError, ValueError, OverflowError, InvalidOperation:
            raise BinanceError("invalid_response", "/api/v3/klines") from None

    def order_book(self) -> OrderBook:
        response = self.client.get("/api/v3/depth", {"symbol": "BTCUSDT", "limit": 10})
        try:
            bids = tuple(Level(amount(row[0]), amount(row[1])) for row in response.data["bids"])
            asks = tuple(Level(amount(row[0]), amount(row[1])) for row in response.data["asks"])
            if not (1 <= len(bids) <= 10 and 1 <= len(asks) <= 10):
                raise ValueError
            if bids[0].price <= 0 or asks[0].price < bids[0].price:
                raise ValueError
            if any(a.price < b.price for a, b in zip(bids, bids[1:])):
                raise ValueError
            if any(a.price > b.price for a, b in zip(asks, asks[1:])):
                raise ValueError
            return OrderBook("BTCUSDT", bids, asks, response.latency_ms)
        except IndexError, KeyError, TypeError, ValueError, InvalidOperation:
            raise BinanceError("invalid_response", "/api/v3/depth") from None
