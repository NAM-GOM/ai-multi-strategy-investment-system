# DEV-M04 최종 검증 보고서

재작성일: 2026-10-10 KST. 최종 기술 판정: **DEV-M04_PASS_WITH_FLAGS**.

이번 재작성에서 기존 01시·05시 원본 DB를 다시 읽기 전용으로 감사했다. 18개 실시간
지표·입력 해시·결정 해시 일치와 재시작 추가 0개를 재확인했다. 새 마감을 추가 관찰한
것은 아니다. 검증 근거와 미관찰 항목을 정리한 [재검증 보고서](DEV-M04-validation.md)를
함께 갱신하고, 기존 최종 커밋의 실제 두 OS CI 로그를 보고서에 추가했다.

01:00·05:00 KST 실제 4H 마감에서 BTC/ETH/SOL 확정봉과 9개 전략 결정을 각각
관찰·영구 저장했다. 별도 프로세스 재시작 후 추가 결정은 모두 0개다. 원본 시장
SQLite를 읽기 전용으로 다시 계산한 지표·입력 해시·결정 해시도 모두 정확히 일치했다.

이 판정은 W04_PREFLIGHT_PASS, 전략 APPROVED 또는 Formal Paper 시작 승인이 아니다.
M04는 주문·Paper Execution·포지션 변경·체결가 생성·Forward PnL 계산을 수행하지 않았다.

## 1. 기준 커밋과 변경 범위

저장소: `NAM-GOM/ai-multi-strategy-investment-system`.
브랜치: `dev-m04-strategy-observer`.

| 구분 | 전체 Commit SHA |
|---|---|
| 제출된 M03 수정 전 기준 | 04bad4484ed491341eafc2d0484dde7bf0da4754 |
| M03 최종 검토·회귀 후 동결 및 원격 반영 | 1b1bf582f34a526d9204a084dc4573c79efa124e |
| M04 최초 구현 | 2ac688b8e685794eb488860de297f37b2992bf71 |
| 최종 실제 관찰·두 OS CI 검증 대상 | 9985e2c999185d4793612bc0edb4552f57c62d12 |
| 이번 재검증 기준 HEAD·감사 도구 포함 CI | 11bfffbdfb529f3da8ac11ebd49fb1ed81c23725 |

M03의 로컬 미커밋 수정과 실제 17:00 KST 증거를 검토했다. 추가 검토에서 동일 버킷의
기존 가격 receipt를 확인해도 신규 쓰기 수가 0이면 재시작 실행을 실패로 표시하는
문제를 수정했다. M03 회귀 245 passed / 8 skipped 및 Ruff/format 후 원격 M03 브랜치를
정상 fast-forward로 갱신하고, 그 SHA에서 별도 M04 checkout을 생성했다.

main과 M01/M02/M03 이력, 기존 DB 및 Frozen 원본은 보존했다. 이번 보고서 재작성은
구현 소스와 관찰 데이터를 변경하지 않으며 기준 HEAD의 후속 M04 커밋으로 게시한다.
보고서 자체의 커밋 식별자는
`git log -1 --format=%H -- docs/DEV-M04-final-report-ko.md`와 최종 전달 메시지에서 확인한다.

## 2. Frozen Source Audit

원본 ZIP, 코드, 설정, 과거 데이터와 W03 원장/자본 곡선을 확보했다. 임의의 전략을
새로 구현하지 않았다. Frozen 모듈의 바이트와 초기화 래퍼를 그대로 재사용한다.

| 항목 | SHA-256 |
|---|---|
| 원본 W03 패키지 | 2ad1bca4fcd1a0694bd39bafff3d3f6b93beccc3f7237b0376a73e030f9ad155 |
| 전략 코드 | 0850fcc32356a4275e0795cece08a6f6d701220b941ce94e2b95dd1ce802a965 |
| W03 설정 | 6a7ce60ed2199cc432cbd98733e3b72f4d926e7120cbc5e69d224b6d9fd0863b |
| BTC 데이터 | f4ddf0ec4354fe66f2635887a809e433962877b9b090a728a02d3721a0183059 |
| ETH 데이터 | f0cda00c5f062f947c0175c911b8afb521a62d38d04d3f45c220a56d3e7002bb |
| SOL 데이터 | fe428dcdce137be444ab38f2c497651455173b4bbcbc2a5cdc75e386e1265187 |
| 통합 전략 Manifest | 8508a1bd15d68b04fe0428c298330961859af88a9a26d565d23fcdf1d93bd38c |

