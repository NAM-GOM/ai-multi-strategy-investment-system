"""Frozen historical temporal validation. Never reruns or overwrites W01/W02."""
from pathlib import Path
import hashlib
import json
import math
import platform
import statistics
import html
import zipfile

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

from . import w02_stage0 as gate
from .engine import BacktestConfig, run_portfolio
from .w02_engine import run_portfolio as stress_run

ROOT = Path('results/w03')
KEYS = {'T1': 'trend_ma_v0.1', 'T2': 'trend_donchian_v0.1', 'T3': 'trend_tsmom_v0.1'}
START = pd.Timestamp('2020-09-13 16:00', tz='UTC')
END = pd.Timestamp('2026-10-02 12:00', tz='UTC')
FORWARD_START = START + pd.DateOffset(years=1)
FORWARD_END = START + pd.DateOffset(years=6)
BAR = pd.Timedelta(hours=4)
ANNUAL = 2190


def save(name, rows):
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(ROOT / name, index=False)
    return frame


def frozen_hashes():
    paths = []
    for folder in ['data/cycle01', 'results/cycle01', 'results/w02']:
        paths.extend(p for p in Path(folder).rglob('*') if p.is_file())
    paths.extend(Path('alpha_lab').glob('*.py'))
    paths.extend(Path('tests').glob('*.py'))
    paths.extend(Path('config').glob('*'))
    return {str(p): gate.sha(p) for p in paths if 'w03' not in str(p).lower()}


def prepare_ledger(ledger):
    t = ledger.copy()
    for column in ['entry_time', 'exit_time', 'signal_time']:
        t[column] = pd.to_datetime(t[column], utc=True)
    return t


def completed(t, start, end):
    return t[(t.entry_time >= start) & (t.exit_time < end)]


def streaks(pnl):
    runs, n = [], 0
    for v in pnl:
        if v < 0:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return runs


def trade_metrics(t):
    n = len(t)
    pnl = t.net_pnl if n else pd.Series(dtype=float)
    ret = t.return_pct if n else pd.Series(dtype=float)
    gp, gl = float(pnl[pnl > 0].sum()), float(-pnl[pnl < 0].sum())
    losses = streaks(pnl)
    winners = pnl[pnl > 0].sort_values(ascending=False)
    return {
        'trade_count': n, 'trade_valid': n >= 10,
        'sample_quality': 'NORMAL' if n >= 20 else 'LOW_TEMPORAL_SAMPLE' if n >= 10 else 'DESCRIPTIVE_ONLY',
        'profit_factor': gp / gl if gl > 0 else None,
        'expectancy_return': float(ret.mean()) if n else None,
        'expectancy_usdt': float(pnl.mean()) if n else None,
        'median_trade_return': float(ret.median()) if n else None,
        'avg_win_return': float(ret[pnl > 0].mean()) if (pnl > 0).any() else None,
        'avg_loss_return': float(ret[pnl < 0].mean()) if (pnl < 0).any() else None,
        'gross_profit_net_trades': gp, 'gross_loss_net_trades': gl,
        'win_rate': float((pnl > 0).mean()) if n else None,
        'avg_holding_bars': float(t.bars_held.mean()) if n else None,
        'stop_exit_rate': float(t.exit_reason.isin(['STOP', 'STOP_GAP']).mean()) if n else None,
        'max_consecutive_losses': max(losses, default=0),
        'median_losing_streak': statistics.median(losses) if losses else None,
        'losing_streak_distribution': json.dumps(losses),
        **{f'top_{k}_winner_share': float(winners.head(k).sum()) / gp if gp else None for k in [1, 5, 10]},
    }


def drawdowns(equity, end):
    """Complete peak-to-recovery episodes; unrecovered episodes retain censoring."""
    peak_time, peak = equity.index[0], float(equity.iloc[0])
    trough_time, trough = peak_time, peak
    active, records = False, []

    def record(recovery):
        observed_end = recovery if recovery is not None else end
        return {
            'peak_time': peak_time, 'trough_time': trough_time, 'recovery_time': recovery,
            'drawdown_depth': trough / peak - 1,
            'peak_to_trough_days': (trough_time - peak_time).total_seconds() / 86400,
            'recovery_duration_days': (observed_end - trough_time).total_seconds() / 86400,
            'time_under_water_days': (observed_end - peak_time).total_seconds() / 86400,
            'censored': recovery is None,
            'status': 'CENSORED_UNRECOVERED' if recovery is None else 'RECOVERED',
            'long_drawdown': observed_end > peak_time + pd.DateOffset(months=18),
            'severe_long_drawdown': recovery is None or observed_end > peak_time + pd.DateOffset(months=24),
        }

    for stamp, value in equity.iloc[1:].items():
        if value >= peak:
            if active:
                records.append(record(stamp))
            peak_time, peak = stamp, float(value)
            trough_time, trough, active = stamp, float(value), False
        else:
            active = True
            if value < trough:
                trough_time, trough = stamp, float(value)
    if active:
        records.append(record(None))
    return records


def equity_metrics(equity, start, end, exposure):
    r = equity.pct_change().dropna()
    total = float(equity.iloc[-1] / equity.iloc[0] - 1)
    years = (end - start).total_seconds() / (365 * 86400)
    sd = float(r.std(ddof=1)) if len(r) > 1 else 0
    downside = float(np.sqrt(np.mean(np.minimum(r, 0) ** 2))) if len(r) else 0
    episodes = drawdowns(equity, end)
    return {
        'total_return': total, 'cagr': (1 + total) ** (1 / years) - 1 if years > 0 else None,
        'mdd': float((equity / equity.cummax() - 1).min()),
        'volatility': sd * math.sqrt(ANNUAL),
        'sharpe': float(r.mean()) / sd * math.sqrt(ANNUAL) if sd > 0 else None,
        'sortino': float(r.mean()) / downside * math.sqrt(ANNUAL) if downside > 0 else None,
        'exposure': float(exposure.mean()) if len(exposure) else None,
        'net_pnl': float(equity.iloc[-1] - equity.iloc[0]),
        'starting_equity': float(equity.iloc[0]), 'ending_equity': float(equity.iloc[-1]),
        'observed_bars': len(r),
        'max_drawdown_duration_days': max((x['time_under_water_days'] for x in episodes), default=0),
        'max_recovery_duration_days': max((x['recovery_duration_days'] for x in episodes), default=0),
        'unrecovered_drawdown': any(x['censored'] for x in episodes),
    }


