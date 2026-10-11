# MR-W02 — Mean Reversion Diagnostic Report

RESULT: MR_W02_DIAGNOSTIC_COMPLETE. MR-W01의 NEGATIVE_DIAGNOSTIC 판정과 v0.1 규칙을 보존한다. 이 보고서는 이미 본 과거 데이터의 진단이며 Genuine Unseen OOS가 아니다.

## 자료와 계산 정의

Source: NAM-GOM/ai-multi-strategy-investment-system, commit bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e. MR-W01 manifest/trades/summary와 같은 W03 frozen snapshot을 사용했다. Binance Spot BTC/ETH/SOL 4H, 2020-09-13 16:00~2026-10-02 12:00 UTC. 2020·2026은 부분 연도. 전략별 독립된 100,000 USDT 공동 자본이다. 자산별 결과는 공동 계좌에 대한 기여이며 개별 자산 독립 운용 수익률이 아니다.

Gross Proxy = 수량 × (슬리피지 전 매도가−매수가). 원본 gross_pnl은 이미 슬리피지 차감 후다. Gross Proxy−양쪽 Fee−양쪽 Slippage=Net PnL. Gross Proxy는 원래 체결 시점·수량을 유지한 비용 분해 값이며 비용 없는 재실행 성과가 아니다.

Gap Loss = 수량 × max(Stop−실제 raw 청산가,0). SIGNAL 청산이라도 시가가 Stop 아래면 포함한다. 별도 추가 차감하지 않는다. Stop Exit Ratio는 STOP와 STOP_GAP만 포함한다. SIGNAL 우선 처리로 실제 위험은 Stop 명칭 비율에만 나타나지 않을 수 있다.

Holding Period는 기록된 entry/exit 시간 차이다. Intrabar Stop은 봉 마감 시각으로 기록되어 최대 4시간 오차가 있다. 원본 bars_held는 포함한 봉 개수로 실제 시간과 다를 수 있다.

Direction Regime: 신호 확정 시점 EMA200의 30봉 변화 >1% UP, <-1% DOWN, 나머지 FLAT. Vol Regime: 신호 이전 60봉 수익률 표준편차를 과거 expanding median과 비교해 HIGH/LOW. 이 값들은 진단용이며 새로운 매매 필터가 아니다. EMA 필터로 DOWN 표본은 적거나 없을 수 있다.

신호 후 1/3/6/12봉 종가 수익률은 실제 거래가 끝난 후도 포함하는 가격 행동 진단이다. 미래 OHLC로 주문을 생성하지 않는다. Close-path MFE/MAE는 진입가·보유 중 종가·청산가만 사용해 유리/불리한 움직임을 측정하며 intrabar 최대/최소값이 아니다. 청산봉의 청산 이후 가격은 제외했다.

Shock cluster: 같은 자산에서 현재 포함 최근 6봉(24시간)의 원본 진입 조건이 2회 이상 발생. 포지션·현금 때문에 실제 주문 수와 다를 수 있다. 자산 간 24시간 신호 동시 발생도 아래에 별도로 기록한다.

저표본: 그룹 <30건은 descriptive only. 유의성·인과관계를 입증하지 않는다. 모든 비교 정의는 진단 실행 코드에 기록했지만 MR-W01 결과를 이미 본 후 정의한 분석이다.

## 비용 분해와 자산 일관성

| strategy | trades | gross_proxy_usdt | fees_usdt | slippage_usdt | net_pnl_usdt | expectancy_usdt |
| --- | --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1 | 42 | -64.43 | 768.65 | 384.33 | -1,217.41 | -28.99 |
| meanrev_bollinger_v0.1 | 300 | 9,249.74 | 6,201.15 | 3,100.57 | -51.98 | -0.17 |
| meanrev_shock_v0.1 | 159 | -2,941.38 | 2,925.48 | 1,462.74 | -7,329.60 | -46.10 |

