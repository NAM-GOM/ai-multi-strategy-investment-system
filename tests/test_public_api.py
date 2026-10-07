from datetime import UTC
from decimal import Decimal

import httpx
import pytest

from trading_system.binance.client import BinanceError
from trading_system.binance.public import PublicAPI
from trading_system.config import SYMBOLS, Config


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_ticker_parsing_without_credentials(client_factory, symbol):
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v3/ticker/price"
        assert request.url.params["symbol"] == symbol
        assert "X-MBX-APIKEY" not in request.headers
        assert "signature" not in request.url.params
        return httpx.Response(200, json={"symbol": symbol, "price": "123.45000001"})

    ticker = PublicAPI(client_factory(handler)).ticker(symbol)
    assert ticker.symbol == symbol
    assert ticker.price == Decimal("123.45000001")
    assert ticker.latency_ms >= 0


def test_public_never_sends_configured_credentials(client_factory):
    def handler(request):
        assert "X-MBX-APIKEY" not in request.headers
        assert "signature" not in request.url.params
        return httpx.Response(200, json={"symbol": "BTCUSDT", "price": "100"})

    PublicAPI(
        client_factory(handler, Config(api_key="test-only-key", api_secret="test-only-secret"))
    ).ticker("BTCUSDT")


def test_ohlcv_parsing_and_utc(client_factory, candle_rows):
    def handler(request):
        assert request.url.path == "/api/v3/klines"
        assert dict(request.url.params) == {"symbol": "BTCUSDT", "interval": "4h", "limit": "10"}
        return httpx.Response(200, json=candle_rows)

    candles = PublicAPI(client_factory(handler)).candles()
    assert len(candles) == 10
    assert candles[0].open == Decimal("100.10")
    assert candles[0].high == Decimal("110.00")
    assert candles[0].low == Decimal("90.00")
    assert candles[0].close == Decimal("105.20")
    assert candles[0].volume == Decimal("12.30")
    assert candles[0].open_time.tzinfo is UTC
    assert candles[0].close_time.tzinfo is UTC
    assert candles[0].open_time.isoformat() == "2023-11-14T22:13:20+00:00"
    assert (candles[0].close_time - candles[0].open_time).total_seconds() == 14399.999


def test_order_book_spread_and_latency(client_factory, book_data, monkeypatch):
    times = iter([100.0, 100.0834])
    monkeypatch.setattr("trading_system.binance.client.perf_counter", lambda: next(times))

    def handler(request):
        assert dict(request.url.params) == {"symbol": "BTCUSDT", "limit": "10"}
        return httpx.Response(200, json=book_data)

    book = PublicAPI(client_factory(handler)).order_book()
    assert len(book.bids) == len(book.asks) == 10
    assert book.bids[0].quantity == Decimal("1.20")
    assert book.best_bid == Decimal(100)
    assert book.best_ask == Decimal(101)
    assert book.spread == Decimal(1)
    assert book.spread_percent == Decimal(1)
    assert book.latency_ms == pytest.approx(83.4)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"symbol": "ETHUSDT", "price": "1"},
        {"symbol": "BTCUSDT", "price": "NaN"},
        {"symbol": "BTCUSDT", "price": "-1"},
        {"symbol": "BTCUSDT", "price": "Infinity"},
    ],
)
def test_bad_ticker_response_is_safe_error(client_factory, payload):
    api = PublicAPI(client_factory(lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(BinanceError, match="invalid_response"):
        api.ticker("BTCUSDT")


@pytest.mark.parametrize("payload", [[], [[0]], "invalid", [None] * 10])
def test_bad_candles_response(client_factory, payload):
    api = PublicAPI(client_factory(lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(BinanceError, match="invalid_response"):
        api.candles()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"bids": [], "asks": []},
        {"bids": [["0", "1"]], "asks": [["1", "1"]]},
        {"bids": [["2", "1"]], "asks": [["1", "1"]]},
        {"bids": [["2", "1"], ["3", "1"]], "asks": [["4", "1"]]},
    ],
)
def test_bad_order_book_response(client_factory, payload):
    api = PublicAPI(client_factory(lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(BinanceError, match="invalid_response"):
        api.order_book()


def test_invalid_symbol_does_not_make_request(client_factory):
    def handler(_):
        pytest.fail("No HTTP request expected")

    with pytest.raises(BinanceError, match="invalid_symbol"):
        PublicAPI(client_factory(handler)).ticker("UNKNOWN")
