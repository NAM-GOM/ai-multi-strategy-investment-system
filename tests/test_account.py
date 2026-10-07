from decimal import Decimal

import httpx
import pytest

from trading_system.binance.account import AccountAPI
from trading_system.binance.client import BinanceError, generate_signature
from trading_system.config import ASSETS, Config


def test_hmac_signature_rfc4231_vector():
    # Public RFC 4231 test vector, not a Binance credential.
    assert generate_signature("what do ya want for nothing?", "Jefe") == (
        "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    )


@pytest.mark.parametrize("key,secret", [("", ""), ("test-only-key", ""), ("", "test-only-secret")])
def test_missing_or_partial_credentials_skip_without_http(client_factory, key, secret, caplog):
    def handler(_):
        pytest.fail("No HTTP request permitted when credentials are missing")

    caplog.set_level("INFO", logger="trading_system")
    assert (
        AccountAPI(client_factory(handler, Config(api_key=key, api_secret=secret))).balances()
        is None
    )
    assert "authentication skipped" in caplog.text


def test_signed_readonly_account_and_balances(client_factory, monkeypatch, caplog):
    calls = []
    # A deliberately skewed local clock must not affect the signed server timestamp.
    monkeypatch.setattr("time.time", lambda: 1)
    caplog.set_level("INFO", logger="trading_system")

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        if request.url.path == "/api/v3/time":
            assert "X-MBX-APIKEY" not in request.headers
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        assert request.url.path == "/api/v3/account"
        assert request.url.host == "api.binance.com"
        assert request.headers["X-MBX-APIKEY"] == "test-only-key"
        params = request.url.params
        assert 1_700_000_000_000 <= int(params["timestamp"]) < 1_700_000_005_000
        assert params["recvWindow"] == "5000"
        raw_query = request.url.query.decode()
        query, signature = raw_query.rsplit("&signature=", 1)
        assert signature == generate_signature(query, "test-only-secret")
        return httpx.Response(
            200,
            json={
                "balances": [
                    {"asset": "USDT", "free": "12.12345678", "locked": "0.00000001"},
                    {"asset": "BTC", "free": "0", "locked": "0"},
                    {"asset": "SOL", "free": "2", "locked": "3"},
                    {"asset": "OTHER", "free": "8", "locked": "1"},
                ]
            },
        )

    config = Config(
        public_base_url="https://data-api.binance.vision",
        api_key="test-only-key",
        api_secret="test-only-secret",
    )
    balances = AccountAPI(client_factory(handler, config)).balances()
    assert len(calls) == 2
    assert tuple(balance.asset for balance in balances) == ASSETS
    assert balances[0].total == Decimal("12.12345679")
    assert balances[1].total == balances[2].total == 0
    assert balances[3].free == 2
    assert balances[3].locked == 3
    assert balances[3].total == 5
    assert "account authentication success" in caplog.text
    for sensitive in ("test-only-key", "test-only-secret", calls[1].url.params["signature"]):
        assert sensitive not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"balances": None},
        {"balances": [{"asset": "BTC", "free": "nan", "locked": "0"}]},
    ],
)
def test_invalid_balance_payload(client_factory, payload):
    def handler(request):
        return httpx.Response(
            200,
            json={"serverTime": 1_700_000_000_000}
            if request.url.path == "/api/v3/time"
            else payload,
        )

    client = client_factory(handler, Config(api_key="test-only-key", api_secret="test-only-secret"))
    with pytest.raises(BinanceError, match="invalid_response"):
        AccountAPI(client).balances()


@pytest.mark.parametrize("payload", [{}, {"serverTime": "123"}, {"serverTime": -1}])
def test_invalid_server_time_never_sends_credentials(client_factory, payload):
    def handler(request):
        assert request.url.path == "/api/v3/time"
        assert "X-MBX-APIKEY" not in request.headers
        return httpx.Response(200, json=payload)

    client = client_factory(handler, Config(api_key="test-only-key", api_secret="test-only-secret"))
    with pytest.raises(BinanceError, match="invalid_response"):
        AccountAPI(client).balances()
