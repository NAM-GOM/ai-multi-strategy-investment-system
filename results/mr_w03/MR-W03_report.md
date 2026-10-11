# MR-W03 — Bollinger Temporal & Parameter Robustness

RESULT: **HOLD**. meanrev_bollinger_v0.1 Baseline과 원본 실행 계약은 보존했다. 이번 결과는 Genuine Unseen OOS가 아니다.

## 재현성과 비교 방법

Source commit bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e. Python 3.14.7, pandas 3.0.1, numpy 2.3.5. MR-W01 Data Snapshot / W03 lock 재검사, MR-W02 300건 원장·비용·73개 Stop 재현, 기존36개 테스트와 harness 검사가 통과했다. Freeze SHA256: 05093a863a309412e13d028928dd1791ece0c759f8e0deb8732bdb3cb33a281c.

OAT는 한 번에 하나의 Parameter만 바꾸는 방법이다. ±20% 이웃8개를 전부 보고했으며 최적 조합을 찾지 않았다. ATR Stop은 원본 함수의 상수 distance만 별도 진단 harness에서 노출했다. Baseline harness는 원본과 전체 원장·equity가 정확히 일치했다.

시간구간은 UTC 캘린더 기준이다. 2020과2026은 부분 연도다. 전체 계좌를 연속 운용하며 구간 시작 이전 equity를 기준으로 해당 구간 가격 변화(MTM)를 배분한다. Trade PF/Expectancy는 구간 안에서 진입·청산이 모두 완료된 거래만 계산하며 boundary trade는 별도 표시한다. 실제 sample 최종 경계 청산은 포함한다. 연도별 allocated_exit 지표는 청산 연도에 전체 거래를 귀속한 보조 지표다.

자산별 수익률은 100,000 USDT 공동 자본에 대한 기여다. 자산별 독립 Backtest가 아니다. 모든 실험에서 같은 BTC→ETH→SOL 순서와 shared cash를 사용했다.

비용 stress는 기존 엔진을 전체 재실행하여 자본·수량·Stop 변화를 반영했다. MR-W02 fixed-trade repricing 수치와 다를 수 있다. 더 싼 비용 가정을 Baseline으로 선택하지 않았다.

## Baseline과 8개 OAT 이웃

| id | period | sigma | ema | stop_atr | net_pnl_usdt | total_return | mdd | profit_factor | expectancy_usdt | trade_count | positive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BASELINE | 20 | 2.00 | 200 | 2.50 | -51.98 | -0.05% | -9.33% | 1.00 | -0.17 | 300 | False |
| period_16 | 16 | 2.00 | 200 | 2.50 | -3,223.90 | -3.22% | -9.70% | 0.93 | -9.01 | 358 | False |
| period_24 | 24 | 2.00 | 200 | 2.50 | 7,531.02 | 7.53% | -6.84% | 1.24 | 32.05 | 235 | True |
| sigma_1.6 | 20 | 1.60 | 200 | 2.50 | -7,856.88 | -7.86% | -12.83% | 0.84 | -19.21 | 409 | False |
| sigma_2.4 | 20 | 2.40 | 200 | 2.50 | 28.27 | 0.03% | -7.00% | 1.00 | 0.15 | 184 | True |
| ema_160 | 20 | 2.00 | 160 | 2.50 | 2,690.92 | 2.69% | -7.92% | 1.08 | 9.93 | 271 | True |
| ema_240 | 20 | 2.00 | 240 | 2.50 | -2,656.42 | -2.66% | -9.55% | 0.94 | -8.54 | 311 | False |
| stop_atr_2 | 20 | 2.00 | 200 | 2.00 | -3,789.29 | -3.79% | -11.05% | 0.93 | -12.11 | 313 | False |
| stop_atr_3 | 20 | 2.00 | 200 | 3.00 | 693.69 | 0.69% | -7.14% | 1.02 | 2.40 | 289 | True |

이웃 양수 개수는 총 4/8이다. 각 가족의 양수 이웃 수: {'ema': 1, 'period': 1, 'sigma': 1, 'stop_atr': 1}. 값이 좋은 이웃을 선택하지 않으며 결과의 폭과 부호 일관성으로 평가한다.

EMA240은 최초38개 evaluation 봉의 EMA가 부족해 INIT_WINDOW_DIFFERENCE가 있다. 아래 보조 표는 전체 변형이 계산 가능한 동일 시작 시점 이후의 MTM과 완결 거래를 비교했다. 포지션은 여전히 원래 연속 운용 state를 유지한다.

