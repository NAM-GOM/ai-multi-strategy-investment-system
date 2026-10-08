# DEV-M02 검증 기록

검증 일자: **2026-10-08 UTC**. 관련 Issue: [#2](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/issues/2).
작업 브랜치: `dev-m02-binance-websocket`. Python **3.14.7**, uv, **websockets 17.2**.

**최종 판정 제안: DEV-M02_PASS_WITH_FLAGS.**
실제 120초 연결에서 세 심볼의 가격·4H 진행 캔들을 수신했고 오류·누락·재연결 없이 정상 종료했습니다.
확정 캔들의 라이브 수신과 장시간 연결 수명·실제 장애 후 재연결은 아직 관찰하지 않았습니다.
해당 로직의 결정적 단위 검증과 실제 수신 결과를 아래에서 구분합니다.
이 판정은 전략 수익성이나 W04 Forward Test 완료를 의미하지 않습니다.

## 브랜치 / Issue 사전 확인

개발 전에 GitHub Issue #2가 OPEN임을 확인하고 원격 M02 브랜치를 조회했습니다.
M02 시작점은 DEV-M01 최신 `5040d505036330248186725b88895c1705fcd9ef`입니다.
`main`은 `59df61dde9339e2f1cc3da4caf7099c44c2a1c8d`이며 PR #1 병합 이후의
M01 후속 네 커밋 `ef4dd4f`, `8be24ea`, `053319b`, `5040d50`이 아직 반영되지 않았습니다.
사전 조회 기준 `main...dev-m01-binance-connectivity`는 main 측 1개 / M01 측 4개입니다.

따라서 DEV-M02 PR의 대상은 우선 **`dev-m01-binance-connectivity`**로 정합니다.
main의 미반영 M01 진단·Windows 검증·Project 09 문서를 보존하는 stacked PR입니다.
M01 후속 변경이 main에 반영된 것을 확인한 후 PR 대상을 재검토해야 합니다.
force-push, reset, merge, 기존 변경 삭제는 수행하지 않았습니다.

## 파일과 Architecture

추가:

- `src/trading_system/binance/websocket.py`: 공식 호스트 allowlist, Combined 연결,
  서버 Ping에 대한 라이브러리 Pong, 수명·STALE 재연결, Backoff/Jitter, 정상 종료, 요약/보고서
- `src/trading_system/market_data/__init__.py`, `models.py`: 불변 PriceEvent / CandleEvent / ServerShutdown
- `src/trading_system/market_data/parser.py`: JSON·스트림·심볼·Decimal·UTC·OHLC·봉 시간 검증
- `src/trading_system/market_data/state.py`: 최신값, 확정 큐, 단조 watermark 중복 방지, 누락 감지
- `src/trading_system/market_data/health.py`: 연결 상태 및 현재 연결 세대의 심볼별 신선도
- `tests/test_market_data.py`, `tests/test_websocket.py`: 결정적 모델·상태·연결 테스트
- `tests/test_stream_integration.py`: `--live-stream`이 있을 때만 실제 120초 수신
- `docs/DEV-M02-validation.md`, `docs/DEV-M02-live-summary.json`: 검증 기록과 공개 데이터 증거

수정: `src/trading_system/cli.py`, `tests/conftest.py`, `pyproject.toml`, `uv.lock`, `README.md`.
기존 REST client / public / account / config / HMAC / logging 구현과 기존 테스트 파일은 보존했습니다.
`tests.yml`, `live-account.yml` 및 DEV-M01 검증 문서는 변경하지 않았습니다.

```text
Binance 공개 Combined WebSocket (1 connection / 6 streams)
  → 엄격한 parser → Decimal / UTC PriceEvent 또는 CandleEvent
  → MarketState: 최신 가격 / 진행 봉 / 최근 확정 봉 / 확정 이벤트 큐
  → HealthMonitor: 현재 연결 세대와 심볼별 수신·이벤트 나이
  → CLI: 5초마다 실제 데이터·카운터·신선도 요약, 확정 이벤트 소비
```

기본 호스트: `wss://data-stream.binance.vision`.
명시적 공식 대체 호스트: `wss://stream.binance.com`.
두 문자열만 허용하며 redirect는 따라가지 않습니다. 자동 호스트 전환은 없습니다.

구독:

```text
btcusdt@miniTicker
ethusdt@miniTicker
solusdt@miniTicker
btcusdt@kline_4h
ethusdt@kline_4h
solusdt@kline_4h
```

연결 경로는 `/stream?streams=<위 6개를 /로 연결>`입니다.
새 REST endpoint / Private endpoint / 주문 함수는 추가하지 않았습니다.

## 실행 / 테스트

```bash
uv python install 3.14.7
uv sync --frozen --group dev
uv run --frozen python -m trading_system.cli stream --duration 120
uv run --frozen python -m trading_system.cli stream --duration 120 --report-file logs/ws-check.json
uv run --frozen pytest
uv run --frozen pytest -m 'not integration'
uv run --frozen ruff check .
uv run --frozen ruff format --check .
# 네트워크를 명시적으로 사용하는 선택적 120초 테스트
uv run --frozen pytest -m integration --live-stream -s
```

`stream`에는 API Key / Secret / .env가 필요 없습니다.
보고서 파일은 새 경로를 지정하세요. 기존 파일을 덮어쓰지 않습니다.
기존 `public`, `account`, `all`과 Private opt-in 규칙을 유지합니다.

| 검증 | 결과 |
| --- | --- |
| 전체 기본 pytest | **190 passed, 7 skipped**. REST live 6개, WebSocket live 1개 미선택 |
| DEV-M01 원본 단위 테스트 7개 파일 | **102 passed** |
| DEV-M02 파서·상태·health + WebSocket 테스트 | **88 passed** |
| Ruff check / format --check | PASS |
| uv frozen sync / dependency compatibility | PASS, Python 3.14.7에서 websockets 17.2 설치·실행 |
| git diff --check | PASS |
| 실제 WebSocket CLI 120초 | **exit 0 / LIVE_PASS**, 아래 실제 수신 증거 |
| WebSocket live pytest 함수 | opt-in 경로 구현, 기본 pytest에서 skip. 이번 라이브 증거는 CLI 실행 |
| GitHub push / PR CI, 구현 commit `c971c86` | **SUCCESS**. frozen 설치 / pytest / Ruff check / format 모두 통과 |

실제 GitHub 검증 run:
[push 37782949874](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37782949874),
[PR 37782971731](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37782971731).
[초안 PR #3](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/pull/3)은 M01 브랜치 대상이며
병합하지 않았습니다. GitHub CI의 성공은 unit/lint 검증이며 위의 클라우드 live CLI 관찰과 구분합니다.

일반 push / PR CI는 live 옵션을 전달하지 않으므로 공개 WebSocket이나 Private API를 호출하지 않습니다.
모의 테스트는 실제 HTTP·WebSocket connector를 fixture에서 차단합니다.

## 실제 네트워크 검증

환경: Codex cloud / Linux x64, 기본 공식 시장 데이터 호스트.
프로그램 시작 **13:07:55.537 UTC**, 연결 성공 **13:07:56.466 UTC**,
수신 종료 약 **13:09:55.538 UTC**, 프로그램 종료 **13:10:00.552 UTC**.
요청한 수신 시간은 **120초**이며 연결 종료 handshake 대기 약 5초가 전체 uptime에 포함되어
최종 보고서 uptime은 **125.006초**입니다. 계정 credential은 사용하지 않았습니다.

공개 원본 요약: [DEV-M02-live-summary.json](DEV-M02-live-summary.json).
`logs/dev-m02-live-primary.json`, `logs/app.log`는 로컬 실행 산출물이며 Git에서 제외합니다.
가격은 관측 시점의 값이며 이후 실행에서는 달라집니다. 코드에 가격을 하드코딩하지 않았습니다.

| 심볼 | 가격 메시지 | 4H 캔들 메시지 | 마지막 가격 (USDT) | 종료 요약의 가격 나이 | 캔들 나이 | 신선도 / 봉 상태 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| BTCUSDT | 119 | 59 | 82386.00000000 | 5.529초 | 6.520초 | PASS / IN_PROGRESS |
| ETHUSDT | 119 | 58 | 2533.34000000 | 5.527초 | 6.520초 | PASS / IN_PROGRESS |
| SOLUSDT | 116 | 59 | 112.30000000 | 5.750초 | 5.750초 | PASS / IN_PROGRESS |

신선도 수치는 연결 종료 대기 후의 최종 JSON입니다. 종료 직전 신선도도 `final_healthy=true`로 확인했습니다.
STOPPED의 Health는 NOT_HEALTHY로 표시하여 종료된 연결을 운영 중으로 오인하지 않도록 합니다.

- 총 수신 **530**, 정상 파싱 **530**, 무효 메시지 **0**, 연결 오류 **0**
- 연결 성공 **1**, 정상 종료 **1**, 재연결 **0**, 이상 종료 없음, exit **0**
- 확정봉 **0**, 중복 확정 **0**, 순서 역전 **0**, 누락 **0**, 큐 overflow **0**
- 처음 6개 스트림이 모두 도착하기 전의 STALE은 약 2초 안에 CONNECTED로 회복
- HTTP 제한 / 네트워크 차단 없음. BLOCKED_ENVIRONMENT로 분류할 관측 오류 없음

**라이브 CLOSED_CANDLE은 미관찰**입니다. 13:08~13:10 UTC는 4시간봉 마감 구간이 아니었습니다.
미관찰을 실제 확정 처리 성공으로 기재하지 않습니다.

## 연결 / 확정 처리의 결정적 검증

네트워크 없이 fake connection / monotonic clock으로 다음을 확인했습니다.

- 정상 연결·종료, 장애 및 정상 서버 close 후 재연결, serverShutdown 재연결
- Exponential Backoff·Jitter·60초 상한, 정상 연결 30초 후 초기화
- 23시간 50분 사전 재연결 정책을 축소한 시간 설정으로 검증
- 동일 server Ping payload를 보내는 라이브러리 자동 Pong을 Sans-I/O protocol로 검증
- 가격 10초 / 캔들 30초 STALE, 회복, 오래된 거래소 event_time 거절, 연결 세대 변경
- 취소·종료 시 socket context / reporter task 정리, backoff 중 종료 응답
- `x=false` 확정 이벤트 없음, `x=true` 확정 이벤트 1회, 반복·재수신 중복 억제
- 3,000개 확정 이벤트를 소비해도 watermark / 최근 확정 상태는 각 3개 유지
- 최신 가격 교체, 오래된 이벤트 거절, 제한된 진행 봉, 확정 큐 overflow 실패 및 보존
- 미확정 봉이 사라지거나 확정봉 시간 간격이 누락되면 DATA_LOSS 명시
- 잘못된 JSON·심볼·Decimal·가격·OHLC·UTC 경계·closure flag 거절

실제 연결은 한 번도 끊기지 않았으므로 **실제 장애 재연결 관찰을 PASS로 주장하지 않습니다**.
24시간 실제 운용도 하지 않았습니다. 이 항목의 PASS는 결정적 단위 검증 범위입니다.

## Security / DEV-M01 보존

- WebSocket 코드에는 API Key / Secret / signature / 계정 요청이 없습니다.
  CLI stream은 .env와 계정 config를 읽지 않고 인증 헤더를 보내지 않습니다.
- 공식 호스트 두 개만 허용하고 redirect를 거절합니다. TLS 검증을 해제하지 않습니다.
- 원문 프레임·exception 본문·proxy URL/헤더·계정 잔액을 WebSocket 로그에 넣지 않습니다.
  websockets.client wire logging을 비활성화하며 httpx/httpcore 기존 정책도 유지합니다.
- 테스트용 credential을 환경과 .env에 넣어도 공개 출력·파일 로그·요약 JSON에 나오지 않음을 검증했습니다.
- 소스·테스트·설정·문서의 credential 패턴 및 현재 환경 credential과의 일치 여부를 값 출력 없이 검사합니다.
  실제 credential 의심 항목 없음. 이 검사는 패턴/현재 환경 값에 한정되며 전 역사 감사는 아닙니다.
- `.env`, 로그, 가상환경 Git 제외를 확인했습니다. 공개 검증 JSON에는 시장 데이터만 있습니다.
- Private endpoint는 기존 **GET /api/v3/account**만 유지합니다. 주문·취소·출금·이체·선물·마진
  endpoint, 권한 변경, strategy/paper execution/DB/Portfolio Allocation은 없습니다.
- 기존 DEV-M01 단위 테스트 **102개 PASS**, REST/HMAC/Account/Config/Logging 소스 변경 없음.
  Windows Private 실검증 기록 및 GitHub-hosted HTTP 451 기록은 이전 문서에 그대로 유지했습니다.
  이번 공개 WebSocket 성공이 Private API의 지역 제한 해결을 의미하지 않습니다.

## Acceptance Gate

| ID | 상태 | 근거와 범위 |
| --- | --- | --- |
| WS-01 | LIVE_PASS | BTC / ETH / SOL 실제 가격 수신 |
| WS-02 | LIVE_PASS + UNIT_PASS | 세 심볼 실제 4H 진행 캔들 파싱, Decimal / UTC 검증 |
| WS-03 | LIVE_PASS + UNIT_PASS | 라이브 IN_PROGRESS, 미확정은 확정 큐에 넣지 않음 |
| WS-04 | UNIT_PASS / LIVE_NOT_OBSERVED | x=true 1회 전달·중복 억제 PASS. 라이브 x=true 0개 |
| WS-05 | UNIT_PASS / LIVE_NOT_OBSERVED | 재연결·Backoff·Jitter PASS. 실제 장애 0회 |
| WS-06 | UNIT_PASS | 심볼별 임계값·회복·연결 세대 검증. 초기 STALE 회복 라이브 관찰 |
| WS-07 | UNIT_PASS | 제한된 최신 상태·watermark·확정 큐, overflow 명시 실패 |
| WS-08 | PASS | DEV-M01 원본 단위 테스트 102개 통과 |
| WS-09 | PASS | pytest 190 passed / 7 skipped, Ruff / format PASS |
| WS-10 | PASS | credential 미사용, 주문·추가 Private API 없음 |
| WS-11 | PASS | 라이브 관찰·모의 검증·미관찰 항목 별도 명시 |

판정 근거:

- **DEV-M02_PASS_WITH_FLAGS (제안)**: 핵심 라이브 수신과 전체 단위/회귀/보안 검증은 성공.
  실제 확정봉, 실제 장애 후 재연결, 장기 운용 수명 검증은 남아 있음.
- DEV-M02_PASS: 현재는 제안하지 않음. 위 라이브 관찰 범위를 확대하고 운영 기준을 확인한 뒤 검토.
- DEV-M02_HOLD: 이번 환경은 차단되지 않았고 핵심 수신이 성공하여 제안하지 않음.
- DEV-M02_REJECTED: 보안/회귀/데이터 손실 실패가 없어 제안하지 않음.

## 남은 위험과 다음 단계

1. 허용된 환경에서 4h 마감 시각을 포함한 관찰로 실제 CLOSED_CANDLE을 확인하세요.
   실제 장애 후 재연결과 24시간 운용·사전 rotation도 별도 운영 검증이 필요합니다.
2. 데이터 누락은 표시하지만 복구하지 않습니다. REST backfill·영속 exactly-once·재시작 후 dedup은
   DEV-M03 이후에 설계합니다. 현재 watermark는 고정 4h·순방향 세션 처리에 한정합니다.
3. 가격 10초 / 캔들 30초는 초기 기준입니다. 실제 부하·네트워크·시계 상태로 운영 기준을 확정하세요.
4. 메모리 소비자가 확정 큐를 비우지 않으면 128개에서 실패합니다. 소비자는 전달 성공을 확인하며
   주기적으로 drain해야 합니다. 프로그램 재시작은 이전 미전달 데이터를 복구하지 않습니다.
5. DEV-M01 후속 커밋의 main 반영 상태를 확인한 뒤 stacked PR의 대상을 재검토하세요.
   임의 병합이나 브랜치 강제 덮어쓰기는 하지 않습니다.
6. W04 Forward Clock은 시작하지 않았습니다. Strategy / Signal / Paper Execution은 별도 Cycle입니다.
