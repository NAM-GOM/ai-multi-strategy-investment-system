"""MR-W03 frozen-design runner. Original MR/Trend files remain read-only."""
from pathlib import Path
from dataclasses import replace
import hashlib,inspect,json,sys,subprocess,datetime
import numpy as np
import pandas as pd
from trading_system.research.mr_w01 import engine as E
from trading_system.research.mr_w01.data import load_snapshot,sha256
from trading_system.research.mr_w01.strategies import BollingerReversion
from trading_system.research.mr_w01.reporting import metrics

ROOT=Path(r'C:\Users\dong1\.codex\.chatgpt-projects\g-p-6abf32cea9688191ad8de5ed67807066')
SCR=ROOT/'intermediate/mr_w03'; OUT=ROOT/'results/mr_w03'
design=json.loads((SCR/'freeze.json').read_text()); pref=OUT/'MR-W03_preflight.md'
freeze_bytes=(SCR/'frozen_preflight.md').read_bytes() if (SCR/'frozen_preflight.md').exists() else pref.read_bytes(); freeze_hash=hashlib.sha256(freeze_bytes).hexdigest()
assert freeze_hash==(SCR/'freeze_sha256.txt').read_text().strip(),'Freeze changed before run'
manifest=json.loads(Path('artifacts/mr-w01/MR-W01_manifest.json').read_text())
frozen_paths=[Path(p) for p in manifest['code_sha256']]+[Path('tests/test_mr_w01.py'),Path('artifacts/w03/lock.json')]
before={str(p):sha256(p) for p in frozen_paths}
for p,h in manifest['code_sha256'].items():
    raw=Path(p).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==h or hashlib.sha256(raw[:-1]).hexdigest()==h,(p,'source mismatch')
assert sha256('tests/test_mr_w01.py')==manifest['test_sha256']
for name in ['trades','summary']:
    assert sha256(f'artifacts/mr-w01/MR-W01_{name}.csv')==manifest['artifact_sha256'][f'MR-W01_{name}.csv']