전략 버전은 원본 `0.1`이며 Manifest 표기는 `v0.1`이다. EMA 50/200 교차,
Donchian 진입55/청산20과 current-bar 제외, Momentum180의 0 교차, ATR20 EWM
`adjust=False` 및 원본 첫 201/56/182행 신호 차단을 보존한다. 공통 역사 초기화는
2020-08-11 04:00 UTC에서 시작한다. 7일·42봉만으로 EMA 초기화를 대신하지 않았다.

손절 3×signal ATR, Risk .005, Asset Cap .333, Fee 10bps/side, Model Slippage 5bps/side,
long-only/no leverage/no pyramiding과 next-bar execution은 원본 엔진의 역사 재현에서
확인했다. 실시간 Observer는 원본 boolean 후보만 기록하며 실행 엔진을 호출하지 않는다.

## 3. W03 재현 결과

원본 공유 포트폴리오 엔진의 세 전략 원장 및 자본 곡선은 Frozen CSV와 정확히 일치했다.
ZIP의 CR/LF 전달 형식만 정규화하고 숫자 문자열·시각·순서·ATR·손절·포지션 계산은
그대로 비교했다. 새 허용 오차나 결과에 맞춘 전략 수정은 없다.

| 전략 | 심볼 | Entry boolean 수 | Exit boolean 수 | 원장 거래 수(terminal 포함) |
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

각 조합은 초기화/평가 13,460행이다. Boolean 수는 실제 주문 수가 아니다. 지표·신호의
prefix 재계산 및 미래 가격 변경 시험도 통과했다. 전체 결과:
[재현 자료](DEV-M04-reproduction.json).

**증거 flag:** 독립적인 W03 전체 봉 지표/boolean 덤프는 제공되지 않았다. 지표 확인은
바이트 동일 원본, prefix 일치, 원본 진입 ATR/손절 원장 및 실제 M04 snapshot 재계산으로
수행했다. 기존 W04 117행 inventory를 새 W03 독립 검증으로 표시하지 않았다.

## 4. 01시·05시 실제 Windows 관찰

| 실제 마감(KST) | 실제 마감(UTC) | 실제 WS 확정봉 | LIVE 결정 | NO_ACTION | 후보 | 재시작 추가 |
|---|---|---:|---:|---:|---|---:|
| 10/10 01:00 | 10/09 16:00 | BTC/ETH/SOL 3개 | 9 | 8 | T3 ETH EXIT_CANDIDATE | 0 |
| 10/10 05:00 | 10/09 20:00 | BTC/ETH/SOL 3개 | 9 | 8 | T3 ETH ENTRY_CANDIDATE | 0 |

| 검증 | 01시 구간 | 05시 구간 |
|---|---|---|
| 실제 Collector 실행(KST) | 00:50:00.631~01:07:08.885 | 04:50:01.291~05:07:08.858 |
| 실제 WS uptime | 1025.017s | 1025.019s |
| 실제 수신 메시지 | 4419 | 4195 |
| 영구 시장 데이터 | REST_BOOTSTRAP 162 + WS_LIVE 3 | REST_BOOTSTRAP 162 + WS_LIVE 3 |
| 가격 snapshot 쓰기 수 | 54 | 48 |
| Collector/Observer 종료 | COMPLETED / 정상 종료 | COMPLETED / 정상 종료 |
| 미해결 Gap / invalid / conflict | 0 / 0 / 0 | 0 / 0 / 0 |
| Observer → restart PID | 1856 → 18212 | 27928 → 28676 |
| DB 결정 총수 | prelaunch 9 + live 9 = 18 | prelaunch 9 + live 9 = 18 |
| 재시작 결과 | ALREADY_COMMITTED | ALREADY_COMMITTED |
| 독립 지표/입력/결정 hash 대조 | EXACT MATCH | EXACT MATCH |

