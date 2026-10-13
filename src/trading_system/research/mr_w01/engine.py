"""MR-only historical simulator. Frozen Trend engine remains unchanged.

Differences from W01: 2.5 ATR stop; sequential BTC/ETH/SOL allocation;
SMA-seeded Wilder inputs; no extra entry filter when exit condition is also true.
"""

import math

import numpy as np
import pandas as pd

from trading_system.observer.frozen.alpha_lab.data import SYMBOLS, validate
from trading_system.observer.frozen.alpha_lab.engine import BacktestConfig

CONFIG = BacktestConfig()
STEP = pd.Timedelta(hours=4)
TRADE_COLUMNS = [
    "strategy",
    "symbol",
    "signal_time",
    "entry_time",
    "entry_bar",
    "entry_price_raw",
    "entry_fill",
    "quantity",
    "entry_atr",
    "initial_stop",
    "entry_fee",
    "entry_equity",
    "exit_signal_time",
    "exit_time",
    "exit_bar_open",
    "exit_price_raw",
    "exit_fill",
    "exit_fee",
    "slippage_cost",
    "gross_pnl",
    "net_pnl",
    "return_pct",
    "bars_held",
    "exit_reason",
]


def run_portfolio(signals, start, end, strategy_key, config=CONFIG):
    if not signals or set(signals) - set(SYMBOLS):
        raise ValueError("Invalid universe")
    symbols = [s for s in SYMBOLS if s in signals]
    index = pd.date_range(start, end, freq="4h", tz="UTC")
    if len(index) < 2:
        raise ValueError("Insufficient evaluation window")
    rows = {}
    for s, df in signals.items():
        validate(df)
        if not {"entry_long", "exit_long", "entry_atr"} <= set(df):
            raise ValueError("Missing strategy output")
        if "is_closed" in df and not df.is_closed.eq(True).all():
            raise ValueError("Unconfirmed candle")
        if not index.isin(df.index).all():
            raise ValueError("Incomplete shared sample")
        rows[s] = df.loc[index].to_dict("records")
    fee, slip = config.fee_bps / 10000, config.slippage_bps / 10000
    cash, fees = config.initial_capital, 0.0
    positions, pending_entry, pending_exit = {}, {}, {}
    realized = {s: 0.0 for s in symbols}
    ledger, curve, executed = [], [], set()

    def close(s, raw, stamp, bar, reason, signal=None):
        nonlocal cash, fees
        p = positions.pop(s)
        fill = raw * (1 - slip)
        exit_fee = p["quantity"] * fill * fee
        gross = p["quantity"] * (fill - p["entry_fill"])
        net = gross - p["entry_fee"] - exit_fee
        cash += p["quantity"] * fill - exit_fee
        fees += exit_fee
        realized[s] += net
        ledger.append(
            {
                **p,
                "strategy": strategy_key,
                "symbol": s,
                "exit_signal_time": signal,
                "exit_time": stamp,
                "exit_bar_open": index[bar],
                "exit_price_raw": raw,
                "exit_fill": fill,
                "exit_fee": exit_fee,
                "gross_pnl": gross,
                "net_pnl": net,
                "slippage_cost": p["quantity"]
                * (p["entry_fill"] - p["entry_price_raw"] + raw - fill),
                "return_pct": net / (p["quantity"] * p["entry_fill"] + p["entry_fee"]),
                "bars_held": bar - p["entry_bar"] + 1,
                "exit_reason": reason,
            }
        )

    for i, stamp in enumerate(index):
        bars = {s: rows[s][i] for s in symbols}
        # Exit and gap stops release cash before any same-open entry allocation.
        for s in symbols:
            if s in positions and s in pending_exit:
                close(s, bars[s]["open"], stamp, i, "SIGNAL", pending_exit[s])
            elif s in positions and bars[s]["open"] <= positions[s]["initial_stop"]:
                close(s, bars[s]["open"], stamp, i, "STOP_GAP")
        pending_exit = {}
        equity_open = cash + sum(p["quantity"] * bars[s]["open"] for s, p in positions.items())
        for s in symbols:
            if s not in pending_entry or s in positions:
                continue
            atr, signal = pending_entry[s]
            token = (s, signal)
            if token in executed or not math.isfinite(atr) or atr <= 0:
                raise ValueError("Invalid or duplicated scheduled entry")
            fill = bars[s]["open"] * (1 + slip)
            distance = 2.5 * atr
            if fill <= distance:
                raise ValueError("Non-positive initial stop")
            q = min(
                equity_open * config.risk_per_trade / distance,
                equity_open * config.max_asset_allocation / fill,
                cash / (fill * (1 + fee)),
            )
            if q <= 0:
                continue
            entry_fee = q * fill * fee
            cash -= q * fill + entry_fee
            fees += entry_fee
            positions[s] = {
                "signal_time": signal,
                "entry_time": stamp,
                "entry_bar": i,
                "entry_price_raw": bars[s]["open"],
                "entry_fill": fill,
                "quantity": q,
                "entry_atr": atr,
                "initial_stop": fill - distance,
                "entry_fee": entry_fee,
                "entry_equity": equity_open,
            }
            executed.add(token)
        pending_entry = {}
        active = bool(positions)
        for s in symbols:
            if s in positions and bars[s]["low"] <= positions[s]["initial_stop"]:
                close(
                    s, min(bars[s]["open"], positions[s]["initial_stop"]), stamp + STEP, i, "STOP"
                )
        if i == len(index) - 1:
            # Accounting boundary, not a strategy exit rule. Includes both sell costs.
            for s in symbols:
                if s in positions:
                    close(s, bars[s]["close"], stamp + STEP, i, "END_OF_TEST")
        value = sum(p["quantity"] * bars[s]["close"] for s, p in positions.items())
        unrealized = {
            s: (
                positions[s]["quantity"] * (bars[s]["close"] - positions[s]["entry_fill"])
                - positions[s]["entry_fee"]
                if s in positions
                else 0.0
            )
            for s in symbols
        }
        equity = cash + value
        if cash < -1e-7 or equity <= 0:
            raise AssertionError("Invalid portfolio accounting")
        np.testing.assert_allclose(
            equity,
            config.initial_capital + sum(realized.values()) + sum(unrealized.values()),
            rtol=1e-10,
            atol=1e-6,
        )
        row = {
            "timestamp": stamp + STEP,
            "cash": cash,
            "position_value": value,
            "equity": equity,
            "fees": fees,
            "realized_pnl": sum(realized.values()),
            "unrealized_pnl": sum(unrealized.values()),
            "exposure": value / equity,
            "active_bar": active,
            "source_gap_before": False,
        }
        for s in symbols:
            row[f"{s}_pnl"] = realized[s] + unrealized[s]
            row[f"{s}_value"] = positions[s]["quantity"] * bars[s]["close"] if s in positions else 0
        curve.append(row)
        if i < len(index) - 1:
            for s in symbols:
                if s in positions:
                    if bars[s]["exit_long"]:
                        pending_exit[s] = stamp + STEP
                elif bars[s]["entry_long"]:
                    pending_entry[s] = (bars[s]["entry_atr"], stamp + STEP)
    return pd.DataFrame(ledger, columns=TRADE_COLUMNS), pd.DataFrame(curve).set_index("timestamp")


