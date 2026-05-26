You are reviewing code that Claude just wrote for task T007: Validate route coverage and scenarios.

Review ROUND v3. Scope this review ONLY to whether the two prior major findings have been fixed. Do not re-review unrelated route-block quality or pre-existing issues outside these two items.

Prior majors to verify:
1. Restore `Z_HARNESS_PAUSE_AT_PCT` / `usage_pause` guard in canonical z-plan command/skill and regenerated exports.
2. Convert docs-staleness branch from direct `/z-maintain-docs` halt into route-decision flow with `route-decision.md`, `plan_route_decision`, and AskUser/no-auto-execute semantics.

Spec (targeted excerpt):

Contextual exits are not peers in the normal planning matrix. They are recommended only when their required preconditions are true:

- `/z-audit-plan` - only when `SPEC.md`, `PLAN.md`, and `TASKS.md` exist, or immediately after a plan is completed.
- `/z-fix` - only when the user has a concrete bug hypothesis or diagnosis.
- `/z-debug` - only when the user has an observed bug/symptom and root cause is unknown.
- `/z-amend` - only when an existing plan artifact needs modification.
- `/z-maintain-docs` - only when docs staleness or doc drift blocks or weakens planning.

## Route Decision Contract

Every participant that decides to bail or recommend another workflow must:

1. Write a route artifact under the active run archive.
2. Emit `plan_route_decision`.
3. Present an AskUser handoff gate unless the command is already in a terminal hard-refusal branch.
4. Stop the current workflow if the user chooses to switch.
5. Preserve existing command-specific telemetry and run-end events.


Emit:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_route_decision \
  "$(printf '{"from_command":"%s","to_command":"%s","route_class":"%s","reason_codes":%s,"signals":%s,"confidence":"%s","classifier_used":%s,"artifact_path":"%s","route_chain":%s,"user_choice":"%s"}' ...)"
```

Required fields:

- `from_command`: current command, such as `/z-plan-light`.
- `to_command`: recommended target command.
- `route_class`: `primary` or `contextual`.
- `reason_codes`: JSON array of stable strings.
- `signals`: JSON object with deterministic signal values.
- `confidence`: `high`, `medium`, or `low`.
- `classifier_used`: boolean.
- `artifact_path`: route artifact path relative to repo root.
- `route_chain`: JSON array of prior route hops.
- `user_choice`: `switch`, `continue`, `abandon`, or `not_asked`.


- `tiny_task`
- `small_fix`
- `medium_plan`
- `large_split`
- `needs_research`
- `needs_brainstorm`
- `existing_plan_audit`
- `existing_plan_amend`
- `diagnosed_bug`
- `unknown_bug`
- `docs_stale`
- `docs_drift`


The route check should collect these signals opportunistically from already-known information. It must not perform expensive exploration just to route.

- `candidate_files`: integer or `null`.
- `expected_tasks`: integer or `null`.
- `non_obvious_decisions`: integer or `null`.
- `cluster_seams`: integer or `null`.
- `cross_module`: boolean.
- `schema_or_persistence`: boolean.
- `public_api_or_wire_format`: boolean.
- `terrain_uncertain`: boolean.
- `approach_uncertain`: boolean.
- `has_bug_diagnosis`: boolean.
- `has_unknown_bug_symptom`: boolean.
- `has_existing_plan`: boolean.
- `has_fix_artifact`: boolean.
- `docs_stale_or_drifted`: boolean.

Signal definitions:

- `candidate_files`: count of files already identified from direct references, docs/precontext, quick grep, or existing task blocks. Use `null` if not yet known.
- `expected_tasks`: estimated task count from plan shape or existing `TASKS.md`. Use `null` before planning if not reasonably estimable.
- `non_obvious_decisions`: count using `/z-plan` decision rules.
- `cluster_seams`: count of separable ownership areas with distinct file/module responsibilities. Use `null` if not assessed.
- `terrain_uncertain`: true when the command cannot cite relevant source facts or docs/precontext are missing/stale for the topic.
- `approach_uncertain`: true when there are multiple plausible framings with materially different plan implications.
- `docs_stale_or_drifted`: true when docs freshness gate fires, doc-fetcher returns `DRIFT WARNING`, or plan/audit evidence contradicts docs.



- No automatic cross-command execution in v1.
- Commands remain standalone after export.
- Existing hard safety gates stay stricter than route recommendations.
- `/z-research` never recommends an implementation approach inside `RESEARCH.md`.
- `/z-audit-plan` remains read-only.
- `planning-router` is advisory; the orchestrator owns the final call.
- Existing telemetry is preserved.

## Edge Cases

- Existing plan artifacts plus a new broad task: prefer `/z-amend` if modifying that plan, otherwise `/z-plan` with a new slug.
- Stale docs plus urgent planning: preserve user override path and emit `doc_drift_acknowledged`.
- Ambiguous prompt like "make this better": route to `/z-research` or ask the user unless known files/scope make `/z-plan` obvious.

Relevant docs invariants (targeted excerpts):
=== commands/z-plan.md targeted excerpts ===
nds under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
   Then log provider resolution (once per run, guarded against re-emission):
   ```bash
   if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN"
     touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
   fi
   ```
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` dir