| strategy | asset | trades | net_pnl_usdt | win_rate | avg_win_usdt | avg_loss_usdt | stop_exit_ratio | gap_loss_usdt | avg_hold_hours | p90_hold_hours |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1 | BTCUSDT | 18 | 730.80 | 77.78% | 203.25 | -528.69 | 22.22% | 0.00 | 52.67 | 87.60 |
| meanrev_rsi_v0.1 | ETHUSDT | 13 | -868.94 | 69.23% | 134.91 | -520.78 | 30.77% | 0.00 | 53.85 | 83.20 |
| meanrev_rsi_v0.1 | SOLUSDT | 11 | -1,079.26 | 54.55% | 249.47 | -515.22 | 45.45% | 0.00 | 28.73 | 44.00 |
| meanrev_bollinger_v0.1 | BTCUSDT | 105 | -4,527.83 | 61.90% | 189.12 | -420.52 | 28.57% | 0.00 | 31.54 | 60.00 |
| meanrev_bollinger_v0.1 | ETHUSDT | 98 | 3,913.97 | 70.41% | 217.04 | -381.43 | 20.41% | 0.00 | 29.92 | 56.00 |
| meanrev_bollinger_v0.1 | SOLUSDT | 97 | 561.89 | 68.04% | 197.11 | -401.53 | 23.71% | 0.00 | 29.28 | 65.60 |
| meanrev_shock_v0.1 | BTCUSDT | 63 | -744.77 | 60.32% | 180.10 | -303.54 | 20.63% | 0.00 | 33.14 | 64.00 |
| meanrev_shock_v0.1 | ETHUSDT | 55 | -3,142.48 | 54.55% | 195.36 | -360.13 | 29.09% | 0.00 | 31.85 | 60.00 |
| meanrev_shock_v0.1 | SOLUSDT | 41 | -3,442.36 | 46.34% | 206.72 | -335.00 | 34.15% | 0.00 | 30.15 | 64.00 |

## 비용 민감도

동일 거래·수량·가격·시각을 고정해 재가격화했다. 비용 변경에 따른 현금·진입 수량·Stop 변화를 재시뮬레이션하지 않았다. ZERO_COST_PROXY는 손익 분해이며 Baseline 승격 금지. 아래는 민감도 진단이다.

| strategy | scenario | net_pnl_usdt | expectancy_usdt |
| --- | --- | --- | --- |
| meanrev_rsi_v0.1 | BASELINE_fee10_slip5 | -1,217.41 | -28.99 |
| meanrev_rsi_v0.1 | ZERO_COST_PROXY | -64.43 | -1.53 |
| meanrev_rsi_v0.1 | STRESS_fee10_slip10 | -1,601.73 | -38.14 |
| meanrev_rsi_v0.1 | STRESS_fee20_slip20 | -3,139.04 | -74.74 |
| meanrev_bollinger_v0.1 | BASELINE_fee10_slip5 | -51.98 | -0.17 |
| meanrev_bollinger_v0.1 | ZERO_COST_PROXY | 9,249.74 | 30.83 |
| meanrev_bollinger_v0.1 | STRESS_fee10_slip10 | -3,152.55 | -10.51 |
| meanrev_bollinger_v0.1 | STRESS_fee20_slip20 | -15,554.82 | -51.85 |
| meanrev_shock_v0.1 | BASELINE_fee10_slip5 | -7,329.60 | -46.10 |
| meanrev_shock_v0.1 | ZERO_COST_PROXY | -2,941.38 | -18.50 |
| meanrev_shock_v0.1 | STRESS_fee10_slip10 | -8,792.34 | -55.30 |
| meanrev_shock_v0.1 | STRESS_fee20_slip20 | -14,643.30 | -92.10 |

## 연도별·기간별 성과

MTM(mark to market)은 보유 자산을 매 봉 종가로 평가한 손익이다. 아래 MTM은 연도 경계를 넘어 보유한 거래도 해당 기간 가격 변화로 귀속한다. 거래 지표는 별도로 청산 연도에 전체 거래 손익을 귀속하며 경계 거래를 분할하지 않는다.

| strategy | year | mtm_pnl_usdt | partial_year |
| --- | --- | --- | --- |
| meanrev_rsi_v0.1 | 2020 | 438.14 | True |
| meanrev_rsi_v0.1 | 2021 | -421.58 | False |
| meanrev_rsi_v0.1 | 2022 | -357.62 | False |
| meanrev_rsi_v0.1 | 2023 | 323.25 | False |
| meanrev_rsi_v0.1 | 2024 | -1,863.89 | False |
| meanrev_rsi_v0.1 | 2025 | 270.26 | False |
| meanrev_rsi_v0.1 | 2026 | 394.03 | True |
| meanrev_bollinger_v0.1 | 2020 | 639.85 | True |
| meanrev_bollinger_v0.1 | 2021 | 1,942.94 | False |
| meanrev_bollinger_v0.1 | 2022 | -1,593.73 | False |
| meanrev_bollinger_v0.1 | 2023 | 4,827.29 | False |
| meanrev_bollinger_v0.1 | 2024 | -9,042.69 | False |
| meanrev_bollinger_v0.1 | 2025 | 1,396.26 | False |
| meanrev_bollinger_v0.1 | 2026 | 1,778.11 | True |
| meanrev_shock_v0.1 | 2020 | 1,523.22 | True |
| meanrev_shock_v0.1 | 2021 | -2,379.54 | False |
| meanrev_shock_v0.1 | 2022 | 348.57 | False |
| meanrev_shock_v0.1 | 2023 | -1,095.86 | False |
| meanrev_shock_v0.1 | 2024 | -3,608.67 | False |
| meanrev_shock_v0.1 | 2025 | 459.99 | False |
| meanrev_shock_v0.1 | 2026 | -2,577.31 | True |

