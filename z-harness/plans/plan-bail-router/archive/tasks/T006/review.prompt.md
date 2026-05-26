You are reviewing code that Claude just wrote for task T006: Regenerate multi-IDE exports.

Spec (excerpt):
221: ## Route Check Insertion Points
222: 
223: Each command should run route checks at predictable points:
224: 
225: - `/z-do`: after premise/doc grounding and before approach.md; again before implementation if file count or decisions grew.
226: - `/z-plan-light`: after quick exploration and before Phase 2 decision selection; again before inline implementation if scope grows.
227: - `/z-plan`: after setup/precontext/docs gates and before Phase 1 Explore; again after decisions if task count/scope implies split.
228: - `/z-plan-split`: after cluster proposal, before user confirmation; route too-few clusters to `/z-plan`, too-uncertain seams to `/z-research`.
229: - `/z-brainstorm`: after scaffolding and before ideator dispatch; route to `/z-research` if terrain is unknown or to `/z-plan` if framing is already clear.
230: - `/z-research`: before cost gate if the request is clearly not research; after finalization only as next-step recommendation. Never inside `RESEARCH.md` findings.
231: - `/z-audit-plan`: during setup if no plan artifacts are found; after final report when presenting action choices.
232: 
233: ## `planning-router` Agent
234: 
235: Add `agents/planning-router.md`.
236: 
237: Frontmatter:
238: 
239: ```yaml
240: ---
241: name: planning-router
242: description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
243: tools: Read, Grep, Glob
244: model: haiku
245: ---
246: ```
247: 
248: Inputs:
249: 
250: - `current_command`
251: - `task_or_topic`
252: - `signals_json`
253: - `route_chain_json`
254: - `repo_root`
255: - optional `existing_artifacts`
256: 
257: Return shape:
258: 
259: ```text
260: STATUS: routed | ask_user | bad_input
261: RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
262: ROUTE_CLASS: primary | contextual | none
263: CONFIDENCE: high | medium | low
264: REASON_CODES: <comma-separated stable reason codes>
265: REASON: <one line, <=160 chars>
266: ```
267: 
268: `STATUS: routed` requires `RECOMMENDED` to be a concrete command and `ROUTE_CLASS` to be `primary` or `contextual`. `STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe; it must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`. `STATUS: bad_input` is only for malformed or missing required inputs; it must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.
269: 
270: Rules:
271: 
272: - Do not edit files.
273: - Do not call other agents.
274: - Do not run expensive repo sweeps.
275: - Prefer deterministic thresholds supplied by the caller over inventing facts.
276: - If the input is malformed, return `STATUS: bad_input`; do not invent a command recommendation.
277: - If loop risk is present, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
278: - If the caller provides `route_chain_json`, inspect it before recommending a target.
279: - If the return is malformed, the caller ignores it and falls back to deterministic route or AskUser choice.
280: 
281: ## Command and Skill Source Changes
282: 
283: Add a compact `## Plan Route Check` section to the following source files:
284: 
285: - `commands/z-do.md`
286: - `commands/z-plan-light.md`
287: - `commands/z-plan.md`
288: - `commands/z-plan-split.md`
289: - `commands/z-brainstorm.md`
290: - `commands/z-research.md`
291: - `commands/z-audit-plan.md`
292: - `skills/z-do/SKILL.md`
293: - `skills/z-plan-light/SKILL.md`
294: - `skills/z-plan/SKILL.md`
295: - `skills/z-plan-split/SKILL.md`
296: - `skills/z-brainstorm/SKILL.md`
297: - `skills/z-research/SKILL.md`
298: - `skills/z-audit-plan/SKILL.md`
299: 
300: The embedded block must be bracketed with HTML comments:
301: 
302: ```markdown
303: <!-- PLAN_ROUTE_CHECK_START -->
304: ...
305: <!-- PLAN_ROUTE_CHECK_END -->
306: ```
307: 
308: The block must:
309: 
310: - State primary route targets and contextual exits.
311: - List deterministic signals relevant to that command.
312: - State when to call `planning-router`.
313: - State the AskUser handoff gate.
314: - State loop prevention.
315: - State telemetry and route artifact requirements.
316: 
317: Command-specific requirements:
318: 
319: - `/z-do`: preserve hard caps. Add downward/upward clarity: if task is no-code research or approach selection, route to `/z-research` or `/z-brainstorm`; if larger than `/z-do`, route to `/z-plan-light` or `/z-plan`.
320: - `/z-plan-light`: preserve current thresholds but allow routing down to `/z-do` before writing `FIX.md`, up to `/z-plan`, sideways to `/z-research` or `/z-brainstorm`, and contextual to `/z-fix` or `/z-debug` for bug workflows.
321: - `/z-plan`: add early route check after setup/precontext detection and before Phase 1. It may route down to `/z-plan-light`, up to `/z-plan-split`, sideways to `/z-research` or `/z-brainstorm`, or contextual to `/z-audit-plan` only after artifacts exist.
322: - `/z-plan-split`: preserve 2-6 cluster invariant. Route too-few clusters to `/z-plan`; route too-many clusters to topic narrowing or `/z-research`; route unknown seams to `/z-research`.
323: - `/z-brainstorm`: before ideator dispatch, route to `/z-research` if terrain is unknown, to `/z-plan` if framing is already clear, or to `/z-plan-light` for a small concrete fix.
324: - `/z-research`: preserve no-recommendation invariant inside `RESEARCH.md`. Route only before research starts or after finalization as a next-step recommendation; do not recommend an approach inside the research note.
325: - `/z-audit-plan`: route to `/z-plan` when no plan artifacts exist, to `/z-amend` for accepted plan changes, and to `/z-maintain-docs` for doc drift that blocks audit confidence. It is read-only.
326: 
327: ## Docs and Memory Changes
328: 
329: Update docs/memory sources so future doc-fetcher calls know the router exists:
330: 
331: - `docs/human/commands.md`
332: - `docs/human/skills.md`
333: - `docs/human/agents.md`
334: - `docs/llm/INDEX.json`
335: - `docs/llm/commands.json`
336: - `docs/llm/skills.json`
337: - `docs/llm/agents.json`
338: 
339: Required doc content:
340: 
341: - Add `z-audit-plan` to command and skill concept source lists where missing.
342: - Specifically add `commands/z-audit-plan.md` to `docs/llm/commands.json` and `docs/llm/INDEX.json`.
343: - Specifically add `skills/z-audit-plan/SKILL.md` to `docs/llm/skills.json` and `docs/llm/INDEX.json`.
344: - Add `planning-router` to agent concept source lists.
345: - Add route policy summary and telemetry invariant.
346: - Mark docs touched for `/z-maintain-docs` follow-up if implementation changes source files faster than docs can be refreshed.
347: 
348: ## Export Changes
349: 
350: After canonical files are updated, regenerate exports with the existing export pipeline:
351: 
352: ```bash
353: python3 scripts/export-cursor.py
354: python3 scripts/export-codex.py
355: python3 scripts/export-agy.py
356: ```
357: 
358: Acceptance:
359: 
360: - Exported Cursor, Codex, and Antigravity prompts/rules include the route check sections and `planning-router` agent.
361: - No generated export file is hand-edited as the source of truth.
362: - Export churn is expected in generated files for touched commands, skills, and the new agent. Unexpected export changes outside those surfaces should be reviewed before acceptance.
363: 
364: ## Invariants
365: 
366: - No automatic cross-command execution in v1.
367: - Commands remain standalone after export.
368: - Existing hard safety gates stay stricter than route recommendations.
369: - `/z-research` never recommends an implementation approach inside `RESEARCH.md`.
370: - `/z-audit-plan` remains read-only.
371: - `planning-router` is advisory; the orchestrator owns the final call.
372: - Existing telemetry is preserved.

Relevant docs invariants:
commands invariant: Planning-family route bails write route-decision.md, emit plan_route_decision with route_class/reason_codes/signals/confidence/classifier_used/artifact_path/route_chain/user_choice, present an AskUser handoff gate, and never auto-execute another command.
agents invariant: planning-router is advisory only; callers own route artifacts, plan_route_decision telemetry, AskUser handoffs, and final routing decisions.
skills invariant: Planning-family skills share the route policy: route bails write route-decision.md, emit plan_route_decision, preserve existing telemetry, present an AskUser handoff, and stop instead of auto-running the target command.

Acceptance criteria:
- `python3 scripts/export-cursor.py` succeeds.
- `python3 scripts/export-codex.py` succeeds.
- `python3 scripts/export-agy.py` succeeds.
- Generated exports include route checks for all touched commands/skills.
- Generated exports include the `planning-router` agent where target format supports agents/rules.

Diff (primary artifact - focus your scrutiny on what changed):

diff --git a/exports/agy/.agent/rules/z-harness-consultant-primary.md b/exports/agy/.agent/rules/z-harness-consultant-primary.md
index 8994f30..fa29a11 100644
--- a/exports/agy/.agent/rules/z-harness-consultant-primary.md
+++ b/exports/agy/.agent/rules/z-harness-consultant-primary.md
@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_primary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/agy/.agent/rules/z-harness-consultant-secondary.md b/exports/agy/.agent/rules/z-harness-consultant-secondary.md
index 1177133..2268570 100644
--- a/exports/agy/.agent/rules/z-harness-consultant-secondary.md
+++ b/exports/agy/.agent/rules/z-harness-consultant-secondary.md
@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_secondary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/agy/.agent/rules/z-harness-implementer.md b/exports/agy/.agent/rules/z-harness-implementer.md
index 2a0051e..23f225d 100644
--- a/exports/agy/.agent/rules/z-harness-implementer.md
+++ b/exports/agy/.agent/rules/z-harness-implementer.md
@@ -2,12 +2,12 @@
 trigger: always_on
 ---
 
-You implement **exactly one task** from `$Z_HARNESS_PLAN_DIR/TASKS.md` and return a structured summary. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
+You implement **exactly one task** from the task block the orchestrator passes you and return a structured summary. The task may originate from canonical `$Z_HARNESS_PLAN_DIR/TASKS.md` or from a promoted review artifact such as `REVIEW-TASKS.md` / `MR-REVIEW.md` when `/z-implement-all --tasks <path>` is used. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
 
 ## Inputs from caller
 
-- **Task ID** (e.g. `T004`)
-- **Task block** verbatim from TASKS.md (files, deps, acceptance criteria)
+- **Task ID** (e.g. `T004`, `T-REV-001`, or `T-MR-001`)
+- **Task block** verbatim from the selected task file (files, deps, acceptance criteria)
 - **`$BASE` path** (e.g. `$Z_HARNESS_PLAN_DIR`) — read SPEC.md / PLAN.md yourself from `$BASE/SPEC.md` and `$BASE/PLAN.md`. The orchestrator no longer extracts slices for you; this keeps the orchestrator's context light. Read only the sections relevant to your task.
 - **`relevant_docs`** (paths, may be empty) — list of `docs/llm/<concept>.json` and `docs/human/<concept>.md` files relevant to this task (discovered by the orchestrator via `**DOCS:**` tags and source-file overlap with `docs/llm/INDEX.json`). **Read each LLM-tier JSON first** — they're small (1-3 KB), state invariants, cross-references, gotchas, and "consumed_by" relationships you may not see by just reading the task's own files. The human-tier markdown is supplementary if the JSON is unclear. If your edits invalidate any claim in a relevant doc, flag it in your `ISSUES:` return so `/z-maintain-docs` can refresh that concept.
 - **`tests_md_path`** (path, may be empty) — `$BASE/TESTS.md` if `/z-test` was run for this plan. If the task block contains a `**Tests:** TEST-001, TEST-004, ...` line, **read TESTS.md** and grep for each listed `## TEST-NNN` heading. Each TEST-NNN entry specifies an `Invariant:`, a `Failure class:`, a `Target file:`, a `Setup:`, and an `Assertion:`. You must produce actual test code at `Target file:` that implements the entry's `Assertion:` against the production code you're writing in this same task. The test must fail if a code change violates the named invariant / failure class — not just pass on the current implementation. If the target file does not yet exist in a recognized test directory, create it following the repo's existing test conventions (look at neighboring tests for fixture patterns).
diff --git a/exports/agy/.agent/rules/z-harness-reviewer.md b/exports/agy/.agent/rules/z-harness-reviewer.md
index e9e46bc..59a71b1 100644
--- a/exports/agy/.agent/rules/z-harness-reviewer.md
+++ b/exports/agy/.agent/rules/z-harness-reviewer.md
@@ -22,11 +22,16 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in. Set it now — check-timeout.sh
+# keys its per-run timeout_availability marker on it, and without it the
+# event isn't emitted. The reviewer is typically dispatched per-task, so
+# pass "tasks/<task-id>" if that's the scope you want the event written to;
+# otherwise the run-id of the parent /z-implement-all call.
+RUN="<run-id or tasks/<task-id> from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/agy/.agent/skills/z-amend/SKILL.md b/exports/agy/.agent/skills/z-amend/SKILL.md
index 12e1654..35a3601 100644
--- a/exports/agy/.agent/skills/z-amend/SKILL.md
+++ b/exports/agy/.agent/skills/z-amend/SKILL.md
@@ -13,6 +13,8 @@ $ARGUMENTS
 
 This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.
 
+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
+
 ## Phase 0 — Discover plan slug
 
 Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to amend:
