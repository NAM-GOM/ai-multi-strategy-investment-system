"""Long-only shared cash portfolio. Signals at t close execute at t+1 open."""
from dataclasses import dataclass
import math
import pandas as pd
from .data import validate


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    risk_per_trade: float = 0.005
    max_asset_allocation: float = 0.333
    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    def __post_init__(self):
        if (self.initial_capital <= 0 or not 0 < self.risk_per_trade <= 1 or
                not 0 < self.max_asset_allocation <= 1 or
                not 0 <= self.fee_bps < 10000 or not 0 <= self.slippage_bps < 10000):
            raise ValueError('Invalid backtest configuration')


def run_portfolio(signals, start, end, config=BacktestConfig(), strategy_key='synthetic_v0.1', allow_source_gaps=False):
    symbols = sorted(signals)
    for df in signals.values():
        validate(df, allow_gaps=allow_source_gaps)
        if not {'entry_long', 'exit_long', 'entry_atr'} <= set(df):
            raise ValueError('Missing strategy output')
    index = pd.date_range(start, end, freq='4h', tz='UTC')
    if allow_source_gaps:
        if len(symbols) != 1:
            raise ValueError('Source-gap diagnostics are single-asset only')
        index = signals[symbols[0]].loc[start:end].index
    if len(index) < 2:
        raise ValueError('Insufficient evaluation window')
    rows = {}
    for symbol, df in signals.items():
        if not index.isin(df.index).all():
            raise ValueError('Incomplete shared sample')
        rows[symbol] = df.loc[index].to_dict('records')
    cash, positions, ledger, curve = config.initial_capital, {}, [], []
    pending_entry, pending_exit = {}, {}
    realized = {s: 0.0 for s in symbols}
    fees = 0.0
    peak = config.initial_capital
    fee, slip = config.fee_bps / 10000, config.slippage_bps / 10000

    def close(symbol, raw_price, stamp, bar, reason, signal_time=None):
        nonlocal cash, fees
        p = positions.pop(symbol)
        fill = raw_price * (1 - slip)
        exit_fee = p['quantity'] * fill * fee
        gross = p['quantity'] * (fill - p['entry_fill'])
        net = gross - p['entry_fee'] - exit_fee
        cash += p['quantity'] * fill - exit_fee
        fees += exit_fee
        realized[symbol] += net
        ledger.append({**p, 'strategy_id': strategy_key.rsplit('_v', 1)[0],
                       'strategy_version': '0.1', 'symbol': symbol,
                       'exit_signal_time': signal_time, 'exit_time': stamp,
                       'exit_price_raw': raw_price, 'exit_fill': fill, 'exit_fee': exit_fee,
                       'slippage_cost': p['quantity'] * ((p['entry_fill'] - p['entry_price_raw']) + (raw_price - fill)),
                       'gross_pnl': gross, 'net_pnl': net,
                       'return_pct': net / (p['quantity'] * p['entry_fill'] + p['entry_fee']),
                       'bars_held': bar - p['entry_bar'] + 1, 'exit_reason': reason})

    for i, stamp in enumerate(index):
        bars = {s: rows[s][i] for s in symbols}
        source_gap = i > 0 and stamp - index[i-1] != pd.Timedelta(hours=4)
        if source_gap:
            # A signal cannot execute at a missing next-bar open.
            pending_entry, pending_exit = {}, {}
        # All exits happen before allocating cash to simultaneous entries.
        for s in symbols:
            if s in positions and s in pending_exit:
                close(s, bars[s]['open'], stamp, i, 'SIGNAL', pending_exit[s])
            elif s in positions and bars[s]['open'] <= positions[s]['initial_stop']:
                close(s, bars[s]['open'], stamp, i, 'STOP_GAP')
        pending_exit = {}
        open_equity = cash + sum(p['quantity'] * bars[s]['open'] for s, p in positions.items())
        candidates = {}
        for s, (atr, signal_time) in pending_entry.items():
            if s in positions or not math.isfinite(atr) or atr <= 0:
                continue
            fill = bars[s]['open'] * (1 + slip)
            distance = 3 * atr
            if fill <= distance:
                continue
            qty = min(open_equity * config.risk_per_trade / distance,
                      open_equity * config.max_asset_allocation / fill)
            candidates[s] = (qty, fill, atr, signal_time)
        # Pro-rata cash rationing prevents symbol-order preference. Include entry fees.
        needed = sum(q * fill * (1 + fee) for q, fill, _, _ in candidates.values())
        scale = min(1.0, cash / needed) if needed else 0.0
        for s, (q, fill, atr, signal_time) in candidates.items():
            q *= scale
            if q <= 0:
                continue
            entry_fee = q * fill * fee
            cash -= q * fill + entry_fee
            fees += entry_fee
            positions[s] = {'signal_time': signal_time, 'entry_time': stamp,
                            'entry_bar': i, 'entry_price_raw': bars[s]['open'],
                            'entry_fill': fill, 'quantity': q, 'entry_atr': atr,
                            'initial_stop': fill - 3 * atr, 'entry_fee': entry_fee,
                            'entry_equity': open_equity, 'cash_scale': scale}
        pending_entry = {}
        active = bool(positions)
        for s in list(positions):
            if bars[s]['low'] <= positions[s]['initial_stop']:
                close(s, min(bars[s]['open'], positions[s]['initial_stop']), stamp, i, 'STOP')
        if i == len(index) - 1:
            # Explicit terminal accounting liquidation, separate from strategy exits.
            for s in list(positions):
                close(s, bars[s]['close'], stamp + pd.Timedelta(hours=4), i, 'END_OF_TEST')
        value = sum(p['quantity'] * bars[s]['close'] for s, p in positions.items())
        equity = cash + value
        if cash < -1e-7 or equity <= 0:
            raise AssertionError('Invalid portfolio accounting')
        cash = max(cash, 0.0)
        unrealized = sum(p['quantity'] * (bars[s]['close'] - p['entry_fill']) - p['entry_fee'] for s, p in positions.items())
        if abs(equity - (config.initial_capital + sum(realized.values()) + unrealized)) > max(1e-6, equity * 1e-10):
            raise AssertionError('Equity/PnL reconciliation failed')
        peak = max(peak, equity)
        record = {'timestamp': stamp + pd.Timedelta(hours=4), 'cash': cash,
                  'position_value': value, 'unrealized_pnl': unrealized,
                  'realized_pnl': sum(realized.values()), 'fees': fees,
                  'equity': equity, 'drawdown': equity / peak - 1,
                  'exposure': value / equity, 'active_bar': active}
        record['source_gap_before'] = source_gap
        for s in symbols:
            p = positions.get(s)
            upnl = p['quantity'] * (bars[s]['close'] - p['entry_fill']) - p['entry_fee'] if p else 0.0
            record[f'{s}_pnl'] = realized[s] + upnl
        curve.append(record)
        if i != len(index) - 1:
            for s, row in bars.items():
                if s in positions:
                    if row['exit_long']:
                        pending_exit[s] = stamp + pd.Timedelta(hours=4)
                elif row['entry_long'] and not row['exit_long']:
                    pending_entry[s] = (row['entry_atr'], stamp + pd.Timedelta(hours=4))
    return pd.DataFrame(ledger), pd.DataFrame(curve).set_index('timestamp')
