2026-05-22T05:38:44.366056Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-22T05:38:44.366196Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-22T05:38:44.366223Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e4e31-7410-7850-baf4-67f20276905a
--------
user
You are reviewing a v2 (retry) implementation of task `per-task-model-selection`. The v1 review flagged 4 majors; this review is to confirm they were addressed and to spot any NEW blockers/majors introduced by the fix delta. Do NOT re-flag scope-creep (the doc-fetcher/z-plan Phase 1 changes and the entire z-amend command+skill files are pre-existing uncommitted dirt from a different WIP, NOT part of this fix).

The 4 prior majors and the implementer's claim of fix:
1. /z-amend re-classification was disabled because heuristic #1 treated any existing stamp as user-authored override. Claim: strip the existing **Complexity:** line BEFORE dispatching, unless user explicitly named a tier.
2. Modified-task trigger too narrow (Files/Acceptance/Tests only). Claim: broadened to "any line OTHER than the **Complexity:** line itself" enumerating title, Files, Depends, Acceptance, **Tests:**, **REMOTE_VERIFY:**, **DOCS:**.
3. /z-implement-next had an orphaned retry-override paragraph (single-shot, no auto-retry). Claim: removed orphan, added clarifying paragraph.
4. Missing-stamp fallback under-specified. Claim: added concrete log-event.sh shell snippets in both /z-implement-all and /z-implement-next (and skill mirrors).

SPEC excerpt (FIX.md Approach section):
- /z-plan Phase 8: parallel classifier dispatch, append **Complexity:** stamp.
- /z-amend full-mode Phase 6: re-classify new/modified tasks; preserve untouched stamps; light mode unaffected.
- /z-implement-all + /z-implement-next: read **Complexity:**, pass model="sonnet" for low|medium, model="opus" for high. Missing stamp → default sonnet + log missing_complexity_stamp warning.
- Retry: cycle ≥ 2 always model="opus". Remove Z_HARNESS_RETRY_UPGRADE env var.
- Implementer frontmatter stays model: sonnet as fallback.

Diff (delta v1→v2, focused excerpts):

=== commands/z-amend.md Phase 6 TASKS.md item (and skill mirror identical) ===
- **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.

=== commands/z-implement-all.md step 5 (and skill mirror identical) ===
**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event. Do not block; do not JIT-classify.
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
  ```

**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header is the implementer's signal to apply Opus-level care to the fix.

[Agent() call uses model="<sonnet|opus per the rules above>"]

Replaces previous Z_HARNESS_RETRY_UPGRADE env-var pattern. **User-authored override.** If user writes `**Complexity:** high` directly, classifier preserves it (returns `REASON: user-authored override`).

Cycle ≥ 2 prompt block now passes model="opus" explicitly in the Agent() call.

=== commands/z-implement-next.md (and skill mirror identical) ===
**Pick the implementer model from the task block's `**Complexity:**` stamp**:
- `low` or `medium` → `model="sonnet"`
- `high` → `model="opus"`
- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event:
  ```bash
  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
  ```

[Agent() call uses model="<sonnet|opus per the rules above>"]

This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.

`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"`, re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.

=== commands/z-plan.md Phase 8 (unchanged from v1) ===
**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) once per task in parallel. Parse TIER/REASON, Edit TASKS.md to append `**Complexity:** <tier>`. Log `task_classified` event. If task block already has user-authored stamp, classifier returns `REASON: user-authored override` and you leave it alone.

Confirm whether the 4 prior majors are now resolved. Identify any NEW blockers or majors introduced by THIS delta (the strip-before-dispatch rule, broadened trigger, single-shot clarification, missing-stamp shell snippets).

OUTPUT BUDGET: under 8000 chars. Blockers and majors only. One finding per bullet, two sentences max. If clean, respond exactly: `No blockers or majors found.` (plus optional 1-line note).

