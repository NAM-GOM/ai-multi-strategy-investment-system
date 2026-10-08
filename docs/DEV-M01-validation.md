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
| PRIVATE-02 | LOCAL_LIVE_PASS / GHA_BLOCKED | 사용자 제공 Windows 실검증: 인증 PASS. GitHub-hosted HTTP 451은 유지 |
| PRIVATE-03 | LOCAL_LIVE_PASS / GHA_BLOCKED | 사용자 제공 Windows 실검증: 네 자산 파싱·Decimal·합계 PASS. Actions 실검증은 미완료 |
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
2. 최초 클라우드 검증에서는 실제 `BINANCE_API_KEY` / `BINANCE_API_SECRET`이 설정되어 있지 않았습니다.
   이후 사용자가 Repository Secrets 등록 완료를 알렸으며, 새로운 수동 workflow는 두 값을 GitHub에서
   주입하도록 구성했습니다. Secrets 값을 열람하거나 현재 클라우드로 가져오지 않았습니다.
   계정 endpoint는 항상 `api.binance.com`을 사용하며 지역 제한을 우회하지 않습니다.
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

## Private Account Verification 확장 — 2026-10-07

변경 파일:

- 추가: `.github/workflows/live-account.yml`, `tests/test_live_account_verification.py`
- 수정: `tests/test_integration.py`, `README.md`, `docs/DEV-M01-validation.md`
- 기존 `tests.yml`, REST Client / HMAC signing / AccountAPI / Balance / Config / 로컬 CLI는 유지

새 workflow는 `workflow_dispatch`만 사용하고 권한은 `contents: read`입니다.
checkout → setup-uv → Python 3.14.7 → `uv sync --frozen --group dev` →
Unit Test → opt-in live account integration 순서로 실행합니다.
Repository Secrets는 마지막 단계에서만 환경변수로 주입합니다. `.env`는 생성하지 않습니다.
일반 push / PR CI는 Secrets나 Private API 호출을 추가하지 않았습니다.

실제 호출은 기존 GET `/api/v3/time` 동기화와 서명된 GET `/api/v3/account`를 재사용합니다.
추가 Private endpoint는 없습니다. 네 자산의 free / locked / total Decimal 모델을 검증하고
자산 누락은 0으로 처리합니다. Actions에는 인증과 자산별 PRESENT / ZERO만 표시합니다.
실패 시 NOT_VERIFIED, 키 미설정 시 SKIPPED를 표시합니다.

앱 로그를 먼저 수집해 Secret / signature / URL / header / account JSON 패턴을 검사하며,
노출 의심 시 원문을 폐기하고 FAIL 요약만 출력합니다. 실제 잔액 숫자, account JSON 전체,
credential, signed URL, 헤더, traceback은 기본 Actions 출력에 넣지 않습니다.
이 exposure check는 수집한 앱 로그와 출력 요약에 대한 검사입니다.
HTTP 451은 `http_4xx HTTP=451`과 runner/environment 접근 불가 메시지로 구별합니다.
나머지 BinanceError 분류를 유지하며 자동 재시도 / 지역 제한 우회는 추가하지 않았습니다.

| 항목 | 현재 검증 결과 |
| --- | --- |
| 기본 `pytest` | 94 passed, 6 skipped (live 미선택) |
| workflow Unit 명령 | 94 passed, 6 deselected |
| workflow live 명령, 현재 머신 키 없음 | 6 skipped. Private 인증 성공을 뜻하지 않음 |
| `ruff check .` / `ruff format --check .` | PASS |
| actionlint 1.7.7, tests.yml / live-account.yml | PASS (공식 release checksum 확인 후 사용) |
| 기존 Unit / Mock tests | 모두 PASS |
| 새 검증 경로 | 성공 / ZERO / 자산 누락 / 오류 분류 / HTTP 451 / skip / 노출 차단 모의 검증 PASS |
| GHA-01 / GHA-02 / GHA-03 / GHA-04 | 구성 검증 PASS. 수동 trigger, Secrets 단계 제한, 일반 CI 미변경 |
| SECURITY-05 / SECURITY-06 | 모의 출력·노출 차단 검사 PASS. 실제 Actions run은 아직 미실행 |
| SECURITY-07 | PASS. Private endpoint 추가 없음, Trading / Withdrawal 미구현 |
| TEST-02 / TEST-03 / DOC-02 | PASS. Unit 통과, 명시적 live 옵션, 사용 절차 문서화 |
| PRIVATE-02 / PRIVATE-03 | **BLOCKED_RUNNER_ACCESS**. 이후 실제 run에서 HTTP 451 확인. 최신 진단은 아래 참조 |

