2026-05-25T00:37:17.779138Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-25T00:37:17.779828Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-25T00:37:17.779839Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5c90-8d18-7403-b8ad-94323edb12a0
--------
user
You are reviewing code that Claude just wrote for task T006: Regenerate multi-IDE exports.

This is REVIEW ROUND v2. Focus on whether the prior findings were addressed; do not re-review unrelated generated churn except for blockers/majors tied to acceptance.

Prior findings:
1. Acceptance-critical source/export files were untracked and missing from the review patch.
2. `agents/planning-router.md` used `cluster_seams == 1` instead of `< 2` for too-few clusters.
3. `commands/z-audit-plan.md` zero-artifact route gate used `$BASE`/`$RUN` before definition; command, skill, and exports need no-plan archive/run initialization before discovery.
4. Generated exports include broad existing branch churn; ensure it is expected generated output from source changes, not hand-edited drift.

Implementer claim:
- `planning-router` now treats `cluster_seams < 2` as too few.
- `/z-audit-plan` command/skill define `$NO_PLAN_RUN` / `$NO_PLAN_ARCHIVE_DIR` before artifact discovery.
- Export scripts all succeeded and validations passed.
- Review patch now includes untracked files as additions.

SPEC relevant excerpt:
51|### Route Artifact
52|
53|Each route artifact is Markdown and lives at one of:
54|
55|- `$CURRENT_ARCHIVE_DIR/route-decision.md`, where `$CURRENT_ARCHIVE_DIR` is the archive directory the command already created for this run.
56|- For plan-backed commands: `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`.
57|- For `/z-do`: `z-harness/adhoc/archive/$RUN/route-decision.md`.
58|- For `/z-audit-plan`: `$BASE/archive/$RUN/route-decision.md`, where `$BASE=$Z_HARNESS_PLAN_DIR`.
59|
60|Commands should define `$CURRENT_ARCHIVE_DIR` in setup immediately after creating the run archive and use it in route instructions.
165|## Route Thresholds
166|
167|Default route recommendations:
168|
169|| Signal pattern | Target | Notes |
170||---|---|---|
171|| Implementation task, `candidate_files <= 3`, no non-obvious decisions, no cross-module impact | `/z-do` | Tiny direct execution with review gate. |
172|| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
173|| Coherent medium feature/change, `expected_tasks <= 25`, no obvious cluster split | `/z-plan` | Produces `SPEC.md`, `PLAN.md`, `TASKS.md`. |
174|| Very large topic, `expected_tasks > 25` or `cluster_seams` in `2..6` and each seam is independently plannable | `/z-plan-split` | Produces a plan tree. |
175|| Unknown terrain, missing citations, or source facts must be mapped before deciding approach | `/z-research` | Produces `RESEARCH.md`; no recommendations. |
176|| Multiple plausible approach framings and terrain is sufficiently known | `/z-brainstorm` | Produces `BRAINSTORM.md`. |
177|| Existing `SPEC.md`/`PLAN.md`/`TASKS.md` need validation before implementation | `/z-audit-plan` | Contextual only. |
178|| Existing plan needs changed scope or decisions | `/z-amend` | Contextual only. |
179|| Concrete bug diagnosis exists | `/z-fix` | Contextual only. |
180|| Bug symptom exists but diagnosis is unknown | `/z-debug` | Contextual only. |
181|| Docs are stale above threshold or drift materially affects planning | `/z-maintain-docs` | Contextual only. |
233|## `planning-router` Agent
234|
235|Add `agents/planning-router.md`.
236|
237|Frontmatter:
238|
239|```yaml
240|---
241|name: planning-router
242|description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
243|tools: Read, Grep, Glob
244|model: haiku
245|---
246|```
247|
248|Inputs:
249|
250|- `current_command`
251|- `task_or_topic`
252|- `signals_json`
253|- `route_chain_json`
254|- `repo_root`
255|- optional `existing_artifacts`
256|
257|Return shape:
258|
259|```text
260|STATUS: routed | ask_user | bad_input
261|RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
262|ROUTE_CLASS: primary | contextual | none
263|CONFIDENCE: high | medium | low
264|REASON_CODES: <comma-separated stable reason codes>
265|REASON: <one line, <=160 chars>
266|```
267|
268|`STATUS: routed` requires `RECOMMENDED` to be a concrete command and `ROUTE_CLASS` to be `primary` or `contextual`. `STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe; it must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`. `STATUS: bad_input` is only for malformed or missing required inputs; it must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.
269|
270|Rules:
271|
272|- Do not edit files.
273|- Do not call other agents.
274|- Do not run expensive repo sweeps.
275|- Prefer deterministic thresholds supplied by the caller over inventing facts.
276|- If the input is malformed, return `STATUS: bad_input`; do not invent a command recommendation.
277|- If loop risk is present, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
278|- If the caller provides `route_chain_json`, inspect it before recommending a target.
279|- If the return is malformed, the caller ignores it and falls back to deterministic route or AskUser choice.
280|
281|## Command and Skill Source Changes
282|
283|Add a compact `## Plan Route Check` section to the following source files:
284|
285|- `commands/z-do.md`
286|- `commands/z-plan-light.md`
287|- `commands/z-plan.md`
288|- `commands/z-plan-split.md`
289|- `commands/z-brainstorm.md`
290|- `commands/z-research.md`
291|- `commands/z-audit-plan.md`
292|- `skills/z-do/SKILL.md`
293|- `skills/z-plan-light/SKILL.md`
294|- `skills/z-plan/SKILL.md`
295|- `skills/z-plan-split/SKILL.md`
296|- `skills/z-brainstorm/SKILL.md`
297|- `skills/z-research/SKILL.md`
298|- `skills/z-audit-plan/SKILL.md`
299|
300|The embedded block must be bracketed with HTML comments:
301|
302|```markdown
303|<!-- PLAN_ROUTE_CHECK_START -->
304|...
305|<!-- PLAN_ROUTE_CHECK_END -->
306|```
307|
308|The block must:
309|
310|- State primary route targets and contextual exits.
311|- List deterministic signals relevant to that command.
312|- State when to call `planning-router`.
313|- State the AskUser handoff gate.
314|- State loop prevention.
315|- State telemetry and route artifact requirements.
316|
317|Command-specific requirements:
318|
319|- `/z-do`: preserve hard caps. Add downward/upward clarity: if task is no-code research or approach selection, route to `/z-research` or `/z-brainstorm`; if larger than `/z-do`, route to `/z-plan-light` or `/z-plan`.
320|- `/z-plan-light`: preserve current thresholds but allow routing down to `/z-do` before writing `FIX.md`, up to `/z-plan`, sideways to `/z-research` or `/z-brainstorm`, and contextual to `/z-fix` or `/z-debug` for bug workflows.
321|- `/z-plan`: add early route check after setup/precontext detection and before Phase 1. It may route down to `/z-plan-light`, up to `/z-plan-split`, sideways to `/z-research` or `/z-brainstorm`, or contextual to `/z-audit-plan` only after artifacts exist.
322|- `/z-plan-split`: preserve 2-6 cluster invariant. Route too-few clusters to `/z-plan`; route too-many clusters to topic narrowing or `/z-research`; route unknown seams to `/z-research`.
323|- `/z-brainstorm`: before ideator dispatch, route to `/z-research` if terrain is unknown, to `/z-plan` if framing is already clear, or to `/z-plan-light` for a small concrete fix.
324|- `/z-research`: preserve no-recommendation invariant inside `RESEARCH.md`. Route only before research starts or after finalization as a next-step recommendation; do not recommend an approach inside the research note.
325|- `/z-audit-plan`: route to `/z-plan` when no plan artifacts exist, to `/z-amend` for accepted plan changes, and to `/z-maintain-docs` for doc drift that blocks audit confidence. It is read-only.
326|
348|## Export Changes
349|
350|After canonical files are updated, regenerate exports with the existing export pipeline:
351|
352|```bash
353|python3 scripts/export-cursor.py
354|python3 scripts/export-codex.py
355|python3 scripts/export-agy.py
356|```
357|
358|Acceptance:
359|
360|- Exported Cursor, Codex, and Antigravity prompts/rules include the route check sections and `planning-router` agent.
361|- No generated export file is hand-edited as the source of truth.
362|- Export churn is expected in generated files for touched commands, skills, and the new agent. Unexpected export changes outside those surfaces should be reviewed before acceptance.
363|
364|## Invariants
365|
366|- No automatic cross-command execution in v1.
367|- Commands remain standalone after export.
368|- Existing hard safety gates stay stricter than route recommendations.
369|- `/z-research` never recommends an implementation approach inside `RESEARCH.md`.
370|- `/z-audit-plan` remains read-only.
371|- `planning-router` is advisory; the orchestrator owns the final call.
372|- Existing telemetry is preserved.
382|## Scenario Acceptance
383|
384|Implementation must document or manually verify these scenarios:
385|
386|- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
387|- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
388|- `/z-do` with cross-module or schema impact recommends `/z-plan`.
389|- Unknown bug symptom recommends `/z-debug`; diagnosed bug recommends `/z-fix`.
390|- Unknown terrain before approach selection recommends `/z-research`.
391|- Multiple plausible framings with enough terrain recommends `/z-brainstorm`.
392|- Existing plan change recommends `/z-amend`.
393|- Existing complete plan can recommend `/z-audit-plan`; fresh intent without plan artifacts must not.
394|- `/z-plan-split` with one seam recommends `/z-plan`.
395|- Immediate ping-pong route is blocked and surfaced to the user.

Acceptance criteria:
102|## T006 - Regenerate multi-IDE exports
103|
104|**Status:** [~]
105|**Files:**
106|- `exports/cursor/.cursor/rules/*.mdc`
107|- `exports/codex/prompts/*.md`
108|- `exports/agy/prompts/*.md`
109|- `exports/agy/.agent/rules/*.md`
110|- `exports/agy/.agent/skills/*/SKILL.md`
111|- `exports/agy/.agent/workflows/*.md`
112|- `exports/agy/agy-plugin.yaml`
113|**Depends:** T002, T003, T004, T005
114|**Acceptance:**
115|- [ ] `python3 scripts/export-cursor.py` succeeds.
116|- [ ] `python3 scripts/export-codex.py` succeeds.
117|- [ ] `python3 scripts/export-agy.py` succeeds.
118|- [ ] Generated exports include route checks for all touched commands/skills.
119|- [ ] Generated exports include the `planning-router` agent where target format supports agents/rules.
120|**DOCS:** multi-ide-exports
121|**Complexity:** high

Relevant docs (must respect invariants):
{
  "slug": "multi-ide-exports",
  "summary": "Pipeline for exporting z-harness source files (commands/, agents/, skills/) to IDE-specific formats for Cursor (.mdc rules), Codex CLI (AGENTS.md + prompt files), and Antigravity/agy (agy-plugin.yaml + prompt files). All targets share scripts/export-common.py for enumeration and filter logic. Invoked via /z-export or per-target Python scripts directly.",
  "key_invariants": [
    "Export adapters MUST NOT include providers.json, .z-harness/, z-harness/plans/, z-harness/archive/, or anything under ~/. This filter is enforced by scripts/audit-tarball.sh.",
    "Claude Code constructs that cannot be represented in target IDEs (Agent(), Skill(), AskUserQuestion()) are replaced with inline comments — never silently dropped.",
    "Each target directory contains a CAPABILITIES.md that documents every dropped or replaced construct.",
    "Export scripts never write files outside their own exports/<target>/ directory."
  ],
  "key_files": [
    { "path": "scripts/export-common.py", "why": "Shared library for source-file enumeration, schema validation, and export filter logic." },
    { "path": "scripts/export-cursor.py", "why": "Produces .cursor/rules/*.mdc files from command/agent/skill sources." },
    { "path": "scripts/export-codex.py", "why": "Produces AGENTS.md and prompts/*.md for Codex CLI." },
    { "path": "scripts/export-agy.py", "why": "Produces agy-plugin.yaml and prompts/*.md for Antigravity." },
    { "path": "scripts/audit-tarball.sh", "why": "CI lint gate: rejects any export tarball containing excluded paths." },
    { "path": "commands/z-export.md", "why": "Slash command wrapping export scripts; --target flag selects cursor|codex|agy|all." },
    { "path": "exports/cursor/CAPABILITIES.md", "why": "Documents what was translated and what was dropped for the Cursor target." },
    { "path": "exports/codex/CAPABILITIES.md", "why": "Documents what was translated and what was dropped for the Codex CLI target." },
    { "path": "exports/agy/CAPABILITIES.md", "why": "Documents what was translated and what was dropped for the agy target." },
    { "path": "docs/human/MULTI-IDE.md", "why": "User-facing guide: per-target install instructions, CAPABILITIES caveats, export filter rules." }
  ],
  "related_concepts": ["commands", "agents", "providers-registry"],
  "last_updated": "2026-05-24"
}


Diff excerpts (primary artifact, narrowed to prior findings and acceptance-critical additions):

