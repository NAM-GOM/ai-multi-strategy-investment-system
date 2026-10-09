"""W02 diagnostic cycle. Frozen W01 inputs; no ranking, parameter selection or downloads."""
import csv
import html
import json
import math
from pathlib import Path
import platform
import numpy as np
import pandas as pd
from .w02_stage0 import reproduce, ROOT, frozen_files, sha
from .w02_engine import run_portfolio as diagnostic_run
from .engine import BacktestConfig
from .metrics import calculate
from .cycle import generate_segments
from .strategies import (MATrendStrategy, MATrendConfig, DonchianTrendStrategy,
                         DonchianConfig, TSMOMTrendStrategy, TSMOMConfig)

KEYS = {'T1': 'trend_ma_v0.1', 'T2': 'trend_donchian_v0.1', 'T3': 'trend_tsmom_v0.1'}
FIG = ROOT / 'figures'

def save(name, rows):
    pd.DataFrame(rows).to_csv(ROOT / name, index=False)

def loss_run(pnl):
    longest = current = 0
    for value in pnl:
        current = current + 1 if value < 0 else 0
        longest = max(longest, current)
    return longest

def enrich(ledger, data):
    rows = []
    for _, trade in ledger.iterrows():
        t = trade.to_dict()
        d = data[t['symbol']]
        begin, end = pd.Timestamp(t['entry_time']), pd.Timestamp(t['exit_time'])
        # SIGNAL/STOP_GAP exits occur at open: that candle is not held.
        # Intrabar STOP: only known earlier bars and the exit price are safe for extrema.
        prior = d.loc[(d.index >= begin) & (d.index < end)]
        if t['exit_reason'] == 'END_OF_TEST':
            prior = d.loc[(d.index >= begin) & (d.index < end)]
        high = max(t['entry_fill'], t['exit_price_raw'], prior.high.max() if len(prior) else t['entry_fill'])
        low = min(t['entry_fill'], t['exit_price_raw'], prior.low.min() if len(prior) else t['entry_fill'])
        upper = high
        ambiguous = t['exit_reason'] == 'STOP'
        if ambiguous:
            upper = max(high, d.loc[end, 'high'])
        peak_stamp = prior.high.idxmax() if len(prior) and prior.high.max() >= t['exit_price_raw'] else end
        mfe = high / t['entry_fill'] - 1
        giveback = (high - t['exit_fill']) / t['entry_fill']
        t.update(mfe_return=mfe, mfe_upper_bound_return=upper / t['entry_fill'] - 1,
                 mae_return=low / t['entry_fill'] - 1, realized_return=t['return_pct'],
                 mfe_giveback_return=giveback, mfe_giveback_fraction=giveback / mfe if mfe > 0 else np.nan,
                 extrema_stop_bar_ambiguous=ambiguous,
                 peak_to_exit_bars=max(0, (end - peak_stamp).total_seconds() / 14400),
                 raw_price_pnl=t['net_pnl'] + t['entry_fee'] + t['exit_fee'] + t['slippage_cost'])
        rows.append(t)
    return pd.DataFrame(rows)

def aggregate(t, tag, symbol):
    pnl = t.net_pnl
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gp = float(wins.sum())
    result = dict(strategy=tag, symbol=symbol, trade_count=len(t), net_pnl=float(pnl.sum()),
                  gross_profit=gp, gross_loss=float(losses.sum()),
                  signal_exit_count=int(t.exit_reason.eq('SIGNAL').sum()),
                  stop_exit_count=int(t.exit_reason.isin(['STOP', 'STOP_GAP']).sum()),
                  terminal_exit_count=int(t.exit_reason.eq('END_OF_TEST').sum()),
                  win_rate=float(pnl.gt(0).mean()), average_win=float(wins.mean()),
                  average_loss=float(losses.mean()), expectancy=float(pnl.mean()),
                  consecutive_losses=loss_run(pnl), holding_min=float(t.bars_held.min()),
                  holding_max=float(t.bars_held.max()), holding_mean=float(t.bars_held.mean()),
                  mfe_mean=float(t.mfe_return.mean()), mae_mean=float(t.mae_return.mean()),
                  realized_return_mean=float(t.return_pct.mean()),
                  giveback_return_mean=float(t.mfe_giveback_return.mean()),
                  giveback_fraction_median=float(t.mfe_giveback_fraction.median()),
                  peak_to_exit_bars_median=float(t.peak_to_exit_bars.median()),
                  short_losing_trades_30bars=int(((pnl < 0) & (t.bars_held <= 30)).sum()),
                  total_fee=float((t.entry_fee + t.exit_fee).sum()),
                  estimated_slippage_cost=float(t.slippage_cost.sum()),
                  raw_price_pnl=float(t.raw_price_pnl.sum()),
                  turnover_initial_equity=float((t.quantity * (t.entry_fill + t.exit_fill)).sum() / 100000))
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        result['holding_p' + str(int(q * 100))] = float(t.bars_held.quantile(q))
    for k in (1, 5, 10):
        result[f'top{k}_gross_profit_share'] = float(wins.nlargest(k).sum() / gp) if gp else np.nan
    return result

