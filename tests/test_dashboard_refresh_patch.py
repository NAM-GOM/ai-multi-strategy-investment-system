"""Offline contract tests for a hash-bound patch; no actual NUC file or process access."""

import ast
import hashlib
import importlib.util
from pathlib import Path

import pytest


def load(name):
    path = Path(__file__).parents[1] / "ops/dashboard" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def support(tmp_path, monkeypatch):
    module = load("dashboard_refresh_support")
    monkeypatch.setattr(module, "_REFRESH_STATE", tmp_path)
    monkeypatch.setattr(
        module,
        "_REFRESH_CONTINUOUS",
        {
            "market": tmp_path / "continuous-01/market/market.sqlite",
            "observer": tmp_path / "continuous-01/observer/observer.sqlite",
        },
    )
    return module


def test_continuous_source_preferred_and_legacy_is_explicitly_labelled(support, tmp_path):
    legacy = {k: tmp_path / f"close-validation-01/{k}.sqlite" for k in ("market", "observer")}
    selected, evidence = support._continuous_refresh_select(legacy)
    assert selected == legacy
    assert {v["kind"] for v in evidence.values()} == {"LEGACY_VALIDATION_FALLBACK"}
    market = support._REFRESH_CONTINUOUS["market"]
    market.parent.mkdir(parents=True)
    market.write_bytes(b"corrupt SQLite fixture")
    selected, evidence = support._continuous_refresh_select(legacy)
    assert selected["market"] == market and evidence["market"]["kind"] == "CONTINUOUS"
    # Selection never falls back merely because the new DB content is corrupt;
    # the original read-only connect/query path reports its error instead.


def test_custom_simulated_sources_are_not_replaced(support, tmp_path):
    custom = {"market": tmp_path / "fixture.sqlite"}
    assert support._continuous_refresh_select(custom)[0] == custom


def test_snapshots_use_real_data_times_not_api_generated_time(support, monkeypatch):
    monkeypatch.setattr(support._refresh_time, "time", lambda: 1791810000)
    old = "2026-10-11T13:54:11+00:00"
    data = {
        "generatedAt": "2026-10-12T06:20:00+00:00",
        "server": {},
        "evidence": {
            "dataTimes": {"balances": old, "market": old, "observer": old},
            "notes": [],
        },
    }
    support._continuous_refresh_enrich(data, {}, False)
    assert data["evidence"]["freshness"]["balances"]["state"] == "STALE"
    assert data["evidence"]["apiHeartbeatIsDataHeartbeat"] is False
    data["evidence"]["dataTimes"]["balances"] = "2026-10-12T13:00:00+00:00"
    support._continuous_refresh_enrich(data, {}, False)
    assert data["evidence"]["freshness"]["balances"]["state"] == "FRESH"


def test_four_hour_signal_cadence_differs_from_price_and_balance_freshness(support, monkeypatch):
    monkeypatch.setattr(support._refresh_time, "time", lambda: 1791808800)
    value = "2026-10-12T06:00:00+00:00"
    data = {
        "server": {},
        "evidence": {"dataTimes": {k: value for k in ("market", "observer", "balances")}},
    }
    support._continuous_refresh_enrich(data, {}, False)
    assert data["evidence"]["freshness"]["observer"]["allowedAgeSeconds"] == 14460
    assert data["evidence"]["freshness"]["market"]["allowedAgeSeconds"] == 30


def test_stopped_service_does_not_inherit_api_online_status(support, monkeypatch):
    monkeypatch.setattr(support, "_continuous_refresh_health", lambda *args: {"state": "READY"})
    data = {
        "server": {"status": "online"},
        "services": {
            "crypto-market-collector.service": "inactive",
            "crypto-strategy-observer.service": "failed",
        },
        "evidence": {"dataTimes": {}},
    }
    support._continuous_refresh_enrich(data, {}, True)
    assert data["server"]["status"] == "online"
    assert data["server"]["collector"] == data["server"]["observer"] == "STOPPED"


def test_stale_or_malformed_health_is_not_ready(support, tmp_path):
    path = tmp_path / "continuous-01/market/health.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"role":"collector","state":"READY","timestamp_ms":0}')
    assert support._continuous_refresh_health("collector", 1791810000)["state"] == "UNKNOWN"
    path.write_text("not json")
    assert support._continuous_refresh_health("collector", 1791810000)["state"] == "UNKNOWN"