=== delta-v2 focused excerpts ===
--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 211-239 ---
211|-@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
212|- 
213|- If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
214|- 
215|-+<!-- PLAN_ROUTE_CHECK_START -->
216|-+## Plan Route Check
217|-+
218|-+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
219|-+
220|-+Deterministic routes:
221|-+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
222|-+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
223|-+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
224|-+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
225|-+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
226|-+
227|-+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
228|-+
229|-+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
230|-+
231|-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
232|-+<!-- PLAN_ROUTE_CHECK_END -->
233|-+
234|- ### 1c. Write proposal artifact
235|- 
236|- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
237|-diff --git a/exports/agy/.agent/skills/z-plan/SKILL.md b/exports/agy/.agent/skills/z-plan/SKILL.md
238|-index 72dd206..5884f6e 100644
239|---- a/exports/agy/.agent/skills/z-plan/SKILL.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 712-740 ---
712|-@@ -142,6 +142,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
713|- 
714|- If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
715|- 
716|-+<!-- PLAN_ROUTE_CHECK_START -->
717|-+## Plan Route Check
718|-+
719|-+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
720|-+
721|-+Deterministic routes:
722|-+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
723|-+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
724|-+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
725|-+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
726|-+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
727|-+
728|-+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
729|-+
730|-+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
731|-+
732|-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
733|-+<!-- PLAN_ROUTE_CHECK_END -->
734|-+
735|- ### 1c. Write proposal artifact
736|- 
737|- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
738|-diff --git a/exports/agy/.agent/workflows/z-plan.md b/exports/agy/.agent/workflows/z-plan.md
739|-index aabfa12..b42bdfc 100644
740|---- a/exports/agy/.agent/workflows/z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 955-983 ---
955|- - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
956|-diff --git a/exports/agy/agy-plugin.yaml b/exports/agy/agy-plugin.yaml
957|-index e84cd4e..c505c6b 100644
958|---- a/exports/agy/agy-plugin.yaml
959|-+++ b/exports/agy/agy-plugin.yaml
960|-@@ -15,6 +15,10 @@ workflows:
961|-     source: commands/z-amend.md
962|-     output: .agent/workflows/z-amend.md
963|-     description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
964|-+  - id: z-audit-plan
965|-+    source: commands/z-audit-plan.md
966|-+    output: .agent/workflows/z-audit-plan.md
967|-+    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
968|-   - id: z-audit
969|-     source: commands/z-audit.md
970|-     output: .agent/workflows/z-audit.md
971|-@@ -66,7 +70,7 @@ workflows:
972|-   - id: z-plan-light
973|-     source: commands/z-plan-light.md
974|-     output: .agent/workflows/z-plan-light.md
975|--    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i..."
976|-+    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
977|-   - id: z-plan-split
978|-     source: commands/z-plan-split.md
979|-     output: .agent/workflows/z-plan-split.md
980|-@@ -150,6 +154,11 @@ rules:
981|-     output: .agent/rules/z-harness-doc-updater.md
982|-     trigger: model_decision
983|-     description: "Sonnet subagent invoked by /z-maintain-docs to refresh ONE doc concept (one human-tier markdown + one llm-tier JSON entry) so they reflect current code. Returns the proposed updates as text (dry-run by default); does NOT write to disk unless expli..."

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 987-1028 ---
987|-+    trigger: model_decision
988|-+    description: "Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blo..."
989|-   - id: implementer
990|-     source: agents/implementer.md
991|-     output: .agent/rules/z-harness-implementer.md
992|-@@ -160,6 +169,11 @@ rules:
993|-     output: .agent/rules/z-harness-mr-reviewer.md
994|-     trigger: always_on
995|-     description: "Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to reviewer)."
996|-+  - id: planning-router
997|-+    source: agents/planning-router.md
998|-+    output: .agent/rules/z-harness-planning-router.md
999|-+    trigger: model_decision
1000|-+    description: "Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only."
1001|-   - id: remote-runner
1002|-     source: agents/remote-runner.md
1003|-     output: .agent/rules/z-harness-remote-runner.md
1004|-@@ -183,6 +197,10 @@ skills:
1005|-     source: skills/z-amend/SKILL.md
1006|-     output: .agent/skills/z-amend/SKILL.md
1007|-     description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
1008|-+  - id: z-audit-plan
1009|-+    source: skills/z-audit-plan/SKILL.md
1010|-+    output: .agent/skills/z-audit-plan/SKILL.md
1011|-+    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
1012|-   - id: z-brainstorm
1013|-     source: skills/z-brainstorm/SKILL.md
1014|-     output: .agent/skills/z-brainstorm/SKILL.md
1015|-@@ -222,7 +240,7 @@ skills:
1016|-   - id: z-plan-light
1017|-     source: skills/z-plan-light/SKILL.md
1018|-     output: .agent/skills/z-plan-light/SKILL.md
1019|--    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i..."
1020|-+    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
1021|-   - id: z-plan-split
1022|-     source: skills/z-plan-split/SKILL.md
1023|-     output: .agent/skills/z-plan-split/SKILL.md
1024|-diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
1025|-index 748cd79..5d8ce6a 100644
1026|---- a/exports/agy/prompts/consultant-primary.md
1027|-+++ b/exports/agy/prompts/consultant-primary.md
1028|-@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 1470-1498 ---
1470|-@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
1471|- 
1472|- If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
1473|- 
1474|-+<!-- PLAN_ROUTE_CHECK_START -->
1475|-+## Plan Route Check
1476|-+
1477|-+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
1478|-+
1479|-+Deterministic routes:
1480|-+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
1481|-+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
1482|-+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
1483|-+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
1484|-+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
1485|-+
1486|-+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
1487|-+
1488|-+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
1489|-+
1490|-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
1491|-+<!-- PLAN_ROUTE_CHECK_END -->
1492|-+
1493|- ### 1c. Write proposal artifact
1494|- 
1495|- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
1496|-diff --git a/exports/agy/prompts/skill-z-plan.md b/exports/agy/prompts/skill-z-plan.md
1497|-index 2030ba7..e54c03a 100644
1498|---- a/exports/agy/prompts/skill-z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 1971-1999 ---
1971|-@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
1972|- 
1973|- If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
1974|- 
1975|-+<!-- PLAN_ROUTE_CHECK_START -->
1976|-+## Plan Route Check
1977|-+
1978|-+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
1979|-+
1980|-+Deterministic routes:
1981|-+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
1982|-+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
1983|-+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
1984|-+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
1985|-+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
1986|-+
1987|-+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
1988|-+
1989|-+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
1990|-+
1991|-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
1992|-+<!-- PLAN_ROUTE_CHECK_END -->
1993|-+
1994|- ### 1c. Write proposal artifact
1995|- 
1996|- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
1997|-diff --git a/exports/agy/prompts/z-plan.md b/exports/agy/prompts/z-plan.md
1998|-index 551c4b8..8f1a68b 100644
1999|---- a/exports/agy/prompts/z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 2572-2600 ---
2572|-+4. Prefer contextual exits when their preconditions are explicit:
2573|-+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
2574|-+   - `has_existing_plan` plus requested plan modification -> `/z-amend`
2575|-+   - `has_bug_diagnosis` -> `/z-fix`
2576|-+   - `has_unknown_bug_symptom` -> `/z-debug`
2577|-+   - `docs_stale_or_drifted` -> `/z-maintain-docs`
2578|-+5. If `terrain_uncertain` is true, recommend `/z-research`.
2579|-+6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
2580|-+7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
2581|-+   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
2582|-+   - If `cluster_seams == 1`, recommend `/z-plan` with `too_few_clusters`.
2583|-+   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
2584|-+   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
2585|-+8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
2586|-+9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
2587|-+10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
2588|-+11. Otherwise recommend `/z-plan`.
2589|-+
2590|-+If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
2591|-+
2592|-+## Confidence Guidance
2593|-+
2594|-+- `high`: supplied signals point clearly to one target and required preconditions are explicit.
2595|-+- `medium`: one target is likely but some quantitative signals are `null` or weak.
2596|-+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
2597|-+
2598|-+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
2599|-+
2600|-+---

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 2999-3027 ---
2999|-@@ -140,6 +140,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
3000|- 
3001|- If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
3002|- 
3003|-+<!-- PLAN_ROUTE_CHECK_START -->
3004|-+## Plan Route Check
3005|-+
3006|-+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
3007|-+
3008|-+Deterministic routes:
3009|-+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
3010|-+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
3011|-+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
3012|-+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
3013|-+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
3014|-+
3015|-+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
3016|-+
3017|-+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
3018|-+
3019|-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
3020|-+<!-- PLAN_ROUTE_CHECK_END -->
3021|-+
3022|- ### 1c. Write proposal artifact
3023|- 
3024|- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
3025|-diff --git a/exports/codex/prompts/z-plan.md b/exports/codex/prompts/z-plan.md
3026|-index 2fe5cf4..78a89aa 100644
3027|---- a/exports/codex/prompts/z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 3706-3734 ---
3706|-@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
3707|- 
3708|- If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
3709|- 
3710|-+<!-- PLAN_ROUTE_CHECK_START -->
3711|-+## Plan Route Check
3712|-+
3713|-+Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
3714|-+
3715|-+Deterministic routes:
3716|-+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
3717|-+- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
3718|-+- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
3719|-+- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
3720|-+- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
3721|-+
3722|-+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
3723|-+
3724|-+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
3725|-+
3726|-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
3727|-+<!-- PLAN_ROUTE_CHECK_END -->
3728|-+
3729|- ### 1c. Write proposal artifact
3730|- 
3731|- Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
3732|-diff --git a/exports/cursor/.cursor/rules/z-plan.mdc b/exports/cursor/.cursor/rules/z-plan.mdc
3733|-index 1a8c911..c3bcbe2 100644
3734|---- a/exports/cursor/.cursor/rules/z-plan.mdc

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 4132-4160 ---
4132|+@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
4133|+ 
4134|+ If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
4135|+ 
4136|++<!-- PLAN_ROUTE_CHECK_START -->
4137|++## Plan Route Check
4138|++
4139|++Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
4140|++
4141|++Deterministic routes:
4142|++- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
4143|++- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
4144|++- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
4145|++- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
4146|++- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
4147|++
4148|++Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
4149|++
4150|++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
4151|++
4152|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
4153|++<!-- PLAN_ROUTE_CHECK_END -->
4154|++
4155|+ ### 1c. Write proposal artifact
4156|+ 
4157|+ Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
4158|+diff --git a/exports/agy/.agent/skills/z-plan/SKILL.md b/exports/agy/.agent/skills/z-plan/SKILL.md
4159|+index 72dd206..5884f6e 100644
4160|+--- a/exports/agy/.agent/skills/z-plan/SKILL.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 4642-4670 ---
4642|+@@ -142,6 +142,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
4643|+ 
4644|+ If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
4645|+ 
4646|++<!-- PLAN_ROUTE_CHECK_START -->
4647|++## Plan Route Check
4648|++
4649|++Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
4650|++
4651|++Deterministic routes:
4652|++- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
4653|++- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
4654|++- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
4655|++- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
4656|++- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
4657|++
4658|++Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
4659|++
4660|++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
4661|++
4662|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
4663|++<!-- PLAN_ROUTE_CHECK_END -->
4664|++
4665|+ ### 1c. Write proposal artifact
4666|+ 
4667|+ Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
4668|+diff --git a/exports/agy/.agent/workflows/z-plan.md b/exports/agy/.agent/workflows/z-plan.md
4669|+index aabfa12..b42bdfc 100644
4670|+--- a/exports/agy/.agent/workflows/z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 4885-4913 ---
4885|+ - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
4886|+diff --git a/exports/agy/agy-plugin.yaml b/exports/agy/agy-plugin.yaml
4887|+index e84cd4e..c505c6b 100644
4888|+--- a/exports/agy/agy-plugin.yaml
4889|++++ b/exports/agy/agy-plugin.yaml
4890|+@@ -15,6 +15,10 @@ workflows:
4891|+     source: commands/z-amend.md
4892|+     output: .agent/workflows/z-amend.md
4893|+     description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
4894|++  - id: z-audit-plan
4895|++    source: commands/z-audit-plan.md
4896|++    output: .agent/workflows/z-audit-plan.md
4897|++    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
4898|+   - id: z-audit
4899|+     source: commands/z-audit.md
4900|+     output: .agent/workflows/z-audit.md
4901|+@@ -66,7 +70,7 @@ workflows:
4902|+   - id: z-plan-light
4903|+     source: commands/z-plan-light.md
4904|+     output: .agent/workflows/z-plan-light.md
4905|+-    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i..."
4906|++    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
4907|+   - id: z-plan-split
4908|+     source: commands/z-plan-split.md
4909|+     output: .agent/workflows/z-plan-split.md
4910|+@@ -150,6 +154,11 @@ rules:
4911|+     output: .agent/rules/z-harness-doc-updater.md
4912|+     trigger: model_decision
4913|+     description: "Sonnet subagent invoked by /z-maintain-docs to refresh ONE doc concept (one human-tier markdown + one llm-tier JSON entry) so they reflect current code. Returns the proposed updates as text (dry-run by default); does NOT write to disk unless expli..."

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 4917-4958 ---
4917|++    trigger: model_decision
4918|++    description: "Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blo..."
4919|+   - id: implementer
4920|+     source: agents/implementer.md
4921|+     output: .agent/rules/z-harness-implementer.md
4922|+@@ -160,6 +169,11 @@ rules:
4923|+     output: .agent/rules/z-harness-mr-reviewer.md
4924|+     trigger: always_on
4925|+     description: "Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to reviewer)."
4926|++  - id: planning-router
4927|++    source: agents/planning-router.md
4928|++    output: .agent/rules/z-harness-planning-router.md
4929|++    trigger: model_decision
4930|++    description: "Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only."
4931|+   - id: remote-runner
4932|+     source: agents/remote-runner.md
4933|+     output: .agent/rules/z-harness-remote-runner.md
4934|+@@ -183,6 +197,10 @@ skills:
4935|+     source: skills/z-amend/SKILL.md
4936|+     output: .agent/skills/z-amend/SKILL.md
4937|+     description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
4938|++  - id: z-audit-plan
4939|++    source: skills/z-audit-plan/SKILL.md
4940|++    output: .agent/skills/z-audit-plan/SKILL.md
4941|++    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
4942|+   - id: z-brainstorm
4943|+     source: skills/z-brainstorm/SKILL.md
4944|+     output: .agent/skills/z-brainstorm/SKILL.md
4945|+@@ -222,7 +240,7 @@ skills:
4946|+   - id: z-plan-light
4947|+     source: skills/z-plan-light/SKILL.md
4948|+     output: .agent/skills/z-plan-light/SKILL.md
4949|+-    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan i..."
4950|++    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
4951|+   - id: z-plan-split
4952|+     source: skills/z-plan-split/SKILL.md
4953|+     output: .agent/skills/z-plan-split/SKILL.md
4954|+diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
4955|+index 748cd79..5d8ce6a 100644
4956|+--- a/exports/agy/prompts/consultant-primary.md
4957|++++ b/exports/agy/prompts/consultant-primary.md
4958|+@@ -23,11 +23,21 @@ USE_STDIN="$(printf '%s' "$DESCRIPTOR" | python3 -c 'import json,sys; d=json.loa

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 5409-5437 ---
5409|+@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
5410|+ 
5411|+ If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
5412|+ 
5413|++<!-- PLAN_ROUTE_CHECK_START -->
5414|++## Plan Route Check
5415|++
5416|++Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
5417|++
5418|++Deterministic routes:
5419|++- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
5420|++- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
5421|++- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
5422|++- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
5423|++- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
5424|++
5425|++Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
5426|++
5427|++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
5428|++
5429|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
5430|++<!-- PLAN_ROUTE_CHECK_END -->
5431|++
5432|+ ### 1c. Write proposal artifact
5433|+ 
5434|+ Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
5435|+diff --git a/exports/agy/prompts/skill-z-plan.md b/exports/agy/prompts/skill-z-plan.md
5436|+index 2030ba7..e54c03a 100644
5437|+--- a/exports/agy/prompts/skill-z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 5919-5947 ---
5919|+@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
5920|+ 
5921|+ If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
5922|+ 
5923|++<!-- PLAN_ROUTE_CHECK_START -->
5924|++## Plan Route Check
5925|++
5926|++Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
5927|++
5928|++Deterministic routes:
5929|++- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
5930|++- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
5931|++- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
5932|++- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
5933|++- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
5934|++
5935|++Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
5936|++
5937|++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
5938|++
5939|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
5940|++<!-- PLAN_ROUTE_CHECK_END -->
5941|++
5942|+ ### 1c. Write proposal artifact
5943|+ 
5944|+ Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
5945|+diff --git a/exports/agy/prompts/z-plan.md b/exports/agy/prompts/z-plan.md
5946|+index 551c4b8..8f1a68b 100644
5947|+--- a/exports/agy/prompts/z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 6520-6548 ---
6520|++4. Prefer contextual exits when their preconditions are explicit:
6521|++   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
6522|++   - `has_existing_plan` plus requested plan modification -> `/z-amend`
6523|++   - `has_bug_diagnosis` -> `/z-fix`
6524|++   - `has_unknown_bug_symptom` -> `/z-debug`
6525|++   - `docs_stale_or_drifted` -> `/z-maintain-docs`
6526|++5. If `terrain_uncertain` is true, recommend `/z-research`.
6527|++6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
6528|++7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
6529|++   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
6530|++   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
6531|++   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
6532|++   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
6533|++8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
6534|++9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
6535|++10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
6536|++11. Otherwise recommend `/z-plan`.
6537|++
6538|++If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
6539|++
6540|++## Confidence Guidance
6541|++
6542|++- `high`: supplied signals point clearly to one target and required preconditions are explicit.
6543|++- `medium`: one target is likely but some quantitative signals are `null` or weak.
6544|++- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
6545|++
6546|++The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
6547|++
6548|++---

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 6956-6984 ---
6956|+@@ -140,6 +140,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
6957|+ 
6958|+ If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
6959|+ 
6960|++<!-- PLAN_ROUTE_CHECK_START -->
6961|++## Plan Route Check
6962|++
6963|++Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
6964|++
6965|++Deterministic routes:
6966|++- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
6967|++- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
6968|++- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
6969|++- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
6970|++- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
6971|++
6972|++Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
6973|++
6974|++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
6975|++
6976|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
6977|++<!-- PLAN_ROUTE_CHECK_END -->
6978|++
6979|+ ### 1c. Write proposal artifact
6980|+ 
6981|+ Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
6982|+diff --git a/exports/codex/prompts/z-plan.md b/exports/codex/prompts/z-plan.md
6983|+index 2fe5cf4..78a89aa 100644
6984|+--- a/exports/codex/prompts/z-plan.md

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 7672-7700 ---
7672|+@@ -143,6 +143,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
7673|+ 
7674|+ If `--clusters="a,b,c"` was passed in Setup step 11, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 11). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.
7675|+ 
7676|++<!-- PLAN_ROUTE_CHECK_START -->
7677|++## Plan Route Check
7678|++
7679|++Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.
7680|++
7681|++Deterministic routes:
7682|++- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
7683|++- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
7684|++- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
7685|++- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
7686|++- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.
7687|++
7688|++Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
7689|++
7690|++If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
7691|++
7692|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
7693|++<!-- PLAN_ROUTE_CHECK_END -->
7694|++
7695|+ ### 1c. Write proposal artifact
7696|+ 
7697|+ Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:
7698|+diff --git a/exports/cursor/.cursor/rules/z-plan.mdc b/exports/cursor/.cursor/rules/z-plan.mdc
7699|+index 1a8c911..c3bcbe2 100644
7700|+--- a/exports/cursor/.cursor/rules/z-plan.mdc

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 7875-7907 ---
7875|+   /z-maintain-docs   — refresh docs/human/ and docs/llm/ for any concepts touched by this plan
7876|+@@ -196,7 +269,7 @@ The implementation is done and reviewed; the docs are what's left.
7877|+ 
7878|+ ## Hard rules
7879|+ 
7880|+-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
7881|++- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
7882|+ - **Never** run this on an incomplete plan without explicit user override.
7883|+ - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
7884|+ - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
7885|+diff --git a/agents/planning-router.md b/agents/planning-router.md
7886|+new file mode 100644
7887|+index 0000000..b6cc941
7888|+--- /dev/null
7889|++++ b/agents/planning-router.md
7890|+@@ -0,0 +1,154 @@
7891|++---
7892|++name: planning-router
7893|++description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
7894|++tools: Read, Grep, Glob
7895|++model: haiku
7896|++---
7897|++
7898|++## Mission
7899|++
7900|++You are a cheap, read-only ambiguity resolver for z-harness planning-family route decisions. The caller has already collected compact deterministic signals and needs an advisory recommendation only when hard thresholds did not settle the route.
7901|++
7902|++You do not edit files, do not call other agents, do not run shell commands, and do not perform broad repo exploration. Prefer the caller's supplied signals over inventing facts.
7903|++
7904|++## Inputs From Caller
7905|++
7906|++The caller prompt must provide:
7907|++

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 8018-8112 ---
8018|++4. Prefer contextual exits when their preconditions are explicit:
8019|++   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
8020|++   - `has_existing_plan` plus requested plan modification -> `/z-amend`
8021|++   - `has_bug_diagnosis` -> `/z-fix`
8022|++   - `has_unknown_bug_symptom` -> `/z-debug`
8023|++   - `docs_stale_or_drifted` -> `/z-maintain-docs`
8024|++5. If `terrain_uncertain` is true, recommend `/z-research`.
8025|++6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
8026|++7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
8027|++   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
8028|++   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
8029|++   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
8030|++   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
8031|++8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
8032|++9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
8033|++10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
8034|++11. Otherwise recommend `/z-plan`.
8035|++
8036|++If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
8037|++
8038|++## Confidence Guidance
8039|++
8040|++- `high`: supplied signals point clearly to one target and required preconditions are explicit.
8041|++- `medium`: one target is likely but some quantitative signals are `null` or weak.
8042|++- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
8043|++
8044|++The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
8045|+diff --git a/commands/z-audit-plan.md b/commands/z-audit-plan.md
8046|+new file mode 100644
8047|+index 0000000..67734b2
8048|+--- /dev/null
8049|++++ b/commands/z-audit-plan.md
8050|+@@ -0,0 +1,201 @@
8051|++---
8052|++description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
8053|++argument-hint: [--slug <slug>]
8054|++---
8055|++
8056|++You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
8057|++
8058|++This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.
8059|++
8060|++<!-- PLAN_ROUTE_CHECK_START -->
8061|++## Plan Route Check
8062|++
8063|++Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
8064|++
8065|++Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.
8066|++
8067|++Deterministic routes:
8068|++- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
8069|++- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
8070|++- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
8071|++- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.
8072|++
8073|++Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8074|++
8075|++If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
8076|++
8077|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
8078|++<!-- PLAN_ROUTE_CHECK_END -->
8079|++
8080|++---
8081|++
8082|++## Phase 0 — Setup
8083|++
8084|++0. **Initialize no-plan route archive:**
8085|++   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
8086|++   ```bash
8087|++   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
8088|++   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
8089|++   ```
8090|++1. **Discover plan slug:**
8091|++   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
8092|++   - If single candidate -> use it.
8093|++   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
8094|++   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
8095|++2. **Export variables:**
8096|++   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
8097|++3. **Pick run ID:**
8098|++   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
8099|++4. **Create directories:**
8100|++   `mkdir -p $BASE/archive/$RUN/transcripts`
8101|++5. **Version stamp + log run start:**
8102|++   Capture the z-harness plugin version stamp and log the run start:
8103|++   ```bash
8104|++   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
8105|++   START_PAYLOAD="$(python3 -c '
8106|++   import json, sys
8107|++   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
8108|++   print(json.dumps(v))
8109|++   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
8110|++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
8111|++   ```
8112|++6. **Notification policy:**

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 8397-8429 ---
8397|++- **Authenticated endpoints** requiring secrets the agent doesn't have → `STATUS: refused`, category `auth_missing`. Do not attempt env-var sniffing.
8398|++
8399|++## Invariants
8400|++
8401|++- First output line is exactly `STATUS: <token>` where token ∈ {`ok`, `partial`, `refused`}.
8402|++- Sections appear in fixed order: `## Answer`, `## Provenance`, `## Unresolved`, optional `## Raw artifact pointer`.
8403|++- No tool dispatch other than the whitelist (`WebFetch`, `WebSearch`, `Bash`, `Read`, `Grep`, `Glob`).
8404|++- Total response ≤3 KB.
8405|++- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
8406|++- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.
8407|+diff --git a/exports/agy/.agent/rules/z-harness-planning-router.md b/exports/agy/.agent/rules/z-harness-planning-router.md
8408|+new file mode 100644
8409|+index 0000000..556fbe3
8410|+--- /dev/null
8411|++++ b/exports/agy/.agent/rules/z-harness-planning-router.md
8412|+@@ -0,0 +1,152 @@
8413|++---
8414|++trigger: model_decision
8415|++description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
8416|++---
8417|++
8418|++## Mission
8419|++
8420|++You are a cheap, read-only ambiguity resolver for z-harness planning-family route decisions. The caller has already collected compact deterministic signals and needs an advisory recommendation only when hard thresholds did not settle the route.
8421|++
8422|++You do not edit files, do not call other agents, do not run shell commands, and do not perform broad repo exploration. Prefer the caller's supplied signals over inventing facts.
8423|++
8424|++## Inputs From Caller
8425|++
8426|++The caller prompt must provide:
8427|++
8428|++- `current_command`: the command currently running.
8429|++- `task_or_topic`: the user's task or topic, kept compact.

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 8538-8632 ---
8538|++4. Prefer contextual exits when their preconditions are explicit:
8539|++   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
8540|++   - `has_existing_plan` plus requested plan modification -> `/z-amend`
8541|++   - `has_bug_diagnosis` -> `/z-fix`
8542|++   - `has_unknown_bug_symptom` -> `/z-debug`
8543|++   - `docs_stale_or_drifted` -> `/z-maintain-docs`
8544|++5. If `terrain_uncertain` is true, recommend `/z-research`.
8545|++6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
8546|++7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
8547|++   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
8548|++   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
8549|++   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
8550|++   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
8551|++8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
8552|++9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
8553|++10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
8554|++11. Otherwise recommend `/z-plan`.
8555|++
8556|++If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
8557|++
8558|++## Confidence Guidance
8559|++
8560|++- `high`: supplied signals point clearly to one target and required preconditions are explicit.
8561|++- `medium`: one target is likely but some quantitative signals are `null` or weak.
8562|++- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
8563|++
8564|++The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
8565|+diff --git a/exports/agy/.agent/skills/z-audit-plan/SKILL.md b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
8566|+new file mode 100644
8567|+index 0000000..590bf27
8568|+--- /dev/null
8569|++++ b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
8570|+@@ -0,0 +1,201 @@
8571|++---
8572|++name: z-audit-plan
8573|++description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
8574|++---
8575|++
8576|++You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
8577|++
8578|++This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.
8579|++
8580|++<!-- PLAN_ROUTE_CHECK_START -->
8581|++## Plan Route Check
8582|++
8583|++Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
8584|++
8585|++Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.
8586|++
8587|++Deterministic routes:
8588|++- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
8589|++- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
8590|++- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
8591|++- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.
8592|++
8593|++Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8594|++
8595|++If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
8596|++
8597|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
8598|++<!-- PLAN_ROUTE_CHECK_END -->
8599|++
8600|++---
8601|++
8602|++## Phase 0 — Setup
8603|++
8604|++0. **Initialize no-plan route archive:**
8605|++   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
8606|++   ```bash
8607|++   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
8608|++   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
8609|++   ```
8610|++1. **Discover plan slug:**
8611|++   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
8612|++   - If single candidate -> use it.
8613|++   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
8614|++   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
8615|++2. **Export variables:**
8616|++   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
8617|++3. **Pick run ID:**
8618|++   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
8619|++4. **Create directories:**
8620|++   `mkdir -p $BASE/archive/$RUN/transcripts`
8621|++5. **Version stamp + log run start:**
8622|++   Capture the z-harness plugin version stamp and log the run start:
8623|++   ```bash
8624|++   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
8625|++   START_PAYLOAD="$(python3 -c '
8626|++   import json, sys
8627|++   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
8628|++   print(json.dumps(v))
8629|++   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
8630|++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
8631|++   ```
8632|++6. **Notification policy:**

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 8791-8838 ---
8791|++Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.
8792|++
8793|++Deterministic routes:
8794|++- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
8795|++- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
8796|++- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
8797|++- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.
8798|++
8799|++Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8800|++
8801|++If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
8802|++
8803|++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
8804|++<!-- PLAN_ROUTE_CHECK_END -->
8805|++
8806|++---
8807|++
8808|++## Phase 0 — Setup
8809|++
8810|++0. **Initialize no-plan route archive:**
8811|++   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
8812|++   ```bash
8813|++   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
8814|++   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
8815|++   ```
8816|++1. **Discover plan slug:**
8817|++   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
8818|++   - If single candidate -> use it.
8819|++   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
8820|++   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
8821|++2. **Export variables:**
8822|++   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
8823|++3. **Pick run ID:**
8824|++   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
8825|++4. **Create directories:**
8826|++   `mkdir -p $BASE/archive/$RUN/transcripts`
8827|++5. **Version stamp + log run start:**
8828|++   Capture the z-harness plugin version stamp and log the run start:
8829|++   ```bash
8830|++   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
8831|++   START_PAYLOAD="$(python3 -c '
8832|++   import json, sys
8833|++   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
8834|++   print(json.dumps(v))
8835|++   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
8836|++   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
8837|++   ```
8838|++6. **Notification policy:**

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch lines 9264-9292 ---
9264|++4. Prefer contextual exits when their preconditions are explicit:
9265|++   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
9266|++   - `has_existing_plan` plus requested plan modification -> `/z-amend`
9267|++   - `has_bug_diagnosis` -> `/z-fix`
9268|++   - `has_unknown_bug_symptom` -> `/z-debug`
9269|++   - `docs_stale_or_drifted` -> `/z-maintain-docs`
9270|++5. If `terrain_uncertain` is true, recommend `/z-research`.
9271|++6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
9272|++7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
9273|++   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
9274|++   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
9275|++   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
9276|++   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
9277|++8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
9278|++9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
9279|++10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
9280|++11. Otherwise recommend `/z-plan`.
9281|++
9282|++If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
9283|++
9284|++## Confidence Guidance
9285|++
9286|++- `high`: supplied signals point clearly to one target and required preconditions are explicit.
9287|++- `medium`: one target is likely but some quantitative signals are `null` or weak.
9288|++- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
9289|++
9290|++The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
9291|+diff --git a/exports/agy/prompts/skill-z-audit-plan.md b/exports/agy/prompts/skill-z-audit-plan.md
9292|+new file mode 100644

