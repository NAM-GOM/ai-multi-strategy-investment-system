# MR-W02 / MR-W03 Codex Cloud handoff

Research archive only. M1 HOLD; M2 MR_W03_HOLD; M3 REJECT_CANDIDATE recommendation. Registry proposal NOT_APPLIED. No APPROVED/PAPER promotion, trading, Observer launch, or operational changes.

## Provenance

- Frozen baseline source commit: bc2ca95d98c4d3e0e7bf3ca9e5e52f545848447e.
- Prior isolated final payload commit: 50281aabbc91816dab7bd26067eddeffa7660474 (local archive repository, available in the saved Git bundle; not an upstream repo commit).
- Existing original source, snapshots, fees, execution contract and Trend/DEV files are inherited unchanged from the baseline commit.
- This GitHub handoff commit adds research files only. Its SHA is the remote branch HEAD; do not confuse it with the source or isolated payload SHA.
- Full sealed ZIP (including bundle/data copies) is available in ChatGPT: https://chatgpt.com/api/library/files/libfile_253f5b56bad081919fa92123d8d087be/download (authorized user access required). Its SHA256 is in artifacts/mr-w03/final/MR-W03_final_artifact.sha256. The binary ZIP is not duplicated in this Git repository.

## Contents

- results/mr_w02/: five original outputs, support tables and test log.
- scripts/mr_w02/diagnose.py and tests/test_mr_w02_audit.py: original diagnostic code and supplemental tests.
- results/mr_w03/: six original outputs, copied byte-for-byte.
- intermediate/mr_w03/: original Freeze, runner, CSV verifier, decision JSON, preflight log and supporting diagnostics.
- artifacts/mr-w03/final/: final audit, specification deviations, proposed Registry handoff and sealing evidence.
- artifacts/mr-research/SHA256SUMS.json: exact hashes of files added by this handoff (excluding that manifest itself).

## Codex Cloud: inspect without another backtest

Select branch research/mr-w02-w03-finalization in this repository, then run:

    python scripts/mr_archive/verify_artifacts.py

This uses only the Python standard library, checks hashes/scenario counts/frozen prefix and existing CSV decision consistency, and does not run any backtest, pytest, API, order, observer or Registry update.

The original W02/W03 runner and verify.py contain Windows absolute output paths. They are intentionally archived unchanged so their recorded SHA remains valid. They are not portable Linux entry points. Do not run them directly in Cloud. A separately reviewed path-only adapter would be needed for a later authorized reproduction, preserving original source and scenario/threshold definitions. No adapter or new research execution is authorized by this handoff.

The earlier MR-R01 MR-W02/MR-W03 BLOCKED status was due to missing artifacts. These inputs are now supplied, but upload and static verification do not constitute independent reproduction and do not close those findings.

Use existing observed historical data only; do not label it Genuine Unseen OOS. No favorable parameter, asset, year or environment selection. New Mean Reversion ideas require a separate version. Actual Registry changes still require user approval.
