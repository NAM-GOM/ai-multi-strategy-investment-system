"""Deterministic routing, Decimal, UTC, finalization, bounded storage and health tests."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_system.config import SYMBOLS
from trading_system.market_data.health import ConnectionState, HealthMonitor
from trading_system.market_data.models import CandleEvent, PriceEvent, ServerShutdown
from trading_system.market_data.parser import FOUR_HOURS_MS, STREAMS, ParseError, parse_message
from trading_system.market_data.state import DataLossError, MarketState

BASE = datetime(2026, 10, 8, tzinfo=UTC)
START = int(BASE.timestamp() * 1000)


def price_payload(symbol="BTCUSDT", *, millis=START, price="100.1234567890123456789"):
    return {
        "stream": symbol.lower() + "@miniTicker",
        "data": {"e": "24hrMiniTicker", "E": millis, "s": symbol, "c": price},
    }


def candle_payload(symbol="BTCUSDT", *, start=START, closed=False, millis=None):
    return {
        "stream": symbol.lower() + "@kline_4h",
        "data": {
            "e": "kline",
            "E": millis if millis is not None else start + (FOUR_HOURS_MS if closed else 1000),
            "s": symbol,
            "k": {
                "t": start,
                "T": start + FOUR_HOURS_MS - 1,
                "s": symbol,
                "i": "4h",
                "o": "100.10",
                "h": "110.20",
                "l": "90.30",
                "c": "105.40",
                "v": "0.0000000000123456789",
                "x": closed,
            },
        },
    }


def event(payload, received_at=BASE):
    return parse_message(json.dumps(payload), received_at)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_price_routing_decimal_utc_source(symbol):
    local_time = BASE.astimezone(timezone(timedelta(hours=9)))
    result = event(price_payload(symbol, millis=START + 123), local_time)
    assert isinstance(result, PriceEvent)
    assert result.symbol == symbol
    assert result.price == Decimal("100.1234567890123456789")
    assert result.event_time == BASE + timedelta(milliseconds=123)
    assert result.received_at == BASE and result.received_at.tzinfo is UTC
    assert result.event_time.tzinfo is UTC
    assert result.source == "binance_spot" and result.event_type == "MARKET_PRICE_UPDATE"


@pytest.mark.parametrize("symbol", SYMBOLS)
@pytest.mark.parametrize("closed", [False, True])
def test_candle_routing_decimal_and_boundaries(symbol, closed):
    result = event(candle_payload(symbol, closed=closed))
    assert isinstance(result, CandleEvent)
    assert result.symbol == symbol and result.interval == "4h"
    assert result.open_time == BASE
    assert result.close_time == BASE + timedelta(hours=4, milliseconds=-1)
    assert result.is_closed is closed
    assert result.volume == Decimal("0.0000000000123456789")
    assert all(
        isinstance(getattr(result, key), Decimal) for key in ("open", "high", "low", "close")
    )
    assert result.key == (symbol, "4h", BASE)
    assert result.event_type == ("CLOSED_CANDLE" if closed else "IN_PROGRESS_CANDLE")


def test_exactly_six_streams_and_server_shutdown():
    assert len(STREAMS) == len(set(STREAMS)) == 6
    for payload in (
        {"e": "serverShutdown", "E": START},
        {"stream": "!serverShutdown", "data": {"e": "serverShutdown", "E": START}},
    ):
        assert event(payload) == ServerShutdown(BASE)


@pytest.mark.parametrize(
    "raw",
    ["{", "[]", "null", "1", "{}", b"\xff", "x" * 65537, None],
    ids=(
        "broken-object",
        "array",
        "null",
        "number",
        "empty-object",
        "invalid-utf8",
        "oversized-frame",
        "wrong-type",
    ),
)
def test_invalid_json_or_frame_rejected_safely(raw):
    with pytest.raises(ParseError, match="Invalid public WebSocket message"):
        parse_message(raw, BASE)


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "-1",
        "NaN",
        "Infinity",
        "-Infinity",
        "bad",
        100,
        None,
        "1e999999999",
        "1e-999999999",
    ],
)
def test_abnormal_price_rejected(value):
    with pytest.raises(ParseError):
        event(price_payload(price=value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("s", "DOGEUSDT"),
        ("s", "btcusdt"),
        ("s", "ETHUSDT"),
        ("e", "trade"),
        ("E", -1),
        ("E", True),
        ("E", 10**100),
    ],
)
def test_invalid_price_metadata_rejected(field, value):
    payload = price_payload()
    payload["data"][field] = value
    with pytest.raises(ParseError):
        event(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("s", "ETHUSDT"),
        ("i", "1m"),
        ("x", "false"),
        ("x", 1),
        ("t", START + 1),
        ("T", START + FOUR_HOURS_MS),
        ("o", "0"),
        ("h", "90"),
        ("l", "110"),
        ("c", "NaN"),
        ("v", "-1"),
    ],
)
def test_invalid_candle_rejected(field, value):
    payload = candle_payload()
    payload["data"]["k"][field] = value
    with pytest.raises(ParseError):
        event(payload)


def test_closed_event_time_and_naive_receive_time_rejected():
    with pytest.raises(ParseError):
        event(candle_payload(closed=True, millis=START + 1000))
    with pytest.raises(ParseError):
        event(price_payload(), BASE.replace(tzinfo=None))
    payload = price_payload()
    payload["stream"] = "btcusdt@trade"
    with pytest.raises(ParseError):
        event(payload)


def test_progress_never_emits_closed_and_final_is_delivered_once():
    state = MarketState()
    progress = event(candle_payload())
    final = event(candle_payload(closed=True))
    assert state.apply(progress)
    assert state.in_progress["BTCUSDT"] == progress
    assert state.drain_closed() == [] and state.closed_emitted == 0
    assert state.apply(final)
    assert "BTCUSDT" not in state.in_progress
    assert state.closed["BTCUSDT"] == final
    assert state.drain_closed() == [final]
    for _ in range(10):
        assert not state.apply(final)
    assert not state.apply(progress)
    assert state.drain_closed() == [] and state.closed_emitted == 1
    assert state.duplicates == 10


def test_watermark_survives_drain_reconnect_and_many_candles():
    state = MarketState()
    for index in range(1000):
        for symbol in SYMBOLS:
            final = event(candle_payload(symbol, start=START + index * FOUR_HOURS_MS, closed=True))
            assert state.apply(final)
            assert state.drain_closed() == [final]
            assert not state.apply(final)
    assert len(state.closed_highwater) == len(state.closed) == 3
    assert state.closed_emitted == state.duplicates == 3000
    assert not state.data_loss


def test_prices_coalesce_and_old_event_cannot_replace_latest():
    state = MarketState()
    for millis in range(100):
        for symbol in SYMBOLS:
            state.apply(event(price_payload(symbol, millis=START + millis)))
    assert len(state.prices) == 3
    latest = state.prices["BTCUSDT"]
    assert not state.apply(event(price_payload(millis=START)))
    assert state.prices["BTCUSDT"] is latest


def test_closed_queue_overflow_is_explicit_and_preserves_pending_event():
    state = MarketState(closed_queue_size=1)
    first = event(candle_payload(closed=True))
    state.apply(first)
    with pytest.raises(DataLossError):
        state.apply(event(candle_payload("ETHUSDT", closed=True)))
    assert state.queue_overflows == 1 and state.data_loss
    assert state.drain_closed() == [first]
    assert "ETHUSDT" not in state.closed_highwater


def test_candle_gap_out_of_order_and_bounded_progress(caplog):
    state = MarketState()
    first = event(candle_payload())
    state.apply(first)
    next_candle = event(candle_payload(start=START + FOUR_HOURS_MS))
    state.apply(next_candle)
    assert state.data_loss and state.candle_gaps == 1
    assert "continuity gap" in caplog.text
    assert not state.apply(first)
    assert len(state.in_progress) == 1
    state.apply(event(candle_payload(start=START + 2 * FOUR_HOURS_MS, closed=True)))
    assert not state.apply(event(candle_payload(closed=True)))
    assert state.out_of_order == 2


def test_gap_after_watermark_warns_once_per_progress_candle():
    state = MarketState()
    state.apply(event(candle_payload(closed=True)))
    state.drain_closed()
    for _ in range(10):
        state.apply(event(candle_payload(start=START + 2 * FOUR_HOURS_MS)))
    assert state.candle_gaps == 1


@pytest.mark.parametrize("size", [0, -1, 4097, True])
def test_invalid_queue_size_rejected(size):
    with pytest.raises(ValueError):
        MarketState(size)


def test_unsupported_state_inputs_rejected():
    state = MarketState()
    for invalid in (
        None,
        replace(event(price_payload()), symbol="DOGEUSDT"),
        replace(event(candle_payload()), interval="1m"),
    ):
        with pytest.raises(ValueError):
            state.apply(invalid)


def populated_health():
    health = HealthMonitor()
    health.begin_connection(reconnect=False)
    health.state = ConnectionState.CONNECTED
    for symbol in SYMBOLS:
        for price in (True, False):
            health.record(symbol, price=price, now=0, event_time=BASE)
    return health


def test_health_stale_limits_are_separate_and_recover(caplog):
    health = populated_health()
    assert health.evaluate(10, BASE + timedelta(seconds=10)) == ConnectionState.CONNECTED
    assert health.evaluate(11, BASE + timedelta(seconds=11)) == ConnectionState.STALE
    assert "data stale warning" in caplog.text
    assert health.fresh("BTCUSDT", price=False, now=11, utc_now=BASE + timedelta(seconds=11))
    for symbol in SYMBOLS:
        health.record(symbol, price=True, now=11, event_time=BASE + timedelta(seconds=11))
    assert health.evaluate(11, BASE + timedelta(seconds=11)) == ConnectionState.CONNECTED
    assert not health.fresh("BTCUSDT", price=False, now=31, utc_now=BASE + timedelta(seconds=31))


def test_reconnect_generation_and_old_exchange_events_never_healthy():
    health = populated_health()
    health.begin_connection(reconnect=True)
    assert health.state == ConnectionState.RECONNECTING
    assert health.age("BTCUSDT", price=True, now=1, utc_now=BASE) is None
    health.state = ConnectionState.CONNECTED
    assert health.evaluate(1, BASE) == ConnectionState.STALE
    for symbol in SYMBOLS:
        for price in (True, False):
            health.record(symbol, price=price, now=20, event_time=BASE)
    assert health.evaluate(20, BASE + timedelta(seconds=20)) == ConnectionState.STALE
    health.state = ConnectionState.STOPPED
    assert health.evaluate(20, BASE) == ConnectionState.STOPPED
