# AI Multi-Strategy Investment System — DEV-M03

**현재 버전은 주문 기능이 없는 Read-only Binance Spot 시장 데이터 수집 시스템입니다.**
DEV-M01의 REST 조회·계정 인증을 유지하며 DEV-M02에서 공개 WebSocket 수집을 추가합니다.
DEV-M03에서는 SQLite 저장·재시작·확정봉 누락 복구를 지원합니다.
GitHub 저장소의 소스, `.python-version`, `pyproject.toml`, `uv.lock`이 구현과 환경의 기준입니다.
Python **3.14.7**을 사용하며 프로젝트의 지원 버전은 **3.14.x**입니다.

구현 범위:

- BTCUSDT / ETHUSDT / SOLUSDT 현재 가격
- BTCUSDT 최근 4시간봉 10개: UTC ISO-8601 시간과 OHLCV. 마지막 봉은 미완성일 수 있습니다.
- BTCUSDT 상위 10개 Bid / Ask, best bid / ask, spread, spread percent, REST latency
- HMAC SHA-256 인증과 USDT / BTC / ETH / SOL의 free / locked / total 잔액
- 키가 없거나 하나만 설정된 경우 계정 검증을 안전하게 건너뜀
- Console / File 로그, 모의 HTTP 테스트, 선택적 실제 연결 테스트
- BTC / ETH / SOL miniTicker·4H Kline Combined Stream, Decimal / UTC 이벤트 모델
- 진행 중 / 확정 Candle 분리, 세션 내 확정 중복 방지, 제한된 메모리와 큐
- 자동 재연결·Backoff·Jitter, 심볼별 신선도 감지, 시간 제한 CLI 모니터
- SQLite 가격 스냅샷·확정봉 저장, 출처 보존, Gap 복구, 실행 이력 및 안전한 백업·복원

주문·취소·출금·이체·선물·마진·권한 변경 기능은 없습니다. 주문 함수 placeholder도 없습니다.
PostgreSQL, Signal Engine, 전략 실행, Portfolio Allocation, 백테스트, 모의 투자는 이후 Cycle의 범위입니다.
DEV-M02 완료는 전략 수익성 검증이나 W04 Forward Test 완료를 의미하지 않습니다.
CCXT나 Trading Framework는 사용하지 않습니다.

## DEV-M03 SQLite 저장·복구

DEV-M03 브랜치는 `dev-m03-sqlite-market-data`이며 DEV-M02 최신 버전을 기준으로 합니다.
Python 기본 `sqlite3`를 사용합니다. ORM과 추가 의존성은 없습니다.
기본 DB는 **`data/market_data.sqlite`**이며 로컬 디스크를 사용하세요. UNC/URI/메모리 DB는 거절합니다.
기존 `stream`은 DB에 저장하지 않는 DEV-M02 검증 명령으로 유지합니다.

```bash
uv sync --frozen --group dev
uv run --frozen python -m trading_system.cli db-init
uv run --frozen python -m trading_system.cli collect --duration 600
uv run --frozen python -m trading_system.cli db-status
uv run --frozen python -m trading_system.cli db-verify
```

각 명령에 `--db-path data/another.sqlite`를 지정할 수 있습니다.
`collect`의 기본 duration은 600초입니다. `--bootstrap-days 7`, `--snapshot-seconds 60`,
`--retention-days 30`, `--recovery-max-days 365`로 초기 운영 범위를 설정합니다.
`--report-file logs/collect-new.json`은 기존 파일을 덮어쓰지 않는 공개 요약 파일입니다.
Public REST/WS만 사용하며 **API Key / Secret / .env / Private API가 필요 없습니다**.

- Schema version 1, WAL, synchronous FULL, busy_timeout 5000 ms, foreign_keys ON,
  명시적인 BEGIN IMMEDIATE / COMMIT / ROLLBACK을 사용합니다.
- OS writer lock과 단일 worker thread로 SQLite writer를 하나만 허용합니다. 동시에 두 collector를
  실행하면 두 번째는 `writer_unavailable`로 실패합니다. 조회와 온라인 백업은 별도 읽기 연결입니다.
- WebSocket 수신은 별도 asyncio task입니다. DB 작업은 worker thread에서 실행하고 한 작업만
  제출하므로 느린 디스크나 REST 복구가 수신 event loop를 직접 차단하지 않습니다.
- 가격은 심볼별 60초 UTC 버킷에 신선한 실제 값을 샘플링합니다. 가격 이벤트·수신 시각이 실제
  쓰기 시점에서 10초 이내일 때만 저장합니다. 같은 버킷의 재시작/재수집은 최신 event_time만
  반영합니다. 이전 가격을 새 이벤트 시각으로 바꾸거나 누락 가격을 보간하지 않습니다.
- 확정봉은 Decimal을 TEXT로 저장합니다. `x=false`는 금지하고 `x=true`만 `WS_LIVE`로 저장합니다.
  확정 큐는 **Peek → transaction commit → ACK** 순서입니다. 저장 실패/취소 시 ACK하지 않습니다.
  DB 실패는 `PERSISTENCE_FAILURE`로 수집을 중단하고 성공으로 보고하지 않습니다.