두 라이브 배치의 모든 결정은 `LIVE_OBSERVATION`, 원본 봉 출처는 `WS_LIVE`다.
9개 결과가 같은 batch에 저장됐고 최신 checkpoint 9개가 해당 봉을 가리킨다.
입력 원본 파일·DB·로그는 독립 감사 전후 해시가 동일했다. SQLite integrity/foreign key,
데이터 연속성과 source/config는 통과했다. 종료된 01시 fixture의 완전성은 실제 완료 시각을
기준으로 판단했으며, 나중 05시 봉이 없다는 이유로 과거 완료 결과를 왜곡하지 않았다.

실제 T3 ETH 지표 예시:

| 마감(KST) | ATR20 | Momentum180 | Entry | Exit | 평가 지연 |
|---|---:|---:|---|---|---:|
| 01:00 | 34.19768487345464 | -0.0004939243291864903 | false | true | 1.080s |
| 05:00 | 33.727800629781896 | 0.004887466588791689 | true | false | 1.039s |

EXIT/ENTRY는 원본 조건 후보다. 실제 ETH 보유/청산/진입 또는 체결을 의미하지 않는다.
전체 18개 실제 indicator snapshot과 입력 해시:
[독립 야간 감사 결과](DEV-M04-overnight-audit.json).

두 구간은 **별도 DB에서 수행한 별도 관찰**이다. 01:07~04:50 연속 WS 관찰이나 무중단
Forward 성과를 주장하지 않는다. 각 실행은 지표 복구용 과거 데이터와 실제 마감 관찰을
분리했고 REST 데이터를 Formal 또는 LIVE로 승격하지 않았다.

## 5. 테스트·회귀·CI

Windows 로컬 최종 전체 회귀: **283 passed / 8 skipped**, 41.50s.
M01/M02/M03 기존 테스트를 포함하며 생략된 8개는 opt-in 네트워크/계정 검사다.

실제 관찰 대상 최종 Commit `9985e2c999185d4793612bc0edb4552f57c62d12`의
[GitHub CI 37936170401](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37936170401):

| 환경 | Pytest | Ruff | Format |
|---|---|---|---|
| Windows / Python 3.14.7 | 283 passed / 8 skipped, 35.00s | PASS | PASS |
| Linux / Python 3.14.7 | 283 passed / 8 skipped, 30.44s | PASS | PASS |

두 job 로그와 step success를 실제 조회했다. 최초 구현 Commit의 두 OS CI도 동일하게
통과했다. 새 독립 감사 도구는 원본 DB 두 개와 18개 지표/해시를 실제 대조해 PASS를
확인했고 Ruff/format도 통과했다. 상세 [야간 CI 증거](DEV-M04-overnight-ci.json).

감사 도구와 기존 최종 보고서가 포함된 Commit `11bfffbdfb529f3da8ac11ebd49fb1ed81c23725`의
[CI 37985954969](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37985954969)도
완료 결과와 원본 job 로그를 다시 확인했다.

| 환경 | Pytest | Ruff | Format |
|---|---|---|---|
| Windows | 283 passed / 8 skipped, 53.38s | PASS | PASS, 53 files |
| Linux | 283 passed / 8 skipped, 34.59s | PASS | PASS, 53 files |

상세 [기준 HEAD CI 증거](DEV-M04-report-ci.json). 이번 재작성 중에는 원본 자료의
읽기 전용 독립 감사와 Ruff/format을 재실행했다. 전체 pytest를 이번에 새로 실행한
것으로 표시하지 않는다. 위 pytest 수치는 해당 SHA의 실제 CI 결과다.

결정적 테스트 범위: Frozen 소스/설정/런타임 변경, warmup 차단, Momentum180,
Donchian current-bar 제외, 확정봉·미래 정보, 3심볼 barrier, REST/LIVE 구분,
중복 충돌, 실제 SQLite transaction rollback, checkpoint 훼손, persistent STOP,
실제 subprocess 강제 종료 및 재시작, read-only DB와 credential 경로 미사용.

