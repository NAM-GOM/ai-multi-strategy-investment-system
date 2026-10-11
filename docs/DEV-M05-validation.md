# DEV-M05 validation and acceptance

Final operational disposition: **DEV-M05_HOLD**. NUC deployment and real TEST-02–07
have not been performed. No operational PASS is claimed from mock tests, a scheduled
4H close, prior E01 trade evidence or static systemd syntax validation.

## FACT — directly checked

- Repository: NAM-GOM/ai-multi-strategy-investment-system. Initial workspace was
  `work` at `59df61d` (main); explicitly fetched the M04 remote and created a new
  branch from `8c6bea8483437bd083a2793c70e4c8b49de197f9`.
- E01 `72a63e9329f0702fd90805f30cb342b0b6725fa0` is an ancestor. GitHub PR #7 is
  merged into dev-m04-strategy-observer with merge SHA 8c6bea8.
- NUC read-only status reports gomi-mini; project scope is isolated development,
  deployment_enabled=false, network_enabled=false, production_paths_blocked=true.
  No operational release/DB/environment file was read or modified.
- All 71 pre-existing src files and the original E01 freeze manifest (72 files total) are protected
  by the additive M05 manifest. Frozen source/input audit hash remains
  `8508a1bd15d68b04fe0428c298330961859af88a9a26d565d23fcdf1d93bd38c`.
- Collector/WS and Observer existing CLIs require finite positive duration. The
  new operational adapter calls M03 once with a finite maximum-float horizon and
  explicit stop event; it does not loop 24H CLI jobs or change protected sources.
- E01 DRY_RUN consumes real receipts/checkpoints when run against its real journal.
  M05 routes only in temporary Backup API copies and owns a separate preview cursor.

Prior 24H counts (320,867 messages / 18 live bars / 54 decisions / COMPLETED), NUC
Ubuntu/Python versions and E01 order 1507111 (0.00009000 BTC / 7.47824040 USDT /
83091.56 / reconciliation PASS) are **user-provided prior evidence**. They are not
newly verified M05 FACT or W04 strategy performance.

## RESULT — executed in the isolated Linux workspace

| Check | Observed result |
| --- | --- |
| Python/dependencies | CPython 3.14.7, uv sync --frozen --group dev PASS; uv.lock unchanged |
| Existing E01 + original freeze suite | 125 passed in 105.24s; MockTransport only |
| New M05 tests | 40 passed in 88.32s; SIMULATED_TEST, zero real HTTP/order calls |
| Full regression, final implementation | 472 passed, 8 opt-in live skips in 224.77s; final source 1cfbdce |
| Ruff check / format | PASS; 90 files formatted/checked (Frozen exclusion unchanged) |
| Offline preflight | PASS, 72 protected files, no network, both unlocks disabled |
| Shell syntax | bash -n both startup/preflight scripts PASS |
| systemd-analyze verify | PASS with local transformed executable paths; no installation/start/reboot |
| Git diff / source scope | No protected existing src edits; no force push or existing branch overwrite |
| GitHub Ubuntu / Windows CI | PASS both platforms: source 1cfbdce, run 38149014076; 472 passed / 8 skipped each |

CI evidence: [workflow 38149014076](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/38149014076),
implementation `1cfbdcecc3b6314563641cdb9bada52a73b02c39`. Ubuntu: 472 passed /
8 skipped in 232.24s; Windows: 472 passed / 8 skipped in 318.19s. Both Ruff and
format steps PASS; Ubuntu shell/systemd syntax step PASS. Normalized job/step
metadata is preserved in [DEV-M05-ci.json](DEV-M05-ci.json). Subsequent evidence-only
commits preserve the tested runtime, tests, lockfile and workflow; current PR Checks
are the source of truth for their own final-HEAD CI results.

The new tests cover real Frozen M04 calculation and actual SQLite transactions
against explicitly simulated WS candles and Mock Testnet. They verify:

- Nine validated T1/T2/T3 decisions, including NO_ACTION; six shadow policies and
  unchanged E01 <=20 USDT risk sizing under explicit **hypothetical** flat capital.
- No actual allocation: T1 candidates report STRATEGY_ALLOCATION_REQUIRED. Manual
  baseline remains outside T1, with original E01 logical DB dumps/receipts/checkpoints
  unchanged even when Preview risk approves in its expendable copy.
- One ingestion session across a virtual 25H/socket rotation. This fast-clock harness
  is a scheduler test, not 25H of wall-clock Binance reception or uptime evidence.
- Sequential nine-decision catch-up after stopped Observer; two missed bars retained
  as PRELAUNCH_STATE_BACKFILL, no skipped commits or retroactive LIVE classification.
- Missing candle hold, REST_RECOVERY provenance, saved live floor, WAL mode and
  unchanged checkpoints under SQLite writer lock.
- Heartbeat STOPPED/HOLD/stale/future timestamps, stale signals, kill switch,
  UNKNOWN_EXECUTION, dependency restart during risk evaluation and account mismatch.
- API 429/backoff failure retains cursor and original journal. GET-only read-only
  Testnet mock reconciliation; non-GET denied at both client and HTTP boundaries.
- Original journal UNKNOWN/SUBMITTING is checked before any online reconciliation;
  a temporary-copy recovery cannot clear real restart uncertainty.
- Persistent reconciliation/reset hold survives a new Bridge instance. Offline
  routing needs no bound account key and never claims account identity verification.
- OS writer lease denies duplicates and releases after a real child process crash.
  Two new runtime CLI processes preserve the preview cursor and original manual journal;
  old fixture signals are rejected as stale, not reported as real LIVE validation.