def audit(ledger, curve, initial=100000.0):
    np.testing.assert_allclose(curve.equity, curve.cash + curve.position_value, atol=1e-6)
    assert (curve.cash >= -1e-7).all()
    np.testing.assert_allclose(curve.equity.iloc[-1], initial + ledger.net_pnl.sum(), atol=1e-5)
    np.testing.assert_allclose(curve.fees.iloc[-1], ledger.entry_fee.sum() + ledger.exit_fee.sum())
    if len(ledger):
        np.testing.assert_allclose(ledger.initial_stop, ledger.entry_fill - 2.5 * ledger.entry_atr)
        np.testing.assert_allclose(ledger.entry_fill, ledger.entry_price_raw * 1.0005)
        np.testing.assert_allclose(ledger.exit_fill, ledger.exit_price_raw * 0.9995)
        np.testing.assert_allclose(ledger.entry_fee, ledger.quantity * ledger.entry_fill * 0.001)
        np.testing.assert_allclose(ledger.exit_fee, ledger.quantity * ledger.exit_fill * 0.001)
        np.testing.assert_allclose(
            ledger.net_pnl,
            ledger.quantity * (ledger.exit_fill - ledger.entry_fill)
            - ledger.entry_fee
            - ledger.exit_fee,
        )
        assert (ledger.quantity * ledger.entry_fill <= ledger.entry_equity * 0.333 + 1e-6).all()
        assert (
            ledger.quantity * ledger.entry_atr * 2.5 <= ledger.entry_equity * 0.005 + 1e-6
        ).all()
        assert (ledger.quantity > 0).all()
        assert not ledger.duplicated(["symbol", "signal_time"]).any()
        assert (ledger.signal_time == ledger.entry_time).all()
        normal = ledger[ledger.exit_reason == "SIGNAL"]
        assert (normal.exit_signal_time == normal.exit_time).all()
        for _, trades in ledger.groupby("symbol"):
            ordered = trades.sort_values("entry_time")
            assert all(
                a >= b for a, b in zip(ordered.entry_time.iloc[1:], ordered.exit_time.iloc[:-1])
            )
    return {"status": "PASS", "trades_checked": len(ledger), "equity_rows": len(curve)}
