# DEV-M03 Final Gap Closure & Live Persistence Validation

검증 환경: Windows 11 Home 10.0.26200 x64 / PowerShell 7.6.5 / Python 3.14.7 / uv 0.12.24.
기준 브랜치: `dev-m03-sqlite-market-data`.
기준 전체 Commit: `04bad4484ed491341eafc2d0484dde7bf0da4754`.

수정은 별도 형제 checkout `DEV-M03-final-validation-20261009`에만 적용했다. 이전 Windows 검증 checkout, DB, 백업, 복원 DB, 실행 저널과 보고서는 보존했다. 의존성 및 `uv.lock`은 변경하지 않았다. commit / push / merge는 수행하지 않았다.

최종 제안: **DEV-M03 기능 검증 PASS로 승격 권고**. 실제 17:00 KST 마감 수신, WS_LIVE 저장, 별도 프로세스 재시작 보존, 공개 REST 복구 및 사후 검사가 통과했다. 과거 12:47의 정확한 이벤트별 원인은 당시 진단 로그 부족으로 확정할 수 없다. 네트워크 중복 마감 수신은 NOT_TESTED이며 실제 수신 payload 재처리 중복 방지는 PASS다. 이 문서는 로컬 제안이며 GitHub 상태나 코드를 게시하지 않았다.

## 작업 1 — 12:47 KST BTC 가격 스냅샷

### 실제 과거 증거

2026-10-09 12:47 KST BTCUSDT 버킷은 원본 DB에 없다. ETHUSDT / SOLUSDT의 해당 버킷은 존재한다. 원본 DB를 읽기 전용으로 조사했으며 빈 값을 생성하거나 원본에 행을 넣지 않았다.

- 12:47:00~12:47:55의 WS 누적 메시지는 1,436 → 1,650으로 증가했다. 매 보고 시 연결은 CONNECTED였고 invalid 메시지는 0이었다. 이는 전체 스트림의 수신 증거이며 당시 BTC 개별 payload를 완전히 재구성하는 증거는 아니다.
- 12:47:13~14의 서버 시간 및 BTC/ETH/SOL 공개 REST 요청은 정상 완료됐다. 해당 시간대에 Writer 실패, rollback, 수집 프로세스 종료가 기록되지 않았다.
- 수집 실행 경계는 12:41:04.125~12:51:11.762 KST다. 누락 분은 실행의 중간이며 재시작 경계가 아니다.
- 인접한 실제 행은 Binance event_time이 로컬 received_at보다 약 583~584ms 앞선다. 예: BTC 12:46 버킷의 event_time은 12:46:03.014, received_at은 12:46:02.431 KST다.
- 후속 공개 서버 시간 조회에서 서버가 로컬 RTT 중간 시각보다 661.5ms / 662.5ms 앞섰다. 첫 연결을 포함한 샘플은 720.5ms, RTT 153ms였다. 이 수치는 후속 환경 측정이며 과거 12:47 시계를 직접 재측정한 값으로 취급하지 않는다.

### 재현된 원인 메커니즘과 최소 수정

메모리 HealthMonitor는 미래 이벤트의 음수 age를 0으로 처리한다. 반면 실제 SQLite 저장 경계는 `0 <= write_time - event_time <= 10초`를 요구한다. 서버가 약 0.66초 빠르고 miniTicker가 1초마다 도착하면, 고정 1초 polling은 매번 미래 이벤트를 선택해 저장을 거절하는 위상에 고정될 수 있다. freshness는 유지돼도 가격 버킷은 비게 된다.

Git HEAD에서 읽은 수정 전 Collector/AsyncWriter와 수정 후 구현을 서로 다른 합성 SQLite fixture로 비교했다. 660ms 시계 차이, 1초 수신 주기, 120초 실험에서:

| 구현 | BTC 스냅샷 | ETH 스냅샷 | SOL 스냅샷 |
|---|---:|---:|---:|
| 수정 전 | 0 | 2 | 2 |
| 수정 후 | 2 | 2 | 2 |