| strategy | exit_year | trades | net_pnl_usdt | expectancy_usdt | profit_factor | low_sample |
| --- | --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1 | 2020 | 4 | 438.14 | 109.53 |  | True |
| meanrev_rsi_v0.1 | 2021 | 6 | -421.58 | -70.26 | 0.59 | True |
| meanrev_rsi_v0.1 | 2022 | 5 | -357.62 | -71.52 | 0.66 | True |
| meanrev_rsi_v0.1 | 2023 | 10 | 323.25 | 32.33 | 1.20 | True |
| meanrev_rsi_v0.1 | 2024 | 10 | -1,863.89 | -186.39 | 0.28 | True |
| meanrev_rsi_v0.1 | 2025 | 5 | 270.26 | 54.05 | 1.52 | True |
| meanrev_rsi_v0.1 | 2026 | 2 | 394.03 | 197.01 |  | True |
| meanrev_bollinger_v0.1 | 2020 | 13 | 639.85 | 49.22 | 1.56 | True |
| meanrev_bollinger_v0.1 | 2021 | 68 | 1,942.94 | 28.57 | 1.25 | False |
| meanrev_bollinger_v0.1 | 2022 | 18 | -1,593.73 | -88.54 | 0.57 | True |
| meanrev_bollinger_v0.1 | 2023 | 63 | 4,827.29 | 76.62 | 1.69 | False |
| meanrev_bollinger_v0.1 | 2024 | 62 | -9,042.69 | -145.85 | 0.33 | False |
| meanrev_bollinger_v0.1 | 2025 | 44 | 1,396.26 | 31.73 | 1.32 | False |
| meanrev_bollinger_v0.1 | 2026 | 32 | 1,778.11 | 55.57 | 1.63 | False |
| meanrev_shock_v0.1 | 2020 | 11 | 1,523.22 | 138.47 | 16.98 | True |
| meanrev_shock_v0.1 | 2021 | 41 | -2,379.54 | -58.04 | 0.58 | False |
| meanrev_shock_v0.1 | 2022 | 8 | 348.57 | 43.57 | 1.22 | True |
| meanrev_shock_v0.1 | 2023 | 22 | -1,095.86 | -49.81 | 0.66 | True |
| meanrev_shock_v0.1 | 2024 | 36 | -3,608.67 | -100.24 | 0.46 | False |
| meanrev_shock_v0.1 | 2025 | 23 | 459.99 | 20.00 | 1.20 | True |
| meanrev_shock_v0.1 | 2026 | 18 | -2,577.31 | -143.18 | 0.40 | True |

## 시장 환경별 성과

| strategy | direction_regime | vol_regime | trades | net_pnl_usdt | expectancy_usdt | profit_factor | low_sample |
| --- | --- | --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1 | FLAT | LOW | 1 | -550.75 | -550.75 | 0.00 | True |
| meanrev_rsi_v0.1 | UP | HIGH | 15 | 910.73 | 60.72 | 1.88 | True |
| meanrev_rsi_v0.1 | UP | LOW | 26 | -1,577.39 | -60.67 | 0.70 | True |
| meanrev_bollinger_v0.1 | FLAT | HIGH | 1 | 250.76 | 250.76 |  | True |
| meanrev_bollinger_v0.1 | FLAT | LOW | 24 | -2,010.33 | -83.76 | 0.55 | True |
| meanrev_bollinger_v0.1 | UP | HIGH | 80 | 4,173.90 | 52.17 | 1.52 | False |
| meanrev_bollinger_v0.1 | UP | LOW | 195 | -2,466.31 | -12.65 | 0.91 | False |
| meanrev_shock_v0.1 | FLAT | HIGH | 3 | 208.86 | 69.62 | 4.48 | True |
| meanrev_shock_v0.1 | FLAT | LOW | 15 | -2,849.01 | -189.93 | 0.26 | True |
| meanrev_shock_v0.1 | UP | HIGH | 51 | 1,702.12 | 33.37 | 1.39 | False |
| meanrev_shock_v0.1 | UP | LOW | 90 | -6,391.57 | -71.02 | 0.59 | False |

## Maximum Drawdown 기여

각 전략의 공동 계좌 최대 Peak→Trough 구간에서 자산별 MTM PnL 변화다. 기여는 더하면 공동 계좌의 USDT 손실과 일치한다. 자산별 독립 MDD를 더한 값이 아니다. Intrabar Drawdown은 측정하지 못한다.

