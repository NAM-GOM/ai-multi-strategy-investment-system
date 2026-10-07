# AI Multi-Strategy Investment System — DEV-M01

**현재 버전은 주문 기능이 없는 Read-only Binance Spot Connectivity MVP입니다.**
Python 프로그램의 공개 시장 데이터 조회와 읽기 전용 계정 인증을 검증합니다.
GitHub 저장소의 소스, `.python-version`, `pyproject.toml`, `uv.lock`이 구현과 환경의 기준입니다.
Python **3.14.7**을 사용하며 프로젝트의 지원 버전은 **3.14.x**입니다.

구현 범위:

- BTCUSDT / ETHUSDT / SOLUSDT 현재 가격
- BTCUSDT 최근 4시간봉 10개: UTC ISO-8601 시간과 OHLCV. 마지막 봉은 미완성일 수 있습니다.
- BTCUSDT 상위 10개 Bid / Ask, best bid / ask, spread, spread percent, REST latency
- HMAC SHA-256 인증과 USDT / BTC / ETH / SOL의 free / locked / total 잔액
- 키가 없거나 하나만 설정된 경우 계정 검증을 안전하게 건너뜀
- Console / File 로그, 모의 HTTP 테스트, 선택적 실제 연결 테스트

주문·취소·출금·이체·선물·마진·권한 변경 기능은 없습니다. 주문 함수 placeholder도 없습니다.
WebSocket, Database, Signal Engine, 전략 실행, 백테스트, 모의 투자는 이후 Cycle의 범위입니다.
CCXT나 Trading Framework는 사용하지 않습니다.

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

## Tests

```bash
pytest
pytest -m 'not integration'
ruff check .
ruff format --check .
```

기본 실행은 실제 네트워크를 사용하는 6개 Integration Test를 skip합니다.
Unit Test는 `httpx.MockTransport`로 가격, 캔들, 호가, Decimal spread, latency, 환경변수,
공개 HMAC 테스트 벡터, 서명된 실제 query 형식, 잔액, missing credential,
HTTP / Binance / timeout / connection / redirect 오류 및 로그 유출 방지를 검증합니다.
Unit Test의 실제 네트워크 접근은 테스트 fixture에서 차단합니다.

실제 API를 사용하는 선택적 검증:

```bash
pytest -m integration --live-public
pytest -m integration --live-account
pytest --live-public --live-account
```

Account Integration Test는 `--live-account` 옵션이 있어도 Key / Secret이 없으면 자동 skip합니다.
옵션이 없으면 CI에 키가 주입되어도 계정 API를 호출하지 않습니다.
실제 요청에 실패하면 Integration Test를 실패로 보고하며 모의 결과로 대체하지 않습니다.

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

현재 이 작업에서는 사용할 서버가 없다는 사용자 답변을 받았고 runner 목록 조회 API도 권한 부족
(`Resource not accessible by integration`)으로 거절되었습니다. runner 설치·등록 완료를 주장하지 않습니다.
실제 Account 검증은 이용 가능한 적격 머신이 준비된 뒤 수행할 수 있습니다.

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
