# DEV-E02 Architecture

Baseline: DEV-M05 PR #10, `3e37b0b81b05906e1cee858671f67a4c5a719566`.
Branch: `dev-e02-t1-testnet-automation`. Initial state: **OFF**.

## Ownership and data flow

```text
Unchanged M05 Collector -> market.sqlite (read only to E02)
Unchanged M05 Observer  -> observer.sqlite (read only to E02)
Unchanged M05 READ_ONLY Bridge -> expendable preview copy; never original writer
                                    |
Separate E02 executor: Frozen E01 SignalRouter -> AutomationRisk -> OrderManager
                                    |
Original testnet_execution.sqlite: one writer, original schema and existing history
                                    |
Fixed Binance Spot Testnet HTTPS/WS only
```

E02 adds `trading_system.automation`; no existing source/test/lockfile or M05 unit
is modified. The E02 LF SHA256 manifest protects 109 baseline files; M05 also
checks its original 72 protected files. These checks compare contents, not Git
working-tree metadata. Review the manifest itself against the pinned base.

Only the leased executor opens the real journal for writing. Operator CLI uses a
durable JSON request spool, separate from SQLite; status and online preflight use
read-only connections. Online preflight backs up to temporary SQLite and runs
E01 GET reconciliation there. It restores the original gate rows in that copy
before evaluating evidence: a missing original C cannot become C through GET.
No E02 table migration is made, preserving M05 Preview's ExecutionStore compatibility.

## Single writer contract

WriterLease is an OS advisory lock; legacy E01 CLI does not acquire it. Deployment
must first stop all legacy writers/open writable file descriptors, then hand the
original journal directory/file/sidecars to a dedicated unprivileged executor.
Runtime refuses Linux root, foreign ownership or group/other write permissions.
The bridge retains read permission. Root administrators remain trusted. Do not run
the original E01 writer CLI alongside E02, even for recovery; use E02 commands.

Control spool changes are fsynced before publication. OFF changes a mode epoch;
activation compares that epoch under a control lock so a concurrent OFF cannot
be overwritten by ON. Requests expire after 60 seconds and bind to the executor
instance; requests from a previous process cannot activate a replacement process.
Every service start abandons unsubmitted T1 intents and starts OFF. Submitted
intents are reconciled with the same durable client ID; they are never reposted.

## Routing and order lifecycle

Frozen E01 verifies current observer run, immutable batch/decision hash, all nine
batch rows, Frozen recalculation, `WS_LIVE` + `LIVE_OBSERVATION`, 4H confirmation,
and the original 60-second window. T2/T3 remain shadow. Quotes are collected
concurrently from the fixed Testnet WS; E01 repeats quote/reference age, price
difference and fresh observer checks before sending. Collector/Observer heartbeats
must both be READY, current boot, age <=30s; instance replacement blocks sending.

ON records a new current watermark/activation time, deliberately excluding old
signals and Gate A candidates. No signal means no order. `phase-a` runs a real
fresh T1 dry run in an expendable copy, preserving original receipts/checkpoint.
It cannot create a passing A without an actually accepted fresh T1 candidate.
The service's `order-test` uses a fresh candidate for POST `/order/test` only,
abandons its intent, and never turns that candidate into a later order.

E01's transactions, SUBMITTING/attempted timestamp before POST, client ID lookup,
fill reconciliation, account deltas and projection seal remain authoritative.
An ambiguous POST is recovered by GET using the same client ID; absence means
UNKNOWN_EXECUTION and HOLD. API/account/DB/observer failures turn new ordering OFF.

## Evidence and control

- A: E02 capped LIVE dry-run evidence, current source paths/session and approved
  signal keys. Mock evidence is explicitly classified and rejected with real transport.
- B: preserved existing checked intent plus ORDER_TEST_PASSED event.
- C: preserved actual attempted terminal FILLED/CANCELED order evidence.
- D: explicit token approval after current account/ledger/allocation/host/M05
  acceptance checks; persisted before ON. Missing gates are never invented.

Original manual order 1507111 must match its existing BTC BUY fill and approval
record. It stays MANUAL_BASELINE, outside T1 quantity/PnL and allocation. T1 gets
1000 USDT once, following explicit allocation command and verified free balance.
Manual trades after allocation are external activity and force reconciliation HOLD.

`bind` explicitly audits the previous source checkpoint and skips existing rows;
it invalidates A/D and stays OFF. `recover` performs GET only and never clears
HOLD. `reset-kill` requires reviewed state, no uncertainty/open orders/hold,
verified allocation/manual B/C and fresh dependencies; it archives local stop
evidence and stays OFF. Account reset needs a separate reviewed session procedure;
E02 never automatically acknowledges reset or discards history.

Host-only checks cannot be disabled through CLI. Mock tests inject local providers
and bypass Linux ownership only inside test fixtures; this is not NUC acceptance.

## Protection limits

ATR20 and the Frozen 3×ATR initial stop do not change. E02 caps exit order quantity
as an execution constraint and reserves future exit count/notional before buying.
Unfilled LIMIT GTC is canceled after 60 seconds, including partial-fill remainder;
no chase/replacement occurs. Stops take priority; a triggered partial BUY is canceled
and reconciled first. Already submitted SELL remainder is counted as pending protection.
Small residuals/insufficient daily budget/filters/balance become HOLD.

This is software stop monitoring, using LIMIT GTC, not an exchange-resident stop.
OFF, server/API interruption, stale observer, dust or daily limits can prevent a
protective exit; no claimed guaranteed fill or loss bound. HOLD requires operator review.