---

ge_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meanin

=== skills/z-plan/SKILL.md targeted excerpts ===
"$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` dir

---

ge_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meanin

=== docs/llm/commands.json invariants/gotchas excerpt ===
, not by constructing z-harness/<slug> paths directly. New canonical path: ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>/. Commands must try the new path first; on miss, resolve_plan_path falls back to the legacy z-harness/<slug>/ path and warns once per process (Z_HARNESS_LEGACY_WARNED guard) with the exact migration command: scripts/migrate-plan-layout.sh <slug>.",
    "Review-family commands preserve evidence artifacts and promote only actionable findings into task-shaped artifacts. Spec gaps route through /z-amend; review-all must not directly mutate SPEC.md or canonical TASKS.md.",
    "Planning-family route bails write route-decision.md, emit plan_route_decision with route_class/reason_codes/signals/confidence/classifier_used/artifact_path/route_chain/user_choice, present an AskUser handoff gate, and never auto-execute another command."
  ],
  "gotchas": [
    "Orchestrating large plans directly in the main thread is context-heavy; delegate to subagents.",
    "Promoted review artifacts such as REVIEW-TASKS.md and MR-REVIEW.md are applied with /z-implement-all --tasks <path>, not by appending directly to canonical TASKS.md.",
    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /

---

hoice, present an AskUser handoff gate, and never auto-execute another command."
  ],
  "gotchas": [
    "Orchestrating large plans directly in the main thread is context-heavy; delegate to subagents.",
    "Promoted review artifacts such as REVIEW-TASKS.md and MR-REVIEW.md are applied with /z-implement-all --tasks <path>, not by appending directly to canonical TASKS.md.",
    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, and /z-research; contextual exits are /z-audit-plan, /z-fix, /z-debug, /z-amend, and /z-maintain-docs.",
    "/z-audit-plan is contextual only and requires existing plan artifacts; when no plan exists it routes to /z-plan instead of auditing."
  ],
  "memories": []
}


=== docs/llm/skills.json invariants/gotchas excerpt ===
   "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
    "Phase telemetry (log-phase.sh start/end) is mandatory for every skill execution.",
    "Review-generated spec-gap tasks are inputs to z-amend and must not authorize implementers to mutate planning artifacts directly.",
    "All skills implement idempotent run patterns; re-running modifies only targeted resources.",
    "z-suggest-memory is the sole path for creating, editing, or deleting memories[] entries; doc-updater only copies them verbatim.",
    "Planning-family skills share the route policy: route bails write route-decision.md, emit plan_route_decision, preserve existing telemetry, present an AskUser handoff, and stop instead of auto-running the target command."
  ],
  "gotchas": [
    "z-implement-all --tasks <path> skips slug discovery, tree validation, and ack/force-partial gates; $BASE is derived from the task file's parent directory.",
    "z-plan-split uses two distinct per-cluster identifiers: cluster_id (C1..CN) for telemetry, cluster_slug (kebab-case) for on-disk paths - never swap them.",
    "z-implement-all hard caps (MAX_ATTEMPTS=2, MAX_TASK_WALL_MS=45min, MAX_DISTI

---

r already has a hypothesis, skill exits with /z-fix recommendation.",
    "z-review-all Phase 3.5 TESTS.md suite run is a blocker gate - any test failure halts the review before consultants are spawned.",
    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists.",
    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, and /z-research; contextual exits are /z-audit-plan, /z-fix, /z-debug, /z-amend, and /z-maintain-docs.",
    "Contextual exits require their preconditions: /z-audit-plan needs existing SPEC/PLAN/TASKS, /z-amend needs an existing plan to modify, /z-fix needs a diagnosis, /z-debug needs an unknown-cause symptom, and /z-maintain-docs needs relevant docs drift."
  ],
  "memories": []
}