이 표는 **DETERMINISTIC SYNTHETIC LAB REPRODUCTION**이다. 실제 네트워크 관찰로 표시하지 않고 실제 수집 DB에 합성 값을 넣지 않았다. 증거: `data/final-validation-20261009/phase-lock-reproduction.json`.

추가로 기존 구현은 전체 가격 쓰기 수가 제출 심볼 수와 같을 때만 모든 메모리 버킷을 ACK했다. 부분 성공 시 이미 저장한 심볼도 ACK되지 않았다. 또한 Collector가 제출 전 결정한 버킷과 Writer의 실제 write_clock 버킷이 다르면 잘못된 버킷을 ACK할 수 있었다. 두 회귀 테스트는 수정 전 실제 SQLite에서 실패했다.

변경:

1. Writer가 commit 이후 DB에서 확인한 심볼별 실제 버킷 receipt를 반환하고 Collector는 그 receipt만 ACK한다. rollback / 취소 시 ACK하지 않는 기존 규칙은 유지한다.
2. 미래 가격 이벤트는 신선도 기준을 완화하지 않고, 이벤트가 저장 가능해지는 시각에 맞춰 1초보다 짧게 재시도한다. 가격·이벤트 시각·수신 시각을 조작하지 않는다.
3. 실제 close가 로컬 시계보다 최대 1초 먼저 도착한 경우 확정 큐를 ACK하지 않고 잠시 유지한다. 더 먼 미래 봉은 기존대로 실패한다. 무제한 미래 봉 대기를 추가하지 않는다.
4. 심볼, 이벤트/수신/쓰기 시각, 실제 버킷, commit/future_event 결과를 공개 진단 로그로 기록한다. 가격 값, credentials 또는 Private API 응답을 추가하지 않는다.

**정확한 과거 원인의 증거 한계:** 시계 차이와 해당 누락을 만드는 코드 경로는 재현했다. 하지만 당시 심볼별 제출 이벤트와 실제 commit receipt가 없어 12:47의 모든 BTC 이벤트를 복원할 수 없다. 해당 사건의 단일 원인을 완전히 입증했다고 표시하지 않는다. 별도의 시계 조정 버킷 문제를 과거 사건의 확인된 원인으로 단정하지 않는다.

추가 회귀 테스트 5건: 미래 가격 재시도/부분 성공 ACK, 실제 커밋 버킷 ACK, 가격 commit 실패 후 재시도, 짧은 미래 close 대기, 먼 미래 close 실패. 기존 테스트는 삭제하거나 약화하지 않았다.

수정 후 실제 600초 공개 수집은 **COMPLETED / LIVE_PASS**로 완료됐다. WS uptime 605.018초, 심볼별 가격 행 {"BTCUSDT": 11, "ETHUSDT": 11, "SOLUSDT": 11}이다. 관찰된 버킷 대비 미저장 버킷은 {"BTCUSDT": [], "ETHUSDT": [], "SOLUSDT": []}이다. 실제 미래 이벤트 거절 후 동일 이벤트가 원본 시각 그대로 commit된 진단 쌍은 14건이다. SQLite integrity는 ['ok']이다. 상세 증거: `data/final-validation-20261009/price-sampling-evidence.json`, `price-sampling-run.json`, `price-sampling.stderr.log`. 이 수집의 실제 WS 확정봉은 0개이며 작업 2를 대신하지 않는다.

## 작업 2 — 실제 4H 마감과 WS_LIVE 저장

대상 마감: **2026-10-09 17:00 KST / 08:00 UTC**. 대상 봉: 04:00~07:59:59.999 UTC.
새 DB: `data/final-live-20261009T170000/live.sqlite`.
실제 수집 시작: 16:50:15 KST. 첫 수집 900초 후 같은 DB에서 **별도 새 Python 프로세스**로 120초 재시작 수집을 완료했다. 기본 Bootstrap 및 60초 REST 연속성 검사를 사용했다.

