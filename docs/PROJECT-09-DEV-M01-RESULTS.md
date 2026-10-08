# 프로젝트 09 전달용 — DEV-M01 결과 정리

작성일: 2026-10-08 (Asia/Seoul)
프로젝트: AI Multi-Strategy Investment System
Cycle: DEV-M01 — Binance Connectivity MVP / Private Account Verification

## 1. 최종 결론

**Windows 로컬 환경에서 공개 시장 데이터 조회와 실제 Binance Spot 계정 인증·잔액 파싱을
지원하는 Read-only Connectivity MVP 검증이 완료됐다.**

공개 API는 클라우드에서 직접 실행해 검증했다. Private Account는 사용자가 Windows 로컬 PC에
연결된 Codex에서 실행한 결과를 보고했으며, 그 결과를 저장소 검증 문서에 반영했다.
이 클라우드 세션에서 Windows 실행을 직접 재현한 것은 아니다.

**GitHub-hosted runner의 Private Account 검증은 HTTP 451 접근 제한으로 미완료다.**
Windows 로컬 성공과 GitHub Actions 성공을 구분한다. 실제 주문 기능은 구현하지 않았다.

## 2. Source of Truth와 검증 기준

- GitHub: https://github.com/NAM-GOM/ai-multi-strategy-investment-system
- 작업 브랜치: `dev-m01-binance-connectivity`
- Windows 실검증 commit: `8be24eab7a7eeee8acb6bfb448f74d1e1e81eba0`
- Windows 결과 반영 문서 commit: `053319b617c4e4fa720f9affba82166e2428bcc4`
- Python: **3.14.7**, 지원 범위 3.14.x
- 환경 / 의존성 기준: `.python-version`, `pyproject.toml`, `uv.lock`
- 상세 문서: `README.md`, `docs/DEV-M01-validation.md`

PR의 병합 여부나 GitHub Actions 성공을 로컬 검증 결과만으로 추정하지 않는다.

## 3. 구현 범위

### Public Market Data

- API Key 없이 BTCUSDT / ETHUSDT / SOLUSDT 현재 가격 조회
- BTCUSDT 최근 4시간봉 10개: open_time / open / high / low / close / volume / close_time
- 시간은 UTC로 유지하며 CLI에서 ISO-8601로 표시
- 마지막 캔들은 진행 중일 수 있음
- BTCUSDT Order Book Bid / Ask 각각 상위 10개
- best_bid / best_ask / spread / spread_percent
- `perf_counter()` 기반 REST application round-trip latency
- latency는 Exchange matching latency가 아님

### Private Account

- 환경변수 `BINANCE_API_KEY`, `BINANCE_API_SECRET` 및 로컬 `.env` 지원
- timestamp / recvWindow / HMAC SHA-256 / X-MBX-APIKEY 처리
- 서버 시간 조회로 timestamp 보정, recvWindow 기본 5000ms
- USDT / BTC / ETH / SOL free / locked / total 파싱
- 값은 Decimal, `total = free + locked`
- 잔액 0 또는 응답에 없는 자산도 0으로 정상 처리
- 키가 없거나 한쪽만 설정되면 안전하게 skip
- timeout / connection / HTTP / Binance error / signature / timestamp / 429 / 418 / 451 구분

### CLI와 로그

- `public`, `account`, `all` 명령 지원
- 로컬 Account CLI는 free / locked / total을 표시
- Console 및 `logs/app.log`에 안전한 성공·실패·endpoint·symbol·latency 기록
- credential redaction 및 httpx/httpcore verbose 로그 억제

## 4. Architecture와 Endpoint

```text
src/trading_system/
  config.py
  logging_config.py
  cli.py
  binance/
    client.py        # GET-only REST, 서명, 오류, latency
    public.py        # 가격 / 캔들 / 호가 모델과 파싱
    account.py       # AccountAPI / Balance
    connectivity.py  # 키 없는 Account host preflight
tests/
.github/workflows/
  tests.yml
  live-account.yml
```

| Method | Endpoint | 용도 |
| --- | --- | --- |
| GET | `/api/v3/ticker/price` | 가격 |
| GET | `/api/v3/klines` | 4H 캔들 10개 |
| GET | `/api/v3/depth` | 상위 10개 호가 |
| GET | `/api/v3/time` | 시간 동기화 / 호스트 사전 진단 |
| GET | `/api/v3/account` | 실제 계정 인증과 잔액 |

Public 기본 호스트: `https://data-api.binance.vision`
Account 호스트: `https://api.binance.com`
Private endpoint는 GET `/api/v3/account` 하나뿐이다.

## 5. 검증 결과

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| PUBLIC-01: 가격 3종 | PASS | 클라우드에서 실제 공개 API 실행 |
| PUBLIC-02: BTCUSDT 4H 캔들 10개 | PASS | 실제 공개 API 실행 |
| PUBLIC-03: BTCUSDT Order Book | PASS | 실제 Bid / Ask 각각 10개 |
| PUBLIC-04: REST latency | PASS | 실제 출력 확인 |
| PRIVATE-01: 키 없는 안전한 skip | PASS | CLI / 모의 테스트 |
| PRIVATE-02: 실제 인증 | **Windows 로컬 실검증 PASS** | 사용자 제공 결과, Account CLI exit 0 |
| PRIVATE-03: 실제 잔액 파싱 | **Windows 로컬 실검증 PASS** | 사용자 제공 live account / Decimal 합계 검증 |
| GitHub-hosted Private 검증 | **BLOCKED_RUNNER_ACCESS** | 실제 HTTP 451 |
| Windows Unit Test | PASS | 102 passed, 6 deselected |
| Windows Live Account Test | PASS | 1 passed, 5 Public tests skipped |
| Windows Ruff / format | PASS | 사용자 제공 결과 |
| 클라우드 기본 pytest | PASS | 102 passed, 6 skipped |
| GitHub 진단 Unit Test | PASS | 102 passed, 6 deselected |
| workflow actionlint | PASS | 공식 release checksum 확인 후 검증 |
| Secret exposure check | PASS | 모의 노출 차단 테스트 및 사용자 제공 로컬 로그 검사 |