실제 smoke 600초는 9개 prelaunch 결정을 저장했지만 실제 마감 0개였다.
이를 OBS-12로 세지 않았고 이번 두 실제 마감으로 OBS-12를 검증했다.

## 6. Acceptance Gate

| Gate | 최종 결과와 근거 |
|---|---|
| OBS-01 | PASS — 원본 source/config와 runtime parameter hash 확인 |
| OBS-02 | PASS_WITH_EVIDENCE_FLAG — 9개 조합, 원본 원장/자본 곡선 정확 일치; 독립 전체 지표 덤프 부재 |
| OBS-03 | PASS — W03 초기화 + 두 시장 DB의 연속된 확정 과거 이력 |
| OBS-04 | PASS — 확정봉만 평가, 미래/미확정 차단 및 실제 WS close |
| OBS-05 | PASS — WS_LIVE/REST/W03 출처와 입력 hash 보존 |
| OBS-06 | PASS — 3심볼 검증 후 9개 공유 batch commit |
| OBS-07 | PASS — 별도 Observer SQLite에 NO_ACTION 포함 영구 저장 |
| OBS-08 | PASS — 두 실제 별도 프로세스 재시작 후 추가 결정 0 |
| OBS-09 | PASS — 오류/충돌/rollback/recovery에서 fail-closed 결정적 검사 |
| OBS-10 | PASS — Windows/Linux pytest, Ruff, format |
| OBS-11 | PASS — 기존 M01/M02/M03 회귀 포함 |
| OBS-12 | PASS — 01시·05시 실제 closed-bar 관찰과 독립 재계산 |
| OBS-13 | PASS — 주문·Paper Execution·포지션·실제 체결 기록 없음 |
| OBS-14 | PASS — W04 Formal 시작/Clock 상태를 접근·변경하지 않음 |

## 7. 미관찰 항목과 상태 보존

실제 네트워크의 duplicate closure는 두 실행에서 0개였으므로 **NOT_OBSERVED**다.
중복 방지는 결정적 테스트, 과거 captured-real-event replay 및 실제 프로세스 재시작으로
검증했다. 네트워크 중복 수신을 검증했다고 승격하지 않는다.

M03의 과거 BTC 12:47 개별 이벤트 원인은 기존 증거 한계 때문에 여전히 완전 입증되지
않았다. W03 독립 전체 봉 지표 덤프 부재와 두 관찰 구간 사이 coverage 공백은 그대로 남긴다.
이 때문에 최종 기술 분류를 PASS_WITH_FLAGS로 기록했다.

T1은 기존 W03_PASS_WITH_FLAGS, T2/T3는 W03_HOLD를 유지한다. T1 Continuity Shadow와
Formal Paper 상태는 혼합하지 않았다. Gate F의 실제 bid/ask freshness, 공유 자본 위험,
Paper Ledger 및 W04 Formal HOLD/STOP은 기존 W04 엔진의 독립 책임으로 남아 있다.
M04는 Gate F나 W04 Preflight를 새로 검증한 것으로 표시하지 않는다.

## 8. 산출물

[기술 검증 문서](DEV-M04-validation.md), [원본 재현 결과](DEV-M04-reproduction.json),
[실제 야간 감사/지표](DEV-M04-overnight-audit.json), [두 OS CI](DEV-M04-overnight-ci.json),
[기준 HEAD 최종 CI](DEV-M04-report-ci.json),
`artifacts/w03/lock.json`, Observer adapter/gate/batch/store/CLI, 회귀 테스트,
`tools/verify_dev_m04_live.py`, `tools/audit_dev_m04_overnight.py`, README.

원본 실행 DB·로그·저널·supervisor 보고서는 각각
`data/m04-live-20261010T010000/`, `data/m04-live-20261010T050000/`에 보존한다.
감사 재실행은 저장소에서 `python tools/audit_dev_m04_overnight.py`로 수행한다.