def calendar(ledger, curve, tag):
    rows = []
    prev = 100000.0
    for year, c in curve.groupby(curve.index.year):
        e = c.equity.to_numpy()
        r = np.diff(np.r_[prev, e]) / np.r_[prev, e[:-1]]
        peaks = np.maximum.accumulate(np.r_[prev, e])[1:]
        t = ledger[pd.to_datetime(ledger.exit_time, utc=True).dt.year.eq(year)]
        sd = np.std(r, ddof=1) if len(r) > 1 else 0
        rows.append(dict(strategy=tag, year=year, partial_year=year in [curve.index[0].year, curve.index[-1].year],
                         return_pct=e[-1] / prev - 1, mdd=float((e / peaks - 1).min()),
                         sharpe=float(r.mean() / sd * math.sqrt(2190)) if sd else None,
                         trade_count=len(t), win_rate=float(t.net_pnl.gt(0).mean()) if len(t) else None,
                         initial_equity=prev, final_equity=e[-1]))
        prev = e[-1]
    return rows

def svg_chart(filename, title, labels, values, percent=False):
    """Exact data charts with a zero axis; no optional plotting dependency."""
    width, height = 950, max(260, 80 + len(labels) * 35)
    finite = [float(v) for v in values if v is not None and math.isfinite(v)]
    lo, hi = min([0] + finite), max([0] + finite)
    if hi == lo: hi = lo + 1
    def x(v): return 200 + 580 * (v - lo) / (hi - lo)
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
              '<rect width="100%" height="100%" fill="white"/>',
              '<g font-family="Arial" font-size="13" fill="#182233">',
              f'<text x="20" y="28" font-size="18">{html.escape(title)}</text>',
              f'<line x1="{x(0)}" x2="{x(0)}" y1="45" y2="{height - 25}" stroke="#888"/>']
    for i, (label, value) in enumerate(zip(labels, values)):
        y = 65 + 35 * i
        if value is None or not math.isfinite(value): continue
        a, b = sorted([x(0), x(value)])
        color = '#2563a6' if value >= 0 else '#c35151'
        text = f'{value:.2%}' if percent else f'{value:,.2f}'
        pieces += [f'<text x="15" y="{y+15}">{html.escape(str(label))}</text>',
                   f'<rect x="{a}" y="{y}" width="{max(1,b-a)}" height="23" fill="{color}"/>',
                   f'<text x="800" y="{y+15}">{text}</text>']
    (FIG / filename).write_text('\n'.join(pieces + ['</g></svg>']), encoding='utf-8')

