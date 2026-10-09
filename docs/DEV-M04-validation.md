# DEV-M04 validation

Current classification: **DEV-M04_HOLD**. Implementation, Windows/Linux deterministic
verification and public smoke/restart are complete. The new actual M04 closed-bar
observation is pending. Technical verification never authorizes Formal W04 or strategy APPROVED.

## Baseline and source audit

Reviewed M03 fixes were committed and fast-forward pushed to
`dev-m03-sqlite-market-data`: `1b1bf582f34a526d9204a084dc4573c79efa124e`.
M04 was created from that exact commit on `dev-m04-strategy-observer`, in an
independent checkout. Main and earlier M01/M02/M03 history were preserved.

M03 genuine 2026-10-09 17:00 KST evidence remains historical M03 evidence. It is not
an M04 live pass. Its network duplicate-close test remains NOT_TESTED; captured real
payload replay passed. The exact historical 12:47 BTC cause remains unproven.
Fresh M03 freeze validation: 245 passed, 8 skipped; Ruff/format PASS. An additional
review fixed zero-new-write restarts that already had committed price receipts.

Frozen package SHA256:
`2ad1bca4fcd1a0694bd39bafff3d3f6b93beccc3f7237b0376a73e030f9ad155`.
Strategy source SHA256:
`0850fcc32356a4275e0795cece08a6f6d701220b941ce94e2b95dd1ce802a965`.
W03 parameter/config SHA256:
`6a7ce60ed2199cc432cbd98733e3b72f4d926e7120cbc5e69d224b6d9fd0863b`.

The byte-preserved source, config, historical CSV, original reference ledgers/equity
curves and manifests are committed under `artifacts/w03` and the Frozen module.
`artifacts/w03/lock.json` maps original paths and records every hash; its own byte
hash is pinned in audit.py. Runtime parameter and dependency versions are also checked.
Data SHA256 values:

| Symbol | SHA256 |
|---|---|
| BTC | f4ddf0ec4354fe66f2635887a809e433962877b9b090a728a02d3721a0183059 |
| ETH | f0cda00c5f062f947c0175c911b8afb521a62d38d04d3f45c220a56d3e7002bb |
| SOL | fe428dcdce137be444ab38f2c497651455173b4bbcbc2a5cdc75e386e1265187 |

## Actual offline reproduction

Original strategy versions are `0.1` (manifest labels `v0.1`). EMA50/200 crossover,
Donchian55/20 excluding current bar, Momentum180 zero transitions and Wilder-style
ATR20 EWM are reused without edits. `cycle.generate_segments` preserves masking of
the first 201/56/182 rows and its indicator initialization rules. Historical common
initialization starts at 2020-08-11 04:00 UTC; evaluation starts at
2020-09-13 16:00 UTC and ends at the 2026-10-02 08:00 UTC open (12:00 UTC close).

Original shared-capital engine replay matches all three Frozen trade ledgers and
equity curves exactly after CR/LF transport normalization. All numeric strings,
timestamps, order, signal-time fields, stop initialization and position accounting
remain equal. No new numerical tolerance was introduced. W03's engine verifies
next-open entry/exit, signal ATR stops, fees 10bps, model slippage 5bps, risk .005,
asset cap .333, long-only/no-pyramiding behavior. This engine is called only in
offline historical verification; live signal evaluation never invokes that engine.

| Strategy | Symbol | Entry booleans | Exit booleans | Original ledger trades incl. terminal |
|---|---|---:|---:|---:|
| T1 | BTC | 32 | 31 | 32 |
| T1 | ETH | 37 | 36 | 37 |
| T1 | SOL | 36 | 35 | 36 |
| T2 | BTC | 439 | 500 | 87 |
| T2 | ETH | 444 | 493 | 99 |
| T2 | SOL | 460 | 579 | 91 |
| T3 | BTC | 198 | 197 | 198 |
| T3 | ETH | 204 | 203 | 204 |
| T3 | SOL | 200 | 200 | 199 |

All combinations have 13,460 initialization/evaluation rows. Boolean counts describe
conditions, not orders. Indicator and boolean prefix regeneration is exact; future
mutations do not change past output. Adapter snapshots are compared against Frozen
output for all nine combinations in deterministic tests.

**Evidence flag:** no independent full-bar W03 indicator/boolean dump was supplied.
Indicator verification uses byte-identical source, exact prefix parity and original
entry ATR/stop ledger parity. The W04 117-record handoff inventory is not claimed as
a newly rerun W03 test. Detailed new audit output is `docs/DEV-M04-reproduction.json`.

## Implemented gates and persistence

Every shared evaluation reads a consistent M03 SQLite read transaction through
MarketRepository. It checks UTC boundaries, confirmed closure, integrity, OHLCV,
valid original provenance, ingestion/event time, unresolved gaps, recorded candle
conflicts, initialization continuity and Frozen warmup. All three symbols must have
the target bar. M04 market access remains read-only and makes no schema changes.
Frozen historical data plus continuous post-freeze M03 rows provide initialization;
no warmup parameter or replacement price was invented.