=== full current diff headers / added file evidence ===
--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 4208-4217 ---
4208| - **Never** trust a single LLM's finding without pushback — list "one reason this might be wrong" before treating a finding as actionable.
4209| - **Always** archive the cumulative diff and both consultant transcripts under `$BASE/archive/$RRUN/`.
4210|diff --git a/agents/planning-router.md b/agents/planning-router.md
4211|new file mode 100644
4212|index 0000000..b6cc941
4213|--- /dev/null
4214|+++ b/agents/planning-router.md
4215|@@ -0,0 +1,154 @@
4216|+---
4217|+name: planning-router

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 4368-4377 ---
4368|+
4369|+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
4370|diff --git a/commands/z-audit-plan.md b/commands/z-audit-plan.md
4371|new file mode 100644
4372|index 0000000..67734b2
4373|--- /dev/null
4374|+++ b/commands/z-audit-plan.md
4375|@@ -0,0 +1,201 @@
4376|+---
4377|+description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 4576-4584 ---
4576|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
4577|diff --git a/exports/agy/.agent/rules/z-harness-external-lookup.md b/exports/agy/.agent/rules/z-harness-external-lookup.md
4578|new file mode 100644
4579|index 0000000..42ae43d
4580|--- /dev/null
4581|+++ b/exports/agy/.agent/rules/z-harness-external-lookup.md
4582|@@ -0,0 +1,149 @@
4583|+---
4584|+trigger: model_decision

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 4730-4739 ---
4730|+- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
4731|+- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.
4732|diff --git a/exports/agy/.agent/rules/z-harness-planning-router.md b/exports/agy/.agent/rules/z-harness-planning-router.md
4733|new file mode 100644
4734|index 0000000..556fbe3
4735|--- /dev/null
4736|+++ b/exports/agy/.agent/rules/z-harness-planning-router.md
4737|@@ -0,0 +1,152 @@
4738|+---
4739|+trigger: model_decision

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 4889-4897 ---
4889|+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
4890|diff --git a/exports/agy/.agent/skills/z-audit-plan/SKILL.md b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
4891|new file mode 100644
4892|index 0000000..590bf27
4893|--- /dev/null
4894|+++ b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
4895|@@ -0,0 +1,201 @@
4896|+---
4897|+name: z-audit-plan

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 5096-5104 ---
5096|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
5097|diff --git a/exports/agy/.agent/workflows/z-audit-plan.md b/exports/agy/.agent/workflows/z-audit-plan.md
5098|new file mode 100644
5099|index 0000000..495297c
5100|--- /dev/null
5101|+++ b/exports/agy/.agent/workflows/z-audit-plan.md
5102|@@ -0,0 +1,200 @@
5103|+---
5104|+description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 5302-5310 ---
5302|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
5303|diff --git a/exports/agy/prompts/external-lookup.md b/exports/agy/prompts/external-lookup.md
5304|new file mode 100644
5305|index 0000000..6f042f5
5306|--- /dev/null
5307|+++ b/exports/agy/prompts/external-lookup.md
5308|@@ -0,0 +1,149 @@
5309|+---
5310|+description: Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blo...

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 5456-5465 ---
5456|+- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
5457|+- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.
5458|diff --git a/exports/agy/prompts/planning-router.md b/exports/agy/prompts/planning-router.md
5459|new file mode 100644
5460|index 0000000..2ce28f2
5461|--- /dev/null
5462|+++ b/exports/agy/prompts/planning-router.md
5463|@@ -0,0 +1,152 @@
5464|+---
5465|+description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 5615-5623 ---
5615|+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
5616|diff --git a/exports/agy/prompts/skill-z-audit-plan.md b/exports/agy/prompts/skill-z-audit-plan.md
5617|new file mode 100644
5618|index 0000000..aff007f
5619|--- /dev/null
5620|+++ b/exports/agy/prompts/skill-z-audit-plan.md
5621|@@ -0,0 +1,201 @@
5622|+---
5623|+description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 5822-5830 ---
5822|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
5823|diff --git a/exports/agy/prompts/z-audit-plan.md b/exports/agy/prompts/z-audit-plan.md
5824|new file mode 100644
5825|index 0000000..e0df5a0
5826|--- /dev/null
5827|+++ b/exports/agy/prompts/z-audit-plan.md
5828|@@ -0,0 +1,201 @@
5829|+---
5830|+description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 6029-6037 ---
6029|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
6030|diff --git a/exports/codex/prompts/z-audit-plan.md b/exports/codex/prompts/z-audit-plan.md
6031|new file mode 100644
6032|index 0000000..85043f8
6033|--- /dev/null
6034|+++ b/exports/codex/prompts/z-audit-plan.md
6035|@@ -0,0 +1,198 @@
6036|+# /z-audit-plan
6037|+

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 6233-6241 ---
6233|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
6234|diff --git a/exports/cursor/.cursor/rules/external-lookup.mdc b/exports/cursor/.cursor/rules/external-lookup.mdc
6235|new file mode 100644
6236|index 0000000..7621121
6237|--- /dev/null
6238|+++ b/exports/cursor/.cursor/rules/external-lookup.mdc
6239|@@ -0,0 +1,149 @@
6240|+---
6241|+description: "Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blocklist."

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 6387-6396 ---
6387|+- No raw HTML/JSON/YAML in `## Answer` — cite and summarize; dump to raw-artifact pointer if needed.
6388|+- Bash commands recorded verbatim in `provenance.commands`; never truncated in provenance.
6389|diff --git a/exports/cursor/.cursor/rules/planning-router.mdc b/exports/cursor/.cursor/rules/planning-router.mdc
6390|new file mode 100644
6391|index 0000000..b328028
6392|--- /dev/null
6393|+++ b/exports/cursor/.cursor/rules/planning-router.mdc
6394|@@ -0,0 +1,152 @@
6395|+---
6396|+description: "Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only."

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 6546-6554 ---
6546|+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
6547|diff --git a/exports/cursor/.cursor/rules/z-audit-plan.mdc b/exports/cursor/.cursor/rules/z-audit-plan.mdc
6548|new file mode 100644
6549|index 0000000..c045a3d
6550|--- /dev/null
6551|+++ b/exports/cursor/.cursor/rules/z-audit-plan.mdc
6552|@@ -0,0 +1,201 @@
6553|+---
6554|+description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."

--- /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch lines 6752-6761 ---
6752|+- **Strictly Read-Only:** Never modify the codebase during the audit.
6753|+- **Format Consistency:** No emojis, professional headers, clean Markdown structures.
6754|diff --git a/skills/z-audit-plan/SKILL.md b/skills/z-audit-plan/SKILL.md
6755|new file mode 100644
6756|index 0000000..feb09ee
6757|--- /dev/null
6758|+++ b/skills/z-audit-plan/SKILL.md
6759|@@ -0,0 +1,201 @@
6760|+---
6761|+name: z-audit-plan

