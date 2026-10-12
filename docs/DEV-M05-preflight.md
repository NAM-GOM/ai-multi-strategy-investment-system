# DEV-M05 preflight checklist

These are pre-deployment checks, not evidence of completed NUC operation.
No key, signed URL, environment dump, order payload with credentials, or secret file
contents may enter source, chat, CI artifacts or reports.

## Development / TEST-01

```bash
uv sync --frozen --group dev
uv run --frozen pytest
uv run --frozen ruff check .
uv run --frozen ruff format --check .
scripts/m05-preflight.sh
bash -n scripts/m05-preflight.sh scripts/m05-runtime.sh
python scripts/m05-verify-units.py
```

The source manifest must match baseline 8c6bea8 and the original 61-file E01 freeze
must pass. Git diff against baseline must contain no edits to pre-existing src files,
Frozen strategies, historical data or W04 ledgers. Existing E01 offline tests must
pass. CI must pass on Ubuntu and Windows for the exact implementation commit.

## NUC / static checks before services

Follow the Korean deployment guide after separate deployment approval. Verify:

- Ubuntu 24.04 and Python 3.14.7, uv.lock frozen install, sufficient disk/inodes,
  synchronized clock (timedatectl/chrony). 4H bars close at 01/05/09/13/17/21 KST;
  use actual received/committed timestamps, never claim a scheduled close as evidence.
- Existing M04/E01 releases and validation directory preserved. Record original
  E01 journal order/fill counts with read-only SQLite or Backup API snapshots.
- No legacy collector/observer or cron/tmux/systemd writer points at the new DBs.
  Existing WriterLease must prevent a second writer; do not delete lock files.
- Separate role directories owned by separate accounts, group read/execute only,
  no group/other directory writes, no sudo, unit ReadWritePaths restricted.
- Bridge can read E01 SQLite/WAL/SHM and directory but cannot write any of them;
  future E01 files inherit read-only ACL. Existing E01 writer ownership is unchanged.
- Testnet environment file owned by gomi/root with restrictive permissions and only
  dedicated keys plus both unlocks OFF. Check without cat/printenv/systemctl show
  Environment or enabling shell tracing. Collector/Observer cannot read the file.
- TLS verification and exact-host endpoint restrictions remain on. No redirects or
  hostname/proxy bypass if Binance/API/environment denies access.
- `scripts/m05-preflight.sh --host-check` passes on NUC and each unit's ordinary
  offline ExecStartPre passes as its service user. This validates static configuration;
  it is not a network, systemd boot or signal/latency test.
- Local unit syntax checker passes; then `systemd-analyze verify` checks actual
  installed paths. A local transformed-path check is not NUC install acceptance.

## Runtime acceptance gates / TEST-02–07

Collector READY requires committed flush, fresh connection, complete recovery and
zero conflicts/data loss. Observer READY requires successful Frozen/input/nine-decision
batch validation with no pending catch-up. Bridge requires both fresh READY healths,
healthy M04 run, no kill/hold/unknown and correct Testnet reconciliation in a copy.
Capture evidence for each test from docs/DEV-M05-validation.md before making PASS.

A NO_ACTION batch is valid routing evidence: require three WS_LIVE closed bars,
exactly nine COMMITTED LIVE_OBSERVATION decisions, unchanged Frozen/input/decision
hashes, three T1 policies and six shadows, zero actual order calls, and the original
E01 journal receipt/checkpoint/allocation unchanged. ENTRY without actual approved
T1 allocation should say STRATEGY_ALLOCATION_REQUIRED, not risk-approved for execution.
Risk sizing/filter approvals in assumed-capital offline tests are SIMULATED_TEST only.

After restart, verify checkpoint continuity, no retrospective LIVE labels, no duplicate
actual receipts/orders and the manual BTC baseline/order 1507111 (prior user evidence)
remains unowned by T1. Stop/reboot tests must be scheduled away from the 60-second
signal window or record the deliberately rejected/missed execution window.

## Separate activation review / not authorized here

TEST-08/09 are NOT_TESTED and not run by this checklist. Require user approval,
TEST-01–07 real evidence, T1 allocation approval, manual-baseline proof, account reset
review, unchanged LIMIT/GTC caps and risk, reconciled ledger, kill/unknown resolution,
server downtime/stop risk review and an explicitly approved scheduler. The M05
preview service cannot be unlocked into a trader by editing environment variables.
A later activation must use reviewed E01 commands with a separate fresh signal;
never replay Preview/old/backfill signals or fabricate LIVE evidence.