| strategy | asset | peak_utc | trough_utc | peak_to_trough_pnl_usdt | portfolio_loss_usdt |
| --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1 | BTCUSDT | 2021-02-24 04:00:00+00:00 | 2024-12-23 20:00:00+00:00 | -1,041.85 | -3,439.00 |
| meanrev_rsi_v0.1 | ETHUSDT | 2021-02-24 04:00:00+00:00 | 2024-12-23 20:00:00+00:00 | -1,562.21 | -3,439.00 |
| meanrev_rsi_v0.1 | SOLUSDT | 2021-02-24 04:00:00+00:00 | 2024-12-23 20:00:00+00:00 | -834.95 | -3,439.00 |
| meanrev_bollinger_v0.1 | BTCUSDT | 2024-01-04 20:00:00+00:00 | 2026-03-23 08:00:00+00:00 | -5,944.97 | -9,903.75 |
| meanrev_bollinger_v0.1 | ETHUSDT | 2024-01-04 20:00:00+00:00 | 2026-03-23 08:00:00+00:00 | -2,210.47 | -9,903.75 |
| meanrev_bollinger_v0.1 | SOLUSDT | 2024-01-04 20:00:00+00:00 | 2026-03-23 08:00:00+00:00 | -1,748.31 | -9,903.75 |
| meanrev_shock_v0.1 | BTCUSDT | 2021-04-08 16:00:00+00:00 | 2026-09-16 16:00:00+00:00 | -1,900.66 | -10,111.59 |
| meanrev_shock_v0.1 | ETHUSDT | 2021-04-08 16:00:00+00:00 | 2026-09-16 16:00:00+00:00 | -4,259.03 | -10,111.59 |
| meanrev_shock_v0.1 | SOLUSDT | 2021-04-08 16:00:00+00:00 | 2026-09-16 16:00:00+00:00 | -3,951.90 | -10,111.59 |

## meanrev_rsi_v0.1

### 가격 행동·Stop·신호 군집

ALL: n=42, Net=-1217.41, Gap Loss=0.00, 평균 Hold=46.76h, 평균 종가경로 MAE=-3.47%, 평균 MFE=2.58%.
STOP_EXIT: n=13, Net=-6773.97, Gap Loss=0.00, 평균 Hold=46.46h, 평균 종가경로 MAE=-6.41%, 평균 MFE=1.41%.
NON_STOP_EXIT: n=29, Net=5556.56, Gap Loss=0.00, 평균 Hold=46.90h, 평균 종가경로 MAE=-2.16%, 평균 MFE=3.11%.

| asset | trades | after_1bar_mean | after_6bars_mean | after_6bars_negative_ratio | below_entry_ratio |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | 18 | -0.24% | 1.29% | 38.89% | 5.56% |
| ETHUSDT | 13 | -0.17% | 0.23% | 61.54% | 7.69% |
| SOLUSDT | 11 | -0.55% | 1.64% | 45.45% | 9.09% |

실제 체결 거래 중 24시간 신호 군집: 2/42건. 군집 거래 Expectancy=-211.92, 나머지=-19.84 USDT. 군집은 독립 표본이 아니며 인과 결론을 내리지 않는다.
원본 진입 조건 50회 중 앞선 24시간에 다른 자산 신호도 있었던 경우 7회. 실제 체결 42건과 구분한다.

### Worst 10 Trades

| trade_id | symbol | entry_time | exit_time | exit_reason | net_pnl | gap_loss | hold_hours | direction_regime | vol_regime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1/0020 | BTCUSDT | 2023-10-11 12:00:00+00:00 | 2023-10-11 20:00:00+00:00 | STOP | -550.75 | 0.00 | 8.00 | FLAT | LOW |
| meanrev_rsi_v0.1/0013 | BTCUSDT | 2022-04-07 12:00:00+00:00 | 2022-04-11 00:00:00+00:00 | STOP | -532.04 | 0.00 | 84.00 | UP | LOW |
| meanrev_rsi_v0.1/0017 | ETHUSDT | 2023-02-10 08:00:00+00:00 | 2023-02-13 12:00:00+00:00 | STOP | -526.13 | 0.00 | 76.00 | UP | LOW |
| meanrev_rsi_v0.1/0018 | ETHUSDT | 2023-04-20 04:00:00+00:00 | 2023-04-21 20:00:00+00:00 | STOP | -524.09 | 0.00 | 40.00 | UP | LOW |
| meanrev_rsi_v0.1/0029 | SOLUSDT | 2024-08-01 12:00:00+00:00 | 2024-08-01 20:00:00+00:00 | STOP | -517.52 | 0.00 | 8.00 | UP | LOW |
| meanrev_rsi_v0.1/0034 | BTCUSDT | 2024-12-20 00:00:00+00:00 | 2024-12-20 12:00:00+00:00 | STOP | -517.17 | 0.00 | 12.00 | UP | LOW |
| meanrev_rsi_v0.1/0010 | SOLUSDT | 2021-11-17 08:00:00+00:00 | 2021-11-18 16:00:00+00:00 | STOP | -516.86 | 0.00 | 32.00 | UP | LOW |
| meanrev_rsi_v0.1/0026 | ETHUSDT | 2024-03-17 04:00:00+00:00 | 2024-03-19 08:00:00+00:00 | STOP | -516.78 | 0.00 | 52.00 | UP | LOW |
| meanrev_rsi_v0.1/0040 | SOLUSDT | 2025-09-23 08:00:00+00:00 | 2025-09-24 08:00:00+00:00 | STOP | -516.34 | 0.00 | 24.00 | UP | LOW |
| meanrev_rsi_v0.1/0033 | ETHUSDT | 2024-12-19 04:00:00+00:00 | 2024-12-19 20:00:00+00:00 | STOP | -516.11 | 0.00 | 16.00 | UP | HIGH |