Full patch paths for reference:
- Delta patch: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch
- Full current patch: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch

Surrounding file context:

=== agents/planning-router.md ===
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

- `existing_artifacts`: compact list of relevant artifacts such as `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`, `RESEARCH.md`, or `BRAINSTORM.md`.

Treat missing required inputs, malformed JSON, unknown `current_command`, or invalid signal types as malformed input.

## Output Contract

Return exactly this parseable shape and no prose before or after:

```text
STATUS: routed | ask_user | bad_input
RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
ROUTE_CLASS: primary | contextual | none
CONFIDENCE: high | medium | low
REASON_CODES: <comma-separated stable reason codes>
REASON: <one line, <=160 chars>
```

`STATUS: routed` requires `RECOMMENDED` to be one concrete command and `ROUTE_CLASS` to be `primary` or `contextual`.

`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.

`STATUS: bad_input` is only for malformed or missing required inputs. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.

## Route Targets

Primary route targets:

- `/z-do`
- `/z-plan-light`
- `/z-plan`
- `/z-plan-split`
- `/z-brainstorm`
- `/z-research`

Contextual exits:

- `/z-audit-plan`
- `/z-fix`
- `/z-debug`
- `/z-amend`
- `/z-maintain-docs`

Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.

## Stable Reason Codes

Use only these reason codes:

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
- `cross_module`
- `schema_or_persistence`
- `too_many_decisions`
- `too_many_files`
- `too_many_tasks`
- `too_few_clusters`
- `too_many_clusters`
- `ambiguous_route`
- `route_loop_risk`
- `bad_input`

## Expected Signals

`signals_json` may include:

- `candidate_files`: integer or `null`
- `expected_tasks`: integer or `null`
- `non_obvious_decisions`: integer or `null`
- `cluster_seams`: integer or `null`
- `cluster_seams_independently_plannable`: boolean
- `cross_module`: boolean
- `schema_or_persistence`: boolean
- `public_api_or_wire_format`: boolean
- `terrain_uncertain`: boolean
- `approach_uncertain`: boolean
- `has_bug_diagnosis`: boolean
- `has_unknown_bug_symptom`: boolean
- `has_existing_plan`: boolean
- `has_fix_artifact`: boolean
- `docs_stale_or_drifted`: boolean

If a relevant signal is missing, reason from what is present and lower confidence. Do not infer file counts, task counts, independent seam plannability, or artifact existence from the filesystem unless the caller supplied an `existing_artifacts` list to interpret.

`non_obvious_decisions: null` means the count is unknown; it does not satisfy "no non-obvious decisions." Likewise, `/z-plan-split` requires an explicit caller-supplied `cluster_seams_independently_plannable: true` signal before recommending a split.

## Decision Rules

Apply these rules in order:

1. If any required input is absent or malformed, return `STATUS: bad_input`.
2. Inspect `route_chain_json` before recommending a target. If the chain already contains two prior entries, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
3. If the best recommendation would send the user back to the immediate prior `from_command`, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
4. Prefer contextual exits when their preconditions are explicit:
   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
   - `has_existing_plan` plus requested plan modification -> `/z-amend`
   - `has_bug_diagnosis` -> `/z-fix`
   - `has_unknown_bug_symptom` -> `/z-debug`
   - `docs_stale_or_drifted` -> `/z-maintain-docs`
5. If `terrain_uncertain` is true, recommend `/z-research`.
6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
11. Otherwise recommend `/z-plan`.

If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.

## Confidence Guidance

- `high`: supplied signals point clearly to one target and required preconditions are explicit.
- `medium`: one target is likely but some quantitative signals are `null` or weak.
- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.

The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.

=== commands/z-audit-plan.md ===
---
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
argument-hint: [--slug <slug>]
---

You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.

This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.

Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.

Deterministic routes:
- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase 0 — Setup

0. **Initialize no-plan route archive:**
   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
   ```bash
   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
   ```
1. **Discover plan slug:**
   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
   - If single candidate -> use it.
   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
2. **Export variables:**
   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
3. **Pick run ID:**
   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
4. **Create directories:**
   `mkdir -p $BASE/archive/$RUN/transcripts`
5. **Version stamp + log run start:**
   Capture the z-harness plugin version stamp and log the run start:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
   ```
6. **Notification policy:**
   Read `Z_HARNESS_NOTIFY` (default `approval_only`).
7. **Docs Grounding:**
   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
   ```
   Agent(
     subagent_type="doc-fetcher",
     description="Doc context for plan audit <slug>",
     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
   )
   ```
   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.

---

## Phase 1 — Reality Check (Reference Verification)

Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:

1. **Entities to verify:**
   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
2. **Bucket division:**
   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
3. **Drift & Hallucination detection:**
   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
   - Flag contract mismatches between proposed specifications and current codebase structures.
   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).

Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.

---

## Phase 2 — Best Practices & Design Audit

Audit the plan's architectural, design, and styling choices against best engineering practices:

1. **Standards verification:**
   - **KISS & DRY:** Check for unnecessary complexity, premature abstractions, or code duplication planned across tasks.
   - **SOLID:** Ensure clean single-responsibility components and clear interface boundaries.
   - **Style:** Align proposed changes with `STYLE.md` rules (if it exists).
2. **Defensive Bloat & Over-engineering:**
   - Check if error handling is overly defensive, or if unnecessary abstractions are introduced where simple code would suffice.
3. **Performance & Resources:**
   - Detect potential N+1 database queries, excessive object allocations in loops, locking/deadlock risks, or poor Big-O complexity in algorithms.
4. **Security & Validation:**
   - Ensure all input validation boundaries, sanitization strategies, authentication/authorization checks, and data exposure patterns are secure.

Checkpoint: Write results to `$BASE/archive/$RUN/phase2-design.md`.

---

## Phase 3 — Adversarial Cross-LLM Review

Spawn two consultants in parallel to review the plan's artifacts (`SPEC.md`, `PLAN.md`, `TASKS.md`) and Phase 1/2 audit notes with a highly critical, adversarial mindset:

```
Agent(
  subagent_type="consultant-primary",
  description="Adversarial plan audit review (Gemini) for <slug>",
  prompt="MODE: plan-audit-review\n\nSPEC:\n<SPEC.md>\n\nPLAN:\n<PLAN.md>\n\nTASKS:\n<TASKS.md>\n\nReality Check Notes:\n<phase1-reality.md>\n\nDesign Audit Notes:\n<phase2-design.md>\n\nAct as a highly critical, adversarial 'Senior Nitpicker'. Find logic flaws, race conditions, edge cases, missing tests in acceptance criteria, security concerns, style drift, or over-engineering in the plan. Report findings with severity (BLOCKER / MAJOR / MINOR), location, and recommendations."
)
Agent(
  subagent_type="consultant-secondary",
  description="Adversarial plan audit review (Codex) for <slug>",
  prompt="MODE: plan-audit-review\n\n<same prompt>"
)
```

Both consultants return structured findings. Transcripts are archived under `$BASE/archive/$RUN/transcripts/`.

---

## Phase 4 — Merge and Synthesize Findings

1. **Aggregation:**
   Merge findings from Reality Check, Design Audit, and both adversarial consultant reviews.
2. **One-Reason-This-Might-Be-Wrong Gate:**
   For every finding, write a brief statement detailing "one reason this finding might be wrong, irrelevant, or pedantic". If the pushback is valid:
   - Drop the finding from the final report.
   - Or demote its severity.
3. **Write final report:**
   Write the unified plan-audit report to `$BASE/PLAN_AUDIT_REPORT.md` (and save a copy in `$BASE/archive/$RUN/PLAN_AUDIT_REPORT.md`):
   ```markdown
   # Plan Audit Report — <slug>
   
   - **Date (UTC):** YYYY-MM-DDTHH:MMZ
   - **Slug:** <slug>
   - **Run ID:** <RUN>
   
   ## Summary
   - <Actionable high-level takeaways>
   
   ## reality-check Reality Check findings
   <Stale references, naming drift, clashing paths>
   
   ## design-check Design & Style findings
   <SOLID/DRY violations, style drift, over-engineering, performance, security>
   
   ## adversarial Adversarial Consult findings
   <Logic gaps, race conditions, unhandled edge cases, missing tests in acceptance>
   
   ## Consensus vs Disagreement
   - consensus: <findings flagged by multiple layers>
   - outlier: <findings worth manual scrutiny>
   
   ## Actionable Recommendations
   <Categorized recommendations with recommended actions>
   ```

---

## Phase 5 — User Gate & Action

1. **Notify:**
   If notification policy ≠ `off`, send a `PushNotification`: "Plan audit complete: N findings surfaced."
2. **Present report:**
   Present the list of findings to the user, highlighting BLOCKER and MAJOR severities.
3. **Ask user via `AskUserQuestion`:**
   - **Amend Plan (Run z-amend):** Trigger interactive plan amendment to address findings.
   - **Proceed as-is:** Acknowledge findings as acceptable tradeoffs and start implementation.
   - **Reject & Re-plan:** Discard current plan artifacts and rerun `/z-plan`.
4. **Log run end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
     "$(printf '{"status":"complete","findings":%d,"blockers":%d,"majors":%d}' "$N_FINDINGS" "$N_BLOCKERS" "$N_MAJORS")"
   ```

---

## Operating Principles

- **Rigorous Verification:** Validate all facts before starting the implementation.
- **Push Back on Reviews:** Apply the "one reason it might be wrong" check to keep reports high-signal.
- **Strictly Read-Only:** Never modify the codebase during the audit.
- **Format Consistency:** No emojis, professional headers, clean Markdown structures.

=== skills/z-audit-plan/SKILL.md ===
---
name: z-audit-plan
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
---

You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.

This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.

Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.

Deterministic routes:
- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase 0 — Setup

0. **Initialize no-plan route archive:**
   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
   ```bash
   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
   ```
1. **Discover plan slug:**
   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
   - If single candidate -> use it.
   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
2. **Export variables:**
   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
3. **Pick run ID:**
   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
4. **Create directories:**
   `mkdir -p $BASE/archive/$RUN/transcripts`
5. **Version stamp + log run start:**
   Capture the z-harness plugin version stamp and log the run start:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
   ```
6. **Notification policy:**
   Read `Z_HARNESS_NOTIFY` (default `approval_only`).
7. **Docs Grounding:**
   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
   ```
   Agent(
     subagent_type="doc-fetcher",
     description="Doc context for plan audit <slug>",
     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
   )
   ```
   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.

---

## Phase 1 — Reality Check (Reference Verification)

Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:

1. **Entities to verify:**
   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
2. **Bucket division:**
   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
3. **Drift & Hallucination detection:**
   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
   - Flag contract mismatches between proposed specifications and current codebase structures.
   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).

Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.

---

## Phase 2 — Best Practices & Design Audit

Audit the plan's architectural, design, and styling choices against best engineering practices:

1. **Standards verification:**
   - **KISS & DRY:** Check for unnecessary complexity, premature abstractions, or code duplication planned across tasks.
   - **SOLID:** Ensure clean single-responsibility components and clear interface boundaries.
   - **Style:** Align proposed changes with `STYLE.md` rules (if it exists).
2. **Defensive Bloat & Over-engineering:**
   - Check if error handling is overly defensive, or if unnecessary abstractions are introduced where simple code would suffice.
3. **Performance & Resources:**
   - Detect potential N+1 database queries, excessive object allocations in loops, locking/deadlock risks, or poor Big-O complexity in algorithms.
4. **Security & Validation:**
   - Ensure all input validation boundaries, sanitization strategies, authentication/authorization checks, and data exposure patterns are secure.

Checkpoint: Write results to `$BASE/archive/$RUN/phase2-design.md`.

---

## Phase 3 — Adversarial Cross-LLM Review

Spawn two consultants in parallel to review the plan's artifacts (`SPEC.md`, `PLAN.md`, `TASKS.md`) and Phase 1/2 audit notes with a highly critical, adversarial mindset:

```
Agent(
  subagent_type="consultant-primary",
  description="Adversarial plan audit review (Gemini) for <slug>",
  prompt="MODE: plan-audit-review\n\nSPEC:\n<SPEC.md>\n\nPLAN:\n<PLAN.md>\n\nTASKS:\n<TASKS.md>\n\nReality Check Notes:\n<phase1-reality.md>\n\nDesign Audit Notes:\n<phase2-design.md>\n\nAct as a highly critical, adversarial 'Senior Nitpicker'. Find logic flaws, race conditions, edge cases, missing tests in acceptance criteria, security concerns, style drift, or over-engineering in the plan. Report findings with severity (BLOCKER / MAJOR / MINOR), location, and recommendations."
)
Agent(
  subagent_type="consultant-secondary",
  description="Adversarial plan audit review (Codex) for <slug>",
  prompt="MODE: plan-audit-review\n\n<same prompt>"
)
```

Both consultants return structured findings. Transcripts are archived under `$BASE/archive/$RUN/transcripts/`.

---

## Phase 4 — Merge and Synthesize Findings

1. **Aggregation:**
   Merge findings from Reality Check, Design Audit, and both adversarial consultant reviews.
2. **One-Reason-This-Might-Be-Wrong Gate:**
   For every finding, write a brief statement detailing "one reason this finding might be wrong, irrelevant, or pedantic". If the pushback is valid:
   - Drop the finding from the final report.
   - Or demote its severity.
3. **Write final report:**
   Write the unified plan-audit report to `$BASE/PLAN_AUDIT_REPORT.md` (and save a copy in `$BASE/archive/$RUN/PLAN_AUDIT_REPORT.md`):
   ```markdown
   # Plan Audit Report — <slug>
   
   - **Date (UTC):** YYYY-MM-DDTHH:MMZ
   - **Slug:** <slug>
   - **Run ID:** <RUN>
   
   ## Summary
   - <Actionable high-level takeaways>
   
   ## reality-check Reality Check findings
   <Stale references, naming drift, clashing paths>
   
   ## design-check Design & Style findings
   <SOLID/DRY violations, style drift, over-engineering, performance, security>
   
   ## adversarial Adversarial Consult findings
   <Logic gaps, race conditions, unhandled edge cases, missing tests in acceptance>
   
   ## Consensus vs Disagreement
   - consensus: <findings flagged by multiple layers>
   - outlier: <findings worth manual scrutiny>
   
   ## Actionable Recommendations
   <Categorized recommendations with recommended actions>
   ```

---

## Phase 5 — User Gate & Action

1. **Notify:**
   If notification policy ≠ `off`, send a `PushNotification`: "Plan audit complete: N findings surfaced."
2. **Present report:**
   Present the list of findings to the user, highlighting BLOCKER and MAJOR severities.
3. **Ask user via `AskUserQuestion`:**
   - **Amend Plan (Run z-amend):** Trigger interactive plan amendment to address findings.
   - **Proceed as-is:** Acknowledge findings as acceptable tradeoffs and start implementation.
   - **Reject & Re-plan:** Discard current plan artifacts and rerun `/z-plan`.
4. **Log run end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
     "$(printf '{"status":"complete","findings":%d,"blockers":%d,"majors":%d}' "$N_FINDINGS" "$N_BLOCKERS" "$N_MAJORS")"
   ```

---

## Operating Principles

- **Rigorous Verification:** Validate all facts before starting the implementation.
- **Push Back on Reviews:** Apply the "one reason it might be wrong" check to keep reports high-signal.
- **Strictly Read-Only:** Never modify the codebase during the audit.
- **Format Consistency:** No emojis, professional headers, clean Markdown structures.

=== exports/cursor/.cursor/rules/planning-router.mdc ===
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

Treat missing required inputs, malformed JSON, unknown `current_command`, or invalid signal types as malformed input.

## Output Contract

Return exactly this parseable shape and no prose before or after:

```text
STATUS: routed | ask_user | bad_input
RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
ROUTE_CLASS: primary | contextual | none
CONFIDENCE: high | medium | low
REASON_CODES: <comma-separated stable reason codes>
REASON: <one line, <=160 chars>
```

`STATUS: routed` requires `RECOMMENDED` to be one concrete command and `ROUTE_CLASS` to be `primary` or `contextual`.

`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.

`STATUS: bad_input` is only for malformed or missing required inputs. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.

## Route Targets

Primary route targets:

- `/z-do`
- `/z-plan-light`
- `/z-plan`
- `/z-plan-split`
- `/z-brainstorm`
- `/z-research`

Contextual exits:

- `/z-audit-plan`
- `/z-fix`
- `/z-debug`
- `/z-amend`
- `/z-maintain-docs`

Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.

## Stable Reason Codes

Use only these reason codes:

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
- `cross_module`
- `schema_or_persistence`
- `too_many_decisions`
- `too_many_files`
- `too_many_tasks`
- `too_few_clusters`
- `too_many_clusters`
- `ambiguous_route`
- `route_loop_risk`
- `bad_input`

## Expected Signals

`signals_json` may include:

