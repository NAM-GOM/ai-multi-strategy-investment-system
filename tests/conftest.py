import logging

import httpx
import pytest

from trading_system.binance.client import BinanceClient
from trading_system.config import Config


def pytest_addoption(parser):
    parser.addoption("--live-public", action="store_true", help="Run real public Binance checks")
    parser.addoption("--live-account", action="store_true", help="Run real read-only account check")


@pytest.fixture(autouse=True)
def protect_unit_tests(request, monkeypatch):
    if not request.node.get_closest_marker("integration"):

        def no_network(*args, **kwargs):
            pytest.fail("Unit tests must use MockTransport, not real HTTP")

        monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    yield
    logger = logging.getLogger("trading_system")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = True


@pytest.fixture
def client_factory():
    clients = []

    def make(handler, config=None):
        client = BinanceClient(config or Config(), transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


@pytest.fixture
def candle_rows():
    return [
        [
            1_700_000_000_000 + index * 14_400_000,
            "100.10",
            "110.00",
            "90.00",
            "105.20",
            "12.30",
            1_700_000_000_000 + (index + 1) * 14_400_000 - 1,
            "0",
            1,
            "0",
            "0",
            "0",
        ]
        for index in range(10)
    ]


@pytest.fixture
def book_data():
    return {
        "lastUpdateId": 123,
        "bids": [[str(100 - i), "1.20"] for i in range(10)],
        "asks": [[str(101 + i), "2.30"] for i in range(10)],
    }