Acceptance criteria for T007:
- Sentinel search confirms `PLAN_ROUTE_CHECK_START` and `PLAN_ROUTE_CHECK_END` in all intended canonical sources.
- Scenario checklist from SPEC is manually verified in the implementation summary.
- Route telemetry fields and reason-code enums are consistent across route blocks.
- No route block says switching automatically runs another command.
- No route block makes `/z-audit-plan` a fresh-intent front-door planner.

Delta patch (primary artifact; v3 changes only):

--- z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch	2026-05-24 17:47:24
+++ z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch	2026-05-24 17:49:51
@@ -1,34 +1,29 @@
-diff --git a/exports/agy/.agent/skills/z-plan/SKILL.md b/exports/agy/.agent/skills/z-plan/SKILL.md
-index 72dd206..8852950 100644
---- a/exports/agy/.agent/skills/z-plan/SKILL.md
-+++ b/exports/agy/.agent/skills/z-plan/SKILL.md
-@@ -34,15 +34,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    ```
-    Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+diff --git a/commands/z-plan.md b/commands/z-plan.md
+index 0f7879b..3ead417 100644
+--- a/commands/z-plan.md
++++ b/commands/z-plan.md
+@@ -44,12 +44,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -57,6 +56,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -65,6 +60,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -48,35 +43,68 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -82,7 +101,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
+@@ -292,12 +307,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- ## Phase 0 — Premise check
+ Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
+-Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
++Log run end. Send a `PushNotification` if policy ≠ `off` with FOUR recommendations:
+ ```
+ Plan complete. <N> tasks queued.
  
- Before any planning, ask:
+ Recommended:
+   /compact          — free planning context before next phase
++  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
+   /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
+   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
+ ```
+diff --git a/exports/agy/.agent/skills/z-plan/SKILL.md b/exports/agy/.agent/skills/z-plan/SKILL.md
+index 72dd206..c041a77 100644
+--- a/exports/agy/.agent/skills/z-plan/SKILL.md
++++ b/exports/agy/.agent/skills/z-plan/SKILL.md
+@@ -36,12 +36,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
+ 6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+-9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
+     - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
+@@ -57,6 +52,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
-@@ -98,7 +117,7 @@ Checkpoint: `phase0-premise.md`.
+ Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
- ## Phase 1 — Exploration
++<!-- PLAN_ROUTE_CHECK_START -->
++## Plan Route Check
++
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++
++Deterministic routes:
++- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
++- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
++- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
++- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
++- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
++- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
++
++Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
++
++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
++
++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
++<!-- PLAN_ROUTE_CHECK_END -->
++
+ ## Phase telemetry (mandatory)
  
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
+ At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
+@@ -284,12 +299,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -113,7 +132,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
-@@ -284,12 +303,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -91,36 +119,31 @@
    /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
  ```
 diff --git a/exports/agy/.agent/workflows/z-plan.md b/exports/agy/.agent/workflows/z-plan.md
-index aabfa12..c047ce3 100644
+index aabfa12..241ecac 100644
 --- a/exports/agy/.agent/workflows/z-plan.md
 +++ b/exports/agy/.agent/workflows/z-plan.md
-@@ -41,15 +41,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    fi
-    ```
+@@ -43,12 +43,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -64,6 +63,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -64,6 +59,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -140,35 +163,8 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -89,7 +108,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
+@@ -291,12 +306,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- ## Phase 0 — Premise check
- 
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
- 
- Before any planning, ask:
- 
-@@ -105,7 +124,7 @@ Checkpoint: `phase0-premise.md`.
- 
- ## Phase 1 — Exploration
- 
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
- 
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -120,7 +139,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
-@@ -291,12 +310,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -183,36 +179,31 @@
    /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
  ```
 diff --git a/exports/agy/prompts/skill-z-plan.md b/exports/agy/prompts/skill-z-plan.md
-index 2030ba7..16557ba 100644
+index 2030ba7..b5430d8 100644
 --- a/exports/agy/prompts/skill-z-plan.md
 +++ b/exports/agy/prompts/skill-z-plan.md
