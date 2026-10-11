import csv,json,hashlib,math
from pathlib import Path
R=Path(r'C:\Users\dong1\.codex\.chatgpt-projects\g-p-6abf32cea9688191ad8de5ed67807066')
O=R/'results/mr_w03';S=R/'intermediate/mr_w03'
def read(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
ss=read(O/'MR-W03_sensitivity.csv');tt=read(O/'MR-W03_temporal.csv');aa=read(O/'MR-W03_asset_consistency.csv')
assert len(ss)==55 and len(tt)==30 and len(aa)==132
full={r['id']:r for r in ss if r['scope']=='FULL'}
assert len(full)==11
base=full['BASELINE'];neighbors=[r for r in full.values() if r['family'] not in ['baseline','cost']]
for r in neighbors:
    assert sum(float(r[k])!=float(base[k]) for k in ['period','sigma','ema','stop_atr'])==1
for k,b in full.items():
    a=[r for r in aa if r['id']==k and r['scope']=='FULL']
    w=[r for r in ss if r['id']==k and r['scope'] in ['2020_2022','2023_2024','2025_2026']]
    assert math.isclose(sum(float(r['net_pnl_usdt']) for r in a),float(b['net_pnl_usdt']),abs_tol=1e-6)
    assert math.isclose(sum(float(r['net_pnl_usdt']) for r in w),float(b['net_pnl_usdt']),abs_tol=1e-6)
    for r in a+w+[b]:
        pos=float(r['net_pnl_usdt'])>0 and bool(r['profit_factor']) and float(r['profit_factor'])>1 and float(r['expectancy_usdt'])>0
        assert (r['positive']=='True')==pos
for r in tt:
    if r['kind']=='CALENDAR_YEAR' and r['scope'] in ['2021','2022','2023','2024','2025']:
        assert r['first_partial_year']=='False' and r['last_partial_year']=='False'
    if r['scope']=='2020':assert r['first_partial_year']=='True'
    if r['scope']=='2026':assert r['last_partial_year']=='True'
assert all(r['indicator_initial_unavailable_bars']=='38' for r in ss if r['id']=='ema_240')
assert all(int(r['boundary_trade_count'])>=0 for r in ss)
d=json.loads((S/'decision.json').read_text())
assert d['decision']=='HOLD' and d['positive_neighbors']==4
assert not any(d['reject_gates'].values()) and not all(d['pass_gates'].values())
freeze=(S/'frozen_preflight.md').read_bytes();p=(O/'MR-W03_preflight.md').read_bytes()
assert p.startswith(freeze)
assert hashlib.sha256(freeze).hexdigest()==(S/'freeze_sha256.txt').read_text().strip()==d['freeze_sha256']
diag=read(S/'2024_comparison.csv');y=diag[0]
assert int(y['stop_count'])==25 and int(y['trade_count'])==62
for r in diag:
    assert math.isclose(float(r['stop_loss_usdt'])+float(r['nonstop_positive_pnl_usdt'])+float(r['nonstop_negative_pnl_usdt']),float(r['trade_net_pnl_usdt']),abs_tol=1e-6)
    assert math.isclose(float(r['gross_proxy_usdt'])-float(r['trade_fees_usdt'])-float(r['trade_slippage_usdt']),float(r['trade_net_pnl_usdt']),abs_tol=1e-6)
print('OUTPUT_AUDIT_PASS: 55 sensitivity,30 temporal,132 asset rows; OAT/partial-year/freeze/accounting/decision gates verified')
print(json.dumps([{'id':r['id'],'net':round(float(r['net_pnl_usdt']),2),'mdd':round(float(r['mdd'])*100,2),'PF':round(float(r['profit_factor']),3)} for r in full.values()]))