실제 공개 WS에서 받은 `k.x=true` payload만 `actual-closed-ws.jsonl`에 기록한다. 수신하지 않은 봉을 WS_LIVE로 만들지 않는다. REST가 먼저 저장했다면 출처를 WS_LIVE로 승격하지 않고 NOT_TESTED로 표시한다. 동일 payload 재저장은 CAPTURED LIVE EVENT REPLAY로 구분하며 실제 네트워크 중복 수신으로 주장하지 않는다.

검증 프로세스 실행 동안만 절전 방지를 요청하고 종료하면 해제한다. 전원 계획·Windows 보안 정책을 영구 변경하지 않는다. PC와 앱이 종료되거나 네트워크가 제한되면 성공으로 대체하지 않는다.

<!-- LIVE_RESULTS_START -->
상태: **PASS**. 실제 마감 2026-10-09 17:00 KST / 08:00 UTC. 실제 k.x=true 3건(BTCUSDT/ETHUSDT/SOLUSDT), invalid=0, reconnect=0. 원본 공개 payload는 `data/final-live-20261009T170000/actual-closed-ws.jsonl`에 보존했다.

각 payload의 t/T/E/OHLCV를 DB와 독립 대조했다. 모두 source=WS_LIVE이며 최초 ingested_at 및 event_time이 새 프로세스 재시작 후에도 동일하다. 로컬 received_at은 Binance E보다 약 0.7초 앞서지만 시각을 조작하지 않고 실제 저장 가능 시각까지 기다렸다.

| 실행 | 실제 KST 구간 | DB 실행 시간 | WS uptime | 상태 |
|---|---|---:|---:|---|
| 첫 수집 | 16:50:15.015~17:05:21.948 | 906.933초 | 905.014초 | COMPLETED / LIVE_PASS |
| 새 프로세스 재시작 | 17:05:22.574~17:07:29.591 | 127.017초 | 125.018초 | COMPLETED / LIVE_PASS |

별도 프로세스 PID: 28380 → 10340. 두 COMPLETED 실행 이력 보존.

| 심볼 | 첫 가격/캔들 메시지 | 재시작 가격/캔들 메시지 | 최종 가격 행 | WS_LIVE 봉 |
|---|---:|---:|---:|---:|
| BTCUSDT | 898 / 449 | 120 / 60 | 18 | 1 |
| ETHUSDT | 836 / 424 | 111 / 55 | 18 | 1 |
| SOLUSDT | 765 / 404 | 102 / 50 | 18 | 1 |

최종 가격 스냅샷은 54개. 쓰기 카운터 48+9=57은 두 실행이 공유하는 분 버킷 갱신을 포함하므로 고유 행 수와 다르다. 가격 중복 행 0, 확정봉 중복 행 0. 최종 확정봉은 REST_BOOTSTRAP=126, REST_RECOVERY=0, WS_LIVE=3. 심볼별 43개 봉이 4H 간격으로 연속한다.

실제 수신 payload 재처리(CAPTURED LIVE EVENT REPLAY): duplicate_candles=3, candles_written=0, conflicts=0, 최초 행 전체 동일. 네트워크 duplicate_closures=0으로 실제 중복 네트워크 수신은 관찰하지 않았다. REST 기존 봉 중복 처리는 첫 실행 48건/재시작 15건이며 Conflict=0; WS_LIVE 출처를 REST로 변경하지 않았다. 미해결 Gap=0, invalid_rows=0, missing_ranges=[], COMPLETE, Integrity PASS.

증거: `data/final-live-20261009T170000/result.json`, `run-1.json`, `run-2.json`, `data/final-validation-20261009/after-live-audit.json`.

승격 제안: **기능 검증 PASS 권고**. 과거 12:47의 이벤트별 원인을 완전히 입증한 것으로 해석하지 않는다.
<!-- LIVE_RESULTS_END -->

## 작업 3 — 실제 공개 REST 누락봉 복구

