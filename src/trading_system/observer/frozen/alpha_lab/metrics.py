"""Metrics from net portfolio equity and completed net trade PnL."""
import math
import numpy as np
import pandas as pd

ANNUAL_BARS = 2190


def ratio(a, b):
    return float(a / b) if b > 0 else None


def calculate(ledger, curve, start, initial=100000.0):
    equity = curve.equity
    returns = equity.pct_change().to_numpy(copy=True)
    returns[0] = equity.iloc[0] / initial - 1
    years = (curve.index[-1] - start).total_seconds() / (365 * 86400)
    total = equity.iloc[-1] / initial - 1
    cagr = (1 + total) ** (1 / years) - 1
    sd = float(np.std(returns, ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0) ** 2)))
    peak = np.maximum.accumulate(np.r_[initial, equity.to_numpy()])[1:]
    mdd = float(np.min(equity.to_numpy() / peak - 1))
    pnl = ledger.net_pnl if len(ledger) else pd.Series(dtype=float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    metrics = {'total_return': float(total), 'cagr': float(cagr), 'mdd': mdd,
               'volatility': sd * math.sqrt(ANNUAL_BARS),
               'sharpe': ratio(float(returns.mean()) * math.sqrt(ANNUAL_BARS), sd),
               'sortino': ratio(float(returns.mean()) * math.sqrt(ANNUAL_BARS), downside),
               'calmar': ratio(cagr, -mdd), 'profit_factor': ratio(wins.sum(), -losses.sum()),
               'win_rate': float((pnl > 0).mean()) if len(pnl) else None,
               'avg_win_usdt': float(wins.mean()) if len(wins) else None,
               'avg_loss_usdt': float(losses.mean()) if len(losses) else None,
               'expectancy_usdt': float(pnl.mean()) if len(pnl) else None,
               'trade_count': len(pnl), 'exposure': float(curve.exposure.mean()),
               'time_exposure_observed_bars': float(curve.active_bar.mean()),
               'avg_holding_period_bars': float(ledger.bars_held.mean()) if len(pnl) else None,
               'avg_holding_period_hours': float(((pd.to_datetime(ledger.exit_time, utc=True) - pd.to_datetime(ledger.entry_time, utc=True)).dt.total_seconds() / 3600).mean()) if len(pnl) else None,
               'total_fees_usdt': float(curve.fees.iloc[-1]),
               'slippage_cost_usdt': float(ledger.slippage_cost.sum()) if len(pnl) else 0,
               'sample_start': str(start), 'sample_end': str(curve.index[-1]),
               'observed_bars': len(curve), 'source_gap_count': int(curve.source_gap_before.sum()),
               'data_quality': 'DOCUMENTED_SOURCE_GAPS' if curve.source_gap_before.any() else 'CONTINUOUS',
               'risk_metric_quality': 'OBSERVED_BAR_APPROXIMATION' if curve.source_gap_before.any() else 'STANDARD_4H',
               'terminal_exits': int((ledger.exit_reason == 'END_OF_TEST').sum()) if len(pnl) else 0}
    contributions = []
    for name in curve.columns:
        if name.endswith('_pnl') and name not in ('realized_pnl', 'unrealized_pnl'):
            symbol = name[:-4]
            net = float(curve[name].iloc[-1])
            contributions.append({'symbol': symbol, 'net_pnl_usdt': net,
                                  'return_contribution': net / initial,
                                  'trade_count': int((ledger.symbol == symbol).sum()) if len(pnl) else 0})
    if abs(sum(c['net_pnl_usdt'] for c in contributions) - (equity.iloc[-1] - initial)) > 1e-5:
        raise AssertionError('Asset contribution reconciliation failed')
    return metrics, contributions
