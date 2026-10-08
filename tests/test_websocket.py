"""No sockets: fake connections and clock make lifecycle tests deterministic."""

import asyncio
import json
import logging
from collections import deque
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_market_data import BASE, START, candle_payload, price_payload
from websockets.exceptions import ConnectionClosedOK
from websockets.frames import Frame, Opcode
from websockets.protocol import OPEN, Protocol, Side

from trading_system.binance import websocket as ws
from trading_system.binance.websocket import PublicConnect
from trading_system.config import SYMBOLS
from trading_system.market_data.health import ConnectionState


class Clock:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def monotonic(self):
        return self.now

    def utc_now(self):
        return BASE + timedelta(seconds=self.now)

    async def wait(self, delay):
        self.delays.append(delay)
        self.now = round(self.now + delay, 6)
        await asyncio.sleep(0)


class FakeSocket:
    def __init__(self, clock, actions=(), *, idle=False, blocking=False, step=0.2):
        self.clock, self.actions = clock, deque(actions)
        self.idle, self.blocking, self.step = idle, blocking, step
        self.index = 0
        self.closed = False

    async def recv(self):
        await asyncio.sleep(0)
        if self.blocking:
            await asyncio.Future()
        self.clock.now = round(self.clock.now + self.step, 6)
        if self.actions:
            action = self.actions.popleft()
            if isinstance(action, Exception):
                raise action
            return action(self.clock) if callable(action) else action
        if self.idle:
            self.clock.now += 1
            raise TimeoutError
        symbol = SYMBOLS[self.index % 3]
        millis = START + int(self.clock.now * 1000)
        payload = (
            price_payload(symbol, millis=millis)
            if self.index % 6 < 3
            else candle_payload(symbol, millis=millis)
        )
        self.index += 1
        return json.dumps(payload)


class Context:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        if isinstance(self.socket, Exception):
            raise self.socket
        return self.socket

    async def __aexit__(self, *args):
        self.socket.closed = True


class Factory:
    def __init__(self, clock, sessions=()):
        self.clock, self.sessions = clock, deque(sessions)
        self.calls = []
        self.sockets = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        socket = self.sessions.popleft() if self.sessions else FakeSocket(self.clock)
        self.sockets.append(socket)
        return Context(socket)


def monitor_fixture(config=None, sessions=()):
    clock = Clock()
    factory = Factory(clock, sessions)
    monitor = ws.WebSocketMonitor(
        config,
        connector=factory,
        monotonic=clock.monotonic,
        utc_now=clock.utc_now,
        random_value=lambda: 0.5,
        wait_override=clock.wait,
    )
    return monitor, clock, factory


def test_connected_stream_uses_six_public_streams_no_credentials_and_stops():
    monitor, _, factory = monitor_fixture()
    result = asyncio.run(monitor.run(5))
    assert result["success"] and result["live_status"] == "LIVE_PASS"
    assert result["normal_shutdown"] and result["final_healthy"]
    assert result["connection"] == "STOPPED" and result["health"] == "NOT_HEALTHY"
    assert result["connection_opens"] == result["disconnects"] == 1
    assert result["invalid_messages"] == result["reconnect_count"] == 0
    assert all(s["price_messages"] and s["candle_messages"] for s in result["symbols"].values())
    url, options = factory.calls[0]
    assert url == ws.StreamConfig().url
    assert len(url.split("streams=")[1].split("/")) == 6
    assert "additional_headers" not in options and "signature" not in url
    assert options["ping_interval"] is None
    assert options["max_queue"] == 16 and options["max_size"] == 65536
    assert all(socket.closed for socket in factory.sockets)


def test_library_pongs_with_identical_server_ping_payload_without_client_ping():
    client = Protocol(Side.CLIENT, state=OPEN)
    client.receive_data(Frame(Opcode.PING, b"binance-ping").serialize(mask=False))
    server = Protocol(Side.SERVER, state=OPEN)
    for frame in client.data_to_send():
        server.receive_data(frame)
    frames = server.events_received()
    assert len(frames) == 1
    assert frames[0].opcode == Opcode.PONG and frames[0].data == b"binance-ping"