def heatmap(frame, xfield, yfield, metric, filename, title):
    xs, ys = sorted(frame[xfield].unique()), sorted(frame[yfield].unique())
    vals = frame[metric]
    lo, hi = vals.min(), vals.max()
    p = ['<svg xmlns="http://www.w3.org/2000/svg" width="700" height="440">', '<rect width="100%" height="100%" fill="white"/>',
         '<g font-family="Arial" fill="#182233">', f'<text x="20" y="30" font-size="20">{title}</text>',
         f'<text x="20" y="55">Columns: {xfield}; rows: {yfield}. B = baseline</text>']
    for i, y in enumerate(ys):
        p.append(f'<text x="20" y="{140+i*85}">{y}</text>')
        for j, x in enumerate(xs):
            r = frame[(frame[xfield] == x) & (frame[yfield] == y)].iloc[0]
            v = r[metric]
            f = (v-lo) / (hi-lo) if hi > lo else .5
            color = f'rgb({int(235-160*f)},{int(245-95*f)},{int(250-35*f)})'
            xpos, ypos = 85+j*180, 95+i*85
            p += [f'<rect x="{xpos}" y="{ypos}" width="170" height="75" fill="{color}" stroke="#444" stroke-width="{3 if r.is_baseline else 1}"/>',
                  f'<text x="{xpos+20}" y="{ypos+42}">{v:.2%}</text>' if metric == 'cagr' else f'<text x="{xpos+20}" y="{ypos+42}">{v:.3f}</text>']
            if r.is_baseline: p.append(f'<text x="{xpos+145}" y="{ypos+22}">B</text>')
    for j, x in enumerate(xs): p.append(f'<text x="{100+j*180}" y="83">{x}</text>')
    (FIG / filename).write_text('\n'.join(p+['</g></svg>']), encoding='utf-8')