| id | start_utc | net_pnl_usdt | mdd | profit_factor | trade_count | boundary_trade_count |
| --- | --- | --- | --- | --- | --- | --- |
| BASELINE | 2020-09-20 00:00:00+00:00 | -51.98 | -9.33% | 1.00 | 300 | 0 |
| period_16 | 2020-09-20 00:00:00+00:00 | -3,223.90 | -9.70% | 0.93 | 358 | 0 |
| period_24 | 2020-09-20 00:00:00+00:00 | 7,531.02 | -6.84% | 1.24 | 235 | 0 |
| sigma_1.6 | 2020-09-20 00:00:00+00:00 | -7,856.88 | -12.83% | 0.84 | 409 | 0 |
| sigma_2.4 | 2020-09-20 00:00:00+00:00 | 28.27 | -7.00% | 1.00 | 184 | 0 |
| ema_160 | 2020-09-20 00:00:00+00:00 | 2,690.92 | -7.92% | 1.08 | 271 | 0 |
| ema_240 | 2020-09-20 00:00:00+00:00 | -2,656.42 | -9.55% | 0.94 | 311 | 0 |
| stop_atr_2 | 2020-09-20 00:00:00+00:00 | -3,789.29 | -11.05% | 0.93 | 313 | 0 |
| stop_atr_3 | 2020-09-20 00:00:00+00:00 | 693.69 | -7.14% | 1.02 | 289 | 0 |

## 시간 구간별 Baseline

| scope | start_utc | end_utc | total_return | net_pnl_usdt | mdd | profit_factor | expectancy_usdt | trade_count | boundary_trade_count | positive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020_2022 | 2020-09-13 16:00:00+00:00 | 2023-01-01 00:00:00+00:00 | 0.99% | 989.06 | -2.76% | 1.08 | 9.99 | 99 | 0 | True |
| 2023_2024 | 2023-01-01 00:00:00+00:00 | 2025-01-01 00:00:00+00:00 | -4.17% | -4,215.40 | -9.20% | 0.79 | -33.72 | 125 | 0 | False |
| 2025_2026 | 2025-01-01 00:00:00+00:00 | 2026-10-02 12:00:00+00:00 | 3.28% | 3,174.36 | -2.80% | 1.44 | 41.77 | 76 | 0 | True |

CAGR은 구간 날짜 길이를365.25일/년으로 환산했다. Sharpe는4H 수익률과2190봉/년, risk-free0으로 계산했다. CSV는 수익률을 소수비율로 저장한다. 부분 연도·저표본 그룹은 수치를 일반화하지 않는다.

## 자산별 일관성

| asset | net_pnl_usdt | total_return | profit_factor | expectancy_usdt | trade_count | positive |
| --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | -4,527.83 | -4.53% | 0.73 | -43.12 | 105 | False |
| ETHUSDT | 3,913.97 | 3.91% | 1.35 | 39.94 | 98 | True |
| SOLUSDT | 561.89 | 0.56% | 1.05 | 5.79 | 97 | True |

| scope | asset | net_pnl_usdt | profit_factor | trade_count | boundary_trade_count | positive |
| --- | --- | --- | --- | --- | --- | --- |
| 2020_2022 | BTCUSDT | -1,058.61 | 0.77 | 32 | 0 | False |
| 2023_2024 | BTCUSDT | -2,913.54 | 0.69 | 49 | 0 | False |
| 2025_2026 | BTCUSDT | -555.68 | 0.81 | 24 | 0 | False |
| 2020_2022 | ETHUSDT | 1,810.20 | 1.42 | 36 | 0 | True |
| 2023_2024 | ETHUSDT | -102.34 | 0.98 | 33 | 0 | False |
| 2025_2026 | ETHUSDT | 2,206.10 | 2.01 | 29 | 0 | True |
| 2020_2022 | SOLUSDT | 237.46 | 1.06 | 31 | 0 | True |
| 2023_2024 | SOLUSDT | -1,199.52 | 0.82 | 43 | 0 | False |
| 2025_2026 | SOLUSDT | 1,523.95 | 1.74 | 23 | 0 | True |

## 비용 stress

| id | fee | slip | net_pnl_usdt | mdd | profit_factor | expectancy_usdt | trade_count | positive |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BASELINE | 10 | 5 | -51.98 | -9.33% | 1.00 | -0.17 | 300 | False |
| MODERATE | 10 | 10 | -2,699.68 | -10.24% | 0.93 | -9.00 | 300 | False |
| SEVERE | 20 | 20 | -15,447.98 | -17.55% | 0.65 | -50.98 | 303 | False |

## 2024년 Stop와 손실 집중

Stop 손실과 비Stop 양수·음수 거래의 합이 전체 순손익이다. 표의 비용은 Net에 이미 들어 있으며 다시 빼지 않는다. Signal 후6봉의 가격은 청산 이후도 포함할 수 있으므로 주문 성과와 분리한다.

