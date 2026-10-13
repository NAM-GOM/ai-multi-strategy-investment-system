"""MockTransport checks REST boundaries, pagination, failure and durable gap resolution."""

from dataclasses import replace

import httpx
import pytest
from test_market_data import START

from trading_system.binance.client import BinanceError
from trading_system.binance.public import PublicAPI
from trading_system.config import SYMBOLS
from trading_system.persistence.config import PersistenceConfig
from trading_system.persistence.records import INTERVAL_MS
from trading_system.persistence.recovery import Backfill
from trading_system.persistence.repository import MarketRepository
from trading_system.persistence.store import MarketStore

SERVER = START + INTERVAL_MS


def row(start):
    return [
        start,
        "100.10",
        "110.20",
        "90.30",
        "105.40",
        "0.0000000000123456789",
        start + INTERVAL_MS - 1,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


class ResponseHandler:
    def __init__(self, server=SERVER):
        self.server = server
        self.calls = []
        self.transform = lambda request, rows: rows

    def __call__(self, request):
        self.calls.append(request)
        assert request.method == "GET" and "X-MBX-APIKEY" not in request.headers
        assert "signature" not in request.url.params
        assert request.url.host == "data-api.binance.vision"
        if request.url.path == "/api/v3/time":
            return httpx.Response(200, json={"serverTime": self.server})
        start, end = int(request.url.params["startTime"]), int(request.url.params["endTime"])
        limit = int(request.url.params["limit"])
        rows = [row(t) for t in range(start, end + 1, INTERVAL_MS)][:limit]
        return httpx.Response(200, json=self.transform(request, rows))


def backfill(store, client_factory, handler, *, days=7, **options):
    config = PersistenceConfig(db_path=store.path, bootstrap_days=days, **options)
    public = PublicAPI(client_factory(handler))
    return Backfill(store, public, config, sleep=lambda delay: None, monotonic=lambda: 0)


def test_bootstrap_seven_days_42_closed_per_symbol_then_restart_preserves_source(
    tmp_path,
    client_factory,
):
    path = tmp_path / "bootstrap.sqlite"
    handler = ResponseHandler()
    with MarketStore(path) as store:
        result = backfill(store, client_factory, handler).run()
        assert result["data_status"] == "COMPLETE" and result["candles_written"] == 126
        assert result["gaps_resolved"] == 3 and result["rest_requests"] == 4
    handler.server += INTERVAL_MS
    with MarketStore(path) as store:
        result = backfill(store, client_factory, handler).run()
        assert result["data_status"] == "COMPLETE"
        assert result["candles_written"] == 3 and result["duplicate_candles"] >= 3
    with MarketRepository(path) as repository:
        assert repository.verify(handler.server)["data_status"] == "COMPLETE"
        for symbol in SYMBOLS:
            candles = repository.candles(symbol, 0, handler.server)
            assert len(candles) == 43
            assert candles[0].source == "REST_BOOTSTRAP"
            assert candles[-1].source == "REST_RECOVERY"
            assert all(c.event_time_ms is None for c in candles)


def test_internal_gap_and_bootstrap_ws_overlap_resolved_only_after_rest_compare(
    tmp_path,
    client_factory,
):
    path = tmp_path / "gap.sqlite"
    handler = ResponseHandler()
    with MarketStore(path) as store:
        backfill(store, client_factory, handler, days=1).run()
        start = START - 2 * INTERVAL_MS
        original = store.connection.execute(
            "SELECT * FROM candles_4h WHERE symbol='BTCUSDT' AND open_time_ms=?",
            (start,),
        ).fetchone()
        from trading_system.persistence.records import candle_from_row

        ws_duplicate = replace(
            candle_from_row(original), source="WS_LIVE", event_time_ms=start + INTERVAL_MS
        )
        assert store.write_batch(candles=[ws_duplicate])["duplicate_candles"] == 1
        with store.transaction():
            store.connection.execute(
                "DELETE FROM candles_4h WHERE symbol='BTCUSDT' AND open_time_ms=?", (start,)
            )
        result = backfill(store, client_factory, handler, days=1).run()
        assert result["data_status"] == "COMPLETE" and result["candles_written"] == 1
        gap = store.connection.execute(
            "SELECT * FROM data_gaps WHERE start_time_ms=?", (start,)
        ).fetchone()
        assert gap["status"] == "RESOLVED" and gap["resolution_source"] == "REST_RECOVERY"
    with MarketRepository(path) as repository:
        assert repository.candles("BTCUSDT", start, start)[0].source == "REST_RECOVERY"


@pytest.mark.parametrize("case", ["missing", "unordered", "duplicate", "current", "invalid-ohlc"])
def test_incomplete_or_malformed_rest_never_resolves_gap(tmp_path, client_factory, case):
    handler = ResponseHandler()

    def transform(request, rows):
        if request.url.params["symbol"] != "BTCUSDT":
            return rows
        if case == "missing":
            return rows[:-1]
        if case == "unordered":
            return list(reversed(rows))
        if case == "duplicate":
            return rows[:-1] + [rows[0]]
        if case == "current":
            return rows[:-1] + [row(SERVER)]
        rows[0][2] = "1"
        return rows

    handler.transform = transform
    path = tmp_path / "incomplete.sqlite"
    with MarketStore(path) as store:
        result = backfill(store, client_factory, handler, days=1).run()
        assert result["data_status"] == "INCOMPLETE"
        assert result["error_category"] in ("invalid_response", "incomplete_rest_page")
        assert (
            store.connection.execute(
                "SELECT count(*) FROM candles_4h WHERE symbol='BTCUSDT'"
            ).fetchone()[0]
            == 0
        )
    with MarketRepository(path) as repository:
        assert any(g["status"] == "FAILED" for g in repository.gaps("BTCUSDT"))


def test_rest_conflict_does_not_change_live_provenance_or_resolve(tmp_path, client_factory):
    handler = ResponseHandler()
    path = tmp_path / "conflict.sqlite"
    with MarketStore(path) as store:
        backfill(store, client_factory, handler, days=1).run()
        from trading_system.persistence.records import candle_from_row

        existing = candle_from_row(
            store.connection.execute(
                "SELECT * FROM candles_4h WHERE symbol='BTCUSDT' "
                "ORDER BY open_time_ms DESC LIMIT 1",
            ).fetchone()
        )

        def conflicting(request, rows):
            if request.url.params["symbol"] == "BTCUSDT":
                rows[-1][4] = "104.20"
            return rows

        handler.transform = conflicting
        result = backfill(store, client_factory, handler, days=1).run()
        assert result["data_status"] == "INCOMPLETE" and result["conflicts"] == 1
    with MarketRepository(path) as repository:
        assert repository.last_candle("BTCUSDT") == existing
        assert any(g["status"] == "CONFLICT" for g in repository.gaps())


def test_paginated_bootstrap_and_bounded_budget(tmp_path, client_factory):
    handler = ResponseHandler()
    with MarketStore(tmp_path / "pages.sqlite") as store:
        result = backfill(store, client_factory, handler, days=365).run()
        assert result["data_status"] == "COMPLETE" and result["candles_written"] == 365 * 6 * 3
        assert result["rest_requests"] == 10
        assert all(
            int(r.url.params["limit"]) <= 1000 for r in handler.calls if "limit" in r.url.params
        )
    with MarketStore(tmp_path / "budget.sqlite") as store:
        result = backfill(
            store, client_factory, ResponseHandler(), days=365, max_rest_requests=2
        ).run()
        assert result["data_status"] == "INCOMPLETE"
        assert (
            result["rest_requests"] == 2 and result["error_category"] == "recovery_budget_exceeded"
        )
        assert result["candles_written"] == 1000


@pytest.mark.parametrize(
    "status,category", [(429, "rate_limit"), (418, "ip_ban"), (451, "http_4xx")]
)
def test_clock_failure_terminal_status_not_retried_or_reported_pass(
    tmp_path,
    client_factory,
    status,
    category,
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"msg": "sensitive-data-not-logged"})

    with MarketStore(tmp_path / "failed.sqlite") as store:
        result = backfill(store, client_factory, handler).run()
        assert result["data_status"] == "INCOMPLETE" and result["error_category"] == category
        assert len(calls) == 1 and result["gaps_detected"] == 3


