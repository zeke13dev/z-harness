2026-05-23T05:10:35.164836Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-23T05:10:35.164935Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-23T05:10:35.164945Z ERROR codex_core::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.125.0 (research preview)
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR, /Users/zeke/.codex/memories]
reasoning effort: medium
reasoning summaries: none
session id: 019e533e-099e-7f53-a107-9d4704329336
--------
user
You are reviewing code that Claude just wrote for task T003: Extend /z-implement-all Setup step 2 (slug discovery) to detect MANIFEST.md and walk tree-rooted plans sequentially in MANIFEST run-order. Add --ack and --force-partial flags. Preserve legacy behavior. Preserve mirror byte-identity tolerance (8 lines / 3 hunks).

Spec (excerpt — MANIFEST.md schema, SHARED-CONCERNS.md schema, gates):

## MANIFEST.md schema
YAML frontmatter has status: planning|ready|partial, total_clusters, clusters_ready.
Body has Clusters table with columns: ID | Name | Scope | Path | Status (ready/planning/failed).
"## Run order" section lists clusters in execution order. Cross-cluster parallelism is v2 (sequential only).

## SHARED-CONCERNS.md schema
YAML frontmatter: artifact, slug, generated_at, acknowledged (bool, default false), acknowledged_at, acknowledged_by, overlap_count (N), partial_tree (bool — true iff any cluster has status != ready).
Ack-gate: refuses to start tree if acknowledged: false AND overlap_count > 0. If overlap_count: 0, auto-passes (file still written with acknowledged: true per spec line 195).
Partial-tree gate: if partial_tree: true, refuse unless --force-partial.

