"""Offline Frozen reproduction and real SQLite failure/restart tests."""

import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from trading_system.cli import main
from trading_system.config import SYMBOLS
from trading_system.observer.adapter import StrategyAdapter
from trading_system.observer.audit import historical_frames, reproduction_gate, source_audit
from trading_system.observer.gate import history_hash
from trading_system.observer.model import (
    FREEZE_MS,
    STRATEGIES,
    ObserverError,
    ObserverState,
    classify,
)
from trading_system.observer.service import BatchProcessor
from trading_system.observer.store import ObserverStore
from trading_system.persistence.records import INTERVAL_MS, CandleRecord
from trading_system.persistence.repository import MarketRepository
from trading_system.persistence.store import MarketStore


@pytest.fixture(scope="module")
def audit():
    return reproduction_gate()


@pytest.fixture
def fixture(tmp_path, audit):
    market, observer = tmp_path / "market.sqlite", tmp_path / "observer.sqlite"
    with MarketStore(market):
        pass
    store = ObserverStore(observer)
    run = store.start(audit, FREEZE_MS)
    processor = BatchProcessor(market, store, audit, run, FREEZE_MS)
    yield market, store, processor
    store.close()


def forward(symbol, start=FREEZE_MS, source="WS_LIVE"):
    close = start + INTERVAL_MS - 1
    return CandleRecord(
        symbol,
        "4h",
        start,
        close,
        Decimal(100),
        Decimal(110),
        Decimal(90),
        Decimal(102),
        Decimal(50),
        close + 10 if source == "WS_LIVE" else None,
        close + 20,
        source,
    )


def add(market, symbols=SYMBOLS, start=FREEZE_MS, source="WS_LIVE"):
    with MarketStore(market) as writer:
        writer.write_batch(candles=[forward(s, start, source) for s in symbols])


def decisions(store):
    return [json.loads(r[0]) for r in store.db.execute("SELECT record FROM signal_decisions")]


def test_w03_nine_combinations_exact_original_ledger_equity(audit):
    assert audit["verification_status"] == "W03_REPRODUCTION_PASS"
    assert len(audit["combinations"]) == 9
    assert all(c["matched"] for c in audit["checks"])
    assert all(c["indicator_prefix_exact"] for c in audit["combinations"])
    assert {c["warmup_bars_from_frozen_source"] for c in audit["combinations"]} == {201, 56, 182}


def test_real_indicator_snapshots_nine_conditions_and_restart(fixture, audit):
    market, store, processor = fixture
    before = market.read_bytes()
    target = FREEZE_MS - INTERVAL_MS
    result = processor.evaluate(target, FREEZE_MS + 100)
    assert result["status"] == "COMMITTED" and len(decisions(store)) == 9
    assert market.read_bytes() == before
    _, frames = historical_frames()
    adapter = StrategyAdapter(audit)
    for d in decisions(store):
        original = adapter.generate(adapter.registry[d["strategy_id"]], frames[d["symbol"]]).iloc[
            -1
        ]
        snapshot = d["indicator_snapshot"]
        assert snapshot["entry_long"] == bool(original.entry_long)
        assert snapshot["exit_long"] == bool(original.exit_long)
        assert snapshot["atr"] == float(original.atr)
        assert d["observation_mode"] == "SEEN_HISTORICAL_DATA"
    # New process-equivalent Store instance, new clock, same immutable decisions.
    restarted = ObserverStore(store.path)
    try:
        run = restarted.start(audit, FREEZE_MS + 500)
        again = BatchProcessor(market, restarted, audit, run, FREEZE_MS + 500)
        assert again.evaluate(target, FREEZE_MS + 600)["status"] == "ALREADY_COMMITTED"
        assert len(decisions(restarted)) == 9
        assert len(restarted.status()["checkpoints"]) == 9
    finally:
        restarted.close()


@pytest.mark.parametrize("missing", SYMBOLS)
def test_three_symbol_barrier_blocks_all(fixture, missing):
    market, store, processor = fixture
    add(market, [s for s in SYMBOLS if s != missing])
    with pytest.raises(ObserverError, match="THREE_SYMBOL_BARRIER"):
        processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 100)
    assert not decisions(store)
    assert not store.status()["checkpoints"]
    assert processor.state == ObserverState.DATA_HOLD