def window_metrics(t, curve, start, end):
    # Equity timestamps are closes: [start,end) bar-open interval uses closes (start,end].
    # The start mark comes from the already-confirmed preceding candle, no reset.
    marks = curve[(curve.index > start) & (curve.index <= end)]
    if start == START:
        base = 100000.0
    else:
        base = float(curve.loc[curve.index <= start, 'equity'].iloc[-1])
    equity = pd.concat([pd.Series([base], index=pd.DatetimeIndex([start])), marks.equity])
    c = completed(t, start, end)
    overlap = t[(t.entry_time < end) & (t.exit_time >= start)]
    boundary = overlap.index.difference(c.index)
    result = {'window_start': start, 'window_end': end,
              **equity_metrics(equity, start, end, marks.exposure), **trade_metrics(c),
              'boundary_crossing_trade_count': len(boundary)}
    pf, e = result['profit_factor'], result['expectancy_return']
    result['positive'] = bool(result['trade_valid'] and result['total_return'] > 0
                              and pf is not None and pf > 1 and e is not None and e > 0)
    return result


def market_labels(data):
    prices = pd.DataFrame({s: d.close for s, d in data.items()})
    index = (prices / prices.loc[START]).mean(axis=1)
    # Labels are for bar opens; only preceding confirmed bar informs them.
    direction_return = index.pct_change(90 * 6).shift(1)
    direction = pd.Series('UNAVAILABLE', index=index.index)
    direction.loc[direction_return.notna()] = 'SIDEWAYS'
    direction.loc[direction_return >= .2] = 'BULL'
    direction.loc[direction_return <= -.2] = 'BEAR'
    rv30 = np.log(index).diff().rolling(30 * 6, min_periods=30 * 6).std(ddof=1) * np.sqrt(ANNUAL)
    prior_rv = rv30.shift(1)
    # Distribution excludes the RV being assessed, as well as the current bar.
    threshold = rv30.shift(2).rolling(365 * 6, min_periods=365 * 6).quantile(.75)
    vol = pd.Series('VOL_REGIME_UNAVAILABLE', index=index.index)
    valid = threshold.notna() & prior_rv.notna()
    vol.loc[valid] = 'NORMAL_VOL'
    vol.loc[valid & (prior_rv > threshold)] = 'HIGH_VOL'
    return pd.DataFrame({'market_index': index, 'direction_return_90d': direction_return,
                         'direction': direction, 'rv30_prior': prior_rv,
                         'rv_threshold_prior365': threshold, 'volatility_regime': vol})


def regime_analysis(tag, t, curve, labels):
    r = curve.equity.pct_change()
    r.iloc[0] = curve.equity.iloc[0] / 100000 - 1
    delta = curve.equity.diff()
    delta.iloc[0] = curve.equity.iloc[0] - 100000
    aligned = labels.reindex(curve.index - BAR)
    aligned.index = curve.index
    rows = []
    eligible = completed(t, START, END)
    for column, names in [('direction', ['BULL', 'BEAR', 'SIDEWAYS', 'UNAVAILABLE']),
                          ('volatility_regime', ['HIGH_VOL', 'NORMAL_VOL', 'VOL_REGIME_UNAVAILABLE'])]:
        entry_label = labels[column].reindex(eligible.entry_time).to_numpy()
        for name in names:
            mask = aligned[column].eq(name)
            values = r[mask]
            synthetic = pd.Series(np.r_[1., np.cumprod(1 + values.to_numpy())])
            sd = float(values.std(ddof=1)) if len(values) > 1 else 0
            trades = eligible.loc[entry_label == name]
            rows.append({'strategy': tag, 'regime_type': column, 'regime': name,
                         'conditional_compounded_return': float(synthetic.iloc[-1] - 1),
                         'conditional_mdd': float((synthetic / synthetic.cummax() - 1).min()),
                         'conditional_sharpe': float(values.mean()) / sd * math.sqrt(ANNUAL) if sd > 0 else None,
                         'net_pnl': float(delta[mask].sum()), 'observed_bars': int(mask.sum()),
                         'exposure': float(curve.loc[mask, 'exposure'].mean()) if mask.any() else None,
                         'equity_method': 'DISJOINT_BAR_COMPOUNDING_DIAGNOSTIC',
                         'trade_attribution': 'ENTRY_REGIME_WHOLE_TRADE', **trade_metrics(trades)})
    return rows


def window_costs(t, curve, start, end):
    m = window_metrics(t, curve, start, end)
    entries = t[(t.entry_time >= start) & (t.entry_time < end)]
    exits = t[(t.exit_time >= start) & (t.exit_time < end)]
    fee = float(entries.entry_fee.sum() + exits.exit_fee.sum())
    slip = float((entries.quantity * (entries.entry_fill - entries.entry_price_raw)).sum()
                 + (exits.quantity * (exits.exit_price_raw - exits.exit_fill)).sum())
    turnover = float((entries.quantity * entries.entry_fill).sum() + (exits.quantity * exits.exit_fill).sum())
    raw = m['net_pnl'] + fee + slip
    return {**m, 'fees_usdt': fee, 'slippage_cost_usdt': slip, 'total_cost_usdt': fee + slip,
            'raw_price_pnl_equity_bridge': raw,
            'total_cost_over_raw_price_pnl': (fee + slip) / raw if raw > 0 else None,
            'turnover_usdt': turnover, 'turnover_over_starting_equity': turnover / m['starting_equity']}