diff --git a/exports/agy/.agent/skills/z-brainstorm/SKILL.md b/exports/agy/.agent/skills/z-brainstorm/SKILL.md
index b24f4e7..740dd2d 100644
--- a/exports/agy/.agent/skills/z-brainstorm/SKILL.md
+++ b/exports/agy/.agent/skills/z-brainstorm/SKILL.md
@@ -39,6 +39,26 @@ $ARGUMENTS
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.
+
+Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
+- Route a framing that is already clear and ready for task planning to `/z-plan`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/.agent/skills/z-do/SKILL.md b/exports/agy/.agent/skills/z-do/SKILL.md
index db7b1a9..baa23a1 100644
--- a/exports/agy/.agent/skills/z-do/SKILL.md
+++ b/exports/agy/.agent/skills/z-do/SKILL.md
@@ -16,7 +16,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -26,18 +27,38 @@ $ARGUMENTS
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    ```
-5. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
+- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
+- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
+- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
+- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 If at any point you discover:
 
-- **>3 files** need editing → recommend `/z-plan-light`
-- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs) → recommend `/z-plan-light`
-- **Cross-module / cross-crate impact** OR **schema change** → recommend `/z-plan`
-- User says "this might be bigger than I thought" → bail
+- **>3 files** need editing
+- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
+- **Cross-module / cross-crate impact** OR **schema change**
+- User says "this might be bigger than I thought"
+
+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
 
-→ Halt: write a one-paragraph `z-harness/adhoc/archive/$RUN/escalation.md`, log `do_escalation`, push-notify, suggest the appropriate command. Do not improvise.
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise check (mandatory, quick)
 
@@ -72,7 +93,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -85,9 +106,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -153,7 +173,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/exports/agy/.agent/skills/z-implement-all/SKILL.md b/exports/agy/.agent/skills/z-implement-all/SKILL.md
index f74b6f0..9321d9c 100644
--- a/exports/agy/.agent/skills/z-implement-all/SKILL.md
+++ b/exports/agy/.agent/skills/z-implement-all/SKILL.md
@@ -11,12 +11,23 @@ Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
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
@@ -104,8 +115,14 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
 
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
@@ -154,7 +171,7 @@ Repeat until no eligible task remains or you halt:
 
 ### 1. Pick next task
 
-Re-read `TASKS.md`. Build a quick eligibility check:
+Re-read `$TASKS_FILE`. Build a quick eligibility check:
 
 - Status is `[ ]` (pending)
 - **Every** dependency listed under "Depends on" is `[x]` (done) — go by task-level deps, not phase headings (phases mislead — e.g. T006 depends on T010+T011 even though they're in different phases)
@@ -191,7 +208,7 @@ Critical: **never retry a skip-flagged task in the same run** unless the user pi
 
 ### 3. Mark in-progress
 
-Edit `$BASE/TASKS.md`: flip the chosen task's `[ ]` to `[~]`. Log:
+Edit `$TASKS_FILE`: flip the chosen task's `[ ]` to `[~]`. Log:
 ```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
 ```
@@ -250,7 +267,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
@@ -389,7 +406,7 @@ If `$BASE/test-runner.json` is absent OR the task block has no `**Tests:**` line
 
 ### 8. Mark done
 
-1. Flip `[~]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
+1. Flip `[~]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
 2. Write per-task summary file `$BASE/archive/tasks/<task-id>/SUMMARY.md` with outcome + counts. Future references to this task pull from the file rather than re-loading the full reviewer return into main thread.
 3. Log:
 ```bash
@@ -405,7 +422,7 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tas
 
 When the loop exits (no more eligible tasks, or you halted):
 
-1. Re-read `TASKS.md` for final counts: `done`, `pending`, `in_progress`, `skipped`.
+1. Re-read `$TASKS_FILE` for final counts: `done`, `pending`, `in_progress`, `skipped`.
 2. Write a summary message to the user:
    - Counts
    - Skipped tasks with reasons (REMOTE / wall-clock / human action required)
diff --git a/exports/agy/.agent/skills/z-plan-light/SKILL.md b/exports/agy/.agent/skills/z-plan-light/SKILL.md
index b0a188f..9abde43 100644
--- a/exports/agy/.agent/skills/z-plan-light/SKILL.md
+++ b/exports/agy/.agent/skills/z-plan-light/SKILL.md
@@ -1,6 +1,6 @@
 ---
 name: z-plan-light
-description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i...
+description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa...
 ---
 
 You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.
@@ -11,7 +11,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -19,7 +19,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -29,10 +30,25 @@ This command is for **small, focused changes**. If at any phase you realize the
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    ```
-6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
-7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
+7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
+- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
+- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
+- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
+- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 At any phase, if you discover:
 
@@ -41,7 +57,12 @@ At any phase, if you discover:
 - **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
 - **The user explicitly says** "this might be bigger than I thought"
 
-→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.
+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
+
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise + quick exploration (combined)
 
@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -168,8 +189,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -215,7 +236,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.
diff --git a/exports/agy/.agent/skills/z-plan-split/SKILL.md b/exports/agy/.agent/skills/z-plan-split/SKILL.md
index 11ccb0a..f1e7c00 100644
--- a/exports/agy/.agent/skills/z-plan-split/SKILL.md
+++ b/exports/agy/.agent/skills/z-plan-split/SKILL.md
@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
 If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
+
+Deterministic routes:
+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
+
+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ### 1c. Write proposal artifact
 
 Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
diff --git a/exports/agy/.agent/skills/z-plan/SKILL.md b/exports/agy/.agent/skills/z-plan/SKILL.md
index 72dd206..5884f6e 100644
--- a/exports/agy/.agent/skills/z-plan/SKILL.md
+++ b/exports/agy/.agent/skills/z-plan/SKILL.md
@@ -57,6 +57,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
 Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
+- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
+- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
+- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
+- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/.agent/skills/z-research/SKILL.md b/exports/agy/.agent/skills/z-research/SKILL.md
index e1b3ad8..61cdd14 100644
--- a/exports/agy/.agent/skills/z-research/SKILL.md
+++ b/exports/agy/.agent/skills/z-research/SKILL.md
@@ -44,6 +44,26 @@ Strict, multi-phase. Do not skip phases. `/z-research` produces a research note
 - `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.
+
+Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
+- Route clearly framed planning work with enough terrain to `/z-plan`.
+- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/.agent/skills/z-review-all/SKILL.md b/exports/agy/.agent/skills/z-review-all/SKILL.md
index bd8a7df..5adcf6d 100644
--- a/exports/agy/.agent/skills/z-review-all/SKILL.md
+++ b/exports/agy/.agent/skills/z-review-all/SKILL.md
@@ -135,6 +135,16 @@ Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcrip
 
 ## Phase 5 — Aggregate findings
 
+Before promotion, classify each accepted finding using the shared review-family promotion contract:
+
+- `implementation_drift` → candidate fixup task.
+- `spec_gap` → amendment proposal task that routes through `/z-amend`; never edit `SPEC.md` directly.
+- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
+- `premise_failure` → escalation section, not implementer work.
+- `observation` → keep in `findings.md` only.
+
+Every promoted finding must include source, severity, evidence, the "one reason this might be wrong" pushback, files, disposition, and acceptance criteria.
+
 Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:
 
 ```markdown
@@ -173,21 +183,84 @@ Diff stats: <X files, Y additions, Z deletions>
 
 Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.
 
-## Phase 6 — Present + ask what to do
+## Phase 6 — Promote findings to review tasks
+
+Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.
+
+Use this structure:
+
+```markdown
+---
+artifact: review-tasks
+slug: <slug>
+run_id: <RRUN>
+source_findings: archive/<RRUN>/findings.md
+drift_findings: <n>
+spec_gap_findings: <m>
+escalations: <k>
+---
+
+# Review Tasks — <slug>
+
+Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:
+
+`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`
+
+## Candidate fixup tasks
+
+### [ ] T-REV-001 — [blocker] <short title>
+- **Class:** implementation_drift
+- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `<path>:<line>` (modified)
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** <verifiable criteria>
+
+## Amendment proposals
+
+### [ ] T-REV-002 — [major] Amend spec: <short title>
+- **Class:** spec_gap
+- **Disposition:** amendment_proposal
+- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.
+
+## Superseding tasks
+
+### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
+- **Class:** completed_task_contradiction
+- **Disposition:** superseding_task
+- **Source:** <finding reference>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** <files to revisit>
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.
+
+## Escalations
+
+- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.
+
+## Report-only observations
+
+- <minor/speculative finding left in findings.md only>
+```
+
+If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.
 
-Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."
+Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."
 
-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
+Present a short summary to the user:
 
-- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
-- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
-- **Both**
-- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
-- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
+- `findings.md` path
+- `REVIEW-TASKS.md` path, if generated
+- top blockers/escalations
+- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first
 
-Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
+Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
 
-**On Ship as-is or after fixup tasks complete**, also push-notify the user:
+**On a clean review or after promoted tasks complete**, also push-notify the user:
 ```
 Final review accepted. Recommended next:
   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
@@ -196,7 +269,7 @@ The implementation is done and reviewed; the docs are what's left.
 
 ## Hard rules
 
-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
 - **Never** run this on an incomplete plan without explicit user override.
 - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
 - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
diff --git a/exports/agy/.agent/workflows/z-audit.md b/exports/agy/.agent/workflows/z-audit.md
index df06609..18adb83 100644
--- a/exports/agy/.agent/workflows/z-audit.md
+++ b/exports/agy/.agent/workflows/z-audit.md
@@ -12,6 +12,15 @@ $ARGUMENTS
 
 This command is **read-only**. Never edit the target. Fixes happen later via `/z-implement-all` consuming the emitted `TASKS.md`.
 
+## Finding promotion contract
+
+`/z-audit` is a producer of the shared review-family promotion contract:
+
+- `REPORT.md` is the evidence artifact. It preserves every accepted finding, consult addition/drop, and the "one reason this might be wrong" pushback.
+- `TASKS.md` is the promotion artifact. It contains only actionable findings that are safe to hand to `/z-implement-all`.
+
+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
+
 ## Setup
 
 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
diff --git a/exports/agy/.agent/workflows/z-brainstorm.md b/exports/agy/.agent/workflows/z-brainstorm.md
index af01e8a..cea3010 100644
--- a/exports/agy/.agent/workflows/z-brainstorm.md
+++ b/exports/agy/.agent/workflows/z-brainstorm.md
@@ -38,6 +38,26 @@ $ARGUMENTS
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.
+
+Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
+- Route a framing that is already clear and ready for task planning to `/z-plan`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/.agent/workflows/z-do.md b/exports/agy/.agent/workflows/z-do.md
index d2bfb95..d7f33bd 100644
--- a/exports/agy/.agent/workflows/z-do.md
+++ b/exports/agy/.agent/workflows/z-do.md
@@ -15,7 +15,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -25,18 +26,38 @@ $ARGUMENTS
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    ```
-5. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
+- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
+- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
+- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
+- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 If at any point you discover:
 
-- **>3 files** need editing → recommend `/z-plan-light`
-- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs) → recommend `/z-plan-light`
-- **Cross-module / cross-crate impact** OR **schema change** → recommend `/z-plan`
-- User says "this might be bigger than I thought" → bail
+- **>3 files** need editing
+- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
+- **Cross-module / cross-crate impact** OR **schema change**
+- User says "this might be bigger than I thought"
+
+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
 
-→ Halt: write a one-paragraph `z-harness/adhoc/archive/$RUN/escalation.md`, log `do_escalation`, push-notify, suggest the appropriate command. Do not improvise.
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise check (mandatory, quick)
 
@@ -71,7 +92,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -84,9 +105,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -152,7 +172,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/exports/agy/.agent/workflows/z-implement-all.md b/exports/agy/.agent/workflows/z-implement-all.md
index 830b5b6..759a6d3 100644
--- a/exports/agy/.agent/workflows/z-implement-all.md
+++ b/exports/agy/.agent/workflows/z-implement-all.md
@@ -276,7 +276,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
diff --git a/exports/agy/.agent/workflows/z-mr-review.md b/exports/agy/.agent/workflows/z-mr-review.md
index 76e9e2c..c0a3e31 100644
--- a/exports/agy/.agent/workflows/z-mr-review.md
+++ b/exports/agy/.agent/workflows/z-mr-review.md
@@ -8,6 +8,16 @@ Arguments (from `$ARGUMENTS`):
 
 $ARGUMENTS
 
+## Finding promotion contract
+
+`/z-mr-review` is a producer of the shared review-family promotion contract:
+
+- The parsed reviewer JSON is the structured finding source.
+- `MR-REVIEW.md` is both the evidence summary and the promotion artifact: ranked findings are emitted as task-shaped blocks that the user can delete before applying survivors.
+- The command preserves its P0-P4 severity model because it is code-quality oriented, but every emitted task block must include source severity, category, file citation, finding detail, and acceptance criteria.
+
+`MR-REVIEW.md` is intentionally separate from canonical plan `TASKS.md`. Users apply survivors with `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`; the implementation orchestrator must treat that path as the task queue while still resolving `$BASE` from the slug for SPEC/PLAN context when present.
+
 ## Argument parsing
 
 Parse `$ARGUMENTS` before doing anything else:
diff --git a/exports/agy/.agent/workflows/z-plan-light.md b/exports/agy/.agent/workflows/z-plan-light.md
index d2a7549..1caf360 100644
--- a/exports/agy/.agent/workflows/z-plan-light.md
+++ b/exports/agy/.agent/workflows/z-plan-light.md
@@ -1,5 +1,5 @@
 ---
-description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i...
+description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa...
 ---
 
 You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.
@@ -10,7 +10,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -18,7 +18,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -28,10 +29,25 @@ This command is for **small, focused changes**. If at any phase you realize the
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    ```
-6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
-7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
+7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
+- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
+- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
+- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
+- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 At any phase, if you discover:
 
@@ -40,7 +56,12 @@ At any phase, if you discover:
 - **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
 - **The user explicitly says** "this might be bigger than I thought"
 
-→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.
+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
+
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise + quick exploration (combined)
 
@@ -62,13 +83,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -167,8 +188,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -214,7 +235,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.
diff --git a/exports/agy/.agent/workflows/z-plan-split.md b/exports/agy/.agent/workflows/z-plan-split.md
index 5d8a343..ac33f3e 100644
--- a/exports/agy/.agent/workflows/z-plan-split.md
+++ b/exports/agy/.agent/workflows/z-plan-split.md
@@ -142,6 +142,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
 If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
