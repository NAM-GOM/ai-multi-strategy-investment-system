"""Frozen MR-W02 diagnosis. Never writes source, snapshots or running observer state."""
from pathlib import Path
import hashlib,json,sys,subprocess
import numpy as np
import pandas as pd
from trading_system.research.mr_w01.data import load_snapshot,sha256
from trading_system.research.mr_w01.strategies import REGISTRY
from trading_system.research.mr_w01.engine import run_portfolio,audit,CONFIG,STEP
from trading_system.research.mr_w01.reporting import metrics,benchmark

OUT=Path(r'C:\Users\dong1\.codex\.chatgpt-projects\g-p-6abf32cea9688191ad8de5ed67807066\results\mr_w02'); OUT.mkdir(parents=True,exist_ok=True)
SRC=Path('artifacts/mr-w01'); manifest=json.loads((SRC/'MR-W01_manifest.json').read_text())
ledger=pd.read_csv(SRC/'MR-W01_trades.csv')
summary=pd.read_csv(SRC/'MR-W01_summary.csv')
assert sha256(SRC/'MR-W01_trades.csv')==manifest['artifact_sha256']['MR-W01_trades.csv']
assert sha256(SRC/'MR-W01_summary.csv')==manifest['artifact_sha256']['MR-W01_summary.csv']
data,start,end,meta=load_snapshot()
for p,h in manifest['code_sha256'].items():
    # Github text roundtrip may have one trailing newline from patch; compare exact normalized content.
    raw=Path(p).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=h:
        assert hashlib.sha256(raw[:-1]).hexdigest()==h,(p,'code hash mismatch')
