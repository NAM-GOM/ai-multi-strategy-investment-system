# MR-W03 Specification Deviation

판정: MR_W03_HOLD 유지. 최초 지시문, 실행 전 Preflight, 실제 설정과 실행 후 정정을 분리하여 기록한다. 원본 지시문은 현재 대화에 제시된 MR-W03 — Bollinger Temporal & Parameter Robustness Cycle이다. 최초 지시문에는 OAT 값·간격, 비용 stress 값, 수치 판정 Threshold가 지정되지 않았다.

| ID / 분류 | 최초 지시 또는 Freeze | 실제 실행 | 영향·처리 |
| --- | --- | --- | --- |
| SD01 / 사전 상세화 | Bollinger Period/StdDev/EMA/ATR Stop OAT; 수치 미지정 | 각 baseline의 ±20%: 16/24, 1.6/2.4, 160/240, 2/3 | 실행 전 Preflight/JSON에 고정한 설계 선택. 사후 최적화나 지시 수치 위반으로 분류하지 않음 |
| SD02 / material scope qualification | Bollinger Period OAT; entry-only인지 exit 포함인지 미지정 | Band 계산과 SMA exit period를 함께 16/24로 변경 | 설정 변수 하나지만 진입·청산 두 행동에 영향을 준다. **entry band 기간만의 독립 효과로 해석할 수 없다.** 실행 전 명시됐고 baseline20은 유지 |
| SD03 / engine implementation deviation | 동일 Backtest 및 Execution Engine | Stop2.5가 원본 engine 상수라 별도 harness의 함수 서명과 distance 한 곳을 parameterize | Baseline2.5의 원본 전체 trade/equity parity와 합성 gap/entry Stop 검사 기록 있음. **모든 시나리오가 원본 engine byte-identical이라는 주장 금지.** 원본 source 미수정, 이 구현 차이는 유지해 공개 |
| SD04 / deterministic initialization difference | 동일 snapshot 재사용, 같은 시간 경계 | EMA240은 평가 시작 후38봉 indicator unavailable | 동일 data/sample bounds 유지; common-ready index239/2020-09-20 00:00 UTC 보조 scope. 이는 새 데이터가 아니며 state reset도 아님 |
| SD05 / post-run erratum | Freeze가 EMA240 부족39봉, 보조 시작 index240으로 기재 | 실제239−201=38봉; common-ready index239로 정정 | 원문·original Freeze Hash 보존, append 정정. 주 baseline/시간구간/8이웃/Threshold 미변경. 보조 scope 시작의 off-by-one 정정으로 공개 |
| SD06 / post-run classification correction | 부분 연도 및 full years2021~2025 사용 | exclusive endpoint 직전 연도로 마지막 부분 연도 판별 정정 | full-year 표시 및 집중도 계산의 코드 정정; 기준80%/full years 범위 미변경. 원문을 덮어쓰지 않음 |
| SD07 / stress design detail | Baseline 비용 및 Stress 민감도, 구체값 미지정 | fee10/slip10 및20/20 bps/side; cash/quantity/Stop 포함 dynamic rerun | 실행 전 고정. MR-W02 fixed-trade repricing과 방법 차이므로 수치 직접 동등성 주장 금지; baseline10/5 유지 |
| SD08 / reporting error correction | MR-W02 재현 | below_entry_ratio bool/object 집계 오류를 numeric0/1로 정정 | 보조 가격경로 보고값만 수정. W02 원본·원장·PnL·전략 규칙 미변경; 결과를 원본 전 지표 exact reproduction으로 일반화하지 않음 |
| SD09 / 사전 evaluation 상세화 | PASS/HOLD/REJECT 기준 사전 Freeze | Positive=Net>0/PF>1/USDT expectancy>0; sample/neighbor/MDD/concentration gates 지정 | 이전 MR-W01 reporting label과 구별. 신규 W03 사전 기준이며 결과 후 Threshold·우선순위 수정 없음 |
| SD10 / artifact portability | 원본 code/snapshot 재사용 | local source fetch 일부 final LF 추가; runner는 Windows 절대 경로 사용 | upstream commit Hash와 local raw Hash 함께 보존. 새 환경 경로 설정 없이 바로 재실행된다는 주장 금지; 이번에는 rerun 안 함 |

이 기록은 새 실험을 허용하거나 유리한 설정을 채택하는 문서가 아니다. SD02/SD03 때문에 Period entry-only 민감도나 원본 engine 불변성에 대한 증거 범위를 제한한다. 이번 최종화에서 추가 Backtest·code fix·재설계로 이 차이를 없애지 않았다.

사전 Freeze와 실행 당시 errata를 보존하고 현재 HOLD를 유지한다. 새로운 Mean Reversion 전략, Parameter, exit 분리 또는 precision 계약 아이디어는 별도 Version과 사전 연구 계획으로 다루어야 한다. 기존 결과의 유리한 자산·연도·환경·Parameter를 v0.1 Baseline으로 선택하지 않는다.
