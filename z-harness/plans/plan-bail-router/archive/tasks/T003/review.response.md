2026-05-25T00:17:08.568816Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-25T00:17:08.568841Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-25T00:17:08.568843Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5c7e-19ae-70f3-a1dd-6be6c15fd251
--------
user
You are reviewing code that Claude just wrote for task T003: Add route check to full and split planning paths.

Review for blockers/majors against acceptance and SPEC only.

Spec (excerpt):
# Spec: Plan Bail Router

## Overview

Add a shared routing policy for the z-harness planning family so each entry point can detect when a different workflow is a better fit, write a route artifact, log structured telemetry, and present a user-gated handoff. The change is planning-only: no command should automatically execute another command in v1.

## Planning Inputs

none - fresh /z-plan run.

## Definitions

### Primary Route Matrix

The primary matrix covers commands that represent different planning depths or pre-planning modes:

- `/z-do`
- `/z-plan-light`
- `/z-plan`
- `/z-plan-split`
- `/z-brainstorm`
- `/z-research`

### Contextual Exits

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

Existing command-specific escalation flows must be updated, not duplicated. If a command already writes `escalation.md` or emits a command-specific escalation event, the implementation should either:

- replace the old user-facing escalation block with `route-decision.md` plus `plan_route_decision`, while preserving the legacy terminal/run-end event; or
- make `escalation.md` a compatibility copy or pointer to `route-decision.md`.

Do not leave two independent prompt blocks that can disagree about the next command.

### Route Artifact

Each route artifact is Markdown and lives at one of:

- `$CURRENT_ARCHIVE_DIR/route-decision.md`, where `$CURRENT_ARCHIVE_DIR` is the archive directory the command already created for this run.
- For plan-backed commands: `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`.
- For `/z-do`: `z-harness/adhoc/archive/$RUN/route-decision.md`.
- For `/z-audit-plan`: `$BASE/archive/$RUN/route-decision.md`, where `$BASE=$Z_HARNESS_PLAN_DIR`.

Commands should define `$CURRENT_ARCHIVE_DIR` in setup immediately after creating the run archive and use it in route instructions.

Required content:

```markdown
# Route Decision: <from-command> -> <to-command>

## Recommendation

Run `<exact command invocation>`.

## Reason

<short explanation>

## Signals

- <signal>: <value>

## Route Chain

1. <prior from> -> <prior to> (<reason>)
2. <from-command> -> <to-command> (<reason>)

## Resume Context

<what the next command should know>
```

### Telemetry

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

Stable `reason_codes`:

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

## Deterministic Signals

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

## Route Thresholds

Default route recommendations:

| Signal pattern | Target | Notes |
|---|---|---|
| Implementation task, `candidate_files <= 3`, no non-obvious decisions, no cross-module impact | `/z-do` | Tiny direct execution with review gate. |
| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
| Coherent medium feature/change, `expected_tasks <= 25`, no obvious cluster split | `/z-plan` | Produces `SPEC.md`, `PLAN.md`, `TASKS.md`. |
| Very large topic, `expected_tasks > 25` or `cluster_seams` in `2..6` and each seam is independently plannable | `/z-plan-split` | Produces a plan tree. |
| Unknown terrain, missing citations, or source facts must be mapped before deciding approach | `/z-research` | Produces `RESEARCH.md`; no recommendations. |
| Multiple plausible approach framings and terrain is sufficiently known | `/z-brainstorm` | Produces `BRAINSTORM.md`. |
| Existing `SPEC.md`/`PLAN.md`/`TASKS.md` need validation before implementation | `/z-audit-plan` | Contextual only. |
| Existing plan needs changed scope or decisions | `/z-amend` | Contextual only. |
| Concrete bug diagnosis exists | `/z-fix` | Contextual only. |
| Bug symptom exists but diagnosis is unknown | `/z-debug` | Contextual only. |
| Docs are stale above threshold or drift materially affects planning | `/z-maintain-docs` | Contextual only. |