결과: **PASS**. 새 fixture `data/final-recovery-20261009/recovery-fixture.sqlite`에 공개 REST로 7일 Bootstrap한 뒤, BTCUSDT의 2026-10-08 16:00 UTC 확정봉 **한 행만 해당 fixture에서 제거**했다. 제거 후 행 수 0을 확인했다. 다른 실제 수집 DB에는 DELETE를 실행하지 않았다.

실제 Backfill 실행에서 DB 상태를 각 commit 후 관찰했다:

`OPEN → RECOVERING → RESOLVED`, resolution_source=`REST_RECOVERY`.

| OHLCV | 독립 공개 REST 응답 | 복구 저장 값 |
|---|---|---|
| Open | 81037.99000000 | 81037.99000000 |
| High | 81839.73000000 | 81839.73000000 |
| Low | 80393.56000000 | 80393.56000000 |
| Close | 81775.52000000 | 81775.52000000 |
| Volume | 5208.93362000 | 5208.93362000 |

새 봉 1개 저장, 기존 봉 중복 3건 처리, conflicts 0, 새 Gap 1개 검출/1개 해결, 공개 REST 요청 5회. event_time은 NULL이며 source는 REST_RECOVERY다. 다른 fixture 행의 전체 SHA-256이 일치한다. 원본 DB·백업·복원·로그·저널 24개 파일의 해시도 일치했다.

`sqlite_integrity=PASS`, invalid_rows=0, missing_ranges=[], unresolved_gaps=0, data_status=COMPLETE.
실제 상태 전이·OHLCV·원본 파일 해시는 `data/final-recovery-20261009/result.json`에 기록했다.

## 검사 및 보안

- `uv run --frozen pytest`: **244 passed / 0 failed / 8 skipped** (252 collected, 실제 마감 후 재실행 3.26s).
- `uv run --frozen ruff check .`: **PASS**.
- `uv run --frozen ruff format --check .`: **PASS**, 42 files already formatted.
- 공개 REST / 공개 WS만 사용한다. Config() 기본 공개 호스트를 사용하며 .env 또는 process credentials를 로드하지 않는다. 실제 Account / 주문 / 취소 / 출금 / 이체 / 전략 API는 호출하지 않는다.
- source 변경은 새 checkout의 Collector/Writer, 회귀 테스트, 공개 검증 도구와 이 문서에 한정했다. 기존 checkout과 원본 검증 데이터는 보존했다.
- 최종 민감정보 검사: 완료된 로그·공개 payload·보고서·공유 요약 40개 파일에서 알려진 process credential 값 및 Private 요청/응답 노출 표식 0건, PASS. .env는 읽지 않았다. 모든 임의 형식의 Secret을 탐지했다는 보장은 아니며 검사 범위는 secret-audit-after-live.json에 기록했다.
## 최종 사후 확인

실제 마감 후 관련 SQLite 6개(새 live/복구 fixture/가격 수집, 원본/백업/복원)의 Integrity와 Foreign Key 검사를 읽기 전용으로 다시 수행했다: 모두 PASS, 위반 0. 원본 보호 파일 24개 해시와 기존 checkout 변경 없음도 재확인했다.

복구 fixture는 14:53 KST에 종료되어 17:00에 새로 마감한 봉을 포함하지 않는다. 최초 사후 검사는 현재 시각 기준 COMPLETE를 기대해 assertion이 실패했다. 안전 분류는 `STALE_FIXED_FIXTURE_AS_OF_CURRENT_TIME`이다. 실제 복구 완료 시각(2026-10-09 05:53:21.565 UTC)을 기준으로 재확인하면 COMPLETE/미해결 Gap 0이며, 현재 시각 기준의 새 마감 누락 3개도 audit JSON에 그대로 기록했다. fixture에 추가 행을 넣거나 원본을 변경해 결과를 맞추지 않았다. 새 마감의 실제 연속성은 별도 live DB에서 확인했다.

공유 요약: `data/final-validation-20261009/DEV-M03-local-summary.json`. 기존 Windows 요약 파일은 덮어쓰지 않았다.