+
+Deterministic routes:
+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
+
+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ### 1c. Write proposal artifact
 
 Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
diff --git a/exports/agy/.agent/workflows/z-plan.md b/exports/agy/.agent/workflows/z-plan.md
index aabfa12..b42bdfc 100644
--- a/exports/agy/.agent/workflows/z-plan.md
+++ b/exports/agy/.agent/workflows/z-plan.md
@@ -64,6 +64,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
 Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
+- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
+- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
+- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
+- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
@@ -291,12 +311,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
 
 Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
 
-Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
+Log run end. Send a `PushNotification` if policy ≠ `off` with FOUR recommendations:
 ```
 Plan complete. <N> tasks queued.
 
 Recommended:
   /compact          — free planning context before next phase
+  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
   /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
 ```
diff --git a/exports/agy/.agent/workflows/z-research.md b/exports/agy/.agent/workflows/z-research.md
index 93da486..58b255b 100644
--- a/exports/agy/.agent/workflows/z-research.md
+++ b/exports/agy/.agent/workflows/z-research.md
@@ -43,6 +43,26 @@ Strict, multi-phase. Do not skip phases. `/z-research` produces a research note
 - `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.
+
+Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
+- Route clearly framed planning work with enough terrain to `/z-plan`.
+- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/.agent/workflows/z-review-all.md b/exports/agy/.agent/workflows/z-review-all.md
index 3ad6f73..23160f4 100644
--- a/exports/agy/.agent/workflows/z-review-all.md
+++ b/exports/agy/.agent/workflows/z-review-all.md
@@ -141,6 +141,32 @@ Both consultants are already on `model: haiku` — they just shell out to gemini
 
 Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcripts/` per the consultant's own logging.
 
+## Finding promotion contract
+
+Review-family commands produce two artifact classes:
+
+- **Evidence artifacts** preserve every reviewed finding and the pushback that was applied before trusting it.
+- **Promotion artifacts** contain only actionable candidate work in a `/z-implement-all`-compatible task shape. Users prune or approve these artifacts once, then run `/z-implement-all --tasks <path>` to apply survivors.
+
+Every promoted finding must carry:
+
+- **Source:** the originating run, consultant(s), prong, and finding text or ID.
+- **Class:** `implementation_drift`, `spec_gap`, `completed_task_contradiction`, `premise_failure`, or `observation`.
+- **Severity:** `blocker`, `major`, or `minor`.
+- **Evidence:** path/line citations or diff/spec references.
+- **Pushback:** one concrete reason the finding might be wrong.
+- **Files:** expected edit targets, or `none` if the item is not directly implementable.
+- **Disposition:** `candidate_task`, `amendment_proposal`, `superseding_task`, `escalation`, or `report_only`.
+- **Acceptance:** verifiable completion criteria for executable tasks.
+
+Promotion rules:
+
+- `implementation_drift` → candidate fixup task.
+- `spec_gap` → amendment proposal task that routes through `/z-amend`; never a direct `SPEC.md` edit.
+- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
+- `premise_failure` → escalation section, not implementer work.
+- `observation` → remain in the evidence artifact only.
+
 ## Phase 5 — Aggregate findings
 
 Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:
@@ -181,21 +207,84 @@ Diff stats: <X files, Y additions, Z deletions>
 
 Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.
 
-## Phase 6 — Present + ask what to do
+## Phase 6 — Promote findings to review tasks
+
+Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.
+
+Use this structure:
+
+```markdown
+---
+artifact: review-tasks
+slug: <slug>
+run_id: <RRUN>
+source_findings: archive/<RRUN>/findings.md
+drift_findings: <n>
+spec_gap_findings: <m>
+escalations: <k>
+---
+
+# Review Tasks — <slug>
+
+Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:
+
+`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`
+
+## Candidate fixup tasks
+
+### [ ] T-REV-001 — [blocker] <short title>
+- **Class:** implementation_drift
+- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `<path>:<line>` (modified)
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** <verifiable criteria>
+
+## Amendment proposals
+
+### [ ] T-REV-002 — [major] Amend spec: <short title>
+- **Class:** spec_gap
+- **Disposition:** amendment_proposal
+- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.
+
+## Superseding tasks
+
+### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
+- **Class:** completed_task_contradiction
+- **Disposition:** superseding_task
+- **Source:** <finding reference>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** <files to revisit>
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.
+
+## Escalations
+
+- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.
+
+## Report-only observations
+
+- <minor/speculative finding left in findings.md only>
+```
+
+If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.
 
-Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."
+Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."
 
-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
+Present a short summary to the user:
 
-- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
-- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
-- **Both**
-- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
-- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
+- `findings.md` path
+- `REVIEW-TASKS.md` path, if generated
+- top blockers/escalations
+- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first
 
-Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
+Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
 
-**On Ship as-is or after fixup tasks complete**, also push-notify the user:
+**On a clean review or after promoted tasks complete**, also push-notify the user:
 ```
 Final review accepted. Recommended next:
   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
@@ -204,7 +293,7 @@ The implementation is done and reviewed; the docs are what's left.
 
 ## Hard rules
 
-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
 - **Never** run this on an incomplete plan without explicit user override.
 - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
 - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
diff --git a/exports/agy/agy-plugin.yaml b/exports/agy/agy-plugin.yaml
index e84cd4e..c505c6b 100644
--- a/exports/agy/agy-plugin.yaml
+++ b/exports/agy/agy-plugin.yaml
@@ -15,6 +15,10 @@ workflows:
     source: commands/z-amend.md
     output: .agent/workflows/z-amend.md
     description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
+  - id: z-audit-plan
+    source: commands/z-audit-plan.md
+    output: .agent/workflows/z-audit-plan.md
+    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
   - id: z-audit
     source: commands/z-audit.md
     output: .agent/workflows/z-audit.md
@@ -66,7 +70,7 @@ workflows:
   - id: z-plan-light
     source: commands/z-plan-light.md
     output: .agent/workflows/z-plan-light.md
-    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i..."
+    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
   - id: z-plan-split
     source: commands/z-plan-split.md
     output: .agent/workflows/z-plan-split.md
@@ -150,6 +154,11 @@ rules:
     output: .agent/rules/z-harness-doc-updater.md
     trigger: model_decision
     description: "Sonnet subagent invoked by /z-maintain-docs to refresh ONE doc concept (one human-tier markdown + one llm-tier JSON entry) so they reflect current code. Returns the proposed updates as text (dry-run by default); does NOT write to disk unless expli..."
+  - id: external-lookup
+    source: agents/external-lookup.md
+    output: .agent/rules/z-harness-external-lookup.md
+    trigger: model_decision
+    description: "Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blo..."
   - id: implementer
     source: agents/implementer.md
     output: .agent/rules/z-harness-implementer.md
@@ -160,6 +169,11 @@ rules:
     output: .agent/rules/z-harness-mr-reviewer.md
     trigger: always_on
     description: "Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to reviewer)."
+  - id: planning-router
+    source: agents/planning-router.md
+    output: .agent/rules/z-harness-planning-router.md
+    trigger: model_decision
+    description: "Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only."
   - id: remote-runner
     source: agents/remote-runner.md
     output: .agent/rules/z-harness-remote-runner.md
@@ -183,6 +197,10 @@ skills:
     source: skills/z-amend/SKILL.md
     output: .agent/skills/z-amend/SKILL.md
     description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
+  - id: z-audit-plan
+    source: skills/z-audit-plan/SKILL.md
+    output: .agent/skills/z-audit-plan/SKILL.md
+    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
   - id: z-brainstorm
     source: skills/z-brainstorm/SKILL.md
     output: .agent/skills/z-brainstorm/SKILL.md
@@ -222,7 +240,7 @@ skills:
   - id: z-plan-light
     source: skills/z-plan-light/SKILL.md
     output: .agent/skills/z-plan-light/SKILL.md
-    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i..."
+    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
   - id: z-plan-split
     source: skills/z-plan-split/SKILL.md
     output: .agent/skills/z-plan-split/SKILL.md
diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
index 748cd79..5d8ce6a 100644
--- a/exports/agy/prompts/consultant-primary.md
+++ b/exports/agy/prompts/consultant-primary.md
@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_primary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/agy/prompts/consultant-secondary.md b/exports/agy/prompts/consultant-secondary.md
index b08a472..3f39bfc 100644
--- a/exports/agy/prompts/consultant-secondary.md
+++ b/exports/agy/prompts/consultant-secondary.md
@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_secondary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/agy/prompts/implementer.md b/exports/agy/prompts/implementer.md
index 4ba0f47..047f515 100644
--- a/exports/agy/prompts/implementer.md
+++ b/exports/agy/prompts/implementer.md
@@ -3,12 +3,12 @@ description: Implements a single task from $Z_HARNESS_PLAN_DIR/TASKS.md in a fre
 role: rule
 ---
 
-You implement **exactly one task** from `$Z_HARNESS_PLAN_DIR/TASKS.md` and return a structured summary. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
+You implement **exactly one task** from the task block the orchestrator passes you and return a structured summary. The task may originate from canonical `$Z_HARNESS_PLAN_DIR/TASKS.md` or from a promoted review artifact such as `REVIEW-TASKS.md` / `MR-REVIEW.md` when `/z-implement-all --tasks <path>` is used. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
 
 ## Inputs from caller
 
-- **Task ID** (e.g. `T004`)
-- **Task block** verbatim from TASKS.md (files, deps, acceptance criteria)
+- **Task ID** (e.g. `T004`, `T-REV-001`, or `T-MR-001`)
+- **Task block** verbatim from the selected task file (files, deps, acceptance criteria)
 - **`$BASE` path** (e.g. `$Z_HARNESS_PLAN_DIR`) — read SPEC.md / PLAN.md yourself from `$BASE/SPEC.md` and `$BASE/PLAN.md`. The orchestrator no longer extracts slices for you; this keeps the orchestrator's context light. Read only the sections relevant to your task.
 - **`relevant_docs`** (paths, may be empty) — list of `docs/llm/<concept>.json` and `docs/human/<concept>.md` files relevant to this task (discovered by the orchestrator via `**DOCS:**` tags and source-file overlap with `docs/llm/INDEX.json`). **Read each LLM-tier JSON first** — they're small (1-3 KB), state invariants, cross-references, gotchas, and "consumed_by" relationships you may not see by just reading the task's own files. The human-tier markdown is supplementary if the JSON is unclear. If your edits invalidate any claim in a relevant doc, flag it in your `ISSUES:` return so `/z-maintain-docs` can refresh that concept.
 - **`tests_md_path`** (path, may be empty) — `$BASE/TESTS.md` if `/z-test` was run for this plan. If the task block contains a `**Tests:** TEST-001, TEST-004, ...` line, **read TESTS.md** and grep for each listed `## TEST-NNN` heading. Each TEST-NNN entry specifies an `Invariant:`, a `Failure class:`, a `Target file:`, a `Setup:`, and an `Assertion:`. You must produce actual test code at `Target file:` that implements the entry's `Assertion:` against the production code you're writing in this same task. The test must fail if a code change violates the named invariant / failure class — not just pass on the current implementation. If the target file does not yet exist in a recognized test directory, create it following the repo's existing test conventions (look at neighboring tests for fixture patterns).
diff --git a/exports/agy/prompts/reviewer.md b/exports/agy/prompts/reviewer.md
index 0511cf0..b46d88f 100644
--- a/exports/agy/prompts/reviewer.md
+++ b/exports/agy/prompts/reviewer.md
@@ -23,11 +23,16 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in. Set it now — check-timeout.sh
+# keys its per-run timeout_availability marker on it, and without it the
+# event isn't emitted. The reviewer is typically dispatched per-task, so
+# pass "tasks/<task-id>" if that's the scope you want the event written to;
+# otherwise the run-id of the parent /z-implement-all call.
+RUN="<run-id or tasks/<task-id> from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/agy/prompts/skill-z-amend.md b/exports/agy/prompts/skill-z-amend.md
index e643352..1832b9f 100644
--- a/exports/agy/prompts/skill-z-amend.md
+++ b/exports/agy/prompts/skill-z-amend.md
@@ -13,6 +13,8 @@ $ARGUMENTS
 
 This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.
 
+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
+
 ## Phase 0 — Discover plan slug
 
 Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to amend:
diff --git a/exports/agy/prompts/skill-z-brainstorm.md b/exports/agy/prompts/skill-z-brainstorm.md
index 3623679..21cad99 100644
--- a/exports/agy/prompts/skill-z-brainstorm.md
+++ b/exports/agy/prompts/skill-z-brainstorm.md
@@ -39,6 +39,26 @@ $ARGUMENTS
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.
+
+Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
+- Route a framing that is already clear and ready for task planning to `/z-plan`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/prompts/skill-z-do.md b/exports/agy/prompts/skill-z-do.md
index ae866a2..1c687ef 100644
--- a/exports/agy/prompts/skill-z-do.md
+++ b/exports/agy/prompts/skill-z-do.md
@@ -16,7 +16,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -26,18 +27,38 @@ $ARGUMENTS
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    ```
-5. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
+- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
+- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
+- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
+- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 If at any point you discover:
 
-- **>3 files** need editing → recommend `/z-plan-light`
-- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs) → recommend `/z-plan-light`
-- **Cross-module / cross-crate impact** OR **schema change** → recommend `/z-plan`
-- User says "this might be bigger than I thought" → bail
+- **>3 files** need editing
+- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
+- **Cross-module / cross-crate impact** OR **schema change**
+- User says "this might be bigger than I thought"
+
+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
 
-→ Halt: write a one-paragraph `z-harness/adhoc/archive/$RUN/escalation.md`, log `do_escalation`, push-notify, suggest the appropriate command. Do not improvise.
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise check (mandatory, quick)
 
@@ -72,7 +93,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -85,9 +106,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -153,7 +173,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/exports/agy/prompts/skill-z-implement-all.md b/exports/agy/prompts/skill-z-implement-all.md
index db94962..2bb4581 100644
--- a/exports/agy/prompts/skill-z-implement-all.md
+++ b/exports/agy/prompts/skill-z-implement-all.md
@@ -11,12 +11,23 @@ Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
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
@@ -104,8 +115,14 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
 
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
@@ -154,7 +171,7 @@ Repeat until no eligible task remains or you halt:
 
 ### 1. Pick next task
 
-Re-read `TASKS.md`. Build a quick eligibility check:
+Re-read `$TASKS_FILE`. Build a quick eligibility check:
 
 - Status is `[ ]` (pending)
 - **Every** dependency listed under "Depends on" is `[x]` (done) — go by task-level deps, not phase headings (phases mislead — e.g. T006 depends on T010+T011 even though they're in different phases)
@@ -191,7 +208,7 @@ Critical: **never retry a skip-flagged task in the same run** unless the user pi
 
 ### 3. Mark in-progress
 
-Edit `$BASE/TASKS.md`: flip the chosen task's `[ ]` to `[~]`. Log:
+Edit `$TASKS_FILE`: flip the chosen task's `[ ]` to `[~]`. Log:
 ```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
 ```
@@ -250,7 +267,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
@@ -389,7 +406,7 @@ If `$BASE/test-runner.json` is absent OR the task block has no `**Tests:**` line
 
 ### 8. Mark done
 
-1. Flip `[~]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
+1. Flip `[~]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
 2. Write per-task summary file `$BASE/archive/tasks/<task-id>/SUMMARY.md` with outcome + counts. Future references to this task pull from the file rather than re-loading the full reviewer return into main thread.
 3. Log:
 ```bash
@@ -405,7 +422,7 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tas
 
 When the loop exits (no more eligible tasks, or you halted):
 
-1. Re-read `TASKS.md` for final counts: `done`, `pending`, `in_progress`, `skipped`.
+1. Re-read `$TASKS_FILE` for final counts: `done`, `pending`, `in_progress`, `skipped`.
 2. Write a summary message to the user:
    - Counts
    - Skipped tasks with reasons (REMOTE / wall-clock / human action required)
diff --git a/exports/agy/prompts/skill-z-plan-light.md b/exports/agy/prompts/skill-z-plan-light.md
index 1466119..60148f2 100644
--- a/exports/agy/prompts/skill-z-plan-light.md
+++ b/exports/agy/prompts/skill-z-plan-light.md
@@ -1,5 +1,5 @@
 ---
-description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i...
+description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa...
 role: skill
 ---
 
@@ -11,7 +11,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -19,7 +19,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -29,10 +30,25 @@ This command is for **small, focused changes**. If at any phase you realize the
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    ```
-6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
-7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
+7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
+- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
+- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
+- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
+- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 At any phase, if you discover:
 
@@ -41,7 +57,12 @@ At any phase, if you discover:
 - **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
 - **The user explicitly says** "this might be bigger than I thought"
 
-→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.
+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
+
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise + quick exploration (combined)
 
@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -168,8 +189,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -215,7 +236,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.
diff --git a/exports/agy/prompts/skill-z-plan-split.md b/exports/agy/prompts/skill-z-plan-split.md
index 155e4a9..3742122 100644
--- a/exports/agy/prompts/skill-z-plan-split.md
+++ b/exports/agy/prompts/skill-z-plan-split.md
@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
 If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
+
+Deterministic routes:
+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
+
+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ### 1c. Write proposal artifact
 
 Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
diff --git a/exports/agy/prompts/skill-z-plan.md b/exports/agy/prompts/skill-z-plan.md
index 2030ba7..e54c03a 100644
--- a/exports/agy/prompts/skill-z-plan.md
+++ b/exports/agy/prompts/skill-z-plan.md
@@ -57,6 +57,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
 Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
+- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
+- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
+- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
+- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/prompts/skill-z-research.md b/exports/agy/prompts/skill-z-research.md
index 730f561..fa128f5 100644
--- a/exports/agy/prompts/skill-z-research.md
+++ b/exports/agy/prompts/skill-z-research.md
@@ -44,6 +44,26 @@ Strict, multi-phase. Do not skip phases. `/z-research` produces a research note
 - `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.
+
+Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
+- Route clearly framed planning work with enough terrain to `/z-plan`.
+- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/prompts/skill-z-review-all.md b/exports/agy/prompts/skill-z-review-all.md
index bf6967b..1b9e8a0 100644
--- a/exports/agy/prompts/skill-z-review-all.md
+++ b/exports/agy/prompts/skill-z-review-all.md
@@ -135,6 +135,16 @@ Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcrip
 
 ## Phase 5 — Aggregate findings
 
+Before promotion, classify each accepted finding using the shared review-family promotion contract:
+
+- `implementation_drift` → candidate fixup task.
+- `spec_gap` → amendment proposal task that routes through `/z-amend`; never edit `SPEC.md` directly.
+- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
+- `premise_failure` → escalation section, not implementer work.
+- `observation` → keep in `findings.md` only.
+
+Every promoted finding must include source, severity, evidence, the "one reason this might be wrong" pushback, files, disposition, and acceptance criteria.
+
 Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:
 
 ```markdown
@@ -173,21 +183,84 @@ Diff stats: <X files, Y additions, Z deletions>
 
 Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.
 
-## Phase 6 — Present + ask what to do
+## Phase 6 — Promote findings to review tasks
+
+Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.
+
+Use this structure:
+
+```markdown
+---
+artifact: review-tasks
+slug: <slug>
+run_id: <RRUN>
+source_findings: archive/<RRUN>/findings.md
+drift_findings: <n>
+spec_gap_findings: <m>
+escalations: <k>
+---
+
+# Review Tasks — <slug>
+
+Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:
+
+`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`
+
+## Candidate fixup tasks
+
+### [ ] T-REV-001 — [blocker] <short title>
+- **Class:** implementation_drift
+- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `<path>:<line>` (modified)
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** <verifiable criteria>
+
+## Amendment proposals
+
+### [ ] T-REV-002 — [major] Amend spec: <short title>
+- **Class:** spec_gap
+- **Disposition:** amendment_proposal
+- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.
+
+## Superseding tasks
+
+### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
+- **Class:** completed_task_contradiction
+- **Disposition:** superseding_task
+- **Source:** <finding reference>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** <files to revisit>
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.
+
+## Escalations
+
+- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.
+
+## Report-only observations
+
+- <minor/speculative finding left in findings.md only>
+```
+
+If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.
 
-Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."
+Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."
 
-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
+Present a short summary to the user:
 
-- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
-- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
-- **Both**
-- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
-- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
+- `findings.md` path
+- `REVIEW-TASKS.md` path, if generated
+- top blockers/escalations
+- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first
 
-Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
+Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
 
-**On Ship as-is or after fixup tasks complete**, also push-notify the user:
+**On a clean review or after promoted tasks complete**, also push-notify the user:
 ```
 Final review accepted. Recommended next:
   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
@@ -196,7 +269,7 @@ The implementation is done and reviewed; the docs are what's left.
 
 ## Hard rules
 
-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
 - **Never** run this on an incomplete plan without explicit user override.
 - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
 - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
diff --git a/exports/agy/prompts/z-audit.md b/exports/agy/prompts/z-audit.md
index 4cad2b9..9cc1b1e 100644
--- a/exports/agy/prompts/z-audit.md
+++ b/exports/agy/prompts/z-audit.md
@@ -13,6 +13,15 @@ $ARGUMENTS
 
 This command is **read-only**. Never edit the target. Fixes happen later via `/z-implement-all` consuming the emitted `TASKS.md`.
 
+## Finding promotion contract
+
+`/z-audit` is a producer of the shared review-family promotion contract:
+
+- `REPORT.md` is the evidence artifact. It preserves every accepted finding, consult addition/drop, and the "one reason this might be wrong" pushback.
+- `TASKS.md` is the promotion artifact. It contains only actionable findings that are safe to hand to `/z-implement-all`.
+
+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
+
 ## Setup
 
 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
diff --git a/exports/agy/prompts/z-brainstorm.md b/exports/agy/prompts/z-brainstorm.md
index 9d6a325..bea48af 100644
--- a/exports/agy/prompts/z-brainstorm.md
+++ b/exports/agy/prompts/z-brainstorm.md
@@ -39,6 +39,26 @@ $ARGUMENTS
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.
+
+Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
+- Route a framing that is already clear and ready for task planning to `/z-plan`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/prompts/z-do.md b/exports/agy/prompts/z-do.md
index 2c8c0eb..280ba4c 100644
--- a/exports/agy/prompts/z-do.md
+++ b/exports/agy/prompts/z-do.md
@@ -16,7 +16,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -26,18 +27,38 @@ $ARGUMENTS
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    ```
-5. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
+- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
+- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
+- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
+- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 If at any point you discover:
 
-- **>3 files** need editing → recommend `/z-plan-light`
-- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs) → recommend `/z-plan-light`
-- **Cross-module / cross-crate impact** OR **schema change** → recommend `/z-plan`
-- User says "this might be bigger than I thought" → bail
+- **>3 files** need editing
+- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
+- **Cross-module / cross-crate impact** OR **schema change**
+- User says "this might be bigger than I thought"
+
+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
 
-→ Halt: write a one-paragraph `z-harness/adhoc/archive/$RUN/escalation.md`, log `do_escalation`, push-notify, suggest the appropriate command. Do not improvise.
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise check (mandatory, quick)
 
@@ -72,7 +93,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -85,9 +106,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -153,7 +173,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/exports/agy/prompts/z-implement-all.md b/exports/agy/prompts/z-implement-all.md
index 3981daa..27a336c 100644
--- a/exports/agy/prompts/z-implement-all.md
+++ b/exports/agy/prompts/z-implement-all.md
@@ -277,7 +277,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
diff --git a/exports/agy/prompts/z-mr-review.md b/exports/agy/prompts/z-mr-review.md
index 4191e61..18db02d 100644
--- a/exports/agy/prompts/z-mr-review.md
+++ b/exports/agy/prompts/z-mr-review.md
@@ -9,6 +9,16 @@ Arguments (from `$ARGUMENTS`):
 
 $ARGUMENTS
 
+## Finding promotion contract
+
+`/z-mr-review` is a producer of the shared review-family promotion contract:
+
+- The parsed reviewer JSON is the structured finding source.
+- `MR-REVIEW.md` is both the evidence summary and the promotion artifact: ranked findings are emitted as task-shaped blocks that the user can delete before applying survivors.
+- The command preserves its P0-P4 severity model because it is code-quality oriented, but every emitted task block must include source severity, category, file citation, finding detail, and acceptance criteria.
+
+`MR-REVIEW.md` is intentionally separate from canonical plan `TASKS.md`. Users apply survivors with `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`; the implementation orchestrator must treat that path as the task queue while still resolving `$BASE` from the slug for SPEC/PLAN context when present.
+
 ## Argument parsing
 
 Parse `$ARGUMENTS` before doing anything else:
diff --git a/exports/agy/prompts/z-plan-light.md b/exports/agy/prompts/z-plan-light.md
index 7c926bc..7ab4b5e 100644
--- a/exports/agy/prompts/z-plan-light.md
+++ b/exports/agy/prompts/z-plan-light.md
@@ -1,5 +1,5 @@
 ---
-description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i...
+description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa...
 role: workflow
 ---
 
@@ -11,7 +11,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -19,7 +19,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -29,10 +30,25 @@ This command is for **small, focused changes**. If at any phase you realize the
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    ```
-6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
-7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
+7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
+- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
+- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
+- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
+- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 At any phase, if you discover:
 
@@ -41,7 +57,12 @@ At any phase, if you discover:
 - **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
 - **The user explicitly says** "this might be bigger than I thought"
 
-→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.
+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
+
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise + quick exploration (combined)
 
@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -168,8 +189,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -215,7 +236,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.
diff --git a/exports/agy/prompts/z-plan-split.md b/exports/agy/prompts/z-plan-split.md
index 188d31c..9cb0197 100644
--- a/exports/agy/prompts/z-plan-split.md
+++ b/exports/agy/prompts/z-plan-split.md
@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
 If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
+
+Deterministic routes:
+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
+
+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ### 1c. Write proposal artifact
 
 Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
diff --git a/exports/agy/prompts/z-plan.md b/exports/agy/prompts/z-plan.md
index 551c4b8..8f1a68b 100644
--- a/exports/agy/prompts/z-plan.md
+++ b/exports/agy/prompts/z-plan.md
@@ -65,6 +65,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
 Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
+- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
+- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
+- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
+- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
@@ -292,12 +312,13 @@ If a task block already contains a user-authored `**Complexity:** <tier>` line (
 
 Copy `$Z_HARNESS_PLAN_DIR/{SPEC,PLAN,TASKS}.md` into `$Z_HARNESS_PLAN_DIR/archive/$RUN/`. Update `manifest.json` with end timestamp, status `complete`, totals (decision count, consultation count, total tokens if available).
 
-Log run end. Send a `PushNotification` if policy ≠ `off` with THREE recommendations:
+Log run end. Send a `PushNotification` if policy ≠ `off` with FOUR recommendations:
 ```
 Plan complete. <N> tasks queued.
 
 Recommended:
   /compact          — free planning context before next phase
+  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
   /z-test           — (optional, recommended for risky / financial code) draft semantic test cases before implementation
   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
 ```
diff --git a/exports/agy/prompts/z-research.md b/exports/agy/prompts/z-research.md
index 45b9ff5..d011d24 100644
--- a/exports/agy/prompts/z-research.md
+++ b/exports/agy/prompts/z-research.md
@@ -44,6 +44,26 @@ Strict, multi-phase. Do not skip phases. `/z-research` produces a research note
 - `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.
+
+Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
+- Route clearly framed planning work with enough terrain to `/z-plan`.
+- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/agy/prompts/z-review-all.md b/exports/agy/prompts/z-review-all.md
index 2fde020..43c7b2f 100644
--- a/exports/agy/prompts/z-review-all.md
+++ b/exports/agy/prompts/z-review-all.md
@@ -142,6 +142,32 @@ Both consultants are already on `model: haiku` — they just shell out to gemini
 
 Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcripts/` per the consultant's own logging.
 
+## Finding promotion contract
+
+Review-family commands produce two artifact classes:
+
+- **Evidence artifacts** preserve every reviewed finding and the pushback that was applied before trusting it.
+- **Promotion artifacts** contain only actionable candidate work in a `/z-implement-all`-compatible task shape. Users prune or approve these artifacts once, then run `/z-implement-all --tasks <path>` to apply survivors.
+
+Every promoted finding must carry:
+
+- **Source:** the originating run, consultant(s), prong, and finding text or ID.
+- **Class:** `implementation_drift`, `spec_gap`, `completed_task_contradiction`, `premise_failure`, or `observation`.
+- **Severity:** `blocker`, `major`, or `minor`.
+- **Evidence:** path/line citations or diff/spec references.
+- **Pushback:** one concrete reason the finding might be wrong.
+- **Files:** expected edit targets, or `none` if the item is not directly implementable.
+- **Disposition:** `candidate_task`, `amendment_proposal`, `superseding_task`, `escalation`, or `report_only`.
+- **Acceptance:** verifiable completion criteria for executable tasks.
+
+Promotion rules:
+
+- `implementation_drift` → candidate fixup task.
+- `spec_gap` → amendment proposal task that routes through `/z-amend`; never a direct `SPEC.md` edit.
+- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
+- `premise_failure` → escalation section, not implementer work.
+- `observation` → remain in the evidence artifact only.
+
 ## Phase 5 — Aggregate findings
 
 Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:
@@ -182,21 +208,84 @@ Diff stats: <X files, Y additions, Z deletions>
 
 Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.
 
-## Phase 6 — Present + ask what to do
+## Phase 6 — Promote findings to review tasks
+
+Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.
+
+Use this structure:
+
+```markdown
+---
+artifact: review-tasks
+slug: <slug>
+run_id: <RRUN>
+source_findings: archive/<RRUN>/findings.md
+drift_findings: <n>
+spec_gap_findings: <m>
+escalations: <k>
+---
+
+# Review Tasks — <slug>
+
+Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:
+
+`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`
+
+## Candidate fixup tasks
+
+### [ ] T-REV-001 — [blocker] <short title>
+- **Class:** implementation_drift
+- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `<path>:<line>` (modified)
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** <verifiable criteria>
+
+## Amendment proposals
+
+### [ ] T-REV-002 — [major] Amend spec: <short title>
+- **Class:** spec_gap
+- **Disposition:** amendment_proposal
+- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.
+
+## Superseding tasks
+
+### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
+- **Class:** completed_task_contradiction
+- **Disposition:** superseding_task
+- **Source:** <finding reference>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** <files to revisit>
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.
+
+## Escalations
+
+- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.
+
+## Report-only observations
+
+- <minor/speculative finding left in findings.md only>
+```
+
+If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.
 
-Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."
+Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."
 
-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
+Present a short summary to the user:
 
-- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
-- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
-- **Both**
-- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
-- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
+- `findings.md` path
+- `REVIEW-TASKS.md` path, if generated
+- top blockers/escalations
+- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first
 
-Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
+Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
 
-**On Ship as-is or after fixup tasks complete**, also push-notify the user:
+**On a clean review or after promoted tasks complete**, also push-notify the user:
 ```
 Final review accepted. Recommended next:
   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
@@ -205,7 +294,7 @@ The implementation is done and reviewed; the docs are what's left.
 
 ## Hard rules
 
-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
 - **Never** run this on an incomplete plan without explicit user override.
 - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
 - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
diff --git a/exports/codex/AGENTS.md b/exports/codex/AGENTS.md
index 2917381..d64bcbd 100644
--- a/exports/codex/AGENTS.md
+++ b/exports/codex/AGENTS.md
@@ -547,11 +547,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_primary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
@@ -686,11 +696,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_secondary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
@@ -1120,16 +1140,167 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-phase.sh" end
 
 ---
 
+## external-lookup
+
+**Role:** Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist.
+
+## Mission
+
+You are a fresh-context lookup worker. Main thread delegates noisy retrieval to you so it doesn't pollute its context. Return ≤3 KB STATUS-headed Markdown per `docs/llm/lookup-contract.json`. All external retrieval — web docs, public API endpoints, paginated JSON responses, library docs outside training cutoff — is your responsibility. Synthesize; never dump raw HTML or JSON into `## Answer`.
+
+## Output contract
+
+Every response begins with exactly one STATUS line, followed by the four Markdown sections in fixed order:
+
+```
+STATUS: <ok|partial|refused>
+
+## Answer
+<synthesis of retrieved information; ≤2 KB; no raw HTML/JSON/YAML>
+
+## Provenance
+- query: <normalized query string>
+- tools_used: <comma-separated subset of {WebFetch, WebSearch, Bash, Read}>
+- sources: <bulleted sub-list of url:section or path:line>
+- freshness_ts: <ISO 8601 UTC, e.g. 2026-05-24T18:41:00Z>
+- confidence: <high | medium | low>
+- commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
+
+## Unresolved
+<gaps, partial results, pagination truncation, stale cache warnings; or "none" if fully resolved>
+
+## Raw artifact pointer
+<path to z-harness/lookup-cache/<sha256>.raw if raw artifact was written; omit section if not used>
+```
+
+The canonical version of this contract is `docs/llm/lookup-contract.json`. If anything here conflicts with that file, `lookup-contract.json` wins.
+
+**STATUS values:**
+- `ok` — answer believed reliable.
+- `partial` — retrieval completed but incomplete OR ambiguous. Includes: 4xx (incl. 429 rate-limit), 5xx, no-results-found, pagination-truncation, source-cache-stale. Body explains gaps in `## Unresolved`.
+- `refused` — verb-blocklist matched OR explicit mission-scope violation. `## Answer` first line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
+
+## Tool guidance
+
+- Prefer `WebFetch` for known URLs of public docs or pages.
+- Prefer `WebSearch` to discover URLs when only a topic is given.
+- Use `Bash` for endpoints WebFetch cannot handle: `gh api`, `curl` with custom headers / query params / auth, `jq` filtering of returned JSON.
+- Use `Read` / `Grep` / `Glob` to inspect local files when the query references repo-local content.
+
+## Verb-blocklist
+
+Before running any Bash command, grep the literal command string (case-insensitive) against every pattern below. Any match → emit `STATUS: refused` with `## Answer` body:
+
+```
+Refused: mutation_blocked — matched pattern '<pattern>' in command '<verbatim cmd>'
+```
+
+Do not execute the command.
+
+```
+# DB writes (verb anywhere AND via -f / redirect)
+INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|VACUUM
+psql\s+[^|]*\s-f\s|sqlite3\s+[^|]*\s*<|>\s*[^|>\s]+\.(db|sqlite|sqlite3)\b
+
+# Git mutations
+git\s+push|git\s+commit|git\s+reset\s+--hard|git\s+rebase\s+--|git\s+stash\s+drop|git\s+branch\s+-D|git\s+checkout\s+--
+
+# GitHub mutations (including gh api with mutating methods)
+gh\s+pr\s+(create|merge|close|edit)|gh\s+issue\s+(create|close|edit)|gh\s+release\s+create|gh\s+api\s+[^|]*--method\s+(POST|PUT|PATCH|DELETE)
+
+# HTTP mutations
+curl[^|]*(-X|--request)\s*(POST|PUT|DELETE|PATCH)
+curl[^|]*(-d|--data|--data-raw|--data-binary|-F|--form)\b
+wget\s+[^|]*--(post-data|method)\b
+\bhttpie\s+(POST|PUT|DELETE|PATCH)\b
+\bhttp\s+(POST|PUT|DELETE|PATCH)\b
+
+# Eval / piped interpreters (NOTE: bare $(...) and backticks NOT blocked — too disruptive; rely on pipe-to-interpreter detection)
+\beval\b|\bsh\s+-c\b|\bbash\s+-c\b
+\|\s*(sh|bash|zsh|python|python3|perl|ruby|node)\b
+<\s*\(.*\)\s*\|\s*(sh|bash|python|perl|ruby|node)\b
+\b(perl|ruby|node|python|python3)\s+-e\b
+
+# Filesystem destructive
+rm\s+-(rf|fr|Rf|fR)\b|>\s*/dev/(sd|nvme|disk)
+```
+
+Implementation note: each pattern is a Python regex tested with `re.IGNORECASE` against the joined argv string. Compile once; test before every `Bash` invocation.
+
+## Budget
+
+Total response (STATUS line + all sections + whitespace) ≤3 KB. Aim for ≤2 KB synthesis inside `## Answer` so Provenance + Unresolved have headroom.
+
+If a raw artifact exceeds the budget, write it to `z-harness/lookup-cache/<sha256-of-normalized-query>.raw` and point at it in `## Raw artifact pointer`. The cache dir is gitignored; create it with `mkdir -p` if missing.
+
+**Normalized query** = lowercase + collapse all internal whitespace runs to one space + strip leading/trailing whitespace.
+
+## Freshness discipline
+
+`freshness_ts` is the **retrieval timestamp** in UTC ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`) — not the source document's own last-modified date.
+
+If a source was loaded from cache and the cache file is >24h old (compare mtime), mark `confidence: low` and call it out in `## Unresolved`.
+
+## Refusal modes
+
+STATUS values are mutually exclusive:
+
+- `ok` — answer believed reliable.
+- `partial` — retrieval completed but incomplete OR ambiguous. Body explains gaps in `## Unresolved`.
+- `refused` — verb-blocklist matched OR explicit mission-scope violation (e.g. user asked to place a trade). Body's first `## Answer` line MUST be `Refused: <category> — <detail>` where category ∈ {`mutation_blocked`, `out_of_scope`, `auth_missing`}.
+
+## Provenance section format
+
+```markdown
+## Provenance
+- query: <normalized query string>
+- tools_used: <comma-separated subset of {WebFetch, WebSearch, Bash, Read}>
+- sources: <bulleted sub-list of url:section or path:line>
+- freshness_ts: <ISO 8601 UTC>
+- confidence: <high | medium | low>
+- commands: <bulleted sub-list of verbatim Bash commands, OR "n/a" if Bash unused>
+```
+
+`commands:` entries are **verbatim** — never truncated in provenance. Display-side truncation may happen in `## Answer` (with `…`) but only there. If verbatim commands push the response over 3 KB, drop the response into the raw artifact pointer file and synthesize down.
+
+## Confidence scale
+
+Three-value enum `{high, medium, low}`:
+
+- `high` — ≥1 authoritative source was directly retrieved AND the answer requires no interpolation.
+- `medium` — multiple sources retrieved but one or more required inference, or sources partially contradict each other.
+- `low` — cached/stale-source answers, or single-source answers where corroboration was attempted but failed.
+
+Never paste raw HTML, JSON, or YAML dumps into `## Answer`. Cite and summarize. Use the raw-artifact pointer for overflow.
+
+## Edge cases
+
+- **WebFetch returns 4xx/5xx** → log in provenance, mark `STATUS: partial`, try **one** fallback (WebSearch or Bash `gh api`) before giving up.
+- **WebSearch returns nothing** → `STATUS: partial`, `## Unresolved` notes "no results for query terms; suggest broader search".
+- **Pagination** → WebSearch results ≤10 entries returned. WebFetch link-follow depth ≤2 (the original URL + at most one followed link per source). If more pages exist, note in `## Unresolved` that results are truncated and suggest a narrower query.
+- **Authenticated endpoints** requiring secrets the agent doesn't have → `STATUS: refused`, category `auth_missing`. Do not attempt env-var sniffing.
+
+## Invariants
+
+- First output line is exactly `STATUS: <token>` where token ∈ {`ok`, `partial`, `refused`}.
+- Sections appear in fixed order: `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
+- No tool dispatch other than the whitelist (`WebFetch`, `WebSearch`, `Bash`, `Read`, `Grep`, `Glob`).
+- Total response ≤3 KB.
+- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
+- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.
+
+---
+
 ## implementer
 
 **Role:** Implements a single task from $Z_HARNESS_PLAN_DIR/TASKS.md in a fresh context. Invoked by /z-implement-all once per task to keep main orchestrator context lean. Reads only the slice of SPEC.md/PLAN.md it needs, edits files, returns a structured summary.
 
-You implement **exactly one task** from `$Z_HARNESS_PLAN_DIR/TASKS.md` and return a structured summary. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
+You implement **exactly one task** from the task block the orchestrator passes you and return a structured summary. The task may originate from canonical `$Z_HARNESS_PLAN_DIR/TASKS.md` or from a promoted review artifact such as `REVIEW-TASKS.md` / `MR-REVIEW.md` when `/z-implement-all --tasks <path>` is used. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
 
 ## Inputs from caller
 
-- **Task ID** (e.g. `T004`)
-- **Task block** verbatim from TASKS.md (files, deps, acceptance criteria)
+- **Task ID** (e.g. `T004`, `T-REV-001`, or `T-MR-001`)
+- **Task block** verbatim from the selected task file (files, deps, acceptance criteria)
 - **`$BASE` path** (e.g. `$Z_HARNESS_PLAN_DIR`) — read SPEC.md / PLAN.md yourself from `$BASE/SPEC.md` and `$BASE/PLAN.md`. The orchestrator no longer extracts slices for you; this keeps the orchestrator's context light. Read only the sections relevant to your task.
 - **`relevant_docs`** (paths, may be empty) — list of `docs/llm/<concept>.json` and `docs/human/<concept>.md` files relevant to this task (discovered by the orchestrator via `**DOCS:**` tags and source-file overlap with `docs/llm/INDEX.json`). **Read each LLM-tier JSON first** — they're small (1-3 KB), state invariants, cross-references, gotchas, and "consumed_by" relationships you may not see by just reading the task's own files. The human-tier markdown is supplementary if the JSON is unclear. If your edits invalidate any claim in a relevant doc, flag it in your `ISSUES:` return so `/z-maintain-docs` can refresh that concept.
 - **`tests_md_path`** (path, may be empty) — `$BASE/TESTS.md` if `/z-test` was run for this plan. If the task block contains a `**Tests:** TEST-001, TEST-004, ...` line, **read TESTS.md** and grep for each listed `## TEST-NNN` heading. Each TEST-NNN entry specifies an `Invariant:`, a `Failure class:`, a `Target file:`, a `Setup:`, and an `Assertion:`. You must produce actual test code at `Target file:` that implements the entry's `Assertion:` against the production code you're writing in this same task. The test must fail if a code change violates the named invariant / failure class — not just pass on the current implementation. If the target file does not yet exist in a recognized test directory, create it following the repo's existing test conventions (look at neighboring tests for fixture patterns).
@@ -1552,6 +1723,160 @@ The orchestrator (T006) creates actual fixture files and invokes this agent to r
 
 ---
 
+## planning-router
+
+**Role:** Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
+
+## Mission
+
+You are a cheap, read-only ambiguity resolver for z-harness planning-family route decisions. The caller has already collected compact deterministic signals and needs an advisory recommendation only when hard thresholds did not settle the route.
+
+You do not edit files, do not call other agents, do not run shell commands, and do not perform broad repo exploration. Prefer the caller's supplied signals over inventing facts.
+
+## Inputs From Caller
+
+The caller prompt must provide:
+
+- `current_command`: the command currently running.
+- `task_or_topic`: the user's task or topic, kept compact.
+- `signals_json`: JSON object containing deterministic route signals.
+- `route_chain_json`: JSON array of prior route hops, or `[]`.
+- `repo_root`: absolute path to the repo root.
+
+The caller may also provide:
+
+- `existing_artifacts`: compact list of relevant artifacts such as `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`, `RESEARCH.md`, or `BRAINSTORM.md`.
+
+Treat missing required inputs, malformed JSON, unknown `current_command`, or invalid signal types as malformed input.
+
+## Output Contract
+
+Return exactly this parseable shape and no prose before or after:
+
+```text
+STATUS: routed | ask_user | bad_input
+RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
+ROUTE_CLASS: primary | contextual | none
+CONFIDENCE: high | medium | low
+REASON_CODES: <comma-separated stable reason codes>
+REASON: <one line, <=160 chars>
+```
+
+`STATUS: routed` requires `RECOMMENDED` to be one concrete command and `ROUTE_CLASS` to be `primary` or `contextual`.
+
+`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
+
+`STATUS: bad_input` is only for malformed or missing required inputs. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.
+
+## Route Targets
+
+Primary route targets:
+
+- `/z-do`
+- `/z-plan-light`
+- `/z-plan`
+- `/z-plan-split`
+- `/z-brainstorm`
+- `/z-research`
+
+Contextual exits:
+
+- `/z-audit-plan`
+- `/z-fix`
+- `/z-debug`
+- `/z-amend`
+- `/z-maintain-docs`
+
+Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
+
+## Stable Reason Codes
+
+Use only these reason codes:
+
+- `tiny_task`
+- `small_fix`
+- `medium_plan`
+- `large_split`
+- `needs_research`
+- `needs_brainstorm`
+- `existing_plan_audit`
+- `existing_plan_amend`
+- `diagnosed_bug`
+- `unknown_bug`
+- `docs_stale`
+- `docs_drift`
+- `cross_module`
+- `schema_or_persistence`
+- `too_many_decisions`
+- `too_many_files`
+- `too_many_tasks`
+- `too_few_clusters`
+- `too_many_clusters`
+- `ambiguous_route`
+- `route_loop_risk`
+- `bad_input`
+
+## Expected Signals
+
+`signals_json` may include:
+
+- `candidate_files`: integer or `null`
+- `expected_tasks`: integer or `null`
+- `non_obvious_decisions`: integer or `null`
+- `cluster_seams`: integer or `null`
+- `cluster_seams_independently_plannable`: boolean
+- `cross_module`: boolean
+- `schema_or_persistence`: boolean
+- `public_api_or_wire_format`: boolean
+- `terrain_uncertain`: boolean
+- `approach_uncertain`: boolean
+- `has_bug_diagnosis`: boolean
+- `has_unknown_bug_symptom`: boolean
+- `has_existing_plan`: boolean
+- `has_fix_artifact`: boolean
+- `docs_stale_or_drifted`: boolean
+
+If a relevant signal is missing, reason from what is present and lower confidence. Do not infer file counts, task counts, independent seam plannability, or artifact existence from the filesystem unless the caller supplied an `existing_artifacts` list to interpret.
+
+`non_obvious_decisions: null` means the count is unknown; it does not satisfy "no non-obvious decisions." Likewise, `/z-plan-split` requires an explicit caller-supplied `cluster_seams_independently_plannable: true` signal before recommending a split.
+
+## Decision Rules
+
+Apply these rules in order:
+
+1. If any required input is absent or malformed, return `STATUS: bad_input`.
+2. Inspect `route_chain_json` before recommending a target. If the chain already contains two prior entries, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
+3. If the best recommendation would send the user back to the immediate prior `from_command`, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
+4. Prefer contextual exits when their preconditions are explicit:
+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
+   - `has_existing_plan` plus requested plan modification -> `/z-amend`
+   - `has_bug_diagnosis` -> `/z-fix`
+   - `has_unknown_bug_symptom` -> `/z-debug`
+   - `docs_stale_or_drifted` -> `/z-maintain-docs`
+5. If `terrain_uncertain` is true, recommend `/z-research`.
+6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
+7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
+   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
+   - If `cluster_seams == 1`, recommend `/z-plan` with `too_few_clusters`.
+   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
+   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
+8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
+9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
+10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
+11. Otherwise recommend `/z-plan`.
+
+If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
+
+## Confidence Guidance
+
+- `high`: supplied signals point clearly to one target and required preconditions are explicit.
+- `medium`: one target is likely but some quantitative signals are `null` or weak.
+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
+
+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
+
+---
+
 ## remote-runner
 
 **Role:** Haiku subagent that handles MECHANICAL remote work — rsync local repo to a per-(slug, task-id) sandbox on the remote host, run cargo build/check/clean, restart paper qtctl manifests, tail logs, run READ-ONLY DB/disk/log queries against shared state. NOT for interpretive debugging (root-causing a failing test, reasoning about DB results — those need Sonnet/Opus). Triggered by tasks tagged **REMOTE_VERIFY** in TASKS.md.
@@ -1701,11 +2026,16 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in. Set it now — check-timeout.sh
+# keys its per-run timeout_availability marker on it, and without it the
+# event isn't emitted. The reviewer is typically dispatched per-task, so
+# pass "tasks/<task-id>" if that's the scope you want the event written to;
+# otherwise the run-id of the parent /z-implement-all call.
+RUN="<run-id or tasks/<task-id> from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/codex/prompts/z-amend.md b/exports/codex/prompts/z-amend.md
index 19f77ca..429761c 100644
--- a/exports/codex/prompts/z-amend.md
+++ b/exports/codex/prompts/z-amend.md
@@ -10,6 +10,8 @@ $ARGUMENTS
 
 This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.
 
+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
+
 ## Phase 0 — Discover plan slug
 
 Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to amend:
diff --git a/exports/codex/prompts/z-audit.md b/exports/codex/prompts/z-audit.md
index aab5e36..41ea026 100644
--- a/exports/codex/prompts/z-audit.md
+++ b/exports/codex/prompts/z-audit.md
@@ -10,6 +10,15 @@ $ARGUMENTS
 
 This command is **read-only**. Never edit the target. Fixes happen later via `/z-implement-all` consuming the emitted `TASKS.md`.
 
+## Finding promotion contract
+
+`/z-audit` is a producer of the shared review-family promotion contract:
+
+- `REPORT.md` is the evidence artifact. It preserves every accepted finding, consult addition/drop, and the "one reason this might be wrong" pushback.
+- `TASKS.md` is the promotion artifact. It contains only actionable findings that are safe to hand to `/z-implement-all`.
+
+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
+
 ## Setup
 
 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
diff --git a/exports/codex/prompts/z-brainstorm.md b/exports/codex/prompts/z-brainstorm.md
index 48abb17..097939f 100644
--- a/exports/codex/prompts/z-brainstorm.md
+++ b/exports/codex/prompts/z-brainstorm.md
@@ -36,6 +36,26 @@ $ARGUMENTS
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.
+
+Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
+- Route a framing that is already clear and ready for task planning to `/z-plan`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/codex/prompts/z-do.md b/exports/codex/prompts/z-do.md
index c3d3bad..c79cabe 100644
--- a/exports/codex/prompts/z-do.md
+++ b/exports/codex/prompts/z-do.md
@@ -13,7 +13,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -23,18 +24,38 @@ $ARGUMENTS
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    ```
-5. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
+- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
+- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
+- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
+- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 If at any point you discover:
 
-- **>3 files** need editing → recommend `/z-plan-light`
-- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs) → recommend `/z-plan-light`
-- **Cross-module / cross-crate impact** OR **schema change** → recommend `/z-plan`
-- User says "this might be bigger than I thought" → bail
+- **>3 files** need editing
+- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
+- **Cross-module / cross-crate impact** OR **schema change**
+- User says "this might be bigger than I thought"
+
+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
 