- `candidate_files`: integer or `null`
- `expected_tasks`: integer or `null`
- `non_obvious_decisions`: integer or `null`
- `cluster_seams`: integer or `null`
- `cluster_seams_independently_plannable`: boolean
- `cross_module`: boolean
- `schema_or_persistence`: boolean
- `public_api_or_wire_format`: boolean
- `terrain_uncertain`: boolean
- `approach_uncertain`: boolean
- `has_bug_diagnosis`: boolean
- `has_unknown_bug_symptom`: boolean
- `has_existing_plan`: boolean
- `has_fix_artifact`: boolean
- `docs_stale_or_drifted`: boolean

If a relevant signal is missing, reason from what is present and lower confidence. Do not infer file counts, task counts, independent seam plannability, or artifact existence from the filesystem unless the caller supplied an `existing_artifacts` list to interpret.

`non_obvious_decisions: null` means the count is unknown; it does not satisfy "no non-obvious decisions." Likewise, `/z-plan-split` requires an explicit caller-supplied `cluster_seams_independently_plannable: true` signal before recommending a split.

## Decision Rules

Apply these rules in order:

1. If any required input is absent or malformed, return `STATUS: bad_input`.
2. Inspect `route_chain_json` before recommending a target. If the chain already contains two prior entries, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
3. If the best recommendation would send the user back to the immediate prior `from_command`, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
4. Prefer contextual exits when their preconditions are explicit:
   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
   - `has_existing_plan` plus requested plan modification -> `/z-amend`
   - `has_bug_diagnosis` -> `/z-fix`
   - `has_unknown_bug_symptom` -> `/z-debug`
   - `docs_stale_or_drifted` -> `/z-maintain-docs`
5. If `terrain_uncertain` is true, recommend `/z-research`.
6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
11. Otherwise recommend `/z-plan`.

If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.

## Confidence Guidance

- `high`: supplied signals point clearly to one target and required preconditions are explicit.
- `medium`: one target is likely but some quantitative signals are `null` or weak.
- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.

The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.

=== exports/agy/.agent/rules/z-harness-planning-router.md ===
---
trigger: model_decision
description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
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

Treat missing required inputs, malformed JSON, unknown `current_command`, or invalid signal types as malformed input.

## Output Contract

Return exactly this parseable shape and no prose before or after:

```text
STATUS: routed | ask_user | bad_input
RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
ROUTE_CLASS: primary | contextual | none
CONFIDENCE: high | medium | low
REASON_CODES: <comma-separated stable reason codes>
REASON: <one line, <=160 chars>
```

`STATUS: routed` requires `RECOMMENDED` to be one concrete command and `ROUTE_CLASS` to be `primary` or `contextual`.

`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.

`STATUS: bad_input` is only for malformed or missing required inputs. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.

## Route Targets

Primary route targets:

- `/z-do`
- `/z-plan-light`
- `/z-plan`
- `/z-plan-split`
- `/z-brainstorm`
- `/z-research`

Contextual exits:

- `/z-audit-plan`
- `/z-fix`
- `/z-debug`
- `/z-amend`
- `/z-maintain-docs`

Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.

## Stable Reason Codes

Use only these reason codes:

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
- `cross_module`
- `schema_or_persistence`
- `too_many_decisions`
- `too_many_files`
- `too_many_tasks`
- `too_few_clusters`
- `too_many_clusters`
- `ambiguous_route`
- `route_loop_risk`
- `bad_input`

## Expected Signals

`signals_json` may include:

- `candidate_files`: integer or `null`
- `expected_tasks`: integer or `null`
- `non_obvious_decisions`: integer or `null`
- `cluster_seams`: integer or `null`
- `cluster_seams_independently_plannable`: boolean
- `cross_module`: boolean
- `schema_or_persistence`: boolean
- `public_api_or_wire_format`: boolean
- `terrain_uncertain`: boolean
- `approach_uncertain`: boolean
- `has_bug_diagnosis`: boolean
- `has_unknown_bug_symptom`: boolean
- `has_existing_plan`: boolean
- `has_fix_artifact`: boolean
- `docs_stale_or_drifted`: boolean

If a relevant signal is missing, reason from what is present and lower confidence. Do not infer file counts, task counts, independent seam plannability, or artifact existence from the filesystem unless the caller supplied an `existing_artifacts` list to interpret.

`non_obvious_decisions: null` means the count is unknown; it does not satisfy "no non-obvious decisions." Likewise, `/z-plan-split` requires an explicit caller-supplied `cluster_seams_independently_plannable: true` signal before recommending a split.

## Decision Rules

Apply these rules in order:

1. If any required input is absent or malformed, return `STATUS: bad_input`.
2. Inspect `route_chain_json` before recommending a target. If the chain already contains two prior entries, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
3. If the best recommendation would send the user back to the immediate prior `from_command`, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
4. Prefer contextual exits when their preconditions are explicit:
   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
   - `has_existing_plan` plus requested plan modification -> `/z-amend`
   - `has_bug_diagnosis` -> `/z-fix`
   - `has_unknown_bug_symptom` -> `/z-debug`
   - `docs_stale_or_drifted` -> `/z-maintain-docs`
5. If `terrain_uncertain` is true, recommend `/z-research`.
6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
7. Apply split-specific seam rules before generic downrouting. If `current_command` is `/z-plan-split` or `cluster_seams` is present, resolve these seam rules before considering `candidate_files`-based routes:
   - If `current_command` is `/z-plan-split` and `cluster_seams` is `null` or absent, recommend `/z-research` with `needs_research` unless other supplied signals genuinely conflict; in that case return `STATUS: ask_user` with `ambiguous_route`.
   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
   - If `cluster_seams` is between 2 and 6 and `cluster_seams_independently_plannable` is true, recommend `/z-plan-split`.
   - If `cluster_seams` is between 2 and 6 but independent plannability is false or unknown, do not recommend `/z-plan-split`; prefer `/z-plan` or return `STATUS: ask_user` with `ambiguous_route` if `/z-plan` and `/z-plan-split` remain tied.
8. If `candidate_files` is known and `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions == 0`, recommend `/z-do`. If `non_obvious_decisions` is `null` or absent, do not recommend `/z-do`; choose a safer planning route or `ask_user` with lower confidence.
9. If `candidate_files` is known and `candidate_files <= 5`, `non_obvious_decisions` is known and `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
10. If `expected_tasks > 25`, recommend `/z-plan-split` only when `cluster_seams_independently_plannable` is true; otherwise recommend `/z-plan` with medium or low confidence based on the supplied signals.
11. Otherwise recommend `/z-plan`.

If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.

## Confidence Guidance

- `high`: supplied signals point clearly to one target and required preconditions are explicit.
- `medium`: one target is likely but some quantitative signals are `null` or weak.
- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.

The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.

=== exports/agy/prompts/z-audit-plan.md ===
---
description: Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md.
role: workflow
---

You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.

This command is **read-only**. Never edit active codebase files. Plan adjustments happen later via `/z-amend` or `/z-plan` based on the audit report's findings.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.

Use only already-known setup signals: `has_existing_plan`, `candidate_files`, `expected_tasks`, `docs_stale_or_drifted`, and whether `SPEC.md`, `PLAN.md`, and `TASKS.md` are present under `$Z_HARNESS_PLAN_DIR`.

Deterministic routes:
- If no plan artifacts are found, route to `/z-plan`; do not pretend an audit can proceed.
- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
- If the completed audit finds accepted plan changes, route contextually to `/z-amend`.
- If doc drift blocks audit confidence, route contextually to `/z-maintain-docs`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

---

## Phase 0 — Setup

0. **Initialize no-plan route archive:**
   Before discovering a plan slug, define a route archive for the "no artifacts found" branch:
   ```bash
   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
   ```
1. **Discover plan slug:**
   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
   - If single candidate -> use it.
   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
2. **Export variables:**
   Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`. Define `$BASE = $Z_HARNESS_PLAN_DIR`.
3. **Pick run ID:**
   `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>-audit-plan`
4. **Create directories:**
   `mkdir -p $BASE/archive/$RUN/transcripts`
5. **Version stamp + log run start:**
   Capture the z-harness plugin version stamp and log the run start:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_start "$START_PAYLOAD"
   ```
6. **Notification policy:**
   Read `Z_HARNESS_NOTIFY` (default `approval_only`).
7. **Docs Grounding:**
   If `docs/llm/INDEX.json` exists in the repo root, dispatch `doc-fetcher` (Haiku) to identify concepts touched by this plan:
   ```
   <!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
     subagent_type="doc-fetcher",
     description="Doc context for plan audit <slug>",
     prompt="query: which concepts cover <plan files and symbols>?\nrepo_root: <abs path>\ndepth: summary"
   )
   ```
   Use the returned concept slugs to retrieve the appropriate `docs/llm/<concept>.json` files as plan-grounding validation guidelines.

---

## Phase 1 — Reality Check (Reference Verification)

Parse `$BASE/SPEC.md` and `$BASE/TASKS.md` to identify factual claims made about the active codebase. Scrutinize these references:

1. **Entities to verify:**
   - **Files & Directories:** Ensure paths described as existing or as preconditions actually exist.
   - **Symbols:** Grep for declarations of functions, methods, classes, variables, or types mentioned in the spec.
   - **Configs:** Verify the existence of specific configuration files or specific JSON/YAML/TOML keys referenced in the plan.
   - **Database Elements:** Ensure tables or columns referenced as active database preconditions exist in schema declarations, models, or migration files.
   - **CLI Flags:** Ensure referenced CLI arguments are declared in their respective option-parsing functions.
2. **Bucket division:**
   - **MUST EXIST NOW:** Entities described as present. Run `Read`/`Grep`/`Glob` to verify their existence and declarations exactly.
   - **WILL BE CREATED:** Newly proposed files. Verify that their proposed paths do not clash with existing files in the codebase.
3. **Drift & Hallucination detection:**
   - Flag similar-but-different naming (e.g. `user_id` vs `uid`, or double-suffixes).
   - Flag contract mismatches between proposed specifications and current codebase structures.
   - Flag dependency order violations (e.g., plan relies on a database table that is not created in this or any prior completed plan).

Checkpoint: Write results to `$BASE/archive/$RUN/phase1-reality.md`.

---

## Phase 2 — Best Practices & Design Audit

Audit the plan's architectural, design, and styling choices against best engineering practices:

1. **Standards verification:**
   - **KISS & DRY:** Check for unnecessary complexity, premature abstractions, or code duplication planned across tasks.
   - **SOLID:** Ensure clean single-responsibility components and clear interface boundaries.
   - **Style:** Align proposed changes with `STYLE.md` rules (if it exists).
2. **Defensive Bloat & Over-engineering:**
   - Check if error handling is overly defensive, or if unnecessary abstractions are introduced where simple code would suffice.
3. **Performance & Resources:**
   - Detect potential N+1 database queries, excessive object allocations in loops, locking/deadlock risks, or poor Big-O complexity in algorithms.
4. **Security & Validation:**
   - Ensure all input validation boundaries, sanitization strategies, authentication/authorization checks, and data exposure patterns are secure.

Checkpoint: Write results to `$BASE/archive/$RUN/phase2-design.md`.

---

## Phase 3 — Adversarial Cross-LLM Review

Spawn two consultants in parallel to review the plan's artifacts (`SPEC.md`, `PLAN.md`, `TASKS.md`) and Phase 1/2 audit notes with a highly critical, adversarial mindset:

```
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Adversarial plan audit review (Gemini) for <slug>",
  prompt="MODE: plan-audit-review\n\nSPEC:\n<SPEC.md>\n\nPLAN:\n<PLAN.md>\n\nTASKS:\n<TASKS.md>\n\nReality Check Notes:\n<phase1-reality.md>\n\nDesign Audit Notes:\n<phase2-design.md>\n\nAct as a highly critical, adversarial 'Senior Nitpicker'. Find logic flaws, race conditions, edge cases, missing tests in acceptance criteria, security concerns, style drift, or over-engineering in the plan. Report findings with severity (BLOCKER / MAJOR / MINOR), location, and recommendations."
)
<!-- agent dispatch / skill invocation not supported in Antigravity; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Adversarial plan audit review (Codex) for <slug>",
  prompt="MODE: plan-audit-review\n\n<same prompt>"
)
```

Both consultants return structured findings. Transcripts are archived under `$BASE/archive/$RUN/transcripts/`.

---

## Phase 4 — Merge and Synthesize Findings

1. **Aggregation:**
   Merge findings from Reality Check, Design Audit, and both adversarial consultant reviews.
2. **One-Reason-This-Might-Be-Wrong Gate:**
   For every finding, write a brief statement detailing "one reason this finding might be wrong, irrelevant, or pedantic". If the pushback is valid:
   - Drop the finding from the final report.
   - Or demote its severity.
3. **Write final report:**
   Write the unified plan-audit report to `$BASE/PLAN_AUDIT_REPORT.md` (and save a copy in `$BASE/archive/$RUN/PLAN_AUDIT_REPORT.md`):
   ```markdown
   # Plan Audit Report — <slug>
   
   - **Date (UTC):** YYYY-MM-DDTHH:MMZ
   - **Slug:** <slug>
   - **Run ID:** <RUN>
   
   ## Summary
   - <Actionable high-level takeaways>
   
   ## reality-check Reality Check findings
   <Stale references, naming drift, clashing paths>
   
   ## design-check Design & Style findings
   <SOLID/DRY violations, style drift, over-engineering, performance, security>
   
   ## adversarial Adversarial Consult findings
   <Logic gaps, race conditions, unhandled edge cases, missing tests in acceptance>
   
   ## Consensus vs Disagreement
   - consensus: <findings flagged by multiple layers>
   - outlier: <findings worth manual scrutiny>
   
   ## Actionable Recommendations
   <Categorized recommendations with recommended actions>
   ```

---

## Phase 5 — User Gate & Action

1. **Notify:**
   If notification policy ≠ `off`, send a `PushNotification`: "Plan audit complete: N findings surfaced."
2. **Present report:**
   Present the list of findings to the user, highlighting BLOCKER and MAJOR severities.
3. **Ask user via `AskUserQuestion`:**
   - **Amend Plan (Run z-amend):** Trigger interactive plan amendment to address findings.
   - **Proceed as-is:** Acknowledge findings as acceptable tradeoffs and start implementation.
   - **Reject & Re-plan:** Discard current plan artifacts and rerun `/z-plan`.