def main():
    # JSON is valid YAML 1.2 and needs no extra package.
    cfg = json.loads(Path('config/w02_diagnostic_sensitivity.yaml').read_text(encoding='utf-8-sig'))
    assert cfg['initial_equity'] == 100000 and cfg['risk_per_trade'] == .005 and cfg['asset_cap'] == .333
    assert cfg['atr_period'] == 20 and cfg['baseline_stop'] == 3 and cfg['cutoff_date_utc'] == '2026-10-02'
    assert cfg['signal_parameters'] == {'T1': {'fast':[40,50,60], 'slow':[160,200,240]},
                                        'T2': {'entry':[44,55,66], 'exit':[16,20,24]}, 'T3': {'lookback':[144,180,216]}}
    assert cfg['stop_multipliers'] == [2.4,3.,3.6] and cfg['cost_scenarios'] == {'A':[10,5],'B':[10,10],'C':[20,20]}
    if (ROOT / 'W02_report.md').exists():
        raise FileExistsError('W02 already exists. Preserve it; use a new output directory for a rerun.')
    frozen = frozen_files()
    ok, manifest, data, baselines = reproduce()
    if not ok:
        save('W02_summary.csv', [dict(strategy=t, classification='W02_INVALID', flags='ENGINE_MISMATCH') for t in KEYS])
        (ROOT / 'W02_report.md').write_text('# W02 — W02_INVALID\n\nRESULT: W01 reproduction failed. ENGINE_MISMATCH. All further experiments stopped. See baseline_reproduction.csv.', encoding='utf-8')
        return
    FIG.mkdir(exist_ok=True)
    start, end = pd.Timestamp(manifest['primary_start']), pd.Timestamp(manifest['last_bar_open'])
    # Extension at 3 ATR must remain byte-exact with the frozen engine before any stop experiments.
    for key, (l, c, _, signals) in baselines.items():
        dl, dc = diagnostic_run(signals, start, end, strategy_key=key)
        if dl.to_csv(index=False) != l.to_csv(index=False) or dc.to_csv() != c.to_csv():
            save('W02_summary.csv', [dict(strategy=t, classification='W02_INVALID', flags='ENGINE_MISMATCH') for t in KEYS])
            (ROOT / 'W02_report.md').write_text('# W02_INVALID\nRESULT: Diagnostic engine baseline parity failed. Experiments stopped.', encoding='utf-8')
            return
    diagnostics, assets, calendars, enriched, signals_all, stop_rows, cost_rows = [], [], [], [], {}, [], []
    for tag, key in KEYS.items():
        ledger, curve, metrics, signals = baselines[key]
        t = enrich(ledger, data)
        t.insert(0, 'strategy', tag)
        enriched.append(t)
        diagnostics.append(aggregate(t, tag, 'ALL'))
        total_abs = sum(abs(g.net_pnl.sum()) for _, g in t.groupby('symbol'))
        for symbol, g in t.groupby('symbol'):
            diagnostics.append(aggregate(g, tag, symbol))
            net = g.net_pnl.sum()
            assets.append(dict(strategy=tag, symbol=symbol, net_pnl=net,
                               return_contribution=net/100000, absolute_pnl_share=abs(net)/total_abs,
                               signed_net_pnl_share=net/t.net_pnl.sum()))
        calendars += calendar(ledger, curve, tag)
        curve.to_csv(ROOT / (tag + '_baseline_equity.csv'))
        if tag == 'T1':
            variants = [(MATrendStrategy(MATrendConfig(f, s)), dict(fast=f, slow=s), f == 50 and s == 200)
                        for f in cfg['signal_parameters']['T1']['fast'] for s in cfg['signal_parameters']['T1']['slow']]
        elif tag == 'T2':
            variants = [(DonchianTrendStrategy(DonchianConfig(e, x)), dict(entry=e, exit=x), e == 55 and x == 20)
                        for e in cfg['signal_parameters']['T2']['entry'] for x in cfg['signal_parameters']['T2']['exit']]
        else:
            variants = [(TSMOMTrendStrategy(TSMOMConfig(n)), dict(lookback=n), n == 180) for n in cfg['signal_parameters']['T3']['lookback']]
        rows = []
        for strategy, params, is_base in variants:
            ss = {s: generate_segments(strategy, d) for s, d in data.items()}
            l, c = diagnostic_run(ss, start, end, strategy_key=key)
            m, _ = calculate(l, c, start)
            rows.append(dict(strategy=tag, **params, is_baseline=is_base,
                             warmup_bars=strategy.warmup_bars,
                             post_start_warmup_bars=max(0,strategy.warmup_bars-manifest['warmup_bars']), **m))
        signals_all[tag] = rows
        for multiple in cfg['stop_multipliers']:
            l, c = diagnostic_run(signals, start, end, strategy_key=key, stop_multiplier=multiple)
            m, _ = calculate(l, c, start)
            stop_rows.append(dict(strategy=tag, stop_multiplier=multiple, **m))
        for name, (fee, slip) in cfg['cost_scenarios'].items():
            l, c = diagnostic_run(signals, start, end, strategy_key=key,
                                  config=BacktestConfig(fee_bps=fee, slippage_bps=slip))
            m, _ = calculate(l, c, start)
            cost_rows.append(dict(strategy=tag, scenario=name, fee_bps=fee, slippage_bps=slip, **m))
        print(tag, 'diagnostics/signal/stop/cost complete', flush=True)
    save('trade_diagnostics.csv', diagnostics)
    save('asset_contribution.csv', assets)
    save('calendar_metrics.csv', calendars)
    pd.concat(enriched).to_csv(ROOT / 'trades_enriched.csv', index=False)
    names = {'T1': 'T1_ema_sensitivity.csv', 'T2': 'T2_donchian_sensitivity.csv', 'T3': 'T3_tsmom_sensitivity.csv'}
    for tag, rows in signals_all.items(): save(names[tag], rows)
    save('stop_sensitivity.csv', stop_rows)
    save('cost_stress.csv', cost_rows)
    for tag, x, y in [('T1','fast','slow'), ('T2','entry','exit')]:
        for metric in ['cagr','sharpe']:
            heatmap(pd.DataFrame(signals_all[tag]), x, y, metric, f'{tag}_{metric}_heatmap.svg', f'{tag} {metric} local sensitivity')
    svg_chart('T3_lookback.svg', 'T3 momentum lookback CAGR', [r['lookback'] for r in signals_all['T3']], [r['cagr'] for r in signals_all['T3']], True)
    svg_chart('asset_contribution.svg', 'Net PnL contribution / initial equity', [r['strategy']+' '+r['symbol'] for r in assets], [r['return_contribution'] for r in assets], True)
    svg_chart('calendar_returns.svg', 'Calendar return (first/last years partial)', [r['strategy']+' '+str(r['year']) for r in calendars], [r['return_pct'] for r in calendars], True)
    svg_chart('stop_mdd.svg', 'Stop sensitivity MDD', [r['strategy']+' '+str(r['stop_multiplier']) for r in stop_rows], [r['mdd'] for r in stop_rows], True)
    svg_chart('cost_expectancy.svg', 'Cost stress expectancy (net USDT per trade)', [r['strategy']+' '+r['scenario'] for r in cost_rows], [r['expectancy_usdt'] for r in cost_rows])
    all_diag = [r for r in diagnostics if r['symbol']=='ALL']
    svg_chart('profit_concentration.svg', 'Top 5 trades / sum of positive net trade PnL', [r['strategy'] for r in all_diag], [r['top5_gross_profit_share'] for r in all_diag], True)
    svg_chart('exit_counts.svg', 'Exit reason counts', [r['strategy']+' '+reason for r in all_diag for reason in ['signal','stop','terminal']], [r[reason+'_exit_count'] for r in all_diag for reason in ['signal','stop','terminal']])
    summary, flag_details = [], []
    for tag, key in KEYS.items():
        b = baselines[key][2]
        d = next(r for r in all_diag if r['strategy']==tag)
        neighbors = pd.DataFrame(signals_all[tag]).query('not is_baseline')
        moderate = next(r for r in cost_rows if r['strategy']==tag and r['scenario']=='B')
        stop = [r for r in stop_rows if r['strategy']==tag]
        mdd_ratio = max(abs(r['mdd']) / abs(b['mdd']) for r in signals_all[tag]+stop)
        isolated = bool(b['cagr'] > 0 and b['sharpe'] > 0 and
                        b['cagr'] >= 1.5*neighbors.cagr.median() and b['sharpe'] >= 1.5*neighbors.sharpe.median() and
                        ((neighbors.cagr <= .75*b['cagr']) & (neighbors.sharpe <= .75*b['sharpe'])).mean() >= 2/3)
        flags = dict(ENGINE_MISMATCH=False, LOW_SAMPLE=b['trade_count'] < 30,
                     PROFIT_CONCENTRATION=d['top5_gross_profit_share'] > .5,
                     ASSET_CONCENTRATION=max(r['absolute_pnl_share'] for r in assets if r['strategy']==tag) > .6,
                     SIGN_SENSITIVITY=bool(neighbors.expectancy_usdt.le(0).mean() > .5),
                     ISOLATED_PEAK=isolated, MDD_FRAGILITY=mdd_ratio >= 1.5,
                     COST_FRAGILITY=moderate['expectancy_usdt'] <= 0 or moderate['profit_factor'] <= 1)
        flag_details += [dict(strategy=tag, flag=k, triggered=v) for k,v in flags.items()]
        active = [f for f,v in flags.items() if v]
        # Proposed review routing, not automatic rejection or approval.
        hold = any(flags[f] for f in ['LOW_SAMPLE','SIGN_SENSITIVITY','ISOLATED_PEAK','COST_FRAGILITY']) or b['expectancy_usdt'] <= 0
        classification = 'W02_HOLD' if hold else 'W02_PASS_WITH_FLAGS' if active else 'W02_PASS_TO_OOS'
        summary.append(dict(strategy=tag, strategy_key=key, classification=classification, flags=';'.join(active),
                            **b, top5_profit_share=d['top5_gross_profit_share'], max_mdd_ratio=mdd_ratio,
                            signal_cagr_min=neighbors.cagr.min(), signal_cagr_max=neighbors.cagr.max(),
                            signal_expectancy_min=neighbors.expectancy_usdt.min(),
                            cost_moderate_expectancy=moderate['expectancy_usdt'], cost_severe_expectancy=next(r['expectancy_usdt'] for r in cost_rows if r['strategy']==tag and r['scenario']=='C')))
    save('W02_summary.csv', summary)
    save('diagnostic_flags.csv', flag_details)
    report(summary, diagnostics, assets, calendars, signals_all, stop_rows, cost_rows, baselines, manifest)
    after = frozen_files()
    if after != frozen: raise AssertionError('Frozen W01 files changed')
    (ROOT / 'W01_preservation.json').write_text(json.dumps({'unchanged': True, 'sha256': frozen}, indent=2))
    paths = list(ROOT.rglob('*')) + [Path('config/w02_diagnostic_sensitivity.yaml'), Path('alpha_lab/w02.py'), Path('alpha_lab/w02_stage0.py'), Path('alpha_lab/w02_engine.py')]
    (ROOT / 'manifest.json').write_text(json.dumps({'status':'W02_COMPLETE', 'python':platform.python_version(),
        'pandas':pd.__version__, 'numpy':np.__version__, 'baseline_reproduction':'PASS', 'extension_engine_parity':'EXACT',
        'no_downloads':True, 'no_optimization':True, 'sha256':{str(p):sha(p) for p in paths if p.is_file()}}, indent=2))
    print(pd.DataFrame(summary)[['strategy','classification','flags']].to_string(index=False), flush=True)