GitHub Actions의 수동 실행 UI는 workflow 파일이 기본 브랜치(`main`)에 있어야 표시됩니다.
현재 작업 브랜치 변경사항을 PR로 main에 병합한 뒤, README의
**Actions → DEV-M01 Live Binance Account Check → Run workflow → dev-m01-binance-connectivity → Run workflow**
절차로 사용자가 실행하세요. 이번 작업에서는 live workflow를 자동으로 dispatch하지 않았습니다.
성공 run의 URL / commit / 결과를 확인한 뒤에만 PRIVATE-02 / PRIVATE-03을 PASS로 갱신하세요.

## HTTP 451 원인 진단 및 실행 경로 수정 — 2026-10-08

실제 최초 Account run:
[37704805818](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37704805818).
Unit 94개가 통과한 뒤 GET `/api/v3/account`에서 HTTP 451로 실패했습니다.
API가 반환한 인증 성공이나 잔액은 없습니다.

이후 키 없는 GitHub-hosted 진단 run:
[37705346650](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37705346650),
실행 commit `ef4dd4fd4be83f1d815582594369d023dfacd07f`.

```text
102 passed, 6 deselected
Probe endpoint: GET /api/v3/time
Credentials: NOT USED
Authentication: NOT_TESTED
Account host connectivity: FAIL
Error: http_4xx endpoint=/api/v3/time HTTP=451 Restriction=restricted_location
Access restriction reason: restricted_location
```

이 run에서도 **인증 전 공개 endpoint가 지역 / 이용 자격 제한으로 거절됨**을 확인했습니다.
Secret을 주입하지 않았고 live-account-check job은 skip했습니다.
현재 클라우드의 키 없는 `/api/v3/time`, `/api/v3/ping` 응답에서도 restricted location과 eligibility
안내가 확인되었습니다. 응답 원문은 로그·보고서에 넣지 않고 고정된 이유 코드만 기록했습니다.
runner API 정보는 GitHub-hosted `ubuntu-latest`를 보여주며, 정확한 출구 국가나 사용자 이용 자격은
현재 증거로 확정할 수 없습니다. 계정 키·서명·timestamp 오류로 판정하지 않습니다.

적용한 변경:

- `BinanceError`의 기존 오류 분류를 유지하고 451의 `restriction_reason`을 안전한 고정 문자열로 추가
- `trading_system.binance.connectivity`: 기존 GET Client로 계정 호스트를 검사, `.env` / credential 미사용
- `live-account.yml`: 기본 `github-hosted-diagnostic` 모드는 공개 preflight만 수행
- 실제 검증 모드 `self-hosted`는 `[self-hosted, linux, x64, binance-readonly]`에서만 수행
- self-hosted 검증에서도 키 없는 preflight 성공 후에만 Secrets 주입 및 기존 계정 integration 실행
- `.github/actionlint.yaml`: 사용자 지정 runner label 선언. lint 규칙을 비활성화하지 않음
- `tests/test_connectivity.py`: 키 미사용 / 451 이유 분류 / timeout 외 응답 오류 / 0 credential 출력 검증
- README에 진단 모드, runner 등록, 해결의 외부 조건과 제한을 명시