4. **Log run end:**
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_audit_end \
     "$(printf '{"status":"complete","findings":%d,"blockers":%d,"majors":%d}' "$N_FINDINGS" "$N_BLOCKERS" "$N_MAJORS")"
   ```

---

## Operating Principles

- **Rigorous Verification:** Validate all facts before starting the implementation.
- **Push Back on Reviews:** Apply the "one reason it might be wrong" check to keep reports high-signal.
- **Strictly Read-Only:** Never modify the codebase during the audit.
- **Format Consistency:** No emojis, professional headers, clean Markdown structures.

=== exports/agy/agy-plugin.yaml ===
# agy-plugin.yaml
# z-harness agy export manifest — read by scripts/export-agy.py
# NOT a native Antigravity file format (agy does not read this)
schema_version: 1

metadata:
  name: z-harness
  description: z-harness planning and implementation workflow for Antigravity IDE
  source_repo: https://github.com/zeke-tools/z-harness

# Commands → .agent/workflows/*.md
# Each command becomes a custom chat mode (agy chat --mode <id>)
workflows:
  - id: z-amend
    source: commands/z-amend.md
    output: .agent/workflows/z-amend.md
    description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
  - id: z-audit-plan
    source: commands/z-audit-plan.md
    output: .agent/workflows/z-audit-plan.md
    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
  - id: z-audit
    source: commands/z-audit.md
    output: .agent/workflows/z-audit.md
    description: "Audit a target component across one or more dimensions (correctness / perf / cleanliness / design). Pre-flight scopes (target, dimensions, optional rubric file), spawns one auditor subagent per dimension in parallel, runs bundled Gemini+Codex cons..."
  - id: z-brainstorm
    source: commands/z-brainstorm.md
    output: .agent/workflows/z-brainstorm.md
    description: "Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan."
  - id: z-debug
    source: commands/z-debug.md
    output: .agent/workflows/z-debug.md
    description: "Heavy hypothesis-tournament debugging pipeline for the case where root cause is unknown. Two rounds of adversarial multi-LLM hypothesis generation (Claude + Codex + Gemini), discriminating-test matrix with consensus-first ranking + forced outlier ..."
  - id: z-do
    source: commands/z-do.md
    output: .agent/workflows/z-do.md
    description: "Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can..."
  - id: z-export
    source: commands/z-export.md
    output: .agent/workflows/z-export.md
    description: "\"Export z-harness commands/agents/skills to Cursor / Codex / Antigravity (agy).\""
  - id: z-fix
    source: commands/z-fix.md
    output: .agent/workflows/z-fix.md
    description: "Lightweight bug-fix command for the case where the user already has a diagnosis. Captures problem + repro, single light-fix sanity consult (\"does the proposed cause explain all symptoms?\"), inline implementation, non-negotiable Codex review. Optio..."
  - id: z-implement-all
    source: commands/z-implement-all.md
    output: .agent/workflows/z-implement-all.md
    description: "Orchestrate implementation of ALL pending tasks in z-harness/TASKS.md, spawning a fresh implementer subagent per task and a reviewer per task. Halts on blockers, retries once on review failure, push-notifies user on every gate."
  - id: z-implement-next
    source: commands/z-implement-next.md
    output: .agent/workflows/z-implement-next.md
    description: "Implement the next pending task from z-harness/TASKS.md, then have Codex scrutinize the diff."
  - id: z-improve
    source: commands/z-improve.md
    output: .agent/workflows/z-improve.md
    description: "Post-run retrospective. Analyzes ONE z-harness run's events.jsonl + artifacts, identifies friction signals (slow phases, retries, doc drift, blocked askings, reviewer cycles), and opens a discussion with the user about concrete edits to the z-harn..."
  - id: z-init-docs
    source: commands/z-init-docs.md
    output: .agent/workflows/z-init-docs.md
    description: "Bootstrap a two-tier docs system in the current repo — docs/human/ (Markdown for humans) and docs/llm/ (token-compacted JSON for fast-lookup by future /z-plan runs). Idempotent; re-runnable to extend coverage."
  - id: z-maintain-docs
    source: commands/z-maintain-docs.md
    output: .agent/workflows/z-maintain-docs.md
    description: "Refresh stale docs in docs/human/ and docs/llm/. Reads docs/llm/INDEX.json to find concepts whose source files changed since each doc's last_updated. Spawns doc-updater subagents (Sonnet) per stale concept. Dry-run preview by default — user review..."
  - id: z-mr-review
    source: commands/z-mr-review.md
    output: .agent/workflows/z-mr-review.md
    description: "Multi-LLM code-quality review of the current branch diff against STYLE.md. Never blocks; ranks P0-P4; output is a TASKS.md-shape file you edit and feed to /z-implement-all."
  - id: z-plan-light
    source: commands/z-plan-light.md
    output: .agent/workflows/z-plan-light.md
    description: "Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sidewa..."
  - id: z-plan-split
    source: commands/z-plan-split.md
    output: .agent/workflows/z-plan-split.md
    description: "Pre-emptive scope splitter — fan a big topic out into N narrow cluster-planner subagents in parallel, then reconcile file-path overlaps into SHARED-CONCERNS.md + MANIFEST.md."
  - id: z-plan
    source: commands/z-plan.md
    output: .agent/workflows/z-plan.md
    description: "Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md."
  - id: z-providers-discover
    source: commands/z-providers-discover.md
    output: .agent/workflows/z-providers-discover.md
    description: Discover LLM CLI providers in PATH and generate providers.json.
  - id: z-research
    source: commands/z-research.md
    output: .agent/workflows/z-research.md
    description: "Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach."
  - id: z-review-all
    source: commands/z-review-all.md
    output: .agent/workflows/z-review-all.md
    description: "Final-gate cross-LLM review of a completed z-harness plan. Runs Gemini + Codex on the cumulative diff against SPEC.md to surface (a) implementation drift across tasks and (b) spec gaps that only surface in aggregate. Use after /z-implement-all com..."
  - id: z-skill-fix
    source: commands/z-skill-fix.md
    output: .agent/workflows/z-skill-fix.md
    description: "Diagnose and patch a misleading skill file — any SKILL.md under .claude/skills/ in the current repo, or any z-harness commands/*.md / agents/*.md when invoked inside the z-harness repo itself. Inline diagnosis note, surgical edit, reviewer safety ..."
  - id: z-stats
    source: commands/z-stats.md
    output: .agent/workflows/z-stats.md
    description: "Read-only progress + cost report for a z-harness plan. Reads metrics.jsonl + TASKS.md to summarize progress, wall time per phase, estimated token spend per subagent type, recent halts, and suggested next command. No writes, no LLM calls."
  - id: z-style-init
    source: commands/z-style-init.md
    output: .agent/workflows/z-style-init.md
    description: "Author the project STYLE.md interactively, grounded in the repo's most idiomatic existing files (Capture). Required before /z-mr-review will run."
  - id: z-suggest-memory
    source: commands/z-suggest-memory.md
    output: .agent/workflows/z-suggest-memory.md
    description: "Authoring skill for the docs/llm/ memory layer. Called mandatorily from /z-debug post-mortem and /z-improve retro. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extract..."
  - id: z-test
    source: commands/z-test.md
    output: .agent/workflows/z-test.md
    description: "Semantic test-case planner. Reads SPEC.md + PLAN.md + TASKS.md for an existing plan, risk-ranks the tasks, drafts non-trivial test cases that catch real semantic bugs (sign errors, schema/feature mismatches, time-window off-by-one, unit confusion,..."
  - id: z-update
    source: commands/z-update.md
    output: .agent/workflows/z-update.md
    description: "z-harness z-update workflow"

# Agents → .agent/rules/*.md
# No subagent dispatch in agy; agents become role-specific rule files
rules:
  - id: auditor
    source: agents/auditor.md
    output: .agent/rules/z-harness-auditor.md
    trigger: always_on
    description: "Fresh-context Sonnet auditor for a single dimension (correctness | perf | cleanliness | design). Reads target files + optional rubric file, returns structured findings (Location / Evidence / Recommendation / Severity). Read-only — never edits. Spa..."
  - id: cluster-planner
    source: agents/cluster-planner.md
    output: .agent/rules/z-harness-cluster-planner.md
    trigger: model_decision
    description: "A `model: sonnet` subagent that runs a stripped-down `/z-plan`-equivalent for ONE narrow scope (one cluster) within a `/z-plan-split` run. Produces SPEC.md + PLAN.md + TASKS.md for the cluster, resolves small decisions unilaterally, and escalates ..."
  - id: complexity-classifier
    source: agents/complexity-classifier.md
    output: .agent/rules/z-harness-complexity-classifier.md
    trigger: model_decision
    description: "Reads a single task block (plus optional SPEC.md slice) and returns a complexity tier — `low`, `medium`, or `high` — that the orchestrator uses to pick which model to dispatch the implementer at. Cheap Haiku call, one per task, stamped once at pla..."
  - id: consultant-primary
    source: agents/consultant-primary.md
    output: .agent/rules/z-harness-consultant-primary.md
    trigger: model_decision
    description: "Routes to the primary consultant LLM (resolved via providers registry) for a second opinion on an engineering decision or to review a plan. Use during /z-plan when a non-obvious decision needs cross-LLM input, and again to review the final plan."
  - id: consultant-secondary
    source: agents/consultant-secondary.md
    output: .agent/rules/z-harness-consultant-secondary.md
    trigger: model_decision
    description: "Routes to the secondary consultant LLM (resolved via providers registry) for a second opinion on an engineering decision or to review a plan. Use during /z-plan as the cross-LLM counterpart to consultant-primary — must resolve to a distinct provider."
  - id: doc-fetcher
    source: agents/doc-fetcher.md
    output: .agent/rules/z-harness-doc-fetcher.md
    trigger: model_decision
    description: "Fast Haiku context-fetcher for the two-tier docs system (docs/llm/INDEX.json + per-concept LLM JSONs + human-tier markdown). Caller asks \"I need context on X\"; this agent reads INDEX.json, picks the matching concept(s), reads their JSONs (and opti..."
  - id: doc-updater
    source: agents/doc-updater.md
    output: .agent/rules/z-harness-doc-updater.md
    trigger: model_decision
    description: "Sonnet subagent invoked by /z-maintain-docs to refresh ONE doc concept (one human-tier markdown + one llm-tier JSON entry) so they reflect current code. Returns the proposed updates as text (dry-run by default); does NOT write to disk unless expli..."
  - id: external-lookup
    source: agents/external-lookup.md
    output: .agent/rules/z-harness-external-lookup.md
    trigger: model_decision
    description: "Fetch external information (web docs, public APIs, paginated JSON, library docs outside training cutoff) and return a tight STATUS-headed Markdown synthesis per docs/llm/lookup-contract.json. Read-only. Refuses mutating shell commands via verb-blo..."
  - id: implementer
    source: agents/implementer.md
    output: .agent/rules/z-harness-implementer.md
    trigger: always_on
    description: "Implements a single task from $Z_HARNESS_PLAN_DIR/TASKS.md in a fresh context. Invoked by /z-implement-all once per task to keep main orchestrator context lean. Reads only the slice of SPEC.md/PLAN.md it needs, edits files, returns a structured su..."
  - id: mr-reviewer
    source: agents/mr-reviewer.md
    output: .agent/rules/z-harness-mr-reviewer.md
    trigger: always_on
    description: "Multi-LLM code-quality reviewer for branch diffs. Assumes correctness; targets AI-shaped and human-shaped slop. Ranks P0-P4, never blocks, never finds correctness bugs (those belong to reviewer)."
  - id: planning-router
    source: agents/planning-router.md
    output: .agent/rules/z-harness-planning-router.md
    trigger: model_decision
    description: "Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only."
  - id: remote-runner
    source: agents/remote-runner.md
    output: .agent/rules/z-harness-remote-runner.md
    trigger: always_on
    description: "Haiku subagent that handles MECHANICAL remote work — rsync local repo to a per-(slug, task-id) sandbox on the remote host, run cargo build/check/clean, restart paper qtctl manifests, tail logs, run READ-ONLY DB/disk/log queries against shared stat..."
  - id: reviewer
    source: agents/reviewer.md
    output: .agent/rules/z-harness-reviewer.md
    trigger: always_on
    description: "Routes to the reviewer LLM (resolved via providers registry) to scrutinize a just-completed implementation task. Finds bugs, spec violations, missed edge cases, and DRY/KISS/SOLID violations."
  - id: spec-precheck
    source: agents/spec-precheck.md
    output: .agent/rules/z-harness-spec-precheck.md
    trigger: model_decision
    description: "Pre-flight sanity check that runs BEFORE the implementer for each task in /z-implement-all. Verifies SPEC.md references (symbols, table names, column names, config keys, file paths) actually exist in the codebase as described — so spec drift is ca..."

# Skills → .agent/skills/<id>/SKILL.md
# Native workspace skills in Antigravity
skills:
  - id: z-amend
    source: skills/z-amend/SKILL.md
    output: .agent/skills/z-amend/SKILL.md
    description: "Amend an existing z-harness plan (SPEC/PLAN/TASKS) or light-plan (FIX.md) so a change is propagated consistently across all artifacts. Preserves completed task state; adds/modifies/removes tasks as needed; optionally cross-consults if the amendmen..."
  - id: z-audit-plan
    source: skills/z-audit-plan/SKILL.md
    output: .agent/skills/z-audit-plan/SKILL.md
    description: "Audit a plan's artifacts (SPEC.md, PLAN.md, TASKS.md) before execution. Reality-checks references against the codebase, verifies best practices/design, and runs a cross-LLM adversarial review. Emits PLAN_AUDIT_REPORT.md."
  - id: z-brainstorm
    source: skills/z-brainstorm/SKILL.md
    output: .agent/skills/z-brainstorm/SKILL.md
    description: "Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan."
  - id: z-debug
    source: skills/z-debug/SKILL.md
    output: .agent/skills/z-debug/SKILL.md
    description: "Investigate a known-bad behavior with explicit repro / hypothesis / evidence / isolation phases, then ship a fix using the /z-plan-light flow, then write a post-mortem with preventative action items. Cross-LLM consult at the hypothesis stage and a..."
  - id: z-do
    source: skills/z-do/SKILL.md
    output: .agent/skills/z-do/SKILL.md
    description: "Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check
...[truncated]

Scrutinize this code rigorously. Claude is prone to over-engineering, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report only blockers and majors tied to the prior findings/acceptance. For each finding: severity (blocker / major), location, and suggested fix. Two sentences max per finding. If there are no blockers or majors, respond with exactly: `No blockers or majors found.`
codex
I’ll verify the current workspace state and patch contents against the prior findings, focusing only on acceptance-critical source/export inclusion, the seam threshold, audit-plan initialization, and generated drift.
exec
/bin/zsh -lc 'rg -n "cluster_seams (== 1|< 2)|NO_PLAN_RUN|NO_PLAN_ARCHIVE_DIR|PLAN_ROUTE_CHECK_START|planning-router|z-audit-plan" agents commands skills exports scripts z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
skills/z-brainstorm/SKILL.md:43:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-brainstorm/SKILL.md:56:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-plan-split.md:146:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan-split.md:152:- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
commands/z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
skills/z-plan-split/SKILL.md:147:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan-split/SKILL.md:153:- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
skills/z-plan-split/SKILL.md:159:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/agy/prompts/z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/z-plan-split.md:146:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-plan-split.md:152:- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
exports/agy/prompts/z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
commands/z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
commands/z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-audit-plan.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
commands/z-audit-plan.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
commands/z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-audit-plan.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
commands/z-audit-plan.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
commands/z-audit-plan.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
commands/z-audit-plan.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/agy/prompts/z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
exports/agy/prompts/z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-audit-plan.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
exports/agy/prompts/z-audit-plan.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
exports/agy/prompts/z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-audit-plan.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/agy/prompts/z-audit-plan.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/agy/prompts/z-audit-plan.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/agy/prompts/z-audit-plan.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:130:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:143:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:177:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:190:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:386:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:399:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:461:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:467:+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:473:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:491:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:502:+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:504:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:522:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:535:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:698:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:711:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:745:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:758:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:896:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:909:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:971:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:977:+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:983:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1001:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1012:+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1014:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1035:+  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1047:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1060:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1219:+  - id: z-audit-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1220:+    source: commands/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1221:+    output: .agent/workflows/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1251:+  - id: planning-router
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1252:+    source: agents/planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1253:+    output: .agent/rules/z-harness-planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1263:+  - id: z-audit-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1264:+    source: skills/z-audit-plan/SKILL.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1265:+    output: .agent/skills/z-audit-plan/SKILL.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1408:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1421:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1455:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1468:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1663:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1676:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1738:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1744:+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1750:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1768:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1779:+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1781:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1799:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1812:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1975:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1988:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2022:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2035:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2173:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2186:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2248:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2254:+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2260:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2278:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2289:+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2291:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2312:+  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2324:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2337:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2721:+## planning-router
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2753:+RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2779:+- `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2785:+Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2846:+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2855:+   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2941:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2954:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2988:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3001:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3210:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3223:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3285:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3291:+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3297:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3315:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3326:+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3328:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3346:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3359:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3643:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3656:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3697:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3710:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3926:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3939:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4001:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4007:+- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4013:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4031:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4042:+- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4044:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4062:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4075:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4210:diff --git a/agents/planning-router.md b/agents/planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4214:+++ b/agents/planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4217:+name: planning-router
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4251:+RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4277:+- `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4283:+Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4344:+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4353:+   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4370:diff --git a/commands/z-audit-plan.md b/commands/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4374:+++ b/commands/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4381:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4385:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4388:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4394:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4398:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4400:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4412:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4413:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4419:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4732:diff --git a/exports/agy/.agent/rules/z-harness-planning-router.md b/exports/agy/.agent/rules/z-harness-planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4736:+++ b/exports/agy/.agent/rules/z-harness-planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4771:+RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4797:+- `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4803:+Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4864:+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4873:+   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4890:diff --git a/exports/agy/.agent/skills/z-audit-plan/SKILL.md b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4894:+++ b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4897:+name: z-audit-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4901:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4905:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4908:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4914:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4918:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4920:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4932:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4933:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4939:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5097:diff --git a/exports/agy/.agent/workflows/z-audit-plan.md b/exports/agy/.agent/workflows/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5101:+++ b/exports/agy/.agent/workflows/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5107:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5111:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5114:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5120:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5124:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5126:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5138:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5139:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5145:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5458:diff --git a/exports/agy/prompts/planning-router.md b/exports/agy/prompts/planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5462:+++ b/exports/agy/prompts/planning-router.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5497:+RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5523:+- `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5529:+Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5590:+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5599:+   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5616:diff --git a/exports/agy/prompts/skill-z-audit-plan.md b/exports/agy/prompts/skill-z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5620:+++ b/exports/agy/prompts/skill-z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5627:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5631:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5634:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5640:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5644:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5646:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5658:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5659:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5665:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5823:diff --git a/exports/agy/prompts/z-audit-plan.md b/exports/agy/prompts/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5827:+++ b/exports/agy/prompts/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5834:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5838:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5841:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5847:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5851:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5853:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5865:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5866:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5872:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6030:diff --git a/exports/codex/prompts/z-audit-plan.md b/exports/codex/prompts/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6034:+++ b/exports/codex/prompts/z-audit-plan.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6036:+# /z-audit-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6038:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6042:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6045:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6051:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6055:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6057:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6069:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6070:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6076:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6389:diff --git a/exports/cursor/.cursor/rules/planning-router.mdc b/exports/cursor/.cursor/rules/planning-router.mdc
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6393:+++ b/exports/cursor/.cursor/rules/planning-router.mdc
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6428:+RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6454:+- `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6460:+Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6521:+   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6530:+   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6547:diff --git a/exports/cursor/.cursor/rules/z-audit-plan.mdc b/exports/cursor/.cursor/rules/z-audit-plan.mdc
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6551:+++ b/exports/cursor/.cursor/rules/z-audit-plan.mdc
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6558:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6562:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6565:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6571:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6575:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6577:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6589:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6590:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6596:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6754:diff --git a/skills/z-audit-plan/SKILL.md b/skills/z-audit-plan/SKILL.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6758:+++ b/skills/z-audit-plan/SKILL.md
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6761:+name: z-audit-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6765:+You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6769:+<!-- PLAN_ROUTE_CHECK_START -->
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6772:+Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6778:+- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6782:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6784:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6796:+   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6797:+   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6803:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
skills/z-do/SKILL.md:35:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-do/SKILL.md:48:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/z-plan.md:68:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-plan.md:79:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
exports/agy/prompts/z-plan.md:81:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-plan.md:321:  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
skills/z-research/SKILL.md:48:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-research/SKILL.md:61:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
agents/planning-router.md:2:name: planning-router
agents/planning-router.md:36:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
agents/planning-router.md:62:- `/z-audit-plan`
agents/planning-router.md:68:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
agents/planning-router.md:129:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
agents/planning-router.md:138:   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
skills/z-audit-plan/SKILL.md:2:name: z-audit-plan
skills/z-audit-plan/SKILL.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
skills/z-audit-plan/SKILL.md:10:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-audit-plan/SKILL.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
skills/z-audit-plan/SKILL.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
skills/z-audit-plan/SKILL.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
skills/z-audit-plan/SKILL.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
skills/z-audit-plan/SKILL.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
skills/z-audit-plan/SKILL.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
skills/z-audit-plan/SKILL.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
skills/z-plan-light/SKILL.md:39:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan-light/SKILL.md:52:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
commands/z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/planning-router.md:34:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
exports/agy/prompts/planning-router.md:60:- `/z-audit-plan`
exports/agy/prompts/planning-router.md:66:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
exports/agy/prompts/planning-router.md:127:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
exports/agy/prompts/planning-router.md:136:   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
skills/z-plan/SKILL.md:61:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan/SKILL.md:72:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
skills/z-plan/SKILL.md:74:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/skill-z-plan.md:60:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-plan.md:71:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
exports/agy/prompts/skill-z-plan.md:73:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
commands/z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/skill-z-plan-split.md:146:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-plan-split.md:152:- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
exports/agy/prompts/skill-z-plan-split.md:158:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
commands/z-plan.md:68:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan.md:79:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
commands/z-plan.md:81:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
commands/z-plan.md:321:  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
exports/agy/prompts/skill-z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/agy-plugin.yaml:18:  - id: z-audit-plan
exports/agy/agy-plugin.yaml:19:    source: commands/z-audit-plan.md
exports/agy/agy-plugin.yaml:20:    output: .agent/workflows/z-audit-plan.md
exports/agy/agy-plugin.yaml:172:  - id: planning-router
exports/agy/agy-plugin.yaml:173:    source: agents/planning-router.md
exports/agy/agy-plugin.yaml:174:    output: .agent/rules/z-harness-planning-router.md
exports/agy/agy-plugin.yaml:200:  - id: z-audit-plan
exports/agy/agy-plugin.yaml:201:    source: skills/z-audit-plan/SKILL.md
exports/agy/agy-plugin.yaml:202:    output: .agent/skills/z-audit-plan/SKILL.md
exports/codex/AGENTS.md:1726:## planning-router
exports/codex/AGENTS.md:1758:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
exports/codex/AGENTS.md:1784:- `/z-audit-plan`
exports/codex/AGENTS.md:1790:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
exports/codex/AGENTS.md:1851:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
exports/codex/AGENTS.md:1860:   - If `cluster_seams < 2`, recommend `/z-plan` with `too_few_clusters`.
exports/agy/prompts/skill-z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
exports/agy/prompts/skill-z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-audit-plan.md:13:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
exports/agy/prompts/skill-z-audit-plan.md:19:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
exports/agy/prompts/skill-z-audit-plan.md:23:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/skill-z-audit-plan.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/agy/prompts/skill-z-audit-plan.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/agy/prompts/skill-z-audit-plan.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/agy/prompts/skill-z-audit-plan.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/agy/prompts/skill-z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-plan-light.md:51:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/skill-z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/skill-z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-do.md:47:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/agy/prompts/z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-brainstorm.md:55:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/agy/prompts/z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
exports/agy/prompts/z-research.md:60:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-plan-split.md:143:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-plan-split.md:149:- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
exports/codex/prompts/z-plan-split.md:155:Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
exports/codex/prompts/z-plan.md:57:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-plan.md:68:- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.
exports/codex/prompts/z-plan.md:70:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-audit-plan.md:1:# /z-audit-plan
exports/codex/prompts/z-audit-plan.md:3:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
exports/codex/prompts/z-audit-plan.md:7:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-audit-plan.md:10:Run this route check during setup before any audit phase starts, and after the final report only as a contextual next-action gate. `/z-audit-plan` is not a front-door planning command; it is valid only when plan artifacts exist.
exports/codex/prompts/z-audit-plan.md:16:- If all plan artifacts exist, stay in `/z-audit-plan` and audit read-only.
exports/codex/prompts/z-audit-plan.md:20:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-audit-plan.md:22:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/codex/prompts/z-audit-plan.md:34:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/codex/prompts/z-audit-plan.md:35:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/codex/prompts/z-audit-plan.md:41:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/codex/prompts/z-do.md:31:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-do.md:44:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
exports/codex/prompts/z-brainstorm.md:39:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-brainstorm.md:52:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-research.md:44:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-research.md:57:Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
exports/codex/prompts/z-plan-light.md:35:<!-- PLAN_ROUTE_CHECK_START -->
exports/codex/prompts/z-plan-light.md:48:Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.

