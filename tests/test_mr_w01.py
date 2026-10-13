"""MR P01-P10 preflight: deterministic offline contracts and adversarial fills."""

import numpy as np
import pandas as pd
import pytest

from trading_system.observer.frozen.alpha_lab.data import validate
from trading_system.observer.frozen.alpha_lab.strategies import BaseStrategy
from trading_system.research.mr_w01.data import load_snapshot
from trading_system.research.mr_w01.engine import STEP, audit, run_portfolio
from trading_system.research.mr_w01.reporting import benchmark, metrics
from trading_system.research.mr_w01.strategies import (
    REGISTRY,
    BollingerReversion,
    RSIReversion,
    ShockReversal,
    wilder,
)


def frame(n=500):
    index = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    close = 100 + np.arange(n) * 0.1 + np.sin(np.arange(n) / 8) * 12
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 10.0,
            "is_closed": True,
        },
        index=index,
    )


def orders(n=6):
    df = frame(n)
    df[["open", "close"]] = 100.0
    df["high"], df["low"] = 110.0, 90.0
    df["entry_long"], df["exit_long"], df["entry_atr"] = False, False, 10.0
    return df


def simulate(signals):
    d = next(iter(signals.values()))
    return run_portfolio(signals, d.index[0], d.index[-1], "synthetic_v0.1")


def test_P01_frozen_snapshot_hash_cutoff_common_sample():
    data, start, end, metadata = load_snapshot()
    assert str(start) == "2020-09-13 16:00:00+00:00"
    assert str(end + STEP) == "2026-10-02 12:00:00+00:00"
    assert metadata["warmup_excluded"] == 201
    assert all(start in d.index and end in d.index for d in data.values())


@pytest.mark.parametrize(
    "bad", ["duplicate", "gap", "utc", "infinite", "negative", "geometry", "offgrid"]
)
def test_P01_quality_rejects(bad):
    df = frame()
    if bad == "duplicate":
        df = pd.concat([df.iloc[:1], df])
    elif bad == "gap":
        df = df.drop(df.index[3])
    elif bad == "utc":
        df.index = df.index.tz_localize(None)
    elif bad == "infinite":
        df.iloc[0, 0] = np.inf
    elif bad == "negative":
        df.iloc[0, 0] = -1
    elif bad == "geometry":
        df.iloc[0, 1] = 1
    else:
        df.index += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError):
        validate(df)


def test_P02_wilder_seeding_and_reference_rsi():
    values = pd.Series(
        [
            44.34,
            44.09,
            44.15,
            43.61,
            44.33,
            44.83,
            45.10,
            45.42,
            45.84,
            46.08,
            45.89,
            46.03,
            45.61,
            46.28,
            46.28,
            46.00,
        ]
    )
    change = values.diff()
    gain, loss = wilder(change.clip(lower=0), 14), wilder(-change.clip(upper=0), 14)
    rsi = 100 - 100 / (1 + gain / loss)
    assert rsi.iloc[:14].isna().all()
    assert rsi.iloc[14] == pytest.approx(70.464135, abs=1e-6)
    assert rsi.iloc[15] == pytest.approx(66.249619, abs=1e-6)
    atr = wilder(pd.Series(range(1, 23), dtype=float), 20)
    assert atr.iloc[19] == 10.5
    assert atr.iloc[20] == (10.5 * 19 + 21) / 20


def test_P02_ema_population_std_and_frozen_parameters():
    df = frame()
    b, s = BollingerReversion().generate(df), ShockReversal().generate(df)
    pd.testing.assert_series_equal(
        b.ema200, df.close.ewm(span=200, adjust=False, min_periods=200).mean(), check_names=False
    )
    assert b.lower_band.iloc[30] == pytest.approx(
        df.close.iloc[11:31].mean() - 2 * np.std(df.close.iloc[11:31], ddof=0)
    )
    assert s.r3.iloc[80] == df.close.iloc[80] / df.close.iloc[77] - 1
    assert s.r3_std60.iloc[80] == pytest.approx(np.std(s.r3.iloc[21:81], ddof=0))
    assert set(REGISTRY) == {"meanrev_rsi_v0.1", "meanrev_bollinger_v0.1", "meanrev_shock_v0.1"}
    assert all(
        isinstance(s, BaseStrategy) and s.atr_stop_multiple == 2.5 for s in REGISTRY.values()
    )


