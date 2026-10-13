# MR-W01 Baseline Report

## FACT

- Three independent candidates use one shared BTC/ETH/SOL portfolio each.
- Binance Spot 4H, long only, no leverage/pyramiding; no exchange order endpoint.
- W01 evaluation: 2020-09-13 16:00:00+00:00 to 2026-10-02 12:00:00+00:00.
- W01 clean CSV hashes and complete committed W03 lock verified. No new historical data.
- Existing Trend T1/T2/T3, W03 classifications and W04/DEV-M02~M04 files unchanged.
- MR rules fixed at v0.1; no parameter search, new filters or optimization.

## ASSUMPTION

- 100,000 USDT/candidate; 0.5% stop-distance risk; entry notional cap 33.3%.
- Fees 10 bps/side, adverse slippage 5 bps/side; fractional units, no exchange filters.
- Wilder uses SMA seeds, EMA200 adjust=False; both rolling standard deviations ddof=0.
- 201 common warmup bars excluded, matching W01. Close signals fill next Open.
- Stops remain EntryFill - 2.5*signal ATR20. Stop gaps fill adverse Open; exit first.
- Simultaneous entries allocate BTC then ETH then SOL using shared cash and open equity.
- Final close liquidation is explicit accounting, not a strategy exit or Time Stop.
- Intrabar Stop timestamps use bar close: actual intrabar clock is unknown (holding-time estimate).
- Asset rows attribute shared portfolio PnL to the same 100k reference; not standalone ROI.
- Exposure is close-marked notional/equity; active-bar duration is a bar approximation.
- Buy & Hold invests thirds including buy fees, no rebalance, same start Open/end Close costs.
- Annualized ratios use 2,190 bars/year, zero risk-free rate. Undefined ratios remain blank.
- Diagnostic conventions fixed: <30 trades INSUFFICIENT; positive net/PF>1/Sharpe>0
  POSITIVE; negative net/PF<1 NEGATIVE; otherwise MIXED. Flags: asset absolute PnL share
  >70%, any holding >30 days. These are reporting assumptions, not entry filters.

## RESULT

MR_W01_PREFLIGHT_PASS; MR_W01_BASELINE_COMPLETE.

| Candidate | Total Return | CAGR | MDD | Sharpe | Trades | Net PnL USDT | Classification |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| meanrev_rsi_v0.1 | -1.22% | -0.20% | -3.40% | -0.162 | 42 | -1217.41 | NEGATIVE_DIAGNOSTIC |
| meanrev_bollinger_v0.1 | -0.05% | -0.01% | -9.33% | 0.012 | 300 | -51.98 | NEGATIVE_DIAGNOSTIC |
| meanrev_shock_v0.1 | -7.33% | -1.25% | -9.93% | -0.551 | 159 | -7329.60 | NEGATIVE_DIAGNOSTIC |
| equal_weight_buy_hold | 1746.91% | 61.87% | -92.39% | 0.990 | 3 | 1746906.00 | BENCHMARK_NOT_CLASSIFIED |

All requested metrics and asset attribution are in MR-W01_summary.csv.
Signals record boolean conditions, not guaranteed fills; engine applies position/cash state.
CSV outputs were independently recomputed and compared exactly before publication.

## RISK

- Historical in-sample diagnostics are not approval, profitability proof or W04 Forward validation.
- Original raw API pages are absent here; verified CSV/manifest provenance is not raw-page re-audit.
- Gap losses and costs can exceed 0.5%; passive appreciation can exceed entry allocation cap.
- Bar-close equity underestimates intrabar drawdown; live liquidity/fill probability not modeled.
- SOL receives cash last; report sequencing effects without changing the frozen order.
- meanrev_rsi_v0.1: trades=42, max absolute asset PnL share=40.29%, concentration_flag=False, longest_hold_hours=124.0, long_hold_flag=False, terminal_exits=0.
- meanrev_bollinger_v0.1: trades=300, max absolute asset PnL share=50.29%, concentration_flag=False, longest_hold_hours=108.0, long_hold_flag=False, terminal_exits=0.
- meanrev_shock_v0.1: trades=159, max absolute asset PnL share=46.97%, concentration_flag=False, longest_hold_hours=128.0, long_hold_flag=False, terminal_exits=0.

## DECISION

Diagnostic labels do not mean APPROVED. Trend W03 classifications unchanged.
- meanrev_rsi_v0.1: NEGATIVE_DIAGNOSTIC. Limited diagnostic continuation; establish failure causes before advancing.
- meanrev_bollinger_v0.1: NEGATIVE_DIAGNOSTIC. Limited diagnostic continuation; establish failure causes before advancing.
- meanrev_shock_v0.1: NEGATIVE_DIAGNOSTIC. Limited diagnostic continuation; establish failure causes before advancing.

## NEXT ACTION

- M1 MR-W02: RSI recovery trades by regime/asset, cost burden and stop/holding tails.
- M2 MR-W02: band recovery false positives, drawdown episodes and concentration.
- M3 MR-W02: shock clusters, sparse signals, gap loss and prior-volatility regime dependence.
- All: diagnostic subperiod/out-of-sample stability and benchmark-relative risk; retain v0.1.
- No strategy approval, live execution or W04 Formal Clock activation is granted.
