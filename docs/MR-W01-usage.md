# MR-W01 실행과 검증

`research/mr-w01-baseline`은 DEV-M04 `574eb63597e42724a6450abd0928458ae72c4b88`을
기준으로 한 독립 연구 브랜치다. 기존 Trend, Frozen Observer, DEV-M02~M04 파일은 수정하지 않는다.
`BaseStrategy.generate()`를 상속하지만 기존 Trend 엔진의 ATR 3배·비례 배분을 변경하지 않고
MR 전용 2.5배 Stop·BTC→ETH→SOL 실행 경로를 사용한다. 네트워크·계정·실제 주문을 호출하지 않는다.

## 실행

저장소 루트에서 Python 3.14.7과 기존 uv.lock을 사용한다.

```bash
uv python install 3.14.7
uv sync --frozen --group dev
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen --with matplotlib==3.10.8 python -m trading_system.research.mr_w01.run --output artifacts/mr-w01-local
```

차트용 Matplotlib은 위 명령의 임시 환경에만 추가한다. 애플리케이션 pyproject/lockfile은
변경하지 않는다. Matplotlib의 전이 의존성은 프로젝트 lock 대상이 아니며 차트 렌더링까지의
byte 단위 재현성은 주장하지 않는다. 금융 계산은 기존 고정 pandas/numpy로 실행한다.

읽기 전용 home인 클라우드에서는 명령 앞에 다음 환경값을 붙인다.

```bash
MPLCONFIGDIR=/tmp/mr-w01-mpl XDG_CACHE_HOME=/tmp/mr-w01-cache UV_CACHE_DIR=/workspace/.cache/uv UV_PYTHON_INSTALL_DIR=/workspace/.python uv run --frozen --with matplotlib==3.10.8 python -m trading_system.research.mr_w01.run --output /tmp/mr-w01-local
```

출력 디렉터리는 새 경로여야 한다. 기존 보고서를 덮어쓰거나 삭제하지 않는다.
Preflight 실패 시 manifest는 STOP이며 공식 완료 결과로 사용할 수 없다.
정식 결과는 [MR-W01_report.md](../artifacts/mr-w01/MR-W01_report.md),
gate 근거는 [MR-W01_preflight.md](../artifacts/mr-w01/MR-W01_preflight.md),
실행·코드·데이터·산출물 해시는 [MR-W01_manifest.json](../artifacts/mr-w01/MR-W01_manifest.json)에 있다.

## 이번 검증

- 변경 전: 283 passed / 8 skipped. 변경 후: 307 passed / 8 skipped.
- P01~P10: 24 passed. Ruff check / format: PASS.
- 별도 프로세스 재실행: summary/trades/signals/equity CSV SHA-256 4/4 동일.
- 저장 CSV 재조회: 수익률·거래 손익·수수료·자산 기여·각 시점 Equity 정합성 PASS.
- 기존 109파일 보존, W03 lock과 historical clean CSV 해시 PASS.
- Binance live API, 계정 조회, W04 Clock 활성화는 수행하지 않았다.
- Windows 로컬 실행은 이번 환경에서 미검증이다. GitHub Windows CI는 별도 결과로 기록한다.

원본 raw API pages는 현재 저장소에 없다. W01 manifest/clean CSV의 동일성은 검증했지만
원본 raw page 재검증으로 표기하지 않는다. 자산별 summary는 공동 Portfolio 기여도이며
각 자산을 별도 초기 자본으로 운용한 결과가 아니다. 상세 비용과 통계의 해석은 보고서에 명시한다.

MR-W01 완료는 코드·데이터·산출물 정합성 완료이며, 세 후보의 수익성 승인이나 실거래 승인이 아니다.
