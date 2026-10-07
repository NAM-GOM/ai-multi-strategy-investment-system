"""Real connectivity only with explicit CLI flags. No credentials => private auto-skip."""

import io
import re
from contextlib import redirect_stderr
from decimal import Decimal

import pytest

from trading_system.binance.account import AccountAPI
from trading_system.binance.client import BinanceClient, BinanceError
from trading_system.binance.public import PublicAPI
from trading_system.config import ASSETS, SYMBOLS, load_config
from trading_system.logging_config import configure_logging

pytestmark = pytest.mark.integration


@pytest.fixture
def live_public(request):
    if not request.config.getoption("--live-public"):
        pytest.skip("Enable --live-public to make real public HTTP requests")
    with BinanceClient(load_config(include_credentials=False)) as client:
        yield PublicAPI(client)


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_live_prices(live_public, symbol):
    ticker = live_public.ticker(symbol)
    assert ticker.price > 0
    assert ticker.latency_ms >= 0


def test_live_candles(live_public):
    assert len(live_public.candles()) == 10


def test_live_order_book(live_public):
    book = live_public.order_book()
    assert len(book.bids) == len(book.asks) == 10
    assert book.best_bid > 0
    assert book.best_ask >= book.best_bid
    assert book.latency_ms >= 0


def _valid_balances(balances):
    """Boolean checks prevent pytest assertion rewriting from showing real amounts."""
    if balances is None or tuple(balance.asset for balance in balances) != ASSETS:
        return False
    return all(
        isinstance(balance.free, Decimal)
        and isinstance(balance.locked, Decimal)
        and isinstance(balance.total, Decimal)
        and balance.free.is_finite()
        and balance.locked.is_finite()
        and balance.total.is_finite()
        and balance.free >= 0
        and balance.locked >= 0
        and balance.total >= 0
        and balance.total == balance.free + balance.locked
        for balance in balances
    )


def _account_report(authentication, balances=None, error=None, *, exposure="PASS"):
    lines = ["DEV-M01 Live Account Check", f"Authentication: {authentication}"]
    for asset in ASSETS:
        status = "NOT_VERIFIED"
        if balances is not None:
            balance = next(balance for balance in balances if balance.asset == asset)
            status = "PRESENT" if balance.total > 0 else "ZERO"
        lines.append(f"{asset}: {status}")
    lines.extend(
        [
            "Private API endpoint: GET /api/v3/account",
            "Trading endpoints: NOT IMPLEMENTED",
            f"Secret exposure check: {exposure}",
        ]
    )
    if error:
        lines.append(error)
    return "\n".join(lines)


def _has_sensitive_output(text, config):
    # Never print matches. Audit both the planned summary and captured application logs.
    return (
        any(value and value in text for value in (config.api_key, config.api_secret))
        or re.search(r"(?i)\bsignature\s*=|\b[0-9a-f]{64}\b", text) is not None
        or '"balances"' in text
        or "https://" in text
        or re.search(r"(?i)X-MBX-APIKEY\s*[:=]", text) is not None
    )


def test_live_readonly_account(request, tmp_path):
    __tracebackhide__ = True
    if not request.config.getoption("--live-account"):
        pytest.skip("Enable --live-account to request real account balances")
    config = load_config()
    if not config.has_credentials:
        print(_account_report("SKIPPED", error="Private API credentials not configured."))
        pytest.skip("Private API credentials not configured. Account check skipped.")

    captured_logs = io.StringIO()
    balances = None
    error = None
    with redirect_stderr(captured_logs):
        configure_logging(
            log_file=tmp_path / "account.log",
            secrets=(config.api_key, config.api_secret),
        )
        try:
            with BinanceClient(config) as client:
                balances = AccountAPI(client).balances()
            if not _valid_balances(balances):
                error = "Error: balance_validation_failed"
        except BinanceError as exception:
            error = f"Error: {exception}"
            if exception.status == 451:
                error += (
                    "\nBinance private API is not reachable from this GitHub Actions "
                    "runner/environment."
                )
        except Exception:
            error = "Error: unexpected_account_verification_failure"

    report = _account_report("FAIL" if error else "PASS", None if error else balances, error)
    if _has_sensitive_output(captured_logs.getvalue() + report, config):
        # Discard all output if the audit fails; never reveal the offending content.
        print(_account_report("FAIL", exposure="FAIL"))
        pytest.fail("Account verification output failed the secret exposure check.", pytrace=False)
    print(report)
    if error:
        pytest.fail("Live account verification failed; see the sanitized summary.", pytrace=False)
