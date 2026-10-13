---
name: codex-efficient-workflow
description: Use only when explicitly asked to apply codex-efficient-workflow or CODEX-OPT-01 portable optimization; provide scoped search, safe output summaries, and reusable handoffs without reducing required verification.
---

# Portable Codex efficiency

Follow the repository AGENTS.md. Classify FAST, STANDARD, or STRICT.
Confirm outcome, relevant paths, acceptance criteria, and mandatory checks.
Search known source paths using rg before opening exact line ranges. Exclude
generated files, dependencies, caches, backups, and credentials from routine search.
Exceptions needed for the task are allowed; exclusions are not a security boundary.

Prefer existing interfaces, helpers, standard libraries, and installed dependencies.
Keep the diff minimal and inspect every changed file. Run relevant checks first.
Preserve all required broader checks and security gates. Never infer production
success from mocks.

For noisy output, save the complete log locally, retain the command exit code,
and report distinct errors with enough surrounding context. Expand the excerpt
when an error, cause chain, recovery result, or acceptance criterion is omitted.
Do not claim character or byte reductions are measured model-token savings.

Reuse a handoff only after comparing its base commit and changed-file list to
the actual workspace. Record goal, scope, decisions, changed files, commands,
verified results, blockers, and exact next action. Do not store credentials,
operating balances, or sensitive production data in a committed handoff.

No automatic MCP registration, API proxy, observer, hook, model change,
brainstorming, subagent, dependency installation, or deployment.
Use optional third-party skills only if specifically requested and reviewed.
Stop redundant retries; analyze the cause after repeated failure.

Report completion and verification concisely with unresolved limits.
