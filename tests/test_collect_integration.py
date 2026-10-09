"""Only --live-collect enables real public REST/WS; no private API is involved."""

import asyncio

import pytest

from trading_system.persistence.collector import Collector
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.repository import MarketRepository

pytestmark = pytest.mark.integration


def test_live_sqlite_collection(request, tmp_path):
    if not request.config.getoption("--live-collect"):
        pytest.skip("Enable --live-collect for a real 120s SQLite/public collection")
    path = tmp_path / "live.sqlite"
    result = asyncio.run(Collector(PersistenceConfig(db_path=path)).run(120))
    if result["status"] != "COMPLETED":
        pytest.fail(
            f"Collection status={result['status']} category={result['error_category']}",
            pytrace=False,
        )
    with MarketRepository(path) as repository:
        assert repository.integrity()
        assert repository.verify()["data_status"] == "COMPLETE"
        assert all(repository.recent_prices(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