def test_timeout_retry_has_explicit_cap_and_request_spacing(tmp_path, client_factory):
    calls, sleeps = [], []
    handler = ResponseHandler()

    def flaky(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("fixture-secret", request=request)
        return handler(request)

    with MarketStore(tmp_path / "retry.sqlite") as store:
        engine = backfill(store, client_factory, flaky, days=1)
        engine.sleep = sleeps.append
        result = engine.run()
        assert result["data_status"] == "COMPLETE" and len(calls) == 5
        assert 1 in sleeps and any(delay >= 0.25 for delay in sleeps)


def test_original_public_candles_unchanged_and_range_inputs_validated(client_factory):
    handler = ResponseHandler()
    public = PublicAPI(client_factory(handler))
    for options in (
        {"symbol": "DOGEUSDT"},
        {"symbol": "BTCUSDT", "interval": "1m"},
        {"symbol": "BTCUSDT", "limit": 1001},
    ):
        with pytest.raises((ValueError, BinanceError)):
            public.candles_range(**options, start_time_ms=START, end_time_ms=SERVER - 1)
    assert not handler.calls


def test_bootstrap_ws_connection_boundary_recovered_next_cycle(tmp_path, client_factory):
    handler = ResponseHandler(server=SERVER - 1)
    with MarketStore(tmp_path / "boundary.sqlite") as store:
        first = backfill(store, client_factory, handler, days=1).run()
        assert first["candles_written"] == 18
        handler.server = SERVER
        second = backfill(store, client_factory, handler, days=1).run()
        assert second["candles_written"] == 3 and second["gaps_resolved"] == 3
        assert second["data_status"] == "COMPLETE"