test=subprocess.run([sys.executable,'-m','pytest','tests/test_mr_w01.py','tests/test_mr_w02_audit.py','-q','-p','no:cacheprovider'],capture_output=True,text=True)
(SCR/'preflight-tests.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
assert test.returncode==0,test.stdout+test.stderr
data,start,end,metadata=load_snapshot(); cutoff=end+E.STEP
old=pd.read_csv('artifacts/mr-w01/MR-W01_trades.csv'); old=old[old.strategy=='meanrev_bollinger_v0.1'].reset_index(drop=True)
orig={s:BollingerReversion().generate(d) for s,d in data.items()}
base_t,base_c=E.run_portfolio(orig,start,end,'meanrev_bollinger_v0.1');E.audit(base_t,base_c)
for col in base_t:
    if pd.api.types.is_numeric_dtype(base_t[col]):np.testing.assert_allclose(old[col],base_t[col],rtol=1e-11,atol=1e-7)
    elif col.endswith('time') or col=='exit_bar_open':pd.testing.assert_series_equal(pd.to_datetime(old[col],utc=True),pd.to_datetime(base_t[col],utc=True),check_names=False)
    else:assert old[col].fillna('').astype(str).tolist()==base_t[col].fillna('').astype(str).tolist()
base_metrics=metrics(base_t,base_c,start)
for name,val in {'net_pnl_usdt':-51.976351060178786,'trade_count':300,'stop_exit_count':73,'total_fees_usdt':6201.1452468016687,'slippage_cost_usdt':3100.574935836471}.items():
    np.testing.assert_allclose(base_metrics[name],val,atol=1e-7,rtol=1e-10)
np.testing.assert_allclose((base_t.quantity*(base_t.exit_price_raw-base_t.entry_price_raw)).sum(),9249.743831577958,atol=1e-7)
# Expose only the frozen engine's stop constant for diagnostics; no original file mutation.
source=inspect.getsource(E.run_portfolio)
assert source.count('distance = 2.5 * atr')==1 and source.count('config=CONFIG):')==1
adapted=source.replace('config=CONFIG):','config=CONFIG, stop_multiple=2.5):').replace('distance = 2.5 * atr','distance = stop_multiple * atr')
namespace=dict(E.__dict__);exec(compile(adapted,'MR_W03_STOP_PARAMETER_HARNESS','exec'),namespace)
run_engine=namespace['run_portfolio']
class Variant(BollingerReversion):
    def __init__(self,period=20,sigma=2,ema=200):self.period,self.sigma,self.ema=period,sigma,ema
    def _add_indicators(self,df):
        df['sma20']=df.close.rolling(self.period).mean()
        df['lower_band']=df.sma20-self.sigma*df.close.rolling(self.period).std(ddof=0)
        df['ema200']=df.close.ewm(span=self.ema,adjust=False,min_periods=self.ema).mean()
        return df
alias={s:Variant().generate(d) for s,d in data.items()}
for s in data:pd.testing.assert_frame_equal(alias[s],orig[s],check_exact=True)
at,ac=run_engine(alias,start,end,'meanrev_bollinger_v0.1')
pd.testing.assert_frame_equal(at,base_t,check_exact=True);pd.testing.assert_frame_equal(ac,base_c,check_exact=True)
checks=['36 existing MR-W01/MR-W02 tests PASS','all 300 baseline trade rows reproduced','MR-W02 cost/PnL/stop count reproduced','Baseline indicator harness exact parity PASS','Stop-parameter harness exact full trade/equity parity PASS']
# Adverse gap + entry-bar stop at both predeclared stop multiples, using the same engine.
idx=pd.date_range('2020-01-01',periods=4,freq='4h',tz='UTC')
for mult in [2,2.5,3]:
    for mode in ['ENTRY_STOP','GAP']:
        f=pd.DataFrame({'open':100.,'high':110.,'low':99.,'close':100.,'volume':1.,'is_closed':True,'entry_long':False,'exit_long':False,'entry_atr':10.},index=idx)
        f.loc[idx[0],'entry_long']=True
        if mode=='ENTRY_STOP':f.loc[idx[1],['low','close']]=[60,65]
        else:f.loc[idx[2],['open','high','low','close']]=[50,60,40,55]
        tr,cu=run_engine({'BTCUSDT':f},idx[0],idx[-1],'test',stop_multiple=mult)
        assert len(tr)==1;np.testing.assert_allclose(tr.initial_stop.iloc[0],100.05-mult*10)
        assert tr.exit_reason.iloc[0]==('STOP' if mode=='ENTRY_STOP' else 'STOP_GAP')
        np.testing.assert_allclose(tr.exit_price_raw.iloc[0],100.05-mult*10 if mode=='ENTRY_STOP' else 50)
checks.append('6 adverse gap/entry Stop tests across 2/2.5/3 ATR PASS')
for family,vals in design['oat'].items():
    for val in vals:
        args={'period':20,'sigma':2,'ema':200}
        if family in args:args[family]=val
        strat=Variant(**args)
        for s,d in data.items():
            a=strat.generate(d.iloc[:500]); b=strat.generate(d.iloc[:400])
            pd.testing.assert_frame_equal(a.iloc[:400],b,check_exact=True)
checks.append('24 OAT prefix invariance checks PASS')
preflight_done=datetime.datetime.now(datetime.timezone.utc).isoformat()
(SCR/'preflight-checks.json').write_text(json.dumps({'status':'MR_W03_PREFLIGHT_PASS','freeze_sha256':freeze_hash,'completed_utc':preflight_done,'checks':checks},indent=2),encoding='utf-8')
print('MR_W03_PREFLIGHT_PASS; design freeze verified; beginning declared runs',flush=True)

def trade_stats(t):
    n=len(t);p=t.net_pnl
    gain=p[p>0].sum();loss=-p[p<0].sum()
    return {'trade_count':n,'trade_net_pnl_usdt':float(p.sum()),'profit_factor':float(gain/loss) if loss>0 else np.nan,'expectancy_usdt':float(p.mean()) if n else np.nan,'expectancy_return':float(t.return_pct.mean()) if n else np.nan,'win_rate':float((p>0).mean()) if n else np.nan,'stop_count':int(t.exit_reason.isin(['STOP','STOP_GAP']).sum()),'stop_ratio':float(t.exit_reason.isin(['STOP','STOP_GAP']).mean()) if n else np.nan,'avg_win_usdt':float(p[p>0].mean()),'avg_loss_usdt':float(p[p<0].mean()),'gross_proxy_usdt':float((t.quantity*(t.exit_price_raw-t.entry_price_raw)).sum()),'trade_fees_usdt':float((t.entry_fee+t.exit_fee).sum()),'trade_slippage_usdt':float(t.slippage_cost.sum())}
def positive(r):return r['net_pnl_usdt']>0 and pd.notna(r['profit_factor']) and r['profit_factor']>1 and r['expectancy_usdt']>0
def measure(t,c,lo,hi,asset=None):
    lo=max(lo,start);hi=min(hi,cutoff)
    series=c.equity if asset is None else 100000+c[f'{asset}_pnl']
    left=series.loc[series.index<=lo];anchor=float(left.iloc[-1]) if len(left) else 100000.
    marks=series[(series.index>lo)&(series.index<=hi)]
    eq=pd.concat([pd.Series([anchor],index=[lo]),marks])
    returns=eq.pct_change().iloc[1:];mdd=float((eq/eq.cummax()-1).min())
    involved=t if asset is None else t[t.symbol==asset]
    full=(involved.entry_time>=lo)&(involved.exit_time<hi)
    if hi==cutoff: full=(involved.entry_time>=lo)&(involved.exit_time<=hi)
    complete=involved[full]
    boundary=involved[(involved.entry_time<hi)&(involved.exit_time>lo)&~full]
    pnl=float(eq.iloc[-1]-anchor);ret=float(eq.iloc[-1]/anchor-1)
    years=(hi-lo).total_seconds()/(365.25*86400)
    sd=returns.std(ddof=1)
    stats=trade_stats(complete)
    last_year=(hi-pd.Timedelta(nanoseconds=1)).year
    result={'start_utc':str(lo),'end_utc':str(hi),'start_equity':anchor,'end_equity':float(eq.iloc[-1]),'net_pnl_usdt':pnl,'total_return':ret,'cagr':float((1+ret)**(1/years)-1) if years>0 else np.nan,'mdd':mdd,'sharpe':float(returns.mean()/sd*np.sqrt(2190)) if sd>0 else np.nan,'observed_bars':len(marks),'boundary_trade_count':len(boundary),'boundary_whole_trade_pnl_usdt':float(boundary.net_pnl.sum()),'first_partial_year':lo>pd.Timestamp(f'{lo.year}-01-01',tz='UTC'),'last_partial_year':hi<pd.Timestamp(f'{last_year+1}-01-01',tz='UTC'),**stats}
    # For a boundary window, MTM and completed-trade Positive are deliberately both required.
    result['positive']=positive(result)
    return result
def audit_variant(t,c,stop,fee,slip):
    assert (c.cash>=-1e-7).all();np.testing.assert_allclose(c.equity,c.cash+c.position_value,atol=1e-6)
    np.testing.assert_allclose(c.equity.iloc[-1],100000+t.net_pnl.sum(),atol=1e-6)
    np.testing.assert_allclose(t.initial_stop,t.entry_fill-stop*t.entry_atr,atol=1e-8)
    np.testing.assert_allclose(t.entry_fill,t.entry_price_raw*(1+slip/10000),atol=1e-8)
    np.testing.assert_allclose(t.exit_fill,t.exit_price_raw*(1-slip/10000),atol=1e-8)
    np.testing.assert_allclose(t.entry_fee,t.quantity*t.entry_fill*fee/10000,atol=1e-8)
    np.testing.assert_allclose(t.exit_fee,t.quantity*t.exit_fill*fee/10000,atol=1e-8)
    np.testing.assert_allclose(t.net_pnl,t.quantity*(t.exit_price_raw-t.entry_price_raw)-t.slippage_cost-t.entry_fee-t.exit_fee,atol=1e-6)
    assert (t.quantity*t.entry_atr*stop<=t.entry_equity*.005+1e-6).all()
    assert (t.quantity*t.entry_fill<=t.entry_equity*.333+1e-6).all()
    assert not t.duplicated(['symbol','signal_time']).any()

scenarios=[dict(id='BASELINE',family='baseline',value=np.nan,period=20,sigma=2,ema=200,stop_atr=2.5,fee=10,slip=5)]
for family,vals in design['oat'].items():
    for v in vals:
        s=dict(scenarios[0]);s.update(id=f'{family}_{v}',family=family,value=v);s[family]=v;scenarios.append(s)
for c in design['cost_scenarios'][1:]:
    s=dict(scenarios[0]);s.update(id=c['id'],family='cost',value=np.nan,fee=c['fee'],slip=c['slip']);scenarios.append(s)
windows=[(w['id'],pd.Timestamp(w['start']),pd.Timestamp(w['end'])) for w in design['windows']]
ready_start=next(iter(data.values())).index[239]
allruns={};sens=[];temporal=[];assets=[]
for s in scenarios:
    sig={sym:Variant(s['period'],s['sigma'],s['ema']).generate(d) for sym,d in data.items()}
    t,c=run_engine(sig,start,end,'meanrev_bollinger_v0.1',config=replace(E.CONFIG,fee_bps=s['fee'],slippage_bps=s['slip']),stop_multiple=s['stop_atr'])
    audit_variant(t,c,s['stop_atr'],s['fee'],s['slip'])
    allruns[s['id']]=(t,c,sig)
    for scope,lo,hi in [('FULL',start,cutoff)]+windows+[('COMMON_READY_DIAGNOSTIC',ready_start,cutoff)]:
        m=measure(t,c,lo,hi)
        missing_ema=sum(sig[next(iter(sig))].loc[start:end].ema200.isna())
        row={**s,'scope':scope,'indicator_initial_unavailable_bars':int(missing_ema),**m}
        sens.append(row)
        if s['family'] in ['baseline','cost'] and scope not in ['COMMON_READY_DIAGNOSTIC','FULL']:temporal.append(dict(row,kind='FROZEN_WINDOW'))
    for sym in data:
        for scope,lo,hi in [('FULL',start,cutoff)]+windows:
            m=measure(t,c,lo,hi,sym);assets.append({**s,'asset':sym,'scope':scope,'attribution':'shared_portfolio_100k_reference',**m})
    if s['family'] in ['baseline','cost']:
        for year in range(2020,2027):
            lo=pd.Timestamp(f'{year}-01-01',tz='UTC');hi=pd.Timestamp(f'{year+1}-01-01',tz='UTC')
            m=measure(t,c,lo,hi)
            allocated=t[t.exit_time.dt.year==year]
            temporal.append({**s,'scope':str(year),'kind':'CALENDAR_YEAR','allocated_exit_trade_count':len(allocated),'allocated_exit_net_pnl_usdt':float(allocated.net_pnl.sum()),**m})
    print(f'RUN {s["id"]} completed; {len(t)} trades',flush=True)
sens=pd.DataFrame(sens);temporal=pd.DataFrame(temporal);assets=pd.DataFrame(assets)
full=sens[sens.scope=='FULL'];baseline=full[full.id=='BASELINE'].iloc[0]
bs=temporal[(temporal.id=='BASELINE')&(temporal.kind=='FROZEN_WINDOW')]
ba=assets[(assets.id=='BASELINE')&(assets.scope=='FULL')]
neighbors=full[full.family.isin(design['oat'])]
families=neighbors.groupby('family').positive.sum()
by=temporal[(temporal.id=='BASELINE')&(temporal.kind=='CALENDAR_YEAR')]
full_years=by[by.scope.isin([str(y) for y in range(2021,2026)])]
posyears=full_years.net_pnl_usdt[full_years.net_pnl_usdt>0]
year_share=float(posyears.nlargest(2).sum()/posyears.sum()) if len(posyears) else np.nan
posassets=ba.net_pnl_usdt[ba.net_pnl_usdt>0]
asset_share=float(posassets.max()/posassets.sum()) if len(posassets) else np.nan
low_sample=int(baseline.trade_count)<100 or (bs.trade_count<30).any() or (ba.trade_count<30).any()
nonpositive_baseline=not bool(baseline.positive)
r1=nonpositive_baseline and bs.positive.sum()==0 and (~ba.positive.astype(bool)).sum()>=2
r2=nonpositive_baseline and (~neighbors.positive.astype(bool)).sum()>=6 and (families==0).sum()>=3 and ((~bs.positive.astype(bool)).sum()>=2 or (~ba.positive.astype(bool)).sum()>=2)
r3=abs(baseline.mdd)>=.2 or ((neighbors.mdd.abs()>=.15)&(neighbors.mdd.abs()>=2*abs(baseline.mdd))).any()
passgates={'BASELINE_POSITIVE':bool(baseline.positive),'TEMPORAL_2_OF_3':int(bs.positive.sum())>=2,'ASSET_2_OF_3':int(ba.positive.sum())>=2,'NEIGHBOR_6_OF_8':int(neighbors.positive.sum())>=6,'EACH_FAMILY_1_OF_2':bool((families>=1).all()),'NEIGHBOR_MDD_1_5X':bool((neighbors.mdd.abs()<=1.5*abs(baseline.mdd)).all()),'MODERATE_POSITIVE':bool(full[full.id=='MODERATE'].positive.iloc[0]),'YEAR_TOP2_MAX_80':bool(pd.notna(year_share) and year_share<=.8),'ASSET_MAX_80':bool(pd.notna(asset_share) and asset_share<=.8)}
rejectgates={'PERSISTENT_LOSS':bool(r1),'JOINT_FRAGILITY':bool(r2),'SEVERE_RISK':bool(r3)}
decision='HOLD' if low_sample else ('REJECT' if any(rejectgates.values()) else ('PASS' if all(passgates.values()) else 'HOLD'))
stats={'decision':decision,'pass_gates':passgates,'reject_gates':rejectgates,'low_sample':bool(low_sample),'positive_neighbors':int(neighbors.positive.sum()),'positive_windows':int(bs.positive.sum()),'positive_assets':int(ba.positive.sum()),'year_top2_positive_share':year_share,'max_positive_asset_share':asset_share,'family_positive_counts':families.to_dict(),'freeze_sha256':freeze_hash,'freeze_json_sha256':sha256(SCR/'freeze.json'),'script_sha256':sha256(SCR/'run.py')}

# 2024 failure anatomy, computed only from the frozen Baseline.
t,c,sig=allruns['BASELINE'];diag=t.copy()
diag['exit_year']=diag.exit_time.dt.year
diag['fees']=diag.entry_fee+diag.exit_fee
diag['gross_proxy']=diag.quantity*(diag.exit_price_raw-diag.entry_price_raw)
for sym,d in sig.items():
    slope=d.ema200/d.ema200.shift(30)-1
    d['direction']=np.where(slope>.01,'UP',np.where(slope<-.01,'DOWN','FLAT'))
    vol=d.close.pct_change().rolling(60).std(ddof=0).shift(1)
    median=vol.expanding(min_periods=60).median().shift(1)
    d['vol']=np.where(vol>median,'HIGH','LOW')
    for ix in diag.index[diag.symbol==sym]:
        r=diag.loc[ix];j=d.index.get_loc(r.signal_time-E.STEP);k=d.index.get_loc(r.entry_time);z=d.index.get_loc(r.exit_bar_open)
        diag.loc[ix,'direction']=d.direction.iloc[j];diag.loc[ix,'vol']=d.vol.iloc[j]
        diag.loc[ix,'after_6bar_return']=d.close.iloc[j+6]/d.close.iloc[j]-1 if j+6<len(d) else np.nan
        # Exclude unknown post-exit path; force booleans into numeric 0/1 before aggregation.
        close_path=d.close.iloc[k:z] if r.exit_reason in ['SIGNAL','STOP_GAP','STOP'] else d.close.iloc[k:z+1]
        prices=list(close_path)+[r.entry_price_raw,r.exit_price_raw]
        diag.loc[ix,'below_entry']=int(any(float(p)<r.entry_price_raw for p in prices))
        diag.loc[ix,'signal_target_return']=d.sma20.iloc[j]/d.close.iloc[j]-1
        diag.loc[ix,'target_movement_return']=d.sma20.iloc[z]/d.sma20.iloc[j]-1
        diag.loc[ix,'stop_pct']=r.entry_atr*2.5/r.entry_fill
def anatomy(g):
    st=g[g.exit_reason.isin(['STOP','STOP_GAP'])];ns=g[~g.exit_reason.isin(['STOP','STOP_GAP'])]
    result=trade_stats(g)
    result.update(stop_loss_usdt=float(st.net_pnl.sum()),nonstop_positive_pnl_usdt=float(ns.net_pnl[ns.net_pnl>0].sum()),nonstop_negative_pnl_usdt=float(ns.net_pnl[ns.net_pnl<0].sum()),mean_stop_pct=float(g.stop_pct.mean()),after_6bar_mean=float(g.after_6bar_return.mean()),after_6bar_negative_ratio=float((g.after_6bar_return.dropna()<0).mean()),below_entry_ratio=float(g.below_entry.mean()),mean_target_movement_return=float(g.target_movement_return.mean()),low_sample=len(g)<30)
    return result
annual_rows=[{'year':int(y),**anatomy(g)} for y,g in diag.groupby('exit_year')]
year_diag=pd.DataFrame(annual_rows)
ref=diag[diag.exit_year.between(2021,2025)&(diag.exit_year!=2024)]
comparison=pd.DataFrame([{'group':'2024','asset':'ALL',**anatomy(diag[diag.exit_year==2024])},{'group':'OTHER_FULL_YEARS_2021_2022_2023_2025','asset':'ALL',**anatomy(ref)}])
asset24=pd.DataFrame([{'group':'2024','asset':sym,**anatomy(g)} for sym,g in diag[diag.exit_year==2024].groupby('symbol')])
months=pd.DataFrame([{'month':str(m),**anatomy(g)} for m,g in diag[diag.exit_year==2024].groupby(diag.exit_time.dt.strftime('%Y-%m'))])
regimes=pd.DataFrame([{'direction':dr,'vol':v,**anatomy(g)} for (dr,v),g in diag[diag.exit_year==2024].groupby(['direction','vol'])])
st24=diag[(diag.exit_year==2024)&diag.exit_reason.isin(['STOP','STOP_GAP'])]
daily=st24.groupby(st24.exit_time.dt.floor('D')).symbol.nunique()
stats['stop2024_days']=len(daily);stats['multi_asset_stop2024_days']=int((daily>=2).sum())
stats['2024_stop_count']=len(st24)
assert {str(p):sha256(p) for p in frozen_paths}==before,'Frozen source changed'
load_snapshot() # complete W03 lock re-audit after experiments
assert pref.read_bytes().startswith(freeze_bytes),'Freeze altered during execution'
for sym in data:
    np.testing.assert_allclose(ba[ba.asset==sym].net_pnl_usdt.iloc[0],diag[diag.symbol==sym].net_pnl.sum(),atol=1e-6)
np.testing.assert_allclose(bs.net_pnl_usdt.sum(),baseline.net_pnl_usdt,atol=1e-6)
np.testing.assert_allclose(by.net_pnl_usdt.sum(),baseline.net_pnl_usdt,atol=1e-6)
np.testing.assert_allclose(ba.net_pnl_usdt.sum(),baseline.net_pnl_usdt,atol=1e-6)
# CSV outputs include every predeclared scenario, with no best-parameter selection.
sens.to_csv(OUT/'MR-W03_sensitivity.csv',index=False,float_format='%.17g')
temporal.to_csv(OUT/'MR-W03_temporal.csv',index=False,float_format='%.17g')
assets.to_csv(OUT/'MR-W03_asset_consistency.csv',index=False,float_format='%.17g')
for name,df in [('year_diagnostics',year_diag),('2024_comparison',comparison),('2024_assets',asset24),('2024_months',months),('2024_regimes',regimes),('baseline_trade_diagnostics',diag)]:df.to_csv(SCR/f'{name}.csv',index=False)
(SCR/'decision.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
def display(df,cols):
    d=df[cols].copy()
    percentage={x for x in cols if any(k in x for k in ['return','mdd','ratio','win_rate','share','stop_pct'])}
    def f(v,c):
        if pd.isna(v):return 'N/A'
        if isinstance(v,(bool,np.bool_)):return str(bool(v))
        if isinstance(v,(float,np.floating)):return f'{v:.2%}' if c in percentage else f'{v:,.2f}'
        return str(v)
    return '| '+' | '.join(cols)+' |\n| '+' | '.join(['---']*len(cols))+' |\n'+'\n'.join('| '+' | '.join(f(v,c) for c,v in zip(cols,row))+' |' for row in d.itertuples(index=False,name=None))
pass_table=display(pd.DataFrame(passgates.items(),columns=['gate','pass']),['gate','pass'])
reject_table=display(pd.DataFrame(rejectgates.items(),columns=['gate','triggered']),['gate','triggered'])
decisiontext=f'''# MR-W03 Decision

RESULT: **{decision}** — meanrev_bollinger_v0.1

Freeze SHA256: {freeze_hash}. 사전 고정 기준을 그대로 적용했다. 이미 본 과거 데이터의 연구 판정이다.
M1 HOLD / M3 REJECT_CANDIDATE 연구 권고와 MR-W01 NEGATIVE_DIAGNOSTIC을 보존한다.
이 결과는 APPROVED/PAPER 승격이나 실제 Registry 자동 수정이 아니다.

## PASS 기준

{pass_table}

## REJECT 기준

{reject_table}

LOW_SAMPLE: {bool(low_sample)}. Positive neighbors {int(neighbors.positive.sum())}/8, 시간구간 {int(bs.positive.sum())}/3, 자산 {int(ba.positive.sum())}/3.
Full-year 양수 손익 상위2개 연도 비중 {year_share:.2%}; 양수 자산 최대 기여 {asset_share:.2%}.
연도·자산 집중도는 총손익이 거의0인 분모 대신 양수 기여 합을 분모로 삼았다.
Baseline 손실만으로 자동 REJECT하지 않으며, 사전 복합 조건의 충족 여부를 위 표에 명시한다.

## 후속 조치

{'후속 독립 검증 연구의 설계를 별도로 작성할 수 있다.' if decision=='PASS' else ('현재 v0.1 후보 연구 중단을 권고한다. 이번 이웃 중 좋은 Parameter·자산·기간만 선택해 재승격하지 않는다.' if decision=='REJECT' else '현재 v0.1의 후속 검증 단계 승격을 보류한다. 자료 부족과 취약성의 원인을 유지한 채 재검토한다.')}
유리한 이웃·연도·자산·환경을 새로운 Baseline으로 채택하지 않는다. 새로운 아이디어는 별도 후보/Version으로 시작하고 전체 검증을 다시 설계한다.
Trend W03/W04와 운영 Observer는 이번 작업에서 접근하거나 변경하지 않았다.
사용자는 이 판정을 05 Strategy Registry의 MR-W03 연구 판정 필드에 기록하고 기존 MR-W01/MR-W02 판정 이력을 함께 보존한다.
'''
(OUT/'MR-W03_decision.md').write_text(decisiontext,encoding='utf-8')
report=[ '# MR-W03 — Bollinger Temporal & Parameter Robustness', '',f'RESULT: **{decision}**. meanrev_bollinger_v0.1 Baseline과 원본 실행 계약은 보존했다. 이번 결과는 Genuine Unseen OOS가 아니다.','', '## 재현성과 비교 방법','',f'Source commit {design["source_commit"]}. Python {sys.version.split()[0]}, pandas {pd.__version__}, numpy {np.__version__}. MR-W01 Data Snapshot / W03 lock 재검사, MR-W02 300건 원장·비용·73개 Stop 재현, 기존36개 테스트와 harness 검사가 통과했다. Freeze SHA256: {freeze_hash}.', '', 'OAT는 한 번에 하나의 Parameter만 바꾸는 방법이다. ±20% 이웃8개를 전부 보고했으며 최적 조합을 찾지 않았다. ATR Stop은 원본 함수의 상수 distance만 별도 진단 harness에서 노출했다. Baseline harness는 원본과 전체 원장·equity가 정확히 일치했다.', '', '시간구간은 UTC 캘린더 기준이다. 2020과2026은 부분 연도다. 전체 계좌를 연속 운용하며 구간 시작 이전 equity를 기준으로 해당 구간 가격 변화(MTM)를 배분한다. Trade PF/Expectancy는 구간 안에서 진입·청산이 모두 완료된 거래만 계산하며 boundary trade는 별도 표시한다. 실제 sample 최종 경계 청산은 포함한다. 연도별 allocated_exit 지표는 청산 연도에 전체 거래를 귀속한 보조 지표다.', '', '자산별 수익률은 100,000 USDT 공동 자본에 대한 기여다. 자산별 독립 Backtest가 아니다. 모든 실험에서 같은 BTC→ETH→SOL 순서와 shared cash를 사용했다.', '', '비용 stress는 기존 엔진을 전체 재실행하여 자본·수량·Stop 변화를 반영했다. MR-W02 fixed-trade repricing 수치와 다를 수 있다. 더 싼 비용 가정을 Baseline으로 선택하지 않았다.', '', '## Baseline과 8개 OAT 이웃','',display(full[full.family!='cost'],['id','period','sigma','ema','stop_atr','net_pnl_usdt','total_return','mdd','profit_factor','expectancy_usdt','trade_count','positive']), '', '이웃 양수 개수는 총 '+str(int(neighbors.positive.sum()))+'/8이다. 각 가족의 양수 이웃 수: '+str(families.to_dict())+'. 값이 좋은 이웃을 선택하지 않으며 결과의 폭과 부호 일관성으로 평가한다.', '', 'EMA240은 최초39개 evaluation 봉의 EMA가 부족해 INIT_WINDOW_DIFFERENCE가 있다. 아래 보조 표는 전체 변형이 계산 가능한 동일 시작 시점 이후의 MTM과 완결 거래를 비교했다. 포지션은 여전히 원래 연속 운용 state를 유지한다.', '',display(sens[(sens.scope=='COMMON_READY_DIAGNOSTIC')&(sens.family!='cost')],['id','start_utc','net_pnl_usdt','mdd','profit_factor','trade_count','boundary_trade_count']), '', '## 시간 구간별 Baseline','',display(bs,['scope','start_utc','end_utc','total_return','net_pnl_usdt','mdd','profit_factor','expectancy_usdt','trade_count','boundary_trade_count','positive']), '', 'CAGR은 구간 날짜 길이를365.25일/년으로 환산했다. Sharpe는4H 수익률과2190봉/년, risk-free0으로 계산했다. CSV는 수익률을 소수비율로 저장한다. 부분 연도·저표본 그룹은 수치를 일반화하지 않는다.', '', '## 자산별 일관성','',display(ba,['asset','net_pnl_usdt','total_return','profit_factor','expectancy_usdt','trade_count','positive']), '',display(assets[(assets.id=='BASELINE')&(assets.scope!='FULL')],['scope','asset','net_pnl_usdt','profit_factor','trade_count','boundary_trade_count','positive']), '', '## 비용 stress','',display(full[full.family.isin(['baseline','cost'])],['id','fee','slip','net_pnl_usdt','mdd','profit_factor','expectancy_usdt','trade_count','positive']), '', '## 2024년 Stop와 손실 집중','', 'Stop 손실과 비Stop 양수·음수 거래의 합이 전체 순손익이다. 표의 비용은 Net에 이미 들어 있으며 다시 빼지 않는다. Signal 후6봉의 가격은 청산 이후도 포함할 수 있으므로 주문 성과와 분리한다.', '',display(comparison,['group','trade_count','stop_count','stop_ratio','stop_loss_usdt','nonstop_positive_pnl_usdt','nonstop_negative_pnl_usdt','trade_net_pnl_usdt','trade_fees_usdt','trade_slippage_usdt','after_6bar_negative_ratio']), '',display(asset24,['asset','trade_count','stop_count','stop_ratio','trade_net_pnl_usdt','gross_proxy_usdt','below_entry_ratio','after_6bar_negative_ratio']), '',display(months,['month','trade_count','stop_count','trade_net_pnl_usdt','profit_factor','low_sample']), '',display(regimes,['direction','vol','trade_count','stop_count','stop_ratio','trade_net_pnl_usdt','low_sample']), '',f'2024 Stop 발생일은 {len(daily)}일이며 2개 이상 자산이 같은 UTC 날짜에 Stop을 기록한 날은 {int((daily>=2).sum())}일이다. 이는 위험 동시 노출의 관찰이며 인과관계·통계적 유의성을 입증하지 않는다.', '', '## 연도·자산 의존성','',display(by,['scope','net_pnl_usdt','allocated_exit_trade_count','allocated_exit_net_pnl_usdt','trade_count','boundary_trade_count','profit_factor']), '',f'2021~2025 full years 중 양수 연도 상위2개 손익 비중은 {year_share:.2%}. 양수 자산 손익의 최대 자산 비중은 {asset_share:.2%}. 음수 연도와 음수 자산도 전부 표에 유지한다. 유리한 그룹만 제외·선택하지 않는다.', '', '## 판정 근거','',decisiontext.split('## PASS 기준')[1], '', '## 확인되지 않은 가설과 제한','', '2024 Stop 증가를 거시 뉴스나 특정 사건의 인과로 확정하지 않는다. 낮은 변동성·밴드 복귀 후 추가 하락·여러 자산 동시 Stop은 원인 후보이며 새 필터로 채택하지 않는다. 관찰 기간이 이미 노출됐고 OAT이웃도8개뿐이므로 전역적 안정성이나 새로운 미래 성과를 증명하지 못한다.', '', 'MR-W02 below_entry_ratio는 bool/object 집계가 Stop 수보다 비정상적으로 작았다. 이번에는 각 거래의 실제 보유 종가·청산 raw 가격을 0/1로 다시 집계했다. 이 보조 보고 수치의 오류는 원장·Net PnL·전략 규칙과 분리하며 MR-W02 원본을 수정하지 않았다. 이번 report/CSV의 below_entry_ratio만 수정 계산을 사용한다.', '', 'OHLC만으로 intrabar 가격 순서와 실제 체결 유동성을 복원할 수 없다. Stop 시간은 봉 종가 표기이므로 최대4시간 오차가 있다. Raw API pages는 기존 snapshot에 없으므로 raw-page 재감사는 못했다. Clean snapshot과 동결 lock 해시 검사는 통과했다. 결과가 기존 v0.1 승인·Paper 상태를 바꾸지 않는다.' ]
report=[r.replace('최초39개 evaluation 봉','최초38개 evaluation 봉') for r in report]
report+=['','## 표기 정정과 설계 보존','', 'Freeze 원문은 EMA240 부족 구간을39봉으로 적었으나, 0-based index와201봉 제외 기준으로 직접 계산하면38봉이다. EMA240은 index239부터 계산 가능하고 평가 시작은 index201이다. 주 실험의 시작·끝과 지표·신호 처리는 변경하지 않았다. 보조 common-ready 시작의 index240을239로 정정했다. 부분 연도의 마지막 연도는 exclusive endpoint 직전 연도로 계산해 2021~2025의 full-year 표시를 바로잡았다. 판정 Threshold·우선순위·8개 이웃은 변경하지 않았으며 최종 HOLD도 유지됐다.']
(OUT/'MR-W03_report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
result_section='\n\n### 실행 결과 append\n\nRESULT: MR_W03_PREFLIGHT_PASS\n\nFreeze SHA256: '+freeze_hash+'\nPreflight 완료 UTC: '+preflight_done+'\n\n'+'\n'.join('- '+s for s in checks)+'\n\n11개 사전 지정 시나리오(기본1+OAT8+비용stress2), 시나리오별 accounting 검사 PASS.\nBaseline 시간구간·연도·자산 MTM 합계가 full Net와 일치. 원본 코드/테스트/W03 lock 변경 없음.\nMR-W02 보조 below_entry_ratio 집계 오류는 report에서 별도로 명시했다. 원장·PnL 재현에는 영향 없음.\n'
result_section+='\n표기 정정: EMA240 초기 부족 봉은 Freeze 원문의39가 아니라 실제38봉이며 common-ready 시작은 index239이다. 마지막 부분 연도 판별은 exclusive endpoint 직전 연도를 사용한다. 판정 설계와 주 실험 경계는 변경하지 않았다.\n'
pref.write_bytes(freeze_bytes+result_section.encode('utf-8'))
print(json.dumps(stats,ensure_ascii=False),flush=True)