-→ Halt: write a one-paragraph `z-harness/adhoc/archive/$RUN/escalation.md`, log `do_escalation`, push-notify, suggest the appropriate command. Do not improvise.
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise check (mandatory, quick)
 
@@ -69,7 +90,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -82,9 +103,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -150,7 +170,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/exports/codex/prompts/z-implement-all.md b/exports/codex/prompts/z-implement-all.md
index 0248511..f2aeec9 100644
--- a/exports/codex/prompts/z-implement-all.md
+++ b/exports/codex/prompts/z-implement-all.md
@@ -8,12 +8,23 @@ Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
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
@@ -101,8 +112,14 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
 
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
@@ -151,7 +168,7 @@ Repeat until no eligible task remains or you halt:
 
 ### 1. Pick next task
 
-Re-read `TASKS.md`. Build a quick eligibility check:
+Re-read `$TASKS_FILE`. Build a quick eligibility check:
 
 - Status is `[ ]` (pending)
 - **Every** dependency listed under "Depends on" is `[x]` (done) — go by task-level deps, not phase headings (phases mislead — e.g. T006 depends on T010+T011 even though they're in different phases)
@@ -188,7 +205,7 @@ Critical: **never retry a skip-flagged task in the same run** unless the user pi
 
 ### 3. Mark in-progress
 
-Edit `$BASE/TASKS.md`: flip the chosen task's `[ ]` to `[~]`. Log:
+Edit `$TASKS_FILE`: flip the chosen task's `[ ]` to `[~]`. Log:
 ```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
 ```
@@ -247,7 +264,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 <!-- agent dispatch / skill invocation not supported in Codex CLI; see CAPABILITIES.md -->
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
@@ -386,7 +403,7 @@ If `$BASE/test-runner.json` is absent OR the task block has no `**Tests:**` line
 
 ### 8. Mark done
 
-1. Flip `[~]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
+1. Flip `[~]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
 2. Write per-task summary file `$BASE/archive/tasks/<task-id>/SUMMARY.md` with outcome + counts. Future references to this task pull from the file rather than re-loading the full reviewer return into main thread.
 3. Log:
 ```bash
@@ -402,7 +419,7 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tas
 
 When the loop exits (no more eligible tasks, or you halted):
 
-1. Re-read `TASKS.md` for final counts: `done`, `pending`, `in_progress`, `skipped`.
+1. Re-read `$TASKS_FILE` for final counts: `done`, `pending`, `in_progress`, `skipped`.
 2. Write a summary message to the user:
    - Counts
    - Skipped tasks with reasons (REMOTE / wall-clock / human action required)
diff --git a/exports/codex/prompts/z-mr-review.md b/exports/codex/prompts/z-mr-review.md
index 33b0e31..f7b4671 100644
--- a/exports/codex/prompts/z-mr-review.md
+++ b/exports/codex/prompts/z-mr-review.md
@@ -6,6 +6,16 @@ Arguments (from `$ARGUMENTS`):
 
 $ARGUMENTS
 
+## Finding promotion contract
+
+`/z-mr-review` is a producer of the shared review-family promotion contract:
+
+- The parsed reviewer JSON is the structured finding source.
+- `MR-REVIEW.md` is both the evidence summary and the promotion artifact: ranked findings are emitted as task-shaped blocks that the user can delete before applying survivors.
+- The command preserves its P0-P4 severity model because it is code-quality oriented, but every emitted task block must include source severity, category, file citation, finding detail, and acceptance criteria.
+
+`MR-REVIEW.md` is intentionally separate from canonical plan `TASKS.md`. Users apply survivors with `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`; the implementation orchestrator must treat that path as the task queue while still resolving `$BASE` from the slug for SPEC/PLAN context when present.
+
 ## Argument parsing
 
 Parse `$ARGUMENTS` before doing anything else:
diff --git a/exports/codex/prompts/z-plan-light.md b/exports/codex/prompts/z-plan-light.md
index 83434d6..31a98d3 100644
--- a/exports/codex/prompts/z-plan-light.md
+++ b/exports/codex/prompts/z-plan-light.md
@@ -8,7 +8,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -16,7 +16,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -26,10 +27,25 @@ This command is for **small, focused changes**. If at any phase you realize the
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    ```
-6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
-7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
+7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
+- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
+- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
+- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
+- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 At any phase, if you discover:
 
@@ -38,7 +54,12 @@ At any phase, if you discover:
 - **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
 - **The user explicitly says** "this might be bigger than I thought"
 
-→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.
+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
+
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise + quick exploration (combined)
 
@@ -60,13 +81,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -165,8 +186,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -212,7 +233,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.
diff --git a/exports/codex/prompts/z-plan-split.md b/exports/codex/prompts/z-plan-split.md
index 5f3c436..443feab 100644
--- a/exports/codex/prompts/z-plan-split.md
+++ b/exports/codex/prompts/z-plan-split.md
@@ -140,6 +140,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
 If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
+
+Deterministic routes:
+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
+
+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ### 1c. Write proposal artifact
 
 Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
diff --git a/exports/codex/prompts/z-plan.md b/exports/codex/prompts/z-plan.md
index 2fe5cf4..78a89aa 100644
--- a/exports/codex/prompts/z-plan.md
+++ b/exports/codex/prompts/z-plan.md
@@ -54,6 +54,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
 Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
+- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
+- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
+- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
+- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/codex/prompts/z-research.md b/exports/codex/prompts/z-research.md
index 2bd71ba..6299b52 100644
--- a/exports/codex/prompts/z-research.md
+++ b/exports/codex/prompts/z-research.md
@@ -41,6 +41,26 @@ Strict, multi-phase. Do not skip phases. `/z-research` produces a research note
 - `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.
+
+Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
+- Route clearly framed planning work with enough terrain to `/z-plan`.
+- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/codex/prompts/z-review-all.md b/exports/codex/prompts/z-review-all.md
index d0a9efd..8d1dc91 100644
--- a/exports/codex/prompts/z-review-all.md
+++ b/exports/codex/prompts/z-review-all.md
@@ -132,6 +132,16 @@ Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcrip
 
 ## Phase 5 — Aggregate findings
 
+Before promotion, classify each accepted finding using the shared review-family promotion contract:
+
+- `implementation_drift` → candidate fixup task.
+- `spec_gap` → amendment proposal task that routes through `/z-amend`; never edit `SPEC.md` directly.
+- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
+- `premise_failure` → escalation section, not implementer work.
+- `observation` → keep in `findings.md` only.
+
+Every promoted finding must include source, severity, evidence, the "one reason this might be wrong" pushback, files, disposition, and acceptance criteria.
+
 Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:
 
 ```markdown
@@ -170,21 +180,84 @@ Diff stats: <X files, Y additions, Z deletions>
 
 Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.
 
-## Phase 6 — Present + ask what to do
+## Phase 6 — Promote findings to review tasks
+
+Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.
+
+Use this structure:
+
+```markdown
+---
+artifact: review-tasks
+slug: <slug>
+run_id: <RRUN>
+source_findings: archive/<RRUN>/findings.md
+drift_findings: <n>
+spec_gap_findings: <m>
+escalations: <k>
+---
+
+# Review Tasks — <slug>
+
+Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:
+
+`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`
+
+## Candidate fixup tasks
+
+### [ ] T-REV-001 — [blocker] <short title>
+- **Class:** implementation_drift
+- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `<path>:<line>` (modified)
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** <verifiable criteria>
+
+## Amendment proposals
+
+### [ ] T-REV-002 — [major] Amend spec: <short title>
+- **Class:** spec_gap
+- **Disposition:** amendment_proposal
+- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.
+
+## Superseding tasks
+
+### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
+- **Class:** completed_task_contradiction
+- **Disposition:** superseding_task
+- **Source:** <finding reference>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** <files to revisit>
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.
+
+## Escalations
+
+- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.
+
+## Report-only observations
+
+- <minor/speculative finding left in findings.md only>
+```
+
+If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.
 
-Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."
+Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."
 
-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
+Present a short summary to the user:
 
-- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
-- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
-- **Both**
-- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
-- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
+- `findings.md` path
+- `REVIEW-TASKS.md` path, if generated
+- top blockers/escalations
+- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first
 
-Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
+Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
 
-**On Ship as-is or after fixup tasks complete**, also push-notify the user:
+**On a clean review or after promoted tasks complete**, also push-notify the user:
 ```
 Final review accepted. Recommended next:
   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
@@ -193,7 +266,7 @@ The implementation is done and reviewed; the docs are what's left.
 
 ## Hard rules
 
-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
 - **Never** run this on an incomplete plan without explicit user override.
 - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
 - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
index a6cc743..49c64d5 100644
--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_primary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/cursor/.cursor/rules/consultant-secondary.mdc b/exports/cursor/.cursor/rules/consultant-secondary.mdc
index f2c2531..12116b6 100644
--- a/exports/cursor/.cursor/rules/consultant-secondary.mdc
+++ b/exports/cursor/.cursor/rules/consultant-secondary.mdc
@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in (see "Archiving" section below).
+# Set it now — check-timeout.sh keys the per-run timeout_availability marker
+# on it, and without it the event isn't emitted.
+RUN="<run-id from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
+
+# Emit `consult_start` BEFORE the provider CLI call so scripts/liveness.sh
+# can detect a hung consultant even when $TIMEOUT_CMD is empty (no coreutils
+# on PATH). The existing post-call `consult` event in the Archiving section
+# below is the matching end-marker (see END_KIND_TO_BASE in liveness.sh).
+bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" consult_start \
+  "$(printf '{"role":"consultant_secondary","mode":"%s","provider":"%s"}' "$MODE" "$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; print(json.load(sys.stdin)["provider"])')")"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/cursor/.cursor/rules/implementer.mdc b/exports/cursor/.cursor/rules/implementer.mdc
index 88d0a1d..6c0dd50 100644
--- a/exports/cursor/.cursor/rules/implementer.mdc
+++ b/exports/cursor/.cursor/rules/implementer.mdc
@@ -3,12 +3,12 @@ description: "Implements a single task from $Z_HARNESS_PLAN_DIR/TASKS.md in a fr
 alwaysApply: false
 ---
 
-You implement **exactly one task** from `$Z_HARNESS_PLAN_DIR/TASKS.md` and return a structured summary. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
+You implement **exactly one task** from the task block the orchestrator passes you and return a structured summary. The task may originate from canonical `$Z_HARNESS_PLAN_DIR/TASKS.md` or from a promoted review artifact such as `REVIEW-TASKS.md` / `MR-REVIEW.md` when `/z-implement-all --tasks <path>` is used. You are spawned fresh per task — the orchestrator does not want a chatty narrative, it wants the work done and a tight report back.
 
 ## Inputs from caller
 
-- **Task ID** (e.g. `T004`)
-- **Task block** verbatim from TASKS.md (files, deps, acceptance criteria)
+- **Task ID** (e.g. `T004`, `T-REV-001`, or `T-MR-001`)
+- **Task block** verbatim from the selected task file (files, deps, acceptance criteria)
 - **`$BASE` path** (e.g. `$Z_HARNESS_PLAN_DIR`) — read SPEC.md / PLAN.md yourself from `$BASE/SPEC.md` and `$BASE/PLAN.md`. The orchestrator no longer extracts slices for you; this keeps the orchestrator's context light. Read only the sections relevant to your task.
 - **`relevant_docs`** (paths, may be empty) — list of `docs/llm/<concept>.json` and `docs/human/<concept>.md` files relevant to this task (discovered by the orchestrator via `**DOCS:**` tags and source-file overlap with `docs/llm/INDEX.json`). **Read each LLM-tier JSON first** — they're small (1-3 KB), state invariants, cross-references, gotchas, and "consumed_by" relationships you may not see by just reading the task's own files. The human-tier markdown is supplementary if the JSON is unclear. If your edits invalidate any claim in a relevant doc, flag it in your `ISSUES:` return so `/z-maintain-docs` can refresh that concept.
 - **`tests_md_path`** (path, may be empty) — `$BASE/TESTS.md` if `/z-test` was run for this plan. If the task block contains a `**Tests:** TEST-001, TEST-004, ...` line, **read TESTS.md** and grep for each listed `## TEST-NNN` heading. Each TEST-NNN entry specifies an `Invariant:`, a `Failure class:`, a `Target file:`, a `Setup:`, and an `Assertion:`. You must produce actual test code at `Target file:` that implements the entry's `Assertion:` against the production code you're writing in this same task. The test must fail if a code change violates the named invariant / failure class — not just pass on the current implementation. If the target file does not yet exist in a recognized test directory, create it following the repo's existing test conventions (look at neighboring tests for fixture patterns).
diff --git a/exports/cursor/.cursor/rules/reviewer.mdc b/exports/cursor/.cursor/rules/reviewer.mdc
index 65bd77b..ff42741 100644
--- a/exports/cursor/.cursor/rules/reviewer.mdc
+++ b/exports/cursor/.cursor/rules/reviewer.mdc
@@ -23,11 +23,16 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa
 MODEL_LABEL="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["model_label"])')"
 TIMEOUT="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["timeout_s"])')"
 
-TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
-if [ -z "$TIMEOUT_CMD" ] && [ -z "$Z_HARNESS_TIMEOUT_WARNED" ]; then
-  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
-  export Z_HARNESS_TIMEOUT_WARNED=1
-fi
+# $RUN is the run-id the caller passed in. Set it now — check-timeout.sh
+# keys its per-run timeout_availability marker on it, and without it the
+# event isn't emitted. The reviewer is typically dispatched per-task, so
+# pass "tasks/<task-id>" if that's the scope you want the event written to;
+# otherwise the run-id of the parent /z-implement-all call.
+RUN="<run-id or tasks/<task-id> from caller>"
+
+# Detects timeout(1)/gtimeout, sets $TIMEOUT_CMD, and emits one
+# `timeout_availability` event per run so silent-disable is debuggable.
+source "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/check-timeout.sh" "$RUN"
 
 if [ "$USE_STDIN" = "True" ]; then
   if [ -n "$TIMEOUT_CMD" ]; then
diff --git a/exports/cursor/.cursor/rules/z-amend.mdc b/exports/cursor/.cursor/rules/z-amend.mdc
index 675b6fd..d6a2b78 100644
--- a/exports/cursor/.cursor/rules/z-amend.mdc
+++ b/exports/cursor/.cursor/rules/z-amend.mdc
@@ -13,6 +13,8 @@ $ARGUMENTS
 
 This command modifies an **already-produced** planning artifact set. It does NOT do exploration / consult-everywhere / full premise check — that's `/z-plan`. It does the surgical work of changing one or more decisions / scope items and making sure every downstream artifact (SPEC.md, PLAN.md, TASKS.md, or FIX.md) reflects the change consistently.
 
+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
+
 ## Phase 0 — Discover plan slug
 
 Multiple plans may coexist under `$Z_HARNESS_PLAN_DIR/`. Determine which one to amend:
diff --git a/exports/cursor/.cursor/rules/z-audit.mdc b/exports/cursor/.cursor/rules/z-audit.mdc
index ba752e5..27274f1 100644
--- a/exports/cursor/.cursor/rules/z-audit.mdc
+++ b/exports/cursor/.cursor/rules/z-audit.mdc
@@ -13,6 +13,15 @@ $ARGUMENTS
 
 This command is **read-only**. Never edit the target. Fixes happen later via `/z-implement-all` consuming the emitted `TASKS.md`.
 
+## Finding promotion contract
+
+`/z-audit` is a producer of the shared review-family promotion contract:
+
+- `REPORT.md` is the evidence artifact. It preserves every accepted finding, consult addition/drop, and the "one reason this might be wrong" pushback.
+- `TASKS.md` is the promotion artifact. It contains only actionable findings that are safe to hand to `/z-implement-all`.
+
+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
+
 ## Setup
 
 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
diff --git a/exports/cursor/.cursor/rules/z-brainstorm.mdc b/exports/cursor/.cursor/rules/z-brainstorm.mdc
index 99ee22d..545f3cf 100644
--- a/exports/cursor/.cursor/rules/z-brainstorm.mdc
+++ b/exports/cursor/.cursor/rules/z-brainstorm.mdc
@@ -39,6 +39,26 @@ $ARGUMENTS
 - `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.
+
+Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
+- Route a framing that is already clear and ready for task planning to `/z-plan`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/cursor/.cursor/rules/z-do.mdc b/exports/cursor/.cursor/rules/z-do.mdc
index dbe3ee6..59ce4fb 100644
--- a/exports/cursor/.cursor/rules/z-do.mdc
+++ b/exports/cursor/.cursor/rules/z-do.mdc
@@ -1,5 +1,5 @@
 ---
-description: "Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces."
+description: "Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution."
 alwaysApply: false
 ---
 
@@ -16,7 +16,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -26,18 +27,38 @@ $ARGUMENTS
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    ```
-5. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
+- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
+- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
+- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
+- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 If at any point you discover:
 
-- **>3 files** need editing → recommend `/z-plan-light`
-- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs) → recommend `/z-plan-light`
-- **Cross-module / cross-crate impact** OR **schema change** → recommend `/z-plan`
-- User says "this might be bigger than I thought" → bail
+- **>3 files** need editing
+- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
+- **Cross-module / cross-crate impact** OR **schema change**
+- User says "this might be bigger than I thought"
+
+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
 