### 추가 하락 사례

아래는 Stop 청산 거래 중 손실이 큰 3건이다. 신호 후 6봉 가격 움직임은 청산 이후도 포함하므로 실제 보유 성과와 분리한다.

| trade_id | symbol | signal_time | net_pnl | post_signal_return_6bars | close_path_mae | signals_last_24h |
| --- | --- | --- | --- | --- | --- | --- |
| meanrev_rsi_v0.1/0020 | BTCUSDT | 2023-10-11 12:00:00+00:00 | -550.75 | -1.32% | -2.20% | 1.00 |
| meanrev_rsi_v0.1/0013 | BTCUSDT | 2022-04-07 12:00:00+00:00 | -532.04 | -1.07% | -4.18% | 1.00 |
| meanrev_rsi_v0.1/0017 | ETHUSDT | 2023-02-10 08:00:00+00:00 | -526.13 | -1.99% | -4.49% | 1.00 |

## meanrev_bollinger_v0.1

### 가격 행동·Stop·신호 군집

ALL: n=300, Net=-51.98, Gap Loss=0.00, 평균 Hold=30.28h, 평균 종가경로 MAE=-2.47%, 평균 MFE=2.29%.
STOP_EXIT: n=73, Net=-38927.20, Gap Loss=0.00, 평균 Hold=28.71h, 평균 종가경로 MAE=-5.95%, 평균 MFE=0.63%.
NON_STOP_EXIT: n=227, Net=38875.22, Gap Loss=0.00, 평균 Hold=30.78h, 평균 종가경로 MAE=-1.36%, 평균 MFE=2.82%.

| asset | trades | after_1bar_mean | after_6bars_mean | after_6bars_negative_ratio | below_entry_ratio |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | 105 | -0.25% | -0.26% | 57.14% | 0.95% |
| ETHUSDT | 98 | -0.16% | 0.41% | 42.86% | 1.02% |
| SOLUSDT | 97 | -0.17% | 2.28% | 35.05% | 1.03% |

실제 체결 거래 중 24시간 신호 군집: 14/300건. 군집 거래 Expectancy=-66.07, 나머지=3.05 USDT. 군집은 독립 표본이 아니며 인과 결론을 내리지 않는다.
원본 진입 조건 354회 중 앞선 24시간에 다른 자산 신호도 있었던 경우 140회. 실제 체결 300건과 구분한다.

### Worst 10 Trades

