# DEV-E01 validation

Date: 2026-10-10 (Asia/Seoul). Issue #5.
Baseline: `574eb63597e42724a6450abd0928458ae72c4b88`.

**Final gate: DEV-E01_HOLD** until actual explicitly authorized Testnet execution
and reconciliation are observed. Offline tests cannot establish the live trading gate.

**Live status: TESTNET_LIVE_NOT_TESTED.** No dedicated Testnet credentials were
provided or used; no Testnet HTTP request or virtual order was executed during this
development session. No production account API request or order was sent.

## Windows live Testnet report

| Step | Evidence / result |
| --- | --- |
| Server connection | TESTNET_LIVE_NOT_TESTED |
| Dedicated Testnet key authentication | TESTNET_LIVE_NOT_TESTED |
| Virtual balance and exchangeInfo | TESTNET_LIVE_NOT_TESTED |
| POST /api/v3/order/test | TESTNET_LIVE_NOT_TESTED |
| Preflight report and separate user approval | Pending |
| One small virtual LIMIT order | TESTNET_LIVE_NOT_TESTED |
| Actual exchange order ID/status | Not observed |
| Actual fill or cancellation | Not observed; no fabricated FILLED status |
| Fill quantity, fee and balance comparison | TESTNET_LIVE_NOT_TESTED |
| Restart and retained live journal | TESTNET_LIVE_NOT_TESTED |
| HTTP 451 / geographical restriction | Not probed; no environment-block claim |

## Offline validation

Windows uses Python 3.14.7 and the already installed locked dependencies from the
M04 virtual environment, with PYTHONPATH pointed only at the E01 checkout. Tests
use HTTPX MockTransport and isolated SQLite files. The existing autouse fixture
rejects real HTTP in unit tests; no live flags are enabled.

Windows results: full pytest **362 passed, 8 skipped** (53.65 seconds), followed
by one additional CLI error-journal failure test and the final verification below.
Final changed-module + freeze subset: **80 passed** (2.01 seconds); repository
Ruff check and format check both pass after the final CLI change.
All eight skips are opt-in legacy live integration tests; no actual API request
was made. Ruff check and repository format check passed. The portable
`DEV-E01-freeze-manifest.json` checks **61** existing source/W03 files against
the baseline commit (LF-normalized SHA-256), including the existing GET-only
client, original CLI, data collection, persistence and Observer code.
Initial test setup encountered Windows sandbox temporary-directory permissions;
the final run uses a fresh workspace-local `data/` test directory. This is not a
Testnet connectivity result.

The existing push/PR workflow retains ubuntu-latest/windows-latest pytest and
Ruff/format checks with no Testnet credentials or live execution flags. A Linux
result will only be claimed after the remote CI run is observed.

## Promotion criteria

- DEV-E01_PASS: offline Windows/Linux checks and freeze verification pass, and all
  live gates above have actual recorded evidence.
- DEV-E01_PASS_WITH_FLAGS: actual live trading gates pass but documented noncritical
  limitations remain; no unknown execution, reset suspicion or accounting gap.
- DEV-E01_HOLD: missing live evidence, unavailable platform checks, environment block,
  unresolved orders/reset or reconciliation discrepancy.
- DEV-E01_REJECTED: any production order route, credential fallback, freeze violation
  or failed safety requirement.

LIMIT/GTC-only is the initial supported subset. MARKET_LOT_SIZE does not apply to
LIMIT orders; MARKET orders are refused. A Testnet fill is never W04 Formal Forward
performance. T2/T3 remain W03_HOLD and the W04 official start/ledger stay unchanged.
