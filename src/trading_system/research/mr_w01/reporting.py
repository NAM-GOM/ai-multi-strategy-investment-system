"""Net-equity metrics and explicit diagnostic conventions, without tuning."""

import numpy as np
import pandas as pd

from trading_system.observer.frozen.alpha_lab.metrics import calculate

from .engine import CONFIG, STEP


def metrics(ledger, curve, start):
    result, _ = calculate(ledger, curve, start)
    pnl = ledger.net_pnl
    result.update(
        net_pnl_usdt=float(pnl.sum()),
        stop_exit_count=int(ledger.exit_reason.str.startswith("STOP").sum()) if len(ledger) else 0,
        max_holding_hours=float(
            (
                (
                    pd.to_datetime(ledger.exit_time, utc=True)
                    - pd.to_datetime(ledger.entry_time, utc=True)
                ).dt.total_seconds()
                / 3600
            ).max()
        )
        if len(ledger)
        else None,
    )
    return result


def classify(result):
    # Reporting conventions only; never an APPROVED or entry/exit filter.
    if result["trade_count"] < 30:
        return "INSUFFICIENT_TRADES"
    pf, sharpe = result["profit_factor"], result["sharpe"]
    if (
        result["total_return"] > 0
        and pf is not None
        and pf > 1
        and sharpe is not None
        and sharpe > 0
    ):
        return "POSITIVE_DIAGNOSTIC"
    if result["total_return"] < 0 and pf is not None and pf < 1:
        return "NEGATIVE_DIAGNOSTIC"
    return "MIXED"


def benchmark(data, start, end):
    """Equal-weight, no rebalance, initial Open buys and terminal Close sells, same costs."""
    index = pd.date_range(start, end, freq="4h", tz="UTC")
    curve = pd.DataFrame(index=index + STEP)
    curve.index.name = "timestamp"
    total_value = np.zeros(len(index))
    trades, buy_fees, sell_fees = [], 0.0, 0.0
    for s, df in data.items():
        bars = df.loc[index]
        raw_buy, raw_sell = float(bars.open.iloc[0]), float(bars.close.iloc[-1])
        fill, sell_fill = raw_buy * 1.0005, raw_sell * 0.9995
        qty = CONFIG.initial_capital / 3 / (fill * 1.001)
        entry_fee, exit_fee = qty * fill * 0.001, qty * sell_fill * 0.001
        buy_fees += entry_fee
        sell_fees += exit_fee
        net = qty * (sell_fill - fill) - entry_fee - exit_fee
        trades.append(
            {
                "strategy": "equal_weight_buy_hold",
                "symbol": s,
                "entry_time": start,
                "exit_time": end + STEP,
                "entry_price_raw": raw_buy,
                "entry_fill": fill,
                "exit_price_raw": raw_sell,
                "exit_fill": sell_fill,
                "quantity": qty,
                "entry_fee": entry_fee,
                "exit_fee": exit_fee,
                "gross_pnl": qty * (sell_fill - fill),
                "net_pnl": net,
                "slippage_cost": qty * (fill - raw_buy + raw_sell - sell_fill),
                "bars_held": len(index),
                "exit_reason": "END_OF_TEST",
            }
        )
        pnl = qty * bars.close.to_numpy() - CONFIG.initial_capital / 3
        pnl[-1] = net
        curve[f"{s}_pnl"] = pnl
        total_value += qty * bars.close.to_numpy()
    total_value[-1] = CONFIG.initial_capital + sum(t["net_pnl"] for t in trades)
    curve["equity"] = total_value
    curve["fees"] = buy_fees
    curve.loc[curve.index[-1], "fees"] += sell_fees
    curve["exposure"] = 1.0
    curve.loc[curve.index[-1], "exposure"] = 0.0
    curve["active_bar"] = True
    curve["source_gap_before"] = False
    return pd.DataFrame(trades), curve


def asset_results(key, ledger, curve, start, symbols):
    """Attribution from the shared portfolio, not independent single-asset backtests."""
    rows = []
    for s in symbols:
        trades = ledger[ledger.symbol == s]
        # 100k reference capital expresses portfolio return contribution, not allocated ROI.
        attributed = pd.DataFrame(index=curve.index)
        attributed["equity"] = CONFIG.initial_capital + curve[f"{s}_pnl"]
        attributed[f"{s}_pnl"] = curve[f"{s}_pnl"]
        attributed["fees"] = float(trades.entry_fee.sum() + trades.exit_fee.sum())
        attributed["exposure"] = curve[f"{s}_value"] / curve.equity
        attributed["active_bar"] = curve[f"{s}_value"] > 0
        attributed["source_gap_before"] = False
        rows.append(
            {
                "strategy": key,
                "scope": f"asset_contribution/{s}",
                "classification": "NOT_SEPARATELY_CLASSIFIED",
                **metrics(trades, attributed, start),
            }
        )
    return rows


def charts(results, destination):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    destination.mkdir()
    for title, name, transform in (
        ("Net equity (USDT)", "equity", lambda c: c.equity),
        (
            "Drawdown",
            "drawdown",
            lambda c: (
                c.equity
                / np.maximum.accumulate(np.r_[CONFIG.initial_capital, c.equity.to_numpy()])[1:]
                - 1
            ),
        ),
    ):
        fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
        for key, (_, curve) in results.items():
            ax.plot(curve.index, transform(curve), label=key, linewidth=0.9)
        ax.set_title(title)
        ax.set_xlabel("UTC")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)
        fig.savefig(destination / f"{name}.svg", metadata={"Date": None})
        plt.close(fig)