codex
I’ll verify the actual command and skill mirror files against the v2 claims, ignoring the unrelated WIP areas you called out. Then I’ll only report blockers or majors introduced by this delta.
exec
/bin/zsh -lc "rg -n \"Re-classify complexity|missing_complexity_stamp|Retry override|single-shot command|Z_HARNESS_RETRY_UPGRADE|Complexity stamp|strip the existing\" commands /Users/zeke/.codex/skills -g 'z-amend*' -g 'z-implement-all*' -g 'z-implement-next*' -g 'z-plan*'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-implement-next.md:50:- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id:
commands/z-implement-next.md:52:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
commands/z-implement-next.md:65:This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
commands/z-implement-next.md:67:`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
commands/z-plan.md:243:**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
commands/z-amend.md:145:   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
commands/z-implement-all.md:163:- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event. Do not block; do not JIT-classify.
commands/z-implement-all.md:165:  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
commands/z-implement-all.md:169:**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
commands/z-implement-all.md:180:This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.

exec
/bin/zsh -lc 'git status --short && git diff -- commands/z-amend.md commands/z-implement-all.md commands/z-implement-next.md commands/z-plan.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
 M README.md
 M agents/implementer.md
 M commands/z-audit.md
 M commands/z-debug.md
 M commands/z-implement-all.md
 M commands/z-implement-next.md
 M commands/z-plan-light.md
 M commands/z-plan.md
 M skills/z-debug/SKILL.md
 M skills/z-implement-all/SKILL.md
 M skills/z-implement-next/SKILL.md
 M skills/z-plan-light/SKILL.md
 M skills/z-plan/SKILL.md
?? agents/complexity-classifier.md
?? agents/doc-fetcher.md
?? commands/z-amend.md
?? commands/z-do.md
?? commands/z-improve.md
?? per-task-model-selection/
?? skills/z-amend/
?? skills/z-do/
?? skills/z-improve/
?? z-harness/
diff --git a/commands/z-implement-all.md b/commands/z-implement-all.md
index 402e972..9afa9c5 100644
--- a/commands/z-implement-all.md
+++ b/commands/z-implement-all.md
@@ -157,17 +157,29 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 
 ### 5. Spawn implementer (fresh context)
 
+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
+- `low` or `medium` → `model="sonnet"`
+- `high` → `model="opus"`
+- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event. Do not block; do not JIT-classify.
+  ```bash
+  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
+    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
+  ```
+
+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
+
 ```
 Agent(
   subagent_type="implementer",
   description="Implement <task-id>",
+  model="<sonnet|opus per the rules above>",
   prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
-**Model-on-retry signal.** If this is the second retry (cycle ≥ 2) after review blockers/majors, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the `Agent()` call so the implementer knows the orchestrator wants Opus-level care for the fix. (The implementer's frontmatter declares `model: sonnet` as default; the env-var is a per-call signal for the agent to read in its prompt construction, not a model override per se. If the harness later supports per-call model override, this maps to that.)
+This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
 
-**`**Complexity:** high` opt-in.** If the user wrote `**Complexity:** high` in the task block, also set the upgrade signal even on first attempt.
+**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
 
 **REMOTE_VERIFY pre-dispatch.** If the task block contains a `**REMOTE_VERIFY:**` line, before parsing the implementer's return, dispatch the `remote-runner` (Haiku) subagent with the verify command. If the remote build fails, treat the implementer return as if it had `STATUS: unable_to_complete` and present the build log excerpt to the user.
 
@@ -234,12 +246,13 @@ cp $BASE/archive/tasks/<task-id>/diff.patch \
    $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch
 ```
 
-Implementer prompt on cycle ≥ 2 is shorter than cycle 1:
+Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
 
 ```
 Agent(
   subagent_type="implementer",
   description="Implement <task-id> v<CYCLE>",
+  model="opus",
   prompt="<task-id> RETRY v<CYCLE>\n\n<task block verbatim — unchanged>\n\nPrior attempt diff (already on disk at $BASE/archive/tasks/<id>/diff-v<CYCLE-1>.patch — READ IT FIRST, then patch ONLY what the reviewer flagged):\n\n=== Reviewer findings to address ===\n<verbatim ≤8K return from codex-reviewer>\n\nDo NOT rewrite from scratch. Apply targeted fixes. Return the same STATUS report shape."
 )
 ```
diff --git a/commands/z-implement-next.md b/commands/z-implement-next.md
index a2a4ebb..e6d7d78 100644
--- a/commands/z-implement-next.md
+++ b/commands/z-implement-next.md
@@ -42,17 +42,29 @@ If TASKS.md is missing or has no pending tasks, tell the user and stop.
 
 **Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.
 
-Spawn the implementer subagent (fresh context):
+Spawn the implementer subagent (fresh context).
+
+**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
+- `low` or `medium` → `model="sonnet"`
+- `high` → `model="opus"`
+- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id:
+  ```bash
+  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
+    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
+  ```
 
 ```
 Agent(
   subagent_type="implementer",
   description="Implement <task-id>",
+  model="<sonnet|opus per the rules above>",
   prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
 )
 ```
 
-If this is a retry after review failure with `cycle ≥ 2`, set env `Z_HARNESS_RETRY_UPGRADE=opus` before the call (per the auto-upgrade-on-retry policy). Also set the env if the task block has `**Complexity:** high`.
+This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
+
+`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
 
 Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.
 
diff --git a/commands/z-plan.md b/commands/z-plan.md
index 6ee87c8..0c65619 100644
--- a/commands/z-plan.md
+++ b/commands/z-plan.md
@@ -32,8 +32,8 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
    Output lands under `z-harness/<slug>/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
 6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
-8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, read it first. It's the cheap ground-truth oracle for Phase 1 Explore — use it to scope which modules to investigate. Treat it as authoritative until evidence in the code contradicts it (log `doc_drift` events when that happens; `/z-maintain-docs` will follow up).
-9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
+8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
    ```
    Docs are <stale_pct>% stale (>= <threshold>% threshold).
    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
@@ -89,18 +89,46 @@ Checkpoint: `phase0-premise.md`.
 
 ## Phase 1 — Exploration
 
-Read the codebase. Use Read/Grep/Glob, and the `Explore` subagent for broad sweeps. Identify: touched files, reusable patterns, constraints (types, framework, tests, perf, security), adjacent code that could regress.
+**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.
 
-**If `docs/llm/INDEX.json` exists, use it first** — it's a cheap structured map of concepts → source files. For each Explore dispatch, include `relevant_concepts: <paths from INDEX.json>` in the prompt so the Explore agent reads those JSON entries first and treats them as scaffolding (saves ~30-50% of broad-repo grep cost). The Explore is still authorized to verify the docs against current code; if it finds drift, it should report it in its return and you log a `doc_drift` event:
+### 1a. Dispatch doc-fetcher (if INDEX.json exists)
 
+If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
+
+```
+Agent(
+  subagent_type="doc-fetcher",
+  description="Doc context for <slug>",
+  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
+)
+```
+
+It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.
+
+If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
 ```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
   '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
 ```
 
-`/z-maintain-docs` later consumes these events to know which concepts need refresh.
+### 1b. Explore for gaps (Haiku by default)
+
+Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.
+
+**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:
+
+```
+Agent(
+  subagent_type="Explore",
+  model: "haiku",
+  description="Find <thing> related to <slug>",
+  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
+)
+```
+
+**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.
 
-**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore is a Claude (Opus by default) repo-mapping pass that consumes 2–3 M tokens of cache-read context. In the data-overhaul run, 5 Explore agents ate 13.9 M tokens — ~93% of the entire planning budget — and the marginal Explore beyond the third surfaced no new findings the prior three missed. If 3 is not enough, prefer running direct Read/Grep/Glob from the orchestrator (which reuses the orchestrator's already-warm context) over spawning a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.
+**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.
 
 Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.
 
@@ -212,6 +240,13 @@ The orchestrator dispatches a `remote-runner` (Haiku) to rsync+build in the sand
 
 **Docs-touched flag.** For any task that touches a user-facing surface (CLI flags, public APIs, configs, schemas), append a `**DOCS:** <concept-slug>` line. This is a hint for `/z-maintain-docs`; not a rigid task on its own.
 
+**Complexity stamp (parallel Haiku classifier).** After writing all task blocks, dispatch the `complexity-classifier` (Haiku) subagent once per task **in parallel** (single message, multiple `Agent()` calls). Each call passes the verbatim task block, `spec_slice_path: $BASE/SPEC.md`, and `repo_root`. Parse each return's `TIER:` and `REASON:` lines, then `Edit` TASKS.md to append a `**Complexity:** <tier>` line to the matching task block. Log a `task_classified` event per task:
+```bash
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" task_classified \
+  "$(printf '{"task":"%s","tier":"%s","reason":%s}' "<task-id>" "<tier>" "$(printf '%s' "<reason>" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
+```
+If a task block already contains a user-authored `**Complexity:** <tier>` line (rare at plan-time, but possible if the user is editing TASKS.md in-flight), the classifier returns `REASON: user-authored override` and you leave the stamp alone. The orchestrator `/z-implement-all` reads this stamp at dispatch time to pick the implementer model (`low|medium` → Sonnet, `high` → Opus).
+
 ## Phase 9 — Finalize archive
 
 Copy `z-harness/$Z_HARNESS_SLUG/{SPEC,PLAN,TASKS}.md` into `z-harness/$Z_HARNESS_SLUG/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).

codex
The command files contain the claimed v2 text for the implement-all/next changes and the z-amend rule. I’m checking the mirrors and the exact surrounding wording now, since review issues here are likely to be instruction ambiguity rather than code syntax.
exec
/bin/zsh -lc "nl -ba skills/z-amend/SKILL.md | sed -n '136,152p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   136	### Full mode
   137	1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
   138	2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
   139	3. **TASKS.md**:
   140	   - Append new tasks with fresh IDs in the appropriate phase block.
   141	   - Edit modified `[ ]` tasks in place.
   142	   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   143	   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   144	   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
   146	
   147	### Light mode
   148	1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.
   149	
   150	### Both modes
   151	After every file edit, run:
   152	```bash

exec
/bin/zsh -lc "nl -ba commands/z-implement-next.md | sed -n '42,70p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba commands/z-implement-all.md | sed -n '157,184p;246,257p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    42	
    43	**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.
    44	
    45	Spawn the implementer subagent (fresh context).
    46	
    47	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
    48	- `low` or `medium` → `model="sonnet"`
    49	- `high` → `model="opus"`
    50	- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id:
    51	  ```bash
    52	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    53	    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
    54	  ```
    55	
    56	```
    57	Agent(
    58	  subagent_type="implementer",
    59	  description="Implement <task-id>",
    60	  model="<sonnet|opus per the rules above>",
    61	  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
    62	)
    63	```
    64	
    65	This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
    66	
    67	`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
    68	
    69	Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.
    70	

 succeeded in 0ms:
   157	
   158	### 5. Spawn implementer (fresh context)
   159	
   160	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
   161	- `low` or `medium` → `model="sonnet"`
   162	- `high` → `model="opus"`
   163	- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event. Do not block; do not JIT-classify.
   164	  ```bash
   165	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
   166	    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
   167	  ```
   168	
   169	**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this command) is the implementer's signal to apply Opus-level care to the fix.
   170	
   171	```
   172	Agent(
   173	  subagent_type="implementer",
   174	  description="Implement <task-id>",
   175	  model="<sonnet|opus per the rules above>",
   176	  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
   177	)
   178	```
   179	
   180	This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
   181	
   182	**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
   183	
   184	**REMOTE_VERIFY pre-dispatch.** If the task block contains a `**REMOTE_VERIFY:**` line, before parsing the implementer's return, dispatch the `remote-runner` (Haiku) subagent with the verify command. If the remote build fails, treat the implementer return as if it had `STATUS: unable_to_complete` and present the build log excerpt to the user.
   246	   $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch
   247	```
   248	
   249	Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
   250	
   251	```
   252	Agent(
   253	  subagent_type="implementer",
   254	  description="Implement <task-id> v<CYCLE>",
   255	  model="opus",
   256	  prompt="<task-id> RETRY v<CYCLE>\n\n<task block verbatim — unchanged>\n\nPrior attempt diff (already on disk at $BASE/archive/tasks/<id>/diff-v<CYCLE-1>.patch — READ IT FIRST, then patch ONLY what the reviewer flagged):\n\n=== Reviewer findings to address ===\n<verbatim ≤8K return from codex-reviewer>\n\nDo NOT rewrite from scratch. Apply targeted fixes. Return the same STATUS report shape."
   257	)

exec
/bin/zsh -lc "nl -ba skills/z-implement-all/SKILL.md | sed -n '157,184p;246,257p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   157	
   158	### 5. Spawn implementer (fresh context)
   159	
   160	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
   161	- `low` or `medium` → `model="sonnet"`
   162	- `high` → `model="opus"`
   163	- **Stamp missing** (legacy plan, or hand-deleted): default to `model="sonnet"` AND log a `missing_complexity_stamp` warning event. Do not block; do not JIT-classify.
   164	  ```bash
   165	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
   166	    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
   167	  ```
   168	
   169	**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
   170	
   171	```
   172	Agent(
   173	  subagent_type="implementer",
   174	  description="Implement <task-id>",
   175	  model="<sonnet|opus per the rules above>",
   176	  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
   177	)
   178	```
   179	
   180	This replaces the previous `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern, which was an advisory care signal only and did not actually change the model. `Agent(...)` supports per-call `model` override directly; that is now the wire.
   181	
   182	**User-authored override.** A user who edits `**Complexity:** high` directly into a task block hand-picks Opus for that task. The classifier preserves user-authored stamps (it returns `REASON: user-authored override`), so the dial is a TASKS.md edit away.
   183	
   184	**REMOTE_VERIFY pre-dispatch.** If the task block contains a `**REMOTE_VERIFY:**` line, before parsing the implementer's return, dispatch the `remote-runner` (Haiku) subagent with the verify command. If the remote build fails, treat the implementer return as if it had `STATUS: unable_to_complete` and present the build log excerpt to the user.
   246	   $BASE/archive/tasks/<task-id>/diff-v$((CYCLE-1)).patch
   247	```
   248	
   249	Implementer prompt on cycle ≥ 2 is shorter than cycle 1. **Pass `model="opus"` on the retry dispatch** per the retry-override rule from step 5 (always Opus on retry, regardless of the task's stamped tier):
   250	
   251	```
   252	Agent(
   253	  subagent_type="implementer",
   254	  description="Implement <task-id> v<CYCLE>",
   255	  model="opus",
   256	  prompt="<task-id> RETRY v<CYCLE>\n\n<task block verbatim — unchanged>\n\nPrior attempt diff (already on disk at $BASE/archive/tasks/<id>/diff-v<CYCLE-1>.patch — READ IT FIRST, then patch ONLY what the reviewer flagged):\n\n=== Reviewer findings to address ===\n<verbatim ≤8K return from codex-reviewer>\n\nDo NOT rewrite from scratch. Apply targeted fixes. Return the same STATUS report shape."
   257	)

exec
/bin/zsh -lc "nl -ba commands/z-amend.md | sed -n '136,152p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   136	### Full mode
   137	1. **SPEC.md** — update only the affected sections. Preserve unrelated content byte-for-byte.
   138	2. **PLAN.md** — update Decisions / Non-goals / Phases sections as listed in `amendment.md`. If a decision is reversed, add a `## Amendments` section at the bottom recording: date, what changed, why (one line each). This gives the archive trail.
   139	3. **TASKS.md**:
   140	   - Append new tasks with fresh IDs in the appropriate phase block.
   141	   - Edit modified `[ ]` tasks in place.
   142	   - Strike-through removed `[ ]` tasks: change `- [ ] T0NN` → `- [~] T0NN ~~<title>~~ (removed in <RUN>)`. Keep them visible — `/z-implement-next` skips `[~]`.
   143	   - For superseded `[x]` tasks: leave them `[x]` and add the new superseding `[ ]` task whose title begins `Supersedes T0NN: ...`.
   144	   - Preserve every `[x]` line untouched unless the user explicitly chose "re-open" in Phase 4.
   145	   - **Re-classify complexity** for new tasks and for `[ ]` tasks whose block changed in any line OTHER than the `**Complexity:**` line itself (title, Files, Depends, Acceptance, `**Tests:**`, `**REMOTE_VERIFY:**`, `**DOCS:**` — any of these can materially shift complexity). For each affected task, **strip the existing `**Complexity:**` line BEFORE dispatching** the `complexity-classifier` (Haiku) subagent — otherwise the classifier's heuristic #1 will return `REASON: user-authored override` and the auto-stamp will never refresh. Exception: if the user *explicitly named* a complexity tier in their amendment instruction (e.g. "and mark T007 as high"), preserve that as a user-authored stamp and skip the classifier. Dispatch in parallel for the affected tasks only; append the new `**Complexity:** <tier>` line per the classifier's return. **Do not re-classify** tasks whose blocks are otherwise unchanged in this amendment — preserve their existing stamp byte-for-byte (avoids stamp churn the user did not ask for). Log one `task_classified` event per re-classified task to `events.jsonl` with `{task, tier, reason, amend_run: "$RUN"}`.
   146	
   147	### Light mode
   148	1. **FIX.md** — update the affected sections (Problem / Root cause / Approach / Files / Acceptance / Cross-LLM consensus). Add an `## Amendments` section at the bottom: date, what changed, why.
   149	
   150	### Both modes
   151	After every file edit, run:
   152	```bash

exec
/bin/zsh -lc "nl -ba skills/z-implement-next/SKILL.md | sed -n '42,70p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    42	
    43	**Discover relevant_docs.** If `docs/llm/INDEX.json` exists, identify concept docs relevant to this task (same logic as `/z-implement-all` step 4b): (a) `**DOCS:** <slug>` lines in task block; (b) `source_file` overlap with the task's `Files:`. Cap at 5 concept paths. Pass as `relevant_docs` below.
    44	
    45	Spawn the implementer subagent (fresh context).
    46	
    47	**Pick the implementer model from the task block's `**Complexity:**` stamp** (stamped by `/z-plan` or `/z-amend`):
    48	- `low` or `medium` → `model="sonnet"`
    49	- `high` → `model="opus"`
    50	- **Stamp missing**: default to `model="sonnet"` and log a `missing_complexity_stamp` warning event with the task id:
    51	  ```bash
    52	  bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" missing_complexity_stamp \
    53	    "$(printf '{"task":"%s","fallback_model":"sonnet"}' "<task-id>")"
    54	  ```
    55	
    56	```
    57	Agent(
    58	  subagent_type="implementer",
    59	  description="Implement <task-id>",
    60	  model="<sonnet|opus per the rules above>",
    61	  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path to z-harness/<slug>>\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants): <paths>"
    62	)
    63	```
    64	
    65	This replaces the prior `Z_HARNESS_RETRY_UPGRADE=opus` env-var pattern; `Agent(...)` supports per-call `model` override directly.
    66	
    67	`/z-implement-next` is a single-shot command and does not auto-retry on Codex review failure. If you want a retry with `model="opus"` (the "always-Opus-on-retry" policy from `/z-implement-all`), re-invoke `/z-implement-next` after manually flipping the task's stamp to `**Complexity:** high`, or run `/z-implement-all` which handles the retry loop internally.
    68	
    69	Implement the task exactly as specified. No scope expansion. If the spec is wrong or ambiguous, **stop and ask the user** rather than improvising. After the answer, **update SPEC.md** to match the resolved decision before continuing — the spec must stay the source of truth.
    70	

codex
No blockers or majors found.

Prior four majors appear resolved in the command files and skill mirrors.
2026-05-22T05:39:30.098309Z ERROR codex_core::session: failed to record rollout items: thread 019e4e31-7410-7850-baf4-67f20276905a not found
tokens used
55,588
No blockers or majors found.

Prior four majors appear resolved in the command files and skill mirrors.