-→ Halt: write a one-paragraph `z-harness/adhoc/archive/$RUN/escalation.md`, log `do_escalation`, push-notify, suggest the appropriate command. Do not improvise.
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise check (mandatory, quick)
 
@@ -72,7 +93,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -85,9 +106,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -153,7 +173,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/exports/cursor/.cursor/rules/z-implement-all.mdc b/exports/cursor/.cursor/rules/z-implement-all.mdc
index c115141..e6dd242 100644
--- a/exports/cursor/.cursor/rules/z-implement-all.mdc
+++ b/exports/cursor/.cursor/rules/z-implement-all.mdc
@@ -11,12 +11,23 @@ Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`).
 
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
@@ -104,8 +115,14 @@ Both flags are inert for legacy (single-slug) plans and only affect tree-rooted
 
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
@@ -154,7 +171,7 @@ Repeat until no eligible task remains or you halt:
 
 ### 1. Pick next task
 
-Re-read `TASKS.md`. Build a quick eligibility check:
+Re-read `$TASKS_FILE`. Build a quick eligibility check:
 
 - Status is `[ ]` (pending)
 - **Every** dependency listed under "Depends on" is `[x]` (done) — go by task-level deps, not phase headings (phases mislead — e.g. T006 depends on T010+T011 even though they're in different phases)
@@ -191,7 +208,7 @@ Critical: **never retry a skip-flagged task in the same run** unless the user pi
 
 ### 3. Mark in-progress
 
-Edit `$BASE/TASKS.md`: flip the chosen task's `[ ]` to `[~]`. Log:
+Edit `$TASKS_FILE`: flip the chosen task's `[ ]` to `[~]`. Log:
 ```bash
 bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tasks/<task-id>" task_start '{"id":"<task-id>"}'
 ```
@@ -250,7 +267,7 @@ The precheck is cheap (≤30s) and saves 30-60 minutes per spec-drift incident 
 <!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->
   subagent_type="implementer",
   description="Implement <task-id>",
-  prompt="<task-id>\n\n<task block verbatim from TASKS.md>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
+  prompt="<task-id>\n\n<task block verbatim from $TASKS_FILE>\n\n$BASE: <abs path>  (read SPEC.md / PLAN.md yourself from here)\nRepo root: <abs path>\nrelevant_docs (paths — Read these for cross-file invariants and consumer contracts): <paths from step 4b>\ntests_md_path: <$BASE/TESTS.md if it exists, else empty>  (if the task block contains a **Tests:** line, Read TESTS.md and produce test code for each listed TEST-NNN at its Target file path, in the same diff as the production code)"
 )
 ```
 