- 확정봉 PK는 `(symbol, interval, open_time_ms)`이며 동일 OHLCV는 중복으로 처리합니다.
  다른 OHLCV는 원본을 보존하고 `candle_conflicts`와 `data_gaps.CONFLICT`에 기록합니다.
  충돌은 자동 해결하거나 덮어쓰지 않습니다.
- 최초 실행에는 서버 UTC 시간 기준 최근 7일 완전히 닫힌 4H 봉을 세 심볼에서 가져옵니다.
  기존 DEV-M01 `PublicAPI.candles()`는 유지하고 새 `candles_range()`를 사용합니다.
  `REST_BOOTSTRAP`과 `REST_RECOVERY`를 구별하며 REST event_time은 NULL입니다.
- 시작·연결 이후·재연결 이후·60초 주기·종료 시 DB 연속성과 기존 마지막 봉을 REST와 비교합니다.
  Gap은 OPEN → RECOVERING → 재조회/연속성 검사 → RESOLVED이며 불완전/실패는 FAILED,
  값 불일치는 CONFLICT입니다. DB 상태는 INCOMPLETE로 유지합니다.
- 한 복구 cycle은 기본 최대 32개 REST 요청, 최소 0.25초 간격, 일시적 transport/5xx만 최대 1회
  재시도합니다. 429/418/451은 같은 cycle의 추가 요청을 중단합니다. 페이지는 최대 1000개입니다.
- 기존 provenance와 최초 ingested_at은 중복 수신으로 변경하지 않습니다. REST 봉을 나중에
  WS_LIVE로 승격하지 않습니다. 조회 결과는 원래 source와 UTC milliseconds를 함께 반환합니다.
  REST 사후 복구는 W04 Genuine Forward 관찰을 대신하지 않습니다.
- 가격은 기본 30일 보존, 확정봉은 자동 삭제하지 않습니다. run 시작/종료를 DB와 별도 fsync
  저널 `market_data.sqlite.runs.jsonl`에 기록합니다. DB만 삭제돼도 저널이 남아 있으면 실행
  이력을 복원합니다. **DB·저널·백업을 모두 삭제하면 복원이 불가능합니다.**
  시장 데이터는 검증된 백업과 REST로 복구하며 저장 전 유실된 가격 메시지의 완전 복구는 보장하지 않습니다.
- `db-verify`는 네트워크 없이 SQLite 무결성·검증된 값·UTC 4H 연속성·Gap 상태를 확인합니다.
  미초기화/미수집/현재 UTC까지 뒤처진 DB는 COMPLETE로 표시하지 않습니다. 시스템 시계를 정확히 유지하세요.

안전한 백업과 새 DB 경로 복원:

```bash
uv run --frozen python -m trading_system.cli db-backup --backup-path data/backups/market-new.sqlite
uv run --frozen python -m trading_system.cli db-restore --backup-path data/backups/market-new.sqlite --db-path data/restored-new.sqlite
uv run --frozen python -m trading_system.cli db-verify --db-path data/restored-new.sqlite
```

SQLite Backup API와 integrity_check를 사용합니다. 운영 중 DB 파일만 복사해 WAL을 누락하지 마세요.
백업/복원 대상 파일이 이미 있으면 거절하며 자동 삭제/덮어쓰기를 하지 않습니다.
DB/WAL/SHM/백업/실행 저널/검증 산출물은 Git에서 제외합니다. 임의 SQL 실행 CLI는 없습니다.

Windows 로컬의 **600초 수집 → 프로그램 재시작 → 추가 600초 → 백업/복원** 검증:

DEV-M03가 main에 병합되기 전에는 `dev-m03-sqlite-market-data` 브랜치에서 실행하세요.
기존 작업 트리에 변경이 있다면 보존하고 별도 clone을 사용하세요. DB와 `.env`를 삭제하지 마세요.

```powershell
uv python install 3.14.7
uv sync --frozen --group dev
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python tools/verify_dev_m03.py --duration 600
```

검증 도구는 기존 DB를 쓰지 않고 `data/dev-m03-validation-<시각>-<UUID>/`를 새로 생성합니다.
두 collection 결과, 기존 기록 보존, 중복/Gap/출처, 백업 복원, credential 출력 검사를 수행하고
`DEV-M03-local-summary.json`에 결과를 기록합니다. 실제 WS 확정봉은 관찰된 경우에만 기재합니다.
`--duration 120`은 짧은 smoke용이며 Windows 10분×2 Acceptance를 대신하지 않습니다.
기본 pytest는 새 `--live-collect` integration을 포함해 실제 네트워크 검사를 모두 skip합니다.

```bash
uv run --frozen pytest -m integration --live-collect -s
```

Windows 긴 pytest ID 오류는 65,537자 입력을 유지한 채 짧은 명시적 ID로 해결했습니다.
push/PR CI는 Linux와 Windows에서 기본 pytest / Ruff를 실행하며 Secrets/live 옵션을 주입하지 않습니다.
상세 검증은 `docs/DEV-M03-validation.md`와 `docs/DEV-M03-summary.json`에 기록합니다.
DEV-M03는 주문·Strategy·Paper Trading·Portfolio Allocation·PostgreSQL을 추가하거나 W04 Clock을 시작하지 않습니다.

