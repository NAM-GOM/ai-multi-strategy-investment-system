import httpx
import pytest

from trading_system.binance.account import AccountAPI
from trading_system.binance.client import BinanceError
from trading_system.config import Config


@pytest.mark.parametrize(
    "status,code,kind",
    [
        (400, None, "http_4xx"),
        (503, None, "http_5xx"),
        (500, -1000, "http_5xx"),
        (429, -1003, "rate_limit"),
        (418, -1003, "ip_ban"),
        (400, -1121, "invalid_symbol"),
        (400, -2014, "invalid_api_key"),
        (401, -2015, "invalid_api_key_or_permissions"),
        (400, -1022, "invalid_signature"),
        (400, -1021, "timestamp_synchronization"),
        (200, -9999, "binance_api_error"),
    ],
)
def test_http_and_binance_errors_no_retry_or_remote_message(
    client_factory, caplog, status, code, kind
):
    calls = []
    caplog.set_level("INFO", logger="trading_system")

    def handler(request):
        calls.append(request)
        payload = {"msg": "do-not-log-this-remote-input"}
        if code is not None:
            payload["code"] = code
        return httpx.Response(status, json=payload)

    client = client_factory(handler)
    with pytest.raises(BinanceError) as caught:
        client.get("/api/v3/depth", {"symbol": "BTCUSDT"})
    assert caught.value.kind == kind
    assert caught.value.status == status
    assert caught.value.code == code
    assert caught.value.latency_ms >= 0
    assert len(calls) == 1
    assert "latency_ms=" in caplog.text
    assert "request failure" in caplog.text
    assert "do-not-log-this-remote-input" not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "exception,kind",
    [
        (httpx.ReadTimeout, "network_timeout"),
        (httpx.ConnectTimeout, "network_timeout"),
        (httpx.ConnectError, "connection_error"),
        (httpx.ProxyError, "connection_error"),
    ],
)
def test_transport_errors_are_sanitized(client_factory, caplog, exception, kind):
    def handler(request):
        raise exception("sensitive-url-or-header", request=request)

    with pytest.raises(BinanceError) as caught:
        client_factory(handler).get("/api/v3/depth")
    assert caught.value.kind == kind
    assert caught.value.latency_ms >= 0
    assert "sensitive-url-or-header" not in str(caught.value) + caplog.text


@pytest.mark.parametrize(
    "status,kind",
    [(200, "invalid_response"), (503, "http_5xx"), (429, "rate_limit"), (418, "ip_ban")],
)
def test_non_json_errors(client_factory, status, kind):
    client = client_factory(lambda _: httpx.Response(status, text="untrusted body"))
    with pytest.raises(BinanceError) as caught:
        client.get("/api/v3/depth")
    assert caught.value.kind == kind


def test_redirect_not_followed_or_signed_credential_leaked(client_factory):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        return httpx.Response(302, headers={"location": "https://untrusted.example"})

    client = client_factory(handler, Config(api_key="test-only-key", api_secret="test-only-secret"))
    with pytest.raises(BinanceError, match="http_redirect_rejected"):
        AccountAPI(client).balances()
    assert len(calls) == 2


def test_endpoint_allowlist_rejects_other_paths_before_http(client_factory):
    def handler(_):
        pytest.fail("Disallowed paths cannot be requested")

    client = client_factory(handler, Config(api_key="test-only-key", api_secret="test-only-secret"))
    with pytest.raises(ValueError):
        client.get("/unsupported")
    with pytest.raises(ValueError):
        client.get("/unsupported", signed=True)


def test_failed_authentication_safe_log(client_factory, caplog):
    caplog.set_level("INFO", logger="trading_system")

    def handler(request):
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        return httpx.Response(400, json={"code": -1022, "msg": "test-only-secret"})

    client = client_factory(handler, Config(api_key="test-only-key", api_secret="test-only-secret"))
    with pytest.raises(BinanceError, match="invalid_signature"):
        AccountAPI(client).balances()
    assert "account authentication failure" in caplog.text
    assert "test-only-secret" not in caplog.text
