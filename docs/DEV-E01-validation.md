# DEV-E01 validation

The original manual-adapter evidence below is retained. The **current integrated
M04 extension** and its acceptance matrix are recorded at the end of this document.

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

Local Windows results: full pytest **362 passed, 8 skipped** (53.65 seconds), then
the final changed-module + freeze subset **80 passed** (2.01 seconds) after adding
one CLI error-journal failure test. Repository Ruff check and format check pass.
Final complete suites on both CI platforms: **363 passed, 8 skipped**.
All eight skips are opt-in legacy live integration tests; no actual API request
was made. Ruff check and repository format check passed. The portable
`DEV-E01-freeze-manifest.json` checks **61** existing source/W03 files against
the baseline commit (LF-normalized SHA-256), including the existing GET-only
client, original CLI, data collection, persistence and Observer code.
Initial test setup encountered Windows sandbox temporary-directory permissions;
the final run uses a fresh workspace-local `data/` test directory. This is not a
Testnet connectivity result.

The existing push/PR workflow retains ubuntu-latest/windows-latest pytest and
Ruff/format checks with no Testnet credentials or live execution flags.

## Observed Windows/Linux CI evidence

Runtime/test code commit: `0ef79dd9108cfe4b681470ec06340bc750779a78`.
[GitHub Actions run 38038789151](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/38038789151)
completed successfully on both platforms. Job steps and decoded logs were read
after completion; the following are observed results, not projected CI outcomes.
Subsequent validation-report edits do not change runtime/test code.

| Platform | pytest | Ruff | Format | Job |
| --- | --- | --- | --- | --- |
| ubuntu-latest, Python 3.14.7 | 363 passed, 8 skipped; 35.88 s | PASS | PASS | [114174712660](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/38038789151/job/114174712660) |
| windows-latest, Python 3.14.7 | 363 passed, 8 skipped; 60.62 s | PASS | PASS | [114174712741](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/38038789151/job/114174712741) |

Coverage includes exact network policy and production-order rejection, isolated
credential loading, HMAC, TLS/redirect policy, Decimal/filter sizing, balances,
local/exchange limits, dual unlock/preflight, all supported order statuses, actual
cancel response alias semantics, timeout/query and lost cancellation ACK, durable
reservation/ACK failure recovery, separate SQLite connections and a fresh CLI
process, trade pagination/dedup/fee conflict, resets, reconciliation rollback,
DB fail-closed behavior, persistent kill switch and all M01–M04 regression tests.

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

## Integrated M04 extension — current report (2026-10-10 UTC)

**Classification: DEV-E01_HOLD.** Phase A offline implementation is verified;
actual Testnet connection/test request/order/fills and T1 activation remain untested.
No dedicated Testnet credentials were provided, no Testnet HTTP/WS request was made,
no Production account request/order was sent, and automation was not enabled.

### FACT — implemented and reviewable

- Audited latest M04 `574eb635`, E01 `9612b240`, Issue #5, M01–M04/W03 sources,
  SignalDecision/Observer schema, MarketRepository and existing stacked PRs #3/#4/#6.
  Official Binance Testnet general-info and REST specifications were read before
  extending the code. Existing verified Testnet lifecycle is reused.
- Added all eleven requested `execution/` modules. M04 is read through immutable
  stored decisions; deterministic regeneration and source/input/batch hashes,
  original LIVE classification, fresh closed 4H next-bar eligibility, startup
  watermark and durable receipt dedup guard the route. T1 alone is enabled in code;
  T2/T3 stay shadow/W03_HOLD. No M04 source or DB schema change.
- Added Python Frozen sizing with independent Testnet ceilings, quote/reference
  separation and divergence/freshness gates, strategy allocations/ownership,
  reservations, fee-aware PnL, actual average fills and initial 3 ATR stop intents.
- Added persistent A/B/C/D evidence, intent-bound manual review approval, default
  disabled one-cycle T1 automation and real-transport CI mutation rejection.
- Reused typed/validated exact-host HMAC transport, read-only account preflight,
  recent order/test, persist-before-submit, stable exchange identities, no blind
  timeout retries, kill switch, reset detection and account/fill reconciliation.
  Integrated configuration rejects explicit reuse of configured Production values;
  remote error-code strings are rejected before CLI output. No secrets were read,
  printed or committed.
- Added separate strategy projection verification: mismatches, unattributed fills,
  unsupported fee-asset attribution and account coverage failures block new orders.
  Manual verification fills become an acknowledged non-strategy baseline; resets
  isolate allocation/gates/PnL while preserving the kill switch.
- Added integrated status/balances/order check/submit/status/cancel/reconcile,
  router status/dry-run/run, allocation and kill-switch CLI. Default network OFF.
  Windows-compatible arguments use `python -m trading_system.execution.cli`.

### RESULT — observed offline verification

The first complete integrated regression after implementation passed **406 tests,
8 opt-in live skips** in **129.72 seconds** on Linux / Python 3.14.7. A subsequent
error-response hardening test and status reporting extension are included in the
final verification recorded below; the earlier count is not presented as a test
of later source changes. Security hardening + existing Testnet subset: **80 passed**.
Repository Ruff and format checks passed; the protected 61-file freeze test passed.
All legacy M01–M04 tests remain included. Existing dependency lock and CI workflow
remain unchanged; normal push/PR CI uses Ubuntu/Windows and no live flags/secrets.