Windows 자산 상태는 **USDT: PRESENT / BTC: ZERO / ETH: ZERO / SOL: ZERO**였다.
실제 보유 수량은 이 전달 문서에 포함하지 않는다.
로컬 실행 보고에는 HTTP 오류가 없었고 Git 변경사항도 없었다.

## 6. GitHub Actions 실패 원인과 적용한 조치

최초 수동 계정 검증 run:
https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37704805818

- Unit 94개 통과
- GET `/api/v3/account` → HTTP 451
- 인증 / 잔액 NOT_VERIFIED
- Secret 노출 검사 PASS

키 없는 추가 진단 run:
https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37705346650

- GET `/api/v3/time`도 HTTP 451 / `restricted_location`
- Binance credentials 미사용, 인증 NOT_TESTED
- 인증 이전의 지역 / 이용 자격 접근 제한임을 확인
- runner의 정확한 출구 국가나 사용자의 이용 자격은 이 증거로 확정하지 않음
- 이 실패를 API Key / signature / timestamp 오류로 판정하지 않음

적용한 조치:

- 기본 `github-hosted-diagnostic` 모드는 공개 사전 진단만 실행하고 Secrets를 주입하지 않음
- `self-hosted` 모드는 `[self-hosted, linux, x64, binance-readonly]`에서 실제 계정 검증
- 사전 진단 성공 후에만 Private 테스트에 Secrets 주입
- HTTP 451 원문 대신 안전한 고정 이유 코드 표시
- 지역 제한 우회, VPN / 프록시 / IP 회전, API Key Permission 변경은 구현하지 않음

현재 사용할 서버는 없다는 사용자 답변을 받았다.
GitHub 인증은 workflow 실행이 가능하지만 runner 목록 조회는 권한 부족으로 거절됐다.
runner 등록·설치 완료나 self-hosted 인증 성공은 확인되지 않았다.
Windows 직접 실행은 성공했으나 현재 workflow의 Linux x64 label은 Windows runner를 선택하지 않는다.

## 7. Security와 구현하지 않은 기능

- API Key / Secret을 소스·YAML·예제·보고서에 넣지 않음
- `.env`와 로그·캐시·가상환경은 Git 제외
- signature / signed URL / HTTP header / 전체 account JSON을 기본 Actions 로그에 출력하지 않음
- Actions에는 Authentication 및 PRESENT / ZERO / NOT_VERIFIED 상태만 출력
- `.env` 없이 Repository Secrets의 환경변수 주입으로 동작
- 실제 계정 Test는 명시적 `--live-account` 옵션에서만 수행
- 기존 `tests.yml`은 일반 push / PR용 Unit / Mock / Lint이며 Binance Secrets 미주입
- TLS 검증과 의존성 artifact 검증 유지
- Trading / Order / Cancel / Withdrawal / Transfer / Futures / Margin / 권한 변경 기능 없음
- WebSocket / Database / Signal Engine / 전략 실행 / 백테스트 / 모의 투자 미구현

## 8. Windows 로컬 재실행

저장소 루트의 PowerShell에서:

```powershell
uv python install 3.14.7
uv sync --frozen --group dev
uv run --frozen python -m trading_system.binance.connectivity
# preflight 성공 및 로컬 read-only HMAC credentials 설정 후
uv run --frozen python -m trading_system.cli account
uv run --frozen pytest -m 'not integration'
uv run --frozen pytest -m integration --live-account -s --tb=no --show-capture=no
uv run --frozen ruff check .
uv run --frozen ruff format --check .
```

Repository Secrets는 로컬에 자동 전달되지 않는다. credentials는 로컬 `.env` 또는 환경변수에
안전하게 설정하며 채팅이나 Git에 넣지 않는다. 직접 실행에는 GitHub runner 등록이 필요 없다.

## 9. 프로젝트 09에서 이어갈 판단

1. **DEV-M01 핵심 Read-only Connectivity는 Windows 로컬 실검증 완료**로 정리할 수 있다.
2. **GitHub Actions Private 자동 검증은 별도 미완료 항목**으로 남긴다.
   적격 실행 머신의 runner 등록과 실제 성공 run을 확인한 뒤에만 Actions 기준 PASS로 변경한다.
3. 향후 Windows self-hosted 자동화를 원하면 현재 Linux 전용 runner 선택의 확장 작업이 필요하다.
   이 문서 작성 시점에는 확장하지 않았다.
4. 다음 Cycle의 범위는 프로젝트 09 채팅에서 별도로 결정한다.
   이 결과만으로 Trading 기능 도입, 권한 변경, DB / WebSocket / Signal Engine 구현이
   승인되었다고 해석하지 않는다.

이 문서를 프로젝트 09 채팅에 첨부하거나 전체 내용을 붙여 넣어 작업 맥락을 이어갈 수 있다.