Acceptance criteria:
- Setup step 2 extended to detect MANIFEST.md vs legacy TASKS.md per slug.
- For tree-rooted slug, validate in order:
  1. Every cluster path in MANIFEST has finalized TASKS.md (parses, ≥1 task block). planning/failed → cluster_not_ready halt.
  2. find <root>/*/ -name MANIFEST.md → nonempty → tree_depth_exceeded halt with {nested_paths:[...]}.
  3. SHARED-CONCERNS.md exists. overlap_count>0 AND acknowledged!=true → shared_concerns_unacknowledged halt. --ack overrides.
  4. partial_tree:true → partial_tree_blocked halt naming failed clusters. --force-partial overrides.
- On pass: expand into sequential cluster paths in MANIFEST run-order. Iterate sequentially. Intra-cluster N=3 parallel preserved.
- Legacy single-slug unchanged. Multi-slug discovery still works. Mixed legacy+tree work.
- --ack and --force-partial documented.
- Mirror byte-identity preserved: tolerance is exactly 8 lines / 3 hunks. MUST NOT increase diff count.

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/commands/z-implement-all.md b/commands/z-implement-all.md
index 402e972..0026979 100644
--- a/commands/z-implement-all.md
+++ b/commands/z-implement-all.md
@@ -6,16 +6,60 @@ You are the **z-harness `/z-implement-all`** orchestrator. Your job is to drive
 
 Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
+## Flags
+
+- `--ack` — Override the SHARED-CONCERNS.md ack-gate when iterating a tree-rooted plan produced by `/z-plan-split`. Equivalent to manually flipping `acknowledged: true` in the file. No-op for legacy single-slug plans.
+- `--force-partial` — Override the partial-tree gate when iterating a tree-rooted plan whose SHARED-CONCERNS.md has `partial_tree: true` (i.e. one or more clusters failed planning). Implies the user accepts that overlap detection is a lower bound on a partial tree. No-op for legacy single-slug plans.
+
+Both flags are inert for legacy (single-slug) plans and only affect tree-rooted discovery in Setup step 2.
+
 ## Setup
 
 1. `cd` to the repo root. Abort if no `z-harness/` directory.
-2. **Discover plan slug.** Multiple plans may coexist under `z-harness/<slug>/`:
-   - Enumerate subdirs of `z-harness/` containing a `TASKS.md`.
-   - Also check for legacy flat layout (`z-harness/TASKS.md` directly).
-   - One candidate → use it; export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat).
-   - Multiple candidates → `AskUserQuestion` to pick.
+2. **Discover plan slug.** Multiple plans may coexist under `z-harness/<slug>/`. A `<slug>/` may be either a **legacy single-slug plan** (contains `TASKS.md` directly) or a **tree-rooted plan** produced by `/z-plan-split` (contains `MANIFEST.md` + per-cluster subdirectories, each with its own `TASKS.md`):
+
+   **2a. Enumerate candidates.**
+   - For each subdir of `z-harness/`: classify as `tree-rooted` if `<slug>/MANIFEST.md` exists, else `legacy` if `<slug>/TASKS.md` exists, else skip.
+   - Also check for the legacy flat layout (`z-harness/TASKS.md` directly).
    - Zero candidates → tell user to run `/z-plan` first; abort.
-3. From here on, **`BASE`** = `z-harness/$Z_HARNESS_SLUG` (or `z-harness` for legacy). All paths use `$BASE`.
+   - One candidate → use it.
+   - Multiple candidates → `AskUserQuestion` to pick. Mixed legacy + tree-rooted slugs are allowed in the same `/z-implement-all` invocation: the user picks one, validation/expansion below depends on its kind.
+   - Export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat).
+
+   **2b. If chosen slug is tree-rooted (has `<slug>/MANIFEST.md`), validate in order:**
+   1. **Cluster-readiness gate.** Parse MANIFEST.md to enumerate cluster paths. For each cluster, the `Status` column must be `ready`; equivalently, `<slug>/<cluster>/TASKS.md` must exist, parse cleanly, and contain ≥1 task block. Any cluster with `status: planning` or `status: failed` → halt with `cluster_not_ready` event:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" cluster_not_ready \
+        "$(printf '{"slug":"%s","cluster_id":"%s","cluster_status":"%s"}' "$Z_HARNESS_SLUG" "<id>" "<status>")"
+      ```
+      Push-notify the user and abort. (No override flag — failed/planning clusters must be re-run via `/z-plan-split` resume or `/z-plan` on the cluster directly.)
+   2. **Nested-MANIFEST gate (depth invariant).** One-level recursion is invariant per `/z-plan-split` SPEC. Check `find z-harness/$Z_HARNESS_SLUG/*/ -name MANIFEST.md` (excluding the root MANIFEST). If any are found, halt with `tree_depth_exceeded` event:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" tree_depth_exceeded \
+        "$(printf '{"slug":"%s","nested_paths":%s}' "$Z_HARNESS_SLUG" "$NESTED_JSON_ARRAY")"
+      ```
+      Push-notify and abort. No override — a tree-of-trees is structurally unsupported in v1.
+   3. **Shared-concerns ack-gate.** `<slug>/SHARED-CONCERNS.md` must exist (cluster-planner reconciliation writes it unconditionally). Read its YAML frontmatter:
+      - If `overlap_count: 0` → ack-gate auto-passes regardless of `acknowledged`.
+      - Else if `acknowledged: true` → pass.
+      - Else (overlap_count > 0 AND acknowledged != true) → halt with `shared_concerns_unacknowledged` event:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" shared_concerns_unacknowledged \
+        "$(printf '{"slug":"%s","acknowledged":false,"overlap_count":%d}' "$Z_HARNESS_SLUG" "$N")"
+      ```
+      Override: if the user invoked `/z-implement-all --ack`, treat the gate as passed and proceed (still log the event for audit).
+   4. **Partial-tree gate.** If SHARED-CONCERNS.md has `partial_tree: true` (some clusters failed planning, so overlap detection is a lower bound), halt with `partial_tree_blocked` event naming the failed clusters parsed from MANIFEST:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" partial_tree_blocked \
+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
+      ```
+      Override: if the user invoked `/z-implement-all --force-partial`, treat the gate as passed and proceed (log the event for audit).
+
+   **2c. Expand tree-rooted slug into cluster sequence.** On all four validations passing, read MANIFEST's "Run order" section and expand the slug into a sequence of cluster paths `[z-harness/<slug>/<C1>/, z-harness/<slug>/<C2>/, ...]`. Iterate clusters **sequentially**: for each cluster in run-order, treat `BASE = z-harness/<slug>/<cluster-id>` and run the full main loop (steps 1–8) on that cluster's TASKS.md, then advance to the next cluster. Within each cluster, the existing N=3 parallel-batching applies as today (intra-cluster parallelism honored; cross-cluster parallelism is v2).
+
+   **2d. If chosen slug is legacy (TASKS.md directly under it, no MANIFEST.md),** behavior is unchanged: a single `BASE` for the whole run, no tree validation, `--ack` and `--force-partial` are no-ops.
+
+3. From here on, **`BASE`** = `z-harness/$Z_HARNESS_SLUG` for legacy slugs (or `z-harness` for legacy flat). For tree-rooted slugs, `BASE` is rebound per-cluster as the orchestrator iterates the run-order sequence from 2c. All paths use `$BASE`.
 4. Read `$BASE/TASKS.md` once into memory — you'll re-read between batches to pick up status flips. **Do NOT pre-extract SPEC/PLAN slices in main thread** — subagents will Read them directly from `$BASE/SPEC.md` and `$BASE/PLAN.md` themselves. This keeps the orchestrator main-thread context light across many tasks.
 5. **Version stamp + run_start event:**
    ```bash
@@ -157,17 +201,29 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 
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
 
@@ -234,12 +290,13 @@ cp $BASE/archive/tasks/<task-id>/diff.patch \
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
diff --git a/skills/z-implement-all/SKILL.md b/skills/z-implement-all/SKILL.md
index 48fb1a9..fb1d7ff 100644
--- a/skills/z-implement-all/SKILL.md
+++ b/skills/z-implement-all/SKILL.md
@@ -6,16 +6,60 @@ You are the **z-harness `/z-implement-all`** orchestrator. Your job is to drive
 
 Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
+## Flags
+
+- `--ack` — Override the SHARED-CONCERNS.md ack-gate when iterating a tree-rooted plan produced by `/z-plan-split`. Equivalent to manually flipping `acknowledged: true` in the file. No-op for legacy single-slug plans.
+- `--force-partial` — Override the partial-tree gate when iterating a tree-rooted plan whose SHARED-CONCERNS.md has `partial_tree: true` (i.e. one or more clusters failed planning). Implies the user accepts that overlap detection is a lower bound on a partial tree. No-op for legacy single-slug plans.
+
+Both flags are inert for legacy (single-slug) plans and only affect tree-rooted discovery in Setup step 2.
+
 ## Setup
 
 1. `cd` to the repo root. Abort if no `z-harness/` directory.
-2. **Discover plan slug.** Multiple plans may coexist under `z-harness/<slug>/`:
-   - Enumerate subdirs of `z-harness/` containing a `TASKS.md`.
-   - Also check for legacy flat layout (`z-harness/TASKS.md` directly).
-   - One candidate → use it; export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat).
-   - Multiple candidates → `AskUserQuestion` to pick.
+2. **Discover plan slug.** Multiple plans may coexist under `z-harness/<slug>/`. A `<slug>/` may be either a **legacy single-slug plan** (contains `TASKS.md` directly) or a **tree-rooted plan** produced by `/z-plan-split` (contains `MANIFEST.md` + per-cluster subdirectories, each with its own `TASKS.md`):
+
+   **2a. Enumerate candidates.**
+   - For each subdir of `z-harness/`: classify as `tree-rooted` if `<slug>/MANIFEST.md` exists, else `legacy` if `<slug>/TASKS.md` exists, else skip.
+   - Also check for the legacy flat layout (`z-harness/TASKS.md` directly).
    - Zero candidates → tell user to run `/z-plan` first; abort.
-3. From here on, **`BASE`** = `z-harness/$Z_HARNESS_SLUG` (or `z-harness` for legacy). All paths use `$BASE`.
+   - One candidate → use it.
+   - Multiple candidates → `AskUserQuestion` to pick. Mixed legacy + tree-rooted slugs are allowed in the same `/z-implement-all` invocation: the user picks one, validation/expansion below depends on its kind.
+   - Export `Z_HARNESS_SLUG=<slug>` (or leave unset for legacy flat).
+
+   **2b. If chosen slug is tree-rooted (has `<slug>/MANIFEST.md`), validate in order:**
+   1. **Cluster-readiness gate.** Parse MANIFEST.md to enumerate cluster paths. For each cluster, the `Status` column must be `ready`; equivalently, `<slug>/<cluster>/TASKS.md` must exist, parse cleanly, and contain ≥1 task block. Any cluster with `status: planning` or `status: failed` → halt with `cluster_not_ready` event:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" cluster_not_ready \
+        "$(printf '{"slug":"%s","cluster_id":"%s","cluster_status":"%s"}' "$Z_HARNESS_SLUG" "<id>" "<status>")"
+      ```
+      Push-notify the user and abort. (No override flag — failed/planning clusters must be re-run via `/z-plan-split` resume or `/z-plan` on the cluster directly.)
+   2. **Nested-MANIFEST gate (depth invariant).** One-level recursion is invariant per `/z-plan-split` SPEC. Check `find z-harness/$Z_HARNESS_SLUG/*/ -name MANIFEST.md` (excluding the root MANIFEST). If any are found, halt with `tree_depth_exceeded` event:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" tree_depth_exceeded \
+        "$(printf '{"slug":"%s","nested_paths":%s}' "$Z_HARNESS_SLUG" "$NESTED_JSON_ARRAY")"
+      ```
+      Push-notify and abort. No override — a tree-of-trees is structurally unsupported in v1.
+   3. **Shared-concerns ack-gate.** `<slug>/SHARED-CONCERNS.md` must exist (cluster-planner reconciliation writes it unconditionally). Read its YAML frontmatter:
+      - If `overlap_count: 0` → ack-gate auto-passes regardless of `acknowledged`.
+      - Else if `acknowledged: true` → pass.
+      - Else (overlap_count > 0 AND acknowledged != true) → halt with `shared_concerns_unacknowledged` event:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" shared_concerns_unacknowledged \
+        "$(printf '{"slug":"%s","acknowledged":false,"overlap_count":%d}' "$Z_HARNESS_SLUG" "$N")"
+      ```
+      Override: if the user invoked `/z-implement-all --ack`, treat the gate as passed and proceed (still log the event for audit).
+   4. **Partial-tree gate.** If SHARED-CONCERNS.md has `partial_tree: true` (some clusters failed planning, so overlap detection is a lower bound), halt with `partial_tree_blocked` event naming the failed clusters parsed from MANIFEST:
+      ```bash
+      bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "orchestration" partial_tree_blocked \
+        "$(printf '{"slug":"%s","failed_cluster_ids":%s}' "$Z_HARNESS_SLUG" "$FAILED_JSON_ARRAY")"
+      ```
+      Override: if the user invoked `/z-implement-all --force-partial`, treat the gate as passed and proceed (log the event for audit).
+
+   **2c. Expand tree-rooted slug into cluster sequence.** On all four validations passing, read MANIFEST's "Run order" section and expand the slug into a sequence of cluster paths `[z-harness/<slug>/<C1>/, z-harness/<slug>/<C2>/, ...]`. Iterate clusters **sequentially**: for each cluster in run-order, treat `BASE = z-harness/<slug>/<cluster-id>` and run the full main loop (steps 1–8) on that cluster's TASKS.md, then advance to the next cluster. Within each cluster, the existing N=3 parallel-batching applies as today (intra-cluster parallelism honored; cross-cluster parallelism is v2).
+
+   **2d. If chosen slug is legacy (TASKS.md directly under it, no MANIFEST.md),** behavior is unchanged: a single `BASE` for the whole run, no tree validation, `--ack` and `--force-partial` are no-ops.
+
+3. From here on, **`BASE`** = `z-harness/$Z_HARNESS_SLUG` for legacy slugs (or `z-harness` for legacy flat). For tree-rooted slugs, `BASE` is rebound per-cluster as the orchestrator iterates the run-order sequence from 2c. All paths use `$BASE`.
 4. Read `$BASE/TASKS.md` once into memory — you'll re-read between batches to pick up status flips. **Do NOT pre-extract SPEC/PLAN slices in main thread** — subagents will Read them directly from `$BASE/SPEC.md` and `$BASE/PLAN.md` themselves. This keeps the orchestrator main-thread context light across many tasks.
 5. **Version stamp + run_start event:**
    ```bash
@@ -157,17 +201,29 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 
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
+**Retry override.** If this dispatch is cycle ≥ 2 (i.e. a retry after Codex review blockers/majors), force `model="opus"` regardless of the stamp. The in-prompt `RETRY v<N>` header (see the cycle-≥-2 prompt block later in this skill) is the implementer's signal to apply Opus-level care to the fix.
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
 
@@ -234,12 +290,13 @@ cp $BASE/archive/tasks/<task-id>/diff.patch \
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

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

NOTE: T003's stated scope is Setup step 2 (slug discovery, MANIFEST detection, validation gates, flags) and preserving the mirror tolerance. The diff also contains changes to "### 5. Spawn implementer" (Complexity stamp model selection, model="opus" retry override). Evaluate whether this is scope creep beyond T003's acceptance criteria. The mirror tolerance constraint (≤8 lines / 3 hunks) is about command↔skill byte-identity drift, not about how many lines T003 may add — but extra unrelated changes in BOTH files double the audit surface.

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
- Report blockers and majors only. Skip minors and nits unless a "minor" hides a correctness bug — promote to major.
- One finding per bullet. Two sentences max per finding.
- No re-stating of code already in the diff. No summaries. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus optional 1-line note).

codex
- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2c: expansion uses `z-harness/<slug>/<cluster-id>/`, but MANIFEST has a `Path` column and acceptance says validate every cluster path. Use the MANIFEST `Path` value for `BASE`, and validate run-order IDs resolve to exactly one table row.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b/2c: no requirement that `## Run order` is a bijection over the Clusters table. Add validation that run-order contains every cluster exactly once, has no unknown IDs, and has no duplicates before executing; otherwise halt with a structured event.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b gates: the cluster-readiness gate aborts on `planning`/`failed` before the partial-tree gate can honor `--force-partial`. If `--force-partial` is intended to allow partial trees, readiness validation must still require finalized TASKS for clusters that will run, but must not unconditionally halt on failed/planning clusters that are excluded or explicitly forced past.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b ack-gate: `--ack` says “still log the event for audit,” but the only documented event is the halt event with `acknowledged:false`, which would falsely record a blocked condition. Add a distinct audit event such as `shared_concerns_ack_override` or include `override:true` and do not describe it as a halt.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b partial-tree gate: `--force-partial` has the same audit problem as `--ack`; logging `partial_tree_blocked` while proceeding corrupts downstream event semantics. Use a separate override event or explicit `override:true`.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b shared concerns: missing `SHARED-CONCERNS.md` is stated as required but has no halt behavior or event. Add an explicit `shared_concerns_missing` halt before reading frontmatter.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b: the MANIFEST frontmatter schema fields are not validated at all. Validate `status`, `total_clusters`, and `clusters_ready` against the clusters table so corrupt or stale manifests do not pass discovery.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, “Spawn implementer”: the complexity/model-selection changes are unrelated to T003 and alter runtime behavior outside Setup step 2. Remove them from this task or split them into a separate reviewed change, especially because they expand both mirrored files’ audit surface without supporting the acceptance criteria.
2026-05-23T05:11:00.172223Z ERROR codex_core::session: failed to record rollout items: thread 019e533e-099e-7f53-a107-9d4704329336 not found
tokens used
8,191
- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2c: expansion uses `z-harness/<slug>/<cluster-id>/`, but MANIFEST has a `Path` column and acceptance says validate every cluster path. Use the MANIFEST `Path` value for `BASE`, and validate run-order IDs resolve to exactly one table row.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b/2c: no requirement that `## Run order` is a bijection over the Clusters table. Add validation that run-order contains every cluster exactly once, has no unknown IDs, and has no duplicates before executing; otherwise halt with a structured event.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b gates: the cluster-readiness gate aborts on `planning`/`failed` before the partial-tree gate can honor `--force-partial`. If `--force-partial` is intended to allow partial trees, readiness validation must still require finalized TASKS for clusters that will run, but must not unconditionally halt on failed/planning clusters that are excluded or explicitly forced past.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b ack-gate: `--ack` says “still log the event for audit,” but the only documented event is the halt event with `acknowledged:false`, which would falsely record a blocked condition. Add a distinct audit event such as `shared_concerns_ack_override` or include `override:true` and do not describe it as a halt.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b partial-tree gate: `--force-partial` has the same audit problem as `--ack`; logging `partial_tree_blocked` while proceeding corrupts downstream event semantics. Use a separate override event or explicit `override:true`.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b shared concerns: missing `SHARED-CONCERNS.md` is stated as required but has no halt behavior or event. Add an explicit `shared_concerns_missing` halt before reading frontmatter.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, Setup 2b: the MANIFEST frontmatter schema fields are not validated at all. Validate `status`, `total_clusters`, and `clusters_ready` against the clusters table so corrupt or stale manifests do not pass discovery.

- **Major**: `commands/z-implement-all.md` / `skills/z-implement-all/SKILL.md`, “Spawn implementer”: the complexity/model-selection changes are unrelated to T003 and alter runtime behavior outside Setup step 2. Remove them from this task or split them into a separate reviewed change, especially because they expand both mirrored files’ audit surface without supporting the acceptance criteria.