@pytest.mark.parametrize("key", list(REGISTRY))
def test_P03_no_lookahead_warmup_or_unconfirmed_signal(key):
    strategy, df = REGISTRY[key], frame()
    full, prefix = strategy.generate(df), strategy.generate(df.iloc[:300])
    pd.testing.assert_frame_equal(full.iloc[:300], prefix)
    assert not full.iloc[:201][["entry_long", "exit_long"]].any().any()
    df.loc[df.index[-1], "is_closed"] = False
    with pytest.raises(ValueError, match="Unconfirmed"):
        strategy.generate(df)


def test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit():
    r = pd.DataFrame({"close": [100, 101, 100], "ema200": [90, 90, 110], "rsi14": [29, 30, 49]})
    entry, exit_ = RSIReversion()._generate_signals(r)
    assert entry.tolist() == [False, True, False]
    assert exit_.tolist() == [False, False, False]  # EMA violation alone is not an exit.
    b = pd.DataFrame(
        {
            "close": [89, 90, 100],
            "lower_band": [90, 90, 90],
            "ema200": [80, 80, 80],
            "sma20": [95, 95, 100],
        }
    )
    entry, exit_ = BollingerReversion()._generate_signals(b)
    assert entry.tolist() == [False, True, False]
    assert exit_.tolist() == [False, False, True]
    sh = pd.DataFrame(
        {
            "close": [100, 101],
            "ema200": [90, 90],
            "sma20": [105, 105],
            "r3": [-0.1, 0],
            "r3_std60": [0.05, 0.5],
        }
    )
    entry, _ = ShockReversal()._generate_signals(sh)
    assert entry.tolist() == [False, True]  # prior volatility, inclusive -2 sigma.


def test_P05_next_open_exit_and_last_signal_unfilled():
    df = orders()
    df.loc[df.index[0], "entry_long"] = True
    df.loc[df.index[2], "exit_long"] = True
    df.loc[df.index[-1], "entry_long"] = True
    ledger, curve = simulate({"BTCUSDT": df})
    assert len(ledger) == 1
    t = ledger.iloc[0]
    assert t.entry_time == df.index[1] == t.signal_time
    assert t.exit_time == df.index[3] == t.exit_signal_time
    assert t.exit_reason == "SIGNAL"
    audit(ledger, curve)


def test_P05_simultaneous_conditions_no_added_entry_filter():
    df = orders()
    df.loc[df.index[0], ["entry_long", "exit_long"]] = True
    df.loc[df.index[1], "exit_long"] = True
    ledger, _ = simulate({"BTCUSDT": df})
    assert ledger.iloc[0].entry_time == df.index[1]
    assert ledger.iloc[0].exit_time == df.index[2]


@pytest.mark.parametrize("mode", ["entry_stop", "gap", "signal_gap"])
def test_P06_entry_bar_stop_and_adverse_gap(mode):
    df = orders()
    df.loc[df.index[0], "entry_long"] = True
    if mode == "entry_stop":
        df.loc[df.index[1], ["open", "close", "high", "low"]] = [100, 80, 110, 70]
    else:
        df.loc[df.index[2], ["open", "close", "high", "low"]] = [60, 65, 70, 50]
        if mode == "signal_gap":
            df.loc[df.index[1], "exit_long"] = True
    df.loc[df.index[1], "entry_atr"] = 1  # must not replace signal_t's ATR.
    ledger, curve = simulate({"BTCUSDT": df})
    t = ledger.iloc[0]
    assert t.entry_atr == 10 and t.initial_stop == pytest.approx(75.05)
    assert t.exit_price_raw == pytest.approx(75.05 if mode == "entry_stop" else 60)
    assert t.exit_reason == {"entry_stop": "STOP", "gap": "STOP_GAP", "signal_gap": "SIGNAL"}[mode]
    audit(ledger, curve)