| trade_id | symbol | entry_time | exit_time | exit_reason | net_pnl | gap_loss | hold_hours | direction_regime | vol_regime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| meanrev_bollinger_v0.1/0140 | BTCUSDT | 2023-10-09 20:00:00+00:00 | 2023-10-11 08:00:00+00:00 | STOP | -565.46 | 0.00 | 36.00 | FLAT | LOW |
| meanrev_bollinger_v0.1/0141 | BTCUSDT | 2023-10-11 12:00:00+00:00 | 2023-10-11 20:00:00+00:00 | STOP | -562.77 | 0.00 | 8.00 | FLAT | LOW |
| meanrev_bollinger_v0.1/0266 | BTCUSDT | 2025-09-20 00:00:00+00:00 | 2025-09-22 08:00:00+00:00 | STOP | -559.13 | 0.00 | 56.00 | FLAT | LOW |
| meanrev_bollinger_v0.1/0166 | ETHUSDT | 2024-01-19 00:00:00+00:00 | 2024-01-22 12:00:00+00:00 | STOP | -558.80 | 0.00 | 84.00 | UP | LOW |
| meanrev_bollinger_v0.1/0181 | BTCUSDT | 2024-04-01 20:00:00+00:00 | 2024-04-02 04:00:00+00:00 | STOP | -557.06 | 0.00 | 8.00 | UP | LOW |
| meanrev_bollinger_v0.1/0108 | BTCUSDT | 2023-02-09 08:00:00+00:00 | 2023-02-09 20:00:00+00:00 | STOP | -554.73 | 0.00 | 12.00 | UP | LOW |
| meanrev_bollinger_v0.1/0176 | BTCUSDT | 2024-03-15 00:00:00+00:00 | 2024-03-15 04:00:00+00:00 | STOP | -554.14 | 0.00 | 4.00 | UP | HIGH |
| meanrev_bollinger_v0.1/0202 | BTCUSDT | 2024-10-01 04:00:00+00:00 | 2024-10-01 16:00:00+00:00 | STOP | -553.23 | 0.00 | 12.00 | UP | LOW |
| meanrev_bollinger_v0.1/0126 | BTCUSDT | 2023-04-20 04:00:00+00:00 | 2023-04-21 08:00:00+00:00 | STOP | -552.89 | 0.00 | 28.00 | UP | LOW |
| meanrev_bollinger_v0.1/0199 | BTCUSDT | 2024-08-27 20:00:00+00:00 | 2024-08-28 00:00:00+00:00 | STOP | -551.57 | 0.00 | 4.00 | FLAT | LOW |

### 추가 하락 사례

아래는 Stop 청산 거래 중 손실이 큰 3건이다. 신호 후 6봉 가격 움직임은 청산 이후도 포함하므로 실제 보유 성과와 분리한다.

| trade_id | symbol | signal_time | net_pnl | post_signal_return_6bars | close_path_mae | signals_last_24h |
| --- | --- | --- | --- | --- | --- | --- |
| meanrev_bollinger_v0.1/0140 | BTCUSDT | 2023-10-09 20:00:00+00:00 | -565.46 | -0.79% | -2.22% | 1.00 |
| meanrev_bollinger_v0.1/0141 | BTCUSDT | 2023-10-11 12:00:00+00:00 | -562.77 | -1.32% | -2.20% | 1.00 |
| meanrev_bollinger_v0.1/0266 | BTCUSDT | 2025-09-20 00:00:00+00:00 | -559.13 | 0.05% | -1.85% | 1.00 |

## meanrev_shock_v0.1

### 가격 행동·Stop·신호 군집

ALL: n=159, Net=-7329.60, Gap Loss=0.00, 평균 Hold=31.92h, 평균 종가경로 MAE=-3.13%, 평균 MFE=1.94%.
STOP_EXIT: n=43, Net=-22049.28, Gap Loss=0.00, 평균 Hold=32.28h, 평균 종가경로 MAE=-7.15%, 평균 MFE=0.72%.
NON_STOP_EXIT: n=116, Net=14719.68, Gap Loss=0.00, 평균 Hold=31.79h, 평균 종가경로 MAE=-1.64%, 평균 MFE=2.40%.

| asset | trades | after_1bar_mean | after_6bars_mean | after_6bars_negative_ratio | below_entry_ratio |
| --- | --- | --- | --- | --- | --- |
| BTCUSDT | 63 | -0.32% | 0.23% | 49.21% | 1.59% |
| ETHUSDT | 55 | -0.17% | -0.42% | 52.73% | 1.82% |
| SOLUSDT | 41 | -0.96% | 0.84% | 43.90% | 2.44% |

실제 체결 거래 중 24시간 신호 군집: 10/159건. 군집 거래 Expectancy=73.92, 나머지=-54.15 USDT. 군집은 독립 표본이 아니며 인과 결론을 내리지 않는다.
원본 진입 조건 182회 중 앞선 24시간에 다른 자산 신호도 있었던 경우 73회. 실제 체결 159건과 구분한다.

### Worst 10 Trades