exec
/bin/zsh -lc 'git diff --name-only -- commands agents skills exports scripts | sort' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'git status --short && git diff --name-status -- && git ls-files --others --exclude-standard' in /Users/zeke/dev/z-harness
 succeeded in 113ms:
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

 succeeded in 149ms:
M	README.md
M	agents/consultant-primary.md
M	agents/consultant-secondary.md
A	agents/external-lookup.md
M	agents/implementer.md
M	agents/reviewer.md
M	commands/z-audit.md
M	commands/z-brainstorm.md
M	commands/z-do.md
M	commands/z-implement-all.md
M	commands/z-mr-review.md
M	commands/z-plan-light.md
M	commands/z-plan-split.md
M	commands/z-plan.md
M	commands/z-research.md
M	commands/z-review-all.md
A	docs/human/LIVENESS.md
M	docs/human/agents.md
M	docs/human/commands.md
A	docs/human/lookup-contract.md
M	docs/human/skills.md
M	docs/llm/INDEX.json
M	docs/llm/agents.json
M	docs/llm/commands.json
A	docs/llm/external-lookup-agent.json
A	docs/llm/lookup-contract.json
M	docs/llm/skills.json
M	exports/agy/.agent/rules/z-harness-consultant-primary.md
M	exports/agy/.agent/rules/z-harness-consultant-secondary.md
M	exports/agy/.agent/rules/z-harness-implementer.md
M	exports/agy/.agent/rules/z-harness-reviewer.md
M	exports/agy/.agent/skills/z-amend/SKILL.md
M	exports/agy/.agent/skills/z-brainstorm/SKILL.md
M	exports/agy/.agent/skills/z-do/SKILL.md
M	exports/agy/.agent/skills/z-implement-all/SKILL.md
M	exports/agy/.agent/skills/z-plan-light/SKILL.md
M	exports/agy/.agent/skills/z-plan-split/SKILL.md
M	exports/agy/.agent/skills/z-plan/SKILL.md
M	exports/agy/.agent/skills/z-research/SKILL.md
M	exports/agy/.agent/skills/z-review-all/SKILL.md
M	exports/agy/.agent/workflows/z-audit.md
M	exports/agy/.agent/workflows/z-brainstorm.md
M	exports/agy/.agent/workflows/z-do.md
M	exports/agy/.agent/workflows/z-implement-all.md
M	exports/agy/.agent/workflows/z-mr-review.md
M	exports/agy/.agent/workflows/z-plan-light.md
M	exports/agy/.agent/workflows/z-plan-split.md
M	exports/agy/.agent/workflows/z-plan.md
M	exports/agy/.agent/workflows/z-research.md
M	exports/agy/.agent/workflows/z-review-all.md
M	exports/agy/agy-plugin.yaml
M	exports/agy/prompts/consultant-primary.md
M	exports/agy/prompts/consultant-secondary.md
M	exports/agy/prompts/implementer.md
M	exports/agy/prompts/reviewer.md
M	exports/agy/prompts/skill-z-amend.md
M	exports/agy/prompts/skill-z-brainstorm.md
M	exports/agy/prompts/skill-z-do.md
M	exports/agy/prompts/skill-z-implement-all.md
M	exports/agy/prompts/skill-z-plan-light.md
M	exports/agy/prompts/skill-z-plan-split.md
M	exports/agy/prompts/skill-z-plan.md
M	exports/agy/prompts/skill-z-research.md
M	exports/agy/prompts/skill-z-review-all.md
M	exports/agy/prompts/z-audit.md
M	exports/agy/prompts/z-brainstorm.md
M	exports/agy/prompts/z-do.md
M	exports/agy/prompts/z-implement-all.md
M	exports/agy/prompts/z-mr-review.md
M	exports/agy/prompts/z-plan-light.md
M	exports/agy/prompts/z-plan-split.md
M	exports/agy/prompts/z-plan.md
M	exports/agy/prompts/z-research.md
M	exports/agy/prompts/z-review-all.md
M	exports/codex/AGENTS.md
M	exports/codex/prompts/z-amend.md
M	exports/codex/prompts/z-audit.md
M	exports/codex/prompts/z-brainstorm.md
M	exports/codex/prompts/z-do.md
M	exports/codex/prompts/z-implement-all.md
M	exports/codex/prompts/z-mr-review.md
M	exports/codex/prompts/z-plan-light.md
M	exports/codex/prompts/z-plan-split.md
M	exports/codex/prompts/z-plan.md
M	exports/codex/prompts/z-research.md
M	exports/codex/prompts/z-review-all.md
M	exports/cursor/.cursor/rules/consultant-primary.mdc
M	exports/cursor/.cursor/rules/consultant-secondary.mdc
M	exports/cursor/.cursor/rules/implementer.mdc
M	exports/cursor/.cursor/rules/reviewer.mdc
M	exports/cursor/.cursor/rules/z-amend.mdc
M	exports/cursor/.cursor/rules/z-audit.mdc
M	exports/cursor/.cursor/rules/z-brainstorm.mdc
M	exports/cursor/.cursor/rules/z-do.mdc
M	exports/cursor/.cursor/rules/z-implement-all.mdc
M	exports/cursor/.cursor/rules/z-mr-review.mdc
M	exports/cursor/.cursor/rules/z-plan-light.mdc
M	exports/cursor/.cursor/rules/z-plan-split.mdc
M	exports/cursor/.cursor/rules/z-plan.mdc
M	exports/cursor/.cursor/rules/z-research.mdc
M	exports/cursor/.cursor/rules/z-review-all.mdc
A	scripts/check-timeout.sh
A	scripts/liveness.sh
M	skills/z-amend/SKILL.md
M	skills/z-brainstorm/SKILL.md
M	skills/z-debug/SKILL.md
M	skills/z-do/SKILL.md
M	skills/z-implement-all/SKILL.md
M	skills/z-improve/SKILL.md
M	skills/z-plan-light/SKILL.md
M	skills/z-plan-split/SKILL.md
M	skills/z-plan/SKILL.md
M	skills/z-research/SKILL.md
M	skills/z-review-all/SKILL.md
M	z-harness/archive/docs/events.jsonl
M	z-harness/archive/orchestration/events.jsonl
M	z-harness/archive/tasks/T001/events.jsonl
M	z-harness/archive/tasks/T001/review.prompt.md
M	z-harness/archive/tasks/T001/review.response.md
M	z-harness/archive/tasks/T002/events.jsonl
M	z-harness/archive/tasks/T003/review.prompt.md
M	z-harness/archive/tasks/T003/review.response.md
M	z-harness/archive/tasks/T006/review.prompt.md
M	z-harness/archive/tasks/T006/review.response.md
A	z-harness/lookup-cache/.gitignore
M	z-harness/metrics.jsonl
A	z-harness/plans/lookup-subagent/staging/qt-market-lookup.md
.agent/rules/z-harness-auditor.md
.agent/rules/z-harness-cluster-planner.md
.agent/rules/z-harness-complexity-classifier.md
.agent/rules/z-harness-consultant-primary.md
.agent/rules/z-harness-consultant-secondary.md
.agent/rules/z-harness-doc-fetcher.md
.agent/rules/z-harness-doc-updater.md
.agent/rules/z-harness-external-lookup.md
.agent/rules/z-harness-implementer.md
.agent/rules/z-harness-mr-reviewer.md
.agent/rules/z-harness-remote-runner.md
.agent/rules/z-harness-reviewer.md
.agent/rules/z-harness-spec-precheck.md
.agent/skills/z-amend/SKILL.md
.agent/skills/z-audit-plan/SKILL.md
.agent/skills/z-brainstorm/SKILL.md
.agent/skills/z-debug/SKILL.md
.agent/skills/z-do/SKILL.md
.agent/skills/z-implement-all/SKILL.md
.agent/skills/z-implement-next/SKILL.md
.agent/skills/z-improve/SKILL.md
.agent/skills/z-init-docs/SKILL.md
.agent/skills/z-maintain-docs/SKILL.md
.agent/skills/z-plan-light/SKILL.md
.agent/skills/z-plan-split/SKILL.md
.agent/skills/z-plan/SKILL.md
.agent/skills/z-research/SKILL.md
.agent/skills/z-review-all/SKILL.md
.agent/skills/z-stats/SKILL.md
.agent/skills/z-suggest-memory/SKILL.md
.agent/skills/z-test/SKILL.md
.agent/workflows/z-amend.md
.agent/workflows/z-audit-plan.md
.agent/workflows/z-audit.md
.agent/workflows/z-brainstorm.md
.agent/workflows/z-debug.md
.agent/workflows/z-do.md
.agent/workflows/z-export.md
.agent/workflows/z-fix.md
.agent/workflows/z-implement-all.md
.agent/workflows/z-implement-next.md
.agent/workflows/z-improve.md
.agent/workflows/z-init-docs.md
.agent/workflows/z-maintain-docs.md
.agent/workflows/z-mr-review.md
.agent/workflows/z-plan-light.md
.agent/workflows/z-plan-split.md
.agent/workflows/z-plan.md
.agent/workflows/z-providers-discover.md
.agent/workflows/z-research.md
.agent/workflows/z-review-all.md
.agent/workflows/z-skill-fix.md
.agent/workflows/z-stats.md
.agent/workflows/z-style-init.md
.agent/workflows/z-suggest-memory.md
.agent/workflows/z-test.md
.agent/workflows/z-update.md
agents/planning-router.md
commands/z-audit-plan.md
exports/agy/.agent/rules/z-harness-external-lookup.md
exports/agy/.agent/rules/z-harness-planning-router.md
exports/agy/.agent/skills/z-audit-plan/SKILL.md
exports/agy/.agent/workflows/z-audit-plan.md
exports/agy/prompts/external-lookup.md
exports/agy/prompts/planning-router.md
exports/agy/prompts/skill-z-audit-plan.md
exports/agy/prompts/z-audit-plan.md
exports/codex/prompts/z-audit-plan.md
exports/cursor/.cursor/rules/external-lookup.mdc
exports/cursor/.cursor/rules/planning-router.mdc
exports/cursor/.cursor/rules/z-audit-plan.mdc
skills/z-audit-plan/SKILL.md
z-harness/archive/20260524T184104Z-lookup-subagent/events.jsonl
z-harness/archive/20260524T184351Z-lookup-subagent/events.jsonl
z-harness/archive/20260524T184351Z-lookup-subagent/transcripts/001-gemini-brainstorm.prompt.md
z-harness/archive/20260524T184351Z-lookup-subagent/transcripts/001-gemini-brainstorm.response.md
z-harness/archive/20260524T190609Z-lookup-subagent/events.jsonl
z-harness/archive/20260524T201705Z-review/events.jsonl
z-harness/archive/20260524T203829Z-subagent-liveness/events.jsonl
z-harness/archive/20260524T203829Z-subagent-liveness/transcripts/001-gemini-plan-review.prompt.md
z-harness/archive/20260524T203829Z-subagent-liveness/transcripts/001-gemini-plan-review.response.md
z-harness/archive/20260524T203829Z-subagent-liveness/transcripts/003-gemini-plan-review.prompt.md
z-harness/archive/20260524T203829Z-subagent-liveness/transcripts/003-gemini-plan-review.response.md
z-harness/archive/20260525T000302Z-compaction-cadence/events.jsonl
z-harness/archive/20260525T000302Z-compaction-cadence/transcripts/001-gemini-bundled-decisions.prompt.md
z-harness/archive/20260525T000302Z-compaction-cadence/transcripts/001-gemini-bundled-decisions.response.md
z-harness/archive/compaction-cadence-plan-critique/transcripts/001-codex-plan-review.prompt.md
z-harness/archive/compaction-cadence-plan-critique/transcripts/001-codex-plan-review.response.md
z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.prompt.md
z-harness/archive/compaction-cadence/transcripts/001-codex-light-fix.response.md
z-harness/archive/consult-lookup-architecture/events.jsonl
z-harness/archive/consult-lookup-architecture/transcripts/001-codex-bundled-decisions.prompt.md
z-harness/archive/consult-lookup-architecture/transcripts/001-codex-bundled-decisions.response.md
z-harness/archive/consult-lookup-architecture/transcripts/003-gemini-bundled-decisions.prompt.md
z-harness/archive/consult-lookup-architecture/transcripts/003-gemini-bundled-decisions.response.md
z-harness/archive/consultant-review/transcripts/001-gemini-plan-review.prompt.md
z-harness/archive/consultant-review/transcripts/001-gemini-plan-review.response.md
z-harness/archive/consults/20260524T203829Z-subagent-liveness/codex-light-fix.prompt.md
z-harness/archive/consults/20260524T203829Z-subagent-liveness/codex-light-fix.response.md
z-harness/archive/consults/lookup-subagent-review/transcripts/001-gemini-plan-review.prompt.md
z-harness/archive/consults/lookup-subagent-review/transcripts/001-gemini-plan-review.response.md
z-harness/archive/consults/transcripts/001-gemini-brainstorm.prompt.md
z-harness/archive/consults/transcripts/001-gemini-brainstorm.response.md
z-harness/archive/consults/transcripts/003-gemini-brainstorm.prompt.md
z-harness/archive/consults/transcripts/003-gemini-brainstorm.response.md
z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.human.md
z-harness/archive/docs/20260524T235238Z-docs/proposed/agents.llm.json
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.human.md
z-harness/archive/docs/20260524T235238Z-docs/proposed/skills.llm.json
z-harness/archive/lookup-subagent-brainstorm/transcripts/001-codex-brainstorm.prompt.md
z-harness/archive/lookup-subagent-brainstorm/transcripts/001-codex-brainstorm.response.md
z-harness/archive/lookup-subagent-review/transcripts/001-codex-review.prompt.md
z-harness/archive/lookup-subagent-review/transcripts/001-codex-review.response.md
z-harness/archive/plan-bail-router/transcripts/001-codex-bundled-decisions.prompt.md
z-harness/archive/plan-bail-router/transcripts/001-codex-bundled-decisions.response.md
z-harness/archive/plan-bail-router/transcripts/003-codex-plan-review.prompt.md
z-harness/archive/plan-bail-router/transcripts/003-codex-plan-review.response.md
z-harness/archive/tasks/T002/review.prompt.md
z-harness/archive/tasks/T002/review.response.md
z-harness/archive/tasks/T004/review.prompt.md
z-harness/archive/tasks/T004/review.response.md
z-harness/archive/tasks/T005/review.prompt.md
z-harness/archive/tasks/T005/review.response.md
z-harness/archive/tasks/T006/review.return.md
z-harness/archive/tasks/subagent-liveness/events.jsonl
z-harness/archive/tasks/subagent-liveness/review.findings.md
z-harness/archive/tasks/subagent-liveness/review.prompt.md
z-harness/archive/tasks/subagent-liveness/review.response.md
z-harness/archive/tasks/subagent-liveness/v4-findings.md
z-harness/archive/unified-review-tasks/transcripts/001-codex-brainstorm.prompt.md
z-harness/archive/unified-review-tasks/transcripts/001-codex-brainstorm.response.md
z-harness/plan-variant-bail-routing/.latest-run
z-harness/plan-variant-bail-routing/archive/20260524T214409Z-plan-variant-bail-routing/events.jsonl
z-harness/plan-variant-bail-routing/archive/20260524T214409Z-plan-variant-bail-routing/phase1-context.md
z-harness/plan-variant-bail-routing/escalation.md
z-harness/plans/compaction-cadence/PLAN.md
z-harness/plans/compaction-cadence/SPEC.md
z-harness/plans/compaction-cadence/TASKS.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/.providers-logged
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/PLAN.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/SPEC.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/TASKS.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/decisions.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/events.jsonl
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/manifest.json
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase0-premise.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase1-context.md
z-harness/plans/compaction-cadence/archive/20260525T000302Z-compaction-cadence/phase3-decisions-final.md
z-harness/plans/compaction-cadence/archive/20260525T003141Z-implement/.providers-logged
z-harness/plans/compaction-cadence/archive/orchestration/events.jsonl
z-harness/plans/compaction-cadence/archive/tasks/T001/diff.patch
z-harness/plans/compaction-cadence/archive/tasks/T001/review.prompt.md
z-harness/plans/compaction-cadence/archive/tasks/T001/review.response.md
z-harness/plans/compaction-cadence/archive/unknown-run/events.jsonl
z-harness/plans/finding-promotion-policy/archive/20260524T210631Z-unified-review-tasks/events.jsonl
z-harness/plans/finding-promotion-policy/archive/20260524T211701Z-finding-promotion-policy/events.jsonl
z-harness/plans/finding-promotion-policy/archive/20260524T211701Z-finding-promotion-policy/phase1-context.md
z-harness/plans/finding-promotion-policy/escalation.md
z-harness/plans/lookup-subagent/BRAINSTORM.md
z-harness/plans/lookup-subagent/PLAN.md
z-harness/plans/lookup-subagent/SPEC.md
z-harness/plans/lookup-subagent/TASKS.md
z-harness/plans/lookup-subagent/archive/20260524T184104Z-lookup-subagent/events.jsonl
z-harness/plans/lookup-subagent/archive/20260524T184104Z-lookup-subagent/phase1-scaffolding.md
z-harness/plans/lookup-subagent/archive/20260524T184351Z-lookup-subagent/phase1-scaffolding.md
z-harness/plans/lookup-subagent/archive/20260524T184351Z-lookup-subagent/transcripts/claude-raw.txt
z-harness/plans/lookup-subagent/archive/20260524T184351Z-lookup-subagent/transcripts/codex-raw.txt
z-harness/plans/lookup-subagent/archive/20260524T184351Z-lookup-subagent/transcripts/gemini-raw.txt
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/PLAN.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/SPEC.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/TASKS.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/decisions.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/events.jsonl
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/manifest.json
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/phase0-premise.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/phase1-context.md
z-harness/plans/lookup-subagent/archive/20260524T190609Z-lookup-subagent/phase3-decisions-final.md
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/cumulative.diff
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/cumulative.stat
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/events.jsonl
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/findings.md
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/shipped.md
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/transcripts/001-codex-final-review.prompt.md
z-harness/plans/lookup-subagent/archive/20260524T201705Z-review/transcripts/001-codex-final-review.response.md
z-harness/plans/lookup-subagent/archive/orchestration/events.jsonl
z-harness/plans/lookup-subagent/archive/tasks/T001/diff.patch
z-harness/plans/lookup-subagent/archive/tasks/T002/diff.patch
z-harness/plans/lookup-subagent/archive/tasks/T003/diff.patch
z-harness/plans/lookup-subagent/archive/tasks/T009/SUMMARY.md
z-harness/plans/plan-bail-router/.latest-run
z-harness/plans/plan-bail-router/PLAN.md
z-harness/plans/plan-bail-router/SPEC.md
z-harness/plans/plan-bail-router/TASKS.md
z-harness/plans/plan-bail-router/archive/20260524T203829Z-subagent-liveness/events.jsonl
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/.providers-logged
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/PLAN.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/TASKS.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/decisions.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/events.jsonl
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/manifest.json
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/phase0-premise.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/phase1-context.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/phase3-decisions-final.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/transcripts/001-gemini-bundled-decisions.prompt.md
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/transcripts/001-gemini-bundled-decisions.response.md
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/amendment.md
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/events.jsonl
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/PLAN.md.diff
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff
z-harness/plans/plan-bail-router/archive/orchestration/events.jsonl
z-harness/plans/plan-bail-router/archive/plan-bail-router/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T001/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v2.patch
z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v3.patch
z-harness/plans/plan-bail-router/archive/tasks/T001/delta-v4.patch
z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v1.patch
z-harness/plans/plan-bail-router/archive/tasks/T001/diff-v3.patch
z-harness/plans/plan-bail-router/archive/tasks/T001/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T001/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T001/review.prompt.md
z-harness/plans/plan-bail-router/archive/tasks/T001/review.response.md
z-harness/plans/plan-bail-router/archive/tasks/T002/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T002/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T002/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md
z-harness/plans/plan-bail-router/archive/tasks/T003/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T003/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md
z-harness/plans/plan-bail-router/archive/tasks/T004/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T004/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T004/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T005/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T005/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T006/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md
z-harness/plans/plan-bail-router/archive/tasks/T006/review.return.md
z-harness/plans/plan-bail-router/archive/unknown-run/events.jsonl
z-harness/plans/subagent-liveness/FIX.md
z-harness/plans/subagent-liveness/archive/.last-run
z-harness/plans/subagent-liveness/archive/20260524T203829Z-subagent-liveness/diff.patch
z-harness/plans/subagent-liveness/archive/20260524T203829Z-subagent-liveness/events.jsonl
z-harness/plans/subagent-liveness/archive/20260524T203829Z-subagent-liveness/phase1-context.md
z-harness/plans/unified-review-tasks/archive/consults/events.jsonl
z-harness/plans/unified-review-tasks/archive/unified-review-tasks/events.jsonl
z-harness/plans/z-audit-plan/PLAN.md
z-harness/plans/z-audit-plan/SPEC.md
z-harness/plans/z-audit-plan/TASKS.md
z-harness/unified-review-tasks/BRAINSTORM.md
z-harness/unified-review-tasks/archive/20260524T210631Z-unified-review-tasks/events.jsonl
z-harness/unified-review-tasks/archive/20260524T210631Z-unified-review-tasks/phase1-scaffolding.md

