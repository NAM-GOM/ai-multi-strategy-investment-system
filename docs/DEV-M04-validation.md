# DEV-M04 검증 보고서 — 재검증본

재작성일: **2026-10-10 KST**. 저장소: `NAM-GOM/ai-multi-strategy-investment-system`.
브랜치: `dev-m04-strategy-observer`.

최종 기술 분류는 **DEV-M04_PASS_WITH_FLAGS**다. 01:00·05:00 KST의 실제 마감에서
BTC/ETH/SOL 확정봉과 9개 Frozen 결정을 각각 영구 저장했다. 이번 읽기 전용 재감사에서도
18개 실시간 indicator snapshot·입력 해시·결정 해시가 정확히 일치했다.
두 새 프로세스 재시작의 추가 결정은 0개다. Windows/Linux CI 및 Ruff/Format은 통과했다.

독립적인 W03 전체 봉 지표/boolean 덤프 부재, 실제 네트워크 중복 마감 미관찰,
두 구간 사이 연속 관찰 부재를 검증 한계로 유지한다. 이 기술 판정은 W04 Preflight PASS,
전략 APPROVED 또는 Formal Paper 시작 승인이 아니다.

## 1. 기준 커밋과 재검증 범위

| 구분 | Commit SHA |
|---|---|
| M03 최종 동결·원격 반영·M04 분기 기준 | `1b1bf582f34a526d9204a084dc4573c79efa124e` |
| M04 최초 구현 | `2ac688b8e685794eb488860de297f37b2992bf71` |
| 실제 야간 관찰 실행 및 당시 두 OS CI | `9985e2c999185d4793612bc0edb4552f57c62d12` |
| 이번 재검증 기준 HEAD·최종 감사 도구 CI | `11bfffbdfb529f3da8ac11ebd49fb1ed81c23725` |

이번 변경은 보고서와 검증 요약에 한정한다. Frozen 규칙, 구현 소스, 시장 DB,
main/M03 이력, 전략 상태와 W04 Clock은 변경하지 않는다. 재작성 보고서의 게시 커밋은
위 기준 HEAD의 후속 커밋이며 Git 이력과 최종 전달 링크로 식별한다.

새 마감을 이번 재작성 시각에 관찰한 것은 아니다. 기존 01시·05시의 DB와
result/collector/observer/restart JSON을 다시 읽고 검증했다.

| 증거 유형 | 근거 | 판정 범위 |
|---|---|---|
| 역사 재현 | [재현 JSON](DEV-M04-reproduction.json), `artifacts/w03` | Frozen 원본·원장·자본 곡선 일치 |
| 결정적·회귀 검사 | `tests/test_observer.py` 및 기존 M01/M02/M03 테스트 | 정상·오류·충돌·강제 종료 시 동작 |
| 실제 Windows 마감 | 두 live 폴더의 원본 DB·실행 JSON | WS 확정봉·동일 봉 9개 저장·재시작 |
| 이번 읽기 전용 재감사 | [야간 감사 JSON](DEV-M04-overnight-audit.json) | 원본 보존·지표·입력/결정 hash 재계산 |
| 기준 HEAD 두 OS CI | [CI 요약](DEV-M04-report-ci.json) | Windows/Linux pytest·Ruff·Format |

## 2. M03 선행 조건

M03의 로컬 수정과 실제 2026-10-09 17:00 KST 마감 결과를 검토했다. 기존 가격 receipt가
저장된 재시작에서 신규 쓰기 0개를 실패로 오인하는 문제를 추가 수정했다.
동결 당시 **245 passed / 8 skipped**, Ruff/Format PASS 후 원격 M03 브랜치에
정상 fast-forward 반영하고 그 SHA에서 M04를 생성했다.

M03의 실제 네트워크 duplicate-close 시험은 **NOT_TESTED**, 과거 BTC 12:47 이벤트의
정확한 원인은 미입증 상태다. 이들을 M04 PASS로 대체하지 않는다.
상세: [M03 동결 검토](DEV-M03-freeze-review.md).

## 3. Frozen Source/Config/Data Audit

원본 W03 패키지·코드·설정·CSV·검증 원장을 확보했다. 26개 파일과 원본 매핑,
runtime parameter 및 의존성 버전을 확인했다. 소스 바이트와 초기화 래퍼를 재사용한다.