@@ -389,7 +406,7 @@ If `$BASE/test-runner.json` is absent OR the task block has no `**Tests:**` line
 
 ### 8. Mark done
 
-1. Flip `[~]` to `[x]` in `$BASE/TASKS.md`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
+1. Flip `[~]` to `[x]` in `$TASKS_FILE`. Add a one-line completion note (e.g. "T004 done; reviewer flagged 1 minor (deferred); 3/3 tests passed").
 2. Write per-task summary file `$BASE/archive/tasks/<task-id>/SUMMARY.md` with outcome + counts. Future references to this task pull from the file rather than re-loading the full reviewer return into main thread.
 3. Log:
 ```bash
@@ -405,7 +422,7 @@ bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "tas
 
 When the loop exits (no more eligible tasks, or you halted):
 
-1. Re-read `TASKS.md` for final counts: `done`, `pending`, `in_progress`, `skipped`.
+1. Re-read `$TASKS_FILE` for final counts: `done`, `pending`, `in_progress`, `skipped`.
 2. Write a summary message to the user:
    - Counts
    - Skipped tasks with reasons (REMOTE / wall-clock / human action required)
diff --git a/exports/cursor/.cursor/rules/z-mr-review.mdc b/exports/cursor/.cursor/rules/z-mr-review.mdc
index dd6faa1..1cd268e 100644
--- a/exports/cursor/.cursor/rules/z-mr-review.mdc
+++ b/exports/cursor/.cursor/rules/z-mr-review.mdc
@@ -9,6 +9,16 @@ Arguments (from `$ARGUMENTS`):
 
 $ARGUMENTS
 
+## Finding promotion contract
+
+`/z-mr-review` is a producer of the shared review-family promotion contract:
+
+- The parsed reviewer JSON is the structured finding source.
+- `MR-REVIEW.md` is both the evidence summary and the promotion artifact: ranked findings are emitted as task-shaped blocks that the user can delete before applying survivors.
+- The command preserves its P0-P4 severity model because it is code-quality oriented, but every emitted task block must include source severity, category, file citation, finding detail, and acceptance criteria.
+
+`MR-REVIEW.md` is intentionally separate from canonical plan `TASKS.md`. Users apply survivors with `/z-implement-all --tasks=z-harness/<SLUG>/MR-REVIEW.md`; the implementation orchestrator must treat that path as the task queue while still resolving `$BASE` from the slug for SPEC/PLAN context when present.
+
 ## Argument parsing
 
 Parse `$ARGUMENTS` before doing anything else:
diff --git a/exports/cursor/.cursor/rules/z-plan-light.mdc b/exports/cursor/.cursor/rules/z-plan-light.mdc
index 86e17c1..b486d3a 100644
--- a/exports/cursor/.cursor/rules/z-plan-light.mdc
+++ b/exports/cursor/.cursor/rules/z-plan-light.mdc
@@ -1,5 +1,5 @@
 ---
-description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan if scope grows beyond ~5 files or >2 non-obvious decisions."
+description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit."
 alwaysApply: false
 ---
 
@@ -11,7 +11,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -19,7 +19,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -29,10 +30,25 @@ This command is for **small, focused changes**. If at any phase you realize the
    ' "$VERSION_BLOB" "<arguments>")"
    bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    ```
-6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
-7. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
+7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
+8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
 
-## Auto-bail thresholds (check throughout)
+## Plan Route Check
+
+<!-- PLAN_ROUTE_CHECK_START -->
+Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
+
+Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
+- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
+- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
+- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
+- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
+- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
+
+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
 
 At any phase, if you discover:
 
@@ -41,7 +57,12 @@ At any phase, if you discover:
 - **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
 - **The user explicitly says** "this might be bigger than I thought"
 
-→ STOP. Write `$Z_HARNESS_PLAN_DIR/escalation.md` describing what you found. Push-notify: "Scope grew past light-mode thresholds. Recommend `/z-plan <task>`." Do not proceed to implementation.
+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
+
+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
+
+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
+<!-- PLAN_ROUTE_CHECK_END -->
 
 ## Phase 1 — Premise + quick exploration (combined)
 
@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -168,8 +189,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -215,7 +236,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.
diff --git a/exports/cursor/.cursor/rules/z-plan-split.mdc b/exports/cursor/.cursor/rules/z-plan-split.mdc
index fe88560..c700822 100644
--- a/exports/cursor/.cursor/rules/z-plan-split.mdc
+++ b/exports/cursor/.cursor/rules/z-plan-split.mdc
@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
 If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
+
+Deterministic routes:
+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
+
+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ### 1c. Write proposal artifact
 
 Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
diff --git a/exports/cursor/.cursor/rules/z-plan.mdc b/exports/cursor/.cursor/rules/z-plan.mdc
index 1a8c911..c3bcbe2 100644
--- a/exports/cursor/.cursor/rules/z-plan.mdc
+++ b/exports/cursor/.cursor/rules/z-plan.mdc
@@ -57,6 +57,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
 Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check after Setup step 10's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
+- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
+- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
+- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
+- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/cursor/.cursor/rules/z-research.mdc b/exports/cursor/.cursor/rules/z-research.mdc
index a35a83a..d5458a4 100644
--- a/exports/cursor/.cursor/rules/z-research.mdc
+++ b/exports/cursor/.cursor/rules/z-research.mdc
@@ -44,6 +44,26 @@ Strict, multi-phase. Do not skip phases. `/z-research` produces a research note
 - `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
 - `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`
 
+<!-- PLAN_ROUTE_CHECK_START -->
+## Plan Route Check
+
+Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.
+
+Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
+
+Deterministic routes:
+- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
+- Route clearly framed planning work with enough terrain to `/z-plan`.
+- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
+- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
+
+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
+
+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
+
+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
+<!-- PLAN_ROUTE_CHECK_END -->
+
 ## Phase telemetry (mandatory)
 
 At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:
diff --git a/exports/cursor/.cursor/rules/z-review-all.mdc b/exports/cursor/.cursor/rules/z-review-all.mdc
index 4a4136a..13cd754 100644
--- a/exports/cursor/.cursor/rules/z-review-all.mdc
+++ b/exports/cursor/.cursor/rules/z-review-all.mdc
@@ -135,6 +135,16 @@ Transcripts are archived by each consultant under `$BASE/archive/$RRUN/transcrip
 
 ## Phase 5 — Aggregate findings
 
+Before promotion, classify each accepted finding using the shared review-family promotion contract:
+
+- `implementation_drift` → candidate fixup task.
+- `spec_gap` → amendment proposal task that routes through `/z-amend`; never edit `SPEC.md` directly.
+- `completed_task_contradiction` → fresh superseding task; never mutate a completed `[x]` task in place.
+- `premise_failure` → escalation section, not implementer work.
+- `observation` → keep in `findings.md` only.
+
+Every promoted finding must include source, severity, evidence, the "one reason this might be wrong" pushback, files, disposition, and acceptance criteria.
+
 Read both consultants' returns. Build `$BASE/archive/$RRUN/findings.md` with this structure:
 
 ```markdown
@@ -173,21 +183,84 @@ Diff stats: <X files, Y additions, Z deletions>
 
 Apply the **one-reason-it-might-be-wrong** rule from `/z-plan` to every finding before listing it. Push back on weak findings.
 
-## Phase 6 — Present + ask what to do
+## Phase 6 — Promote findings to review tasks
+
+Build `$BASE/REVIEW-TASKS.md` and snapshot the same content to `$BASE/archive/$RRUN/REVIEW-TASKS.md`. This is a candidate artifact: the user deletes anything they reject before applying it.
+
+Use this structure:
+
+```markdown
+---
+artifact: review-tasks
+slug: <slug>
+run_id: <RRUN>
+source_findings: archive/<RRUN>/findings.md
+drift_findings: <n>
+spec_gap_findings: <m>
+escalations: <k>
+---
+
+# Review Tasks — <slug>
+
+Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:
+
+`/z-implement-all --tasks $BASE/REVIEW-TASKS.md`
+
+## Candidate fixup tasks
+
+### [ ] T-REV-001 — [blocker] <short title>
+- **Class:** implementation_drift
+- **Source:** Prong A; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `<path>:<line>` (modified)
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** <verifiable criteria>
+
+## Amendment proposals
+
+### [ ] T-REV-002 — [major] Amend spec: <short title>
+- **Class:** spec_gap
+- **Disposition:** amendment_proposal
+- **Source:** Prong B; <gemini|codex|both>; finding <stable reference or short quote>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** run `/z-amend "<specific amendment>"`; resulting SPEC/PLAN/TASKS reflect the amendment and preserve completed-task state.
+
+## Superseding tasks
+
+### [ ] T-REV-003 — [major] Supersedes T0NN: <short title>
+- **Class:** completed_task_contradiction
+- **Disposition:** superseding_task
+- **Source:** <finding reference>
+- **Pushback:** <one reason this might be wrong>
+- **Files:** <files to revisit>
+- **Depends on:** none | T-REV-00N
+- **Acceptance:** new work corrects or replaces the completed task behavior without editing the completed `[x]` task in place.
+
+## Escalations
+
+- **Premise failure:** <finding>. Recommended next: `/z-plan <affected scope>`.
+
+## Report-only observations
+
+- <minor/speculative finding left in findings.md only>
+```
+
+If there are no actionable findings and no escalations, write `$BASE/archive/$RRUN/shipped.md` acknowledging the clean final review and omit `REVIEW-TASKS.md`.
 
-Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps."
+Push-notify: "Final review complete: A=<n> drift, B=<m> spec gaps, review tasks=<t>, escalations=<k>."
 
-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
+Present a short summary to the user:
 
-- **Open drift fixup tasks** → append new tasks (e.g. `T100-fixup-drift`) to `$BASE/TASKS.md`, mark them `[ ]`. User can then run `/z-implement-all` again.
-- **Spec retro** → patch `$BASE/SPEC.md` to address the Prong B findings (you make the edits in-line; user reviews).
-- **Both**
-- **Ship as-is** — write a `$BASE/archive/$RRUN/shipped.md` acknowledging findings as acceptable; close out the plan.
-- **Reject and re-plan** — escalate; recommend running `/z-plan` for the affected scope.
+- `findings.md` path
+- `REVIEW-TASKS.md` path, if generated
+- top blockers/escalations
+- next command: `/z-implement-all --tasks $BASE/REVIEW-TASKS.md` after deleting rejected candidates, or `/z-amend` for amendment proposals that should be applied first
 
-Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"user_action":"<choice>"}'`.
+Log: `bash ${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh "$RRUN" review_all_end '{"slug":"<slug>","drift_findings":<a>,"spec_gap_findings":<b>,"review_tasks":<t>,"escalations":<k>,"user_action":"artifact_promoted"}'`.
 
-**On Ship as-is or after fixup tasks complete**, also push-notify the user:
+**On a clean review or after promoted tasks complete**, also push-notify the user:
 ```
 Final review accepted. Recommended next:
   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
@@ -196,7 +269,7 @@ The implementation is done and reviewed; the docs are what's left.
 
 ## Hard rules
 
-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
 - **Never** run this on an incomplete plan without explicit user override.
 - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
 - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.


Surrounding file context:
- Actual working tree also has untracked/generated planning-router exports at `exports/cursor/.cursor/rules/planning-router.mdc`, `exports/agy/.agent/rules/z-harness-planning-router.md`, and `exports/agy/prompts/planning-router.md`; Codex format has `planning-router` embedded in `exports/codex/AGENTS.md`.
- `rg` showed `PLAN_ROUTE_CHECK_START`/`Plan Route Check` in exported prompts/rules for z-do, z-plan-light, z-plan, z-plan-split, z-brainstorm, z-research, and z-audit-plan across Cursor, Codex, and Antigravity outputs.

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Focus especially on whether route checks and planning-router were exported to supported targets, and whether generated output appears consistent with source changes rather than hand-edited drift.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET - respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug - in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).