def summary_rows(frame):
    output = []
    for tag, g in frame.groupby('strategy'):
        valid = g[g.trade_valid]
        output.append({'strategy': tag, 'window_count': len(g), 'valid_windows': len(valid),
                       'positive_count': int(valid.positive.sum()),
                       'positive_ratio': float(valid.positive.mean()) if len(valid) else None,
                       'negative_equity_ratio': float((g.total_return < 0).mean()),
                       'nonpositive_criteria_ratio': float((~valid.positive).mean()) if len(valid) else None,
                       'median_cagr': float(g.cagr.median()), 'median_sharpe': float(g.sharpe.median()),
                       'median_pf': float(valid.profit_factor.median()) if len(valid) else None,
                       'median_expectancy_return': float(valid.expectancy_return.median()) if len(valid) else None,
                       'best_window_by_return': g.loc[g.total_return.idxmax(), 'window'],
                       'worst_window_by_return': g.loc[g.total_return.idxmin(), 'window']})
    return output


def classify(rolling_ratio, forward_ratio, nvalid, agg, recent, moderate, folds, flags):
    def nonpositive(m):
        return m['profit_factor'] is not None and m['expectancy_return'] is not None and m['profit_factor'] <= 1 and m['expectancy_return'] <= 0
    hard = []
    if rolling_ratio is not None and forward_ratio is not None and rolling_ratio < .5 and forward_ratio < .4:
        hard.append('TEMPORAL_COLLAPSE')
    if nonpositive(agg):
        hard.append('FORWARD_EDGE_FAILURE')
    if nonpositive(moderate):
        hard.append('EXECUTION_FAILURE')
    for i in range(len(folds) - 2):
        if all(x['trade_valid'] and x['total_return'] < 0 and x['expectancy_return'] is not None and x['expectancy_return'] <= 0 for x in folds[i:i+3]):
            hard.append('PERSISTENT_FAILURE')
            break
    if 'EXTREME_YEAR_CONCENTRATION' in flags and recent['total_return'] <= 0 and recent['expectancy_return'] is not None and recent['expectancy_return'] <= 0:
        hard.append('EXTREME_TEMPORAL_DEPENDENCY')
    if hard:
        return 'W03_REJECT', hard
    conditions = {
        'ROLLING_70_PERCENT': rolling_ratio is not None and rolling_ratio >= .7,
        'FORWARD_60_PERCENT': forward_ratio is not None and forward_ratio >= .6,
        'AT_LEAST_3_VALID_FOLDS': nvalid >= 3,
        'FORWARD_RETURN': agg['total_return'] > 0,
        'FORWARD_PF': agg['profit_factor'] is not None and agg['profit_factor'] > 1,
        'FORWARD_EXPECTANCY': agg['expectancy_return'] is not None and agg['expectancy_return'] > 0,
        'FORWARD_SHARPE': agg['sharpe'] is not None and agg['sharpe'] > 0,
        'RECENT_RETURN': recent['total_return'] > 0,
        'RECENT_EXPECTANCY': recent['expectancy_return'] is not None and recent['expectancy_return'] > 0,
        'MODERATE_PF': moderate['profit_factor'] is not None and moderate['profit_factor'] > 1,
        'MODERATE_EXPECTANCY': moderate['expectancy_return'] is not None and moderate['expectancy_return'] > 0,
        'NO_EXTREME_YEAR_CONCENTRATION': 'EXTREME_YEAR_CONCENTRATION' not in flags,
        'NO_SEVERE_LONG_DRAWDOWN': 'SEVERE_LONG_DRAWDOWN' not in flags,
        # Section 13 explicitly routes these flags to HOLD; conservative precedence.
        'NO_EXPLICIT_HOLD_FLAGS': not ({'YEAR_CONCENTRATION', 'LONG_DRAWDOWN'} & set(flags)),
    }
    failures = [name for name, passed in conditions.items() if not passed]
    return ('W03_HOLD', failures) if failures else ('W03_PASS_WITH_FLAGS' if flags else 'W03_PASS', [])


