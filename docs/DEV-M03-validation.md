# DEV-M03 SQLite 저장·복구 검증

작성일: 2026-10-09 (Asia/Seoul). DEV-M02 기준 commit `da8ab0e5729edf18aaccda69a91b3489670d8426`.
작업 브랜치: `dev-m03-sqlite-market-data`. Python 3.14.7 / uv / 기본 sqlite3.

**현재 판정: DEV-M03_HOLD — Windows 로컬 600초×2 실검증 결과 대기.**
구현·Linux/Windows CI·Linux 클라우드 실제 수집/재시작·백업/복원을 완료했습니다.
Windows 로컬 10분×2 검증은 사용자 실행 대기이며 라이브 WS 확정봉은 관찰되지 않았습니다.
최신 구현 commit: `05be73fb588ddd4adc6d9fc57ab0be2209be9ed3`. 기본 구현은 `e56058f`이며
후속 commit은 종료 시 64개보다 많은 확정봉 backlog를 모든 배치 commit 후 ACK하도록 보완합니다.
문서 후속 commit은 이 구현을 변경하지 않습니다.

## 기준선과 선행 호환성 수정

DEV-M02 PR #3은 OPEN이며 `dev-m01-binance-connectivity` 대상의 stacked PR입니다.
main은 `59df61d`, M01은 `5040d50`, M02는 `da8ab0e`로 확인했습니다.
main에 M01 후속 변경과 M02가 아직 없으므로 M03 PR 대상은 **dev-m02-binance-websocket**입니다.
[Draft PR #4](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/pull/4)를 이 대상으로 생성했습니다.
기존 브랜치 병합·reset·force-push·변경 삭제는 하지 않았습니다.

별도 선행 commit `64c75b0`: 65,537자 invalid-frame 테스트 입력을 유지하고 pytest parameter ID만
짧게 지정했습니다. 입력 검증을 약화시키거나 테스트를 삭제하지 않았습니다.
Linux/Windows matrix를 일반 CI에 추가했으며 Secrets나 live 옵션은 없습니다.
선행 [CI 37872643747](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37872643747):
Linux **190 passed / 7 skipped**, Windows **190 passed / 7 skipped**, Ruff/format 모두 PASS.

## 구현 파일과 Architecture

- `persistence/schema.sql`: STRICT 테이블, PK/CHECK, PRAGMA user_version 1
- `persistence/config.py`, `records.py`: 로컬 경로·범위 설정, Decimal/UTC 및 출처 모델
- `persistence/store.py`: OS writer lease, SQLite transaction, 삽입/중복/충돌, Gap·run 저널
- `persistence/repository.py`: 읽기 전용 정렬 조회, 무결성/연속성 확인, Backup API·새 경로 복원
- `persistence/writer.py`: 단일 worker thread, 한 작업만 제출, commit 후 ACK
- `persistence/recovery.py`: 서버 UTC 검증, 범위 REST, pagination/상한/간격/재시도, Gap 재검사
- `persistence/collector.py`, `persistence/cli.py`: 시작·연결·재연결·주기·종료 복구 및 저장 CLI
- `market_data/state.py`: 기존 drain 동작을 보존하면서 Peek/ACK 추가
- `binance/public.py`: 기존 candles()를 보존하고 server_time_ms / candles_range 추가
- `binance/websocket.py`: 기존 M02 결과는 유지, 종료 직전 신선도를 데이터 손실 플래그와 별도 기록
- `trading_system/cli.py`: 기존 명령 유지, db-init/collect/db-status/db-verify/db-backup/db-restore 추가
- `tests/test_persistence.py`, `test_recovery.py`, `test_collector.py`, `test_collect_integration.py`
- `tools/verify_dev_m03.py`: 기존 DB를 보존하는 로컬 600초×2·재시작·백업·복원 검증
- `.gitignore`, `.github/workflows/tests.yml`, README, 본 문서, `DEV-M03-summary.json`

파일 경로의 `persistence/`는 `src/trading_system/persistence/`를 뜻합니다.
추가 외부 의존성·ORM·서비스는 없습니다. 기존 lockfile을 유지합니다.

```text
공개 Combined WS → 기존 Parser/MarketState/HealthMonitor → 메모리 최신 가격 / 확정봉 bounded 큐
                       ↓ immutable price snapshot / Peek(closed)
단일 worker → SQLite BEGIN IMMEDIATE → 검증/PK 중복/CONFLICT → COMMIT → event loop ACK
           ↳ 공개 REST Bootstrap / Recovery → Gap 재조회·연속성 확인 → RESOLVED 또는 실패
읽기 전용 Repository → source/ingested_at 보존 조회 / 상태 / 무결성 / 공식 Backup API
```

## 스키마와 저장 정책

| 테이블 | 키와 용도 |
| --- | --- |
| price_snapshots | `(symbol,bucket_start_ms)`, Decimal price_text와 실제 event/received UTC ms |
| candles_4h | `(symbol,interval,open_time_ms)`, 확정 4h OHLCV TEXT, event_time, ingested_at, source |
| data_gaps | gap_id, inclusive 4h open-time 범위, OPEN/RECOVERING/RESOLVED/FAILED/CONFLICT |
| ingestion_runs | run UUID, 시작/종료/환경/상태, 수신·저장·중복·Gap·재연결 수와 안전한 오류 분류 |
| candle_conflicts | 기존·새 검증 OHLCV와 출처의 공개 데이터 감사 기록; 원본을 덮어쓰지 않음 |

WAL / synchronous FULL / busy_timeout 5000 / foreign_keys ON. Schema version 1 외 버전은 거절합니다.
SQLite 실패 시 ROLLBACK하며 확정 큐를 ACK하지 않습니다.
정상 종료는 수신을 멈춘 뒤 bounded 큐를 모든 배치 commit/ACK하며, 중간 배치 실패는 PERSISTENCE_FAILURE와 pending 수를 남깁니다. 느린 SQL/REST는 수신 event loop 밖에서 실행합니다.
가격은 60초 버킷에 최신 유효·신선한 값을 저장하고 동일 버킷은 event_time이 증가할 때만 갱신합니다.
쓰기 시점에 event_time/received_at이 10초 이내인 경우만 저장합니다. 가격 보존 기본 30일입니다.

진행 봉 저장은 금지합니다. 같은 PK·동일 OHLCV는 중복, 다른 값은 CONFLICT입니다.
중복에서 최초 source와 ingested_at은 바꾸지 않습니다. REST_BOOTSTRAP/REST_RECOVERY를 WS_LIVE로 승격하지 않습니다.
REST 과거 데이터는 W04 실시간 관찰을 대신하지 않습니다. 저장 전 가격 손실의 완전 복구는 보장하지 않습니다.

최근 7일 = 기본 42개 완전 확정봉/심볼입니다. 공개 GET `/api/v3/time`, `/api/v3/klines`만 추가 사용합니다.
범위의 순서·시간 경계·누락·중복·OHLCV를 검증하고 close_time < server_time인 봉만 저장합니다.
복구 기본 상한: 365일/범위, 32 REST 요청/cycle, 1000개/page, 최소 0.25초 간격.
timeout/connection/5xx만 최대 1회 재시도하며 429/418/451은 같은 cycle의 추가 요청을 중단합니다.
REST가 불완전하거나 값이 다르면 RESOLVED로 변경하지 않습니다. 미해결 구간은 INCOMPLETE입니다.

DB만 삭제되면 별도 fsync run 저널로 실행 이력을 다시 적재합니다. 저널·백업까지 삭제하면 복구할 수 없습니다.
시장 데이터 복구에는 검증된 Backup API 결과 또는 REST가 필요합니다. 운영 중 파일 단순 복사는 사용하지 않습니다.

## 현재 직접 검증

| 항목 | 확인 결과 |
| --- | --- |
| Linux 기본 pytest | **239 passed / 8 skipped** |
| 신규 결정적 테스트 | **49 passed**: SQLite 25, REST 복구 15, 수집 9 |
| DEV-M01/M02 회귀 | 기존 **190개 PASS** |
| Ruff / format | PASS |
| Windows 기본 pytest CI | **239 passed / 8 skipped**, 긴 ID 입력 보존 및 SQLite 포함 |
| GitHub 구현 CI | Linux/Windows pytest·Ruff·format PASS, [37875812326](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37875812326) |
| 클라우드 실제 첫 120초 collection | COMPLETED / exit 0, Bootstrap 126, snapshots 9, 수신 465 |
| 클라우드 재시작 두 번째 120초 collection | COMPLETED / exit 0, snapshots 추가 9, 수신 434, 신규 봉 0 |
| 클라우드 DB 누적 | 가격 18, 확정봉 126, run 2, conflict 0, 미해결 Gap 0 |
| 클라우드 무결성 / 백업 / 복원 | PASS, 모든 심볼 가격·봉과 run 수가 일치 |
| Windows 로컬 600초×2 | 사용자 실행 대기. 현재 PASS로 처리하지 않음 |
| 라이브 WS 확정봉 | 두 cloud run 모두 0개, 실제 CLOSED_CANDLE PASS 주장 없음 |

기본 pytest는 HTTP/WS live 8개를 skip합니다. 네트워크는 `--live-collect` 등 명시적 옵션에만 사용합니다.
테스트는 transaction rollback, 디스크 쓰기 실패, commit 이전 ACK 금지, cancellation 정리,
Decimal/UTC/PK/출처, 재시작·저널 복원, pagination·누락·충돌·요청 상한, 온라인 WAL backup/restore를 검사합니다.

## Windows 로컬 실검증

저장소 루트에서 README의 환경 준비 후 실행합니다.

```powershell
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python tools/verify_dev_m03.py --duration 600
```

도구는 기존 DB를 삭제/덮어쓰지 않고 새 `data/dev-m03-validation-<시각>-<UUID>/`를 사용합니다.
DB 초기화 → 7일 Bootstrap+600초 수집 → db-verify → 같은 DB로 추가600초 → 기존 기록 보존·중복·Gap 확인
→ SQLite backup → 새 경로 restore → 결과 비교를 수행합니다.
summary에는 환경·실제 commit·duration·두 run·REST/WS 출처별 봉 수·무결성·실제 x=true 관찰 여부를 기록합니다.
실제 API Key/Secret/계정 정보는 사용하거나 요약에 넣지 않습니다.
Windows hosted CI를 Windows 로컬 PC 실행과 동일하다고 기재하지 않습니다.

## Acceptance Gate

| Gate | 현재 결과와 증거 범위 |
| --- | --- |
| DB-01 | PASS — SQLite 초기화·재실행·실제 두 프로세스 재시작 |
| DB-02 | PASS — 세 심볼 실제 가격 스냅샷 총 18개, stale 값 차단 unit |
| DB-03 | PASS (UNIT + REST LIVE) — 미확정 저장 거절, REST 완전 확정 126개; WS 확정 실관찰 없음 |
| DB-04 | PASS — PK와 동일 봉 중복 처리, 실제 재시작 후 126개 유지 |
| DB-05 | PASS — Decimal TEXT 원본/복원 및 UTC ms 검증 |
| DB-06 | PASS (UNIT) — 내부/마지막 누락·불완전 페이지·범위 탐지; 실제 장애 누락 미관찰 |
| DB-07 | PASS (UNIT + BOOTSTRAP LIVE) — 복구 성공·실패 모의 검사, 실제 REST_BOOTSTRAP 126; 실제 REST_RECOVERY 신규 봉 0 |
| DB-08 | PASS (UNIT) — rollback·disk failure·conflict·취소 실패 주입, 데이터 보존 |
| DB-09 | PASS (UNIT + LIVE SHUTDOWN) — commit 후 ACK, 실패 전 ACK 금지, 실제 정상 종료 두 번 |
| DB-10 | PASS — 온라인 WAL backup 단위 검사 및 실제 Backup API 복원/데이터 비교 |
| DB-11 | PASS — Windows hosted CI 기본 pytest 239 passed / 8 skipped; 로컬 결과는 별도 대기 |
| DB-12 | PASS — DEV-M01/M02 기존 190개 회귀 테스트 |
| DB-13 | PENDING_USER_EXECUTION — Windows 로컬 600초×2 확인 전 PASS 처리하지 않음 |
| DB-14 | PASS — 구현 commit의 GitHub Linux/Windows pytest·Ruff·format |
| DB-15 | PASS — secret scan, GET 공개 수집, 주문·계정 저장 없음, local artifact Git 제외 |

## 실제 수집 기록

Linux 클라우드, 실행일 2026-10-09 (Asia/Seoul). 첫 run 시작 11:26:02,
두 번째 run 시작 11:31:04. WS 수집 구간은 각각 120초이며 Bootstrap/close/최종 복구 시간은 별도입니다.

| 항목 | 첫 실행 | 재시작 실행 |
| --- | ---: | ---: |
| 상태 | COMPLETED | COMPLETED |
| 수신 총수 | 465 | 434 |
| BTC 가격 / 4H 갱신 | 114 / 58 | 110 / 55 |
| ETH 가격 / 4H 갱신 | 95 / 45 | 96 / 47 |
| SOL 가격 / 4H 갱신 | 99 / 54 | 84 / 42 |
| 가격 저장 수 | 9 | 9 |
| 신규 확정봉 | REST_BOOTSTRAP 126 | 0 |
| 확정봉 중복 검사 | 9 | 12 |
| Gap 탐지 / 해결 | 3 / 3 (빈 DB Bootstrap) | 0 / 0 |
| Invalid / reconnect / conflict | 0 / 0 / 0 | 0 / 0 / 0 |
| 실제 x=true | 0 | 0 |

종료 직전 세 심볼 가격·캔들 모두 fresh였고 미ACK 확정 큐는 0입니다.
종료 후 connection=STOPPED / health=NOT_HEALTHY는 수집 종료 상태이며 종료 직전 신선도는 별도 기록됩니다.
SQLite integrity PASS, invalid rows 0, missing range 0, unresolved gap 0.
처음 저장된 42봉/심볼은 REST_BOOTSTRAP 출처와 최초 ingested_at을 그대로 유지했습니다.
공식 Backup API로 새로운 백업/복원 파일을 만들고 모든 심볼의 가격·봉 및 테이블 수를 비교했습니다.
이 2분×2 Linux 결과를 10분×2 Windows 로컬 Acceptance로 대체하지 않습니다.
자동 검증 도구도 별도 새 DB에서 120초×2를 실제 실행했습니다. 두 run COMPLETED,
수신 452/488, 가격 18, REST_BOOTSTRAP 126, 미해결 Gap 0, 재시작·백업/복원·secret 검사 PASS.
도구 status는 LIVE_PASS_WITH_FLAGS입니다. Linux/120초라는 환경·시간 제한이 있고, 실행 도중
본 작업의 문서/종료 backlog 수정으로 Git 상태가 달라져 source_unmodified=false였습니다.
이를 Windows 로컬 PASS 또는 변경 없는 커밋 검증으로 주장하지 않습니다.
앞선 두 직접 CLI live run은 `e56058f` 기준이며 종료 backlog 보완은 추가 단위/Windows CI로 검증했습니다.

## 보안과 남은 제한

추적 파일의 실제 환경 credential 일치 및 일반 secret 패턴 검사에서 발견 0입니다.
수집 로그에서 credential 값, signature=, X-MBX-APIKEY 헤더, account balances JSON 노출 0입니다.
M01 client/account/config/logging과 M02 models/parser/health, 기존 validation 문서,
pyproject.toml/uv.lock을 기준선과 byte 비교하여 보존을 확인했습니다.
수집은 Config()의 공개 기본값만 사용하고 .env나 프로세스 API credentials를 로딩하지 않습니다.
SQL 값은 parameter binding을 사용하며 동적인 테이블 이름은 코드 내 고정 목록입니다.
DB/WAL/SHM/백업/저널/.env가 Git 추적 대상이 아님을 확인했습니다.
이 검사 결과는 알려지지 않은 모든 형태의 credential 부재를 보증하는 외부 보안 감사는 아닙니다.

- Windows 로컬 600초×2는 외부 실제 결과를 받아야 DB-13을 판정할 수 있습니다.
- 실제 4H CLOSED_CANDLE은 미관찰이며, 확정 처리·저장·중복/ACK는 결정적 테스트로 검증했습니다.
- 실제 장기 단절/REST_RECOVERY 신규 봉은 미관찰이며 복구 실패·누락·충돌은 mock 검증입니다.
- 저장 전 가격은 완전 복구하지 않습니다. DB/저널/백업 전체 삭제와 디스크 물리 손상은 자동 복원이 불가합니다.
- SQLite는 로컬 디스크 운영을 전제로 합니다. 외부 프로세스의 임의 SQL 변경, 공유 네트워크 디스크는 지원 범위가 아닙니다.
- 손상된 실행 저널은 자동으로 삭제하지 않고 run_journal_invalid로 안전 차단합니다. 기존 데이터 보존 후 운영자 점검이 필요합니다.

**최종 제안: DEV-M03_HOLD.** 구현과 CI는 통과했으나 필수 Windows 로컬 실검증이 아직 없습니다.
Windows 결과가 통과하면 실제 WS 확정봉 미관찰 등 증거 제한을 명시하여
DEV-M03_PASS 또는 DEV-M03_PASS_WITH_FLAGS를 다시 판정합니다. 결과 없이 상태를 승격하지 않습니다.

DEV-M03는 주문·Strategy·Paper Trading·Portfolio Allocation·Master AI·Futures/Margin·PostgreSQL을
구현하지 않고 W04 Formal Forward Clock을 시작하지 않습니다.
