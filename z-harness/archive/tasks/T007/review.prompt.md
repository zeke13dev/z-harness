You are reviewing code that Claude just wrote for task T007: Migrate /z-plan (notify gate ONLY).

Spec excerpt (notify gate only migration):
- Both commands/z-plan.md AND skills/z-plan/SKILL.md gain setup snippet (after RUN= line): `export Z_HARNESS_RUN="$RUN"` then `eval "$(... config.py export-env)"`.
- Every existing PushNotification (3 per file) wrapped with `should-notify --event <kind>` guard; event kinds from {approval, phase_end, error}.
- NO changes to doc-fetcher dispatch logic — /z-plan is a heavy flow; docs.always_apply does not apply.
- Z_HARNESS_NOTIFY prose references replaced by pointer to docs/human/config.md.
- Both files symmetric.

Acceptance criteria:
- Both commands/z-plan.md AND skills/z-plan/SKILL.md gain setup snippet: `export Z_HARNESS_RUN="$RUN"` then `eval "$(... config.py export-env)"`.
- Every existing PushNotification (3 per file) wrapped with `should-notify --event <kind>` guard; event kinds from {approval, phase_end, error}.
- NO changes to doc-fetcher dispatch logic — /z-plan is a heavy flow; docs.always_apply does not apply.
- Z_HARNESS_NOTIFY prose references replaced by pointer to docs/human/config.md.
- Both files symmetric.

Diff (primary artifact):

```diff
diff --git a/commands/z-plan.md b/commands/z-plan.md
index d33ae82..7eb50de 100644
--- a/commands/z-plan.md
+++ b/commands/z-plan.md
@@ -22,6 +22,11 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
 2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
 3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
+4a. Export run id and resolve config:
+    ```bash
+    export Z_HARNESS_RUN="$RUN"
+    eval "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" export-env)"
+    ```
 5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
@@ -41,7 +46,7 @@ Strict, multi-phase. Do not skip phases. Do not write production code — `/z-pl
      touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
    fi
    ```
-6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
+6. Notification policy is resolved from config via the `export-env` step above. See `docs/human/config.md` for knob details (`notify.level`).
 7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
 8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
 9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
@@ -213,7 +218,10 @@ Show `decisions.md` to the user. They are the gate:
 
 **Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.
 
-Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.
+Block here until the user has approved the decisions doc.
+```bash
+[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: decisions ready for approval>
+```
 
 ## Phase 3 — Bundled cross-LLM consultation
 
@@ -237,7 +245,9 @@ If anything is still unclear about scope, constraints, or success criteria — a
 
 ## Phase 5 — Present + approve
 
-If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."
+```bash
+[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event approval)" = yes ] && <PushNotification: "Decisions ready for review.">
+```
 
 Present a **concise** decisions summary: one bullet per decision (what, why, what was rejected). Separate **Shortcuts** section: what's being skipped, robust alternative, cost of the shortcut.
 
@@ -306,7 +316,10 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
 
 Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
 
-Log run end. Send a `PushNotification` if policy ≠ `off` with FOUR recommendations:
+Log run end. Send a PushNotification (guarded by notify level) with FOUR recommendations:
+```bash
+[ "$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py" should-notify --event phase_end)" = yes ] && <PushNotification: plan complete message below>
+```
 ```
 Plan complete. <N> tasks queued.
```

Scrutinize rigorously for:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Event kind mapping accuracy (Phase 2.5=approval, Phase 5=approval, Phase 9=phase_end per SPEC)

**Key focus checks:**
- All 3 PushNotification calls in diff are wrapped? (Should be line 223, 249, 321 in commands/z-plan.md; symmetric in SKILL.md)
- Event kinds match {approval, phase_end, error}; semantically correct per phase?
- Setup snippet lands AFTER existing RUN= line? (It does, at "4a")
- No Z_HARNESS_NOTIFY references remain?
- Doc-fetcher dispatch at line 50/7 is UNCHANGED?

OUTPUT BUDGET — respect strictly: <8000 chars, blockers/majors only.
