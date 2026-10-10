"""Exact sandbox network policy; only dedicated Testnet credentials are read."""

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from time import monotonic
from urllib.parse import urlencode

import httpx

HOST = "https://testnet.binance.vision"
SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
PUBLIC = frozenset({("GET", "/api/v3/time"), ("GET", "/api/v3/exchangeInfo")})
ALLOWED = PUBLIC | frozenset(
    {
        ("GET", "/api/v3/account"),
        ("POST", "/api/v3/order/test"),
        ("POST", "/api/v3/order"),
        ("GET", "/api/v3/order"),
        ("GET", "/api/v3/openOrders"),
        ("GET", "/api/v3/myTrades"),
        ("DELETE", "/api/v3/order"),
    }
)


class TestnetError(RuntimeError):
    __test__ = False

    def __init__(self, kind: str, *, code: int | None = None):
        self.kind, self.code = kind, code
        super().__init__(f"{kind} code={code}")


@dataclass(frozen=True)
class TestnetConfig:
    __test__ = False
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    trading_enabled: bool = False

    @classmethod
    def from_env(cls):
        # Deliberately no dotenv, production Config, URL override, or credential fallback.
        return cls(
            os.environ.get("BINANCE_TESTNET_API_KEY", ""),
            os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
            os.environ.get("BINANCE_TESTNET_TRADING_ENABLED", "") == "YES_TESTNET_ONLY",
        )


def signature(query: str, secret: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def sandbox_policy(request: httpx.Request) -> None:
    url = request.url
    if (
        url.scheme != "https"
        or url.host != "testnet.binance.vision"
        or url.port not in (None, 443)
        or url.username
        or url.password
        or (request.method, url.path) not in ALLOWED
    ):
        raise TestnetError("NETWORK_POLICY_DENIED")


class TestnetExecutionClient:
    __test__ = False

    def __init__(self, config: TestnetConfig, *, transport: httpx.BaseTransport | None = None):
        self.config = config
        self.blocked_until = 0.0
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).disabled = True
        self._http = httpx.Client(
            verify=True,
            trust_env=False,
            follow_redirects=False,
            timeout=10,
            transport=transport,
            event_hooks={"request": [sandbox_policy]},
        )

    def close(self):
        self._http.close()

    def request(self, method: str, path: str, params=None, *, confirm: bool = False):
        if (method, path) not in ALLOWED:
            raise TestnetError("NETWORK_POLICY_DENIED")
        if monotonic() < self.blocked_until:
            raise TestnetError("RATE_LIMIT_HOLD")
        if method != "GET" and not (self.config.trading_enabled and confirm):
            raise TestnetError("DRY_RUN")
        values = dict(params or {})
        if "symbol" in values and values["symbol"] not in SYMBOLS:
            raise TestnetError("UNSUPPORTED_SYMBOL")
        if method == "POST":
            if (
                values.get("type") != "LIMIT"
                or values.get("side") not in ("BUY", "SELL")
                or values.get("timeInForce") != "GTC"
                or set(values)
                - {
                    "symbol",
                    "side",
                    "type",
                    "timeInForce",
                    "quantity",
                    "price",
                    "newClientOrderId",
                    "newOrderRespType",
                }
            ):
                raise TestnetError("UNSUPPORTED_ORDER")
        headers = {}
        if (method, path) not in PUBLIC:
            if not self.config.api_key or not self.config.api_secret:
                raise TestnetError("MISSING_TESTNET_CREDENTIALS")
            if "signature" in values or "timestamp" in values or "recvWindow" in values:
                raise TestnetError("RESERVED_PARAMETER")
            server = self.request("GET", "/api/v3/time")
            if (
                not isinstance(server, dict)
                or type(server.get("serverTime")) is not int
                or server["serverTime"] <= 0
            ):
                raise TestnetError("INVALID_SERVER_TIME")
            values.update(timestamp=server["serverTime"], recvWindow=5000)
            headers["X-MBX-APIKEY"] = self.config.api_key
        query = urlencode(values)
        if headers:
            query += "&signature=" + signature(query, self.config.api_secret)
        try:
            response = self._http.request(method, HOST + path, params=query, headers=headers)
        except httpx.RequestError:
            raise TestnetError("UNKNOWN_TRANSPORT") from None
        if response.status_code in (403, 451):
            raise TestnetError("BLOCKED_ENVIRONMENT")
        if response.status_code in (418, 429):
            try:
                delay = max(60, int(response.headers.get("Retry-After", "60")))
            except ValueError:
                delay = 60
            self.blocked_until = monotonic() + delay
            raise TestnetError("RATE_LIMIT_HOLD")
        if 300 <= response.status_code < 400:
            raise TestnetError("REDIRECT_REJECTED")
        try:
            data = response.json()
        except ValueError:
            raise TestnetError("INVALID_RESPONSE") from None
        code = data.get("code") if isinstance(data, dict) else None
        if response.status_code >= 500 or code in (-1006, -1007):
            raise TestnetError("UNKNOWN_EXECUTION", code=code)
        if response.status_code >= 400 or (isinstance(code, int) and code < 0):
            raise TestnetError("API_ERROR", code=code)
        expected = list if path in ("/api/v3/openOrders", "/api/v3/myTrades") else dict
        if not isinstance(data, expected):
            raise TestnetError("INVALID_RESPONSE")
        return data