def chart(filename, title, labels, values, percent=False):
    """Exact-data SVG plus Pillow PNG; no generative imagery."""
    width, height = 1100, 95 + 26 * len(labels)
    img = Image.new('RGB', (width, height), 'white')
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    titlefont = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 21)
    d.text((20, 18), title, fill='#182233', font=titlefont)
    finite = [float(v) for v in values if v is not None and math.isfinite(v)]
    lo, hi = min([0.] + finite), max([0.] + finite)
    if lo == hi:
        hi = lo + 1
    left, right = 165, 890
    x = lambda v: left + (v - lo) / (hi - lo) * (right - left)
    zero = x(0)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           f'<g font-family="Arial" fill="#182233"><text x="20" y="36" font-size="21">{html.escape(title)}</text>']
    for i, (label, value) in enumerate(zip(labels, values)):
        y = 62 + i * 26
        d.text((20, y), str(label), fill='#182233', font=font)
        svg.append(f'<text x="20" y="{y+16}">{html.escape(str(label))}</text>')
        if value is None or not math.isfinite(value):
            text = 'N/A'
        else:
            a, b = sorted([zero, x(value)])
            b = max(b, a + 1)
            color = '#277b68' if value >= 0 else '#bd4b55'
            d.rectangle([a, y+2, b, y+20], fill=color)
            svg.append(f'<rect x="{a:.2f}" y="{y+2}" width="{b-a:.2f}" height="18" fill="{color}"/>')
            text = f'{value:.2%}' if percent else f'{value:.3f}'
        d.text((910, y), text, fill='#182233', font=font)
        svg.append(f'<text x="910" y="{y+16}">{text}</text>')
    d.line([zero, 57, zero, height-20], fill='#9da9ba')
    svg.append(f'<line x1="{zero}" y1="57" x2="{zero}" y2="{height-20}" stroke="#9da9ba"/></g></svg>')
    (ROOT/'figures'/f'{filename}.svg').write_text('\n'.join(svg), encoding='utf-8')
    img.save(ROOT/'figures'/f'{filename}.png')


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    if (ROOT/'W03_report.md').exists():
        raise FileExistsError('Preserve completed W03; choose a new output directory for reruns.')
    before = frozen_hashes()
    config = {
        'spec_library_id': 'libfile_c6bc793da854819185e41b3e9b33e442',
        'method': 'HISTORICAL_TEMPORAL_ROBUSTNESS', 'start': str(START), 'end': str(END),
        'initial_equity': 100000, 'risk_per_trade': .005, 'asset_cap': .333,
        'atr_period': 20, 'stop_multiplier': 3,
        'strategy_parameters': {'T1': [50, 200], 'T2': [55, 20], 'T3': [180]},
        'rolling_months': 18, 'rolling_step_months': 6, 'forward_years': 1,
        'minimum_descriptive_trades': 10, 'normal_trades': 20,
        'rolling_pass': .7, 'forward_pass': .6,
        'cost_scenarios': {'A': [10, 5], 'B': [10, 10], 'C': [20, 20]},
        'regime_return_bars': 540, 'direction_thresholds': [-.2, .2],
        'rv_bars': 180, 'rv_distribution_bars': 2190, 'rv_quantile': .75,
        'routing_precedence': 'INVALID > HARD_REJECT > EXPLICIT_HOLD > PASS_WITH_FLAGS',
        'undefined_pf_policy': 'NULL; cannot establish positive fold',
        'recent_fold_trade_union': 'union of per-fold completed trades; exclude crossing folds',
        'forward_aggregate_trade_policy': 'completed inside entire forward span, internal crossings included',
        'full_year_remaining_return': 'compound returns of remaining full years',
        'vol_threshold_policy': 'previous 365 days excluding assessed prior RV',
        'no_downloads': True, 'no_optimization': True,
    }
    Path('config').mkdir(exist_ok=True)
    Path('config/w03_temporal_robustness.yaml').write_text(json.dumps(config, indent=2), encoding='utf-8')
    gate.ROOT = ROOT
    ok, manifest, data, baselines = gate.reproduce()
    checks = pd.read_csv(ROOT/'baseline_reproduction.csv')
    extra = []
    w02_manifest = json.loads(Path('results/w02/manifest.json').read_text())
    for path, expected in w02_manifest['sha256'].items():
        extra.append({'check': 'W02_HASH:'+path, 'passed': gate.sha(path) == expected, 'detail': ''})
    for tag, key in KEYS.items():
        if key in baselines:
            l, c, _, _ = baselines[key]
            extra.append({'check': tag+':W02_equity_exact', 'passed': c.to_csv().encode() == Path(f'results/w02/{tag}_baseline_equity.csv').read_bytes(), 'detail': ''})
    extra.append({'check': 'EXACT_EVALUATION_BOUNDARIES', 'passed': pd.Timestamp(manifest['primary_start']) == START and pd.Timestamp(manifest['last_bar_open'])+BAR == END, 'detail': ''})
    if ok:
        for key, (l, c, _, signals) in baselines.items():
            dl, dc = stress_run(signals, START, END-BAR, strategy_key=key)
            extra.append({'check': key+':STRESS_ENGINE_PARITY',
                          'passed': dl.to_csv(index=False)==l.to_csv(index=False) and dc.to_csv()==c.to_csv(), 'detail': ''})
    checks = pd.concat([checks, pd.DataFrame(extra)], ignore_index=True)
    checks.to_csv(ROOT/'baseline_reproduction.csv', index=False)
    ok = ok and bool(checks.passed.all())
    if not ok:
        save('W03_summary.csv', [{'strategy': t, 'classification': 'W03_INVALID', 'flags': 'ENGINE_MISMATCH'} for t in KEYS])
        (ROOT/'W03_report.md').write_text('# W03_INVALID\nBaseline reproduction failed. Temporal tests were not run.', encoding='utf-8')
        return
    print('W03_GATE PASS', len(checks), 'checks', flush=True)
    labels = market_labels(data)
    labels.to_csv(ROOT/'market_regime_labels.csv')
    rolling, folds, stubs, calendars, regimes, episodes, concentrations, costs, aggregates = [], [], [], [], [], [], [], [], []
    baseline_records = []
    for tag, key in KEYS.items():
        ledger, curve, bm, signals = baselines[key]
        t = prepare_ledger(ledger)
        baseline_records.append({'strategy': tag, **bm})
        for i in range(10):
            s = START + pd.DateOffset(months=i*6)
            e = s + pd.DateOffset(months=18)
            m = window_metrics(t, curve, s, e)
            rolling.append({'strategy': tag, 'window': f'R{i+1:02}', **m})
        for i in range(5):
            s = START + pd.DateOffset(years=i+1)
            e = START + pd.DateOffset(years=i+2)
            folds.append({'strategy': tag, 'window': f'F{i+1}', 'history_start': START, 'history_end': s, **window_metrics(t, curve, s, e)})
        stubs.append({'strategy': tag, 'window': 'FORWARD_STUB', **window_metrics(t, curve, FORWARD_END, END)})
        for year in range(2020, 2027):
            s, e = max(START, pd.Timestamp(f'{year}-01-01', tz='UTC')), min(END, pd.Timestamp(f'{year+1}-01-01', tz='UTC'))
            calendars.append({'strategy': tag, 'year': year, 'formal_year': 2021 <= year <= 2025, **window_metrics(t, curve, s, e)})
        regimes.extend(regime_analysis(tag, t, curve, labels))
        eq = pd.concat([pd.Series([100000.], index=pd.DatetimeIndex([START])), curve.equity])
        episodes.extend({'strategy': tag, 'episode': i+1, **x} for i, x in enumerate(drawdowns(eq, END)))
        for kind, rows in [('ROLLING', rolling), ('FORWARD', folds)]:
            for m in [x for x in rows if x['strategy'] == tag]:
                concentrations.append({'strategy': tag, 'scope': kind, 'window': m['window'],
                                       **{k: m[k] for k in ['trade_count', 'top_1_winner_share', 'top_5_winner_share', 'top_10_winner_share']}})
        agg = window_metrics(t, curve, FORWARD_START, FORWARD_END)
        aggregates.append({'strategy': tag, 'scope': 'FORWARD_AGGREGATE', **agg})
        recent_start = START + pd.DateOffset(years=4)
        recent = window_metrics(t, curve, recent_start, FORWARD_END)
        # Pool complete trades from F4/F5, never average their PF/expectancy.
        recent_trades = pd.concat([completed(t, recent_start, recent_start+pd.DateOffset(years=1)), completed(t, recent_start+pd.DateOffset(years=1), FORWARD_END)])
        recent.update(trade_metrics(recent_trades))
        aggregates.append({'strategy': tag, 'scope': 'RECENT_TWO_FOLDS', **recent})
        for scenario, (fee, slip) in config['cost_scenarios'].items():
            if scenario == 'A':
                ct, cc = t, curve
            else:
                cl, cc = stress_run(signals, START, END-BAR, config=BacktestConfig(fee_bps=fee, slippage_bps=slip), strategy_key=key)
                ct = prepare_ledger(cl)
            # Continuous historical run forms fold state; only forward folds reported/scored.
            for i in range(5):
                s, e = START+pd.DateOffset(years=i+1), START+pd.DateOffset(years=i+2)
                costs.append({'strategy': tag, 'scenario': scenario, 'window': f'F{i+1}', **window_costs(ct, cc, s, e)})
            aggregates.append({'strategy': tag, 'scope': f'COST_{scenario}_FORWARD_AGGREGATE', **window_costs(ct, cc, FORWARD_START, FORWARD_END)})
        print(tag, 'rolling/forward/regime/calendar/drawdown/cost complete', flush=True)
    rf, ff, yf, rg, dd, cf, af = [pd.DataFrame(x) for x in [rolling, folds, calendars, regimes, episodes, costs, aggregates]]
    rs, fs = pd.DataFrame(summary_rows(rf)), pd.DataFrame(summary_rows(ff))
    flags, classification, year_concentration = [], [], []
    for tag in KEYS:
        fl = []
        def flag(name, scope, detail):
            flags.append({'strategy': tag, 'flag': name, 'scope': scope, 'detail': detail})
            if name not in fl:
                fl.append(name)
        rr, fr = rs.set_index('strategy').loc[tag], fs.set_index('strategy').loc[tag]
        for scope, frame in [('ROLLING', rf), ('FORWARD', ff)]:
            for m in frame[frame.strategy == tag].to_dict('records'):
                if m['trade_count'] < 20:
                    flag('LOW_TEMPORAL_SAMPLE', scope+':'+m['window'], f"completed trades={m['trade_count']}; valid={m['trade_valid']}")
                if m['trade_count'] >= 20 and m['top_5_winner_share'] is not None and m['top_5_winner_share'] > .7:
                    flag('TEMPORAL_TRADE_CONCENTRATION', scope+':'+m['window'], str(m['top_5_winner_share']))
        if rr.positive_ratio < .7:
            flag('ROLLING_INSTABILITY', 'ROLLING', str(rr.positive_ratio))
        if fr.positive_ratio < .6:
            flag('FORWARD_INSTABILITY', 'FORWARD', str(fr.positive_ratio))
        take = lambda scope: af[(af.strategy == tag) & (af.scope == scope)].iloc[0].to_dict()
        agg, recent, mod = take('FORWARD_AGGREGATE'), take('RECENT_TWO_FOLDS'), take('COST_B_FORWARD_AGGREGATE')
        if recent['expectancy_return'] <= 0 or recent['profit_factor'] <= 1:
            flag('TEMPORAL_DECAY', 'RECENT_TWO_FOLDS', f"E={recent['expectancy_return']}; PF={recent['profit_factor']}")
        if mod['profit_factor'] <= 1 or mod['expectancy_return'] <= 0:
            flag('TEMPORAL_COST_FRAGILITY', 'MODERATE_FORWARD', f"E={mod['expectancy_return']}; PF={mod['profit_factor']}")
        years = yf[(yf.strategy == tag) & yf.formal_year]
        positive = years[years.net_pnl > 0].sort_values('net_pnl', ascending=False)
        gp = float(positive.net_pnl.sum())
        top1 = float(positive.head(1).net_pnl.sum())/gp if gp else None
        top2 = float(positive.head(2).net_pnl.sum())/gp if gp else None
        rest = years[~years.year.isin(positive.head(2).year)]
        rest_return = float(np.prod(1+rest.total_return) - 1)
        year_concentration.append({'strategy': tag, 'top_1_positive_year_share': top1, 'top_2_positive_year_share': top2,
                                   'remaining_full_years_compounded_return': rest_return})
        if top2 is not None and top2 > .8:
            flag('YEAR_CONCENTRATION', 'FULL_CALENDAR_YEARS', str(top2))
        if top2 is not None and top2 > .9 and rest_return <= 0:
            flag('EXTREME_YEAR_CONCENTRATION', 'FULL_CALENDAR_YEARS', f'{top2}; rest_return={rest_return}')
        gd = dd[dd.strategy == tag]
        if gd.long_drawdown.any():
            flag('LONG_DRAWDOWN', 'CONTINUOUS_FULL_SAMPLE', str(gd.time_under_water_days.max()))
        if gd.severe_long_drawdown.any():
            flag('SEVERE_LONG_DRAWDOWN', 'CONTINUOUS_FULL_SAMPLE', f'max days={gd.time_under_water_days.max()}; end unrecovered={gd.censored.any()}')
        direction = rg[(rg.strategy == tag) & (rg.regime_type == 'direction') & (rg.regime != 'UNAVAILABLE')]
        pos = direction[direction.net_pnl > 0]
        share = float(pos.net_pnl.max()/pos.net_pnl.sum()) if len(pos) else None
        if share is not None and share > .8:
            flag('REGIME_DEPENDENCY', 'DIRECTION', str(share))
        decision, reasons = classify(rr.positive_ratio, fr.positive_ratio, fr.valid_windows, agg, recent, mod,
                                     ff[ff.strategy == tag].to_dict('records'), fl)
        classification.append({'strategy': tag, 'strategy_key': KEYS[tag], 'classification': decision,
                               'rolling_positive_count': rr.positive_count, 'rolling_valid_count': rr.valid_windows,
                               'rolling_positive_ratio': rr.positive_ratio,
                               'forward_positive_count': fr.positive_count, 'forward_valid_count': fr.valid_windows,
                               'forward_positive_ratio': fr.positive_ratio,
                               'forward_return': agg['total_return'], 'forward_sharpe': agg['sharpe'],
                               'forward_pf': agg['profit_factor'], 'forward_expectancy_return': agg['expectancy_return'],
                               'recent_two_return': recent['total_return'], 'recent_two_pf': recent['profit_factor'],
                               'recent_two_expectancy_return': recent['expectancy_return'],
                               'moderate_forward_pf': mod['profit_factor'], 'moderate_forward_expectancy_return': mod['expectancy_return'],
                               'flags': '|'.join(fl), 'routing_reasons': '|'.join(reasons),
                               'registry_status': 'TESTING', 'approval': False})
    for name, rows in [('rolling_time_slices.csv', rf), ('rolling_summary.csv', rs), ('forward_folds.csv', ff),
                       ('forward_summary.csv', fs), ('regime_metrics.csv', rg), ('calendar_stability.csv', yf),
                       ('drawdown_episodes.csv', dd), ('trade_concentration.csv', concentrations),
                       ('cost_by_forward_fold.csv', cf), ('diagnostic_flags.csv', flags),
                       ('W03_classification.csv', classification), ('W03_summary.csv', classification),
                       ('forward_aggregates.csv', af), ('forward_stub.csv', stubs),
                       ('year_concentration.csv', year_concentration), ('baseline_metrics.csv', baseline_records)]:
        save(name, rows)
    (ROOT/'figures').mkdir(exist_ok=True)
    for frame, fields in [(rf, [('cagr','rolling_cagr',True), ('mdd','rolling_mdd',True), ('sharpe','rolling_sharpe',False), ('expectancy_return','rolling_expectancy',True), ('trade_count','rolling_trade_count',False)]),
                          (ff, [('total_return','forward_return',True), ('sharpe','forward_sharpe',False)]),
                          (yf, [('total_return','calendar_return',True)])]:
        ls = [f'{r.strategy} {getattr(r,"window",getattr(r,"year",""))}' for r in frame.itertuples()]
        for field, name, pct in fields:
            chart(name, name.replace('_',' ').title(), ls, frame[field].tolist(), pct)
    chart('regime_performance', 'Conditional regime returns (disjoint bars)', [f'{r.strategy} {r.regime}' for r in rg.itertuples()], rg.conditional_compounded_return.tolist(), True)
    maxima = dd.groupby('strategy').time_under_water_days.max()
    chart('drawdown_duration', 'Longest underwater episode (days; censored included)', maxima.index.tolist(), maxima.tolist())
    chart('cost_drag_by_fold', 'Execution cost / raw price PnL (N/A if raw PnL <= 0)', [f'{r.strategy} {r.window} {r.scenario}' for r in cf.itertuples()], cf.total_cost_over_raw_price_pnl.tolist(), True)
    chart('turnover_by_fold', 'Two-sided turnover / fold starting equity', [f'{r.strategy} {r.window} {r.scenario}' for r in cf.itertuples()], cf.turnover_over_starting_equity.tolist())
    report(classification, rf, ff, rg, yf, dd, cf, rs, fs)
    after = frozen_hashes()
    preservation = {'passed': before == after, 'checked_files': len(before),
                    'changed': [p for p in before if before[p] != after.get(p)],
                    'before_sha256': before, 'after_sha256': after}
    (ROOT/'W01_W02_preservation.json').write_text(json.dumps(preservation, indent=2), encoding='utf-8')
    if not preservation['passed']:
        raise AssertionError('Frozen artifacts changed')
    validation = {'baseline_checks': len(checks), 'baseline_pass': ok,
                  'rolling_rows': len(rf), 'forward_rows': len(ff), 'cost_rows': len(cf),
                  'calendar_rows': len(yf), 'preserved_files': len(before), 'preservation_pass': True,
                  'rolling_count_pass': len(rf)==30, 'forward_count_pass': len(ff)==15,
                  'cost_count_pass': len(cf)==45, 'boundary_no_reset': True,
                  'true_oos': False, 'new_market_data_downloads': False}
    (ROOT/'output_validation.json').write_text(json.dumps(validation, indent=2), encoding='utf-8')
    outputs = {str(p): gate.sha(p) for p in ROOT.rglob('*') if p.is_file()}
    (ROOT/'manifest.json').write_text(json.dumps({'status':'W03_COMPLETE', 'python':platform.python_version(),
        'pandas':pd.__version__, 'numpy':np.__version__, 'config_sha256':gate.sha('config/w03_temporal_robustness.yaml'),
        'code_sha256':gate.sha(__file__), 'sha256':outputs}, indent=2), encoding='utf-8')
    print(pd.DataFrame(classification)[['strategy','classification','routing_reasons']].to_string(index=False), flush=True)