| trade_id | symbol | entry_time | exit_time | exit_reason | net_pnl | gap_loss | hold_hours | direction_regime | vol_regime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| meanrev_shock_v0.1/0060 | BTCUSDT | 2022-11-07 12:00:00+00:00 | 2022-11-08 04:00:00+00:00 | STOP | -544.30 | 0.00 | 16.00 | UP | LOW |
| meanrev_shock_v0.1/0140 | BTCUSDT | 2025-09-20 00:00:00+00:00 | 2025-09-22 08:00:00+00:00 | STOP | -539.96 | 0.00 | 56.00 | FLAT | LOW |
| meanrev_shock_v0.1/0080 | BTCUSDT | 2023-12-11 12:00:00+00:00 | 2023-12-11 20:00:00+00:00 | STOP | -531.39 | 0.00 | 8.00 | UP | LOW |
| meanrev_shock_v0.1/0074 | ETHUSDT | 2023-10-03 04:00:00+00:00 | 2023-10-05 16:00:00+00:00 | STOP | -530.58 | 0.00 | 60.00 | FLAT | LOW |
| meanrev_shock_v0.1/0065 | ETHUSDT | 2023-04-19 16:00:00+00:00 | 2023-04-21 08:00:00+00:00 | STOP | -528.38 | 0.00 | 40.00 | UP | LOW |
| meanrev_shock_v0.1/0143 | BTCUSDT | 2026-01-19 08:00:00+00:00 | 2026-01-20 08:00:00+00:00 | STOP | -526.71 | 0.00 | 24.00 | UP | LOW |
| meanrev_shock_v0.1/0026 | ETHUSDT | 2021-04-17 20:00:00+00:00 | 2021-04-18 04:00:00+00:00 | STOP | -526.10 | 0.00 | 8.00 | UP | LOW |
| meanrev_shock_v0.1/0081 | ETHUSDT | 2023-12-11 12:00:00+00:00 | 2023-12-13 04:00:00+00:00 | STOP | -525.49 | 0.00 | 40.00 | UP | LOW |
| meanrev_shock_v0.1/0110 | BTCUSDT | 2024-11-01 00:00:00+00:00 | 2024-11-03 04:00:00+00:00 | STOP | -524.74 | 0.00 | 52.00 | UP | LOW |
| meanrev_shock_v0.1/0051 | ETHUSDT | 2021-11-16 08:00:00+00:00 | 2021-11-17 04:00:00+00:00 | STOP | -522.58 | 0.00 | 20.00 | UP | LOW |

### 추가 하락 사례

아래는 Stop 청산 거래 중 손실이 큰 3건이다. 신호 후 6봉 가격 움직임은 청산 이후도 포함하므로 실제 보유 성과와 분리한다.

| trade_id | symbol | signal_time | net_pnl | post_signal_return_6bars | close_path_mae | signals_last_24h |
| --- | --- | --- | --- | --- | --- | --- |
| meanrev_shock_v0.1/0060 | BTCUSDT | 2022-11-07 12:00:00+00:00 | -544.30 | -4.99% | -2.74% | 1.00 |
| meanrev_shock_v0.1/0140 | BTCUSDT | 2025-09-20 00:00:00+00:00 | -539.96 | 0.05% | -1.85% | 1.00 |
| meanrev_shock_v0.1/0080 | BTCUSDT | 2023-12-11 12:00:00+00:00 | -531.39 | -1.79% | -3.52% | 1.00 |

## 전략별 권고와 남은 가설

PROPOSAL M1 — HOLD. BTC +730.80, ETH −868.94, SOL −1,079.26 USDT. 42건 중 승률 69.05%이나 평균 이익 191.61/손실 −521.07 USDT로 손실 규모가 승률 이점을 상쇄한다. Gross Proxy도 소폭 음수여서 비용만의 문제로 설명할 수 없다. 자산별 11~18건으로 BTC의 우위를 일반화할 수 없다. 가설: RSI 회복이 충분한 반등을 보장하지 않고 작은 이익 뒤 큰 Stop 손실이 남는다. 위 Stop/종가경로 자료는 관찰된 특징이며 원인은 추가 연구가 필요하다. 현재 버전의 다음 검증 단계 승격은 보류한다.

PROPOSAL M2 — CONTINUE_RESEARCH. BTC −4,527.83 손실을 ETH +3,913.97/SOL +561.89가 상쇄했다. 전체 300건, Expectancy −0.17 USDT로 비용 전 가격 손익의 대부분이 비용으로 사라진다. 그러나 BTC 자체는 Gross Proxy도 음수인지 자산 비용 표로 확인해, 비용 취약성과 자산 불일치를 함께 평가한다. 밴드 복귀 이후 Stop 사례는 복귀가 반등 지속을 보장하지 않았음을 보여준다. 비용 가정을 낮춰 Baseline을 유리하게 바꾸지 않는다. 후속 연구는 기존 규칙의 시간·자산·집중도 원인 분석까지 허용하며 Paper 승격을 뜻하지 않는다.

PROPOSAL M3 — REJECT_CANDIDATE. BTC/ETH/SOL 모두 Net 음수이며 합산 Gross Proxy도 음수다. 비용만으로 설명할 수 없는 음의 가격 손익과 Stop 손실이 존재한다. 현재 v0.1 후보의 승격 연구는 중단할 것을 권고한다. Shock 군집·기존 변동성의 영향은 위 조건별 표로 구분하지만 표본 의존성이 있어 단정하지 않는다. Mean Reversion 전략군 전체를 폐기한다는 뜻은 아니다. 새로운 아이디어는 별도 후보 ID/Version과 사전 검증 설계를 거쳐야 한다.

