"""Run one frozen baseline snapshot; no tuning or parameter search."""
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
from .data import SYMBOLS, validate
from .strategies import STRATEGY_REGISTRY
from .engine import run_portfolio, BacktestConfig
from .metrics import calculate
from .audit import audit


def generate_segments(strategy, df):
    # Reset indicator history after missing source candles; never interpolate prices.
    groups = df.index.to_series().diff().ne(pd.Timedelta(hours=4)).cumsum()
    pieces = []
    for _, segment in df.groupby(groups):
        signal = strategy.generate(segment)
        signal.loc[signal.index[:strategy.warmup_bars], ['entry_long', 'exit_long']] = False
        pieces.append(signal)
    return pd.concat(pieces)


def main():
    root = Path('results/cycle01')
    root.mkdir(parents=True, exist_ok=True)
    # Mandatory test gate, including failure output in a saved artifact.
    test = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                          text=True, capture_output=True)
    (root / 'unit_tests.txt').write_text(test.stdout + test.stderr)
    if test.returncode:
        raise RuntimeError('Synthetic unit tests failed; baseline blocked')
    data_root = Path('data/cycle01')
    validation = json.loads((data_root / 'validation.json').read_text())
    data = {}
    for s in SYMBOLS:
        for page in validation[s]['pages']:
            raw_file = data_root / 'raw' / page['file']
            if hashlib.sha256(raw_file.read_bytes()).hexdigest() != page['sha256']:
                raise ValueError('Raw source page hash mismatch')
        path = data_root / f'{s}_4h.csv'
        if hashlib.sha256(path.read_bytes()).hexdigest() != validation[s]['clean_sha256']:
            raise ValueError('Clean data hash mismatch')
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        validate(df, allow_gaps=True)
        data[s] = df
    end = min(d.index[-1] for d in data.values())
    # Find common continuous suffix, then exclude the largest frozen warmup.
    common_raw_start = max(d.index[0] for d in data.values())
    for d in data.values():
        gaps = d.index.to_series().diff().gt(pd.Timedelta(hours=4))
        if gaps.any():
            common_raw_start = max(common_raw_start, d.index[gaps.to_numpy()][-1])
    common = {s: d.loc[common_raw_start:end] for s, d in data.items()}
    for d in common.values():
        validate(d)
    warmup = max(s.warmup_bars for s in STRATEGY_REGISTRY.values())
    start = common_raw_start + pd.Timedelta(hours=4 * warmup)
    comparisons, diagnostics, all_contributions, audits = [], [], [], {}

    def save_run(key, scope, signals, begin, finish, gaps=False):
        ledger, curve = run_portfolio(signals, begin, finish, strategy_key=key, allow_source_gaps=gaps)
        audits[f'{scope}/{key}'] = audit(ledger, curve)
        metrics, contributions = calculate(ledger, curve, begin)
        dest = root / scope / key
        dest.mkdir(parents=True, exist_ok=True)
        ledger.to_csv(dest / 'trade_ledger.csv', index=False)
        curve.to_csv(dest / 'equity_curve.csv')
        (dest / 'metrics.json').write_text(json.dumps(metrics, indent=2, allow_nan=False))
        pd.DataFrame(contributions).to_csv(dest / 'asset_contribution.csv', index=False)
        for c in contributions:
            all_contributions.append({'strategy': key, 'scope': scope, **c})
        print(key, scope, 'CAGR', round(metrics['cagr'], 4), 'MDD', round(metrics['mdd'], 4), 'trades', metrics['trade_count'], flush=True)
        return {'strategy': key, 'scope': scope, **metrics}

    for key, strategy in STRATEGY_REGISTRY.items():
        # Indicators use only common raw sample; identical initialization and performance windows.
        signals = {s: generate_segments(strategy, d) for s, d in common.items()}
        comparisons.append(save_run(key, 'common_portfolio', signals, start, end))
        for s, d in data.items():
            signals = generate_segments(strategy, d)
            begin = d.index[strategy.warmup_bars]
            diagnostics.append(save_run(key, f'full_history/{s}', {s: signals}, begin, end, True))
    pd.DataFrame(comparisons).to_csv(root / 'primary_comparison.csv', index=False)
    pd.DataFrame(diagnostics).to_csv(root / 'secondary_diagnostics.csv', index=False)
    pd.DataFrame(all_contributions).to_csv(root / 'asset_contribution.csv', index=False)
    (root / 'audit.json').write_text(json.dumps(audits, indent=2))
    (root / 'primary_data_validation.json').write_text(json.dumps({'status': 'PASS',
        'common_raw_start': str(common_raw_start), 'primary_start': str(start),
        'last_bar_open': str(end), 'warmup_bars_excluded': warmup,
        'symbols': {s: {'rows': len(d), 'missing_bars': 0, 'duplicates': 0,
                         'utc': True, 'finite_ohlcv': True, 'valid_ohlc': True} for s, d in common.items()}}, indent=2))
    files = list(Path('alpha_lab').glob('*.py')) + list(Path('tests').glob('*.py'))
    manifest = {'status': 'BASELINE_COMPLETE_NEEDS_REVIEW', 'config': vars(BacktestConfig()),
                'common_raw_start': str(common_raw_start), 'primary_start': str(start),
                'last_bar_open': str(end), 'warmup_bars': warmup,
                'python': platform.python_version(), 'pandas': pd.__version__, 'numpy': np.__version__,
                'source_snapshot': json.loads((data_root / 'snapshot.json').read_text()),
                'code_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                'data_sha256': {s: validation[s]['clean_sha256'] for s in SYMBOLS},
                'warnings': ['Full-history source gaps: indicators reset, missing next-open orders cancelled; carried positions mark only observed bars. Gap-spanning returns distort annualized 4H volatility ratios; secondary diagnostic only.',
                             '33.3% cap applies at entry; passive appreciation can exceed it. No rule-changing rebalance.',
                             '0.5% is stop-distance sizing before costs and gap losses, not guaranteed realized loss.',
                             'Terminal liquidation at last confirmed close includes fee/slippage.',
                             'Fractional units; exchange filters and live liquidity not modeled.']}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (root / 'strategy_registry.json').write_text(json.dumps({key: {
        'id': key, 'version': '0.1', 'status': 'TESTING', 'review': 'NEEDS_REVIEW',
        'parameters': vars(s.config), 'warmup_bars': s.warmup_bars,
        'universe': list(SYMBOLS), 'timeframe': '4H',
        'atr_period': 20, 'initial_stop_multiple': 3,
        'primary_metrics': next(m for m in comparisons if m['strategy'] == key),
        'oos_result': None, 'paper_result': None, 'live_result': None,
        'source': 'docs/frozen_strategy_builder.md',
        'implementation_sha256': hashlib.sha256(Path('alpha_lab/strategies.py').read_bytes()).hexdigest()
    } for key, s in STRATEGY_REGISTRY.items()}, indent=2))
    report = ['# Alpha Lab Baseline Cycle 01', '', 'RESULT: first frozen baseline backtest; NEEDS_REVIEW. No optimization, OOS approval, paper or live result.', '',
              f'Primary common raw sample: {common_raw_start} to {end}. Performance: {start} to {end + pd.Timedelta(hours=4)} (UTC).', '',
              '| Strategy | CAGR | MDD | Sharpe | PF | Trades | Exposure |', '|---|---:|---:|---:|---:|---:|---:|']
    for m in comparisons:
        report.append(f"| {m['strategy']} | {m['cagr']:.2%} | {m['mdd']:.2%} | {m['sharpe']:.3f} | {m['profit_factor']:.3f} | {m['trade_count']} | {m['exposure']:.2%} |")
    report += ['', 'All requested metrics: primary_comparison.csv and secondary_diagnostics.csv. Trade ledgers, equity curves and asset contributions: per-run folders.', '',
               '## Data quality', '']
    for s in SYMBOLS:
        v = validation[s]
        report.append(f"- {s}: {v['rows']} bars; {v['first']} to {v['last']}; {v['missing_bars']} unavailable source bars; {v['short_close_timestamps']} early close timestamps.")
    report += ['', '## Execution and interpretation', ''] + ['- ' + w for w in manifest['warnings']]
    report += ['', '- Shared 100,000 USDT initial capital per strategy; no strategy mixing. Simultaneous entries use common open equity and pro-rata available cash including fees.',
               '- Primary comparison excludes all common warmup bars, starts flat and requires a fresh post-start signal. ATR/EMA implementation copied unchanged from frozen Strategy Builder.',
               '- Exposure is mean close-marked position value / equity; active-bar ratio is separately provided and includes same-bar stops.',
               '- Sharpe/volatility use sample standard deviation and sqrt(2190), zero risk-free rate; Sortino uses RMS of all negative returns with zeros for non-negative returns. Calmar = CAGR / abs(MDD).',
               '- Trade PnL is USDT after both fees and adverse fills. Avg Loss is signed negative; Expectancy is mean net trade PnL. PF undefined denominator is null.',
               '- Holding bars include entry and exit bars; holding hours use open timestamps for stop fills (4H data cannot reveal exact intrabar stop time).',
               '- Asset contributions are additive net PnL / initial capital and reconcile to total portfolio return.']
    (root / 'REPORT.md').write_text('\n'.join(report), encoding='utf-8')
    outputs = list(root.rglob('*.csv')) + list(root.rglob('*.json')) + [root / 'REPORT.md', root / 'unit_tests.txt']
    (root / 'output_checksums.json').write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                                        for p in outputs if p.name != 'output_checksums.json'}, indent=2))


if __name__ == '__main__':
    main()