def stub_source():
    return b"""import json
import time
from datetime import datetime, timezone
from pathlib import Path
STATE = Path('/var/lib/CryptoAutoTrading/state')
DATABASES = {}
SYMBOLS = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT'}
ALLOWED_SERVICES = ('nuc-dashboard-api.service',)
def snapshot(databases=DATABASES, include_host=True):
    data = {'server': {}, 'evidence': {'dataTimes': {}}}
    for name in databases:
        if name == 'market':
            try:
                db = None
                __LATEST_PRICE_QUERY__
            finally:
                pass
    return data
""".replace(
        b"__LATEST_PRICE_QUERY__",
        (
            b"last = rows(db, 'SELECT symbol,price_text,event_time_ms,received_at_ms "
            b"FROM price_snapshots '\n"
            b"                            'WHERE (symbol,bucket_start_ms) IN '\n"
            b"                            '(SELECT symbol,MAX(bucket_start_ms) "
            b"FROM price_snapshots GROUP BY symbol)')"
        ),
    )


def test_patch_compiles_preserves_original_and_adds_only_read_only_sources():
    patch = load("apply_refresh_patch")
    original = stub_source()
    updated = patch.render_patch(original, expected_sha=hashlib.sha256(original).hexdigest())
    tree = ast.parse(updated)
    assert original == stub_source()
    assert "GROUP BY symbol" not in updated.decode()
    assert "ORDER BY bucket_start_ms DESC LIMIT 1" in updated.decode()
    assert b"crypto-testnet-account-sync.service" in updated
    functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert "snapshot" in functions and "_continuous_refresh_select" in functions
    namespace = {}
    exec(compile(updated, "SIMULATED_TEST_dashboard.py", "exec"), namespace)
    result = namespace["snapshot"](databases={}, include_host=False)
    assert result["evidence"]["apiHeartbeatIsDataHeartbeat"] is False
    with pytest.raises(ValueError, match="differs from reviewed"):
        patch.render_patch(original)


def test_support_cannot_submit_exchange_requests_or_control_services():
    text = (Path(__file__).parents[1] / "ops/dashboard/dashboard_refresh_support.py").read_text()
    assert not any(
        v in text for v in ("api_key", "api_secret", "httpx", "requests.", "subprocess", "sudo")
    )


def account_fixture(support, tmp_path, **overrides):
    import json

    snapshot = {
        "schemaVersion": 1,
        "mode": "READ_ONLY_TESTNET_ACCOUNT_SYNC",
        "execution_enabled": False,
        "real_journal_modified": False,
        "account_session_id": "existing-session",
        "balance_timestamp_ms": 1791810000000,
        "balances": [
            {
                "asset": "USDT",
                "free": "9992.52175960",
                "locked": "0",
                "time": "2026-10-12T13:00:00+00:00",
            }
        ],
    }
    snapshot.update(overrides)
    target = tmp_path / "continuous-01/account/latest-account.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(snapshot))
    return {
        "session": {"id": "existing-session"},
        "account": {"equity": 1},
        "balances": [{"asset": "OLD"}],
        "evidence": {"dataTimes": {"balances": "2026-10-11T13:54:11+00:00"}},
    }


def test_get_snapshot_refreshes_balances_without_inventing_valuation(support, tmp_path):
    data = account_fixture(support, tmp_path)
    support._continuous_refresh_account(data, 1791810001)
    assert data["balances"][0]["asset"] == "USDT"
    assert data["account"]["equity"] is None
    assert data["evidence"]["balancesKnown"] is True
    assert data["evidence"]["orderDataSource"] == "E01_JOURNAL_RECORDED_HISTORY"


@pytest.mark.parametrize(
    "override",
    [
        {"account_session_id": "reset-session"},
        {"balance_timestamp_ms": 1791819999999},
        {"execution_enabled": True},
        {"real_journal_modified": True},
        {
            "balances": [
                {"asset": "USDT", "free": "NaN", "locked": "0", "time": "2026-10-12T13:00:00+00:00"}
            ]
        },
    ],
)
def test_bad_account_snapshot_never_presents_old_balances_as_current(support, tmp_path, override):
    data = account_fixture(support, tmp_path, **override)
    support._continuous_refresh_account(data, 1791810001)
    assert data["balances"] == []
    assert data["evidence"]["balancesKnown"] is False
    assert data["evidence"]["accountDataSource"] == "ACCOUNT_SNAPSHOT_INVALID"