Nine decisions, including NO_ACTION, commit atomically with nine checkpoints. The
unique key is strategy/version/symbol/bar-open. Deterministic hashes exclude only
wall-clock evaluation time. Original classification is retained on re-evaluation.
Conflicting repeated output stops without overwrite. Batch failures are immutable
DATA_BLOCKED attempt records, never partial committed batches. DB triggers preserve
decisions/manifests/health; recovery verifies record hashes, batch completeness and
latest checkpoints. Persistent STOP survives restart. CLI uses a process writer lease.

M04 maintains its own process/observation clock, not Formal W04. REST bootstrap and
recovery never become LIVE or FORMAL observations. Prelaunch or missed bars remain
state backfill. No existing W04 state, T1 continuity/formal ledger, T2/T3 HOLD or
quote-freshness Gate F is modified. FORMAL_W04_ELIGIBLE is reserved and never emitted.

## Tests and observed validation

Windows Python 3.14.7: **283 passed, 8 skipped** on the latest completed full run.
The skipped tests are existing opt-in network/account tests. The final rerun after
writer-lease/supervisor additions also passed: 283 passed, 8 skipped in 41.50s. Ruff and
format cover new implementation; Frozen sources are excluded to preserve hashes.

Covered: source/config/data/runtime changes; full original-engine reproduction;
nine snapshots; W03 warmup masking; Momentum180; current-bar exclusion; future
information; provenance/time classification; missing/invalid/unresolved data;
read-only market DB; immutable records; duplicate conflicts; atomic rollback;
checkpoint corruption; persistent STOP; actual subprocess forced crash and separate
CLI restart; existing M01/M02/M03 tests; no credential/config or order path invoked.

GitHub CI for implementation commit `2ac688b8e685794eb488860de297f37b2992bf71`:
[run 37933197403](https://github.com/NAM-GOM/ai-multi-strategy-investment-system/actions/runs/37933197403).
Windows: 283 passed, 8 skipped in 53.96s. Linux: 283 passed, 8 skipped in 34.58s.
Both Ruff and format PASS (52 files). Step evidence: `docs/DEV-M04-ci.json`.

New Windows public 600-second collector/observer smoke: **PASS**, between real closes.
M03 collector COMPLETED / public WS LIVE_PASS, 605.016 seconds uptime, 2,604 messages,
144 REST_BOOTSTRAP candles, 33 price snapshots, three bootstrap gaps resolved,
zero reconnects, **zero actual WS closed candles**. All three symbols observed.
M04 committed nine decisions with real Frozen indicator snapshots: one
ENTRY_CANDIDATE and eight NO_ACTION, all **PRELAUNCH_STATE_BACKFILL**. No orders,
positions, fills or Formal W04 clock were created. A separate new observer process
returned ALREADY_COMMITTED, retained all nine records and added zero decisions.
Evidence and actual snapshots: `docs/DEV-M04-smoke-summary.json`.
This smoke does not establish OBS-12 and its old candidate is not a new live signal.

New actual M04 4H closes: **LIVE_NOT_OBSERVED** as of this report. At the user's
request, targets are 2026-10-10 01:00 and 05:00 KST / 2026-10-09 16:00 and 20:00 UTC.
Two independent opt-in supervisor processes are running, each prepared to
capture that close and verify original WS_LIVE provenance, all nine actual snapshots,
NO_ACTION persistence and separate-process restart. It is running in the background;
the supervisor reports LIVE_NOT_OBSERVED while waiting. Results will be written to
`data/m04-live-20261010T010000/` and `data/m04-live-20261010T050000/`. These are
separate observation windows, not evidence of continuous coverage between them.
The one-time thread follow-up was moved to 2026-10-10 05:10 KST to inspect both
actual results, update this report/branch, and create `docs/DEV-M04-final-report-ko.md`.
A plan or active process is not an actual result.

## Acceptance gates

| Gate | Current result |
|---|---|
| OBS-01 source/config | PASS |
| OBS-02 nine-combination reproduction | PASS_WITH_EVIDENCE_FLAG above |
| OBS-03 Frozen warmup/history | PASS offline; live continuity checked at runtime |
| OBS-04 closed only | PASS deterministic |
| OBS-05 provenance | PASS deterministic and public smoke |
| OBS-06 shared barrier | PASS deterministic |
| OBS-07 persistent decisions | PASS deterministic |
| OBS-08 restart duplicates | PASS separate-process deterministic |
| OBS-09 fail closed | PASS deterministic |
| OBS-10 Windows/Linux/Ruff/format | PASS both OS CI, including Ruff/format |
| OBS-11 M01/M02/M03 regression | PASS both OS CI |
| OBS-12 actual M04 closed-bar | LIVE_NOT_OBSERVED |
| OBS-13 no trading/paper execution | PASS |
| OBS-14 Formal clock unchanged | PASS; M04 never accesses W04 state |

Final PASS classification requires actual results for the pending gates. No claims
about unobserved network duplicates, old event causes, complete independent W03
indicator dumps or Formal W04 performance are added.