## 환경 생성 및 설치

저장소 루트에서 실행합니다. [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에
따라 uv를 설치한 뒤 아래 명령을 실행하세요. uv가 Python과 가상환경을 관리합니다.

```bash
git clone https://github.com/NAM-GOM/ai-multi-strategy-investment-system.git
cd ai-multi-strategy-investment-system
uv python install 3.14.7
uv sync --frozen --group dev
source .venv/bin/activate
python --version
```

Windows PowerShell에서는 활성화 명령이 `.venv\Scripts\Activate.ps1`입니다.
활성화하지 않아도 `uv run --frozen python -m trading_system.cli public`처럼 실행할 수 있습니다.
`uv.lock`은 직접 편집하지 않습니다. 의존성을 변경하는 별도 작업에서만 다시 생성하세요.

이미 Python 3.14.7을 설치했다면 표준 venv / pip도 가능합니다.
다만 아래 방식은 uv의 전체 전이 의존성 lock을 적용하지 않으므로 재현에는 위 명령을 권장합니다.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -e . 'pytest==9.0.2' 'ruff==0.15.6'
```

## 환경변수와 .env

**Public 명령에는 API Key가 필요 없으며, 요청에 인증 헤더·서명을 넣지 않습니다.**
계정 검증이 필요할 때만 아래 명령으로 예제 파일을 복사하고 로컬에서 값을 입력하세요.
이미 `.env`가 있다면 보존합니다.

```bash
test -e .env || (umask 077; cp .env.example .env)
```

| 변수 | 기본값 / 용도 |
| --- | --- |
| `BINANCE_API_KEY` | 미설정. 읽기 권한이 있는 HMAC API Key |
| `BINANCE_API_SECRET` | 미설정. HMAC 서명용 Secret |
| `BINANCE_PUBLIC_BASE_URL` | `https://data-api.binance.vision` |
| `BINANCE_TIMEOUT_SECONDS` | `10`, 허용 범위 `0 < timeout <= 60`초 |
| `BINANCE_RECV_WINDOW_MS` | `5000`, 허용 범위 `1..5000`ms |

프로세스 환경변수가 루트 `.env`보다 우선합니다. 빈 환경변수도 `.env` 값을 덮어씁니다.
`.env` 보간은 사용하지 않고, 로딩으로 프로세스 환경을 변경하지 않습니다.
CLI는 현재 작업 디렉터리의 `.env`를 읽으므로 저장소 루트에서 실행하세요.

공개 데이터 기본 호스트는 Binance 공식 문서에서 시장 데이터 전용으로 안내하는
`data-api.binance.vision`입니다. `https://api.binance.com`도 명시적으로 설정할 수 있습니다.
계정 요청은 항상 `https://api.binance.com`으로 전송하며 다른 호스트나 HTTP URL은 허용하지 않습니다.
계정용 키는 HMAC 유형을 사용하세요. RSA / Ed25519 키는 이 MVP에서 지원하지 않습니다.

## 실행

```bash
python -m trading_system.cli public
python -m trading_system.cli account
python -m trading_system.cli all
```

`public`은 가격 3개, BTCUSDT 4H 캔들 10개, 호가와 latency를 출력합니다.
`account`는 인증 상태와 잔액 4개를 출력합니다. 응답에 없는 자산도 0으로 표시합니다.
`all`은 Public 검사 실패 시에도 Account 검사를 진행하며 최종 종료 코드에 실패를 반영합니다.
키가 없거나 일부만 설정되면 종료 코드 0과 아래 메시지를 출력합니다.

```text
Private API credentials not configured. Account check skipped.
```

가격·수량·잔액은 `Decimal`로 계산하며 `total = free + locked`입니다.
`spread = best_ask - best_bid`, `spread_percent = spread / best_bid * 100`입니다.
캔들 시간은 UTC로 유지하고 CLI에서 ISO-8601 `+00:00`으로 표시합니다.

**REST latency는 `perf_counter()`로 측정한 application round-trip latency입니다.**
현재 프로그램에서 HTTP 요청을 보내고 응답 본문을 수신·해석하는 데 걸린 시간이며,
Exchange matching latency가 아닙니다. 서명 요청의 사전 서버 시간 조회는 Account latency에서 제외합니다.
서버 시간을 조회한 뒤 monotonic 경과 시간을 보정해 timestamp를 생성합니다.

## 오류와 로그

Console 로그는 stderr, 파일 로그는 **`logs/app.log`**에 기록됩니다.
디렉터리는 실행 중 생성하며 파일은 1 MB 단위로 최대 3개 백업으로 회전합니다.
시작·종료, endpoint, symbol, 성공·실패, latency, 계정 인증 상태, 안전한 exception 분류를 기록합니다.
잔액과 API 응답 본문은 파일 로그에 기록하지 않습니다.

| 오류 분류 | 의미 |
| --- | --- |
| `network_timeout` | 연결 / 읽기 등 HTTP timeout |
| `connection_error` | DNS / TCP / TLS / Proxy 연결 오류 |
| `http_4xx`, `http_5xx` | 일반 HTTP 오류. HTTP status도 표시 |
| `binance_api_error` | 별도 매핑 없는 Binance 음수 오류 코드 |
| `invalid_symbol` | 잘못된 symbol / Binance `-1121` |
| `invalid_api_key` | Binance `-2014` |
| `invalid_api_key_or_permissions` | Binance `-2015`: key / IP / 권한을 API가 하나의 코드로 보고 |
| `invalid_signature` | Binance `-1022` |
| `timestamp_synchronization` | Binance `-1021` |
| `authentication_failure` | Binance `-1002` |
| `rate_limit`, `ip_ban` | HTTP 429 / 418. 자동 재시도 없음 |
| `invalid_response` | JSON / 필수 필드 / 숫자 형태 오류 |
| `http_redirect_rejected` | 인증정보 유출 방지를 위해 redirect 거절 |

Exit code: 성공 또는 credentials skip `0`, API / 내부 오류 `1`, 설정 / 로그 초기화 오류 `2`,
사용자 중단 `130`. 자동 재시도를 하지 않으므로 429/418에서는 요청을 중단하고 Binance 제한을 확인하세요.
Binance의 원문 오류 메시지나 HTTP URL·헤더·traceback은 출력하지 않습니다.
HTTP 451은 해당 호스트의 접근 제한을 뜻하며 키 오류와 구별됩니다.
지원되지 않는 지역에서 Account 접근 제한을 우회하는 기능은 구현하지 않습니다.

## DEV-M02 공개 WebSocket

DEV-M02 작업 브랜치는 `dev-m02-binance-websocket`입니다. `main`에 반영되기 전에는 해당
브랜치를 checkout한 뒤 `uv sync --frozen --group dev`를 실행하세요.
Python 3.14.7에서 확인한 **websockets 17.2**를 `pyproject.toml`과 `uv.lock`에 고정했습니다.

```bash
uv run --frozen python -m trading_system.cli stream --duration 120
# 공개 검증 요약 JSON 저장: logs/는 실행 중 생성, 파일은 새 경로를 사용
uv run --frozen python -m trading_system.cli stream --duration 120 --report-file logs/ws-check.json
```

API Key / Secret이나 `.env`가 필요 없으며 `stream`은 계정 설정을 읽지 않습니다.
기존 `public`, `account`, `all` 명령의 동작은 유지합니다.
기본 서버는 `wss://data-stream.binance.vision`이며 한 연결에서 다음을 구독합니다.

```text
btcusdt@miniTicker / ethusdt@miniTicker / solusdt@miniTicker
btcusdt@kline_4h   / ethusdt@kline_4h   / solusdt@kline_4h
```

Combined URL은 `/stream?streams=<위 6개 스트림을 /로 연결>`입니다.
공식 대체 서버는 아래처럼 명시적으로 선택합니다. 임의 URL과 redirect는 거절합니다.
자동 호스트 전환이나 지역 제한 우회는 구현하지 않습니다.

```bash
uv run --frozen python -m trading_system.cli stream --duration 120 --ws-base-url wss://stream.binance.com
```

5초 간격으로 연결 상태·실제 가격·심볼별 가격/캔들 수신 수·가격 나이·캔들 상태·오류/재연결
횟수를 출력합니다. 가격을 받기 전에는 `NOT_RECEIVED`입니다. `CONNECTED` / `HEALTHY`는
현재 연결에서 **세 심볼의 가격과 캔들이 모두 신선한 경우**에만 표시합니다.
`CONNECTING`, `STALE`, `RECONNECTING`, `DISCONNECTED`, `STOPPED`도 지원합니다.
종료 후 상태는 `STOPPED`이며 `Final data fresh`는 종료 직전의 신선도를 별도로 표시합니다.

- 초기 신선도 기준: 가격 **10초**, 캔들 **30초**. Binance miniTicker는 약 1초, 4H Kline도
  약 2초마다 갱신합니다. 시간 간격 4h가 메시지 간격 4h라는 뜻은 아닙니다.
  monotonic 수신 나이와 거래소 UTC 이벤트 나이를 함께 확인하므로 시스템 시계가 정확해야 합니다.
  이 임계값은 초기 운영 기준이며 장기 운용 후 조정해야 합니다.
- `k.x=false`는 최신 진행 봉으로만 보관합니다. `k.x=true`만 `CLOSED_CANDLE`로 전달합니다.
  `(symbol, interval, open_time)` 기준으로 단조 증가 watermark를 사용해 세션 내 중복을 막습니다.
  watermark보다 오래된 확정봉은 재발행하지 않고 잠재적 전달 손실로 명시합니다.
- 가격은 심볼별 최신 1개로 합치며, 심볼별 진행 봉·최근 확정 봉·watermark 각 1개를 유지합니다.
  확정봉 큐는 기본 **128개**, 라이브러리 수신 큐는 **16 프레임**, 프레임 크기는 **64 KiB**입니다.
  CLI는 요약마다 확정 이벤트를 소비합니다. 다른 소비자는 `market.drain_closed()`를 호출해야 합니다.
  확정봉 큐가 가득 차면 조용히 버리지 않고 `DATA_LOSS` / 실패로 종료합니다.
  캔들 연속성 누락도 명시하며 REST backfill은 수행하지 않습니다.
- 연결이 끊기거나 서버 `serverShutdown` 메시지가 오면 재연결합니다.
  Backoff는 1 / 2 / 4 / 8 / 16 / 32 / 최대 60초에 Jitter를 적용합니다.
  30초 이상 정상 유지한 연결 뒤에만 Backoff를 초기화합니다.
  30초 연속 STALE이면 재연결하며, 재연결 중에는 기존 값이 신선해도 정상으로 취급하지 않습니다.
- 서버 Ping에는 websockets의 자동 Pong으로 같은 payload를 응답합니다. 추가 클라이언트 Ping이나
  subscribe 제어 메시지는 보내지 않습니다. 24시간 수명 전에 **23시간 50분**에 사전 재연결합니다.
  Binance 제한은 제어 메시지 5개/초, 연결 시도 300회/5분/IP, 스트림 1024개/연결입니다.
- `Ctrl+C`로 종료할 수 있습니다. 로그는 기존 회전식 `logs/app.log`에 연결·종료·재연결·수신 수·
  무효 메시지 수·확정봉·STALE을 기록합니다. 원본 프레임이나 API credential은 기록하지 않습니다.

종료 코드: 신선한 6개 스트림을 받고 손실 없이 정상 종료하면 `0`, 수신/환경 검증 실패 `1`,
잘못된 설정 또는 보고서 파일 생성 실패 `2`, 사용자 중단 `130`입니다.
제한 응답은 `BLOCKED_ENVIRONMENT`로 보고합니다. 반복 연결 실패로 데이터가 전혀 없는 경우도
해당 상태로 분류하며 `error_category` / HTTP status를 함께 확인하세요.
실패를 모의 데이터로 대체하지 않습니다. JSON 보고서는 기존 파일을 덮어쓰지 않습니다.

실제 4H 마감은 2분 테스트에 없을 수 있습니다. 확정 로직의 단위 테스트 PASS와
실제 `x=true` 관찰은 별도입니다. 저장하지 않는 `stream`의 중복 방지는 메모리 세션 범위입니다.
DEV-M03의 `collect`는 DB PK 중복 방지와 REST 누락 복구를 추가하며, 영속적인 이벤트 전달의
exactly-once 보장을 주장하지 않습니다. [DEV-M02 검증 기록](docs/DEV-M02-validation.md)을 확인하세요.

공식 규격: [Binance Spot WebSocket Streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams).

## Tests

```bash
pytest
pytest -m 'not integration'
ruff check .
ruff format --check .
```

기본 실행은 실제 네트워크를 사용하는 8개 Integration Test를 skip합니다.
Unit Test는 `httpx.MockTransport`로 가격, 캔들, 호가, Decimal spread, latency, 환경변수,
공개 HMAC 테스트 벡터, 서명된 실제 query 형식, 잔액, missing credential,
HTTP / Binance / timeout / connection / redirect 오류 및 로그 유출 방지를 검증합니다.
Unit Test의 실제 네트워크 접근은 테스트 fixture에서 차단합니다.
DEV-M02는 파서·Decimal/UTC·중복 확정·제한된 메모리/큐·STALE·재연결/Backoff/Jitter·
Ping/Pong·서버 종료·사전 rotation·Ctrl+C에 대응하는 취소·credential 미사용을 결정적으로 검사합니다.
DEV-M03는 SQLite transaction/ACK, 실패 주입, Decimal/UTC/출처, 재시작, Gap/REST 복구와
공식 Backup API를 검증합니다. CI는 Linux와 Windows에서 같은 기본 명령을 실행합니다.

실제 API를 사용하는 선택적 검증:

```bash
pytest -m integration --live-public
pytest -m integration --live-account
pytest --live-public --live-account
pytest -m integration --live-stream -s
```

Account Integration Test는 `--live-account` 옵션이 있어도 Key / Secret이 없으면 자동 skip합니다.
옵션이 없으면 CI에 키가 주입되어도 계정 API를 호출하지 않습니다.
실제 요청에 실패하면 Integration Test를 실패로 보고하며 모의 결과로 대체하지 않습니다.
WebSocket integration도 `--live-stream`을 명시했을 때만 120초간 실행합니다.
일반 push / PR CI에는 live 옵션이나 Binance Secrets를 추가하지 않습니다.

## GitHub Actions에서 Binance Account 검증

`.github/workflows/live-account.yml`은 **사용자가 수동으로 실행할 때만** 읽기 전용 계정 API를 호출합니다.
Repository Secrets의 `BINANCE_API_KEY`, `BINANCE_API_SECRET`을 live 테스트 단계의 환경변수로만
주입합니다. `.env` 파일은 만들지 않습니다. HMAC 유형의 **Read-only API Key**를 사용하세요.
**Trading Permission 및 Withdrawal Permission은 필요 없습니다.**

GitHub에서 workflow 파일이 기본 브랜치(`main`)에 등록되어 있어야 Actions의 수동 실행 버튼이
표시됩니다. 현재 작업 브랜치만 push한 상태라면 먼저 `dev-m01-binance-connectivity`의 변경사항을
PR로 `main`에 병합하세요. 병합 자체로 live workflow가 실행되지는 않습니다.

그다음 다음 순서로 실행합니다.

1. GitHub 저장소 → **Actions**
2. **DEV-M01 Live Binance Account Check**
3. **Run workflow**
4. Branch에서 **dev-m01-binance-connectivity** 선택
5. `runner_mode` 선택: **github-hosted-diagnostic** 또는 **self-hosted**
6. **Run workflow**

기본값 `github-hosted-diagnostic`은 GitHub의 Ubuntu runner에서 **키 없이** 계정 호스트의
공개 `/api/v3/time` 접근만 검사합니다. 인증이나 잔액을 조회하지 않습니다.
실제 계정 검증에는 `self-hosted`를 선택해야 하며, 아래의 허용된 실행 환경 준비가 선행되어야 합니다.

Workflow는 checkout → setup-uv → Python 3.14.7 설치 → frozen 의존성 설치 →
Unit Test → **credentials 없는 계정 호스트 preflight** → 명시적 live account integration 순서로
동작합니다. preflight가 실패하면 Secrets 주입과 계정 조회를 진행하지 않습니다.

```bash
uv run --frozen pytest -m 'not integration'
uv run --frozen pytest -m integration --live-account -s --tb=no --show-capture=no
```

일반 push / PR용 `tests.yml`은 기존 Unit / Mock / Lint CI로 유지하며 Binance Secrets를 주입하지
않습니다. 일반 pytest는 Private API를 호출하지 않습니다. live workflow에서도 `--live-public`을
지정하지 않아 가격 / 캔들 / 호가 Integration Test는 skip합니다.

실제 계정 응답은 기존 AccountAPI / Balance로 파싱합니다. USDT / BTC / ETH / SOL을 모두 포함하며,
free / locked / total이 유한한 음수 아닌 Decimal인지, `total == free + locked`인지 검증합니다.
응답에서 빠진 자산은 기존 동작대로 0으로 처리합니다.

Actions 로그에는 다음 형식의 **상태 요약만** 표시합니다.

```text
DEV-M01 Live Account Check
Authentication: PASS 또는 FAIL
USDT: PRESENT 또는 ZERO
BTC: PRESENT 또는 ZERO
ETH: PRESENT 또는 ZERO
SOL: PRESENT 또는 ZERO
Private API endpoint: GET /api/v3/account
Trading endpoints: NOT IMPLEMENTED
Secret exposure check: PASS 또는 FAIL
```

`PRESENT`는 total > 0, `ZERO`는 total == 0을 뜻합니다. 실제 보유 수량, 계정 JSON 전체,
Key / Secret / signature, 요청 URL / 헤더는 출력하지 않습니다. 앱 로그는 먼저 메모리에 모으고
요약과 함께 credential / 서명 / URL / 헤더 / account JSON 노출 패턴을 검사합니다.
검사에 실패하면 원문을 버리고 안전한 FAIL 메시지만 표시합니다. pytest traceback과 failure capture도
workflow에서 비활성화하며 로그 파일을 artifact로 업로드하지 않습니다.
로컬 `python -m trading_system.cli account`의 free / locked / total 숫자 출력은 유지합니다.

Secrets가 없거나 한쪽만 있으면 `Authentication: SKIPPED`, 자산별 `NOT_VERIFIED`와 pytest skip을
표시합니다. **job이 녹색이어도 skip은 PRIVATE-02 / PRIVATE-03의 PASS가 아닙니다.**
인증 또는 잔액 검증에 실패하면 test와 job을 실패로 보고하며 안전한 오류 분류와 HTTP status를 표시합니다.
HTTP 451에서는 다음 메시지를 추가하고 지역 제한을 우회하지 않습니다.

```text
Binance private API is not reachable from this GitHub Actions runner/environment.
```

`ubuntu-latest` runner에서도 Binance의 지역 / IP 제한 때문에 실패할 수 있습니다.
실제 수동 run에서 `Authentication: PASS`, 네 자산의 상태 출력, exposure check PASS를 확인한 뒤에만
검증 문서의 PRIVATE-02 / PRIVATE-03을 PASS로 변경하세요. 코드나 모의 테스트 성공만으로 변경하지 않습니다.

### HTTP 451 원인과 실행 환경 준비

기존 GitHub-hosted 계정 검증은 HTTP 451로 실패했습니다. 키 없는 공개 endpoint도
`restricted_location`으로 거절되면 **인증 이전의 지역 / 이용 자격 접근 제한**입니다.
키 오류 / IP 권한 오류(`-2014`, `-2015`), 서명 오류(`-1022`), timestamp 오류(`-1021`)와 다릅니다.
응답 원문 대신 고정된 `Restriction=restricted_location` 또는 `unspecified_451`만 표시합니다.
runner의 정확한 국가와 사용자의 이용 자격은 HTTP status만으로 추정하지 않습니다.

```bash
uv run --frozen python -m trading_system.binance.connectivity
```

이 preflight는 `.env`와 Binance credentials를 읽지 않습니다. 성공해도 Account 인증 성공을 뜻하지
않으며, 실패 시 종료 코드 1입니다. GitHub-hosted runner의 451을 새 키 발급, recvWindow 변경,
재시도로 해결할 수 있다는 근거는 없습니다. 시장 데이터 전용 호스트는 Account API를 제공하지 않습니다.

실제 해결 경로는 **사용자와 서비스 모두 Binance 이용 자격이 있는 환경**에서 신뢰할 수 있는
self-hosted runner를 사용하는 것입니다. 차단된 사용자의 제한을 우회할 목적으로 원격 지역을 선택하거나
VPN / 프록시 / runner 변경을 이용하는 방식은 지원하지 않습니다.

1. 이미 Binance 이용이 허용되는 환경의 Linux x64 서버 또는 개인 PC를 준비합니다.
   별도 서버가 없다면 해당 환경에서 사용 중인 Linux PC도 가능합니다.
2. GitHub 저장소 → **Settings → Actions → Runners → New self-hosted runner**에서
   Linux x64를 선택하고 해당 머신에서 GitHub가 제공하는 등록 절차를 수행합니다.
   등록 토큰은 로컬에서만 사용하고 Git이나 채팅에 넣지 않습니다.
3. runner에 **`binance-readonly`** label을 추가하고 online 상태를 확인합니다.
   workflow는 `[self-hosted, linux, x64, binance-readonly]`만 선택합니다.
4. 그 머신에서 키 없는 preflight가 성공하고, 계정과 실행 환경의 이용 자격이 충족되는지 확인합니다.
   기존 키의 IP 제한이 있다면 해당 신뢰할 수 있는 출구 IP가 허용되어 있어야 합니다.
   이번 구현은 API Key Permission을 변경하지 않습니다.
5. 수동 workflow에서 **self-hosted**를 선택합니다. runner가 없으면 job은 대기하므로
   준비 전에는 기본 진단 모드를 사용하세요.

클라우드 작업 당시에는 사용할 서버가 없었고 runner 목록 조회 API도 권한 부족
(`Resource not accessible by integration`)으로 거절되었습니다. 이후 Windows 로컬 PC에서는
사용자 보고 기준으로 실제 Account 인증과 네 자산 잔액 검증이 성공했습니다.
GitHub runner 등록 및 workflow 인증 성공은 별도로 남아 있습니다.

### Windows 로컬 실행 검증

2026-10-08 접수된 사용자 보고에서 Python 3.14.7 / commit `8be24ea`로 계정 호스트 접근,
실제 인증, 네 자산의 Decimal / total 검증, Unit 102개와 live account 1개가 통과했습니다.
세부 근거와 GitHub-hosted 결과의 구분은 [검증 기록](docs/DEV-M01-validation.md)에 있습니다.

Windows PowerShell에서도 가상환경 활성화 없이 직접 실행할 수 있습니다.

```powershell
uv python install 3.14.7
uv sync --frozen --group dev
uv run --frozen python -m trading_system.binance.connectivity
# preflight 성공 및 로컬 read-only credentials 설정 후
uv run --frozen python -m trading_system.cli account
uv run --frozen pytest -m integration --live-account -s --tb=no --show-capture=no
```

Repository Secrets는 로컬에 자동 전달되지 않습니다. Key / Secret은 로컬 `.env` 또는 환경변수로
안전하게 설정하고 채팅이나 Git에 넣지 않습니다. 직접 실행에는 GitHub runner 등록이 필요 없습니다.
기존 self-hosted workflow는 Linux x64 label을 사용하므로 이 Windows 실행 결과가 Windows runner의
workflow 지원·성공을 뜻하지는 않습니다.

## Architecture / Endpoints

```text
src/trading_system/
  config.py             # 환경변수, .env, host / timeout / recvWindow 검증
  logging_config.py     # Console / File, credential redaction, HTTP 로그 억제
  cli.py                # public / account / all, 출력 및 종료 코드
  binance/
    client.py           # 허용된 GET, timeout, 서명, 서버 시간, 오류, latency
    public.py           # Ticker / Candle / OrderBook 모델과 파싱
    account.py          # 읽기 전용 인증, Balance 모델과 파싱
tests/                  # 모의 응답 테스트 및 opt-in integration
```

| Method | Endpoint | 용도 |
| --- | --- | --- |
| GET | `/api/v3/ticker/price` | BTCUSDT / ETHUSDT / SOLUSDT 가격 |
| GET | `/api/v3/klines` | BTCUSDT, interval=4h, limit=10 |
| GET | `/api/v3/depth` | BTCUSDT, limit=10 |
| GET | `/api/v3/time` | 서명 요청 전 서버 시간 동기화 |
| GET | `/api/v3/account` | timestamp / recvWindow / HMAC / X-MBX-APIKEY |

공통 클라이언트는 이 endpoint만 허용하고, Signed GET은 account에만 허용합니다.
REST 규격의 기준은 [Binance 공식 Spot API 문서](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)입니다.

## Security / Cloud 환경

- **API Key와 Secret을 Git에 Commit하지 않습니다.** `.env.example`은 빈 값만 포함합니다.
- 현재 단계에는 **Trading Permission 및 Withdrawal Permission이 필요 없습니다.** 읽기 권한만 사용하세요.
- API Key, Secret, 전체 signature를 Console / File / exception message에 기록하지 않습니다.
  알려진 credential 값과 signature 필드를 추가로 redact하고 HTTPX wire 로그를 억제합니다.
- `.env`, `.env.*` (예제 제외), `*.log`, 회전 로그, 캐시, 가상환경은 Git에서 제외합니다.
- TLS 검증과 의존성 artifact 검증을 끄지 않습니다. redirect와 자동 retry를 사용하지 않습니다.
- 실제 API 키를 테스트 fixture, CI 설정, 셸 명령 인자, 보고서에 입력하지 마세요.
  로컬 `.env` 또는 안전한 환경변수 주입을 사용하고 키 값은 채팅에 보내지 마세요.
- HMAC Secret은 Python 프로세스가 실제 값을 읽어야 합니다. HTTPS proxy의 secret placeholder는
  로컬 HMAC 계산에 사용할 수 없으므로 그런 placeholder를 실제 Secret으로 취급하지 마세요.
- 클라우드 네트워크에는 `data-api.binance.vision`과 `api.binance.com` 접근이 필요합니다.
  저장된 설정 초안은 실행 중 설정이나 게시 완료를 뜻하지 않습니다.
- 각 클라우드 작업은 격리되어 있으므로 기존 checkout을 사용하고 별도 Git worktree를 만들지 않습니다.

검증 결과와 남은 조건은 [DEV-M01 검증 기록](docs/DEV-M01-validation.md)에 정리합니다.
# DEV-M04 Strategy Signal Observer

DEV-M04 reuses the byte-preserved W03 strategies and their original initialization
wrapper. It records conditions from confirmed BTC/ETH/SOL 4H candles. It does not
start Formal W04, change strategy approvals or positions, submit orders, create
forward fills, or start forward PnL. T2/T3 remain W03_HOLD.

The frozen M03 parent is `1b1bf582f34a526d9204a084dc4573c79efa124e`.
See [M04 validation](docs/DEV-M04-validation.md) and
[M03 freeze review](docs/DEV-M03-freeze-review.md) for actual and pending results.

Final result: **DEV-M04_PASS_WITH_FLAGS**. Both 2026-10-10 01:00 and 05:00 KST
real closes passed with nine LIVE decisions each, exact offline snapshot/hash
replay, and zero new decisions after process restart. See the
[Korean final report](docs/DEV-M04-final-report-ko.md) and
[independent overnight audit](docs/DEV-M04-overnight-audit.json).
These are two separate observation windows; Formal W04 remains unstarted.

Run from the repository checkout with Python 3.14.7:

```sh
uv sync --frozen --group dev
uv run --frozen python -m trading_system.cli strategy-audit
uv run --frozen python -m trading_system.cli db-init
uv run --frozen python -m trading_system.cli strategy-replay --start-ms 1790928000000 --end-ms 1790928000000
uv run --frozen python -m trading_system.cli observe --duration 600
uv run --frozen python -m trading_system.cli observer-status
```

Audit and replay are offline. The default replay range is the complete Frozen W03
evaluation interval; the example records only its last batch. Replay generates
historical condition records, never live Paper performance. Frozen files live in
`artifacts/w03` and `src/trading_system/observer/frozen`; their exact bytes are
protected by `.gitattributes` and hashes. pandas/numpy match W03 exactly. Their
formatting is excluded from Ruff to preserve source bytes.

The Observer opens `data/market_data.sqlite` through M03 MarketRepository in read-only
mode. A separate M03 Collector must maintain it. The Frozen initialization history
is joined to **all** post-freeze market candles, with no missing interval. A rolling
7-day bootstrap eventually omits the boundary; use a bootstrap that reaches
2026-10-02 12:00 UTC or retain the existing continuous DB. The Observer does not
download or write market data. Missing history or any failed symbol blocks the
whole nine-decision batch.

`data/observer.sqlite` contains append-only manifests, batch decisions and health
events, atomic checkpoints and run records. `--observer-db` selects an independent
observer instance. A persistent rule/persistence STOP requires a new audited
observer DB while preserving the old evidence. A single CLI writer lease prevents
overlapping observer processes. Restarts verify stored hashes and retain each
decision's original observation classification. `observer-status` is read-only.

Research freeze: `2026-10-02T12:00:00Z`. Frozen bars are SEEN_HISTORICAL_DATA;
post-freeze REST and already-ended WS bars are PRELAUNCH_STATE_BACKFILL. Only new
WS closes observed after this process started can be LIVE_OBSERVATION. After a
DATA_HOLD, recovered old bars remain state backfill. FORMAL_W04_ELIGIBLE is reserved
for the separate verified W04 system; M04 does not issue that classification.
Candidate booleans are not position-aware executable orders. Frozen stops, capital
allocation, next-open execution, observed quotes and Gate F belong to W04; their
historical behavior is checked through exact original engine parity.

An opt-in Windows live supervisor is available:

```sh
uv run --frozen python tools/verify_dev_m04_live.py --target-close-ms 1791561600000 --output data/m04-live-20261010T010000
```

It waits for the specified future real 4H close, runs the public M03 collector and
M04 observer in separate processes, checks all nine durable decisions, and launches
a new observer process to test duplicate prevention. It requests temporary Windows
sleep prevention and restores it on exit. A scheduled target is a validation plan,
not a Formal W04 start or evidence of a received candle. If the close is not received,
the report remains LIVE_NOT_OBSERVED or records failure.
