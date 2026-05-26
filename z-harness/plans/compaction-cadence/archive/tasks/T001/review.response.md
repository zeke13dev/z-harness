2026-05-25T00:35:53.809928Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-25T00:35:53.810582Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-25T00:35:53.810589Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5c8f-4514-7d22-8eac-a949dc6248d3
--------
user
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

codex
I’ll verify the actual workspace, not just the pasted diff, and scope the checks to the three T001 files plus repository-wide references for the two removed identifiers.
exec
/bin/zsh -lc 'rg -n "Usage-limit guard policy|Z_HARNESS_PAUSE_AT_PCT|usage_pause|compaction_pause" README.md commands/z-implement-all.md skills/z-implement-all/SKILL.md' in /Users/zeke/dev/z-harness
 exited 1 in 0ms:
exec
/bin/zsh -lc 'rg -n "Z_HARNESS_PAUSE_AT_PCT|usage_pause" .' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'git diff -- README.md commands/z-implement-all.md skills/z-implement-all/SKILL.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
@@ -276,7 +274,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 Agent(
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
diff --git a/skills/z-implement-all/SKILL.md b/skills/z-implement-all/SKILL.md
index 53302ca..c5010ec 100644
--- a/skills/z-implement-all/SKILL.md
+++ b/skills/z-implement-all/SKILL.md
@@ -10,12 +10,23 @@ Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
 - `--ack` — Override the SHARED-CONCERNS.md ack-gate when iterating a tree-rooted plan produced by `/z-plan-split`. Equivalent to manually flipping `acknowledged: true` in the file. No-op for legacy single-slug plans.
 - `--force-partial` — Override the partial-tree gate when iterating a tree-rooted plan whose SHARED-CONCERNS.md has `partial_tree: true` (i.e. one or more clusters failed planning). Implies the user accepts that overlap detection is a lower bound on a partial tree. No-op for legacy single-slug plans.
+- `--tasks=<path>` — Override the default tasks file location. When provided, that file is the task queue instead of `$BASE/TASKS.md`. `<path>` may be repo-relative (for example `z-harness/<slug>/REVIEW-TASKS.md` or `z-harness/<slug>/MR-REVIEW.md`) or absolute. `$BASE` is derived from the directory containing the task file so SPEC.md, PLAN.md, and archive paths resolve next to the promoted artifact. Slug discovery, tree validation, `--ack`, and `--force-partial` are skipped for this single overridden task file.
 
-Both flags are inert for legacy (single-slug) plans and only affect tree-rooted discovery in Setup step 2.
+Both `--ack` and `--force-partial` are inert for legacy (single-slug) plans and only affect tree-rooted discovery in Setup step 2.
 
 ## Setup
 
 1. `cd` to the repo root. Abort if no `z-harness/` directory.
+
+   **`--tasks` fast path.** If the user invoked with `--tasks=<path>`, resolve the path to absolute and derive `BASE` as its parent directory:
+   ```bash
+   TASKS_FILE="$(realpath <path>)"
+   BASE="$(dirname "$TASKS_FILE")"
+   Z_HARNESS_SLUG="$(basename "$BASE")"
+   ```
+   Skip steps 2 and 2a-2d. Jump directly to step 3, binding `BASE` and `TASKS_FILE` as derived above. This supports promoted review artifacts such as `REVIEW-TASKS.md` and `MR-REVIEW.md`.
+
+   **Example:** `/z-implement-all --tasks=z-harness/my-plan/REVIEW-TASKS.md` reads task blocks such as `T-REV-001` from `REVIEW-TASKS.md` and resolves SPEC.md/PLAN.md at `z-harness/my-plan/`.
 2. **Discover plan slug.** Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. A `$Z_HARNESS_PLAN_DIR/` may be either a **legacy single-slug plan** (contains `TASKS.md` directly) or a **tree-rooted plan** produced by `/z-plan-split` (contains `MANIFEST.md` + per-cluster subdirectories, each with its own `TASKS.md`):
 
    **2a. Enumerate candidates.**
@@ -103,8 +114,14 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
 
    **2d. If chosen slug is legacy (TASKS.md directly under it, no MANIFEST.md),** behavior is unchanged: a single `BASE` for the whole run, no tree validation, `--ack` and `--force-partial` are no-ops.
 
-3. From here on, **`BASE`** = `$Z_HARNESS_PLAN_DIR` for legacy slugs (or `z-harness` for legacy flat). For tree-rooted slugs, `BASE` is rebound per-cluster as the orchestrator iterates the run-order sequence from 2c. All paths use `$BASE`.
-4. Read `$BASE/TASKS.md` once into memory — you'll re-read between batches to pick up status flips. **Do NOT pre-extract SPEC/PLAN slices in main thread** — subagents will Read them directly from `$BASE/SPEC.md` and `$BASE/PLAN.md` themselves. This keeps the orchestrator main-thread context light across many tasks.
+3. From here on, **`BASE`** = `$Z_HARNESS_PLAN_DIR` for legacy slugs (or `z-harness` for legacy flat). For tree-rooted slugs, `BASE` is rebound per-cluster as the orchestrator iterates the run-order sequence from 2c. When `--tasks` was provided, `BASE` was set in step 1's fast path. All paths use `$BASE`.
+
+   **Set the default tasks file now that `BASE` is bound** (the `--tasks` fast path already set `TASKS_FILE`, so the default leaves it alone):
+   ```bash
+   TASKS_FILE="${TASKS_FILE:-$BASE/TASKS.md}"
+   ```
+
+4. Read `$TASKS_FILE` into memory — always set by step 1's fast path or step 3's default above. You'll re-read between batches to pick up status flips. **Do NOT pre-extract SPEC/PLAN slices in main thread** — subagents will Read them directly from `$BASE/SPEC.md` and `$BASE/PLAN.md` themselves. This keeps the orchestrator main-thread context light across many tasks.
 5. **Version stamp + run_start event:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
@@ -124,8 +141,6 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
      {"framework": "<pytest|cargo|jest|...>", "cmd_template": "<template>", "set_at": "<ISO ts>"}
      ```
    This is asked exactly once per slug; it's a per-plan cache so different plans can target different test frameworks.
-8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
-
 ## Parallelism (read first)
 
 The numbered steps below describe a **single task track** — one task's journey from pick → precheck → implement → review → done. The orchestrator dispatches up to **N=3 task tracks in parallel** per outer iteration, subject to these rules:
@@ -153,7 +168,7 @@ Repeat until no eligible task remains or you halt:
 
 ### 1. Pick next task
 
-Re-read `TASKS.md`. Build a quick eligibility check:
+Re-read `$TASKS_FILE`. Build a quick eligibility check:
 
 - Status is `[ ]` (pending)
 - **Every** dependency listed under "Depends on" is `[x]` (done) — go by task-level deps, not phase headings (phases mislead — e.g. T006 depends on T010+T011 even though they're in different phases)
@@ -190,7 +205,7 @@ Critical: **never retry a skip-flagged task in the same run** unless the user pi
 
 ### 3. Mark in-progress
 
-Edit `$BASE/TASKS.md`: flip the chosen task's `[ ]` to `[~]`. Log:
+Edit `$TASKS_FILE`: flip the chosen task's `[ ]` to `[~]`. Log:
 ```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
 ```
@@ -249,7 +264,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 Agent(
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
@@ -388,7 +403,7 @@ If `$BASE/test-runner.json` is absent OR the task block has no `**Tests:**` line
 
 ### 8. Mark done
 
-1. Flip `[~]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
+1. Flip `[~]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
 2. Write per-task summary file `$BASE/archive/tasks/<task-id>/SUMMARY.md` with outcome + counts. Future references to this task pull from the file rather than re-loading the full reviewer return into main thread.
 3. Log:
 ```bash
@@ -404,7 +419,7 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tas
 
 When the loop exits (no more eligible tasks, or you halted):
 
-1. Re-read `TASKS.md` for final counts: `done`, `pending`, `in_progress`, `skipped`.
+1. Re-read `$TASKS_FILE` for final counts: `done`, `pending`, `in_progress`, `skipped`.
 2. Write a summary message to the user:
    - Counts
    - Skipped tasks with reasons (REMOTE / wall-clock / human action required)

 succeeded in 131ms:
./z-harness/archive/tasks/per-task-model-selection/review.response.md:213: 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:68:+8. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly. (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/review.prompt.md:456:+8. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly. (User resumes by re-invoking with the same topic.)
./z-harness/plans/doc-memories/archive/tasks/T012/diff.patch:64: - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:49:+8. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly. (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff-v1.patch:437:+8. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly. (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:48:-+8. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly. (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:52:++9. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly (see Early-exit telemetry contract below). (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:85:++- `usage_paused` — Usage-limit guard fired (Setup step 9 or mid-run). Emit `phase_end` for the currently-active phase before returning.
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:243:-+8. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly. (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:247:++9. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly (see Early-exit telemetry contract below). (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/delta-v2.patch:280:++- `usage_paused` — Usage-limit guard fired (Setup step 9 or mid-run). Emit `phase_end` for the currently-active phase before returning.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:57:+9. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly (see Early-exit telemetry contract below). (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:89:+- `usage_paused` — Usage-limit guard fired (Setup step 9 or mid-run). Emit `phase_end` for the currently-active phase before returning.
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:500:+9. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly (see Early-exit telemetry contract below). (User resumes by re-invoking with the same topic.)
./z-harness/plans/plan-decompose/archive/tasks/T002/diff.patch:532:+- `usage_paused` — Usage-limit guard fired (Setup step 9 or mid-run). Emit `phase_end` for the currently-active phase before returning.
./exports/agy/prompts/z-plan.md:45:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/compaction-cadence/SPEC.md:5:Delete the never-functioning `Z_HARNESS_PAUSE_AT_PCT` usage-% guard, and replace its mechanism (pause + push-notify) with deterministic breakpoints inserted at the highest-context-pressure boundaries in `/z-implement-all`, `/z-review-all`, and the `--audit` path of `/z-maintain-docs`.
./z-harness/plans/compaction-cadence/SPEC.md:31:4. **`usage_pause` event name retired.** New event: `compaction_pause` with payload `{trigger: "task_count"|"wall_time"|"pre_consult", detail: {...}}`. Existing `metrics.jsonl` consumers (`/z-stats`) handle missing event types gracefully — no migration.
./z-harness/plans/compaction-cadence/SPEC.md:37:**Delete:** the entire "Usage-limit guard policy" subsection at line 154 (env var `Z_HARNESS_PAUSE_AT_PCT`, all language about "current usage %" and the 90% threshold).
./z-harness/plans/compaction-cadence/SPEC.md:134:- Delete the `Z_HARNESS_PAUSE_AT_PCT` row from any env-var table.
./z-harness/plans/compaction-cadence/SPEC.md:175:- **SOLID:** The compaction policy is now a single concern (breakpoint placement) with clear extension points (add a new `trigger` value, add a new `phase` value). Removing `Z_HARNESS_PAUSE_AT_PCT` eliminates a fictitious "usage-% awareness" responsibility the orchestrator never had.
./z-harness/plans/compaction-cadence/PLAN.md:5:Replace a non-functioning context-pressure mechanism (`Z_HARNESS_PAUSE_AT_PCT`) with deterministic compaction breakpoints in the three most context-heavy commands.
./z-harness/plans/compaction-cadence/PLAN.md:9:- **D1.** Delete `Z_HARNESS_PAUSE_AT_PCT` everywhere.
./z-harness/plans/compaction-cadence/PLAN.md:13:- **D5.** New event name `compaction_pause`; retire `usage_pause`.
./z-harness/plans/compaction-cadence/PLAN.md:30:1. **Delete the dead guard.** Remove `Z_HARNESS_PAUSE_AT_PCT` from `commands/z-implement-all.md`, `skills/z-implement-all/SKILL.md`, `README.md`. Sweep exports.
./z-harness/plans/compaction-cadence/TASKS.md:18:- All references to `Z_HARNESS_PAUSE_AT_PCT` are removed across the three files (grep returns zero hits).
./z-harness/plans/compaction-cadence/TASKS.md:19:- `usage_pause` event name no longer mentioned anywhere as the active emission name (a one-line "(deprecated; replaced by `compaction_pause`)" note is acceptable in the README event-type table if such a table exists).
./z-harness/plans/compaction-cadence/TASKS.md:36:- No code path emits `usage_pause` anymore.
./z-harness/plans/compaction-cadence/TASKS.md:177:- `grep -r Z_HARNESS_PAUSE_AT_PCT exports/` returns zero hits.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/decisions.md:5:- **Decision:** What to do with `Z_HARNESS_PAUSE_AT_PCT` and all "current usage %" language.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/decisions.md:48:  - (a) Reuse `usage_pause` everywhere (semantic stretch — not usage-driven anymore).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/decisions.md:50:- **Tentative:** (b). Honest naming; lets `/z-stats` distinguish reasons. Keep `usage_pause` reserved for if/when a real usage signal exists.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:5:Delete the never-functioning `Z_HARNESS_PAUSE_AT_PCT` usage-% guard, and replace its mechanism (pause + push-notify) with deterministic breakpoints inserted at the highest-context-pressure boundaries in `/z-implement-all`, `/z-review-all`, and the `--audit` path of `/z-maintain-docs`.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:31:4. **`usage_pause` event name retired.** New event: `compaction_pause` with payload `{trigger: "task_count"|"wall_time"|"pre_consult", detail: {...}}`. Existing `metrics.jsonl` consumers (`/z-stats`) handle missing event types gracefully — no migration.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:37:**Delete:** the entire "Usage-limit guard policy" subsection at line 154 (env var `Z_HARNESS_PAUSE_AT_PCT`, all language about "current usage %" and the 90% threshold).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:134:- Delete the `Z_HARNESS_PAUSE_AT_PCT` row from any env-var table.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md:175:- **SOLID:** The compaction policy is now a single concern (breakpoint placement) with clear extension points (add a new `trigger` value, add a new `phase` value). Removing `Z_HARNESS_PAUSE_AT_PCT` eliminates a fictitious "usage-% awareness" responsibility the orchestrator never had.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/PLAN.md:5:Replace a non-functioning context-pressure mechanism (`Z_HARNESS_PAUSE_AT_PCT`) with deterministic compaction breakpoints in the three most context-heavy commands.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/PLAN.md:9:- **D1.** Delete `Z_HARNESS_PAUSE_AT_PCT` everywhere.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/PLAN.md:13:- **D5.** New event name `compaction_pause`; retire `usage_pause`.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/PLAN.md:30:1. **Delete the dead guard.** Remove `Z_HARNESS_PAUSE_AT_PCT` from `commands/z-implement-all.md`, `skills/z-implement-all/SKILL.md`, `README.md`. Sweep exports.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase3-decisions-final.md:3:## D1. Delete `Z_HARNESS_PAUSE_AT_PCT` outright
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:18:- All references to `Z_HARNESS_PAUSE_AT_PCT` are removed across the three files (grep returns zero hits).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:19:- `usage_pause` event name no longer mentioned anywhere as the active emission name (a one-line "(deprecated; replaced by `compaction_pause`)" note is acceptable in the README event-type table if such a table exists).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:36:- No code path emits `usage_pause` anymore.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md:177:- `grep -r Z_HARNESS_PAUSE_AT_PCT exports/` returns zero hits.
./z-harness/plans/compaction-cadence/archive/tasks/T001/diff.patch:17:-- `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/compaction-cadence/archive/tasks/T001/diff.patch:39:-8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
./z-harness/plans/compaction-cadence/archive/tasks/T001/diff.patch:103:-8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase1-context.md:7:| `/z-implement-all` | per-task loop, batches ≤3 parallel tracks | `Z_HARNESS_PAUSE_AT_PCT=90` at batch boundary (spec only — never fires) | between task batches; before reviewer spawn |
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase1-context.md:20:- **0 `usage_pause` events** across full history → confirms the guard never fires; the signal `Z_HARNESS_PAUSE_AT_PCT` reads doesn't exist.
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase1-context.md:26:1. The `Z_HARNESS_PAUSE_AT_PCT` block can be deleted, not preserved. The "usage_pause" event type stays (still useful if we ever get a real signal), but the trigger does not.
./exports/agy/prompts/skill-z-plan.md:37:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase0-premise.md:5:1. **Delete usage-% awareness** from `/z-implement-all` (and any other commands that reference `Z_HARNESS_PAUSE_AT_PCT` or "current usage %"). The orchestrator cannot read its own token usage; the guard never functioned.
./exports/agy/prompts/skill-z-plan-split.md:51:9. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly (see Early-exit telemetry contract below). (User resumes by re-invoking with the same topic.)
./exports/agy/prompts/skill-z-plan-split.md:83:- `usage_paused` — Usage-limit guard fired (Setup step 9 or mid-run). Emit `phase_end` for the currently-active phase before returning.
./z-harness/plans/mr-style-reviewer/archive/tasks/T004/review.response.md:2565:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./exports/codex/prompts/z-plan-split.md:48:9. Usage-limit guard: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If usage ≥ threshold, do not dispatch new phases; emit `usage_pause`, push-notify, finalize cleanly (see Early-exit telemetry contract below). (User resumes by re-invoking with the same topic.)
./exports/codex/prompts/z-plan-split.md:80:- `usage_paused` — Usage-limit guard fired (Setup step 9 or mid-run). Emit `phase_end` for the currently-active phase before returning.
./exports/codex/prompts/z-plan.md:34:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:2335:commands/z-plan.md:37:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/mr-style-reviewer/archive/tasks/T014/review.response.md:2353:commands/z-implement-all.md:145:8. **Usage-limit guard policy.** Read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). At each batch boundary, check whether Claude Code surfaces current usage %. If ≥ this threshold: emit a `usage_pause` event, push-notify ("Usage at <N>%; pausing. Reply or re-invoke `/z-implement-all` to resume."), finalize the loop cleanly (no new dispatch; in-flight tasks complete), and exit. Re-invocation picks up from current TASKS.md state — no manual recovery needed.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.prompt.md:46: - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1585:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:1902:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/20260522T172231Z-review/cumulative.diff:2301:+- `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/diff.patch:35: - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:87:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.prompt.md:398:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/delta-v2.patch:28:  - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/diff-v1.patch:34: - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:43:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff.patch:359:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:102:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:413:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/review.response.md:742:    37	7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:43:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T005/diff-v1.patch:354:+7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.response.md:61: - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/tasks/T006/review.response.md:797: - `Z_HARNESS_PAUSE_AT_PCT` — default `90`. Pause new phase dispatch when Claude Code usage hits this %.
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:700:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
./z-harness/plans/brainstorm-and-research/archive/tasks/T003/review.response.md:964:7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).

codex
- **Major**: [commands/z-plan.md](/Users/zeke/dev/z-harness/commands/z-plan.md:45) and [skills/z-plan/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan/SKILL.md:38) still document an active `Z_HARNESS_PAUSE_AT_PCT` usage guard that emits `usage_pause`. Suggested fix: remove the same dead guard language there, or explicitly narrow T001’s acceptance to `/z-implement-all` only and leave a follow-up task for `/z-plan`.

- **Major**: [commands/z-plan-split.md](/Users/zeke/dev/z-harness/commands/z-plan-split.md:51) and [skills/z-plan-split/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-split/SKILL.md:52) still contain active usage-limit guard instructions and `usage_pause` emission language. Suggested fix: delete those active guard references, and update any related early-exit event text to the replacement event or a deprecated note.

- **Major**: exported prompt copies under `exports/agy/prompts/` and `exports/codex/prompts/` still contain active `Z_HARNESS_PAUSE_AT_PCT` / `usage_pause` guard text, so regenerated or packaged prompts will preserve the deleted behavior. Suggested fix: sweep the export files or regenerate them from corrected source after removing the active guard references.
tokens used
54,972
- **Major**: [commands/z-plan.md](/Users/zeke/dev/z-harness/commands/z-plan.md:45) and [skills/z-plan/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan/SKILL.md:38) still document an active `Z_HARNESS_PAUSE_AT_PCT` usage guard that emits `usage_pause`. Suggested fix: remove the same dead guard language there, or explicitly narrow T001’s acceptance to `/z-implement-all` only and leave a follow-up task for `/z-plan`.

- **Major**: [commands/z-plan-split.md](/Users/zeke/dev/z-harness/commands/z-plan-split.md:51) and [skills/z-plan-split/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-split/SKILL.md:52) still contain active usage-limit guard instructions and `usage_pause` emission language. Suggested fix: delete those active guard references, and update any related early-exit event text to the replacement event or a deprecated note.

- **Major**: exported prompt copies under `exports/agy/prompts/` and `exports/codex/prompts/` still contain active `Z_HARNESS_PAUSE_AT_PCT` / `usage_pause` guard text, so regenerated or packaged prompts will preserve the deleted behavior. Suggested fix: sweep the export files or regenerate them from corrected source after removing the active guard references.