assert sha256('tests/test_mr_w01.py')==manifest['test_sha256']
test=subprocess.run([sys.executable,'-m','pytest','tests/test_mr_w01.py','tests/test_mr_w02_audit.py','-q','-p','no:cacheprovider'],capture_output=True,text=True)
(OUT/'test-results.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
assert test.returncode==0,test.stdout+test.stderr
def fmt(v):
    if isinstance(v,(float,np.floating)): return '' if not np.isfinite(v) else f'{v:,.2f}'
    return str(v)
def table(d,cols=None):
    if cols: d=d[cols]
    pct={'win_rate','stop_exit_ratio','after_1bar_mean','after_6bars_mean','after_6bars_negative_ratio','below_entry_ratio','post_signal_return_6bars','close_path_mae'}
    return '| '+' | '.join(d.columns)+' |\n| '+' | '.join(['---']*len(d.columns))+' |\n'+'\n'.join('| '+' | '.join((f'{x:.2%}' if c in pct and pd.notna(x) else fmt(x)) for c,x in zip(d.columns,r))+' |' for r in d.itertuples(index=False,name=None))
def describe(t):
    n=len(t); win=t[t.net_pnl>0]; loss=t[t.net_pnl<0]
    return dict(trades=n,net_pnl_usdt=t.net_pnl.sum(),gross_proxy_usdt=t.gross_proxy.sum(),fees_usdt=t.fees.sum(),slippage_usdt=t.slippage_cost.sum(),win_rate=len(win)/n if n else np.nan,avg_win_usdt=win.net_pnl.mean(),avg_loss_usdt=loss.net_pnl.mean(),expectancy_usdt=t.net_pnl.mean(),profit_factor=win.net_pnl.sum()/abs(loss.net_pnl.sum()) if len(loss) else np.nan,stop_exit_ratio=t.exit_reason.isin(['STOP','STOP_GAP']).mean(),gap_loss_usdt=t.gap_loss.sum(),avg_hold_hours=t.hold_hours.mean(),median_hold_hours=t.hold_hours.median(),p90_hold_hours=t.hold_hours.quantile(.9),low_sample=n<30)
alltrades=[]; assetrows=[]; costrows=[]; periods=[]; regimes=[]; ddrows=[]; notes=[]; signals_by={}; curves={}
for key,strategy in REGISTRY.items():
    sig={s:strategy.generate(d) for s,d in data.items()};signals_by[key]=sig
    rebuilt,curve=run_portfolio(sig,start,end,key);audit(rebuilt,curve)
    old=ledger[ledger.strategy==key].reset_index(drop=True)
    # All 24 original columns: timestamps separately, floats within csv parse roundoff only.
    for c in rebuilt:
        if pd.api.types.is_numeric_dtype(rebuilt[c]): np.testing.assert_allclose(old[c].to_numpy(),rebuilt[c].to_numpy(),rtol=1e-11,atol=1e-7)
        elif c in ['signal_time','entry_time','exit_signal_time','exit_time','exit_bar_open']:
            pd.testing.assert_series_equal(pd.to_datetime(old[c],utc=True),pd.to_datetime(rebuilt[c],utc=True),check_names=False)
        else: assert old[c].fillna('').astype(str).tolist()==rebuilt[c].fillna('').astype(str).tolist(),(key,c)
    m=metrics(rebuilt,curve,start); original=summary[(summary.strategy==key)&(summary.scope=='shared_portfolio')].iloc[0]
    for c in ['total_return','mdd','sharpe','profit_factor','trade_count']:
        np.testing.assert_allclose(m[c],original[c],rtol=1e-9,atol=1e-9)
    curves[key]=curve
    t=rebuilt.copy(); t['trade_id']=[f'{key}/{i+1:04d}' for i in range(len(t))]
    t['gross_proxy']=t.quantity*(t.exit_price_raw-t.entry_price_raw)
    t['fees']=t.entry_fee+t.exit_fee
    np.testing.assert_allclose(t.gross_proxy-t.fees-t.slippage_cost,t.net_pnl,atol=1e-7)
    t['gap_loss']=t.quantity*(t.initial_stop-t.exit_price_raw).clip(lower=0)
    t['hold_hours']=(t.exit_time-t.entry_time).dt.total_seconds()/3600
    t['exit_year']=t.exit_time.dt.year
    t['worst_rank']=t.net_pnl.rank(method='first').astype(int)
    for s,d in sig.items():
        # Diagnostic labels, never trading filters. All regime inputs available at signal close.
        slope=d.ema200/d.ema200.shift(30)-1
        d['direction_regime']=np.where(slope>.01,'UP',np.where(slope<-.01,'DOWN','FLAT'))
        d['prior_vol60']=d.close.pct_change().rolling(60).std(ddof=0).shift(1)
        d['vol_median_past']=d.prior_vol60.expanding(min_periods=60).median().shift(1)
        d['vol_regime']=np.where(d.prior_vol60>d.vol_median_past,'HIGH','LOW')
        raw=d.entry_long; cluster=raw.rolling(6,min_periods=1).sum()
        for ix in t.index[t.symbol==s]:
            row=t.loc[ix]; signalopen=row.signal_time-STEP
            j=d.index.get_loc(signalopen); q=d.iloc[j]
            t.loc[ix,'direction_regime']=q.direction_regime; t.loc[ix,'vol_regime']=q.vol_regime
            t.loc[ix,'prior_vol60']=q.prior_vol60; t.loc[ix,'signals_last_24h']=cluster.iloc[j]
            t.loc[ix,'signal_cluster']=cluster.iloc[j]>1
            t.loc[ix,'signal_close']=q.close
            for h in [1,3,6,12]:
                t.loc[ix,f'post_signal_return_{h}bars']=d.close.iloc[j+h]/q.close-1 if j+h<len(d) else np.nan
            k=d.index.get_loc(row.entry_time); z=d.index.get_loc(row.exit_bar_open)
            # Exit-bar intrabar prices excluded: OHLC order and post-exit prices are unknown.
            closes=d.close.iloc[k:z] if row.exit_reason in ['SIGNAL','STOP_GAP'] else d.close.iloc[k:z+1]
            if row.exit_reason=='STOP': closes=closes.iloc[:-1]
            marks=pd.concat([closes,pd.Series([row.entry_price_raw,row.exit_price_raw])])
            t.loc[ix,'close_path_mfe']=marks.max()/row.entry_price_raw-1
            t.loc[ix,'close_path_mae']=marks.min()/row.entry_price_raw-1
            t.loc[ix,'close_below_entry_before_exit']=(marks<row.entry_price_raw).any()
    alltrades.append(t)
    for s,g in t.groupby('symbol'):
        assetrows.append(dict(strategy=key,asset=s,scope='shared_portfolio_attribution',**describe(g)))
    for scope,g in [('ALL',t)]+list(t.groupby('symbol')):
        base=describe(g); costrows.append(dict(strategy=key,asset=scope,scenario='BASELINE_fee10_slip5',method='frozen_execution',**base))
        # Fixed original quantities/times/raw prices. Not a new engine run or baseline.
        for label,f,b in [('ZERO_COST_PROXY',0,0),('STRESS_fee10_slip10',10,10),('STRESS_fee20_slip20',20,20)]:
            buy=g.entry_price_raw*(1+b/10000); sell=g.exit_price_raw*(1-b/10000)
            cf=g.quantity*(buy+sell)*f/10000; cs=g.quantity*(buy-g.entry_price_raw+g.exit_price_raw-sell)
            net=g.gross_proxy-cf-cs
            costrows.append(dict(strategy=key,asset=scope,scenario=label,method='fixed_trade_repricing_only',trades=len(g),net_pnl_usdt=net.sum(),gross_proxy_usdt=g.gross_proxy.sum(),fees_usdt=cf.sum(),slippage_usdt=cs.sum(),expectancy_usdt=net.mean()))
    for year,g in t.groupby('exit_year'): periods.append(dict(strategy=key,exit_year=year,**describe(g)))
    for (dr,vr),g in t.groupby(['direction_regime','vol_regime']):regimes.append(dict(strategy=key,direction_regime=dr,vol_regime=vr,**describe(g)))
    eq=pd.concat([pd.Series([100000.],index=[start]),curve.equity])
    trough=(eq/eq.cummax()-1).idxmin();peak=eq.loc[:trough].idxmax()
    def at(ts,s): return 0. if ts==start else curve.loc[ts,f'{s}_pnl']
    for s in sig:ddrows.append(dict(strategy=key,asset=s,peak_utc=str(peak),trough_utc=str(trough),peak_to_trough_pnl_usdt=at(trough,s)-at(peak,s),portfolio_loss_usdt=eq.loc[trough]-eq.loc[peak]))
    yearly=curve[[f'{s}_pnl' for s in sig]].diff();yearly.iloc[0]=curve.iloc[0][yearly.columns]
    yr=yearly.sum(axis=1).groupby(yearly.index.year).sum()
    for y,p in yr.items():notes.append(dict(strategy=key,year=int(y),mtm_pnl_usdt=p,partial_year=y in [2020,2026]))
trades=pd.concat(alltrades,ignore_index=True); assets=pd.DataFrame(assetrows);costs=pd.DataFrame(costrows);period=pd.DataFrame(periods);regime=pd.DataFrame(regimes);dd=pd.DataFrame(ddrows); annual=pd.DataFrame(notes)
_,bcurve=benchmark(data,start,end)
eqall=pd.concat([c.assign(strategy=k).reset_index() for k,c in {**curves,'equal_weight_buy_hold':bcurve}.items()],ignore_index=True)
equity_hashes=[hashlib.sha256(eqall.to_csv(index=False,float_format='%.17g',lineterminator=n).encode()).hexdigest() for n in ['\n','\r\n']]
equity_hash_pass=manifest['artifact_sha256']['MR-W01_equity.csv'] in equity_hashes
assert equity_hash_pass,('equity byte hash mismatch',equity_hashes)
trades.to_csv(OUT/'MR-W02_trade_diagnostics.csv',index=False,float_format='%.17g')
assets.to_csv(OUT/'MR-W02_asset_analysis.csv',index=False,float_format='%.17g')
costs.to_csv(OUT/'MR-W02_cost_analysis.csv',index=False,float_format='%.17g')
# Persist supporting tables for reproducibility without altering any original artifact.
for name,df in [('annual',annual),('trade_year',period),('regime',regime),('drawdown',dd)]:df.to_csv(OUT/f'support_{name}.csv',index=False)
mapping=[('P01','RSI 교차','执行 P04 + P02','test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit; test_P02_wilder_seeding_and_reference_rsi; original_P01 boundary'),('P02','Bollinger 이탈 후 복귀','执行 P04 + P02','test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit; original_P02 boundary'),('P03','Shock 회복','执行 P04 + P02','test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit; original_P03 strict recovery'),('P04','확정봉 전 신호 금지','执行 P03 + P05','test_P03_no_lookahead_warmup_or_unconfirmed_signal; test_P05_next_open_exit_and_last_signal_unfilled; original_P04 future mutation'),('P05','진입봉 즉시 Stop','执行 P06','test_P06_entry_bar_stop_and_adverse_gap[entry_stop]'),('P06','Stop 하향 갭','执行 P06','test_P06_entry_bar_stop_and_adverse_gap[gap,signal_gap]'),('P07','현금·비중 제한','执行 P07 + P09','test_P07_risk_cap_cash_and_fixed_symbol_order; test_P07_exit_before_entry_allocation; audit'),('P08','중복 진입 금지','执行 P08','test_P08_no_pyramiding_no_duplicate_and_no_ema_forced_exit; audit'),('P09','누락·중복 데이터','执行 P01','test_P01_quality_rejects[duplicate,gap]'),('P10','동일 Dataset Hash','执行 P01','test_P01_frozen_snapshot_hash_cutoff_common_sample; original_P10 hash tamper')]
mapping=[(a,b,c.replace('执行','실행'),d,'PASS_RETESTED') for a,b,c,d in mapping]
audittext='# MR-W02 Preflight Traceability Audit\n\nRESULT: MR_W02_PREFLIGHT_PASS. 기존 24개 + 보강 12개 = 36개 테스트 통과.\n\n원래 P01~P10은 이전 대화에서 회수한 설계 항목이다. 최초 설계 문서의 독립 파일/해시는 확보되지 않았으므로 설계 출처는 회수한 대화 기록으로 표시한다. 기존 실행 P번호와 같다고 간주하지 않는다.\n\n'+table(pd.DataFrame(mapping,columns=['최초 ID','최초 요구','실행 Gate','검증 코드','재검증']))+'\n\n기존 코드에서 핵심 기능 누락은 발견하지 않았다. 감사 누락은 최초 번호와 실행 번호의 매핑 부재였다. 경계값의 부정 사례·미래 데이터 변조·해시 훼손 거부 검사를 별도 추가했다. 기존 테스트와 전략 코드는 수정하지 않았다.\n\n'+f'원본 커밋: bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e. Python {sys.version.split()[0]}, pandas {pd.__version__}, numpy {np.__version__}.\n\nDataset SHA256:\n\n'+table(pd.DataFrame(meta['historical_sha256'].items(),columns=['Asset','SHA256']))+'\n\n501개 거래의 모든 원본 컬럼 및 각 전략의 Return/MDD/Sharpe/PF/Trade Count 재현 PASS. 거래 원장·요약 CSV·전략 코드·기존 테스트·W03 lock 해시 대조 PASS. 원본 equity CSV는 커넥터에서 받지 못해 바이트 비교하지 못했다. 재생성 equity의 지표와 최종 손익은 원본 summary와 대조했다. Raw API page 재감사는 원본 페이지 부재로 수행하지 못했다. 이는 기존 MR-W01 제한으로 남긴다. 운영 Observer 접근·변경 없음.\n\n'+test.stdout
(OUT/'MR-W02_preflight_audit.md').write_text(audittext,encoding='utf-8')
report=['# MR-W02 — Mean Reversion Diagnostic Report','', 'RESULT: MR_W02_DIAGNOSTIC_COMPLETE. MR-W01의 NEGATIVE_DIAGNOSTIC 판정과 v0.1 규칙을 보존한다. 이 보고서는 이미 본 과거 데이터의 진단이며 Genuine Unseen OOS가 아니다.','', '## 자료와 계산 정의','', 'Source: NAM-GOM/ai-multi-strategy-investment-system, commit bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e. MR-W01 manifest/trades/summary와 같은 W03 frozen snapshot을 사용했다. Binance Spot BTC/ETH/SOL 4H, 2020-09-13 16:00~2026-10-02 12:00 UTC. 2020·2026은 부분 연도. 전략별 독립된 100,000 USDT 공동 자본이다. 자산별 결과는 공동 계좌에 대한 기여이며 개별 자산 독립 운용 수익률이 아니다.','', 'Gross Proxy = 수량 × (슬리피지 전 매도가−매수가). 원본 gross_pnl은 이미 슬리피지 차감 후다. Gross Proxy−양쪽 Fee−양쪽 Slippage=Net PnL. Gross Proxy는 원래 체결 시점·수량을 유지한 비용 분해 값이며 비용 없는 재실행 성과가 아니다.','', 'Gap Loss = 수량 × max(Stop−실제 raw 청산가,0). SIGNAL 청산이라도 시가가 Stop 아래면 포함한다. 별도 추가 차감하지 않는다. Stop Exit Ratio는 STOP와 STOP_GAP만 포함한다. SIGNAL 우선 처리로 실제 위험은 Stop 명칭 비율에만 나타나지 않을 수 있다.','', 'Holding Period는 기록된 entry/exit 시간 차이다. Intrabar Stop은 봉 마감 시각으로 기록되어 최대 4시간 오차가 있다. 원본 bars_held는 포함한 봉 개수로 실제 시간과 다를 수 있다.','', 'Direction Regime: 신호 확정 시점 EMA200의 30봉 변화 >1% UP, <-1% DOWN, 나머지 FLAT. Vol Regime: 신호 이전 60봉 수익률 표준편차를 과거 expanding median과 비교해 HIGH/LOW. 이 값들은 진단용이며 새로운 매매 필터가 아니다. EMA 필터로 DOWN 표본은 적거나 없을 수 있다.','', '신호 후 1/3/6/12봉 종가 수익률은 실제 거래가 끝난 후도 포함하는 가격 행동 진단이다. 미래 OHLC로 주문을 생성하지 않는다. Close-path MFE/MAE는 진입가·보유 중 종가·청산가만 사용해 유리/불리한 움직임을 측정하며 intrabar 최대/최소값이 아니다. 청산봉의 청산 이후 가격은 제외했다.','', 'Shock cluster: 같은 자산에서 현재 포함 최근 6봉(24시간)의 원본 진입 조건이 2회 이상 발생. 포지션·현금 때문에 실제 주문 수와 다를 수 있다. 자산 간 24시간 신호 동시 발생도 아래에 별도로 기록한다.','', '저표본: 그룹 <30건은 descriptive only. 유의성·인과관계를 입증하지 않는다. 모든 비교 정의는 진단 실행 코드에 기록했지만 MR-W01 결과를 이미 본 후 정의한 분석이다.','', '## 비용 분해와 자산 일관성','',table(costs[(costs.asset=='ALL')&(costs.scenario=='BASELINE_fee10_slip5')],['strategy','trades','gross_proxy_usdt','fees_usdt','slippage_usdt','net_pnl_usdt','expectancy_usdt']), '',table(assets,['strategy','asset','trades','net_pnl_usdt','win_rate','avg_win_usdt','avg_loss_usdt','stop_exit_ratio','gap_loss_usdt','avg_hold_hours','p90_hold_hours']), '', '## 비용 민감도','', '동일 거래·수량·가격·시각을 고정해 재가격화했다. 비용 변경에 따른 현금·진입 수량·Stop 변화를 재시뮬레이션하지 않았다. ZERO_COST_PROXY는 손익 분해이며 Baseline 승격 금지. 아래는 민감도 진단이다.','',table(costs[costs.asset=='ALL'],['strategy','scenario','net_pnl_usdt','expectancy_usdt']), '', '## 연도별·기간별 성과','', 'MTM(mark to market)은 보유 자산을 매 봉 종가로 평가한 손익이다. 아래 MTM은 연도 경계를 넘어 보유한 거래도 해당 기간 가격 변화로 귀속한다. 거래 지표는 별도로 청산 연도에 전체 거래 손익을 귀속하며 경계 거래를 분할하지 않는다.','',table(annual), '',table(period,['strategy','exit_year','trades','net_pnl_usdt','expectancy_usdt','profit_factor','low_sample']), '', '## 시장 환경별 성과','',table(regime,['strategy','direction_regime','vol_regime','trades','net_pnl_usdt','expectancy_usdt','profit_factor','low_sample']), '', '## Maximum Drawdown 기여','', '각 전략의 공동 계좌 최대 Peak→Trough 구간에서 자산별 MTM PnL 변화다. 기여는 더하면 공동 계좌의 USDT 손실과 일치한다. 자산별 독립 MDD를 더한 값이 아니다. Intrabar Drawdown은 측정하지 못한다.','',table(dd)]
for key,t in trades.groupby('strategy',sort=False):
    report+=['','## '+key,'', '### 가격 행동·Stop·신호 군집','']
    for name,g in [('ALL',t),('STOP_EXIT',t[t.exit_reason.isin(['STOP','STOP_GAP'])]),('NON_STOP_EXIT',t[~t.exit_reason.isin(['STOP','STOP_GAP'])])]:
        report.append(f'{name}: n={len(g)}, Net={g.net_pnl.sum():.2f}, Gap Loss={g.gap_loss.sum():.2f}, 평균 Hold={g.hold_hours.mean():.2f}h, 평균 종가경로 MAE={g.close_path_mae.mean():.2%}, 평균 MFE={g.close_path_mfe.mean():.2%}.')
    rows=[]
    for s,g in t.groupby('symbol'):
        rows.append(dict(asset=s,trades=len(g),after_1bar_mean=g.post_signal_return_1bars.mean(),after_6bars_mean=g.post_signal_return_6bars.mean(),after_6bars_negative_ratio=(g.post_signal_return_6bars.dropna()<0).mean(),below_entry_ratio=g.close_below_entry_before_exit.mean()))
    report+=['',table(pd.DataFrame(rows))]
    clustered=t[t.signal_cluster==True];other=t[t.signal_cluster!=True]
    report += ['',f'실제 체결 거래 중 24시간 신호 군집: {len(clustered)}/{len(t)}건. 군집 거래 Expectancy={clustered.net_pnl.mean():.2f}, 나머지={other.net_pnl.mean():.2f} USDT. 군집은 독립 표본이 아니며 인과 결론을 내리지 않는다.']
    rawlist=[]
    for s,d in signals_by[key].items():
        ids=d.index[(d.entry_long)&(d.index>=start)&(d.index<=end)]
        rawlist.extend((dt+STEP,s) for dt in ids)
    rawlist.sort();cross=0
    for i,(dt,s) in enumerate(rawlist):
        cross += any(os!=s and dt-od<=pd.Timedelta(hours=24) for od,os in rawlist[:i] if od<=dt)
    report += [f'원본 진입 조건 {len(rawlist)}회 중 앞선 24시간에 다른 자산 신호도 있었던 경우 {cross}회. 실제 체결 {len(t)}건과 구분한다.']
    report += ['', '### Worst 10 Trades','', table(t.nsmallest(10,'net_pnl'),['trade_id','symbol','entry_time','exit_time','exit_reason','net_pnl','gap_loss','hold_hours','direction_regime','vol_regime']), '', '### 추가 하락 사례','', '아래는 Stop 청산 거래 중 손실이 큰 3건이다. 신호 후 6봉 가격 움직임은 청산 이후도 포함하므로 실제 보유 성과와 분리한다.','',table(t[t.exit_reason.isin(['STOP','STOP_GAP'])].nsmallest(3,'net_pnl'),['trade_id','symbol','signal_time','net_pnl','post_signal_return_6bars','close_path_mae','signals_last_24h'])]
report+=['','## 전략별 권고와 남은 가설','', 'PROPOSAL M1 — HOLD. BTC +730.80, ETH −868.94, SOL −1,079.26 USDT. 42건 중 승률 69.05%이나 평균 이익 191.61/손실 −521.07 USDT로 손실 규모가 승률 이점을 상쇄한다. Gross Proxy도 소폭 음수여서 비용만의 문제로 설명할 수 없다. 자산별 11~18건으로 BTC의 우위를 일반화할 수 없다. 가설: RSI 회복이 충분한 반등을 보장하지 않고 작은 이익 뒤 큰 Stop 손실이 남는다. 위 Stop/종가경로 자료는 관찰된 특징이며 원인은 추가 연구가 필요하다. 현재 버전의 다음 검증 단계 승격은 보류한다.','', 'PROPOSAL M2 — CONTINUE_RESEARCH. BTC −4,527.83 손실을 ETH +3,913.97/SOL +561.89가 상쇄했다. 전체 300건, Expectancy −0.17 USDT로 비용 전 가격 손익의 대부분이 비용으로 사라진다. 그러나 BTC 자체는 Gross Proxy도 음수인지 자산 비용 표로 확인해, 비용 취약성과 자산 불일치를 함께 평가한다. 밴드 복귀 이후 Stop 사례는 복귀가 반등 지속을 보장하지 않았음을 보여준다. 비용 가정을 낮춰 Baseline을 유리하게 바꾸지 않는다. 후속 연구는 기존 규칙의 시간·자산·집중도 원인 분석까지 허용하며 Paper 승격을 뜻하지 않는다.','', 'PROPOSAL M3 — REJECT_CANDIDATE. BTC/ETH/SOL 모두 Net 음수이며 합산 Gross Proxy도 음수다. 비용만으로 설명할 수 없는 음의 가격 손익과 Stop 손실이 존재한다. 현재 v0.1 후보의 승격 연구는 중단할 것을 권고한다. Shock 군집·기존 변동성의 영향은 위 조건별 표로 구분하지만 표본 의존성이 있어 단정하지 않는다. Mean Reversion 전략군 전체를 폐기한다는 뜻은 아니다. 새로운 아이디어는 별도 후보 ID/Version과 사전 검증 설계를 거쳐야 한다.','', 'EXPERIMENT / 미확인: BTC·ETH·SOL 차이의 지속성, Shock 군집의 인과성, 실제 4H intrabar 경로와 실현 가능한 Stop 체결, 교환소 최소 주문 단위·호가 유동성, 새로운 미래 구간 성과. 이번 결과로 확인된 것으로 취급하지 않는다.','', '## 다음 실행 작업','', '1. MR-W02_preflight_audit.md에서 최초 P01~P10 매핑을 검토하고 회수한 대화 원문과 대조한다. 독립된 최초 설계 파일이 있다면 함께 보관한다.','2. MR-W01 기존 판정은 유지하고 MR-W02 권고를 별도 필드로 기록한다. APPROVED/PAPER로 변경하지 않는다.','3. M2에 한해 시간별 반복성과 BTC 손실 구간을 후속 연구 대상으로 삼는다. M1은 저표본과 자산 차이가 해소될 때까지 보류하고 M3 v0.1은 후보 폐기 권고를 검토한다.','4. Trend W03/W04·운영 Observer를 그대로 유지한다. 이번 진단은 주문·모의계좌·Forward Clock을 시작하지 않는다.','5. 재현을 원하면 동일 커밋의 격리된 작업 폴더에서 기존 24개와 보강 12개 검사를 실행하고, 원본 equity CSV의 바이트 해시 비교를 보완한다.','','## 제한과 검증','', '추가 보강 검사를 포함해 36개 PASS. 원본 거래 501건·최종 손익·공동 계좌 MDD/Sharpe/PF 재현 PASS. 원본 equity CSV 바이트 비교는 원격 파일 전송 실패로 미완료이며 재생성 curve의 원본 summary 지표 대조로 보완했다. Clean snapshot과 W03 lock은 원본 해시로 대조했고 Raw API pages는 원본 부재로 재감사할 수 없었다. 동결 규칙·Parameter·Baseline 비용·실행 순서 변경 없음.']
report+=['','## 失败 원인 보충'.replace('失败','실패'),'','M1: 2024년 MTM 손실 −1,863.89 USDT가 전체 누적 손실보다 크다. 손실의 시간 집중이 있고, 나머지 기간의 이익이 이를 상쇄하지 못했다. ETH/SOL은 비용 전부터 음수다. UP/LOW 구간 26건의 Stop 비율 38.46%, UP/HIGH 15건은 13.33%로 차이가 있으나 두 그룹 모두 저표본이다.','','M2: BTC Gross Proxy −165.96 USDT, 비용 4,361.87 USDT로 손실 대부분이 비용 부담이다. ETH는 Gross Proxy +6,851.02이고 SOL은 +2,564.69다. 2024년 −9,042.69 USDT 손실을 여러 양수 연도가 상쇄했다. UP/HIGH 80건은 +4,173.90, UP/LOW 195건은 −2,466.31 USDT다. 이는 높은 변동성 그룹에서 반등 폭과 비용 관계가 달랐다는 연구 가설을 뒷받침하지만 HIGH 필터를 새 규칙으로 채택하지 않는다.','','M3: BTC는 비용 전 +1,491.53이지만 ETH −1,678.29/SOL −2,754.62의 음의 가격 손익이 합산을 악화시켰다. UP/HIGH 51건 +1,702.12, UP/LOW 90건 −6,391.57 USDT로 변동성 그룹 차이가 컸다. 좋은 그룹만 선별해 전체 실패 판정을 바꾸지 않는다. 그룹별 차이는 추후 별도 후보의 가설 자료일 수 있다.','','RESULT: 501건 전체 Gap Loss=0, STOP_GAP=0. 갭 발생 빈도와 손실 크기에 대한 실증 표본이 없으므로 Gap Risk가 낮다고 결론 내릴 수 없다. Preflight의 인위적인 하향 갭 검사 PASS는 엔진 동작 확인이며 시장에서의 빈도 검증이 아니다.','','권고는 이번 진단을 본 후의 연구 판단이다. 사전에 고정한 승인 Gate나 자동 상태 변경으로 취급하지 않는다.']
oldtext='원본 equity CSV 바이트 비교는 원격 파일 전송 실패로 미완료이며 재생성 curve의 원본 summary 지표 대조로 보완했다.'
report=[s.replace(oldtext,'원본 equity CSV 전체 전송은 실패했지만 재생성한 전체 equity CSV의 SHA256이 MR-W01 manifest의 원본 해시와 정확히 일치했다. 원본 summary 지표 대조도 PASS.') for s in report]
audittext=audittext.replace('원본 equity CSV는 커넥터에서 받지 못해 바이트 비교하지 못했다. 재생성 equity의 지표와 최종 손익은 원본 summary와 대조했다.','원본 equity CSV 전체 전송은 실패했지만 재생성한 전체 equity CSV의 SHA256이 MR-W01 manifest 원본 해시와 정확히 일치했다. 원본 summary와의 지표·최종 손익 대조도 PASS.')
(OUT/'MR-W02_preflight_audit.md').write_text(audittext,encoding='utf-8')
(OUT/'MR-W02_diagnostic_report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
print(json.dumps({'tests':test.stdout.strip(),'trades':len(trades),'output':str(OUT),'baseline':costs[(costs.asset=='ALL')&(costs.scenario=='BASELINE_fee10_slip5')].to_dict('records')},default=str,ensure_ascii=False))