@pytest.mark.parametrize(
    "source,expected",
    [
        ("REST_BOOTSTRAP", "PRELAUNCH_STATE_BACKFILL"),
        ("REST_RECOVERY", "PRELAUNCH_STATE_BACKFILL"),
        ("WS_LIVE", "LIVE_OBSERVATION"),
    ],
)
def test_backfill_live_separation(fixture, source, expected):
    market, store, processor = fixture
    add(market, source=source)
    processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 100)
    assert {d["observation_mode"] for d in decisions(store)} == {expected}
    assert {d["data_provenance"]["source"] for d in decisions(store)} == {source}
    assert all(d["observation_mode"] != "FORMAL_W04_ELIGIBLE" for d in decisions(store))


def test_prelaunch_ws_is_not_retroactively_live():
    provenance = {"source": "WS_LIVE", "ingested_at_ms": FREEZE_MS + INTERVAL_MS + 10}
    assert (
        classify(FREEZE_MS, provenance, FREEZE_MS + 2 * INTERVAL_MS, FREEZE_MS + 3 * INTERVAL_MS)
        == "PRELAUNCH_STATE_BACKFILL"
    )


def test_missing_then_recovery_remains_state_only(fixture):
    market, store, processor = fixture
    with pytest.raises(ObserverError):
        processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 100)
    processor.live_floor_ms = FREEZE_MS + INTERVAL_MS + 100
    add(market, source="REST_RECOVERY")
    processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 200)
    assert all(d["observation_mode"] == "PRELAUNCH_STATE_BACKFILL" for d in decisions(store))


def test_gap_continuity_blocks_even_with_latest_bar(fixture):
    market, store, processor = fixture
    add(market, start=FREEZE_MS + INTERVAL_MS)
    with pytest.raises(ObserverError, match="MISSING_CANDLE"):
        processor.evaluate(FREEZE_MS + INTERVAL_MS, FREEZE_MS + 2 * INTERVAL_MS + 100)
    assert not decisions(store)


def test_unresolved_gap_blocks(fixture):
    market, store, processor = fixture
    add(market)
    with MarketStore(market) as writer:
        writer.record_gap("BTCUSDT", FREEZE_MS, FREEZE_MS, "missing_closed_candles")
    with pytest.raises(ObserverError, match="UNRESOLVED_GAP"):
        processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 100)
    assert not decisions(store)


@pytest.mark.parametrize("at", [FREEZE_MS, FREEZE_MS + INTERVAL_MS - 1])
def test_unconfirmed_bar_blocked(fixture, at):
    market, store, processor = fixture
    add(market)
    with pytest.raises(ObserverError, match="UNCONFIRMED_OR_FUTURE"):
        processor.evaluate(FREEZE_MS, at)
    assert not decisions(store)


def test_future_ingestion_blocked(fixture):
    market, store, processor = fixture
    add(market)
    with pytest.raises(ObserverError, match="FUTURE_INFORMATION"):
        processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 5)
    assert not decisions(store)