def test_P07_risk_cap_cash_and_fixed_symbol_order():
    df = orders()
    df["entry_atr"] = 0.1  # allocation rather than risk binds.
    df["low"] = 99.9
    df.loc[df.index[0], "entry_long"] = True
    ledger, curve = simulate({s: df.copy() for s in ("SOLUSDT", "ETHUSDT", "BTCUSDT")})
    assert ledger.symbol.tolist() == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert ledger.quantity.iloc[0] == pytest.approx(ledger.quantity.iloc[1])
    audit(ledger, curve)
    btc, eth, sol = df.copy(), df.copy(), df.copy()
    for other in (eth, sol):
        other["entry_long"] = False
        other.loc[other.index[1], "entry_long"] = True
    btc.loc[btc.index[2:], ["open", "close", "high", "low"]] = [200, 200, 210, 199]
    ledger, curve = simulate({"SOLUSDT": sol, "ETHUSDT": eth, "BTCUSDT": btc})
    quantities = ledger.set_index("symbol").quantity
    assert quantities["SOLUSDT"] < quantities["ETHUSDT"]
    audit(ledger, curve)


def test_P07_exit_before_entry_allocation():
    btc, eth = orders(), orders()
    btc.loc[btc.index[0], "entry_long"] = True
    btc.loc[btc.index[1], "exit_long"] = True
    eth.loc[eth.index[1], "entry_long"] = True
    ledger, curve = simulate({"BTCUSDT": btc, "ETHUSDT": eth})
    a, b = ledger.iloc[0], ledger.iloc[1]
    assert a.exit_time == b.entry_time
    assert b.entry_equity == pytest.approx(100000 + a.net_pnl)
    audit(ledger, curve)


def test_P08_no_pyramiding_no_duplicate_and_no_ema_forced_exit():
    df = orders()
    df["entry_long"] = True
    df["ema200"] = 200.0
    ledger, curve = simulate({"BTCUSDT": df})
    assert len(ledger) == 1 and ledger.iloc[0].exit_reason == "END_OF_TEST"
    audit(ledger, curve)


def test_P09_bilateral_costs_pnl_and_equity_reconcile():
    df = orders()
    df.loc[df.index[0], "entry_long"] = True
    ledger, curve = simulate({"BTCUSDT": df})
    t = ledger.iloc[0]
    expected = t.quantity * (100 * 0.9995 - 100 * 1.0005)
    expected -= t.quantity * (100 * 1.0005 + 100 * 0.9995) * 0.001
    assert t.net_pnl == pytest.approx(expected)
    assert t.slippage_cost == pytest.approx(t.quantity * 0.1)
    assert curve.equity.iloc[-1] == pytest.approx(100000 + expected)
    audit(ledger, curve)
    broken = curve.copy()
    broken.iloc[-1, broken.columns.get_loc("equity")] += 10
    with pytest.raises(AssertionError):
        audit(ledger, broken)


def test_P10_determinism_empty_trades_and_equal_weight_benchmark():
    df = orders()
    signals = {s: df.copy() for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
    a, b = simulate(signals), simulate(signals)
    for x, y in zip(a, b):
        pd.testing.assert_frame_equal(x, y)
    audit(*a)
    assert metrics(*a, df.index[0])["trade_count"] == 0
    ledger, curve = benchmark(signals, df.index[0], df.index[-1])
    assert len(ledger) == 3
    assert np.ptp(ledger.quantity.to_numpy()) == 0
    assert curve.equity.iloc[-1] == pytest.approx(100000 + ledger.net_pnl.sum())
    assert curve.equity.iloc[-1] < 100000  # flat-price benchmark must still pay costs.