When deterministic signals conflict:

- If confidence is high that the current command is too light, route upward.
- If confidence is high that the current command is too heavy, recommend the lighter command only before any expensive phase or artifact write.
- If confidence is medium, use `planning-router` if available.
- If confidence is low, ask the user to choose from the top two targets.

`planning-router` is used only when all are true:

- the route check has already collected a compact signal payload;
- no hard command threshold already mandates a route or refusal;
- the top two plausible targets are both reasonable;
- the command has not already used `planning-router` for the same `reason_codes` in this run.

## Loop Prevention

Route artifacts and prompts must carry a route chain when re-invoking a recommended command.

Rules:

- The source of truth is `route_chain` from the latest `route-decision.md` passed in the current prompt or discovered in the active run archive.
- If no route artifact is present, the chain is empty.
- If `route_chain` contains two prior entries, do not route again. Ask the user to choose one command explicitly.
- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
- If the user chooses `continue`, log the override and do not route again for the same `reason_codes` in the same run.

## AskUser Handoff Gate

Default options:

- `Switch to <recommended command>` - current command writes the route artifact, logs `user_choice: "switch"`, and stops with the exact invocation.
- `Continue here` - available only when the current command's hard thresholds do not forbid continuation. Logs `user_choice: "continue"`.
- `Abandon` - current command logs `user_choice: "abandon"` and ends cleanly.

For hard-refusal branches, such as `/z-plan-split` with fewer than two cluster seams, the command may skip the AskUser gate and emit `user_choice: "not_asked"` if it already has a mandatory terminal exit.

`Switch to <recommended command>` means present the exact next command invocation and stop the current command. It does not execute the next command.

## Route Check Insertion Points

Each command should run route checks at predictable points:

- `/z-do`: after premise/doc grounding and before approach.md; again before implementation if file count or decisions grew.
- `/z-plan-light`: after quick exploration and before Phase 2 decision selection; again before inline implementation if scope grows.
- `/z-plan`: after setup/precontext/docs gates and before Phase 1 Explore; again after decisions if task count/scope implies split.
- `/z-plan-split`: after cluster proposal, before user confirmation; route too-few clusters to `/z-plan`, too-uncertain seams to `/z-research`.
- `/z-brainstorm`: after scaffolding and before ideator dispatch; route to `/z-research` if terrain is unknown or to `/z-plan` if framing is already clear.
- `/z-research`: before cost gate if the request is clearly not research; after finalization only as next-step recommendation. Never inside `RESEARCH.md` findings.
- `/z-audit-plan`: during setup if no plan artifacts are found; after final report when presenting action choices.

## `planning-router` Agent

Add `agents/planning-router.md`.

Frontmatter:

```yaml
---
name: planning-router
description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
tools: Read, Grep, Glob
model: haiku
---
```

Inputs:

- `current_command`
- `task_or_topic`
- `signals_json`
- `route_chain_json`
- `repo_root`
- optional `existing_artifacts`

Return shape:

```text
STATUS: routed | ask_user | bad_input
RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
ROUTE_CLASS: primary | contextual | none
CONFIDENCE: high | medium | low
REASON_CODES: <comma-separated stable reason codes>
REASON: <one line, <=160 chars>
```

`STATUS: routed` requires `RECOMMENDED` to be a concrete command and `ROUTE_CLASS` to be `primary` or `contextual`. `STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe; it must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`. `STATUS: bad_input` is only for malformed or missing required inputs; it must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.

Rules:

- Do not edit files.
- Do not call other agents.
- Do not run expensive repo sweeps.
- Prefer deterministic thresholds supplied by the caller over inventing facts.
- If the input is malformed, return `STATUS: bad_input`; do not invent a command recommendation.
- If loop risk is present, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
- If the caller provides `route_chain_json`, inspect it before recommending a target.
- If the return is malformed, the caller ignores it and falls back to deterministic route or AskUser choice.