def test_network_error_then_normal_server_close_reconnect_with_backoff():
    monitor, clock, factory = monitor_fixture()
    factory.sessions.extend(
        [
            FakeSocket(clock, [OSError("sensitive error content")]),
            FakeSocket(clock, [ConnectionClosedOK(None, None)]),
        ]
    )
    result = asyncio.run(monitor.run(10))
    assert result["success"] and result["reconnect_count"] == 2
    assert result["connection_errors"] == 1
    assert clock.delays == [1, 2]
    assert all(socket.closed for socket in factory.sockets)


def test_server_shutdown_and_planned_rotation_reconnect():
    monitor, clock, factory = monitor_fixture(ws.StreamConfig(max_connection_age=4))
    factory.sessions.append(FakeSocket(clock, [json.dumps({"e": "serverShutdown", "E": START})]))
    result = asyncio.run(monitor.run(10))
    assert result["success"]
    assert result["reconnect_count"] >= 2
    assert result["connection_errors"] == 0


def test_backoff_exponential_jitter_cap_and_reset():
    backoff = ws.Backoff(random_value=lambda: 0.5)
    assert [backoff.next_delay() for _ in range(10)] == [1, 2, 4, 8, 16, 32, 60, 60, 60, 60]
    backoff.reset()
    assert backoff.next_delay() == 1
    assert ws.Backoff(random_value=lambda: 0).next_delay() == 1
    jittered = ws.Backoff(random_value=lambda: 1)
    jittered.next_delay()
    assert jittered.next_delay() == 2.5


def test_stable_connection_resets_backoff_on_disconnect():
    monitor, clock, factory = monitor_fixture(ws.StreamConfig(stable_reset_after=2))
    monitor.backoff.attempt = 4
    successful = FakeSocket(clock)
    original = successful.recv

    async def receive():
        if clock.now > 3:
            raise OSError("disconnect")
        return await original()

    successful.recv = receive
    factory.sessions.append(successful)
    result = asyncio.run(monitor.run(8))
    assert result["success"] and result["reconnect_count"] == 1
    assert clock.delays == [1]


def test_stale_connection_reconnects_and_does_not_fabricate_data():
    monitor, clock, factory = monitor_fixture(ws.StreamConfig(stale_reconnect_after=3))
    factory.sessions.append(FakeSocket(clock, idle=True))
    result = asyncio.run(monitor.run(9))
    assert result["reconnect_count"] == 1 and result["success"]
    assert result["closed_candles"] == 0


def test_invalid_message_is_counted_without_logging_payload(caplog):
    monitor, clock, factory = monitor_fixture()
    factory.sessions.append(FakeSocket(clock, ['{"bad":"must-not-log-this"}']))
    result = asyncio.run(monitor.run(5))
    assert result["invalid_messages"] == 1 and result["success"]
    assert "must-not-log-this" not in caplog.text


class AccessError(Exception):
    def __init__(self, status):
        self.response = SimpleNamespace(status_code=status)
        super().__init__("secret header body or proxy URL")


@pytest.mark.parametrize("status", [301, 403, 451, 501])
def test_environment_restriction_is_not_reported_as_success(status, caplog):
    monitor, _, factory = monitor_fixture(sessions=[AccessError(status)])
    result = asyncio.run(monitor.run(120))
    assert not result["success"] and result["live_status"] == "BLOCKED_ENVIRONMENT"
    assert result["http_status"] == status and result["valid_messages"] == 0
    assert len(factory.calls) == 1
    assert "secret header" not in caplog.text


def test_queue_overflow_fails_closed():
    monitor, clock, factory = monitor_fixture(ws.StreamConfig(closed_queue_size=1))
    factory.sessions.append(
        FakeSocket(
            clock,
            [
                json.dumps(candle_payload(closed=True)),
                json.dumps(candle_payload("ETHUSDT", closed=True)),
            ],
        )
    )
    result = asyncio.run(monitor.run(120))
    assert not result["success"] and result["live_status"] == "FAILED_VALIDATION"
    assert result["queue_overflows"] == 1 and result["data_loss"]
    assert result["queue_depth"] == 1
    assert result["error_category"] == "closed_candle_queue_overflow"