codex
The key prior fixes are present in the checked files: `planning-router` uses `< 2`, and `/z-audit-plan` now has a pre-discovery no-plan archive branch in source plus exports. I’m checking whether the export acceptance actually holds and whether the generated patch still omits required files.
exec
/bin/zsh -lc 'python3 scripts/export-codex.py' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'python3 scripts/export-cursor.py' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'python3 scripts/export-agy.py' in /Users/zeke/dev/z-harness
 succeeded in 259ms:
export-codex: emitted 44 prompt files to /Users/zeke/dev/z-harness/exports/codex/prompts
  AGENTS.md written to /Users/zeke/dev/z-harness/exports/codex/AGENTS.md
  all 44 prompt files passed validation.

 succeeded in 260ms:
export-cursor: emitted 58 .mdc files to /Users/zeke/dev/z-harness/exports/cursor/.cursor/rules
  all 58 files passed validation.

 succeeded in 282ms:
export-agy: emitted 26 workflows, 14 rules, 18 skills, 58 prompts to /Users/zeke/dev/z-harness/exports/agy
  agy-plugin.yaml: /Users/zeke/dev/z-harness/exports/agy/agy-plugin.yaml
  CAPABILITIES.md: /Users/zeke/dev/z-harness/exports/agy/CAPABILITIES.md
  README.md:       /Users/zeke/dev/z-harness/exports/agy/README.md
  all 116 prompt/workflow/rule/skill/ files passed validation.

exec
/bin/zsh -lc "rg -n \"cluster_seams == 1|\\"'$BASE/archive/'"\\"'$RUN/route-decision|NO_PLAN_ARCHIVE_DIR|NO_PLAN_RUN" agents/planning-router.md commands/z-audit-plan.md skills/z-audit-plan/SKILL.md exports/codex/AGENTS.md exports/codex/prompts/z-audit-plan.md exports/cursor/.cursor/rules/planning-router.mdc exports/cursor/.cursor/rules/z-audit-plan.mdc exports/agy/.agent/rules/z-harness-planning-router.md exports/agy/.agent/workflows/z-audit-plan.md exports/agy/.agent/skills/z-audit-plan/SKILL.md exports/agy/prompts/planning-router.md exports/agy/prompts/z-audit-plan.md exports/agy/prompts/skill-z-audit-plan.md' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
exports/codex/prompts/z-audit-plan.md:22:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/codex/prompts/z-audit-plan.md:34:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/codex/prompts/z-audit-plan.md:35:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/codex/prompts/z-audit-plan.md:41:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/agy/prompts/skill-z-audit-plan.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/agy/prompts/skill-z-audit-plan.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/agy/prompts/skill-z-audit-plan.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/agy/prompts/skill-z-audit-plan.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/agy/prompts/z-audit-plan.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/agy/prompts/z-audit-plan.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/agy/prompts/z-audit-plan.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/agy/prompts/z-audit-plan.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/cursor/.cursor/rules/z-audit-plan.mdc:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/cursor/.cursor/rules/z-audit-plan.mdc:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/cursor/.cursor/rules/z-audit-plan.mdc:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/cursor/.cursor/rules/z-audit-plan.mdc:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
skills/z-audit-plan/SKILL.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
skills/z-audit-plan/SKILL.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
skills/z-audit-plan/SKILL.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
skills/z-audit-plan/SKILL.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/agy/.agent/workflows/z-audit-plan.md:24:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/agy/.agent/workflows/z-audit-plan.md:36:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/agy/.agent/workflows/z-audit-plan.md:37:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/agy/.agent/workflows/z-audit-plan.md:43:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
commands/z-audit-plan.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
commands/z-audit-plan.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
commands/z-audit-plan.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
commands/z-audit-plan.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
exports/agy/.agent/skills/z-audit-plan/SKILL.md:25:If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
exports/agy/.agent/skills/z-audit-plan/SKILL.md:37:   NO_PLAN_RUN=$(date -u +%Y%m%dT%H%M%SZ)-audit-plan-no-plan
exports/agy/.agent/skills/z-audit-plan/SKILL.md:38:   NO_PLAN_ARCHIVE_DIR="z-harness/archive/$NO_PLAN_RUN"
exports/agy/.agent/skills/z-audit-plan/SKILL.md:44:   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.

exec
/bin/zsh -lc "printf '%s
' agents/planning-router.md commands/z-audit-plan.md skills/z-audit-plan/SKILL.md exports/agy/.agent/rules/z-harness-planning-router.md exports/agy/.agent/skills/z-audit-plan/SKILL.md exports/agy/.agent/workflows/z-audit-plan.md exports/agy/prompts/planning-router.md exports/agy/prompts/skill-z-audit-plan.md exports/agy/prompts/z-audit-plan.md exports/codex/prompts/z-audit-plan.md exports/cursor/.cursor/rules/planning-router.mdc exports/cursor/.cursor/rules/z-audit-plan.mdc | while read f; do if rg -q \""'^diff --git a/${f//./'"\\.} b/"'${f//./'"\\.}\" z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch; then echo \"present "'$f"; else echo "MISSING $f"; fi; done' in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'for f in commands/z-do.md commands/z-plan-light.md commands/z-plan.md commands/z-plan-split.md commands/z-brainstorm.md commands/z-research.md commands/z-audit-plan.md skills/z-do/SKILL.md skills/z-plan-light/SKILL.md skills/z-plan/SKILL.md skills/z-plan-split/SKILL.md skills/z-brainstorm/SKILL.md skills/z-research/SKILL.md skills/z-audit-plan/SKILL.md; do c=$(rg -c "PLAN_ROUTE_CHECK_START" "$f" || true); echo "$c $f"; done' in /Users/zeke/dev/z-harness
 succeeded in 134ms:
present exports/agy/prompts/planning-router.md
present exports/agy/prompts/skill-z-audit-plan.md
present exports/agy/prompts/z-audit-plan.md
present exports/codex/prompts/z-audit-plan.md
present exports/cursor/.cursor/rules/planning-router.mdc
present exports/cursor/.cursor/rules/z-audit-plan.mdc

 succeeded in 142ms:
1 skills/z-do/SKILL.md
1 skills/z-plan-light/SKILL.md
1 skills/z-plan/SKILL.md
1 skills/z-plan-split/SKILL.md
1 skills/z-brainstorm/SKILL.md
1 skills/z-research/SKILL.md
1 skills/z-audit-plan/SKILL.md

codex
No blockers or majors found.
tokens used
114,392
No blockers or majors found.
