You are reviewing code that Claude just wrote for task T001: Delete the dead usage-% guard (Z_HARNESS_PAUSE_AT_PCT + usage_pause event).

Task description: The usage-limit guard was designed to pause execution when Claude Code usage hit a threshold, but it was never fully implemented and is now dead code. The task is to remove all references to it.

Acceptance criteria:
1. Section "Usage-limit guard policy" (around commands/z-implement-all.md:154 and skills/z-implement-all/SKILL.md:144) is removed entirely.
2. All references to `Z_HARNESS_PAUSE_AT_PCT` are removed across the three files (grep returns zero hits).
3. `usage_pause` event name no longer mentioned anywhere as the active emission name (a one-line "(deprecated; replaced by `compaction_pause`)" note is acceptable in the README event-type table if such a table exists).

NOTE: The three files had pre-existing uncommitted modifications before T001 began. Scope review to T001-relevant lines only (removal of usage guard, env var, and usage_pause emission). Ignore other pre-existing diffs in these files.

Diff (primary artifact — focus scrutiny on what changed):

```diff
diff --git a/README.md b/README.md
index cabfcfe..bcb3cff 100644
--- a/README.md
+++ b/README.md
@@ -82,6 +82,7 @@ Every command writes its artifacts under `z-harness/<slug>/`, with run-frozen ar
 | `spec-precheck` | haiku | Pre-flight: verify SPEC.md references actually exist before implementing |
 | `doc-updater` | sonnet | Refreshes one stale concept's docs/human + docs/llm pair |
 | `remote-runner` | haiku | Mechanical remote work — rsync sandbox + cargo build, read-only DB/log queries, paper qtctl restarts |
+| `external-lookup` | haiku | Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist. |
 
 Which CLI each agent role calls is determined by `providers.json` (see
 [docs/human/PROVIDERS.md](docs/human/PROVIDERS.md)). Run
@@ -189,7 +190,6 @@ When a downstream repo defines its own skills that interoperate with z-harness,
 ## Environment knobs
 
 - `Z_HARNESS_NOTIFY` — `off` | `approval_only` (default) | `all`. Controls push notifications.
-- `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
 - `Z_HARNESS_MAX_EXPLORE` — default `3`. Cap on `Explore` subagent dispatches per `/z-plan` run.
 - `Z_HARNESS_DOC_STALENESS_THRESHOLD` — default `20` (percent). Above this, `/z-plan` halts and recommends `/z-maintain-docs` first.
 - ~~`Z_HARNESS_RETRY_UPGRADE`~~ — removed. The implementer model is now picked directly via `Agent(model=...)` based on the task block's `**Complexity:** low|medium|high` stamp (`low|medium` → Sonnet, `high` → Opus). Retries (cycle ≥ 2) always dispatch with `model="opus"`. The complexity stamp is added at plan-time by a Haiku `complexity-classifier` subagent and is user-editable in TASKS.md.
@@ -290,7 +290,8 @@ z-harness/
 │   ├── mr-reviewer.md
 │   ├── spec-precheck.md
 │   ├── doc-updater.md
-│   └── remote-runner.md
+│   ├── remote-runner.md
+│   └── external-lookup.md
 ├── scripts/
 │   ├── extract-dismissals.py
 │   ├── log-event.sh
diff --git a/commands/z-implement-all.md b/commands/z-implement-all.md
index 84283ea..c6e988d 100644
--- a/commands/z-implement-all.md
+++ b/commands/z-implement-all.md
@@ -151,8 +151,6 @@ Both `--ack` and `--force-partial` are inert for legacy (single-slug) plans and
      {"framework": "<pytest|cargo|jest|...>", "cmd_template": "<template>", "set_at": "<ISO ts>"}
      ```
    This is asked exactly once per slug; it's a per-plan cache so different plans can target different test frameworks.
-8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
-
 ## Parallelism (read first)
 
 The numbered steps below describe a **single task track** — one task's journey from pick → precheck → implement → review → done. The orchestrator dispatches up to **N=3 task tracks in parallel** per outer iteration, subject to these rules:
diff --git a/skills/z-implement-all/SKILL.md b/skills/z-implement-all/SKILL.md
index 53302ca..c5010ec 100644
--- a/skills/z-implement-all/SKILL.md
+++ b/skills/z-implement-all/SKILL.md
@@ -141,8 +141,6 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
      {"framework": "<pytest|cargo|jest|...>", "cmd_template": "<template>", "set_at": "<ISO ts>"}
      ```
    This is asked exactly once per slug; it's a per-plan cache so different plans can target different test frameworks.
-8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
-
 ## Parallelism (read first)
 
 The numbered steps below describe a **single task track** — one task's journey from pick → precheck → implement → review → done. The orchestrator dispatches up to **N=3 task tracks in parallel** per outer iteration, subject to these rules:
```

Scrutinize this code rigorously. The spec said three files need changes for this task. The diff shows changes to README.md, commands/z-implement-all.md, and skills/z-implement-all/SKILL.md.

Key things to check:
1. Was the "Usage-limit guard policy" section completely removed from both command and skill files?
2. Were ALL references to `Z_HARNESS_PAUSE_AT_PCT` removed?
3. Was `usage_pause` event completely removed as an active emission (or only marked deprecated if in a README table)?
4. Are there any dangling or broken references after the deletions?
5. Does the diff match the scope it claims (T001 only; ignore other pre-existing changes)?

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

OUTPUT BUDGET — respect strictly:
- Total response under 8000 characters.
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff.