def test_stop_during_backoff_is_responsive():
    monitor, clock, factory = monitor_fixture()
    factory.sessions.append(FakeSocket(clock, [OSError("down")]))
    stop = asyncio.Event()

    async def wait(delay):
        stop.set()
        await clock.wait(delay)

    monitor.wait_override = wait
    result = asyncio.run(monitor.run(120, stop=stop))
    assert result["normal_shutdown"] and result["connection"] == "STOPPED"
    assert len(factory.calls) == 1 and not result["success"]


def test_cancellation_closes_connection_and_reporter():
    async def scenario():
        monitor, clock, factory = monitor_fixture()
        factory.sessions.append(FakeSocket(clock, blocking=True))
        task = asyncio.create_task(monitor.run(120))
        for _ in range(5):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert monitor.health.state == ConnectionState.STOPPED
        assert all(socket.closed for socket in factory.sockets)
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

    asyncio.run(scenario())


def test_summary_consumer_failure_stops_without_exception_contents(caplog):
    monitor, _, _ = monitor_fixture()

    def bad_consumer(_):
        raise ValueError("sensitive content")

    result = asyncio.run(monitor.run(120, on_summary=bad_consumer))
    assert not result["success"]
    assert result["error_category"] == "summary_consumer_failure"
    assert "sensitive content" not in caplog.text


@pytest.mark.parametrize(
    "base",
    [
        "wss://example.com",
        "ws://data-stream.binance.vision",
        "wss://data-stream.binance.vision:443",
        "wss://user:password@stream.binance.com",
        "wss://stream.binance.com/path",
    ],
)
def test_only_exact_official_servers_allowed(base):
    with pytest.raises(ValueError):
        ws.StreamConfig(base_url=base)


def test_redirects_are_never_followed():
    connector = PublicConnect.__new__(PublicConnect)
    error = AccessError(301)
    assert connector.process_redirect(error) is error


@pytest.mark.parametrize("duration", [0, -1, float("inf"), float("nan")])
def test_invalid_duration_rejected(duration):
    monitor, _, factory = monitor_fixture()
    with pytest.raises(ValueError):
        asyncio.run(monitor.run(duration))
    assert not factory.calls


def test_stream_cli_skips_config_and_credentials_and_writes_safe_report(
    monkeypatch,
    tmp_path,
    capsys,
):
    from trading_system import cli

    key, secret = "unit-test-only-api-key", "unit-test-only-api-secret"
    monkeypatch.setenv("BINANCE_API_KEY", key)
    monkeypatch.setenv("BINANCE_API_SECRET", secret)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("BINANCE_API_KEY=dotenv-must-not-read\n")

    def forbidden_config(*args, **kwargs):
        pytest.fail("stream must not load account configuration")

    monkeypatch.setattr(cli, "load_config", forbidden_config)
    monitor, _, factory = monitor_fixture()
    monkeypatch.setattr(ws, "WebSocketMonitor", lambda config: monitor)
    report = tmp_path / "public-summary.json"
    assert cli.main(["stream", "--duration", "5", "--report-file", str(report)]) == 0
    output = capsys.readouterr()
    text = output.out + output.err + (tmp_path / "logs/app.log").read_text() + report.read_text()
    assert "LIVE_PASS" in text and json.loads(report.read_text())["success"]
    assert all(value not in text for value in (key, secret, "dotenv-must-not-read"))
    assert "X-MBX-APIKEY" not in text and "signature=" not in text
    assert logging.getLogger("websockets.client").disabled
    assert all("additional_headers" not in opts for _, opts in factory.calls)


def test_cli_refuses_to_overwrite_existing_report(monkeypatch, tmp_path):
    monitor, _, _ = monitor_fixture()
    monkeypatch.setattr(ws, "WebSocketMonitor", lambda config: monitor)
    report = tmp_path / "existing.json"
    report.write_text("original evidence")
    assert ws.run_stream_cli(5, ws.WS_BASE_URLS[0], str(report)) == 2
    assert report.read_text() == "original evidence"
