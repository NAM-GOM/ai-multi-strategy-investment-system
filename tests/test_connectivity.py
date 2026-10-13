import httpx
import pytest

from trading_system.binance import connectivity
from trading_system.binance.client import BinanceError


def install_probe(monkeypatch, client_factory, handler):
    def make(config):
        assert not config.has_credentials
        assert config.public_base_url == "https://api.binance.com"
        return client_factory(handler, config)

    monkeypatch.setattr(connectivity, "BinanceClient", make)


def test_probe_uses_no_credentials_even_when_environment_is_set(
    monkeypatch,
    client_factory,
    capsys,
):
    monkeypatch.setenv("BINANCE_API_KEY", "test-only-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "test-only-secret")

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v3/time"
        assert "X-MBX-APIKEY" not in request.headers
        assert "signature" not in request.url.params
        return httpx.Response(200, json={"serverTime": 1_700_000_000_000})

    install_probe(monkeypatch, client_factory, handler)
    assert connectivity.main() == 0
    output = capsys.readouterr().out
    assert "Account host connectivity: PASS" in output
    assert "Authentication: NOT_TESTED" in output
    assert "test-only-key" not in output
    assert "test-only-secret" not in output


@pytest.mark.parametrize(
    "message,reason",
    [
        (
            "Service unavailable from a restricted location according to eligibility terms.",
            "restricted_location",
        ),
        ("untrusted error text", "unspecified_451"),
    ],
)
def test_451_reason_is_classified_without_echoing_response(
    monkeypatch,
    client_factory,
    capsys,
    message,
    reason,
):
    install_probe(
        monkeypatch,
        client_factory,
        lambda _: httpx.Response(
            451,
            json={"code": 0, "msg": message + " test-only-secret"},
        ),
    )
    assert connectivity.main() == 1
    output = capsys.readouterr().out
    assert "HTTP=451" in output
    assert f"Access restriction reason: {reason}" in output
    assert message not in output
    assert "test-only-secret" not in output


@pytest.mark.parametrize(
    "status,payload,kind",
    [
        (200, {}, "invalid_response"),
        (200, {"serverTime": "123"}, "invalid_response"),
        (429, {"code": -1003}, "rate_limit"),
        (500, {}, "http_5xx"),
    ],
)
def test_probe_failures_do_not_allow_live_verification(
    monkeypatch,
    client_factory,
    capsys,
    status,
    payload,
    kind,
):
    install_probe(monkeypatch, client_factory, lambda _: httpx.Response(status, json=payload))
    assert connectivity.main() == 1
    assert kind in capsys.readouterr().out


def test_non_451_errors_have_no_restriction_reason(client_factory):
    client = client_factory(lambda _: httpx.Response(401, json={"code": -2015}))
    with pytest.raises(BinanceError) as caught:
        client.get("/api/v3/time")
    assert caught.value.restriction_reason is None
    assert caught.value.kind == "invalid_api_key_or_permissions"
