# DEV-M01 검증 기록

검증 일자: **2026-10-07 (Asia/Seoul)**. Python 3.14.7 / httpx 0.28.1 / pytest 9.0.2.
현재 구현은 주문 기능이 없는 읽기 전용 Binance Spot 클라이언트입니다.

## 생성 / 수정 파일

- 수정: `README.md`, `.gitignore`
- 생성: `.python-version`, `.env.example`, `pyproject.toml`, `uv.lock`
- 생성: `src/trading_system/__init__.py`, `config.py`, `logging_config.py`, `cli.py`
- 생성: `src/trading_system/binance/__init__.py`, `client.py`, `public.py`, `account.py`
- 생성: `tests/conftest.py`, `test_public_api.py`, `test_account.py`, `test_config.py`,
  `test_errors.py`, `test_cli.py`, `test_integration.py`
- 생성: `.github/workflows/tests.yml`, `docs/DEV-M01-validation.md`
- 로컬 실행 산출물 (Git 제외): `.venv/`, `logs/app.log`, pytest / bytecode / ruff cache

공통 GET 전용 REST Client가 인증, timeout, error, latency를 담당합니다.
Public / Account 모듈은 응답을 Decimal 기반 모델로 변환하며 CLI는 표시와 종료 코드를 담당합니다.
사용하는 endpoint는 모두 GET이며 `/api/v3/ticker/price`, `/api/v3/klines`,
`/api/v3/depth`, `/api/v3/time`, `/api/v3/account`뿐입니다.
설치 / 실행 / 환경변수 / 보안 설정은 루트 README에 있습니다.

## 직접 실행 결과

`uv sync --frozen --group dev` 설치 및 반복 실행에 성공했습니다.
`uv build --out-dir /tmp/dev-m01-dist`로 sdist / wheel을 빌드했고 `uv pip check`도 통과했습니다.
`ruff check .`, `ruff format --check .`, `git diff --check`를 통과했습니다.

| 명령 | 결과 |
| --- | --- |
| `pytest` | 71 passed, 6 skipped (live integration 미선택) |
| `pytest --live-public --live-account` | 76 passed, 1 skipped (실제 계정 키 없음) |
| `python -m trading_system.cli public` | 기본 public host에서 가격 / 캔들 / 호가 / latency 출력, exit 0 |
| `python -m trading_system.cli account` | credentials skip 메시지, exit 0 |
| `uv run --frozen python -m trading_system.cli all` | 공개 데이터 성공 + 계정 skip, exit 0 |

2026-10-07 21:40 KST의 실제 공개 API 실행 관측값 (실시간 숫자는 계속 변합니다):

```text
BTCUSDT : 83559.90000000 USDT
ETHUSDT : 2575.87000000 USDT
SOLUSDT : 116.87000000 USDT
BTCUSDT 4H candles: 10
BTCUSDT bids / asks: 10 / 10
best_bid: 83563.35000000
best_ask: 83563.36000000
spread: 0.01000000 USDT
spread_percent: 0.00001197%
REST Latency: 182.1 ms (application round-trip)
Private API credentials not configured. Account check skipped.
```

이 숫자는 검증 기록이며 실행 코드에 가격을 하드코딩하지 않았습니다.
로그에서 실제 성공·실패 endpoint / symbol / latency / program exit를 확인했습니다.
계정 인증 성공·실패와 잔액 4종 출력은 모의 응답 테스트로 검증했습니다.
라이브 계정 인증 성공은 확인하지 않았습니다.

## Acceptance Criteria

