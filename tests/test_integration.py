"""Real connectivity only with explicit CLI flags. No credentials => private auto-skip."""

import pytest

from trading_system.binance.account import AccountAPI
from trading_system.binance.client import BinanceClient
from trading_system.binance.public import PublicAPI
from trading_system.config import ASSETS, SYMBOLS, load_config

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


def test_live_readonly_account(request):
    if not request.config.getoption("--live-account"):
        pytest.skip("Enable --live-account to request real account balances")
    config = load_config()
    if not config.has_credentials:
        pytest.skip("Private API credentials not configured. Account check skipped.")
    with BinanceClient(config) as client:
        balances = AccountAPI(client).balances()
    assert tuple(balance.asset for balance in balances) == ASSETS
    assert all(balance.total == balance.free + balance.locked for balance in balances)
