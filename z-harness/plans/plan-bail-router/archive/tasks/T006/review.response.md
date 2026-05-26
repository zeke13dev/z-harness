2026-05-25T00:31:10.128322Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-25T00:31:10.128987Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-25T00:31:10.128993Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5c8a-f0ef-7f03-8871-6a2628960a67
--------
user
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

codex
I’ll verify the generated artifacts against the source/export pipeline shape, then focus the review on acceptance-critical drift rather than every unrelated export change.
exec
/bin/zsh -lc 'ls -l exports/cursor/.cursor/rules/planning-router.mdc exports/agy/.agent/rules/z-harness-planning-router.md exports/agy/prompts/planning-router.md 2>/dev/null; rg -n "planning-router" exports/cursor exports/agy exports/codex' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'git status --short && git diff --name-only' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'rg -n "PLAN_ROUTE_CHECK_START|planning-router|z-audit-plan" commands skills agents docs exports scripts/export-*.py' in /Users/zeke/dev/z-harness
 succeeded in 459ms:
-rw-r--r--@ 1 zeke  staff  7684 May 24 17:28 exports/agy/.agent/rules/z-harness-planning-router.md
-rw-r--r--@ 1 zeke  staff  7671 May 24 17:28 exports/agy/prompts/planning-router.md
-rw-r--r--@ 1 zeke  staff  7681 May 24 17:28 exports/cursor/.cursor/rules/planning-router.mdc
exports/agy/prompts/z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/codex/prompts/z-plan-split.md:155:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/codex/prompts/z-plan-light.md:48:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/agy/prompts/z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/AGENTS.md:1726:## planning-router
exports/codex/prompts/z-audit-plan.md:20:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-plan.md:70:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-plan.md:81:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-brainstorm.md:52:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-do.md:44:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/skill-z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/agy/prompts/skill-z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/skill-z-plan.md:73:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/codex/prompts/z-research.md:57:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/agy-plugin.yaml:172:  - id: planning-router
exports/agy/agy-plugin.yaml:173:    source: agents/planning-router.md
exports/agy/agy-plugin.yaml:174:    output: .agent/rules/z-harness-planning-router.md
exports/agy/prompts/skill-z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

 succeeded in 461ms:
skills/z-plan-split/SKILL.md:147:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan-split/SKILL.md:159:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
commands/z-plan-split.md:146:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
docs/human/agents.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
docs/human/agents.md:10:These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
docs/human/agents.md:24:- `agents/planning-router.md:1` — `planning-router` — Cheap Haiku, read-only ambiguity resolver for plan-family route decisions. It accepts compact caller-supplied signals, returns the exact `STATUS`/`RECOMMENDED`/`ROUTE_CLASS`/`CONFIDENCE`/`REASON_CODES`/`REASON` shape, treats malformed input as `bad_input`, and asks the user on route-loop or conflicting-signal risk.
docs/human/agents.md:32:- `skills` — Skills define the exact operational boundaries, steps, and telemetry wrappers that direct subagent execution. Planning skills pass `planning-router` only compact already-known signals when deterministic route thresholds do not settle the next command.
docs/human/agents.md:35:- `planning-router` supports the shared route policy but does not own it. The caller owns the final decision, writes `route-decision.md`, emits `plan_route_decision`, and presents the AskUser handoff gate.
docs/human/agents.md:44:- `planning-router` is advisory only: it does not edit, call agents, or run shell commands. It must not route tiny/small tasks when `non_obvious_decisions` is unknown, and it must not recommend `/z-plan-split` unless split seams are explicitly independently plannable.
docs/human/agents.md:45:- `planning-router` distinguishes primary route targets (`/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`) from contextual exits (`/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, `/z-maintain-docs`) and returns `ask_user` rather than a concrete route when loop risk or conflicting signals make automation unsafe.
exports/agy/prompts/z-plan-split.md:146:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/agy/prompts/skill-z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/AGENTS.md:1726:## planning-router
exports/codex/AGENTS.md:1758:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
exports/codex/AGENTS.md:1784:- `/z-audit-plan`
exports/codex/AGENTS.md:1790:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
exports/codex/AGENTS.md:1851:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
exports/codex/prompts/z-plan-split.md:143:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-plan-split.md:155:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/agy/prompts/z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
exports/agy/prompts/z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-audit-plan.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
exports/agy/prompts/z-audit-plan.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
exports/agy/prompts/z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
commands/z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
commands/z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-audit-plan.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
commands/z-audit-plan.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
commands/z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-audit-plan.md:1:# /z-audit-plan
exports/codex/prompts/z-audit-plan.md:3:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
exports/codex/prompts/z-audit-plan.md:7:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-audit-plan.md:10:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
exports/codex/prompts/z-audit-plan.md:16:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
exports/codex/prompts/z-audit-plan.md:20:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
skills/z-do/SKILL.md:35:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-do/SKILL.md:48:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/skill-z-plan-split.md:146:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
docs/human/skills.md:4:> Covers source: skills/z-amend/SKILL.md, skills/z-audit-plan/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md
docs/human/skills.md:15:- `skills/z-audit-plan/SKILL.md:1` — `z-audit-plan` — Read-only pre-implementation audit of existing plan artifacts. It verifies references and design, runs adversarial consultants, writes PLAN_AUDIT_REPORT.md, and routes to `/z-plan`, `/z-amend`, or `/z-maintain-docs` only through the shared route handoff gate.
docs/human/skills.md:36:- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
docs/human/skills.md:39:- Planning skills mirror the shared route classes: primary routes are `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, and `/z-research`; contextual exits are `/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, and `/z-maintain-docs`. Route bails write `route-decision.md`, emit `plan_route_decision`, preserve existing telemetry, and stop rather than auto-running the target command.
docs/human/skills.md:50:- Contextual exits require preconditions: `/z-audit-plan` needs existing SPEC/PLAN/TASKS, `/z-amend` needs an existing plan to change, `/z-fix` needs a concrete diagnosis, `/z-debug` needs an unknown-cause symptom, and `/z-maintain-docs` needs doc staleness or drift that matters to the current workflow.
exports/agy/prompts/z-plan.md:68:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-plan.md:79:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
exports/agy/prompts/z-plan.md:81:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-plan.md:321:  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
exports/agy/prompts/skill-z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
agents/planning-router.md:2:name: planning-router
agents/planning-router.md:36:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
agents/planning-router.md:62:- `/z-audit-plan`
agents/planning-router.md:68:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
agents/planning-router.md:129:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
skills/z-research/SKILL.md:48:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-research/SKILL.md:61:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
exports/agy/prompts/skill-z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-audit-plan.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
exports/agy/prompts/skill-z-audit-plan.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
exports/agy/prompts/skill-z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
skills/z-audit-plan/SKILL.md:2:name: z-audit-plan
skills/z-audit-plan/SKILL.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
skills/z-audit-plan/SKILL.md:10:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-audit-plan/SKILL.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
skills/z-audit-plan/SKILL.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
skills/z-audit-plan/SKILL.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-brainstorm.md:39:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-brainstorm.md:52:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-do.md:31:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-do.md:44:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
docs/human/commands.md:4:> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-audit-plan.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md
docs/human/commands.md:14:- `commands/z-audit-plan.md:1` — `z-audit-plan` — Read-only audit of existing SPEC/PLAN/TASKS artifacts before implementation; routes to `/z-plan` when plan artifacts are absent and to `/z-amend` or `/z-maintain-docs` after audit when appropriate.
docs/human/commands.md:35:- `agents` — Commands instantiate and direct subagent teams (e.g. auditors, reviewers, implementers, plan consultants) to safely delegate heavy workloads. Planning-family commands may call `planning-router` only for ambiguous route decisions after deterministic signals have been collected.
docs/human/commands.md:38:- Planning-family commands share a route policy: primary routes are `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, and `/z-research`; contextual exits are `/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, and `/z-maintain-docs`. A route writes `route-decision.md`, emits `plan_route_decision`, presents an AskUser handoff gate, and never auto-executes the recommended command.
docs/human/commands.md:44:- `/z-audit-plan` is contextual only: it requires existing plan artifacts, remains read-only, and is not a substitute front door for `/z-plan`.
exports/agy/prompts/planning-router.md:34:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
exports/agy/prompts/planning-router.md:60:- `/z-audit-plan`
exports/agy/prompts/planning-router.md:66:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
exports/agy/prompts/planning-router.md:127:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
exports/codex/prompts/z-research.md:44:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-research.md:57:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-plan.md:60:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-plan.md:71:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
exports/agy/prompts/skill-z-plan.md:73:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/agy-plugin.yaml:18:  - id: z-audit-plan
exports/agy/agy-plugin.yaml:19:    source: commands/z-audit-plan.md
exports/agy/agy-plugin.yaml:20:    output: .agent/workflows/z-audit-plan.md
exports/agy/agy-plugin.yaml:172:  - id: planning-router
exports/agy/agy-plugin.yaml:173:    source: agents/planning-router.md
exports/agy/agy-plugin.yaml:174:    output: .agent/rules/z-harness-planning-router.md
exports/agy/agy-plugin.yaml:200:  - id: z-audit-plan
exports/agy/agy-plugin.yaml:201:    source: skills/z-audit-plan/SKILL.md
exports/agy/agy-plugin.yaml:202:    output: .agent/skills/z-audit-plan/SKILL.md
exports/agy/prompts/z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/codex/prompts/z-plan-light.md:35:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-plan-light.md:48:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
commands/z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-plan.md:57:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-plan.md:68:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
exports/codex/prompts/z-plan.md:70:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
skills/z-brainstorm/SKILL.md:43:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-brainstorm/SKILL.md:56:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
commands/z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
skills/z-plan-light/SKILL.md:39:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan-light/SKILL.md:52:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
skills/z-plan/SKILL.md:61:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan/SKILL.md:72:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
skills/z-plan/SKILL.md:74:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
docs/llm/skills.json:7:    "skills/z-audit-plan/SKILL.md",
docs/llm/skills.json:28:    {"file": "skills/z-audit-plan/SKILL.md", "line": 1, "symbol": "z-audit-plan", "kind": "module", "summary": "Read-only pre-implementation plan audit; verifies SPEC/PLAN/TASKS, writes PLAN_AUDIT_REPORT.md, and routes contextually to /z-plan, /z-amend, or /z-maintain-docs through route-decision.md."},
docs/llm/skills.json:64:    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, and /z-research; contextual exits are /z-audit-plan, /z-fix, /z-debug, /z-amend, and /z-maintain-docs.",
docs/llm/skills.json:65:    "Contextual exits require their preconditions: /z-audit-plan needs existing SPEC/PLAN/TASKS, /z-amend needs an existing plan to modify, /z-fix needs a diagnosis, /z-debug needs an unknown-cause symptom, and /z-maintain-docs needs relevant docs drift."
commands/z-plan.md:68:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan.md:79:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
commands/z-plan.md:81:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-plan.md:321:  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
docs/llm/commands.json:8:    "commands/z-audit-plan.md",
docs/llm/commands.json:61:      "file": "commands/z-audit-plan.md",
docs/llm/commands.json:63:      "symbol": "z-audit-plan",
docs/llm/commands.json:212:    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, and /z-research; contextual exits are /z-audit-plan, /z-fix, /z-debug, /z-amend, and /z-maintain-docs.",
docs/llm/commands.json:213:    "/z-audit-plan is contextual only and requires existing plan artifacts; when no plan exists it routes to /z-plan instead of auditing."
docs/llm/agents.json:16:    "agents/planning-router.md",
docs/llm/agents.json:33:    {"file": "agents/planning-router.md", "line": 1, "symbol": "planning-router", "kind": "module", "summary": "Haiku; read-only advisory router for ambiguous plan-family route decisions; requires exact parseable return shape and explicit split preconditions."},
docs/llm/agents.json:46:    "planning-router is advisory only: callers own route artifacts, plan_route_decision telemetry, AskUser handoffs, and final routing decisions."
docs/llm/agents.json:54:    "planning-router distinguishes primary route targets (/z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research) from contextual exits (/z-audit-plan, /z-fix, /z-debug, /z-amend, /z-maintain-docs), and returns ask_user for loop-risk or conflicting-signal cases."
docs/llm/INDEX.json:19:        "agents/planning-router.md",
docs/llm/INDEX.json:33:      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
docs/llm/INDEX.json:40:        "commands/z-audit-plan.md",
docs/llm/INDEX.json:70:      "summary": "Slash command surfaces, including planning-family route checks, contextual exits such as /z-audit-plan, plan_route_decision telemetry, review-family finding promotion, and /z-implement-all --tasks consumption."
docs/llm/INDEX.json:111:        "skills/z-audit-plan/SKILL.md",
docs/llm/INDEX.json:137:      "summary": "Operational checklists, including planning-family route policy, z-audit-plan plan audits, review finding promotion, z-amend safety gates, and explicit --tasks implementation queues."

 succeeded in 531ms:
 M README.md
 M agents/consultant-primary.md
 M agents/consultant-secondary.md
 A agents/external-lookup.md
 M agents/implementer.md
 M agents/reviewer.md
 M commands/z-audit.md
 M commands/z-brainstorm.md
 M commands/z-do.md
 M commands/z-implement-all.md
 M commands/z-mr-review.md
 M commands/z-plan-light.md
 M commands/z-plan-split.md
 M commands/z-plan.md
 M commands/z-research.md
 M commands/z-review-all.md
 A docs/human/LIVENESS.md
 M docs/human/agents.md
 M docs/human/commands.md
 A docs/human/lookup-contract.md
 M docs/human/skills.md
 M docs/llm/INDEX.json
 M docs/llm/agents.json
 M docs/llm/commands.json
 A docs/llm/external-lookup-agent.json
 A docs/llm/lookup-contract.json
 M docs/llm/skills.json
 M exports/agy/.agent/rules/z-harness-consultant-primary.md
 M exports/agy/.agent/rules/z-harness-consultant-secondary.md
 M exports/agy/.agent/rules/z-harness-implementer.md
 M exports/agy/.agent/rules/z-harness-reviewer.md
 M exports/agy/.agent/skills/z-amend/SKILL.md
 M exports/agy/.agent/skills/z-brainstorm/SKILL.md
 M exports/agy/.agent/skills/z-do/SKILL.md
 M exports/agy/.agent/skills/z-implement-all/SKILL.md
 M exports/agy/.agent/skills/z-plan-light/SKILL.md
 M exports/agy/.agent/skills/z-plan-split/SKILL.md
 M exports/agy/.agent/skills/z-plan/SKILL.md
 M exports/agy/.agent/skills/z-research/SKILL.md
 M exports/agy/.agent/skills/z-review-all/SKILL.md
 M exports/agy/.agent/workflows/z-audit.md
 M exports/agy/.agent/workflows/z-brainstorm.md
 M exports/agy/.agent/workflows/z-do.md
 M exports/agy/.agent/workflows/z-implement-all.md
 M exports/agy/.agent/workflows/z-mr-review.md
 M exports/agy/.agent/workflows/z-plan-light.md
 M exports/agy/.agent/workflows/z-plan-split.md
 M exports/agy/.agent/workflows/z-plan.md
 M exports/agy/.agent/workflows/z-research.md
 M exports/agy/.agent/workflows/z-review-all.md
 M exports/agy/agy-plugin.yaml
 M exports/agy/prompts/consultant-primary.md
 M exports/agy/prompts/consultant-secondary.md
 M exports/agy/prompts/implementer.md
 M exports/agy/prompts/reviewer.md
 M exports/agy/prompts/skill-z-amend.md
 M exports/agy/prompts/skill-z-brainstorm.md
 M exports/agy/prompts/skill-z-do.md
 M exports/agy/prompts/skill-z-implement-all.md
 M exports/agy/prompts/skill-z-plan-light.md
 M exports/agy/prompts/skill-z-plan-split.md
 M exports/agy/prompts/skill-z-plan.md
 M exports/agy/prompts/skill-z-research.md
 M exports/agy/prompts/skill-z-review-all.md
 M exports/agy/prompts/z-audit.md
 M exports/agy/prompts/z-brainstorm.md
 M exports/agy/prompts/z-do.md
 M exports/agy/prompts/z-implement-all.md
 M exports/agy/prompts/z-mr-review.md
 M exports/agy/prompts/z-plan-light.md
 M exports/agy/prompts/z-plan-split.md
 M exports/agy/prompts/z-plan.md
 M exports/agy/prompts/z-research.md
 M exports/agy/prompts/z-review-all.md
 M exports/codex/AGENTS.md
 M exports/codex/prompts/z-amend.md
 M exports/codex/prompts/z-audit.md
 M exports/codex/prompts/z-brainstorm.md
 M exports/codex/prompts/z-do.md
 M exports/codex/prompts/z-implement-all.md
 M exports/codex/prompts/z-mr-review.md
 M exports/codex/prompts/z-plan-light.md
 M exports/codex/prompts/z-plan-split.md
 M exports/codex/prompts/z-plan.md
 M exports/codex/prompts/z-research.md
 M exports/codex/prompts/z-review-all.md
 M exports/cursor/.cursor/rules/consultant-primary.mdc
 M exports/cursor/.cursor/rules/consultant-secondary.mdc
 M exports/cursor/.cursor/rules/implementer.mdc
 M exports/cursor/.cursor/rules/reviewer.mdc
 M exports/cursor/.cursor/rules/z-amend.mdc
 M exports/cursor/.cursor/rules/z-audit.mdc
 M exports/cursor/.cursor/rules/z-brainstorm.mdc
 M exports/cursor/.cursor/rules/z-do.mdc
 M exports/cursor/.cursor/rules/z-implement-all.mdc
 M exports/cursor/.cursor/rules/z-mr-review.mdc
 M exports/cursor/.cursor/rules/z-plan-light.mdc
 M exports/cursor/.cursor/rules/z-plan-split.mdc
 M exports/cursor/.cursor/rules/z-plan.mdc
 M exports/cursor/.cursor/rules/z-research.mdc
 M exports/cursor/.cursor/rules/z-review-all.mdc
 A scripts/check-timeout.sh
 A scripts/liveness.sh
 M skills/z-amend/SKILL.md
 M skills/z-brainstorm/SKILL.md
 M skills/z-debug/SKILL.md
 M skills/z-do/SKILL.md
 M skills/z-implement-all/SKILL.md
 M skills/z-improve/SKILL.md
 M skills/z-plan-light/SKILL.md
 M skills/z-plan-split/SKILL.md
 M skills/z-plan/SKILL.md
 M skills/z-research/SKILL.md
 M skills/z-review-all/SKILL.md
 M z-harness/archive/docs/events.jsonl
 M z-harness/archive/orchestration/events.jsonl
 M z-harness/archive/tasks/T001/events.jsonl
 M z-harness/archive/tasks/T001/review.prompt.md
 M z-harness/archive/tasks/T001/review.response.md
 M z-harness/archive/tasks/T002/events.jsonl
 M z-harness/archive/tasks/T003/review.prompt.md
 M z-harness/archive/tasks/T003/review.response.md
 A z-harness/lookup-cache/.gitignore
 M z-harness/metrics.jsonl
 A z-harness/plans/lookup-subagent/staging/qt-market-lookup.md
?? .agent/
?? agents/planning-router.md
?? commands/z-audit-plan.md
?? exports/agy/.agent/rules/z-harness-external-lookup.md
?? exports/agy/.agent/rules/z-harness-planning-router.md
?? exports/agy/.agent/skills/z-audit-plan/
?? exports/agy/.agent/workflows/z-audit-plan.md
?? exports/agy/prompts/external-lookup.md
?? exports/agy/prompts/planning-router.md
?? exports/agy/prompts/skill-z-audit-plan.md
?? exports/agy/prompts/z-audit-plan.md
?? exports/codex/prompts/z-audit-plan.md
?? exports/cursor/.cursor/rules/external-lookup.mdc
?? exports/cursor/.cursor/rules/planning-router.mdc
?? exports/cursor/.cursor/rules/z-audit-plan.mdc
?? skills/z-audit-plan/
?? z-harness/archive/20260524T184104Z-lookup-subagent/
?? z-harness/archive/20260524T184351Z-lookup-subagent/
?? z-harness/archive/20260524T190609Z-lookup-subagent/
?? z-harness/archive/20260524T201705Z-review/
?? z-harness/archive/20260524T203829Z-subagent-liveness/
?? z-harness/archive/20260525T000302Z-compaction-cadence/
?? z-harness/archive/compaction-cadence-plan-critique/
?? z-harness/archive/compaction-cadence/
?? z-harness/archive/consult-lookup-architecture/
?? z-harness/archive/consultant-review/
?? z-harness/archive/consults/
?? z-harness/archive/docs/20260524T235238Z-docs/
?? z-harness/archive/lookup-subagent-brainstorm/
?? z-harness/archive/lookup-subagent-review/
?? z-harness/archive/plan-bail-router/
?? z-harness/archive/tasks/T002/review.prompt.md
?? z-harness/archive/tasks/T002/review.response.md
?? z-harness/archive/tasks/T004/review.prompt.md
?? z-harness/archive/tasks/T004/review.response.md
?? z-harness/archive/tasks/T005/review.prompt.md
?? z-harness/archive/tasks/T005/review.response.md
?? z-harness/archive/tasks/subagent-liveness/
?? z-harness/archive/unified-review-tasks/
?? z-harness/plan-variant-bail-routing/
?? z-harness/plans/compaction-cadence/
?? z-harness/plans/finding-promotion-policy/
?? z-harness/plans/lookup-subagent/BRAINSTORM.md
?? z-harness/plans/lookup-subagent/PLAN.md
?? z-harness/plans/lookup-subagent/SPEC.md
?? z-harness/plans/lookup-subagent/TASKS.md
?? z-harness/plans/lookup-subagent/archive/
?? z-harness/plans/plan-bail-router/
?? z-harness/plans/subagent-liveness/
?? z-harness/plans/unified-review-tasks/
?? z-harness/plans/z-audit-plan/
?? z-harness/unified-review-tasks/
README.md
agents/consultant-primary.md
agents/consultant-secondary.md
agents/external-lookup.md
agents/implementer.md
agents/reviewer.md
commands/z-audit.md
commands/z-brainstorm.md
commands/z-do.md
commands/z-implement-all.md
commands/z-mr-review.md
commands/z-plan-light.md
commands/z-plan-split.md
commands/z-plan.md
commands/z-research.md
commands/z-review-all.md
docs/human/LIVENESS.md
docs/human/agents.md
docs/human/commands.md
docs/human/lookup-contract.md
docs/human/skills.md
docs/llm/INDEX.json
docs/llm/agents.json
docs/llm/commands.json
docs/llm/external-lookup-agent.json
docs/llm/lookup-contract.json
docs/llm/skills.json
exports/agy/.agent/rules/z-harness-consultant-primary.md
exports/agy/.agent/rules/z-harness-consultant-secondary.md
exports/agy/.agent/rules/z-harness-implementer.md
exports/agy/.agent/rules/z-harness-reviewer.md
exports/agy/.agent/skills/z-amend/SKILL.md
exports/agy/.agent/skills/z-brainstorm/SKILL.md
exports/agy/.agent/skills/z-do/SKILL.md
exports/agy/.agent/skills/z-implement-all/SKILL.md
exports/agy/.agent/skills/z-plan-light/SKILL.md
exports/agy/.agent/skills/z-plan-split/SKILL.md
exports/agy/.agent/skills/z-plan/SKILL.md
exports/agy/.agent/skills/z-research/SKILL.md
exports/agy/.agent/skills/z-review-all/SKILL.md
exports/agy/.agent/workflows/z-audit.md
exports/agy/.agent/workflows/z-brainstorm.md
exports/agy/.agent/workflows/z-do.md
exports/agy/.agent/workflows/z-implement-all.md
exports/agy/.agent/workflows/z-mr-review.md
exports/agy/.agent/workflows/z-plan-light.md
exports/agy/.agent/workflows/z-plan-split.md
exports/agy/.agent/workflows/z-plan.md
exports/agy/.agent/workflows/z-research.md
exports/agy/.agent/workflows/z-review-all.md
exports/agy/agy-plugin.yaml
exports/agy/prompts/consultant-primary.md
exports/agy/prompts/consultant-secondary.md
exports/agy/prompts/implementer.md
exports/agy/prompts/reviewer.md
exports/agy/prompts/skill-z-amend.md
exports/agy/prompts/skill-z-brainstorm.md
exports/agy/prompts/skill-z-do.md
exports/agy/prompts/skill-z-implement-all.md
exports/agy/prompts/skill-z-plan-light.md
exports/agy/prompts/skill-z-plan-split.md
exports/agy/prompts/skill-z-plan.md
exports/agy/prompts/skill-z-research.md
exports/agy/prompts/skill-z-review-all.md
exports/agy/prompts/z-audit.md
exports/agy/prompts/z-brainstorm.md
exports/agy/prompts/z-do.md
exports/agy/prompts/z-implement-all.md
exports/agy/prompts/z-mr-review.md
exports/agy/prompts/z-plan-light.md
exports/agy/prompts/z-plan-split.md
exports/agy/prompts/z-plan.md
exports/agy/prompts/z-research.md
exports/agy/prompts/z-review-all.md
exports/codex/AGENTS.md
exports/codex/prompts/z-amend.md
exports/codex/prompts/z-audit.md
exports/codex/prompts/z-brainstorm.md
exports/codex/prompts/z-do.md
exports/codex/prompts/z-implement-all.md
exports/codex/prompts/z-mr-review.md
exports/codex/prompts/z-plan-light.md
exports/codex/prompts/z-plan-split.md
exports/codex/prompts/z-plan.md
exports/codex/prompts/z-research.md
exports/codex/prompts/z-review-all.md
exports/cursor/.cursor/rules/consultant-primary.mdc
exports/cursor/.cursor/rules/consultant-secondary.mdc
exports/cursor/.cursor/rules/implementer.mdc
exports/cursor/.cursor/rules/reviewer.mdc
exports/cursor/.cursor/rules/z-amend.mdc
exports/cursor/.cursor/rules/z-audit.mdc
exports/cursor/.cursor/rules/z-brainstorm.mdc
exports/cursor/.cursor/rules/z-do.mdc
exports/cursor/.cursor/rules/z-implement-all.mdc
exports/cursor/.cursor/rules/z-mr-review.mdc
exports/cursor/.cursor/rules/z-plan-light.mdc
exports/cursor/.cursor/rules/z-plan-split.mdc
exports/cursor/.cursor/rules/z-plan.mdc
exports/cursor/.cursor/rules/z-research.mdc
exports/cursor/.cursor/rules/z-review-all.mdc
scripts/check-timeout.sh
scripts/liveness.sh
skills/z-amend/SKILL.md
skills/z-brainstorm/SKILL.md
skills/z-debug/SKILL.md
skills/z-do/SKILL.md
skills/z-implement-all/SKILL.md
skills/z-improve/SKILL.md
skills/z-plan-light/SKILL.md
skills/z-plan-split/SKILL.md
skills/z-plan/SKILL.md
skills/z-research/SKILL.md
skills/z-review-all/SKILL.md
z-harness/archive/docs/events.jsonl
z-harness/archive/orchestration/events.jsonl
z-harness/archive/tasks/T001/events.jsonl
z-harness/archive/tasks/T001/review.prompt.md
z-harness/archive/tasks/T001/review.response.md
z-harness/archive/tasks/T002/events.jsonl
z-harness/archive/tasks/T003/review.prompt.md
z-harness/archive/tasks/T003/review.response.md
z-harness/lookup-cache/.gitignore
z-harness/metrics.jsonl
z-harness/plans/lookup-subagent/staging/qt-market-lookup.md

codex
The first pass shows the route markers and router exports exist, but several acceptance-critical outputs are still untracked. I’m also running the three export scripts to catch generator failures or non-idempotent output.
exec
/bin/zsh -lc 'python3 scripts/export-codex.py' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'python3 scripts/export-cursor.py' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'python3 scripts/export-agy.py' in /Users/zeke/dev/z-harness
 succeeded in 131ms:
export-cursor: emitted 58 .mdc files to /Users/zeke/dev/z-harness/exports/cursor/.cursor/rules
  all 58 files passed validation.

 succeeded in 131ms:
export-codex: emitted 44 prompt files to /Users/zeke/dev/z-harness/exports/codex/prompts
  AGENTS.md written to /Users/zeke/dev/z-harness/exports/codex/AGENTS.md
  all 44 prompt files passed validation.

 succeeded in 161ms:
export-agy: emitted 26 workflows, 14 rules, 18 skills, 58 prompts to /Users/zeke/dev/z-harness/exports/agy
  agy-plugin.yaml: /Users/zeke/dev/z-harness/exports/agy/agy-plugin.yaml
  CAPABILITIES.md: /Users/zeke/dev/z-harness/exports/agy/CAPABILITIES.md
  README.md:       /Users/zeke/dev/z-harness/exports/agy/README.md
  all 116 prompt/workflow/rule/skill/ files passed validation.

codex
All three export scripts complete successfully. I’m checking the resulting status and the generator manifests now, because stale tracked/untracked output is the main risk for this task.
exec
/bin/zsh -lc "sed -n '1,260p' scripts/export-agy.py" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,240p' scripts/export-cursor.py" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
"""
export-cursor.py — Build Cursor .mdc rules from z-harness commands, agents, and skills.

Usage:
    python3 scripts/export-cursor.py [--out exports/cursor]

Emits one .mdc file per command / agent / skill into:
    exports/cursor/.cursor/rules/<id>.mdc

Frontmatter mapping:
    source description  → MDC description
    alwaysApply         → false (default)
    globs               → omitted unless source specifies

Body rewriting:
    Lines or blocks invoking Agent(...), Skill(...), or other Anthropic-specific
    constructs are replaced with a one-line HTML comment directing the reader to
    CAPABILITIES.md.

After emission, each .mdc file is re-parsed to verify:
    - YAML frontmatter is present and parseable between --- fences
    - Body is non-empty

A summary count is printed at the end.
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import re
import sys
from pathlib import Path

# Allow running from repo root: python3 scripts/export-cursor.py
_REPO_ROOT = Path(__file__).resolve().parent.parent

# export-common.py uses a hyphen so it is not directly importable; load it
# via importlib instead.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common",
    _REPO_ROOT / "scripts" / "export-common.py",
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
output_path_for = _COMMON_MOD.output_path_for
validate_capabilities = _COMMON_MOD.validate_capabilities


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

# Patterns that indicate Anthropic-specific / Claude Code constructs.
_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to remove Anthropic-specific constructs.

    Strategy: scan for Agent(...)/Skill(...)/AskUserQuestion(...) call sites.
    When found on a line, replace that entire line with the replacement comment
    (preserving leading whitespace for readability).  Code blocks that contain
    these constructs are handled line-by-line as well since cursor rules are
    read as plain markdown.
    """
    lines = body.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n\r")
        if (
            _AGENT_CALL_RE.search(stripped)
            or _SKILL_CALL_RE.search(stripped)
            or _TOOL_SCHEMA_RE.search(stripped)
        ):
            # Preserve leading whitespace, replace the rest.
            leading = len(stripped) - len(stripped.lstrip())
            result.append(" " * leading + _REPLACEMENT_COMMENT + "\n")
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# MDC rendering
# ---------------------------------------------------------------------------

def _render_mdc(entry: dict) -> str:
    """Render a single source *entry* as a Cursor .mdc string."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", "")
    # Escape any double-quotes in description for YAML safety.
    description_escaped = description.replace('"', '\\"')

    globs_line = ""
    if "globs" in fm:
        globs_escaped = fm["globs"].replace('"', '\\"')
        globs_line = f'\nglobs: "{globs_escaped}"'

    frontmatter_block = (
        f'---\n'
        f'description: "{description_escaped}"{globs_line}\n'
        f'alwaysApply: false\n'
        f'---\n'
    )

    rewritten_body = _rewrite_body(body)
    # Ensure body starts with a newline for readability.
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return frontmatter_block + rewritten_body


# ---------------------------------------------------------------------------
# MDC validation
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _validate_mdc(path: Path) -> list[str]:
    """Basic MDC validation: frontmatter present + parseable, body non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors

    fm_text = m.group(1)
    # Verify required keys are present in frontmatter.
    for required_key in ("description", "alwaysApply"):
        if not re.search(rf"^{required_key}\s*:", fm_text, re.MULTILINE):
            errors.append(f"{path}: frontmatter missing required key '{required_key}'")

    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export z-harness commands/agents/skills to Cursor .mdc rules."
    )
    p.add_argument(
        "--out",
        default="exports/cursor",
        help="Output root directory (default: exports/cursor)",
    )
    p.add_argument(
        "--repo",
        default=str(_REPO_ROOT),
        help="Repository root (default: parent of this script's directory)",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    repo_root = Path(args.repo).resolve()
    out_root = (repo_root / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    sources = enumerate_sources(repo_root)

    emitted: list[Path] = []
    skipped: list[tuple[str, str]] = []

    for kind in ("commands", "agents", "skills"):
        for entry in sources[kind]:
            eid = entry["id"]
            out_path = output_path_for(repo_root, "cursor", kind, eid)
            # If --out differs from the default, redirect accordingly.
            # output_path_for always writes under repo_root/exports/cursor;
            # honour --out by replacing that prefix.
            default_base = repo_root / "exports" / "cursor"
            if out_root != default_base:
                relative = out_path.relative_to(default_base)
                out_path = out_root / relative

            out_path.parent.mkdir(parents=True, exist_ok=True)

            mdc_content = _render_mdc(entry)
            out_path.write_text(mdc_content, encoding="utf-8")
            emitted.append(out_path)

    # Validate all emitted files.
    validation_errors: list[str] = []
    for path in emitted:
        validation_errors.extend(_validate_mdc(path))

    # Validate CAPABILITIES.md if it exists.
    caps_path = out_root / "CAPABILITIES.md"
    if caps_path.exists():
        cap_errors = validate_capabilities(caps_path)
        if cap_errors:
            validation_errors.extend(
                [f"CAPABILITIES.md: {e}" for e in cap_errors]
            )

    # Print summary.
    total = len(emitted)
    print(f"export-cursor: emitted {total} .mdc files to {out_root / '.cursor' / 'rules'}")

    if skipped:
        print(f"  skipped {len(skipped)} entries:")
        for sid, reason in skipped:
            print(f"    {sid}: {reason}")

    if validation_errors:
        print(f"\nValidation errors ({len(validation_errors)}):")
        for err in validation_errors:
            print(f"  ERROR: {err}")
        return 1

    print(f"  all {total} files passed validation.")
    return 0



 succeeded in 0ms:
"""
export-agy.py — Build Antigravity (agy) workflows and rules from z-harness sources.

Usage:
    python3 scripts/export-agy.py [--out exports/agy]

Emits:
  exports/agy/
    agy-plugin.yaml             -- z-harness export manifest (not read by agy natively)
    .agent/
      workflows/<id>.md         -- one per command (agy chat --mode <id>)
      rules/<id>.md             -- one per agent
    prompts/<id>.md             -- flat prompt files (commands + agents + skills)
    CAPABILITIES.md             -- unsupported-constructs documentation
    README.md                   -- install instructions

Frontmatter mapping:
    commands → workflow frontmatter:  description (from source or stem-based default)
    agents   → rule frontmatter:      trigger (always_on | model_decision), description

Body rewriting:
    Agent(...) / Skill(...) / AskUserQuestion(...) / TaskCreate(...) lines are replaced
    with an HTML comment directing the reader to CAPABILITIES.md.

Cascade (agy's AI) is Gemini-based; Anthropic-specific XML tags are also stripped.

After emission, basic validation is run on each generated file.
A summary count is printed at the end.
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import re
import sys
from pathlib import Path

# Allow running from repo root: python3 scripts/export-agy.py
_REPO_ROOT = Path(__file__).resolve().parent.parent

# export-common.py uses a hyphen so it is not directly importable; load via importlib.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common",
    _REPO_ROOT / "scripts" / "export-common.py",
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
validate_capabilities = _COMMON_MOD.validate_capabilities


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Antigravity; "
    "see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Replace Anthropic-specific construct call-sites with an HTML comment."""
    lines = body.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n\r")
        if (
            _AGENT_CALL_RE.search(stripped)
            or _SKILL_CALL_RE.search(stripped)
            or _TOOL_SCHEMA_RE.search(stripped)
        ):
            leading = len(stripped) - len(stripped.lstrip())
            result.append(" " * leading + _REPLACEMENT_COMMENT + "\n")
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# Workflow rendering (.agent/workflows/<id>.md)
# ---------------------------------------------------------------------------

def _render_workflow(entry: dict) -> str:
    """Render a command entry as an Antigravity workflow .md file."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", f"z-harness {entry['id']} workflow")
    # Strip any embedded '---' from description to avoid YAML delimiter conflict.
    description = description.replace("---", "—")
    # Truncate to 250-char limit.
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return f"---\ndescription: {description}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# Rule rendering (.agent/rules/<id>.md)
# ---------------------------------------------------------------------------

# Agents whose names suggest they are always-on context providers.
_ALWAYS_ON_AGENTS = {
    "implementer",
    "reviewer",
    "auditor",
    "mr-reviewer",
    "remote-runner",
}


def _agent_trigger(agent_id: str) -> str:
    return "always_on" if agent_id in _ALWAYS_ON_AGENTS else "model_decision"


def _render_rule(entry: dict) -> str:
    """Render an agent entry as an Antigravity rule .md file."""
    fm = entry["frontmatter"]
    body = entry["body"]

    agent_id = entry["id"]
    trigger = _agent_trigger(agent_id)

    description = fm.get("description", f"z-harness {agent_id} agent context")
    description = description.replace("---", "—")
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    frontmatter_lines = [f"trigger: {trigger}"]
    if trigger == "model_decision":
        frontmatter_lines.append(f"description: {description}")

    fm_block = "---\n" + "\n".join(frontmatter_lines) + "\n---\n"
    return fm_block + rewritten_body


def _render_skill(entry: dict) -> str:
    """Render a skill entry as an Antigravity skill SKILL.md file."""
    fm = entry["frontmatter"]
    body = entry["body"]

    skill_id = entry["id"]
    description = fm.get("description", f"z-harness {skill_id} skill")
    description = description.replace("---", "—")
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return f"---\nname: {skill_id}\ndescription: {description}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# Prompt rendering (exports/agy/prompts/<id>.md)
# ---------------------------------------------------------------------------

def _render_prompt(entry: dict, role: str) -> str:
    """Render a flat prompt file with YAML frontmatter (description, role)."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", f"z-harness {entry['id']}")
    description = description.replace("---", "—")
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return f"---\ndescription: {description}\nrole: {role}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# agy-plugin.yaml generation
# ---------------------------------------------------------------------------

def _yaml_str(value: str) -> str:
    """Emit a YAML scalar, quoting if the value contains special characters."""
    needs_quotes = any(c in value for c in (':', '#', '"', "'", '{', '}', '[', ']', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '\n'))
    if needs_quotes:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _build_manifest(sources: dict, repo_name: str = "z-harness") -> str:
    """Build the agy-plugin.yaml manifest content."""
    lines: list[str] = []

    lines.append("# agy-plugin.yaml")
    lines.append("# z-harness agy export manifest — read by scripts/export-agy.py")
    lines.append("# NOT a native Antigravity file format (agy does not read this)")
    lines.append("schema_version: 1")
    lines.append("")
    lines.append("metadata:")
    lines.append(f"  name: {repo_name}")
    lines.append("  description: z-harness planning and implementation workflow for Antigravity IDE")
    lines.append("  source_repo: https://github.com/zeke-tools/z-harness")
    lines.append("")

    # Commands → workflows
    lines.append("# Commands → .agent/workflows/*.md")
    lines.append("# Each command becomes a custom chat mode (agy chat --mode <id>)")
    lines.append("workflows:")
    for entry in sources["commands"]:
        eid = entry["id"]
        fm = entry["frontmatter"]
        description = fm.get("description", f"z-harness {eid} workflow")
        description = description.replace("---", "—")
        if len(description) > 250:
            description = description[:247] + "..."
        source_rel = f"commands/{entry['source_path'].name}"
        lines.append(f"  - id: {eid}")
        lines.append(f"    source: {source_rel}")
        lines.append(f"    output: .agent/workflows/{eid}.md")
        lines.append(f"    description: {_yaml_str(description)}")
    lines.append("")

    # Agents → rules
    lines.append("# Agents → .agent/rules/*.md")
    lines.append("# No subagent dispatch in agy; agents become role-specific rule files")
    lines.append("rules:")
    for entry in sources["agents"]:
        eid = entry["id"]
        fm = entry["frontmatter"]
        description = fm.get("description", f"z-harness {eid} agent context")
        description = description.replace("---", "—")
        if len(description) > 250:
            description = description[:247] + "..."
        trigger = _agent_trigger(eid)
        source_rel = f"agents/{entry['source_path'].name}"
        lines.append(f"  - id: {eid}")
        lines.append(f"    source: {source_rel}")
        lines.append(f"    output: .agent/rules/z-harness-{eid}.md")
        lines.append(f"    trigger: {trigger}")
        lines.append(f"    description: {_yaml_str(description)}")
    lines.append("")

    # Skills → .agent/skills/<id>/SKILL.md

exec
/bin/zsh -lc "sed -n '1,220p' scripts/export-codex.py" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
"""
export-codex.py — Build Codex CLI prompt files from z-harness commands, agents, and skills.

Usage:
    python3 scripts/export-codex.py [--out exports/codex]

Emits one prompt .md file per command / skill into:
    exports/codex/prompts/<id>.md

Agents are consolidated into:
    exports/codex/AGENTS.md   (one ## <agent-id> section per agent)

Body rewriting:
    Lines invoking Agent(...), Skill(...), AskUserQuestion(...) are replaced
    with an HTML comment directing the reader to CAPABILITIES.md.
"""

# ---------------------------------------------------------------------------
# Format research note
#
# Codex CLI (OpenAI) reads task prompts via stdin:
#     cat prompts/<id>.md | codex exec -
#
# The recommended pattern for batch/template usage is to maintain a directory
# of prompt files and pipe them on demand.  There is no native "prompt
# library" concept built into the Codex CLI binary itself — the per-file
# convention is an empirical best-practice observed in the community.  From
# `codex --help` and the openai-codex README:
#
#     codex exec -          # reads the task prompt from stdin
#     codex exec <task>     # inline string task
#
# So each z-harness command/skill maps to one prompt file:
#     exports/codex/prompts/<id>.md
# Users either pipe it:
#     cat exports/codex/prompts/z-plan.md | codex exec -
# Or reference it from a wrapper script.
#
# Agents are consolidated into AGENTS.md because Codex CLI has no native
# subagent dispatch — the file documents the agent roles so users can manually
# invoke the right prompt.
#
# Anthropic-specific constructs (Agent(), Skill(), AskUserQuestion()) are
# replaced with HTML comments referencing CAPABILITIES.md.
# ---------------------------------------------------------------------------

from __future__ import annotations

import argparse
import importlib.util as _ilu
import re
import sys
from pathlib import Path

# Allow running from repo root: python3 scripts/export-codex.py
_REPO_ROOT = Path(__file__).resolve().parent.parent

# export-common.py uses a hyphen so it is not directly importable; load it
# via importlib instead.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common",
    _REPO_ROOT / "scripts" / "export-common.py",
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
output_path_for = _COMMON_MOD.output_path_for
validate_capabilities = _COMMON_MOD.validate_capabilities


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

# Patterns that indicate Anthropic-specific / Claude Code constructs.
_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(",
    re.MULTILINE,
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Codex CLI;"
    " see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to remove Anthropic-specific constructs.

    Lines containing Agent(...), Skill(...), AskUserQuestion(...) etc. are
    replaced line-by-line with a single HTML comment, preserving leading
    whitespace.
    """
    lines = body.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n\r")
        if (
            _AGENT_CALL_RE.search(stripped)
            or _SKILL_CALL_RE.search(stripped)
            or _TOOL_SCHEMA_RE.search(stripped)
        ):
            leading = len(stripped) - len(stripped.lstrip())
            result.append(" " * leading + _REPLACEMENT_COMMENT + "\n")
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# Prompt file rendering (commands + skills)
# ---------------------------------------------------------------------------

def _render_prompt(entry: dict) -> str:
    """Render a single command/skill *entry* as a Codex prompt file.

    Format:
        # /<id>
        <rewritten body>
    """
    entry_id = entry["id"]
    body = entry["body"]

    header = f"# /{entry_id}\n"
    rewritten_body = _rewrite_body(body)

    # Strip leading blank lines from body (frontmatter separator artifacts).
    rewritten_body = rewritten_body.lstrip("\n")

    return header + "\n" + rewritten_body


# ---------------------------------------------------------------------------
# AGENTS.md rendering
# ---------------------------------------------------------------------------

def _render_agents_md(agents: list[dict]) -> str:
    """Render all agents as a single consolidated AGENTS.md."""
    lines: list[str] = [
        "# Agents\n",
        "\n",
        "This file documents all z-harness agents exported for Codex CLI use.\n",
        "\n",
        "Codex CLI has no native subagent dispatch.  These agent definitions\n",
        "describe the **role and behaviour** of each agent so you can manually\n",
        "compose prompts or invoke the appropriate prompt file.\n",
        "\n",
        "---\n",
        "\n",
    ]

    for entry in agents:
        agent_id = entry["id"]
        fm = entry["frontmatter"]
        body = entry["body"]

        description = fm.get("description", "")
        role_line = f"**Role:** {description}\n" if description else ""

        rewritten_body = _rewrite_body(body)
        rewritten_body = rewritten_body.lstrip("\n")

        lines.append(f"## {agent_id}\n")
        lines.append("\n")
        if role_line:
            lines.append(role_line)
            lines.append("\n")
        lines.append(rewritten_body)
        if not rewritten_body.endswith("\n"):
            lines.append("\n")
        lines.append("\n---\n\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Prompt validation
# ---------------------------------------------------------------------------

def _validate_prompt(path: Path) -> list[str]:
    """Validate a prompt .md file: header line present, body non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    lines = text.splitlines()
    if not lines:
        errors.append(f"{path}: file is empty")
        return errors

    if not lines[0].startswith("# /"):
        errors.append(
            f"{path}: first line must be '# /<id>', got: {lines[0]!r}"
        )

    body_lines = [ln for ln in lines[1:] if ln.strip()]
    if not body_lines:
        errors.append(f"{path}: body is empty (no non-blank lines after header)")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export z-harness commands/agents/skills to Codex CLI prompt files."
    )
    p.add_argument(
        "--out",
        default="exports/codex",
        help="Output root directory (default: exports/codex)",
    )

exec
/bin/zsh -lc 'git status --short exports/agy exports/codex exports/cursor agents/planning-router.md commands/z-audit-plan.md skills/z-audit-plan docs/llm docs/human' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
 A docs/human/LIVENESS.md
 M docs/human/agents.md
 M docs/human/commands.md
 A docs/human/lookup-contract.md
 M docs/human/skills.md
 M docs/llm/INDEX.json
 M docs/llm/agents.json
 M docs/llm/commands.json
 A docs/llm/external-lookup-agent.json
 A docs/llm/lookup-contract.json
 M docs/llm/skills.json
 M exports/agy/.agent/rules/z-harness-consultant-primary.md
 M exports/agy/.agent/rules/z-harness-consultant-secondary.md
 M exports/agy/.agent/rules/z-harness-implementer.md
 M exports/agy/.agent/rules/z-harness-reviewer.md
 M exports/agy/.agent/skills/z-amend/SKILL.md
 M exports/agy/.agent/skills/z-brainstorm/SKILL.md
 M exports/agy/.agent/skills/z-do/SKILL.md
 M exports/agy/.agent/skills/z-implement-all/SKILL.md
 M exports/agy/.agent/skills/z-plan-light/SKILL.md
 M exports/agy/.agent/skills/z-plan-split/SKILL.md
 M exports/agy/.agent/skills/z-plan/SKILL.md
 M exports/agy/.agent/skills/z-research/SKILL.md
 M exports/agy/.agent/skills/z-review-all/SKILL.md
 M exports/agy/.agent/workflows/z-audit.md
 M exports/agy/.agent/workflows/z-brainstorm.md
 M exports/agy/.agent/workflows/z-do.md
 M exports/agy/.agent/workflows/z-implement-all.md
 M exports/agy/.agent/workflows/z-mr-review.md
 M exports/agy/.agent/workflows/z-plan-light.md
 M exports/agy/.agent/workflows/z-plan-split.md
 M exports/agy/.agent/workflows/z-plan.md
 M exports/agy/.agent/workflows/z-research.md
 M exports/agy/.agent/workflows/z-review-all.md
 M exports/agy/agy-plugin.yaml
 M exports/agy/prompts/consultant-primary.md
 M exports/agy/prompts/consultant-secondary.md
 M exports/agy/prompts/implementer.md
 M exports/agy/prompts/reviewer.md
 M exports/agy/prompts/skill-z-amend.md
 M exports/agy/prompts/skill-z-brainstorm.md
 M exports/agy/prompts/skill-z-do.md
 M exports/agy/prompts/skill-z-implement-all.md
 M exports/agy/prompts/skill-z-plan-light.md
 M exports/agy/prompts/skill-z-plan-split.md
 M exports/agy/prompts/skill-z-plan.md
 M exports/agy/prompts/skill-z-research.md
 M exports/agy/prompts/skill-z-review-all.md
 M exports/agy/prompts/z-audit.md
 M exports/agy/prompts/z-brainstorm.md
 M exports/agy/prompts/z-do.md
 M exports/agy/prompts/z-implement-all.md
 M exports/agy/prompts/z-mr-review.md
 M exports/agy/prompts/z-plan-light.md
 M exports/agy/prompts/z-plan-split.md
 M exports/agy/prompts/z-plan.md
 M exports/agy/prompts/z-research.md
 M exports/agy/prompts/z-review-all.md
 M exports/codex/AGENTS.md
 M exports/codex/prompts/z-amend.md
 M exports/codex/prompts/z-audit.md
 M exports/codex/prompts/z-brainstorm.md
 M exports/codex/prompts/z-do.md
 M exports/codex/prompts/z-implement-all.md
 M exports/codex/prompts/z-mr-review.md
 M exports/codex/prompts/z-plan-light.md
 M exports/codex/prompts/z-plan-split.md
 M exports/codex/prompts/z-plan.md
 M exports/codex/prompts/z-research.md
 M exports/codex/prompts/z-review-all.md
 M exports/cursor/.cursor/rules/consultant-primary.mdc
 M exports/cursor/.cursor/rules/consultant-secondary.mdc
 M exports/cursor/.cursor/rules/implementer.mdc
 M exports/cursor/.cursor/rules/reviewer.mdc
 M exports/cursor/.cursor/rules/z-amend.mdc
 M exports/cursor/.cursor/rules/z-audit.mdc
 M exports/cursor/.cursor/rules/z-brainstorm.mdc
 M exports/cursor/.cursor/rules/z-do.mdc
 M exports/cursor/.cursor/rules/z-implement-all.mdc
 M exports/cursor/.cursor/rules/z-mr-review.mdc
 M exports/cursor/.cursor/rules/z-plan-light.mdc
 M exports/cursor/.cursor/rules/z-plan-split.mdc
 M exports/cursor/.cursor/rules/z-plan.mdc
 M exports/cursor/.cursor/rules/z-research.mdc
 M exports/cursor/.cursor/rules/z-review-all.mdc
?? agents/planning-router.md
?? commands/z-audit-plan.md
?? exports/agy/.agent/rules/z-harness-external-lookup.md
?? exports/agy/.agent/rules/z-harness-planning-router.md
?? exports/agy/.agent/skills/z-audit-plan/
?? exports/agy/.agent/workflows/z-audit-plan.md
?? exports/agy/prompts/external-lookup.md
?? exports/agy/prompts/planning-router.md
?? exports/agy/prompts/skill-z-audit-plan.md
?? exports/agy/prompts/z-audit-plan.md
?? exports/codex/prompts/z-audit-plan.md
?? exports/cursor/.cursor/rules/external-lookup.mdc
?? exports/cursor/.cursor/rules/planning-router.mdc
?? exports/cursor/.cursor/rules/z-audit-plan.mdc
?? skills/z-audit-plan/

exec
/bin/zsh -lc "sed -n '260,520p' scripts/export-agy.py && sed -n '1,220p' scripts/export-common.py" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    # Skills → .agent/skills/<id>/SKILL.md
    lines.append("# Skills → .agent/skills/<id>/SKILL.md")
    lines.append("# Native workspace skills in Antigravity")
    if sources["skills"]:
        lines.append("skills:")
        for entry in sources["skills"]:
            eid = entry["id"]
            source_rel = f"skills/{eid}/SKILL.md"
            lines.append(f"  - id: {eid}")
            lines.append(f"    source: {source_rel}")
            lines.append(f"    output: .agent/skills/{eid}/SKILL.md")
            fm = entry["frontmatter"]
            description = fm.get("description", f"z-harness {eid} skill")
            description = description.replace("---", "—")
            if len(description) > 250:
                description = description[:247] + "..."
            lines.append(f"    description: {_yaml_str(description)}")
    else:
        lines.append("skills: []")
    lines.append("")

    # MCP hint
    lines.append("# MCP tools — optional; registered separately by the user")
    lines.append("# Listed here for documentation only; export-agy.py does not write mcp_config.json")
    lines.append("mcp_hint:")
    lines.append("  - tool: z-harness-log")
    lines.append('    description: "Would be implemented as MCP server for metrics/event logging"')
    lines.append("    status: not_implemented")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CAPABILITIES.md
# ---------------------------------------------------------------------------

_CAPABILITIES_MD = """\
# Antigravity (agy) Export — CAPABILITIES.md

This document describes what the z-harness feature set can and cannot express
when exported to Antigravity IDE (Google's agy / Cascade agent platform).

---

## Supported

The following z-harness constructs have direct or near-direct equivalents in Antigravity:

| z-harness construct | Antigravity equivalent |
|---------------------|----------------------|
| `commands/*.md` (slash commands) | `.agent/workflows/<name>.md` — custom chat modes (`agy chat --mode <id>`) |
| `agents/*.md` (agent definitions) | `.agent/rules/<name>.md` — always_on or model_decision rules |
| `skills/*/SKILL.md` (skills) | `.agent/skills/<name>/SKILL.md` — workspace skills |
| `Bash`, `Read`, `Edit`, `Write` tools | Cascade native tools (exact names may differ; semantics are equivalent) |
| `AskUserQuestion` tool (clarification) | Cascade conversational turn (native; no special syntax needed) |
| `WebFetch`, `WebSearch` tools | Cascade native (if enabled in the workspace) |
| Markdown body / instruction content | Passed as system-level instructions to Cascade (Gemini-based) |
| `metrics.jsonl` shell writes | Shell commands in workflow bodies work; writes to workspace-relative paths |

---

## Unsupported

The following z-harness features have no native Antigravity equivalent:

1. **Subagent dispatch (`Agent(subagent_type=...)`)** — Cascade exposes no `Agent()` builtin
   and no `.agent/subagents/` directory.  Workaround: call `agy chat --mode <workflow-id>`
   from a shell command in the workflow body. This does not nest within a running Cascade
   session; it launches a new top-level session.

2. **Programmatic Skill Invocation (`Skill(name=...)`)** — Although Antigravity natively
   supports workspace skills under `.agent/skills/<name>/SKILL.md`, it does not support
   programmatic `Skill()` runtime API calls or dynamic inclusion. Downstream actions that rely
   on programmatic skill loading must be handled as instructions directing Cascade to load the
   appropriate workspace skill.

3. **Provider registry (`providers.json`, `resolve-provider.sh`)** — Cascade is bound to
   Gemini; there is no multi-provider routing mechanism.  All provider-routing logic in
   `scripts/resolve-provider.sh` is inapplicable.

4. **Multi-model review loop** — `/z-review-all` dispatches Codex + Gemini reviewers in
   parallel.  Single-provider Cascade cannot replicate this pattern; only one reviewer
   (the Cascade agent itself) is available.

5. **`Z_HARNESS_PLANS_DIR` + `plan-path.sh` env injection** — Cascade workflows cannot
   receive injected environment variables at load time.  Any path that z-harness resolves
   via `$Z_HARNESS_PLANS_DIR` must be hardcoded or assumed to be the workspace root in the
   exported workflow body.

6. **`metrics.jsonl` event stream (structured)** — `log-event.sh` and `log-phase.sh` write
   JSONL files.  These shell commands work inside workflow bodies but require the workspace
   to be writable at the expected paths.  The `TOKEN=` handshake pattern (start → end)
   may not survive across Cascade turns if the agent context is reset.

7. **`AskUserQuestion` structured return** — Claude Code's `AskUserQuestion` tool pauses
   execution and returns a typed answer object.  Cascade's equivalent is a conversational
   turn with no structured return value; downstream logic that branches on the answer type
   must be restructured as plain Markdown instructions.

8. **Workflow bodies > 12,000 characters** — Several z-harness commands (e.g., `z-plan`)
   exceed the Antigravity content limit for workflow files.  Mitigation: split into
   sub-workflows, or link to an external file if `@file` syntax is supported (unconfirmed
   as of agy 1.107.0).

---

## Notes

- **Gemini prompt norms:** Cascade is Gemini-based.  Anthropic-specific XML tags (e.g.,
  `<parameter name="thinking">`, `<result>`) are stripped during export and should not appear in
  workflow bodies.  Use clear imperative Markdown headings instead.

- **Workflow file placement:** Antigravity auto-discovers `.agent/workflows/**/*.md` by
  watching the workspace directory tree.  No install step is required after copying files.
  For global scope (available across all workspaces), place workflow files at:
  `~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/<name>.md`

- **Rule trigger values:** `always_on` (every session), `model_decision` (model chooses
  based on `description`), `glob` (applied when matching files are in context).

- **`agy-plugin.yaml`** is a z-harness convention manifest, not a native Antigravity
  format.  Antigravity does not read this file; it is used only by `scripts/export-agy.py`
  to document the mapping between source files and generated output.
"""


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------

_README_MD = """\
# z-harness → Antigravity (agy) Export

This directory contains z-harness commands, agents, and skills exported as Antigravity
(Google's agy IDE) workflow, rule, and skill files.

## What's included

| Path | Purpose |
|------|---------|
| `.agent/workflows/*.md` | Custom chat modes — one per z-harness command |
| `.agent/rules/*.md` | Always-on or model-decision rules — one per z-harness agent |
| `.agent/skills/*` | Workspace skills — one per z-harness skill |
| `prompts/*.md` | Flat prompt files (description + role frontmatter) |
| `agy-plugin.yaml` | Export manifest (z-harness convention; not read by agy) |
| `CAPABILITIES.md` | What can and cannot be expressed in Antigravity |

## Install

### Per-project (recommended)

Copy the `.agent/` directory into your project workspace root:

```bash
cp -r exports/agy/.agent /path/to/your/project/
```

Antigravity auto-discovers `.agent/workflows/**/*.md`, `.agent/rules/**/*.md`, and `.agent/skills/**/*`
by watching the workspace directory tree.  No restart required — files become
available immediately in the IDE.

### Global (all workspaces)

To make workflows available across all projects, copy them to the global workflows path:

```bash
mkdir -p ~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/
cp exports/agy/.agent/workflows/*.md \\
  ~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/
```

## Usage

After installing, invoke a workflow from the command line:

```bash
agy chat --mode z-plan "Add user authentication feature"
agy chat --mode z-implement-next
agy chat --mode z-review-all
```

Or select the mode from the Antigravity IDE mode picker in the chat panel.

## Re-generating

Run the export script from the repo root:

```bash
python3 scripts/export-agy.py
# or with a custom output directory:
python3 scripts/export-agy.py --out /path/to/output
```

## Known limitations

See `CAPABILITIES.md` for a full list of z-harness features that cannot be
expressed in Antigravity (subagent dispatch, skills, multi-model review, etc.).
"""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _validate_workflow(path: Path) -> list[str]:
    """Validate an Antigravity workflow .md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    if not re.search(r"^description\s*:", fm_text, re.MULTILINE):
        errors.append(f"{path}: workflow frontmatter missing 'description'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


def _validate_rule(path: Path) -> list[str]:
    """Validate an Antigravity rule .md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    if not re.search(r"^trigger\s*:", fm_text, re.MULTILINE):
        errors.append(f"{path}: rule frontmatter missing 'trigger'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


def _validate_skill(path: Path) -> list[str]:
    """Validate an Antigravity skill SKILL.md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    for key in ("name", "description"):
        if not re.search(rf"^{key}\s*:", fm_text, re.MULTILINE):
            errors.append(f"{path}: skill frontmatter missing '{key}'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


def _validate_prompt(path: Path) -> list[str]:
"""
export-common.py — shared helpers for the multi-IDE export pipeline.

Importable by export-cursor.py, export-codex.py, export-agy.py, and any
other per-target adapter. Stdlib only; no third-party deps.

Public surface:
  enumerate_sources(repo_root) -> dict
  validate_capabilities(path) -> list[str]
  output_path_for(repo_root, target, kind, id) -> Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-fenced frontmatter at the top of *text*.

    Returns (frontmatter_dict, body_text).  Only simple ``key: value`` pairs
    are handled — no nested structures, sequences, or multi-line values.  This
    is intentional: the source files in this repo only use flat frontmatter.
    """
    frontmatter: dict[str, str] = {}
    body = text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return frontmatter, body

    end_fence = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            end_fence = i
            break

    if end_fence == -1:
        return frontmatter, body

    for line in lines[1:end_fence]:
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*:\s*(.*)', stripped)
        if match:
            frontmatter[match.group(1)] = match.group(2).strip()

    body = "".join(lines[end_fence + 1:])
    return frontmatter, body


# ---------------------------------------------------------------------------
# Source enumeration
# ---------------------------------------------------------------------------

def _collect_entries(directory: Path) -> list[dict[str, Any]]:
    """Return one entry dict per markdown file in *directory* (non-recursive)."""
    if not directory.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        entries.append(
            {
                "id": path.stem,
                "source_path": path,
                "frontmatter": frontmatter,
                "body": body,
            }
        )
    return entries


def _collect_skills(skills_dir: Path) -> list[dict[str, Any]]:
    """Return one entry per skill (each skill lives in its own sub-directory
    as ``skills/<name>/SKILL.md``)."""
    if not skills_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        entries.append(
            {
                "id": skill_dir.name,
                "source_path": skill_file,
                "frontmatter": frontmatter,
                "body": body,
            }
        )
    return entries


def enumerate_sources(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Return a dict with keys ``commands``, ``agents``, ``skills``.

    Each value is a list of entry dicts::

        {
            "id": str,                      # stem of the source file / skill dir name
            "source_path": pathlib.Path,    # absolute path to the source file
            "frontmatter": dict[str, str],  # parsed key/value pairs (flat)
            "body": str,                    # markdown body after the frontmatter fence
        }
    """
    repo_root = Path(repo_root).resolve()
    return {
        "commands": _collect_entries(repo_root / "commands"),
        "agents": _collect_entries(repo_root / "agents"),
        "skills": _collect_skills(repo_root / "skills"),
    }


# ---------------------------------------------------------------------------
# CAPABILITIES.md schema validation
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS = ("## Supported", "## Unsupported", "## Notes")


def validate_capabilities(path: Path) -> list[str]:
    """Validate that *path* is a CAPABILITIES.md file conforming to the
    minimal schema.

    Required sections: ``## Supported``, ``## Unsupported``, ``## Notes``.

    Returns a list of validation error strings.  An empty list means the file
    is valid.
    """
    errors: list[str] = []
    path = Path(path)

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    text = path.read_text(encoding="utf-8")
    for section in _REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"Missing required section: {section!r}")

    return errors


# ---------------------------------------------------------------------------
# Per-target output path computation
# ---------------------------------------------------------------------------

_TARGET_CONVENTIONS: dict[str, dict[str, str]] = {
    "cursor": {
        "commands": ".cursor/rules/{id}.mdc",
        "agents": ".cursor/rules/{id}.mdc",
        "skills": ".cursor/rules/{id}.mdc",
    },
    "codex": {
        "commands": "prompts/{id}.md",
        "agents": "prompts/{id}.md",
        "skills": "prompts/{id}.md",
    },
    "agy": {
        "commands": "prompts/{id}.md",
        "agents": "prompts/{id}.md",
        "skills": "prompts/{id}.md",
    },
}


def output_path_for(repo_root: Path, target: str, kind: str, id: str) -> Path:
    """Return the conventional output path for a given export target.

    Args:
        repo_root: Absolute path to the repository root.
        target: Export target name — one of ``cursor``, ``codex``, ``agy``.
        kind: Source kind — one of ``commands``, ``agents``, ``skills``.
        id: Source identifier (file stem / skill dir name).

    Returns:
        An absolute Path inside ``exports/<target>/`` following the per-target
        convention:

        - cursor → ``exports/cursor/.cursor/rules/<id>.mdc``
        - codex  → ``exports/codex/prompts/<id>.md``
        - agy    → ``exports/agy/prompts/<id>.md``

    Raises:
        ValueError: if *target* or *kind* is not recognised.
    """
    repo_root = Path(repo_root).resolve()

    if target not in _TARGET_CONVENTIONS:
        raise ValueError(
            f"Unknown target {target!r}. Valid targets: {sorted(_TARGET_CONVENTIONS)}"
        )
    kind_map = _TARGET_CONVENTIONS[target]
    if kind not in kind_map:
        raise ValueError(
            f"Unknown kind {kind!r}. Valid kinds: {sorted(kind_map)}"
        )

    relative = kind_map[kind].format(id=id)
    return repo_root / "exports" / target / relative

exec
/bin/zsh -lc "find exports/cursor/.cursor/rules -maxdepth 1 -type f -name '*.mdc' | wc -l" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
      40

exec
/bin/zsh -lc "sed -n '1,25p' exports/cursor/.cursor/rules/planning-router.mdc; sed -n '1,25p' agents/planning-router.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: "Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only."
alwaysApply: false
---

## Mission

You are a cheap, read-only ambiguity resolver for z-harness planning-family route decisions. The caller has already collected compact deterministic signals and needs an advisory recommendation only when hard thresholds did not settle the route.

You do not edit files, do not call other agents, do not run shell commands, and do not perform broad repo exploration. Prefer the caller's supplied signals over inventing facts.

## Inputs From Caller

The caller prompt must provide:

- `current_command`: the command currently running.
- `task_or_topic`: the user's task or topic, kept compact.
- `signals_json`: JSON object containing deterministic route signals.
- `route_chain_json`: JSON array of prior route hops, or `[]`.
- `repo_root`: absolute path to the repo root.

The caller may also provide:

- `existing_artifacts`: compact list of relevant artifacts such as `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`, `RESEARCH.md`, or `BRAINSTORM.md`.

---
name: planning-router
description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
tools: Read, Grep, Glob
model: haiku
---

## Mission

You are a cheap, read-only ambiguity resolver for z-harness planning-family route decisions. The caller has already collected compact deterministic signals and needs an advisory recommendation only when hard thresholds did not settle the route.

You do not edit files, do not call other agents, do not run shell commands, and do not perform broad repo exploration. Prefer the caller's supplied signals over inventing facts.

## Inputs From Caller

The caller prompt must provide:

- `current_command`: the command currently running.
- `task_or_topic`: the user's task or topic, kept compact.
- `signals_json`: JSON object containing deterministic route signals.
- `route_chain_json`: JSON array of prior route hops, or `[]`.
- `repo_root`: absolute path to the repo root.

The caller may also provide:


exec
/bin/zsh -lc "sed -n '1,18p' exports/cursor/.cursor/rules/z-do.mdc; sed -n '1,18p' commands/z-do.md; sed -n '1,18p' skills/z-do/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: "Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution."
alwaysApply: false
---

You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.

## Setup

1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
2. `export Z_HARNESS_SLUG=adhoc`
3. `mkdir -p z-harness/adhoc/archive/$RUN`
---
description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
argument-hint: <small task description>
---

You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.

## Setup

1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
2. `export Z_HARNESS_SLUG=adhoc`
3. `mkdir -p z-harness/adhoc/archive/$RUN`
---
name: z-do
description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
argument-hint: <small task description>
---

You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.

## Setup

1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
2. `export Z_HARNESS_SLUG=adhoc`

exec
/bin/zsh -lc "for f in z-do z-plan-light z-plan z-plan-split z-brainstorm z-research z-audit-plan; do printf '%s cursor=' \""'$f"; rg -c '"'<"'!-- PLAN_ROUTE_CHECK_START -->'"' exports/cursor/.cursor/rules/"'$f.mdc 2>/dev/null || true; printf '"'%s codex=' \" "'$f"; rg -c '"'<"'!-- PLAN_ROUTE_CHECK_START -->'"' exports/codex/prompts/"'$f.md 2>/dev/null || true; printf '"'%s agy-workflow=' \" "'$f"; rg -c '"'<"'!-- PLAN_ROUTE_CHECK_START -->'"' exports/agy/.agent/workflows/"'$f.md 2>/dev/null || true; printf '"'%s agy-skill=' \" "'$f"; rg -c '"'<"'!-- PLAN_ROUTE_CHECK_START -->'"' exports/agy/.agent/skills/"'$f/SKILL.md 2>/dev/null || true; done' in /Users/zeke/dev/z-harness
 succeeded in 172ms:
 z-plan-split codex=1
 z-plan-split agy-workflow=1
 z-plan-split agy-skill=1
z-brainstorm cursor=1
 z-brainstorm codex=1
 z-brainstorm agy-workflow=1
 z-brainstorm agy-skill=1
z-research cursor=1
 z-research codex=1
 z-research agy-workflow=1
 z-research agy-skill=1
z-audit-plan cursor=1
 z-audit-plan codex=1
 z-audit-plan agy-workflow=1
 z-audit-plan agy-skill=1

exec
/bin/zsh -lc "nl -ba agents/planning-router.md | sed -n '118,150p'; nl -ba commands/z-plan-split.md | sed -n '150,156p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
   118	
   119	`non_obvious_decisions: null` means the count is unknown; it does not satisfy "no non-obvious decisions." Likewise, `/z-plan-split` requires an explicit caller-supplied `cluster_seams_independently_plannable: true` signal before recommending a split.
   120	
   121	## Decision Rules
   122	
   123	Apply these rules in order:
   124	
   125	1. If any required input is absent or malformed, return `STATUS: bad_input`.
   126	2. Inspect `route_chain_json` before recommending a target. If the chain already contains two prior entries, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
   127	3. If the best recommendation would send the user back to the immediate prior `from_command`, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
   128	4. Prefer contextual exits when their preconditions are explicit:
   129	   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
   130	   - `has_existing_plan` plus requested plan modification -> `/z-amend`
   131	   - `has_bug_diagnosis` -> `/z-fix`
   132	   - `has_unknown_bug_symptom` -> `/z-debug`
   133	   - `docs_stale_or_drifted` -> `/z-maintain-docs`
   134	5. If `terrain_uncertain` is true, recommend `/z-research`.
   135	6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
   136	7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
   137	   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
   138	   - If `cluster_seams == 1`, recommend `/z-plan` with `too_few_clusters`.
   139	   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
   140	   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
   141	8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
   142	9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
   143	10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
   144	11. Otherwise recommend `/z-plan`.
   145	
   146	If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
   147	
   148	## Confidence Guidance
   149	
   150	- `high`: supplied signals point clearly to one target and required preconditions are explicit.
   150	
   151	Deterministic routes:
   152	- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
   153	- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
   154	- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
   155	- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
   156	- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.

exec
/bin/zsh -lc "nl -ba commands/z-audit-plan.md | sed -n '1,90p'; nl -ba skills/z-audit-plan/SKILL.md | sed -n '1,90p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	---
     2	description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
     3	argument-hint: [--slug <slug>]
     4	---
     5	
     6	You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
     7	
     8	This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.
     9	
    10	<!-- PLAN_ROUTE_CHECK_START -->
    11	## Plan Route Check
    12	
    13	Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
    14	
    15	Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.
    16	
    17	Deterministic routes:
    18	- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
    19	- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
    20	- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
    21	- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.
    22	
    23	Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
    24	
    25	If routing, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
    26	
    27	Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
    28	<!-- PLAN_ROUTE_CHECK_END -->
    29	
    30	---
    31	
    32	## Phase 0 — Setup
    33	
    34	1. **Discover plan slug:**
    35	   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
    36	   - If single candidate -> use it.
    37	   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
    38	   - If zero -> write a route decision recommending `/z-plan`, emit `plan_route_decision`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
    39	2. **Export variables:**
    40	   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
    41	3. **Pick run ID:**
    42	   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
    43	4. **Create directories:**
    44	   `mkdir -p $BASE/archive/$RUN/transcripts`
    45	5. **Version stamp + log run start:**
    46	   Capture the z-harness plugin version stamp and log the run start:
    47	   ```bash
    48	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    49	   START_PAYLOAD="$(python3 -c '
    50	   import json, sys
    51	   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
    52	   print(json.dumps(v))
    53	   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
    54	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
    55	   ```
    56	6. **Notification policy:**
    57	   Read `Z_HARNESS_NOTIFY` (default `approval_only`).
    58	7. **Docs Grounding:**
    59	   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
    60	   ```
    61	   Agent(
    62	     subagent_type="doc-fetcher",
    63	     description="Doc context for plan audit <slug>",
    64	     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
    65	   )
    66	   ```
    67	   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.
    68	
    69	---
    70	
    71	## Phase 1 — Reality Check (Reference Verification)
    72	
    73	Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:
    74	
    75	1. **Entities to verify:**
    76	   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
    77	   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
    78	   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
    79	   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
    80	   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
    81	2. **Bucket division:**
    82	   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
    83	   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
    84	3. **Drift & Hallucination detection:**
    85	   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
    86	   - Flag contract mismatches between proposed specifications and current codebase structures.
    87	   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).
    88	
    89	Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.
    90	
     1	---
     2	name: z-audit-plan
     3	description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
     4	---
     5	
     6	You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
     7	
     8	This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.
     9	
    10	<!-- PLAN_ROUTE_CHECK_START -->
    11	## Plan Route Check
    12	
    13	Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
    14	
    15	Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.
    16	
    17	Deterministic routes:
    18	- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
    19	- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
    20	- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
    21	- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.
    22	
    23	Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
    24	
    25	If routing, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
    26	
    27	Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
    28	<!-- PLAN_ROUTE_CHECK_END -->
    29	
    30	---
    31	
    32	## Phase 0 — Setup
    33	
    34	1. **Discover plan slug:**
    35	   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
    36	   - If single candidate -> use it.
    37	   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
    38	   - If zero -> write a route decision recommending `/z-plan`, emit `plan_route_decision`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
    39	2. **Export variables:**
    40	   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
    41	3. **Pick run ID:**
    42	   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
    43	4. **Create directories:**
    44	   `mkdir -p $BASE/archive/$RUN/transcripts`
    45	5. **Version stamp + log run start:**
    46	   Capture the z-harness plugin version stamp and log the run start:
    47	   ```bash
    48	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    49	   START_PAYLOAD="$(python3 -c '
    50	   import json, sys
    51	   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
    52	   print(json.dumps(v))
    53	   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
    54	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
    55	   ```
    56	6. **Notification policy:**
    57	   Read `Z_HARNESS_NOTIFY` (default `approval_only`).
    58	7. **Docs Grounding:**
    59	   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
    60	   ```
    61	   Agent(
    62	     subagent_type="doc-fetcher",
    63	     description="Doc context for plan audit <slug>",
    64	     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
    65	   )
    66	   ```
    67	   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.
    68	
    69	---
    70	
    71	## Phase 1 — Reality Check (Reference Verification)
    72	
    73	Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:
    74	
    75	1. **Entities to verify:**
    76	   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
    77	   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
    78	   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
    79	   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
    80	   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
    81	2. **Bucket division:**
    82	   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
    83	   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
    84	3. **Drift & Hallucination detection:**
    85	   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
    86	   - Flag contract mismatches between proposed specifications and current codebase structures.
    87	   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).
    88	
    89	Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.
    90	

codex
- **major** — `git status` shows acceptance-critical source/export files still untracked, including `agents/planning-router.md`, `commands/z-audit-plan.md`, `skills/z-audit-plan/`, `exports/cursor/.cursor/rules/planning-router.mdc`, `exports/agy/.agent/rules/z-harness-planning-router.md`, and `exports/*/z-audit-plan*`; if this diff is submitted as-is, the new router and `/z-audit-plan` exports are missing from version control. Add the untracked canonical and generated files, or make the task explicitly include only tracked output.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:138) routes “too few clusters” only when `cluster_seams == 1`, but the invariant is fewer than 2 clusters, so `cluster_seams: 0` can fall through to generic file-count routing. Change the rule to `cluster_seams < 2` and regenerate all exports.

- **major** — [commands/z-audit-plan.md](/Users/zeke/dev/z-harness/commands/z-audit-plan.md:38) tells the command to write a route decision and emit telemetry when zero plan artifacts exist, but `$BASE` and `$RUN` are not defined until later setup steps. Define a no-plan archive location and run id before artifact discovery, or move run initialization ahead of the zero-artifact route gate, then mirror it in the skill and exports.

- **major** — `exports/agy`, `exports/codex`, and `exports/cursor` contain broad generated churn outside the T006 surfaces, including consultant timeout/liveness changes, review-promotion changes, `/z-implement-all --tasks`, `external-lookup`, `/z-audit`, and `/z-mr-review`. Either split those unrelated canonical changes out of this task or document why they are expected source-of-truth changes before accepting the regenerated exports.
tokens used
126,006
- **major** — `git status` shows acceptance-critical source/export files still untracked, including `agents/planning-router.md`, `commands/z-audit-plan.md`, `skills/z-audit-plan/`, `exports/cursor/.cursor/rules/planning-router.mdc`, `exports/agy/.agent/rules/z-harness-planning-router.md`, and `exports/*/z-audit-plan*`; if this diff is submitted as-is, the new router and `/z-audit-plan` exports are missing from version control. Add the untracked canonical and generated files, or make the task explicitly include only tracked output.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:138) routes “too few clusters” only when `cluster_seams == 1`, but the invariant is fewer than 2 clusters, so `cluster_seams: 0` can fall through to generic file-count routing. Change the rule to `cluster_seams < 2` and regenerate all exports.

- **major** — [commands/z-audit-plan.md](/Users/zeke/dev/z-harness/commands/z-audit-plan.md:38) tells the command to write a route decision and emit telemetry when zero plan artifacts exist, but `$BASE` and `$RUN` are not defined until later setup steps. Define a no-plan archive location and run id before artifact discovery, or move run initialization ahead of the zero-artifact route gate, then mirror it in the skill and exports.

- **major** — `exports/agy`, `exports/codex`, and `exports/cursor` contain broad generated churn outside the T006 surfaces, including consultant timeout/liveness changes, review-promotion changes, `/z-implement-all --tasks`, `external-lookup`, `/z-audit`, and `/z-mr-review`. Either split those unrelated canonical changes out of this task or document why they are expected source-of-truth changes before accepting the regenerated exports.
