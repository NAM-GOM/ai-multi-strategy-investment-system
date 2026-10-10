"""Reuse the exact REST allowlist and validate responses before engine consumption."""

import asyncio
import json
import os
import ssl
from time import time

from websockets.asyncio.client import connect as TestnetConnect

from trading_system.testnet.client import SYMBOLS, TestnetError
from trading_system.testnet.client import TestnetExecutionClient as IsolatedClient
from trading_system.testnet.risk import dec

from .models import Balance, ExchangeOrder, Quote


class FixedTestnetConnect(TestnetConnect):
    def process_redirect(self, exc):
        return TestnetError("REDIRECT_REJECTED")


class TestnetExecutionClient(IsolatedClient):
    __test__ = False

    def __init__(self, config, *, transport=None):
        super().__init__(config, transport=transport)
        self._execution_send_guard = None
        self._http.event_hooks["request"].append(self._send_boundary)

    def _send_boundary(self, request):
        if request.method == "POST" and request.url.path in ("/api/v3/order", "/api/v3/order/test"):
            if self._execution_send_guard:
                self._execution_send_guard(request.url.params["newClientOrderId"])

    def request(self, method, path, params=None, *, confirm=False):
        if method != "GET" and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
            # Mock transports still exercise the lifecycle in normal CI without any real HTTP.
            import httpx

            if not isinstance(self._http._transport, httpx.MockTransport):
                raise TestnetError("CI_ORDER_BLOCKED")
        data = super().request(method, path, params, confirm=confirm)
        try:
            if path == "/api/v3/account":
                balances = [Balance.parse(b) for b in data["balances"]]
                if len({b.asset for b in balances}) != len(balances):
                    raise ValueError
                if type(data.get("canTrade")) is not bool or data.get("accountType") != "SPOT":
                    raise ValueError
            elif path == "/api/v3/order":
                ExchangeOrder.parse(data)
            elif path == "/api/v3/openOrders":
                for order in data:
                    ExchangeOrder.parse(order)
            elif path == "/api/v3/order/test" and data != {}:
                raise ValueError
            elif path == "/api/v3/exchangeInfo":
                if not isinstance(data["symbols"], list) or not data["symbols"]:
                    raise ValueError
                for symbol in data["symbols"]:
                    if not isinstance(symbol["filters"], list):
                        raise ValueError
            elif path == "/api/v3/myTrades":
                for fill in data:
                    if (
                        type(fill["id"]) is not int
                        or type(fill["orderId"]) is not int
                        or type(fill["time"]) is not int
                        or type(fill["isBuyer"]) is not bool
                        or not isinstance(fill["commissionAsset"], str)
                        or min(dec(fill["qty"]), dec(fill["price"]), dec(fill["quoteQty"])) <= 0
                        or dec(fill["commission"]) < 0
                    ):
                        raise ValueError
        except KeyError, TypeError, ValueError:
            raise TestnetError("INVALID_TYPED_RESPONSE") from None
        return data


async def read_quote(symbol, *, clock=None):
    """Fixed public Testnet bookTicker. Receipt age, not an invented exchange timestamp."""
    if symbol not in SYMBOLS:
        raise TestnetError("UNSUPPORTED_SYMBOL")
    clock = clock or (lambda: int(time() * 1000))
    url = "wss://stream.testnet.binance.vision/stream?streams=" + symbol.lower() + "@bookTicker"
    try:
        async with asyncio.timeout(5):
            async with FixedTestnetConnect(
                url,
                ssl=ssl.create_default_context(),
                open_timeout=5,
                max_size=4096,
                max_queue=1,
                close_timeout=1,
            ) as websocket:
                data = json.loads(await websocket.recv())
                quote = Quote.parse(data["data"], clock())
                if quote.symbol != symbol:
                    raise TestnetError("INVALID_TESTNET_QUOTE")
                return quote
    except TestnetError:
        raise
    except Exception:
        raise TestnetError("TESTNET_QUOTE_UNAVAILABLE") from None
