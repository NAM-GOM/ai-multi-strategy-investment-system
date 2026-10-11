# MR-W02 Preflight Traceability Audit

RESULT: MR_W02_PREFLIGHT_PASS. 기존 24개 + 보강 12개 = 36개 테스트 통과.

원래 P01~P10은 이전 대화에서 회수한 설계 항목이다. 최초 설계 문서의 독립 파일/해시는 확보되지 않았으므로 설계 출처는 회수한 대화 기록으로 표시한다. 기존 실행 P번호와 같다고 간주하지 않는다.

| 최초 ID | 최초 요구 | 실행 Gate | 검증 코드 | 재검증 |
| --- | --- | --- | --- | --- |
| P01 | RSI 교차 | 실행 P04 + P02 | test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit; test_P02_wilder_seeding_and_reference_rsi; original_P01 boundary | PASS_RETESTED |
| P02 | Bollinger 이탈 후 복귀 | 실행 P04 + P02 | test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit; original_P02 boundary | PASS_RETESTED |
| P03 | Shock 회복 | 실행 P04 + P02 | test_P04_exact_conditions_inclusive_crossings_and_no_extra_exit; original_P03 strict recovery | PASS_RETESTED |
| P04 | 확정봉 전 신호 금지 | 실행 P03 + P05 | test_P03_no_lookahead_warmup_or_unconfirmed_signal; test_P05_next_open_exit_and_last_signal_unfilled; original_P04 future mutation | PASS_RETESTED |
| P05 | 진입봉 즉시 Stop | 실행 P06 | test_P06_entry_bar_stop_and_adverse_gap[entry_stop] | PASS_RETESTED |
| P06 | Stop 하향 갭 | 실행 P06 | test_P06_entry_bar_stop_and_adverse_gap[gap,signal_gap] | PASS_RETESTED |
| P07 | 현금·비중 제한 | 실행 P07 + P09 | test_P07_risk_cap_cash_and_fixed_symbol_order; test_P07_exit_before_entry_allocation; audit | PASS_RETESTED |
| P08 | 중복 진입 금지 | 실행 P08 | test_P08_no_pyramiding_no_duplicate_and_no_ema_forced_exit; audit | PASS_RETESTED |
| P09 | 누락·중복 데이터 | 실행 P01 | test_P01_quality_rejects[duplicate,gap] | PASS_RETESTED |
| P10 | 동일 Dataset Hash | 실행 P01 | test_P01_frozen_snapshot_hash_cutoff_common_sample; original_P10 hash tamper | PASS_RETESTED |

기존 코드에서 핵심 기능 누락은 발견하지 않았다. 감사 누락은 최초 번호와 실행 번호의 매핑 부재였다. 경계값의 부정 사례·미래 데이터 변조·해시 훼손 거부 검사를 별도 추가했다. 기존 테스트와 전략 코드는 수정하지 않았다.

원본 커밋: bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e. Python 3.14.7, pandas 3.0.1, numpy 2.3.5.

Dataset SHA256:

| Asset | SHA256 |
| --- | --- |
| BTCUSDT | f4ddf0ec4354fe66f2635887a809e433962877b9b090a728a02d3721a0183059 |
| ETHUSDT | f0cda00c5f062f947c0175c911b8afb521a62d38d04d3f45c220a56d3e7002bb |
| SOLUSDT | fe428dcdce137be444ab38f2c497651455173b4bbcbc2a5cdc75e386e1265187 |

501개 거래의 모든 원본 컬럼 및 각 전략의 Return/MDD/Sharpe/PF/Trade Count 재현 PASS. 거래 원장·요약 CSV·전략 코드·기존 테스트·W03 lock 해시 대조 PASS. 원본 equity CSV 전체 전송은 실패했지만 재생성한 전체 equity CSV의 SHA256이 MR-W01 manifest 원본 해시와 정확히 일치했다. 원본 summary와의 지표·최종 손익 대조도 PASS. Raw API page 재감사는 원본 페이지 부재로 수행하지 못했다. 이는 기존 MR-W01 제한으로 남긴다. 운영 Observer 접근·변경 없음.

....................................                                     [100%]
36 passed in 1.59s