def synthetic(n):
    value = np.r_[np.linspace(200, 100, n // 2), np.linspace(100, 300, n - n // 2)]
    return pd.DataFrame(
        {"open": value, "high": value + 1, "low": value - 1, "close": value, "volume": 10.0},
        index=pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC"),
    )


@pytest.mark.parametrize(
    "key,n",
    [
        (STRATEGIES[0], 199),
        (STRATEGIES[0], 201),
        (STRATEGIES[1], 56),
        (STRATEGIES[2], 181),
        (STRATEGIES[2], 182),
    ],
)
def test_frozen_warmup_blocked(audit, key, n):
    adapter = StrategyAdapter(audit)
    frame, provenance = synthetic(n), {"source": "SYNTHETIC_TEST_ONLY"}
    context = {
        "input_hash": history_hash(frame, provenance),
        "provenance": provenance,
        "target_ms": int(frame.index[-1].value // 1_000_000),
    }
    with pytest.raises(ObserverError, match="INSUFFICIENT_FROZEN_WARMUP"):
        adapter.evaluate(key, "BTCUSDT", frame, context)


def test_donchian_current_bar_excluded_and_momentum_180(audit):
    adapter = StrategyAdapter(audit)
    frame = synthetic(500)
    frame.iloc[-1, frame.columns.get_loc("high")] = 9999
    donchian = adapter.generate(adapter.registry[STRATEGIES[1]], frame)
    assert donchian.donchian_upper.iloc[-1] == frame.high.iloc[-56:-1].max()
    momentum = adapter.generate(adapter.registry[STRATEGIES[2]], frame)
    assert momentum.momentum.iloc[-1] == frame.close.iloc[-1] / frame.close.iloc[-181] - 1


def test_future_changes_do_not_change_any_frozen_indicator(audit):
    adapter = StrategyAdapter(audit)
    frame, altered = synthetic(800), synthetic(800)
    altered.iloc[600:, :4] *= 4
    for strategy in adapter.registry.values():
        original = adapter.generate(strategy, frame)
        pd.testing.assert_frame_equal(
            original.iloc[:600], adapter.generate(strategy, altered).iloc[:600], check_exact=True
        )


def test_input_hash_rejects_mutation(audit):
    adapter = StrategyAdapter(audit)
    frame = synthetic(300)
    with pytest.raises(ObserverError, match="INPUT_HASH_MISMATCH"):
        adapter.evaluate(STRATEGIES[0], "BTCUSDT", frame, {"input_hash": "bad", "provenance": {}})


@pytest.mark.parametrize(
    "path",
    [
        "src/trading_system/observer/frozen/alpha_lab/strategies.py",
        "artifacts/w03/config/w03_temporal_robustness.yaml",
        "artifacts/w03/historical/BTCUSDT_4h.csv",
    ],
)
def test_source_parameter_data_change_detected(monkeypatch, path):
    from trading_system.observer import audit as module

    original = module.sha
    monkeypatch.setattr(
        module,
        "sha",
        lambda p: "0" * 64 if str(p).replace("\\", "/").endswith(path) else original(p),
    )
    with pytest.raises(ObserverError) as error:
        source_audit()
    assert error.value.state == ObserverState.RULE_MISMATCH_STOP


def test_duplicate_conflict_stops_without_overwrite(fixture):
    _, store, processor = fixture
    processor.evaluate(FREEZE_MS - INTERVAL_MS, FREEZE_MS + 100)
    original = decisions(store)
    from trading_system.observer.model import SignalDecision

    batch = [SignalDecision(**d) for d in original]
    batch[0] = replace(batch[0], decision="ENTRY_CANDIDATE")
    with pytest.raises(ObserverError, match="DUPLICATE_DECISION_CONFLICT"):
        store.commit_batch(batch, processor.run_id, FREEZE_MS + 200)
    assert decisions(store) == original


def test_transaction_failure_rolls_back_all_nine_checkpoints(fixture):
    _, store, processor = fixture
    store.db.execute(
        "CREATE TRIGGER fail_checkpoint BEFORE INSERT ON processing_checkpoints "
        "BEGIN SELECT RAISE(ABORT,'simulated disk transaction error'); END"
    )
    with pytest.raises(ObserverError) as error:
        processor.evaluate(FREEZE_MS - INTERVAL_MS, FREEZE_MS + 100)
    assert error.value.state == ObserverState.PERSISTENCE_STOP
    assert not decisions(store) and not store.status()["checkpoints"]
    assert not store.db.execute(
        "SELECT * FROM evaluation_batches WHERE status='COMMITTED'"
    ).fetchone()


def test_immutable_decisions_and_checkpoint_corruption(fixture):
    _, store, processor = fixture
    processor.evaluate(FREEZE_MS - INTERVAL_MS, FREEZE_MS + 100)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        store.db.execute("UPDATE signal_decisions SET decision='NO_ACTION'")
    store.db.execute("UPDATE processing_checkpoints SET last_decision_hash='bad'")
    store.db.commit()
    with pytest.raises(ObserverError, match="STATE_RECOVERY_FAILED"):
        store.recover()


def test_read_only_market_repository(fixture):
    market, _, _ = fixture
    with MarketRepository(market) as repository:
        with pytest.raises(sqlite3.OperationalError):
            repository.connection.execute("DELETE FROM candles_4h")


def test_cli_no_credentials_or_execution(fixture, monkeypatch, capsys):
    market, store, _ = fixture
    from trading_system import cli
    from trading_system.observer import cli as observer_cli
    from trading_system.observer.audit import source_audit

    def forbidden(*args, **kwargs):
        pytest.fail("credentials/account path invoked")

    monkeypatch.setattr(cli, "load_config", forbidden)
    monkeypatch.setattr(
        observer_cli,
        "reproduction_gate",
        lambda: {**source_audit(), "verification_status": "W03_REPRODUCTION_PASS"},
    )
    assert main(["strategy-audit"]) == 0
    assert main(["observer-status", "--observer-db", str(store.path)]) == 0
    assert (
        main(
            [
                "observe",
                "--duration",
                "nan",
                "--db-path",
                str(market),
                "--observer-db",
                str(store.path),
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert '"formal_w04_started":false' in output


def test_market_path_collision_rejected_before_open(fixture, capsys):
    market, _, _ = fixture
    before = market.read_bytes()
    assert main(["observe", "--db-path", str(market), "--observer-db", str(market)]) == 2
    assert market.read_bytes() == before
    assert "PATH_COLLISION" in capsys.readouterr().out


def test_runtime_parameter_mutation_stops(audit, monkeypatch):
    adapter = StrategyAdapter(audit)
    monkeypatch.setattr(adapter.registry[STRATEGIES[2]], "atr_period", 21)
    with pytest.raises(ObserverError, match="RUNTIME_PARAMETER_MISMATCH"):
        source_audit()


def test_persistent_stop_survives_new_store(fixture, audit):
    _, store, processor = fixture
    store.health(processor.run_id, FREEZE_MS + 1, ObserverState.RULE_MISMATCH_STOP, "fixture")
    restarted = ObserverStore(store.path)
    try:
        with pytest.raises(ObserverError, match="PERSISTENT_STOP"):
            restarted.start(audit, FREEZE_MS + 2)
    finally:
        restarted.close()


def test_actual_process_crash_rolls_back_transaction(fixture):
    _, store, processor = fixture
    code = (
        "import sqlite3,sys,os; db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN'); "
        'db.execute("INSERT INTO evaluation_batches VALUES'
        "('crash',1,'COMMITTED','fixture',?,1,NULL)\",(sys.argv[2],)); os._exit(23)"
    )
    result = subprocess.run([sys.executable, "-c", code, str(store.path), processor.run_id])
    assert result.returncode == 23
    store.recover()
    assert not store.db.execute(
        "SELECT * FROM evaluation_batches WHERE batch_id='crash'"
    ).fetchone()
    assert not decisions(store) and not store.status()["checkpoints"]


def test_actual_cli_process_restart_does_not_duplicate(fixture):
    market, store, _ = fixture
    command = [
        sys.executable,
        "-m",
        "trading_system.cli",
        "strategy-replay",
        "--db-path",
        str(market),
        "--observer-db",
        str(store.path),
        "--start-ms",
        str(FREEZE_MS - INTERVAL_MS),
        "--end-ms",
        str(FREEZE_MS - INTERVAL_MS),
    ]
    first = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stdout + first.stderr
    second = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "ALREADY_COMMITTED" in second.stdout
    assert len(decisions(store)) == 9


def test_invalid_ohlcv_fail_closed(fixture):
    market, store, processor = fixture
    add(market)
    with sqlite3.connect(market) as db:
        db.execute("UPDATE candles_4h SET high_text='1' WHERE symbol='BTCUSDT'")
    with pytest.raises(ObserverError, match="INVALID_OHLCV"):
        processor.evaluate(FREEZE_MS, FREEZE_MS + INTERVAL_MS + 100)
    assert not decisions(store)


def test_no_action_batch_is_persisted(fixture):
    _, store, processor = fixture
    processor.evaluate(FREEZE_MS - INTERVAL_MS, FREEZE_MS + 100)
    assert len(decisions(store)) == 9
    assert any(d["decision"] == "NO_ACTION" for d in decisions(store))