| ID | 상태 | 근거 / 남은 조건 |
| --- | --- | --- |
| PUBLIC-01 | PASS | API 키 없이 BTC / ETH / SOL 실제 가격 조회 |
| PUBLIC-02 | PASS | BTCUSDT 최근 4H Candle 10개 실제 조회 |
| PUBLIC-03 | PASS | BTCUSDT Bid / Ask 각각 10개 실제 조회 |
| PUBLIC-04 | PASS | Order Book REST latency 출력 |
| PRIVATE-01 | PASS | 키 미설정 시 안전하게 skip, exit 0 |
| PRIVATE-02 | 미검증 | 키 / Secret 미설정. 계정 호스트도 현재 클라우드에서 HTTP 451 |
| PRIVATE-03 | 모의 검증 PASS / 실제 미검증 | USDT / BTC / ETH / SOL free / locked / total / 0 출력 테스트 통과 |
| SECURITY-01 | PASS | 소스의 실제 API Key 없음. 테스트 fixture는 명확한 dummy 값 |
| SECURITY-02 | PASS | 소스의 실제 Secret 없음. HMAC 테스트는 공개 RFC 4231 벡터 |
| SECURITY-03 | PASS | `.env` Git 미추적 및 ignore 규칙 확인 |
| SECURITY-04 | PASS | endpoint allowlist / 소스 HTTP 호출 점검: GET 5종만 존재 |
| TEST-01 | PASS | 기본 pytest 및 실제 공개 integration 포함 실행 통과. Private skip 명시 |
| LOG-01 | PASS | 실제 성공·실패·latency 로그 및 모의 인증 / credential redaction 검증 |
| README-01 | PASS | pinned Python / frozen 설치 / CLI / pytest 절차를 현재 머신에서 실행 |

소스·설정·문서·테스트를 대상으로 API credential 대입, Binance key 형태,
대표적인 토큰 / private key 패턴을 값 출력 없이 점검했습니다.
의존성 checksum과 공개 HMAC 벡터는 credential로 분류하지 않았습니다.
검사 결과 실제 credential 의심 항목은 없었습니다. 이 점검은 패턴 기반으로 범위가 제한됩니다.
`.env`, `.env.local`, 로그와 회전 로그, 가상환경, bytecode / pytest 캐시 ignore도 확인했습니다.

## 발견된 문제와 다음 단계

1. 최초 `api.binance.com` 공개 호출은 HTTP 451로 실패했고 실제 응답의 restricted location 여부를
   확인했습니다. Binance 공식 시장 데이터 전용 호스트 `data-api.binance.vision`에서 공개 데이터
   검증이 성공해 기본 Public host로 사용합니다. 이 호스트는 계정 인증을 제공하지 않습니다.
2. 실제 `BINANCE_API_KEY` / `BINANCE_API_SECRET`은 설정되어 있지 않습니다. 계정 endpoint는 항상
   `api.binance.com`을 사용하므로 PRIVATE-02 / PRIVATE-03 완료에는 Binance 사용이 허용되는
   실행 환경에서 안전하게 주입한 read-only HMAC 키가 필요합니다. 지역 제한을 우회하지 않습니다.
3. Unit Test와 패키지 빌드는 개발 준비를 검증하지만 실제 Private 인증 성공을 대신하지 않습니다.
   키는 채팅이나 Git에 넣지 말고 안전한 로컬 `.env` / 환경변수로 설정한 후
   `python -m trading_system.cli account`와 `pytest -m integration --live-account`를 실행하세요.
4. 클라우드 환경 설정 초안에 `install_script`, `start_skill`, Binance 두 호스트의 네트워크 허용 목록을
   저장했습니다. 설치 스크립트는 현재 머신에서 재실행했고 CLI 준비 절차도 검증했습니다.
   초안 저장은 게시나 새 작업 복원 검증을 의미하지 않습니다. 재사용하려면 환경 설정을 검토·저장하고
   환경을 게시하세요. 실제 Secret 값이나 proxy secret placeholder를 이 초안에 추가하지 않았습니다.
5. 다음 Cycle에 진입하기 전 PRIVATE-02 / PRIVATE-03의 실제 검증을 완료하세요.
   WebSocket / DB / Trading / Signal Engine은 DEV-M01에 포함하지 않았습니다.

GitHub Actions 워크플로는 모의 응답 테스트와 lint를 수행하도록 작성했습니다.
GitHub에서 해당 workflow가 실제 실행되어 성공했는지는 이 로컬 검증 기록에 포함하지 않습니다.