def report(summary, diagnostics, assets, calendars, variants, stops, costs, baseline, manifest):
    lines = ['# W02 — Diagnostic & Sensitivity Cycle', '',
             'RESULT: W01 Baseline reproduction PASS. 거래 원장과 Equity Curve CSV 바이트 일치; 원본 지표 relative tolerance 1e-8, absolute tolerance 0. Stop 실험용 엔진도 3 ATR에서 바이트 일치.', '',
             f"FACT: Binance Spot BTC/ETH/SOL 4H. Raw history {manifest['common_raw_start']}; 평가 {manifest['primary_start']} ~ {pd.Timestamp(manifest['last_bar_open'])+pd.Timedelta(hours=4)} UTC. 동일 snapshot, 신규 다운로드 없음.", '',
             '각 전략은 독립된 100,000 USDT shared BTC/ETH/SOL portfolio. W01 파일·전략 version·신호 규칙 보존. Signal/stop/cost 실험은 각각 분리. 최적 Parameter 선정 없음. OOS/Paper/Live 결과 또는 APPROVED 판정 아님.', '',
             '| 전략 | 분류 | Flag |', '|---|---|---|']
    for s in summary: lines.append(f"| {s['strategy']} | {s['classification']} | {s['flags'] or '없음'} |")
    lines += ['', '## 계산 정의 및 해석 범위', '',
              '- Gross Profit/Gross Loss는 W01 PF와 동일하게 **양수/음수 net trade PnL의 합**이다. 수수료 차감 전 `gross_pnl`과 구분한다. 손실은 음수로 기록한다. Expectancy는 완료 거래 평균 net USDT이며 자본 증가에 영향을 받으므로 거래 return도 함께 확인한다.',
              '- MFE는 보유 중 최대 유리 움직임, MAE는 최대 불리 움직임이다. Entry fill 기준 가격 수익률로 계산한다. Signal/gap exit 봉은 open 즉시 청산하므로 고가·저가 제외. Stop 봉의 고가는 순서를 알 수 없어 기본 MFE에서 제외하고 upper bound에만 포함. MAE에는 stop/gap exit raw 가격 포함. 실현 return은 양쪽 비용 포함.',
              '- MFE giveback은 관측된 peak에서 exit fill까지 반납한 가격 수익률. MFE=0일 때 giveback fraction은 정의하지 않는다. 100% 초과는 유리했던 움직임을 전부 반납하고 손실로 청산했다는 뜻이다. 평균 return 차이와 fraction 중앙값을 제공한다. peak-to-exit bars는 사후 가격 고점부터 청산까지의 지연 proxy이며 정식 reversal detector가 아니다.',
              '- 30봉(5일) 이하 손실 거래는 짧은 손실의 기술적 proxy로만 사용한다. Whipsaw(짧은 방향 전환으로 손실 반복)나 false breakout을 확정하는 지표가 아니다. 연속 손실은 원장 exit 순서 기준; 동시 청산은 W01 symbol 순서.',
              '- Calendar return/MDD는 직전 연말 equity에서 시작하는 mark-to-market 계산. Trade Count/Win Rate는 청산연도 기준이며 당해 return과 직접 일치하지 않는다. 2020/2026은 부분연도.',
              '- 모든 variant는 W01 raw history와 평가 구간 고정. EMA slow 240은 시작 후 40봉, momentum 216은 17봉 추가 warmup으로 신호 비활성. 추가 과거자료 삽입 없음. 따라서 초기 가동 차이도 sensitivity에 포함된다.',
              '- Stop 변화는 손절 거리와 수량 계산 양쪽에 동일 multiplier 적용. 0.5% risk와 33.3% entry cap 고정. 비용 stress는 기존 거래에서 비용만 빼는 방식이 아니라 재실행하므로 fill/stop/수량/현금 변화도 포함한다.',
              '- Fee/slippage는 이미 net PnL에 반영되어 있다. raw price PnL = net PnL + fees + estimated slippage. 비용의 순수 인과 효과와 compounding 차이를 구분한다.', '',
              '## Flag 기준과 Review routing', '',
              '`ISOLATED_PEAK`은 명세의 정량 기준이 없어 다음 PROPOSAL을 고정 적용했다: Baseline CAGR/Sharpe가 모두 이웃 중앙값의 1.5배 이상이고, 이웃 2/3 이상에서 두 지표 모두 Baseline의 75% 이하. 이웃은 Baseline을 제외한다. `SIGN_SENSITIVITY`는 이웃 과반 Expectancy≤0. `MDD_FRAGILITY`는 signal/stop variant 중 절대 MDD가 1.5배 이상. 비용은 별도 COST flag로 판단한다.', '',
              '분류는 승인·자동 Reject가 아닌 Review routing 제안이다. LOW_SAMPLE/SIGN_SENSITIVITY/ISOLATED_PEAK/COST_FRAGILITY 또는 Baseline Expectancy≤0이면 HOLD로 검토 우선 배치한다. 그 외 flag는 PASS_WITH_FLAGS, flag 없으면 PASS_TO_OOS. 모든 결과는 사후 in-sample 진단이므로 추가 검증이 필요하다.', '']
    for s in summary:
        tag = s['strategy']
        d = next(r for r in diagnostics if r['strategy']==tag and r['symbol']=='ALL')
        a = [r for r in assets if r['strategy']==tag]
        v, st, co = variants[tag], [r for r in stops if r['strategy']==tag], [r for r in costs if r['strategy']==tag]
        c = baseline[KEYS[tag]][1]
        trough = c.drawdown.idxmin()
        peak = c.loc[:trough].equity.idxmax()
        lines += [f'## {tag} — {s["classification"]}', '',
                  f'**FACT:** Baseline {KEYS[tag]}, trades {d["trade_count"]}; 신호 청산 {d["signal_exit_count"]}, stop {d["stop_exit_count"]}, 종료 정산 {d["terminal_exit_count"]}.', '',
                  f'**RESULT:** CAGR {s["cagr"]:.2%}, MDD {s["mdd"]:.2%}, Sharpe {s["sharpe"]:.3f}; net PnL {d["net_pnl"]:,.2f} USDT. Win Rate {d["win_rate"]:.2%}, 평균 이익 {d["average_win"]:,.2f}, 평균 손실 {d["average_loss"]:,.2f}, Expectancy {d["expectancy"]:,.2f} USDT.', '',
                  f'- Top 1 / 5 / 10 양수 거래 기여: {d["top1_gross_profit_share"]:.2%} / {d["top5_gross_profit_share"]:.2%} / {d["top10_gross_profit_share"]:.2%}.',
                  '- Absolute PnL 기여: '+ '; '.join(f'{r["symbol"]} {r["absolute_pnl_share"]:.2%} (net {r["net_pnl"]:,.2f})' for r in a)+'.',
                  f'- 최대 연속 손실 {d["consecutive_losses"]}; 30봉 이하 손실 {d["short_losing_trades_30bars"]}; 보유기간 중앙값 {d["holding_p50"]:.0f}봉, P10/P90 {d["holding_p10"]:.0f}/{d["holding_p90"]:.0f}봉.',
                  f'- Signal local CAGR 범위 {min(r["cagr"] for r in v):.2%} ~ {max(r["cagr"] for r in v):.2%}; Expectancy>0 {sum(r["expectancy_usdt"]>0 for r in v)}/{len(v)} configurations.',
                  '- Stop 실험: '+ '; '.join(f'{r["stop_multiplier"]} ATR: CAGR {r["cagr"]:.2%}, MDD {r["mdd"]:.2%}, E {r["expectancy_usdt"]:,.2f}' for r in st)+'.',
                  '- 비용 A/B/C: '+ '; '.join(f'{r["scenario"]}: CAGR {r["cagr"]:.2%}, PF {r["profit_factor"]:.3f}, E {r["expectancy_usdt"]:,.2f}, fee {r["total_fees_usdt"]:,.2f}, slip {r["slippage_cost_usdt"]:,.2f}' for r in co)+'.',
                  f'- MDD peak/trough: {peak} → {trough} UTC (봉 종가 equity 기준).',
                  f'- 평균 MFE {d["mfe_mean"]:.2%}, 평균 MAE {d["mae_mean"]:.2%}, 평균 실현 return {d["realized_return_mean"]:.2%}, 평균 giveback {100*d["giveback_return_mean"]:.2f}%p; giveback fraction 중앙값 {d["giveback_fraction_median"]:.2%}.', '',
                  f'**INTERPRETATION:** 이웃에서 Expectancy 방향은 {"모두 양수로 유지된다" if all(r["expectancy_usdt"]>0 for r in v) else "일부 달라진다"}. 최대 variant MDD/Baseline 비율 {s["max_mdd_ratio"]:.2f}배. Moderate/Severe stress Expectancy는 {s["cost_moderate_expectancy"]:,.2f}/{s["cost_severe_expectancy"]:,.2f} USDT다. 단순 수익률 순위로 Parameter를 선택하지 않는다.', '']
        if tag == 'T1':
            lines += [f'낮은 승률과 큰 평균 이익의 조합은 긴 추세 거래가 손실을 상쇄하는 구조와 일치한다. 상위 거래 집중도와 자산 기여를 함께 검토해야 한다. 연속 손실 {d["consecutive_losses"]}회는 실전 중단 유혹을 키울 수 있으며, 짧은 손실 proxy {d["short_losing_trades_30bars"]}건은 whipsaw 검토용이다.', '']
        elif tag == 'T2':
            lines += [f'Stop 청산 비중 {d["stop_exit_count"]/d["trade_count"]:.2%}. 30봉 이하 손실 {d["short_losing_trades_30bars"]}건은 돌파 실패 후보지만, stop 청산만으로 false breakout을 단정하지 않는다. Entry/exit 채널별 결과는 두 heatmap으로 확인한다. Current bar는 원본 shift(1) 계산으로 제외한다.', '']
        else:
            raw = d['raw_price_pnl']
            lines += [f'양쪽 거래대금 / 초기자금은 {d["turnover_initial_equity"]:.2f}배. 총 fee+slip {d["total_fee"]+d["estimated_slippage_cost"]:,.2f} USDT, raw price PnL 대비 {(d["total_fee"]+d["estimated_slippage_cost"])/raw:.2%}. 고점부터 exit까지 중앙값 {d["peak_to_exit_bars_median"]:.1f}봉은 청산 지연 proxy다. Momentum 0 crossing에는 과거 기준가격도 움직이므로 가격 reversal과 exit 사이에 고정 지연이 존재한다고 해석하지 않는다.', '']
        lines += [f'**RISK FLAG:** {s["flags"] or "지정 flag 없음"}.', '',
                  '**NEXT STEP:** '+('Flag 원인을 검토하고 미해결 취약성을 기록한 뒤 OOS/Walk-Forward 설계를 진행한다.' if s['flags'] else '현재 Baseline을 그대로 동결하여 시간 분리 OOS/Walk-Forward 검증으로 진행한다.')+' W02 자료를 보고 이미 확인한 구간을 미관측 OOS로 다시 부르지 않는다.', '']
    lines += ['## FUTURE_EXPERIMENT', '',
              'Entry/Exit 개선·추가 filter·trailing stop·자산 비중 변경은 시행하지 않았다. 다음 실험은 현재 Baseline의 OOS/Walk-Forward 재현성과 거래비용·유동성 현실성 검증이며, 전략 변경이 필요할 경우 별도 version과 별도 검증 계획을 만든다.', '',
              '## 산출물', '', '요청 CSV 10개, baseline_reproduction.csv, report, config와 추가 trades_enriched.csv/diagnostic_flags.csv/보존 해시/manifest. figures의 SVG는 정확한 수치를 표시하는 heatmap 및 diagnostic chart다. SVG는 브라우저에서 열 수 있다.']
    (ROOT / 'W02_report.md').write_text('\n'.join(lines), encoding='utf-8')

if __name__ == '__main__': main()