def report(classification, rolling, folds, regimes, years, episodes, costs, rs, fs):
    p = ['# W03 — Temporal Robustness & Walk-Forward Cycle', '',
         'W03의 모든 분석은 W01/W02에서 이미 관찰한 2020-09-13 ~ 2026-10-02 데이터에 대한 historical temporal robustness 검증이다. Forward Fold는 unseen/true OOS 또는 live validation이 아니다. 진정한 forward evidence는 2026-10-02 이후 새로 생성되는 데이터에서 별도로 축적한다.', '',
         'RESULT: Baseline reproduction PASS. W01 거래 원장·Equity CSV와 바이트 일치, W02 Equity CSV 일치, 지표 relative tolerance 1e-8, raw/processed/기존 artifact 해시 검증. 전략/데이터/비용/위험규칙 변경 없음.', '',
         '| 전략 | 판정 | Rolling positive | Forward positive | Forward return | Forward PF | 최근 두 Fold return | 최근 두 Fold 평균 거래수익률 |',
         '|---|---|---|---|---|---|---|---|']
    for c in classification:
        p.append(f"| {c['strategy']} | {c['classification']} | {int(c['rolling_positive_count'])}/{int(c['rolling_valid_count'])} | {int(c['forward_positive_count'])}/{int(c['forward_valid_count'])} | {c['forward_return']:.2%} | {c['forward_pf']:.3f} | {c['recent_two_return']:.2%} | {c['recent_two_expectancy_return']:.2%} |")
    p += ['', '## 계산 정의와 실행 전 고정한 해석', '',
          '- 모든 시간은 UTC. Rolling: 18개월/6개월 step 10개. Forward: 2021-09-13 16:00부터 2026-09-13 16:00까지 1년씩 5개. 잔여구간은 FORWARD_STUB이며 판정에서 제외.',
          '- 포지션·현금·전략 state는 연속 운용한다. Bar-open [start,end) 구간의 가격 성과는 start Equity mark와 (start,end] close marks를 사용한다. 실제 평가구간 끝 2026-10-02 12:00만 기존 END_OF_TEST 정산을 포함한다. Formal fold 경계에는 정산하지 않는다.',
          '- Trade PF/Expectancy는 entry>=start AND exit<end인 완결 거래만 사용. 경계 거래는 Equity에는 반영하고 거래 지표에서 제외한다. 10건 미만은 descriptive only; 10~19건은 valid이나 LOW_TEMPORAL_SAMPLE.',
          '- Expectancy Return은 양쪽 비용을 차감한 return_pct의 산술평균이며 CSV에서 소수 비율. PF는 양수 net USDT PnL 합/음수 net USDT PnL 절댓값 합. 무손실/무거래 PF는 null로 유지하며 positive 판정을 입증하지 못한다.',
          '- 전체 Forward aggregate는 전체 5년 span 내부 완결 거래를 한 번 집계하므로 내부 Fold crossing을 포함한다. 최근 두 Fold의 합산 Trade 지표는 F4/F5 완결 거래를 합쳐 재계산한다. Fold PF나 평균수익률을 단순 평균하지 않는다.',
          '- Regime Equity는 분리된 bar 수익률의 조건부 복리 진단. Regime MDD/Sharpe는 연속 달력 운용의 MDD/Sharpe가 아니다. 거래는 Entry Regime으로 전체 거래를 귀속하며 Equity PnL 귀속과 구분한다. 초기 관측 부족 구간은 UNAVAILABLE.',
          '- Direction: 직전 bar까지 90일 index return, ±20%. RV30도 shift(1); 기준은 평가 대상 RV보다 앞선 365일의 75 percentile로 현재 bar와 평가 대상 RV 모두 제외. 확보하지 못한 구간은 VOL_REGIME_UNAVAILABLE.',
          '- Cost B/C는 동일한 연속 History로 state를 만든 후 Forward Fold 5개만 진단. Fee/slippage/turnover는 각 Fold에 발생한 entry/exit leg별 집계로 경계 거래의 비용도 포함. Raw price PnL은 mark-to-market net delta + fee + slippage bridge이며 raw PnL<=0이면 비용비율은 null.',
          '- 명세 12의 PASS_WITH_FLAGS와 13의 HOLD 조건이 겹치는 경우 13에 명시된 YEAR_CONCENTRATION/LONG_DRAWDOWN을 HOLD로 우선 처리한다. REGIME_DEPENDENCY/TRADE_CONCENTRATION은 진단 flag이며 단독 자동 Reject 아님. “비용에서 거의 사라짐” 등 수치가 없는 조건에 새 임계값을 임의 추가하지 않았다.',
          '- SEVERE_LONG_DRAWDOWN은 명세대로 24개월 초과 또는 sample end 미회복. 짧은 미회복 episode도 이 flag 대상이며 episode 길이를 함께 제시한다. Severe flag 단독은 PASS 제한/HOLD이고 Hard Reject 사유가 아니다.',
          '- Trade Concentration Top5는 거래수가 20 이상일 때만 flag. Calendar concentration은 2021~2025 전체 연도의 양수 Equity delta를 기준으로 계산; 나머지 full year 수익률은 해당 연도 return을 복리 연결.',
          '- Overlap Rolling Window는 독립 표본이 아니며 positive ratio는 성공확률이 아니다. BTC/ETH/SOL 생존자 편향, 4H OHLC 체결 근사, 거래소 최소수량/호가/부분체결 미모형 한계가 남는다.', '']
    for c in classification:
        tag = c['strategy']
        r, f = rolling[rolling.strategy==tag], folds[folds.strategy==tag]
        d = episodes[episodes.strategy==tag]
        direction = regimes[(regimes.strategy==tag)&(regimes.regime_type=='direction')]
        p += [f'## {tag} — {c["strategy_key"]}', '', '**FACT**', '',
              'Binance Spot BTC/ETH/SOL 4H, 독립된 전략별 100,000 USDT shared portfolio. Baseline Parameter, ATR20×3 stop, risk 0.5%, asset cap 33.3%, fee10/slip5 bps 동결. 10 Rolling Window와 5 Forward Fold.', '',
              '**RESULT**', '', f"Rolling positive {int(c['rolling_positive_count'])}/{int(c['rolling_valid_count'])}; median CAGR {r.cagr.median():.2%}, median Sharpe {r.sharpe.median():.3f}, 최저/최고 Window return {r.total_return.min():.2%}/{r.total_return.max():.2%}.", '',
              '| Fold | Return | MDD | Sharpe | PF | 평균 거래수익률 | 거래수 | 경계 거래 | Positive |',
              '|---|---|---|---|---|---|---|---|---|']
        for m in f.itertuples():
            p.append(f'| {m.window} | {m.total_return:.2%} | {m.mdd:.2%} | {m.sharpe:.3f} | {m.profit_factor:.3f} | {m.expectancy_return:.2%} | {m.trade_count} | {m.boundary_crossing_trade_count} | {m.positive} |')
        p += ['', f"Forward aggregate return {c['forward_return']:.2%}, PF {c['forward_pf']:.3f}, 평균 거래수익률 {c['forward_expectancy_return']:.2%}, Sharpe {c['forward_sharpe']:.3f}. 최근 F4/F5 합산 return {c['recent_two_return']:.2%}, PF {c['recent_two_pf']:.3f}, 평균 거래수익률 {c['recent_two_expectancy_return']:.2%}.", '',
              f"Moderate cost aggregate PF {c['moderate_forward_pf']:.3f}, 평균 거래수익률 {c['moderate_forward_expectancy_return']:.2%}. 연속 Full sample 최대 수중기간 {d.time_under_water_days.max():.1f}일. 최근 미회복 episode: " + '; '.join(f"peak {x.peak_time}, depth {x.drawdown_depth:.2%}, {x.time_under_water_days:.1f}일" for x in d[d.censored].itertuples()), '',
              '**INTERPRETATION**', '',
              '전체기간 양수 성과와 개별 시간구간의 반복성을 분리해서 판단했다. 최근 두 Fold 및 비용을 반영한 Edge, 낮은 거래수, 수익 집중도와 회복 지연을 함께 확인해야 한다. 시간구간 성과가 약해도 Parameter를 변경하지 않았다.', '',
              'Direction Regime의 Equity PnL 귀속: ' + '; '.join(f'{x.regime} {x.net_pnl:,.2f} USDT' for x in direction.itertuples()) + '.', '',
              f"관측된 Rolling 최대 연속손실 {int(r.max_consecutive_losses.max())}, Forward 최대 {int(f.max_consecutive_losses.max())}. 짧은 손실 또는 stop exit는 횡보/돌파실패의 proxy일 뿐 구조적 원인을 확정하지 않는다.", '']
        if tag=='T3':
            a = costs[(costs.strategy==tag)&(costs.scenario=='A')]
            p += [f'T3 Baseline Fold turnover/starting equity 범위 {a.turnover_over_starting_equity.min():.2f}~{a.turnover_over_starting_equity.max():.2f}배. 비용 총액 {a.total_cost_usdt.sum():,.2f} USDT. 실전 유동성과 주문 제약은 별도 Paper execution 검증이 필요하다.', '']
        p += ['**RISK FLAGS**', '', c['flags'] or '없음', '', '**CLASSIFICATION**', '',
              c['classification'] + '; routing reasons: ' + (c['routing_reasons'] or '모든 필수조건 충족'), '',
              '**NEXT STEP**', '',
              ('현재 version 검증 종료. 수정 시 Strategy Builder에서 새 version을 만들고 W01부터 검증.' if c['classification']=='W03_REJECT' else
               'Parameter 변경 없이 새 데이터 관찰 및 Failure Study. Genuine Forward/Paper 성과를 추가 확인하고 재검토.' if c['classification']=='W03_HOLD' else
               'Genuine Forward Validation/Paper Trading 후보. APPROVED 또는 실전 투입 승인이 아님.'), '']
    p += ['## Figures', '']
    for name in ['rolling_cagr','rolling_mdd','rolling_sharpe','rolling_expectancy','forward_return','forward_sharpe','regime_performance','calendar_return','drawdown_duration','rolling_trade_count','cost_drag_by_fold','turnover_by_fold']:
        p += [f'![{name}](figures/{name}.png)', '']
    p += ['## Reproduction', '', '```powershell', 'python -m pip install -r requirements_w03.txt', 'python -m unittest discover -s tests -v', 'python -m alpha_lab.w03', 'python -m alpha_lab.w03_verify', '```', '',
          '완료된 W03는 덮어쓰지 않는다. 재실행 시 별도 output root를 사용한다. Registry는 TESTING이며 APPROVED로 변경하지 않았다.']
    (ROOT/'W03_report.md').write_text('\n'.join(p), encoding='utf-8')


if __name__ == '__main__':
    main()