All actual Testnet POST order/test, POST order, DELETE/cancel and automated runs:
**0 calls**. Mock E01 lifecycle tests may exercise mock orders; these are not exchange
orders. No Testnet credentials were available to/used by this development runtime.

## Test protocol status

| Test | Development result | NUC / live status |
| --- | --- | --- |
| TEST-01 offline unit/regression | PASS for simulated path and existing E01 | NUC offline execution still required before deployment |
| TEST-02 continuous smoke | Virtual 25H single-run + observer scheduling PASS | NOT_TESTED; no NUC services started |
| TEST-03 read-only authentication/balances/order book | Mock GET/reconciliation/WS provider integration PASS | BLOCKED: NUC deployment/network/key access unavailable |
| TEST-04 actual nine LIVE 4H decisions | Frozen nine-decision simulated batches PASS | NOT_TESTED; no actual new bar observed |
| TEST-05 actual Observer DB to E01 Preview | Three separate real temporary SQLite DBs PASS | BLOCKED: production-path access unavailable |
| TEST-06 fresh process restart/dedup | Process/OS lock/checkpoint tests PASS | NOT_TESTED on NUC/systemd/reboot |
| TEST-07 failure injection | Mock API limit, missing bar, DB lock, health, reset/unknown PASS | Collector-stop smoke not run; destructive API/DB failures remain sandbox only |
| TEST-08 activation preflight | Review structure/documentation only | NOT_TESTED / separate approval required |
| TEST-09 one new actual T1 order | Not run, no fake LIVE/trade constructed | NOT_TESTED / separate order approval required |

## Acceptance criteria

| Criterion | Evidence / remaining gate |
| --- | --- |
| M05-01 M03/M04 Frozen source unchanged | Offline PASS: 72 protected baseline files + original E01 freeze/reproduction |
| M05-02 no 24H service limit | Offline PASS: one huge finite-horizon invocation + virtual 25H; real continuous NUC run pending |
| M05-03 systemd startup/restart | Syntax PASS; actual install/start/restart NOT_TESTED |
| M05-04 one Collector/Observer writer | OS leases PASS; separate account/filesystem/systemd enforcement awaiting deployment |
| M05-05 no missing/duplicate 4H bars | Mock recovery/uniqueness PASS; actual WS/reconnect coverage pending |
| M05-06 consistent nine decisions | Real Frozen engine over simulated inputs PASS; actual LIVE batch pending |
| M05-07 read-only Testnet connection | Mock PASS, real M05 connection BLOCKED |
| M05-08 Router DRY_RUN | Isolated copy Router/Risk PASS; actual Observer Preview pending |
| M05-09 duplicate/retroactive receipt prevention | Original receipts untouched, persistent preview cursor and backfill/stale rejection PASS |
| M05-10 old manual buy preserved | Copy/DB immutability PASS; actual order 1507111 not independently re-read |
| M05-11 NUC reboot recovery | Mock fresh-process/crash recovery PASS; NUC reboot NOT_TESTED |
| M05-12 stop/kill/reconciliation fail closed | Offline PASS; actual service stop and recovery still pending |
| M05-13 Windows/Linux CI | PASS: Ubuntu + Windows at implementation 1cfbdce; run 38149014076 |
| M05-14 actual NUC smoke | BLOCKED: deployment disabled |
| M05-15 no production order path | PASS: GET-only bridge; reused exact-host client; no runtime mutation command |
| M05-16 T1/T2/T3/W04 unchanged | Offline PASS; no allocation, source or formal ledger changes |
| M05-17 automation explicitly disabled | PASS: OFF required, HTTP mutations blocked, no service activation option |

## NOT_TESTED / BLOCKED

No NUC file installation, systemd start/enable/restart, reboot, real-time smoke,
actual WS_LIVE close, real E01 SQLite read, live API authentication/quote/account
reconciliation, account reset review or actual performance has been performed here.
The NUC connector explicitly disables deployment/network and protects operational
paths. The isolated cloud environment exposes no dedicated Testnet credentials;
the user's secret file was deliberately not accessed. These are task/environment
limitations, not a deployment completed behind the report.

TEST-08/09 were not authorized; this is an intentional scope boundary, not a failed
mock test. Existing E01 manual fill performance is not added to W04 Paper results.
No T1 capital is allocated by M05.

## Required operator next steps / 운영자 다음 단계

1. M04 대상 M05 PR과 CI를 검토한 뒤 별도 NUC 배포를 승인한다.
2. 한국어 배포 지침으로 기존 원장을 Backup API로 보존하고, 새 release·역할 계정·읽기
   전용 ACL·OFF 환경·정적 preflight를 준비한다. 기존 M04/E01 release와 24H DB는 유지한다.
3. TEST-02/03 서비스/read-only 연결을 수행한 뒤, 새 실제 4H 봉의 9개 COMMITTED LIVE
   결정을 Preview로 관찰해 TEST-04/05 증거를 저장한다. NO_ACTION이어도 유효한 검증이다.
4. 승인된 TEST-06/07 종료·복구·재부팅 smoke 결과를 실제 시각/run/hash와 함께 기록한다.
   account/SQLite discrepancy는 원본을 보존하고 영구 HOLD를 조사한다.
5. LIMIT/GTC 및 소프트웨어 Stop이 서버 중단 시 자동 보호되지 않는 위험을 DRY_RUN 종료
   전에 검토한다. 모든 Gate와 별도 사용자 승인 전까지 T1 allocation/자동 주문은 OFF다.
   TEST-08 활성화와 TEST-09 신규 실제 T1 소액 주문은 각각 별도 승인으로 진행한다.