| group | trade_count | stop_count | stop_ratio | stop_loss_usdt | nonstop_positive_pnl_usdt | nonstop_negative_pnl_usdt | trade_net_pnl_usdt | trade_fees_usdt | trade_slippage_usdt | after_6bar_negative_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 62 | 25 | 40.32% | -13,432.22 | 4,490.16 | -100.63 | -9,042.69 | 1,324.44 | 662.22 | 62.90% |
| OTHER_FULL_YEARS_2021_2022_2023_2025 | 193 | 41 | 21.24% | -21,799.51 | 29,413.68 | -1,041.41 | 6,572.76 | 3,683.51 | 1,841.76 | 39.38% |

| asset | trade_count | stop_count | stop_ratio | trade_net_pnl_usdt | gross_proxy_usdt | below_entry_ratio | after_6bar_negative_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BTCUSDT | 26 | 11 | 42.31% | -4,231.76 | -3,161.10 | 88.46% | 69.23% |
| ETHUSDT | 12 | 5 | 41.67% | -2,152.45 | -1,771.64 | 83.33% | 75.00% |
| SOLUSDT | 24 | 9 | 37.50% | -2,658.48 | -2,123.29 | 83.33% | 50.00% |

| month | trade_count | stop_count | trade_net_pnl_usdt | profit_factor | low_sample |
| --- | --- | --- | --- | --- | --- |
| 2024-01 | 5 | 3 | -1,271.02 | 0.22 | True |
| 2024-02 | 6 | 0 | 887.81 | 100.32 | True |
| 2024-03 | 7 | 3 | -1,197.52 | 0.27 | True |
| 2024-04 | 6 | 3 | -1,197.70 | 0.27 | True |
| 2024-05 | 5 | 1 | -230.62 | 0.57 | True |
| 2024-06 | 3 | 0 | 200.35 | 3.74 | True |
| 2024-07 | 3 | 1 | -155.67 | 0.72 | True |
| 2024-08 | 3 | 3 | -1,619.49 | 0.00 | True |
| 2024-10 | 7 | 4 | -2,051.67 | 0.06 | True |
| 2024-11 | 7 | 2 | -404.14 | 0.62 | True |
| 2024-12 | 10 | 5 | -2,003.02 | 0.23 | True |

| direction | vol | trade_count | stop_count | stop_ratio | trade_net_pnl_usdt | low_sample |
| --- | --- | --- | --- | --- | --- | --- |
| FLAT | LOW | 4 | 2 | 50.00% | -782.41 | True |
| UP | HIGH | 13 | 5 | 38.46% | -1,821.78 | True |
| UP | LOW | 45 | 18 | 40.00% | -6,438.50 | False |

2024 Stop 발생일은 18일이며 2개 이상 자산이 같은 UTC 날짜에 Stop을 기록한 날은 7일이다. 이는 위험 동시 노출의 관찰이며 인과관계·통계적 유의성을 입증하지 않는다.

## 연도·자산 의존성

| scope | net_pnl_usdt | allocated_exit_trade_count | allocated_exit_net_pnl_usdt | trade_count | boundary_trade_count | profit_factor |
| --- | --- | --- | --- | --- | --- | --- |
| 2020 | 639.85 | 13.00 | 639.85 | 13 | 0 | 1.56 |
| 2021 | 1,942.94 | 68.00 | 1,942.94 | 68 | 0 | 1.25 |
| 2022 | -1,593.73 | 18.00 | -1,593.73 | 18 | 0 | 0.57 |
| 2023 | 4,827.29 | 63.00 | 4,827.29 | 63 | 0 | 1.69 |
| 2024 | -9,042.69 | 62.00 | -9,042.69 | 62 | 0 | 0.33 |
| 2025 | 1,396.26 | 44.00 | 1,396.26 | 44 | 0 | 1.32 |
| 2026 | 1,778.11 | 32.00 | 1,778.11 | 32 | 0 | 1.63 |

2021~2025 full years 중 양수 연도 상위2개 손익 비중은 82.90%. 양수 자산 손익의 최대 자산 비중은 87.45%. 음수 연도와 음수 자산도 전부 표에 유지한다. 유리한 그룹만 제외·선택하지 않는다.

## 판정 근거



| gate | pass |
| --- | --- |
| BASELINE_POSITIVE | False |
| TEMPORAL_2_OF_3 | True |
| ASSET_2_OF_3 | True |
| NEIGHBOR_6_OF_8 | False |
| EACH_FAMILY_1_OF_2 | True |
| NEIGHBOR_MDD_1_5X | True |
| MODERATE_POSITIVE | False |
| YEAR_TOP2_MAX_80 | False |
| ASSET_MAX_80 | False |

## REJECT 기준

| gate | triggered |
| --- | --- |
| PERSISTENT_LOSS | False |
| JOINT_FRAGILITY | False |
| SEVERE_RISK | False |