EXPERIMENT / 미확인: BTC·ETH·SOL 차이의 지속성, Shock 군집의 인과성, 실제 4H intrabar 경로와 실현 가능한 Stop 체결, 교환소 최소 주문 단위·호가 유동성, 새로운 미래 구간 성과. 이번 결과로 확인된 것으로 취급하지 않는다.

## 다음 실행 작업

1. MR-W02_preflight_audit.md에서 최초 P01~P10 매핑을 검토하고 회수한 대화 원문과 대조한다. 독립된 최초 설계 파일이 있다면 함께 보관한다.
2. MR-W01 기존 판정은 유지하고 MR-W02 권고를 별도 필드로 기록한다. APPROVED/PAPER로 변경하지 않는다.
3. M2에 한해 시간별 반복성과 BTC 손실 구간을 후속 연구 대상으로 삼는다. M1은 저표본과 자산 차이가 해소될 때까지 보류하고 M3 v0.1은 후보 폐기 권고를 검토한다.
4. Trend W03/W04·운영 Observer를 그대로 유지한다. 이번 진단은 주문·모의계좌·Forward Clock을 시작하지 않는다.
5. 재현을 원하면 동일 커밋의 격리된 작업 폴더에서 기존 24개와 보강 12개 검사를 실행하고, 원본 equity CSV의 바이트 해시 비교를 보완한다.

## 제한과 검증

추가 보강 검사를 포함해 36개 PASS. 원본 거래 501건·최종 손익·공동 계좌 MDD/Sharpe/PF 재현 PASS. 원본 equity CSV 전체 전송은 실패했지만 재생성한 전체 equity CSV의 SHA256이 MR-W01 manifest의 원본 해시와 정확히 일치했다. 원본 summary 지표 대조도 PASS. Clean snapshot과 W03 lock은 원본 해시로 대조했고 Raw API pages는 원본 부재로 재감사할 수 없었다. 동결 규칙·Parameter·Baseline 비용·실행 순서 변경 없음.

## 실패 원인 보충

M1: 2024년 MTM 손실 −1,863.89 USDT가 전체 누적 손실보다 크다. 손실의 시간 집중이 있고, 나머지 기간의 이익이 이를 상쇄하지 못했다. ETH/SOL은 비용 전부터 음수다. UP/LOW 구간 26건의 Stop 비율 38.46%, UP/HIGH 15건은 13.33%로 차이가 있으나 두 그룹 모두 저표본이다.

M2: BTC Gross Proxy −165.96 USDT, 비용 4,361.87 USDT로 손실 대부분이 비용 부담이다. ETH는 Gross Proxy +6,851.02이고 SOL은 +2,564.69다. 2024년 −9,042.69 USDT 손실을 여러 양수 연도가 상쇄했다. UP/HIGH 80건은 +4,173.90, UP/LOW 195건은 −2,466.31 USDT다. 이는 높은 변동성 그룹에서 반등 폭과 비용 관계가 달랐다는 연구 가설을 뒷받침하지만 HIGH 필터를 새 규칙으로 채택하지 않는다.

M3: BTC는 비용 전 +1,491.53이지만 ETH −1,678.29/SOL −2,754.62의 음의 가격 손익이 합산을 악화시켰다. UP/HIGH 51건 +1,702.12, UP/LOW 90건 −6,391.57 USDT로 변동성 그룹 차이가 컸다. 좋은 그룹만 선별해 전체 실패 판정을 바꾸지 않는다. 그룹별 차이는 추후 별도 후보의 가설 자료일 수 있다.

RESULT: 501건 전체 Gap Loss=0, STOP_GAP=0. 갭 발생 빈도와 손실 크기에 대한 실증 표본이 없으므로 Gap Risk가 낮다고 결론 내릴 수 없다. Preflight의 인위적인 하향 갭 검사 PASS는 엔진 동작 확인이며 시장에서의 빈도 검증이 아니다.

권고는 이번 진단을 본 후의 연구 판단이다. 사전에 고정한 승인 Gate나 자동 상태 변경으로 취급하지 않는다.

M3의 군집 거래 10건은 평균 +73.92 USDT, 비군집 거래 149건은 −54.15 USDT였다. 이번 표본에서 군집이 손실 원인이라는 가설은 지지되지 않았다. 군집 10건은 저표본이며 군집을 유리한 새 필터로 채택하지 않는다.

독립 출력 검증: 거래별 비용 항등식 501건, 자산별 손익 합계 9그룹, 연도별 MTM 합계, 최대 Drawdown 자산 기여 합계가 모두 원장/계좌 합계와 일치했다.
