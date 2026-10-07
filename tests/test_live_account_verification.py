"""Mock the manual live test itself; unit CI never needs real credentials/network."""

import logging
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import test_integration as live

from trading_system.binance.account import Balance
from trading_system.config import ASSETS, Config


def request_for(enabled):
    return SimpleNamespace(config=SimpleNamespace(getoption=lambda _: enabled))


def install_client(monkeypatch, client_factory, handler):
    config = Config(api_key="test-only-key", api_secret="test-only-secret")
    monkeypatch.setattr(live, "load_config", lambda: config)
    monkeypatch.setattr(live, "BinanceClient", lambda config: client_factory(handler, config))


def test_manual_verification_outputs_statuses_without_amounts(
    monkeypatch,
    client_factory,
    tmp_path,
    capsys,
):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        assert request.url.path == "/api/v3/account"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "balances": [
                    {"asset": "USDT", "free": "12.345678901", "locked": "0"},
                    {"asset": "BTC", "free": "0", "locked": "0.0123456789"},
                    {"asset": "ETH", "free": "0", "locked": "0"},
                    # Missing SOL must be represented as zero.
                ]
            },
        )

    install_client(monkeypatch, client_factory, handler)
    live.test_live_readonly_account(request_for(True), tmp_path)
    output = capsys.readouterr()
    assert "Authentication: PASS" in output.out
    assert "USDT: PRESENT" in output.out
    assert "BTC: PRESENT" in output.out
    assert "ETH: ZERO" in output.out
    assert "SOL: ZERO" in output.out
    assert "Private API endpoint: GET /api/v3/account" in output.out
    assert "Trading endpoints: NOT IMPLEMENTED" in output.out
    assert "Secret exposure check: PASS" in output.out
    assert not output.err
    log = (tmp_path / "account.log").read_text()
    for value in (
        "12.345678901",
        "0.0123456789",
        "test-only-key",
        "test-only-secret",
        requests[-1].url.params["signature"],
        '"balances"',
        "https://",
    ):
        assert value not in output.out + log
    assert not logging.getLogger("httpx").isEnabledFor(logging.DEBUG)
    assert not logging.getLogger("httpcore").isEnabledFor(logging.DEBUG)


@pytest.mark.parametrize(
    "status,code,classification",
    [
        (400, -2014, "invalid_api_key"),
        (401, -2015, "invalid_api_key_or_permissions"),
        (400, -1022, "invalid_signature"),
        (400, -1021, "timestamp_synchronization"),
        (429, -1003, "rate_limit"),
        (418, -1003, "ip_ban"),
        (451, None, "http_4xx"),
        (400, None, "http_4xx"),
        (503, None, "http_5xx"),
    ],
)
def test_manual_verification_safe_failure_categories(
    monkeypatch,
    client_factory,
    tmp_path,
    capsys,
    status,
    code,
    classification,
):
    def handler(request):
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        payload = {"msg": "test-only-key test-only-secret do-not-print-remote-body"}
        if code is not None:
            payload["code"] = code
        return httpx.Response(status, json=payload)

    install_client(monkeypatch, client_factory, handler)
    with pytest.raises(pytest.fail.Exception):
        live.test_live_readonly_account(request_for(True), tmp_path)
    output = capsys.readouterr().out
    assert "Authentication: FAIL" in output
    assert classification in output
    assert f"HTTP={status}" in output
    assert "NOT_VERIFIED" in output
    assert "Secret exposure check: PASS" in output
    for value in ("test-only-key", "test-only-secret", "do-not-print-remote-body"):
        assert value not in output
    if status == 451:
        assert (
            "Binance private API is not reachable from this GitHub Actions runner/environment."
        ) in output


@pytest.mark.parametrize(
    "exception,classification",
    [
        (httpx.ReadTimeout, "network_timeout"),
        (httpx.ConnectError, "connection_error"),
    ],
)
def test_manual_verification_safe_transport_errors(
    monkeypatch,
    client_factory,
    tmp_path,
    capsys,
    exception,
    classification,
):
    def handler(request):
        raise exception("do-not-print-url-header-or-signature", request=request)

    install_client(monkeypatch, client_factory, handler)
    with pytest.raises(pytest.fail.Exception):
        live.test_live_readonly_account(request_for(True), tmp_path)
    output = capsys.readouterr().out
    assert classification in output
    assert "do-not-print-url-header-or-signature" not in output


def test_no_flag_cannot_load_credentials_or_call_api(monkeypatch, tmp_path):
    def unexpected():
        pytest.fail("Must skip before even reading credentials")

    monkeypatch.setattr(live, "load_config", unexpected)
    with pytest.raises(pytest.skip.Exception):
        live.test_live_readonly_account(request_for(False), tmp_path)


def test_no_secrets_skip_and_do_not_claim_pass(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(live, "load_config", lambda: Config())
    with pytest.raises(pytest.skip.Exception):
        live.test_live_readonly_account(request_for(True), tmp_path)
    output = capsys.readouterr().out
    assert "Authentication: SKIPPED" in output
    assert "Authentication: PASS" not in output
    assert "NOT_VERIFIED" in output


@pytest.mark.parametrize("value", [None, "0", Decimal("-1"), Decimal("NaN")])
def test_balance_validation_rejects_missing_non_decimal_negative_nonfinite(value):
    balances = tuple(Balance(asset, Decimal(0), Decimal(0)) for asset in ASSETS)
    if value is None:
        balances = None
    else:
        balances = (Balance("USDT", value, Decimal(0)), *balances[1:])
    assert not live._valid_balances(balances)


def test_balance_validation_requires_all_assets_and_correct_totals():
    balances = tuple(Balance(asset, Decimal(0), Decimal(0)) for asset in ASSETS)
    assert live._valid_balances(balances)
    assert not live._valid_balances(balances[:-1])
    wrong_total = SimpleNamespace(
        asset="USDT", free=Decimal(1), locked=Decimal(2), total=Decimal(9)
    )
    assert not live._valid_balances((wrong_total, *balances[1:]))


@pytest.mark.parametrize(
    "unsafe_log",
    [
        '"balances": [{"asset": "USDT", "free": "987.654321"}]',
        "https://api.binance.com/sensitive-request-url",
        "signature=" + "a" * 64,
        "X-MBX-APIKEY: unexpected-header",
    ],
)
def test_unsafe_debug_output_is_discarded_before_public_log(
    monkeypatch,
    client_factory,
    tmp_path,
    capsys,
    unsafe_log,
):
    def handler(request):
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": 1_700_000_000_000})
        logging.getLogger("trading_system").error(unsafe_log)
        return httpx.Response(200, json={"balances": []})

    install_client(monkeypatch, client_factory, handler)
    with pytest.raises(pytest.fail.Exception):
        live.test_live_readonly_account(request_for(True), tmp_path)
    output = capsys.readouterr().out
    assert "Authentication: FAIL" in output
    assert "Secret exposure check: FAIL" in output
    assert unsafe_log not in output