-@@ -34,15 +34,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    ```
-    Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+@@ -36,12 +36,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -57,6 +56,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -57,6 +52,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -232,35 +223,8 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -82,7 +101,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
+@@ -284,12 +299,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- ## Phase 0 — Premise check
- 
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
- 
- Before any planning, ask:
- 
-@@ -98,7 +117,7 @@ Checkpoint: `phase0-premise.md`.
- 
- ## Phase 1 — Exploration
- 
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
- 
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -113,7 +132,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
-@@ -284,12 +303,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -275,36 +239,31 @@
    /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
  ```
 diff --git a/exports/agy/prompts/z-plan.md b/exports/agy/prompts/z-plan.md
-index 551c4b8..7b39285 100644
+index 551c4b8..a7a2405 100644
 --- a/exports/agy/prompts/z-plan.md
 +++ b/exports/agy/prompts/z-plan.md
-@@ -42,15 +42,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    fi
-    ```
+@@ -44,12 +44,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -65,6 +64,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -65,6 +60,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -324,35 +283,8 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -90,7 +109,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
+@@ -292,12 +307,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- ## Phase 0 — Premise check
- 
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
- 
- Before any planning, ask:
- 
-@@ -106,7 +125,7 @@ Checkpoint: `phase0-premise.md`.
- 
- ## Phase 1 — Exploration
- 
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
- 
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -121,7 +140,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
-@@ -292,12 +311,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -367,36 +299,31 @@
    /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
  ```
 diff --git a/exports/codex/prompts/z-plan.md b/exports/codex/prompts/z-plan.md
-index 2fe5cf4..0c414c4 100644
+index 2fe5cf4..906ffad 100644
 --- a/exports/codex/prompts/z-plan.md
 +++ b/exports/codex/prompts/z-plan.md
-@@ -31,15 +31,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    ```
-    Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+@@ -33,12 +33,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -54,6 +53,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -54,6 +49,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -416,35 +343,8 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -79,7 +98,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
+@@ -281,12 +296,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- ## Phase 0 — Premise check
- 
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
- 
- Before any planning, ask:
- 
-@@ -95,7 +114,7 @@ Checkpoint: `phase0-premise.md`.
- 
- ## Phase 1 — Exploration
- 
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
- 
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -110,7 +129,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- <!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
-@@ -281,12 +300,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -459,36 +359,31 @@
    /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
  ```
 diff --git a/exports/cursor/.cursor/rules/z-plan.mdc b/exports/cursor/.cursor/rules/z-plan.mdc
-index 1a8c911..4e363b9 100644
+index 1a8c911..65eea85 100644
 --- a/exports/cursor/.cursor/rules/z-plan.mdc
 +++ b/exports/cursor/.cursor/rules/z-plan.mdc
-@@ -34,15 +34,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    ```
-    Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+@@ -36,12 +36,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -57,6 +56,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -57,6 +52,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -508,35 +403,8 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -82,7 +101,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
- 
- ## Phase 0 — Premise check
- 
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
+@@ -284,12 +299,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- Before any planning, ask:
- 
-@@ -98,7 +117,7 @@ Checkpoint: `phase0-premise.md`.
- 
- ## Phase 1 — Exploration
- 
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
- 
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -113,7 +132,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- <!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->
-@@ -284,12 +303,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -551,7 +419,7 @@
    /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
  ```
 diff --git a/skills/z-plan/SKILL.md b/skills/z-plan/SKILL.md
-index 8ad9942..96ce70b 100644
+index 8ad9942..e2e3f53 100644
 --- a/skills/z-plan/SKILL.md
 +++ b/skills/z-plan/SKILL.md
 @@ -1,4 +1,5 @@
@@ -560,33 +428,28 @@
  description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
  argument-hint: <feature or task description>
  ---
-@@ -34,15 +35,14 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
-    ```
-    Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
+@@ -36,12 +37,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
  6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
--7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
--8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
+ 7. Usage-limit guard policy: read env `Z_HARNESS_PAUSE_AT_PCT` (default `90`). If Claude Code surfaces a usage indicator and current usage ≥ this %, **don't dispatch new phases**; instead emit `usage_pause`, push-notify, and finalize whatever phase you're on cleanly. The user resumes by re-invoking `/z-plan` with the same task (or `/z-implement-all` if planning is already done).
+ 8. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 -9. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-+7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
-+8. **Docs-freshness gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, **halt before Phase 1**, push-notify the user, and recommend `/z-maintain-docs` first:
-    ```
-    Docs are <stale_pct>% stale (>= <threshold>% threshold).
-    Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
-    ```
-    The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
--10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
-+9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
+-   ```
+-   Docs are <stale_pct>% stale (>= <threshold>% threshold).
+-   Recommend: /z-maintain-docs to refresh, then resume /z-plan <task>.
+-   ```
+-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
++9. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
+ 10. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
      - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
      - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
-     - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.
-@@ -57,6 +57,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
+@@ -57,6 +53,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
  
  Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
  
 +<!-- PLAN_ROUTE_CHECK_START -->
 +## Plan Route Check
 +
-+Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
++Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
 +
 +Deterministic routes:
 +- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
@@ -606,35 +469,8 @@
  ## Phase telemetry (mandatory)
  
  At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
-@@ -82,7 +102,7 @@ This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`);
+@@ -284,12 +300,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
  