Final local full regression before the last transport-boundary guard: **407 passed,
8 skipped, 128.83 seconds**, Python 3.14.7. After that guard, the complete new
integration subset: **45 passed, 102.60 seconds**; Ruff check and format check PASS.
This distinction preserves the tested source scope. The current full suite contains
416 tests (408 offline tests and eight opt-in live skips).
Current integration CI: PENDING_CI_RESULT (the 363-test evidence above belongs to
the earlier manual adapter and does not establish the new integration's CI).

The new integration tests use actual M03/M04 SQLite, actual Frozen computation and
HTTPX MockTransport. The fixture creates an isolated, deterministic SOL T1 EMA
crossover, not a historical or live account observation. Tests exercise dry-run,
manual review/test/cancel evidence, gated T1 submission, partial/final fills,
actual mock fee/balance changes, weighted entry/3 ATR stop, realized PnL, recovery
and global receipt dedup. All mock gate rows exist only in temporary databases.

Security/failure coverage includes: Production host/path rejection, key isolation/
explicit reuse rejection, missing keys, HMAC and invalid error strings, insufficient
balance, quantity/filter/precision/minimum ceilings, NO_ACTION/shadow/backfill/Formal
rejection, corrupt batch/record/manifest/input, M04 hold/stop, stale/future data,
spread/divergence/quote age, duplicate submit/signal, timeout/unknown state/restart,
partial fills, cancel aliases/failure, DB commit failure/crash recovery, reset,
external activity, rate limits, HTTP 403/451 and persistent kill switch. The existing
freeze/reproduction/clock tests verify unchanged W03/W04 and all prior modules.

An initial sandbox-only full-suite attempt stalled in the unchanged M03 collector
because its asyncio thread wake-up sockets were restricted. The same 13 collector
tests passed with required execution permissions, and the full suite was run with
that allowance. Unit-test HTTP guards/mock transports remained active; no live flag
was enabled. This was an execution sandbox issue, not a Binance connectivity result.

### Acceptance matrix

| Gate | Evidence and present status |
| --- | --- |
| EX-01 | FACT: exact Testnet host, TLS, allowlist, dedicated keys; offline security PASS |
| EX-02 | FACT: read-only M04 and exact Frozen/input regeneration; offline PASS |
| EX-03 | RESULT: startup/receipt/restart dedup and stale/backfill blocking PASS |
| EX-04 | RESULT: Frozen + execution caps/filter/balance/kill tests PASS |
| EX-05 | NOT_TESTED live order/test; mock success proves only code path |
| EX-06 | NOT_TESTED live virtual order; no exchange Order ID observed |
| EX-07 | RESULT mock fees/balances/PnL PASS; NOT_TESTED live fills/fees |
| EX-08 | RESULT SQLite durability/restart/reservation recovery PASS offline |
| EX-09 | RESULT UNKNOWN_EXECUTION query-before-replay and HOLD PASS offline |
| EX-10 | RESULT account/strategy/reset reconciliation PASS mock; NOT_TESTED live |
| EX-11 | RESULT gated T1 connection and protective exit PASS mock; NOT_TESTED activation |
| EX-12 | RESULT all M01–M04 regression retained and PASS locally |
| EX-13 | Current Windows/Linux integration CI: PENDING_CI_RESULT |
| EX-14 | RESULT Production GET-only sources unchanged; order URL structural tests PASS |
| EX-15 | RESULT 61 protected hashes and Frozen reproduction/clock tests PASS |

### NOT_TESTED / BLOCKED

- NOT_TESTED: real Testnet public connection, signed key authentication/balances,
  order/test, actual manual order ID/status, live fills/cancel/commission/balances,
  reset or rate-limit observation, live sleep/reboot/long-duration operation and
  automatic new T1 live signal execution. Actual HTTP 451 was not probed.
- BLOCKED: live Phases B/C need dedicated Spot Testnet HMAC credentials; D needs
  a separately approved concrete order; F needs successful A–E evidence and
  separate user activation. No live success is inferred from code/mock results.
- LIMIT/GTC-only and one-cycle execution are explicit initial limits. A Testnet
  bookTicker receipt timestamp does not prove upstream book age. GTC fills and
  local risk-stop handling are not identical to exact W03 modeled fills; downtime,
  minimum filters, fee attribution and the finite test budget can block exits.
  These execution limitations never change Frozen rules or W03/W04 classifications.

### Changed files and next steps

New files: `src/trading_system/execution/{__init__,config,models,testnet_client,
signal_router,risk_engine,order_manager,position_manager,reconciliation,
execution_store,cli}.py`, `tests/test_execution.py`, `docs/DEV-E01-architecture.md`.
Modified: `src/trading_system/testnet/store.py` (additive schema hook),
`src/trading_system/testnet/client.py` (safe error-code validation), README,
`.env.testnet.example`, design/validation documents. No verified artifact is deleted.

Users should first review the draft PR and this HOLD matrix, then issue/store
dedicated Testnet credentials locally. Follow README's B read-only -> C test request
-> separately approved D one small order -> E fills/cancel/account reconciliation
-> separately activated F new T1 signal sequence. Do not put keys in chat/PR/issues.
Keep M03/M04 running before Router startup; initial existing signals are never
traded. Offline assumptions are explicit and consumed signals cannot be promoted.
Automatic recurring scheduling and Demo Mode remain separate future work.