검증: 기본 pytest **102 passed, 6 skipped**, 실제 GitHub 진단의 Unit **102 passed**,
ruff / format / actionlint 통과. 공식 actionlint release checksum을 확인했습니다.
일반 `tests.yml`은 변경하지 않았습니다. 주문 / 출금 / 이체 / 추가 Private endpoint도 없습니다.

실제 해결에는 **사용자와 실행 환경 모두 Binance 이용 자격을 충족하는 신뢰할 수 있는 머신**이
필요합니다. 기존 제한을 우회할 목적으로 다른 지역의 서버를 선택하거나 VPN / 프록시 / IP 회전을
사용하지 않습니다. 사용자가 현재 사용할 서버가 없다고 답변했으며, 현재 GitHub 인증으로
runner 목록 조회도 `Resource not accessible by integration` (HTTP 403)입니다.
runner를 설치·등록하거나 live 계정 검증에 성공했다고 보고하지 않습니다.

적격 환경의 Linux x64 PC도 self-hosted runner가 될 수 있습니다. 실제 머신을 준비한 뒤
GitHub Settings → Actions → Runners에서 `binance-readonly` label로 등록하고 preflight를 통과하면,
수동 workflow의 `self-hosted` 모드로 계정 검증을 재개할 수 있습니다.
이 진단 시점의 PRIVATE-02 / PRIVATE-03은 **BLOCKED_RUNNER_ACCESS**였습니다.
이후 Windows 로컬 실검증 결과는 아래에 별도로 기록합니다.

## Windows 로컬 실검증 결과 — 보고 접수 2026-10-08

사용자가 Windows PC에 연결된 Codex에서 실행한 결과 요약을 제공했습니다.
이 기록의 근거는 사용자 제공 보고서이며, 이 클라우드 세션에서 Windows 명령을 직접 재실행한 것은
아닙니다. Secret이나 실제 잔액 수량을 요청·수집하지 않았습니다.

| 항목 | 사용자 제공 결과 |
| --- | --- |
| Python | 3.14.7 |
| Branch / Commit | `dev-m01-binance-connectivity` / `8be24eab7a7eeee8acb6bfb448f74d1e1e81eba0` |
| Account host connectivity | PASS, exit 0 |
| Account CLI authentication | PASS, exit 0 |
| USDT / BTC / ETH / SOL | PRESENT / ZERO / ZERO / ZERO |
| Decimal / total consistency | PASS |
| Unit Test | 102 passed, 6 deselected |
| Live account integration | 1 passed, 5 Public tests skipped |
| Ruff check / format | PASS |
| Error / HTTP error | 없음 |
| Secret exposure check | PASS, 출력 및 앱 로그 검사 |
| 로컬 Git changes | 없음. 소스·테스트·의존성·lockfile 보존 |
| 로컬 Remaining action | 없음 |

**PRIVATE-02 / PRIVATE-03: Windows 로컬 실검증 PASS (사용자 보고 기준).**
이 결과로 해당 Windows 실행 환경에서 기존 read-only Client의 실제 HMAC 인증과 네 자산의 잔액
파싱이 성공했음을 기록합니다. 키 없는 public 데이터 검증과 별개로 private 실검증 근거가 확보됐습니다.

**GitHub Actions: 기존 GitHub-hosted HTTP 451 / BLOCKED_RUNNER_ACCESS 유지.**
Windows 직접 실행은 GitHub-hosted 또는 self-hosted workflow의 성공을 의미하지 않습니다.
따라서 GitHub Actions PRIVATE-02 / PRIVATE-03을 PASS로 변경하지 않습니다.
GitHub 자동 검증을 완료하려면 적격 runner를 등록하고 실제 workflow 성공 run을 확인해야 합니다.
현재 self-hosted workflow label은 Linux x64용이며 Windows runner 등록·실행은 검증하지 않았습니다.