LOW_SAMPLE: False. Positive neighbors 4/8, 시간구간 2/3, 자산 2/3.
Full-year 양수 손익 상위2개 연도 비중 82.90%; 양수 자산 최대 기여 87.45%.
연도·자산 집중도는 총손익이 거의0인 분모 대신 양수 기여 합을 분모로 삼았다.
Baseline 손실만으로 자동 REJECT하지 않으며, 사전 복합 조건의 충족 여부를 위 표에 명시한다.

## 후속 조치

현재 v0.1의 후속 검증 단계 승격을 보류한다. 자료 부족과 취약성의 원인을 유지한 채 재검토한다.
유리한 이웃·연도·자산·환경을 새로운 Baseline으로 채택하지 않는다. 새로운 아이디어는 별도 후보/Version으로 시작하고 전체 검증을 다시 설계한다.
Trend W03/W04와 운영 Observer는 이번 작업에서 접근하거나 변경하지 않았다.
사용자는 이 판정을 05 Strategy Registry의 MR-W03 연구 판정 필드에 기록하고 기존 MR-W01/MR-W02 판정 이력을 함께 보존한다.


## 확인되지 않은 가설과 제한

2024년은 62건 중 25건이 Stop으로 끝나 Stop 비율이 40.32%였다. 다른 full years(2021·2022·2023·2025)의 21.24%보다 높았다. 평균 이익도 214.70에서 144.84 USDT로 작아졌다. 2024년 비용 전 가격 손익 자체가 −7,056.03 USDT이고 비용 1,986.66 USDT가 더해져 −9,042.69 USDT가 됐다. BTC·ETH·SOL 모두 해당 연도의 비용 전 손익부터 음수였다. 따라서 2024 손실은 비용 부담과 함께 Stop 증가·반등 이익 감소를 동반했다. 좁아진 Stop 거리나 환경 차이가 원인이었는지는 추가 가설이며 이번 분석만으로 인과를 확정하지 않는다.

4개 이웃만 양수였고 나머지4개는 음수였다. 각 가족 안에서도 양수1개·음수1개로 갈렸으며, 이웃 전체 손익 범위는 −7,856.88~+7,531.02 USDT였다. 좋은 이웃을 고르면 성과를 개선한 것처럼 보일 수 있으나, 이번 결과는 넓은 안정 구간을 입증하지 못한다. Moderate 비용 full rerun −2,699.68, Severe −15,447.98 USDT도 취약성으로 유지한다. 비용 stress는 MR-W02의 fixed-trade repricing과 방식이 달라 그 수치와 직접 동일하다고 주장하지 않는다.

Baseline의 평균 거래 수익률(expectancy_return)은 양수지만 USDT Expectancy는 음수다. 거래별 비중과 수량이 달라 단순 수익률 평균과 자본 손익이 다를 수 있다. 판정은 Freeze에 명시한 Net PnL·PF·USDT Expectancy를 사용하며, 유리한 지표로 교체하지 않는다.

2024 Stop 증가를 거시 뉴스나 특정 사건의 인과로 확정하지 않는다. 낮은 변동성·밴드 복귀 후 추가 하락·여러 자산 동시 Stop은 원인 후보이며 새 필터로 채택하지 않는다. 관찰 기간이 이미 노출됐고 OAT이웃도8개뿐이므로 전역적 안정성이나 새로운 미래 성과를 증명하지 못한다.

MR-W02 below_entry_ratio는 bool/object 집계가 Stop 수보다 비정상적으로 작았다. 이번에는 각 거래의 실제 보유 종가·청산 raw 가격을 0/1로 다시 집계했다. 이 보조 보고 수치의 오류는 원장·Net PnL·전략 규칙과 분리하며 MR-W02 원본을 수정하지 않았다. 이번 report/CSV의 below_entry_ratio만 수정 계산을 사용한다.

OHLC만으로 intrabar 가격 순서와 실제 체결 유동성을 복원할 수 없다. Stop 시간은 봉 종가 표기이므로 최대4시간 오차가 있다. Raw API pages는 기존 snapshot에 없으므로 raw-page 재감사는 못했다. Clean snapshot과 동결 lock 해시 검사는 통과했다. 결과가 기존 v0.1 승인·Paper 상태를 바꾸지 않는다.

## 표기 정정과 설계 보존

Freeze 원문은 EMA240 부족 구간을39봉으로 적었으나, 0-based index와201봉 제외 기준으로 직접 계산하면38봉이다. EMA240은 index239부터 계산 가능하고 평가 시작은 index201이다. 주 실험의 시작·끝과 지표·신호 처리는 변경하지 않았다. 보조 common-ready 시작의 index240을239로 정정했다. 부분 연도의 마지막 연도는 exclusive endpoint 직전 연도로 계산해 2021~2025의 full-year 표시를 바로잡았다. 판정 Threshold·우선순위·8개 이웃은 변경하지 않았으며 최종 HOLD도 유지됐다.