## Command and Skill Source Changes

Add a compact `## Plan Route Check` section to the following source files:

- `commands/z-do.md`
- `commands/z-plan-light.md`
- `commands/z-plan.md`
- `commands/z-plan-split.md`
- `commands/z-brainstorm.md`
- `commands/z-research.md`
- `commands/z-audit-plan.md`
- `skills/z-do/SKILL.md`
- `skills/z-plan-light/SKILL.md`
- `skills/z-plan/SKILL.md`
- `skills/z-plan-split/SKILL.md`
- `skills/z-brainstorm/SKILL.md`
- `skills/z-research/SKILL.md`
- `skills/z-audit-plan/SKILL.md`

The embedded block must be bracketed with HTML comments:

```markdown
<!-- PLAN_ROUTE_CHECK_START -->
...
<!-- PLAN_ROUTE_CHECK_END -->
```

The block must:

- State primary route targets and contextual exits.
- List deterministic signals relevant to that command.
- State when to call `planning-router`.
- State the AskUser handoff gate.
- State loop prevention.
- State telemetry and route artifact requirements.

Command-specific requirements:

- `/z-do`: preserve hard caps. Add downward/upward clarity: if task is no-code research or approach selection, route to `/z-research` or `/z-brainstorm`; if larger than `/z-do`, route to `/z-plan-light` or `/z-plan`.
- `/z-plan-light`: preserve current thresholds but allow routing down to `/z-do` before writing `FIX.md`, up to `/z-plan`, sideways to `/z-research` or `/z-brainstorm`, and contextual to `/z-fix` or `/z-debug` for bug workflows.
- `/z-plan`: add early route check after setup/precontext detection and before Phase 1. It may route down to `/z-plan-light`, up to `/z-plan-split`, sideways to `/z-research` or `/z-brainstorm`, or contextual to `/z-audit-plan` only after artifacts exist.
- `/z-plan-split`: preserve 2-6 cluster invariant. Route too-few clusters to `/z-plan`; route too-many clusters to topic narrowing or `/z-research`; route unknown seams to `/z-research`.
- `/z-brainstorm`: before ideator dispatch, route to `/z-research` if terrain is unknown, to `/z-plan` if framing is already clear, or to `/z-plan-light` for a small concrete fix.
- `/z-research`: preserve no-recommendation invariant inside `RESEARCH.md`. Route only before research starts or after finalization as a next-step recommendation; do not recommend an approach inside the research note.
- `/z-audit-plan`: route to `/z-plan` when no plan artifacts exist, to `/z-amend` for accepted plan changes, and to `/z-maintain-docs` for doc drift that blocks audit confidence. It is read-only.

## Docs and Memory Changes

Update docs/memory sources so future doc-fetcher calls know the router exists:

- `docs/human/commands.md`
- `docs/human/skills.md`
- `docs/human/agents.md`
- `docs/llm/INDEX.json`
- `docs/llm/commands.json`
- `docs/llm/skills.json`
- `docs/llm/agents.json`

Required doc content:

- Add `z-audit-plan` to command and skill concept source lists where missing.
- Specifically add `commands/z-audit-plan.md` to `docs/llm/commands.json` and `docs/llm/INDEX.json`.
- Specifically add `skills/z-audit-plan/SKILL.md` to `docs/llm/skills.json` and `docs/llm/INDEX.json`.
- Add `planning-router` to agent concept source lists.
- Add route policy summary and telemetry invariant.
- Mark docs touched for `/z-maintain-docs` follow-up if implementation changes source files faster than docs can be refreshed.

## Export Changes

After canonical files are updated, regenerate exports with the existing export pipeline:

```bash
python3 scripts/export-cursor.py
python3 scripts/export-codex.py
python3 scripts/export-agy.py
```

Acceptance:

- Exported Cursor, Codex, and Antigravity prompts/rules include the route check sections and `planning-router` agent.
- No generated export file is hand-edited as the source of truth.
- Export churn is expected in generated files for touched commands, skills, and the new agent. Unexpected export changes outside those surfaces should be reviewed before acceptance.

## Invariants

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
- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
- `planning-router` unavailable or malformed return: default to deterministic route or ask user; do not block on the classifier.

## Scenario Acceptance

Implementation must document or manually verify these scenarios:

- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
- `/z-do` with cross-module or schema impact recommends `/z-plan`.
- Unknown bug symptom recommends `/z-debug`; diagnosed bug recommends `/z-fix`.
- Unknown terrain before approach selection recommends `/z-research`.
- Multiple plausible framings with enough terrain recommends `/z-brainstorm`.
- Existing plan change recommends `/z-amend`.
- Existing complete plan can recommend `/z-audit-plan`; fresh intent without plan artifacts must not.
- `/z-plan-split` with one seam recommends `/z-plan`.
- Immediate ping-pong route is blocked and surfaced to the user.


Acceptance criteria:
- Sentineled `Plan Route Check` blocks exist in all four files.
- `/z-plan` insertion points are after setup/precontext/docs gates and after decisions when split risk is clear.
- `/z-plan-split` preserves the 2-6 cluster invariant.
- Too-few cluster seams route to `/z-plan`; unknown seams can route to `/z-research`.
- Route-chain and ping-pong prevention are included.

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/commands/z-plan-split.md b/commands/z-plan-split.md
index f9571eb..8cd99a1 100644
--- a/commands/z-plan-split.md
+++ b/commands/z-plan-split.md
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
diff --git a/commands/z-plan.md b/commands/z-plan.md
index 0f7879b..0cbea4a 100644
--- a/commands/z-plan.md
+++ b/commands/z-plan.md
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
diff --git a/skills/z-plan-split/SKILL.md b/skills/z-plan-split/SKILL.md
index f9571eb..3f39779 100644
--- a/skills/z-plan-split/SKILL.md
+++ b/skills/z-plan-split/SKILL.md
@@ -1,4 +1,5 @@
 ---
+name: z-plan-split
 description: Pre-emptive scope splitter — fan a big topic out into N narrow cluster-planner subagents in parallel, then reconcile file-path overlaps into SHARED-CONCERNS.md + MANIFEST.md.
 argument-hint: <topic> [--slug=<root-slug>] [--clusters="a,b,c"]
 ---
@@ -143,6 +144,25 @@ Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes
 
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
diff --git a/skills/z-plan/SKILL.md b/skills/z-plan/SKILL.md
index 8ad9942..034e8da 100644
--- a/skills/z-plan/SKILL.md
+++ b/skills/z-plan/SKILL.md
@@ -1,4 +1,5 @@
 ---
+name: z-plan
 description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
 argument-hint: <feature or task description>
 ---
@@ -57,6 +58,26 @@ Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.js
 
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


Surrounding file context:
Relevant docs were read for invariants before this prompt; no additional blocker/major constraints beyond the SPEC and acceptance criteria are requested.

Scrutinize this code rigorously. Claude is prone to: over-engineering, premature abstraction, plausible-looking-but-wrong logic, missed edge cases, and silently expanding scope beyond the spec.

Report:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns
6. Anything else worth flagging

For each finding: severity (blocker / major / minor / nit), location, and a suggested fix.

**OUTPUT BUDGET — respect strictly:**
- Total response under **8000 characters**.
- Report **blockers and majors only**. Skip minors and nits unless a "minor" hides a correctness bug — in which case promote it to major.
- One finding per bullet. Two sentences max per finding (one for the problem, one for the fix).
- No re-stating of code already in the diff. No summaries of what the code does. No restating the spec.
- If there are no blockers or majors, respond with exactly: `No blockers or majors found.` (plus an optional 1-line note if something needs the implementer's attention but is below the bar).

codex
No blockers or majors found.
tokens used
46,396
No blockers or majors found.

