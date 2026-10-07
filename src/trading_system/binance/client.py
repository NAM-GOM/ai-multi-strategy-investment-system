"""Small GET-only REST client. Errors/logs never expose URLs, headers or payloads."""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.parse import urlencode

import httpx

from trading_system.config import ACCOUNT_BASE_URL, Config

logger = logging.getLogger("trading_system.binance")
PUBLIC_ENDPOINTS = frozenset(
    {
        "/api/v3/ticker/price",
        "/api/v3/klines",
        "/api/v3/depth",
        "/api/v3/time",
    }
)
ACCOUNT_ENDPOINT = "/api/v3/account"


def generate_signature(query_string: str, secret: str) -> str:
    """HMAC SHA-256 of the exact URL-encoded query sent to Binance."""
    return hmac.new(
        secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class BinanceError(RuntimeError):
    def __init__(
        self,
        kind: str,
        endpoint: str,
        *,
        status: int | None = None,
        code: int | None = None,
        latency_ms: float | None = None,
    ) -> None:
        self.kind = kind
        self.endpoint = endpoint
        self.status = status
        self.code = code
        self.latency_ms = latency_ms
        # Do not include Binance's msg: remote responses may echo sensitive input.
        details = f"{kind} endpoint={endpoint}"
        if status is not None:
            details += f" HTTP={status}"
        if code is not None:
            details += f" BinanceCode={code}"
        super().__init__(details)


@dataclass(frozen=True)
class RestResponse:
    data: Any
    latency_ms: float


def _error_kind(status: int, code: int | None) -> str:
    if status == 418:
        return "ip_ban"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "http_5xx"
    return {
        -1121: "invalid_symbol",
        -2014: "invalid_api_key",
        -2015: "invalid_api_key_or_permissions",
        -1022: "invalid_signature",
        -1021: "timestamp_synchronization",
        -1003: "rate_limit",
        -1002: "authentication_failure",
    }.get(code, "binance_api_error" if code is not None else "http_4xx")


class BinanceClient:
    def __init__(self, config: Config, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        # HTTPX INFO messages include the entire signed URL. Disable them even when
        # this client is used directly without the CLI's logging initialization.
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).disabled = True
            logging.getLogger(name).setLevel(logging.WARNING)
        self._http = httpx.Client(
            timeout=config.timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def __enter__(self) -> BinanceClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def get(
        self,
        endpoint: str,
        params: dict[str, str | int] | None = None,
        *,
        signed: bool = False,
    ) -> RestResponse:
        if signed:
            if endpoint != ACCOUNT_ENDPOINT:
                raise ValueError("Only read-only account authentication is supported.")
            if not self.config.has_credentials:
                raise BinanceError("missing_credentials", endpoint)
        elif endpoint not in PUBLIC_ENDPOINTS:
            raise ValueError("Unsupported read-only public endpoint.")

        request_params = dict(params or {})
        headers: dict[str, str] = {}
        base_url = self.config.public_base_url
        if signed:
            # Use Binance server time plus monotonic elapsed time instead of local wall clock.
            # This also avoids a stale timestamp if the host clock is skewed.
            before = perf_counter()
            server = self.get("/api/v3/time")
            after = perf_counter()
            try:
                server_ms = server.data["serverTime"]
                if type(server_ms) is not int or server_ms <= 0:
                    raise ValueError
            except KeyError, TypeError, ValueError:
                raise BinanceError("invalid_response", "/api/v3/time") from None
            request_params["recvWindow"] = self.config.recv_window_ms
            request_params["timestamp"] = server_ms + int((after - before) * 500)
            headers["X-MBX-APIKEY"] = self.config.api_key
            base_url = ACCOUNT_BASE_URL

        query = urlencode(request_params)
        if signed:
            query += "&signature=" + generate_signature(query, self.config.api_secret)
        # Latency is application round-trip time, including reading the response body.
        # It excludes time synchronization and is NOT exchange matching latency.
        started = perf_counter()
        status: int | None = None
        code: int | None = None
        kind: str | None = None
        data: Any = None
        try:
            response = self._http.get(f"{base_url}{endpoint}", params=query, headers=headers)
            status = response.status_code
            try:
                data = response.json()
            except ValueError:
                kind = "invalid_response" if status < 400 else _error_kind(status, None)
            if isinstance(data, dict) and type(data.get("code")) is int and data["code"] < 0:
                code = data["code"]
                kind = _error_kind(status, code)
            elif status >= 400:
                kind = _error_kind(status, None)
            elif 300 <= status < 400:
                kind = "http_redirect_rejected"
        except httpx.TimeoutException:
            kind = "network_timeout"
        except httpx.RequestError:
            # DNS failures and TCP/TLS/proxy errors are transport connection errors.
            kind = "connection_error"
        latency_ms = (perf_counter() - started) * 1000
        # Only allowlisted symbols are written to logs; never log arbitrary params.
        symbol = request_params.get("symbol")
        symbol_label = symbol if symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT") else "-"
        if kind:
            error = BinanceError(kind, endpoint, status=status, code=code, latency_ms=latency_ms)
            logger.error(
                "request failure symbol=%s latency_ms=%.3f exception=%s",
                symbol_label,
                latency_ms,
                error,
            )
            raise error from None
        logger.info(
            "request success endpoint=%s symbol=%s latency_ms=%.3f",
            endpoint,
            symbol_label,
            latency_ms,
        )
        return RestResponse(data, latency_ms)