| 항목 | SHA-256 |
|---|---|
| 원본 W03 패키지 | `2ad1bca4fcd1a0694bd39bafff3d3f6b93beccc3f7237b0376a73e030f9ad155` |
| 전략 코드 | `0850fcc32356a4275e0795cece08a6f6d701220b941ce94e2b95dd1ce802a965` |
| 설정/파라미터 | `6a7ce60ed2199cc432cbd98733e3b72f4d926e7120cbc5e69d224b6d9fd0863b` |
| BTC 데이터 | `f4ddf0ec4354fe66f2635887a809e433962877b9b090a728a02d3721a0183059` |
| ETH 데이터 | `f0cda00c5f062f947c0175c911b8afb521a62d38d04d3f45c220a56d3e7002bb` |
| SOL 데이터 | `fe428dcdce137be444ab38f2c497651455173b4bbcbc2a5cdc75e386e1265187` |
| 통합 Manifest | `8508a1bd15d68b04fe0428c298330961859af88a9a26d565d23fcdf1d93bd38c` |
| Baseline | `faa1492c637dd155c08c30c755359a52b2cf1e14f0c20d46b1e14c90f21993b2` |
| lock.json 바이트 | `b1659e920f6b5e718a9073ddca8a0c91f6ae16993100af9d3a57758d73a68d30` |

| 전략 ID | 버전 | 보존 규칙 | 원본 신호 차단 행 수 |
|---|---|---|---:|
| `trend_ma_v0.1` | `0.1` | EMA50/200 교차 | 201 |
| `trend_donchian_v0.1` | `0.1` | Entry55/Exit20, current bar 제외 | 56 |
| `trend_tsmom_v0.1` | `0.1` | Momentum180의 0 교차 | 182 |

Manifest 버전은 `v0.1`로 표기한다. 위 행 수는 원본 초기화 기준이며 M04가 새로 정한
전략 파라미터가 아니다. ATR20 EWM `adjust=False`, Stop 3×signal ATR, Risk 0.5%,
Asset Cap 33.3%, Fee 10bps/side, Model Slippage 5bps/side, long-only/no leverage/
no pyramiding을 보존한다. 공통 초기화는 2020-08-11 04:00 UTC, 평가 구간은
2020-09-13 16:00 UTC~2026-10-02 08:00 UTC open이다. 마지막 close는 연구 동결
12:00 UTC다. 7일·42봉을 EMA200/Momentum180의 충분한 초기화로 인정하지 않는다.

## 4. W03 9개 조합 재현

세 전략의 원본 공유 포트폴리오 trade ledger와 equity curve, 총 6개 산출물이 정확히
일치했다. CR/LF 전달 형식만 정규화하고 숫자 문자열·시각·순서·포지션 계산·ATR·
손절 초기화·next-bar timing을 비교했다. 새 수치 허용 오차를 도입하지 않았다.

| 전략 | 자산 | Entry boolean | Exit boolean | 원장 거래 수(terminal 포함) |
|---|---|---:|---:|---:|
| T1 | BTC | 32 | 31 | 32 |
| T1 | ETH | 37 | 36 | 37 |
| T1 | SOL | 36 | 35 | 36 |
| T2 | BTC | 439 | 500 | 87 |
| T2 | ETH | 444 | 493 | 99 |
| T2 | SOL | 460 | 579 | 91 |
| T3 | BTC | 198 | 197 | 198 |
| T3 | ETH | 204 | 203 | 204 |
| T3 | SOL | 200 | 200 | 199 |

각 조합은 13,460행이다. Boolean 수와 실행 원장 거래 수는 서로 다른 검증 값이다.
지표/신호 prefix 재계산과 미래 가격 변경 시험도 통과했다.

**OBS-02 증거 한계:** 독립적인 W03 전체 봉 indicator/boolean 덤프가 없다.
모든 과거 봉을 별도 당시 지표 덤프와 대조했다는 주장은 하지 않는다. 실제 근거는
바이트 동일 원본, 원본 원장/자본 곡선, 진입 ATR/손절 및 prefix 일치다.
따라서 `PASS_WITH_EVIDENCE_FLAG`를 유지한다. 기존 W04 117행 inventory는 새로
수행한 W03 독립 재현으로 계산하지 않는다.

## 5. 실제 01시·05시 마감 및 재시작

| 항목 | 01시 구간 | 05시 구간 |
|---|---|---|
| 마감 KST | 2026-10-10 01:00 | 2026-10-10 05:00 |
| 마감 UTC | 2026-10-09 16:00 | 2026-10-09 20:00 |
| Collector 실행 KST | 00:50:00.631~01:07:08.885 | 04:50:01.291~05:07:08.858 |
| WS uptime / 메시지 | 1025.017s / 4419 | 1025.019s / 4195 |
| 실제 확정 WS 봉 | BTC/ETH/SOL 3개 | BTC/ETH/SOL 3개 |
| 시장 DB 출처 수 | REST_BOOTSTRAP 162 + WS_LIVE 3 | REST_BOOTSTRAP 162 + WS_LIVE 3 |
| 시장 품질(완료 시점) | COMPLETE | COMPLETE |
| 미해결 gap / invalid / conflict | 0 / 0 / 0 | 0 / 0 / 0 |
| LIVE batch / 결정 | 1 / 9 | 1 / 9 |
| NO_ACTION | 8 | 8 |
| 다른 후보 | T3 ETH EXIT_CANDIDATE | T3 ETH ENTRY_CANDIDATE |
| Observer DB 전체 결정 | prelaunch 9 + live 9 = 18 | prelaunch 9 + live 9 = 18 |
| Observer → restart PID | 1856 → 18212 | 27928 → 28676 |
| 재시작 상태 / 추가 결정 | ALREADY_COMMITTED / 0 | ALREADY_COMMITTED / 0 |
| 읽기 전용 독립 재감사 | INDEPENDENT_LIVE_AUDIT_PASS | INDEPENDENT_LIVE_AUDIT_PASS |