- ## Phase 0 — Premise check
- 
--**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 10, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
-+**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.
- 
- Before any planning, ask:
- 
-@@ -98,7 +118,7 @@ Checkpoint: `phase0-premise.md`.
- 
- ## Phase 1 — Exploration
- 
--**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 10) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
-+**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:
- 
- - **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- - **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.
-@@ -113,7 +133,7 @@ The four resulting cases:
- 
- ### 1a. Dispatch doc-fetcher (if INDEX.json exists)
- 
--If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
-+If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:
- 
- ```
- Agent(
-@@ -284,12 +304,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
- 
  Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
  
 -Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
@@ -650,10 +486,10 @@
  ```
 diff --git a/z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md b/z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md
 new file mode 100644
-index 0000000..a0380a7
+index 0000000..b297fd7
 --- /dev/null
 +++ b/z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md
-@@ -0,0 +1,113 @@
+@@ -0,0 +1,144 @@
 +# T007 Validation Evidence
 +
 +Task: T007 - Validate route coverage and scenarios
@@ -751,6 +587,37 @@
 +
 +No generated export file still contains the stale `THREE recommendations` marker.
 +
++## Final Review-Major Fix Evidence
++
++Reviewer-major fixes were applied only to canonical `/z-plan` sources and regenerated exports.
++
++Usage-limit guard restoration:
++
++- `commands/z-plan.md` and `skills/z-plan/SKILL.md` again include setup step 7: `Z_HARNESS_PAUSE_AT_PCT` / `usage_pause`.
++- Post-export search confirmed the same guard in generated `z-plan` targets:
++  - `exports/cursor/.cursor/rules/z-plan.mdc`
++  - `exports/codex/prompts/z-plan.md`
++  - `exports/agy/.agent/skills/z-plan/SKILL.md`
++  - `exports/agy/.agent/workflows/z-plan.md`
++  - `exports/agy/prompts/skill-z-plan.md`
++  - `exports/agy/prompts/z-plan.md`
++
++Docs-staleness route flow:
++
++- `commands/z-plan.md` and `skills/z-plan/SKILL.md` now describe a `Docs-freshness route gate` that writes `route-decision.md`, emits `plan_route_decision`, uses `reason_codes: ["docs_stale"]`, sets `signals.docs_stale_or_drifted: true`, and presents a user-gated handoff before Phase 1.
++- The branch explicitly says not to execute `/z-maintain-docs` automatically.
++- Search across canonical and generated `z-plan` targets found the route-flow wording and no remaining direct `Recommend: /z-maintain-docs` / `halt before Phase 1` stale-doc branch.
++
++Export command rerun after these final fixes:
++
++```bash
++python3 scripts/export-cursor.py && python3 scripts/export-codex.py && python3 scripts/export-agy.py
++```
++
++Result: all three export scripts completed successfully, with Cursor reporting 58 validated `.mdc` files, Codex reporting 44 validated prompt files plus `AGENTS.md`, and Antigravity reporting 26 workflows, 14 rules, 18 skills, and 58 prompts validated.
++
++`/z-audit-plan` contextual-only spot check still passes: both canonical sources say it is not a front-door planning command, is valid only when plan artifacts exist, and must not execute the next command automatically.
++
 +## Scenario Checklist
 +
 +- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
@@ -766,4 +633,4 @@
 +
 +## Outcome
 +
-+Validation passed after the scoped `skills/z-plan/SKILL.md` consistency fix.
++Validation passed after the scoped `skills/z-plan/SKILL.md` consistency fix and final review-major fixes.


Scrutinize rigorously but only for the two prior majors above.

Report blockers and majors only. If either prior issue remains, give severity, location, and suggested fix. If both prior issues are fixed, respond exactly: `No blockers or majors remain.`
