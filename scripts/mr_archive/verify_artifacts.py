"""Portable, read-only archive verification. No strategy execution."""
from pathlib import Path
import csv, hashlib, json, math
R=Path(__file__).resolve().parents[2]
manifest=json.loads((R/'artifacts/mr-research/SHA256SUMS.json').read_text(encoding='utf-8'))
for path,digest in manifest.items():
    assert hashlib.sha256((R/path).read_bytes()).hexdigest()==digest,path
def rows(name):
    with (R/'results/mr_w03'/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
s=rows('MR-W03_sensitivity.csv');t=rows('MR-W03_temporal.csv');a=rows('MR-W03_asset_consistency.csv')
assert (len(s),len(t),len(a))==(55,30,132)
full={x['id']:x for x in s if x['scope']=='FULL'}
assert len(full)==11 and len({(x['id'],x['scope']) for x in s})==55
frozen=(R/'intermediate/mr_w03/frozen_preflight.md').read_bytes()
d=json.loads((R/'intermediate/mr_w03/decision.json').read_text())
assert hashlib.sha256(frozen).hexdigest()==d['freeze_sha256']
assert (R/'results/mr_w03/MR-W03_preflight.md').read_bytes().startswith(frozen)
def positive(x):return float(x['net_pnl_usdt'])>0 and float(x['profit_factor'])>1 and float(x['expectancy_usdt'])>0
base=full['BASELINE'];neighbors=[x for x in full.values() if x['family'] not in ('baseline','cost')]
assert len(neighbors)==8 and sum(map(positive,neighbors))==d['positive_neighbors']==4
for x in neighbors:
    assert sum(float(x[k])!=float(base[k]) for k in ('period','sigma','ema','stop_atr'))==1
for identity,x in full.items():
    for group in ([z for z in a if z['id']==identity and z['scope']=='FULL'],[z for z in s if z['id']==identity and z['scope'] in ('2020_2022','2023_2024','2025_2026')]):
        assert math.isclose(sum(float(z['net_pnl_usdt']) for z in group),float(x['net_pnl_usdt']),abs_tol=1e-6)
assert d['decision']=='HOLD' and not any(d['reject_gates'].values()) and not all(d['pass_gates'].values())
print('ARCHIVE_CHECK_PASS: hashes; original Freeze; 11 scenarios; CSV rows 55/30/132; original HOLD preserved. Backtests run: 0. Registry changes: 0.')