18개 live 결정은 모두 `LIVE_OBSERVATION`, 평가 대상 원본 봉은 `WS_LIVE`다.
각 DB의 9개 checkpoint, 완전한 batch hash, decision hash, SQLite integrity/foreign key,
원본 파일 감사 전후 해시를 확인했다. 18개 snapshot/input hash를 재계산해 정확히
일치했다. 원본 DB·로그·JSON은 변경하지 않았다.

| T3 ETH 실제 지표 | 01시 | 05시 |
|---|---:|---:|
| ATR20 | 34.19768487345464 | 33.727800629781896 |
| Momentum180 | -0.0004939243291864903 | 0.004887466588791689 |
| Entry / Exit | false / true | true / false |
| 마감 경계 이후 평가 지연 | 1.080s | 1.039s |

후보는 보유 포지션이나 체결을 뜻하지 않는다. 전체 snapshot·개별 입력 해시는
[야간 감사 JSON](DEV-M04-overnight-audit.json)에 보존했다.
원본 폴더: `data/m04-live-20261010T010000/`, `data/m04-live-20261010T050000/`.

이들은 **독립 DB의 두 관찰 구간**이며 01:07~04:50 연속 관찰을 입증하지 않는다.
각 종료 DB의 품질은 실제 완료 시점으로 판단한다. 나중 봉이 없다는 이유로 종료된
구간을 재분류하지 않는다. 600초 public smoke는 실제 마감 0개, prelaunch 결정 9개였고
[smoke 요약](DEV-M04-smoke-summary.json)에 보존하며 OBS-12에 포함하지 않는다.

## 6. 결정적 테스트·회귀·두 OS CI

기준 HEAD `11bfffbdfb529f3da8ac11ebd49fb1ed81c23725`의
[CI 37985954969](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37985954969)를
재조회하고 두 job 원본 로그의 pytest/Ruff/Format 결과를 확인했다.

| 환경 | Pytest | Ruff | Format |
|---|---|---|---|
| Windows / Python 3.14.7 | 283 passed, 8 skipped / 53.38s | PASS | PASS, 53 files |
| Linux / Python 3.14.7 | 283 passed, 8 skipped / 34.59s | PASS | PASS, 53 files |

8 skipped는 기존 opt-in 네트워크/계정 검사이며 PASS 수에 포함하지 않는다.
이전 로컬 전체 회귀는 283 passed / 8 skipped(41.50s)였다. 이번 재작성에서는
읽기 전용 야간 감사와 Ruff/Format을 다시 실행했다. 전체 pytest를 이번에 새로
실행했다고 표시하지 않는다. 실제 야간 실행 SHA의
[CI 37936170401](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37936170401)와
[야간 CI JSON](DEV-M04-overnight-ci.json)도 별도로 유지한다.

| 검사 영역 | 대표 테스트 / 실제 근거 |
|---|---|
| Frozen 9개 재현 | `test_w03_nine_combinations_exact_original_ledger_equity` |
| Warmup·Momentum180·Donchian | `test_frozen_warmup_blocked`, `test_donchian_current_bar_excluded_and_momentum_180` |
| 확정봉·미래 정보 | `test_unconfirmed_bar_blocked`, `test_future_ingestion_blocked`, 미래 지표 변경 검사 |
| REST/LIVE·복구 분리 | `test_backfill_live_separation`, `test_missing_then_recovery_remains_state_only` |
| barrier·gap·OHLCV | `test_three_symbol_barrier_blocks_all`, gap/invalid OHLCV 검사 |
| 입력/소스/설정 변경 | `test_input_hash_rejects_mutation`, `test_source_parameter_data_change_detected` |
| 중복·불변·DB 실패 | 충돌 STOP, 9개 checkpoint transaction rollback, immutable/corruption 검사 |
| Crash/Restart·STOP 복구 | 실제 subprocess 강제 종료·CLI 재시작, `test_persistent_stop_survives_new_store` |
| Read-only·실행 경계 | `test_read_only_market_repository`, `test_cli_no_credentials_or_execution` |
| 정상 무신호 배치 | `test_no_action_batch_is_persisted` 및 두 실제 batch |

