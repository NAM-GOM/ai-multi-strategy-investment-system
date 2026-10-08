"""One public combined connection; bounded state and explicit lifecycle management."""

import asyncio
import json
import logging
import math
import random
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from trading_system.config import SYMBOLS
from trading_system.market_data.health import ConnectionState, HealthMonitor
from trading_system.market_data.models import PriceEvent, ServerShutdown
from trading_system.market_data.parser import STREAMS, ParseError, parse_message
from trading_system.market_data.state import DataLossError, MarketState

logger = logging.getLogger("trading_system.websocket")
WS_BASE_URLS = ("wss://data-stream.binance.vision", "wss://stream.binance.com")


class PublicConnect(connect):
    """Reject redirects rather than connect to an unvalidated destination."""

    def process_redirect(self, exc: Exception) -> Exception:
        return exc


@dataclass(frozen=True)
class StreamConfig:
    base_url: str = WS_BASE_URLS[0]
    price_stale_after: float = 10
    candle_stale_after: float = 30
    summary_interval: float = 5
    max_connection_age: float = 23 * 3600 + 50 * 60
    stale_reconnect_after: float = 30
    stable_reset_after: float = 30
    closed_queue_size: int = 128

    def __post_init__(self) -> None:
        if self.base_url not in WS_BASE_URLS:
            raise ValueError("Only the two official public WebSocket hosts are allowed.")
        for value in (
            self.price_stale_after,
            self.candle_stale_after,
            self.summary_interval,
            self.max_connection_age,
            self.stale_reconnect_after,
            self.stable_reset_after,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("WebSocket timing values must be finite and positive.")
        if not 5 <= self.summary_interval <= 10 or self.max_connection_age >= 24 * 3600:
            raise ValueError("Summary interval must be 5..10s; rotation must precede 24h.")
        if type(self.closed_queue_size) is not int or not 1 <= self.closed_queue_size <= 4096:
            raise ValueError("Closed event queue must be 1..4096.")

    @property
    def url(self) -> str:
        return self.base_url + "/stream?streams=" + "/".join(STREAMS)


class Backoff:
    def __init__(self, *, random_value: Callable[[], float] = random.random) -> None:
        self.attempt = 0
        self.random_value = random_value

    def next_delay(self) -> float:
        nominal = min(60, 2 ** min(self.attempt, 6))
        self.attempt += 1
        return max(1.0, min(60.0, nominal * (0.75 + 0.5 * self.random_value())))

    def reset(self) -> None:
        self.attempt = 0


class WebSocketMonitor:
    def __init__(
        self,
        config: StreamConfig | None = None,
        *,
        connector=None,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        random_value: Callable[[], float] = random.random,
        wait_override=None,
    ) -> None:
        self.config = config or StreamConfig()
        self.connector = connector or PublicConnect
        self.monotonic, self.utc_now = monotonic, utc_now
        self.wait_override = wait_override
        self.backoff = Backoff(random_value=random_value)
        self.market = MarketState(self.config.closed_queue_size)
        self.health = HealthMonitor(self.config.price_stale_after, self.config.candle_stale_after)
        self.messages_received = self.valid_messages = self.invalid_messages = 0
        self.reconnect_count = self.connection_opens = self.disconnects = self.connection_errors = 0
        self.price_counts = dict.fromkeys(SYMBOLS, 0)
        self.candle_counts = dict.fromkeys(SYMBOLS, 0)
        self.blocked_environment = self.fatal_error = self.final_healthy = False
        self.normal_shutdown = False
        self.started = self.monotonic()
        self.last_error_category: str | None = None
        self.last_http_status: int | None = None
        # Library debug logs could expose proxy headers; do not emit wire logs.
        logging.getLogger("websockets.client").disabled = True
        logging.getLogger("websockets").setLevel(logging.WARNING)

    def snapshot(self) -> dict:
        now, utc_now = self.monotonic(), self.utc_now()
        state = self.health.evaluate(now, utc_now)
        per_symbol = {}
        for symbol in SYMBOLS:
            price = self.market.prices.get(symbol)
            candle = self.market.in_progress.get(symbol) or self.market.closed.get(symbol)
            per_symbol[symbol] = {
                "price": format(price.price, "f") if price else None,
                "price_messages": self.price_counts[symbol],
                "candle_messages": self.candle_counts[symbol],
                "last_price_received_at": price.received_at.isoformat() if price else None,
                "price_age_seconds": self.health.age(symbol, price=True, now=now, utc_now=utc_now),
                "candle_age_seconds": self.health.age(
                    symbol, price=False, now=now, utc_now=utc_now
                ),
                "price_fresh": self.health.fresh(symbol, price=True, now=now, utc_now=utc_now),
                "candle_fresh": self.health.fresh(symbol, price=False, now=now, utc_now=utc_now),
                "candle": "CLOSED"
                if candle and candle.is_closed
                else "IN_PROGRESS"
                if candle
                else "NOT_RECEIVED",
            }
        healthy = state == ConnectionState.CONNECTED and not self.market.data_loss
        return {
            "connection": str(state),
            "uptime_seconds": round(now - self.started, 3),
            "symbols": per_symbol,
            "messages_received": self.messages_received,
            "valid_messages": self.valid_messages,
            "invalid_messages": self.invalid_messages,
            "reconnect_count": self.reconnect_count,
            "connection_opens": self.connection_opens,
            "disconnects": self.disconnects,
            "connection_errors": self.connection_errors,
            "closed_candles": self.market.closed_emitted,
            "duplicate_closures": self.market.duplicates,
            "out_of_order": self.market.out_of_order,
            "queue_depth": len(self.market.closed_events),
            "queue_overflows": self.market.queue_overflows,
            "candle_gaps": self.market.candle_gaps,
            "data_loss": self.market.data_loss,
            "health": "DATA_LOSS"
            if self.market.data_loss
            else "HEALTHY"
            if healthy
            else "NOT_HEALTHY",
            "blocked_environment": self.blocked_environment,
            "error_category": self.last_error_category,
            "http_status": self.last_http_status,
            "normal_shutdown": self.normal_shutdown,
            "final_healthy": self.final_healthy,
            "all_symbols_observed": all(
                self.price_counts[s] and self.candle_counts[s] for s in SYMBOLS
            ),
        }

    def _on_message(self, raw) -> bool:
        self.messages_received += 1
        now, utc_now = self.monotonic(), self.utc_now()
        try:
            event = parse_message(raw, utc_now)
        except ParseError:
            self.invalid_messages += 1
            if self.invalid_messages == 1 or self.invalid_messages % 100 == 0:
                logger.warning("invalid message count=%d; payload omitted", self.invalid_messages)
            return False
        if isinstance(event, ServerShutdown):
            logger.info("serverShutdown received; reconnect required")
            return True
        self.valid_messages += 1
        price = isinstance(event, PriceEvent)
        (self.price_counts if price else self.candle_counts)[event.symbol] += 1
        accepted = self.market.apply(event)
        if accepted:
            self.health.record(event.symbol, price=price, now=now, event_time=event.event_time)
        self.health.evaluate(now, utc_now)
        return False

    async def _wait(self, delay: float, stop: asyncio.Event) -> None:
        if self.wait_override is not None:
            await self.wait_override(delay)
        else:
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def run(
        self, duration: float, *, stop: asyncio.Event | None = None, on_summary=None
    ) -> dict:
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("duration must be finite and positive.")
        stop = stop or asyncio.Event()
        self.started = self.monotonic()
        deadline = self.started + duration
        self.health.begin_connection(reconnect=False)

        # Fake clock waits apply only to reconnects, not to this independently paced reporter.
        async def reporting() -> None:
            while not stop.is_set() and self.monotonic() < deadline:
                if on_summary:
                    try:
                        on_summary(self)
                    except Exception:
                        self.fatal_error = True
                        self.last_error_category = "summary_consumer_failure"
                        logger.error("summary consumer failed; stopping")
                        stop.set()
                        return
                snapshot = self.snapshot()
                logger.info(
                    "message received count=%d invalid message count=%d connection=%s",
                    snapshot["messages_received"],
                    snapshot["invalid_messages"],
                    snapshot["connection"],
                )
                await asyncio.sleep(self.config.summary_interval)

        reporter = asyncio.create_task(reporting())
        attempted = False
        try:
            while not stop.is_set() and self.monotonic() < deadline:
                if attempted:
                    self.reconnect_count += 1
                    self.health.begin_connection(reconnect=True)
                attempted = True
                connected_at = None
                stale_since = None
                healthy_for_reset = False
                try:
                    logger.info("WebSocket connect attempt=%d", self.reconnect_count + 1)
                    async with self.connector(
                        self.config.url,
                        ping_interval=None,
                        open_timeout=min(10, deadline - self.monotonic()),
                        close_timeout=5,
                        max_size=65_536,
                        max_queue=16,
                        compression=None,
                        logger=logging.getLogger("websockets.client"),
                    ) as socket:
                        self.connection_opens += 1
                        connected_at = self.monotonic()
                        self.health.state = ConnectionState.CONNECTED
                        logger.info("WebSocket connection open")
                        while not stop.is_set() and self.monotonic() < deadline:
                            now = self.monotonic()
                            if now - connected_at >= self.config.max_connection_age:
                                logger.info("planned reconnect before 24h lifetime")
                                break
                            try:
                                raw = await asyncio.wait_for(
                                    socket.recv(), timeout=min(1, deadline - now)
                                )
                            except TimeoutError:
                                raw = None
                            if raw is not None and self._on_message(raw):
                                break
                            phase = self.health.evaluate(self.monotonic(), self.utc_now())
                            if phase == ConnectionState.STALE:
                                stale_since = (
                                    stale_since if stale_since is not None else self.monotonic()
                                )
                                if (
                                    self.monotonic() - stale_since
                                    >= self.config.stale_reconnect_after
                                ):
                                    logger.warning("stale connection reconnect")
                                    break
                            else:
                                stale_since = None
                        self.final_healthy = (
                            self.health.evaluate(self.monotonic(), self.utc_now())
                            == ConnectionState.CONNECTED
                            and not self.market.data_loss
                        )
                        healthy_for_reset = self.final_healthy
                except DataLossError:
                    self.fatal_error = True
                    self.last_error_category = "closed_candle_queue_overflow"
                    logger.error("closed candle queue overflow; stopping to expose data loss")
                    break
                except Exception as error:
                    healthy_for_reset = (
                        self.health.evaluate(self.monotonic(), self.utc_now())
                        == ConnectionState.CONNECTED
                    )
                    self.final_healthy = False
                    # Never include str(error), traceback, proxy headers or frame contents.
                    response = getattr(error, "response", None)
                    status = getattr(response, "status_code", None)
                    self.last_http_status = status if type(status) is int else None
                    self.last_error_category = (
                        "connection_closed"
                        if isinstance(error, ConnectionClosed)
                        else type(error).__name__
                    )
                    if not isinstance(error, ConnectionClosed) or isinstance(
                        error, ConnectionClosedError
                    ):
                        self.connection_errors += 1
                    logger.warning(
                        "connection error category=%s HTTP=%s",
                        self.last_error_category,
                        self.last_http_status,
                    )
                    if self.last_http_status in (
                        300,
                        301,
                        302,
                        303,
                        307,
                        308,
                        400,
                        401,
                        403,
                        404,
                        426,
                        451,
                        501,
                    ) or isinstance(error, ssl.SSLCertVerificationError):
                        self.blocked_environment = True
                        break
                finally:
                    self.disconnects += int(connected_at is not None)
                    self.health.state = ConnectionState.DISCONNECTED
                    logger.info("WebSocket disconnect")
                if stop.is_set() or self.monotonic() >= deadline:
                    break
                if (
                    connected_at is not None
                    and healthy_for_reset
                    and self.monotonic() - connected_at >= self.config.stable_reset_after
                ):
                    self.backoff.reset()
                self.final_healthy = False
                self.health.state = ConnectionState.RECONNECTING
                delay = self.backoff.next_delay()
                logger.info("reconnect attempt backoff_seconds=%.3f", delay)
                await self._wait(min(delay, deadline - self.monotonic()), stop)
            self.normal_shutdown = True
        finally:
            reporter.cancel()
            await asyncio.gather(reporter, return_exceptions=True)
            self.health.state = ConnectionState.STOPPED
            logger.info(
                "graceful shutdown state=STOPPED messages=%d invalid=%d reconnects=%d",
                self.messages_received,
                self.invalid_messages,
                self.reconnect_count,
            )
        result = self.snapshot()
        result["success"] = bool(
            result["all_symbols_observed"] and self.final_healthy and not self.fatal_error
        )
        result["live_status"] = (
            "LIVE_PASS"
            if result["success"]
            else "BLOCKED_ENVIRONMENT"
            if (self.blocked_environment or (not self.valid_messages and self.connection_errors))
            else "FAILED_VALIDATION"
        )
        return result


def print_summary(monitor: WebSocketMonitor) -> None:
    for candle in monitor.market.drain_closed():
        print(f"CLOSED_CANDLE {candle.symbol} 4h open_time={candle.open_time.isoformat()}")
    summary = monitor.snapshot()
    seconds = int(summary["uptime_seconds"])
    print(
        f"\nDEV-M02 WebSocket Monitor\nConnection: {summary['connection']}\n"
        f"Uptime: {seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
    )
    for symbol, data in summary["symbols"].items():
        age = data["price_age_seconds"]
        age_label = f"{age:.2f}" if age is not None else "NOT_RECEIVED"
        print(
            f"{symbol}: {data['price'] or 'NOT_RECEIVED'} USDT "
            f"price_messages={data['price_messages']} candle_messages={data['candle_messages']} "
            f"price_age_s={age_label}"
        )
        print(f"{symbol} 4H Candle: {data['candle']}")
    print(
        f"Messages Received: {summary['messages_received']}\n"
        f"Invalid Messages: {summary['invalid_messages']}\n"
        f"Reconnect Count: {summary['reconnect_count']}\n"
        f"Closed Candles: {summary['closed_candles']}\n"
        f"Queue Overflows: {summary['queue_overflows']}\n"
        f"Candle Gaps: {summary['candle_gaps']}\nHealth: {summary['health']}"
    )


def run_stream_cli(duration: float, base_url: str, report_file: str | None = None) -> int:
    try:
        monitor = WebSocketMonitor(StreamConfig(base_url=base_url))
        result = asyncio.run(monitor.run(duration, on_summary=print_summary))
    except KeyboardInterrupt:
        logger.info("stream interrupted; graceful shutdown requested")
        return 130
    except ValueError:
        print("Invalid stream configuration or duration.")
        return 2
    except Exception as error:
        logger.error("stream failure category=%s", type(error).__name__)
        print("Stream failed; see safe error category in logs/app.log.")
        return 1
    print_summary(monitor)
    print(
        f"Live Result: {result['live_status']}\nFinal data fresh: {result['final_healthy']}\n"
        f"Normal shutdown: {result['normal_shutdown']}\n"
        f"Closed candle live observed: {result['closed_candles'] > 0}"
    )
    if report_file:
        try:
            # Exclusive creation preserves previous validation evidence.
            with Path(report_file).open("x", encoding="utf-8") as output:
                json.dump(result, output, indent=2)
                output.write("\n")
        except OSError:
            print("Cannot create report file; choose a new writable path.")
            return 2
    return 0 if result["success"] else 1
