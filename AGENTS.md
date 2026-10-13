Universal Codex Efficiency Rules

1. Objective

Complete the requested task with minimal unnecessary work, context, tool calls, and token usage.

Maintain correctness, security, and required verification.

Do not sacrifice correctness to reduce tokens or execution time.

2. Task Classification

Classify the task before execution.

- FAST: Small edits, isolated bugs, documentation, or simple changes.
- STANDARD: Feature development, moderate refactoring, or several related files.
- STRICT: Security, payments, financial transactions, databases, infrastructure, production systems, or high-risk changes.

Use the smallest suitable workflow.

3. Scope Control

- Identify the requested outcome and affected files.
- Search for relevant symbols before reading full files.
- Read only the code needed to understand the change.
- Reuse valid findings from the current session.
- Avoid unrelated refactoring or architecture changes.
- Do not install dependencies unless needed.
- Prefer minimal, reviewable changes.
- Preserve existing interfaces unless the task requires a change.

4. Context and Token Efficiency

- Avoid broad repository scans.
- Exclude generated files, dependencies, caches, and large logs from routine searches.
- Read large files in relevant sections.
- Summarize command output instead of repeating full logs.
- Keep tool outputs concise when possible.
- Do not repeat completed analysis without a reason.
- Use relevant Skills and MCP tools only when they provide clear value.
- Avoid unnecessary subagents and parallel investigations.
- Use short checkpoints when a task requires several phases.

5. Editing Procedure

1. Locate the relevant implementation.
2. Identify the smallest safe change.
3. Edit only the necessary files.
4. Inspect the resulting diff.
5. Run focused verification.
6. Address failures using the smallest relevant correction.
7. Run required broader verification before completion.

Do not rewrite an entire file for a small change.

6. Validation Policy

FAST

- Run focused tests or checks when appropriate.
- Do not run the full test suite by default.
- Preserve all mandatory project checks.

STANDARD

- Run affected tests first.
- Run broader regression tests when integration risk exists.
- Use CI for required platform checks.

STRICT

- Preserve all mandatory tests and safety gates.
- Verify failure handling and recovery paths.
- Never bypass security checks to save time.
- Do not treat mock results as production evidence.

If the same failure persists after two corrective attempts, reassess the root cause before retrying.

7. Execution Limits

- Do not repeat identical failed commands without changing the cause.
- Avoid redundant builds and duplicate CI runs.
- Do not wait for unrelated asynchronous checks unless their results are required.
- Stop expanding the task when the requested acceptance criteria are satisfied.
- Report blockers instead of attempting unrelated fixes.

8. Security and Change Control

- Respect repository-specific instructions.
- Do not expose secrets or credentials.
- Do not modify production data without authorization.
- Do not deploy, publish, merge, or perform external actions beyond the granted scope.
- Require explicit authorization for destructive or irreversible actions.
- Preserve existing safety controls.

9. Reporting

Keep final reports concise.

Report only:

- Completed work
- Changed files
- Tests performed and results
- Remaining issues
- Next action, if required

Do not repeat the complete implementation history.

10. Priority

Follow this order:

1. Safety and explicit user instructions
2. Correctness
3. Required verification
4. Minimal scope
5. Execution time
6. Token efficiency

Apply these rules to all software projects unless more specific project instructions override them.

## CODEX-OPT-01 portable configuration

The Universal Codex Efficiency Rules above remain authoritative. Repository safety
rules and explicit user instructions take precedence over optional third-party skills.

- Confirm the requested scope before searching; use targeted `rg` and line ranges.
- Run affected tests first when useful, then all project-mandated checks before completion.
  A passing focused check never replaces a required safety gate.
- Use an existing handoff only after checking its commit, changed files, and known blockers.
- Keep complete diagnostic output in a local file when needed; show a concise summary
  without discarding exit codes, distinct errors, or required recovery evidence.
- Do not repeat failures without new evidence or expand unrelated work.
- Do not automatically start proxies, memory observers, lifecycle hooks, brainstorming,
  or subagents. Tool installation is not proof of Cloud host activation.
- Optional reviewed skills in `tools/codex-optimization/available-skills/` are inactive
  by default. Read only the specifically requested skill, subject to these rules.
- The project skill `codex-efficient-workflow` is opt-in. Its presence does not prove
  discovery by an already running Cloud session.
- Financial, security, database, infrastructure, and production changes remain STRICT.
- Report changed files, verification evidence, limitations, and required next actions.

For another project, merge these rules without replacing that project's instructions.
See `docs/codex-optimization/cloud-setup-guide.md` for setup and rollback.