## 7. Acceptance Gate 판정

| Gate | 결과 | 근거와 검증 범위 |
|---|---|---|
| OBS-01 | PASS | Frozen source/config/runtime parameter 및 26개 파일 hash |
| OBS-02 | PASS_WITH_EVIDENCE_FLAG | 9개 조합, 원본 6개 원장/자본 산출물 일치; 독립 전체 지표 덤프 부재 |
| OBS-03 | PASS | 원본 초기화·warmup 및 두 live DB의 연속된 과거 이력 |
| OBS-04 | PASS | 미확정/미래 차단 테스트 및 실제 WS 확정봉 |
| OBS-05 | PASS | W03/REST/WS 출처와 input hash 보존·재계산 |
| OBS-06 | PASS | 3심볼 미완료 차단 및 실제 동일 봉 9개 batch |
| OBS-07 | PASS | 별도 SQLite 영속 저장, 각 batch NO_ACTION 8개 포함 |
| OBS-08 | PASS | 두 새 프로세스 ALREADY_COMMITTED·추가 결정 0 |
| OBS-09 | PASS | 오류·충돌·DB rollback·상태 훼손 fail-closed 결정적 검사 |
| OBS-10 | PASS | 기준 HEAD Windows/Linux pytest·Ruff·Format |
| OBS-11 | PASS | 동일 전체 CI에 기존 M01/M02/M03 회귀 포함 |
| OBS-12 | PASS | 두 실제 마감·snapshot·영속 저장·재시작·출처 검증 |
| OBS-13 | PASS | Observer 주문/Paper 경로 미호출, 실제 보고서 execution=false |
| OBS-14 | PASS | Formal 시작 false, W04 상태 접근/변경 경로 없음 |

OBS-09의 장애 주입은 결정적 테스트 결과이며 두 실제 구간에서 해당 장애가 모두
발생했다는 뜻은 아니다. OBS-02를 증거 한계가 없는 무조건 PASS로 해석하지 않는다.

## 8. 미관찰 항목과 상태 보존

| 항목 | 상태 | 처리 |
|---|---|---|
| 독립 W03 전체 봉 indicator/boolean 덤프 | MISSING_ARTIFACT_FLAG | 원본/원장/prefix 증거 범위만 주장 |
| 실제 네트워크 duplicate-close 수신 | NOT_OBSERVED | 두 실행 duplicate_closures=0; 결정적/재시작 검사와 구분 |
| 01:07~04:50 연속 WS 관찰 | NOT_OBSERVED | 두 독립 구간만 PASS |
| 기존 M03 BTC 12:47 개별 원인 | UNPROVEN | 과거 증거 한계 유지 |
| 기존 opt-in 검사 8개 | SKIPPED | pytest PASS 수에 포함하지 않음 |
| W04 Preflight / Gate F / Formal 성과 | NOT_EVALUATED_BY_M04 | 별도 승인·공식 Manifest·W04 엔진 책임 |

T1의 기존 `W03_PASS_WITH_FLAGS`, T2/T3의 `W03_HOLD`를 유지한다.
T1 Continuity Shadow와 Formal 상태를 혼합하지 않는다. 연구 동결
`2026-10-02T12:00:00Z`를 유지한다. REST_BOOTSTRAP/REST_RECOVERY나 놓친 봉은
state backfill로만 사용하며 `FORMAL_W04_ELIGIBLE`은 발행하지 않는다.

실제 next-bar execution, bid/ask freshness, shared capital risk, Paper Ledger와
Formal HOLD/STOP은 W04 엔진의 책임이다. 원본 역사 엔진은 재현 검증에만 사용한다.
M04는 주문·Paper 실행·포지션 변경·실제 체결가·Forward PnL·신규 Formal 시작을 만들지 않는다.

## 9. 재검증 방법과 산출물

저장소 루트의 동일 의존성 환경에서 실행한다.

```powershell
.venv/Scripts/python.exe tools/audit_dev_m04_overnight.py
.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
```

감사는 원본 시장/Observer DB를 읽기 전용으로 열고 감사 JSON만 재생성한다.
원본 DB·JSON·로그 감사 전후 hash를 확인하며 새 LIVE/Formal 신호를 만들지 않는다.

[최종 한국어 보고서](DEV-M04-final-report-ko.md), [역사 재현](DEV-M04-reproduction.json),
[야간 감사](DEV-M04-overnight-audit.json), [기준 HEAD CI](DEV-M04-report-ci.json),
[야간 실행 CI](DEV-M04-overnight-ci.json), `artifacts/w03/lock.json`,
Observer adapter/gate/batch/store/CLI, 회귀 테스트, 두 검증 도구 및 README를 보존한다.
