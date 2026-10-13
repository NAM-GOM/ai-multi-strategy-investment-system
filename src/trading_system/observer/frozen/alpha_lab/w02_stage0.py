"""Read-only W01 reproduction gate; never invoke cycle.main (it overwrites W01)."""
import hashlib
import json
import math
from pathlib import Path

import pandas as pd
from .cycle import generate_segments
from .engine import run_portfolio, BacktestConfig
from .metrics import calculate
from .strategies import STRATEGY_REGISTRY
from .data import validate

ROOT = Path('results/w02')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def frozen_files():
    paths = list(Path('data/cycle01').rglob('*')) + list(Path('results/cycle01').rglob('*'))
    manifest = json.loads(Path('results/cycle01/manifest.json').read_text())
    paths += [Path(p) for p in manifest['code_sha256']]
    return {str(p): sha(p) for p in paths if p.is_file() and '__pycache__' not in str(p)}

def reproduce():
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path('results/cycle01/manifest.json').read_text())
    checks, baselines, data = [], {}, {}
    def check(name, passed, detail=''):
        checks.append({'check': name, 'passed': bool(passed), 'detail': detail})
    for path, expected in manifest['code_sha256'].items():
        check('code:' + path, sha(path) == expected)
    output_hashes = json.loads(Path('results/cycle01/output_checksums.json').read_text())
    for path, expected in output_hashes.items():
        if 'common_portfolio' in path:
            check('reference:' + path, sha(path) == expected)
    validation = json.loads(Path('data/cycle01/validation.json').read_text())
    for symbol, expected in manifest['data_sha256'].items():
        path = Path('data/cycle01') / (symbol + '_4h.csv')
        check('data:' + symbol, sha(path) == expected)
        for page in validation[symbol]['pages']:
            p = Path('data/cycle01/raw') / page['file']
            check('raw:' + p.name, sha(p) == page['sha256'])
        # Match W01 parsing: default pandas float parser, not a new representation.
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        data[symbol] = frame.loc[manifest['common_raw_start']:manifest['last_bar_open']]
        validate(data[symbol])
    check('cutoff', pd.Timestamp(manifest['last_bar_open']) + pd.Timedelta(hours=4)
          <= pd.Timestamp(manifest['source_snapshot']['cutoff_ms'], unit='ms', tz='UTC'))
    check('date_limit', pd.Timestamp(manifest['last_bar_open']) < pd.Timestamp('2026-10-03', tz='UTC'))
    if all(c['passed'] for c in checks):
        for key, strategy in STRATEGY_REGISTRY.items():
            signals = {s: generate_segments(strategy, d) for s, d in data.items()}
            ledger, curve = run_portfolio(signals, manifest['primary_start'], manifest['last_bar_open'],
                                          BacktestConfig(**manifest['config']), strategy_key=key)
            metrics, _ = calculate(ledger, curve, pd.Timestamp(manifest['primary_start']))
            reference = Path('results/cycle01/common_portfolio') / key
            # CSV byte equality includes order, timestamps, symbols, reasons, every price and quantity.
            check(key + ':trade_ledger_exact', ledger.to_csv(index=False).encode() == (reference / 'trade_ledger.csv').read_bytes())
            check(key + ':equity_curve_exact', curve.to_csv().encode() == (reference / 'equity_curve.csv').read_bytes())
            expected = json.loads((reference / 'metrics.json').read_text())
            for field, value in expected.items():
                actual = metrics[field]
                passed = math.isclose(actual, value, rel_tol=1e-8, abs_tol=0) if isinstance(value, float) else actual == value
                check(key + ':' + field, passed, f'expected={value}; actual={actual}')
            baselines[key] = (ledger, curve, metrics, signals)
    pd.DataFrame(checks).to_csv(ROOT / 'baseline_reproduction.csv', index=False)
    return all(c['passed'] for c in checks), manifest, data, baselines

if __name__ == '__main__':
    ok, _, _, baseline = reproduce()
    print('BASELINE_REPRODUCTION', 'PASS' if ok else 'W02_INVALID')
    for key, (_, _, m, _) in baseline.items():
        print(key, m['cagr'], m['mdd'], m['trade_count'])
