2026-05-24T23:55:10.172800Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-24T23:55:10.173449Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-24T23:55:10.173451Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5c69-fb8e-7b92-a622-ac19cd62ee3f
--------
user
You are reviewing code that Claude just wrote for task T001: Add planning-router agent.

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
- `agents/planning-router.md` exists with Haiku/read-only frontmatter.
- Agent return shape matches SPEC exactly.
- Agent docs/memory include `planning-router`.
- Malformed input and route-loop behavior are specified.

Relevant docs/invariants read before review:
- docs/llm/agents.json says agents are consumed_by commands and skills; invariants include isolated customized system prompts and doc-updater memory preservation; gotcha says subagents are read-only except explicitly authorized outputs.
- docs/human/agents.md says planning-router is advisory only: malformed input returns STATUS: bad_input, route-loop risk returns STATUS: ask_user, and the command/orchestrator owns the final handoff decision.

Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/docs/human/agents.md b/docs/human/agents.md
index cfb4e56..7396ffa 100644
--- a/docs/human/agents.md
+++ b/docs/human/agents.md
@@ -1,13 +1,15 @@
 # Agents
 
-> Last updated: 2026-05-23
-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
+> Last updated: 2026-05-24
+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
 
 ## Overview
 The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each subagent is configured with a tailored system prompt, dedicated tools, and appropriate model profiles (typically Sonnet or specialized consultant roles) to execute discrete, high-discipline steps.
 
 These agents act as isolated workers spawned in parallel or series by orchestration commands. By decomposing complex workflows—such as code generation, planning, security checks, and code reviews—into focused subagent roles with precise scopes, the system minimizes context drift and maximizes execution quality.
 
+The `planning-router` agent is a Haiku, read-only advisory classifier for ambiguous planning-family route decisions. It consumes compact caller-supplied signals, never edits files, and returns only the parseable route envelope that callers can accept, ignore, or convert into an AskUser handoff.
+
 ## Key entry points
 - `agents/auditor.md:1` — `auditor` — Scrutinizes target codebase files across correctness, perf, cleanliness, or design dimensions.
 - `agents/cluster-planner.md:1` — `cluster-planner` — Resolves specialized technical sub-tasks during large-scale workspace planning.
@@ -17,7 +19,8 @@ These agents act as isolated workers spawned in parallel or series by orchestrat
 - `agents/doc-fetcher.md:1` — `doc-fetcher` — Retrieves, filters, and ranks documentation concepts relevant to an ongoing plan phase.
 - `agents/doc-updater.md:1` — `doc-updater` — Rebuilds or updates concept documentation files to match source files under maintain-docs.
 - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
-- `agents/implementer.md:1` — `implementer` — Executes the actual code-writing tasks under discrete plan targets.
+- `agents/implementer.md:1` — `implementer` — Executes a single passed task block, whether it came from canonical `TASKS.md` or a promoted review task artifact.
+- `agents/planning-router.md:1` — `planning-router` — Advises ambiguous `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`, and contextual route handoffs from compact signals.
 - `agents/remote-runner.md:1` — `remote-runner` — Executes verification tests and builds inside remote sandboxes for safety.
 - `agents/spec-precheck.md:1` — `spec-precheck` — Validates specifications, task lists, and designs for completeness before implementation.
 
@@ -29,6 +32,7 @@ These agents act as isolated workers spawned in parallel or series by orchestrat
 ## Edge cases / gotchas
 - Many agents operate in parallel (e.g., auditors, cluster planners, and implementers) which requires strict telemetry event logging using `log-phase.sh` to prevent execution tracing conflicts.
 - Memory preservation is mandatory for `doc-updater`: it must copy existing `memories[]` arrays verbatim without altering, adding, or deleting entries.
+- `planning-router` is advisory only: malformed input returns `STATUS: bad_input`, route-loop risk returns `STATUS: ask_user`, and the command/orchestrator owns the final handoff decision.
 
 ## Examples
-- An implementer receiving a task to code will use `agents/implementer.md` to ground its tools and complete the code-generation cycle in isolation before returning its proposed diff for review.
+- An implementer receiving a task to code will use `agents/implementer.md` to ground its tools and complete the code-generation cycle in isolation before returning its proposed diff for review. The task ID may be canonical (`T004`) or review-generated (`T-REV-001`, `T-MR-001`).
diff --git a/docs/llm/INDEX.json b/docs/llm/INDEX.json
index 90f0ada..ecebe64 100644
--- a/docs/llm/INDEX.json
+++ b/docs/llm/INDEX.json
@@ -15,6 +15,7 @@
         "agents/doc-updater.md",
         "agents/gemini-consultant.md",
         "agents/implementer.md",
+        "agents/planning-router.md",
         "agents/remote-runner.md",
         "agents/spec-precheck.md"
       ],
@@ -27,7 +28,7 @@
         "commands",
         "skills"
       ],
-      "summary": "Scrutinizes codebase targets across correctness/perf/cleanliness/design."
+      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
     },
     {
       "slug": "commands",
@@ -43,6 +44,7 @@
         "commands/z-improve.md",
         "commands/z-init-docs.md",
         "commands/z-maintain-docs.md",
+        "commands/z-mr-review.md",
         "commands/z-plan-light.md",
         "commands/z-plan-split.md",
         "commands/z-plan.md",
@@ -62,7 +64,7 @@
       "consumed_by": [
         "skills"
       ],
-      "summary": "Propagates targeted plan amendments consistently across plan artifacts."
+      "summary": "Slash command surfaces, including review-family finding promotion into task-shaped artifacts and /z-implement-all --tasks consumption."
     },
     {
       "slug": "scripts",
@@ -73,7 +75,7 @@
         "scripts/remote-sandbox-sync.sh",
         "scripts/version.sh"
       ],
-      "last_updated": "2026-05-23",
+      "last_updated": "2026-05-24",
       "confidence": "high",
       "depends_on": [],
       "consumed_by": [
@@ -128,7 +130,7 @@
         "scripts"
       ],
       "consumed_by": [],
-      "summary": "Checklists for amending spec, plan, and task checklists consistently."
+      "summary": "Operational checklists, including review finding promotion, z-amend safety gates, and explicit --tasks implementation queues."
     },
     {
       "slug": "providers-registry",
@@ -209,6 +211,35 @@
       ],
       "consumed_by": [],
       "summary": "Explicit in-place plugin update via /z-update; detects symlink vs tarball mode; git pull --ff-only for symlink, atomic swap for tarball; no autoupdate; version tracked by scripts/version.sh."
+    },
+    {
+      "slug": "lookup-contract",
+      "source_files": [
+        "agents/external-lookup.md"
+      ],
+      "last_updated": "2026-05-24",
+      "confidence": "high",
+      "depends_on": [
+        "agents"
+      ],
+      "consumed_by": [
+        "external-lookup-agent"
+      ],
+      "summary": "Output envelope contract (STATUS line + fixed Markdown sections) that all external/domain lookup subagents must emit."
+    },
+    {
+      "slug": "external-lookup-agent",
+      "source_files": [
+        "agents/external-lookup.md"
+      ],
+      "last_updated": "2026-05-24",
+      "confidence": "high",
+      "depends_on": [
+        "agents",
+        "lookup-contract"
+      ],
+      "consumed_by": [],
+      "summary": "Haiku-tier subagent for external retrieval (web docs, public APIs, library docs) that offloads lookups from main context while enforcing a read-only verb-blocklist."
     }
   ]
 }
diff --git a/docs/llm/agents.json b/docs/llm/agents.json
index 973f1e7..09de5ab 100644
--- a/docs/llm/agents.json
+++ b/docs/llm/agents.json
@@ -13,6 +13,7 @@
     "agents/doc-updater.md",
     "agents/gemini-consultant.md",
     "agents/implementer.md",
+    "agents/planning-router.md",
     "agents/remote-runner.md",
     "agents/spec-precheck.md"
   ],
@@ -112,7 +113,14 @@
       "line": 1,
       "symbol": "implementer",
       "kind": "module",
-      "summary": "Writes code and fulfills discrete task files."
+      "summary": "Writes code and fulfills a single passed task block, including canonical tasks and promoted review task IDs such as T-REV-001 or T-MR-001."
+    },
+    {
+      "file": "agents/planning-router.md",
+      "line": 1,
+      "symbol": "planning-router",
+      "kind": "module",
+      "summary": "Advisory Haiku router for ambiguous z-harness planning-family route decisions; returns routed, ask_user, or bad_input envelopes from compact caller-supplied signals."
     },
     {
       "file": "agents/remote-runner.md",


Surrounding file context (only if relevant to evaluating the diff):

=== /Users/zeke/dev/z-harness/agents/planning-router.md ===
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

If a relevant signal is missing, reason from what is present and lower confidence. Do not infer file counts, task counts, or artifact existence from the filesystem unless the caller supplied an `existing_artifacts` list to interpret.

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
7. If `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions` is `0` or `null`, recommend `/z-do`.
8. If `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
9. If `expected_tasks > 25` or `cluster_seams` is between 2 and 6, recommend `/z-plan-split`.
10. If `cluster_seams == 1`, recommend `/z-plan` with `too_few_clusters`.
11. Otherwise recommend `/z-plan`.

If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.

## Confidence Guidance

- `high`: supplied signals point clearly to one target and required preconditions are explicit.
- `medium`: one target is likely but some quantitative signals are `null` or weak.
- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.

The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.


=== /Users/zeke/dev/z-harness/docs/llm/agents.json ===
{
  "concept": "agents",
  "last_updated": "2026-05-24",
  "covers_spec": "none",
  "source_file": [
    "agents/auditor.md",
    "agents/mr-reviewer.md",
    "agents/cluster-planner.md",
    "agents/codex-consultant.md",
    "agents/codex-reviewer.md",
    "agents/complexity-classifier.md",
    "agents/doc-fetcher.md",
    "agents/doc-updater.md",
    "agents/gemini-consultant.md",
    "agents/implementer.md",
    "agents/planning-router.md",
    "agents/remote-runner.md",
    "agents/spec-precheck.md"
  ],
  "confidence": "high",
  "entry_points": [
    {
      "file": "agents/mr-reviewer.md",
      "line": 1,
      "symbol": "mr-reviewer",
      "kind": "module",
      "summary": "Fans out to codex/gemini consultants, deduplicates findings by (file, category, normalized_text), applies consensus tier-bumps and dismissal-pattern matches, returns structured findings JSON to orchestrator."
    },
    {
      "file": "agents/auditor.md",
      "line": 1,
      "symbol": "auditor",
      "kind": "module",
      "summary": "Scrutinizes codebase targets across correctness/perf/cleanliness/design."
    },
    {
      "file": "agents/cluster-planner.md",
      "line": 1,
      "symbol": "cluster-planner",
      "kind": "module",
      "summary": "Plans sub-tasks for large split components."
    },
    {
      "file": "agents/codex-consultant.md",
      "line": 1,
      "symbol": "codex-consultant",
      "kind": "module",
      "summary": "Performs Codex-tier validation and review of plan specifications.",
      "modes": [
        "bundled-decisions",
        "plan-review",
        "light-fix",
        "debug-hypotheses",
        "brainstorm",
        "research-review",
        "doc-audit",
        "test-cases",
        "mr-review",
        "generate-hypotheses-round1",
        "generate-hypotheses-round2-adversarial"
      ]
    },
    {
      "file": "agents/codex-reviewer.md",
      "line": 1,
      "symbol": "codex-reviewer",
      "kind": "module",
      "summary": "Reviews code-generation diffs against correctness and style rubrics."
    },
    {
      "file": "agents/complexity-classifier.md",
      "line": 1,
      "symbol": "complexity-classifier",
      "kind": "module",
      "summary": "Classifies task files by expected execution complexity."
    },
    {
      "file": "agents/doc-fetcher.md",
      "line": 1,
      "symbol": "doc-fetcher",
      "kind": "module",
      "summary": "Retrieves, filters, and ranks relevant documentation concepts."
    },
    {
      "file": "agents/doc-updater.md",
      "line": 1,
      "symbol": "doc-updater",
      "kind": "module",
      "summary": "Rebuilds or refreshes concept markdown and JSON docs."
    },
    {
      "file": "agents/gemini-consultant.md",
      "line": 1,
      "symbol": "gemini-consultant",
      "kind": "module",
      "summary": "Performs primary Gemini-tier validation of plan specifications.",
      "modes": [
        "bundled-decisions",
        "plan-review",
        "light-fix",
        "debug-hypotheses",
        "brainstorm",
        "research-review",
        "doc-audit",
        "test-cases",
        "mr-review",
        "generate-hypotheses-round1",
        "generate-hypotheses-round2-adversarial"
      ]
    },
    {
      "file": "agents/implementer.md",
      "line": 1,
      "symbol": "implementer",
      "kind": "module",
      "summary": "Writes code and fulfills a single passed task block, including canonical tasks and promoted review task IDs such as T-REV-001 or T-MR-001."
    },
    {
      "file": "agents/planning-router.md",
      "line": 1,
      "symbol": "planning-router",
      "kind": "module",
      "summary": "Advisory Haiku router for ambiguous z-harness planning-family route decisions; returns routed, ask_user, or bad_input envelopes from compact caller-supplied signals."
    },
    {
      "file": "agents/remote-runner.md",
      "line": 1,
      "symbol": "remote-runner",
      "kind": "module",
      "summary": "Executes testing and verification inside isolated sandboxes."
    },
    {
      "file": "agents/spec-precheck.md",
      "line": 1,
      "symbol": "spec-precheck",
      "kind": "module",
      "summary": "Validates planning specs and checklists for completeness."
    }
  ],
  "depends_on": [
    "scripts"
  ],
  "consumed_by": [
    "commands",
    "skills"
  ],
  "invariants": [
    "Subagents are configured as isolated agents with customized system prompt instructions.",
    "doc-updater must preserve memories verbatim from any pre-existing concept JSON."
  ],
  "gotchas": [
    "Subagents are read-only except for explicitly authorized output files like findings or logs."
  ],
  "memories": []
}


=== /Users/zeke/dev/z-harness/docs/human/agents.md ===
# Agents

> Last updated: 2026-05-24
> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md

## Overview
The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each subagent is configured with a tailored system prompt, dedicated tools, and appropriate model profiles (typically Sonnet or specialized consultant roles) to execute discrete, high-discipline steps.

These agents act as isolated workers spawned in parallel or series by orchestration commands. By decomposing complex workflows—such as code generation, planning, security checks, and code reviews—into focused subagent roles with precise scopes, the system minimizes context drift and maximizes execution quality.

The `planning-router` agent is a Haiku, read-only advisory classifier for ambiguous planning-family route decisions. It consumes compact caller-supplied signals, never edits files, and returns only the parseable route envelope that callers can accept, ignore, or convert into an AskUser handoff.

## Key entry points
- `agents/auditor.md:1` — `auditor` — Scrutinizes target codebase files across correctness, perf, cleanliness, or design dimensions.
- `agents/cluster-planner.md:1` — `cluster-planner` — Resolves specialized technical sub-tasks during large-scale workspace planning.
- `agents/consultant-secondary.md:1` — `consultant-secondary` — Performs secondary LLM critiques to resolve plan ambiguities and technical risks.
- `agents/reviewer.md:1` — `reviewer` — Scrutinizes diffs from code-generation agents against safety, rubric, and styling guidelines.
- `agents/complexity-classifier.md:1` — `complexity-classifier` — Classifies task files based on implementation complexity to guide orchestrator constraints.
- `agents/doc-fetcher.md:1` — `doc-fetcher` — Retrieves, filters, and ranks documentation concepts relevant to an ongoing plan phase.
- `agents/doc-updater.md:1` — `doc-updater` — Rebuilds or updates concept documentation files to match source files under maintain-docs.
- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
- `agents/implementer.md:1` — `implementer` — Executes a single passed task block, whether it came from canonical `TASKS.md` or a promoted review task artifact.
- `agents/planning-router.md:1` — `planning-router` — Advises ambiguous `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`, and contextual route handoffs from compact signals.
- `agents/remote-runner.md:1` — `remote-runner` — Executes verification tests and builds inside remote sandboxes for safety.
- `agents/spec-precheck.md:1` — `spec-precheck` — Validates specifications, task lists, and designs for completeness before implementation.

## How it interacts with others
- `commands` — Commands are the orchestrators that compile configurations and spawn these subagents to perform specialized work.
- `skills` — Skills define the exact operational boundaries, steps, and telemetry wrappers that direct subagent execution.
- `scripts` — Subagents use utility scripts to report telemetry log-events, time phase durations, and sync remote file structures.

## Edge cases / gotchas
- Many agents operate in parallel (e.g., auditors, cluster planners, and implementers) which requires strict telemetry event logging using `log-phase.sh` to prevent execution tracing conflicts.
- Memory preservation is mandatory for `doc-updater`: it must copy existing `memories[]` arrays verbatim without altering, adding, or deleting entries.
- `planning-router` is advisory only: malformed input returns `STATUS: bad_input`, route-loop risk returns `STATUS: ask_user`, and the command/orchestrator owns the final handoff decision.

## Examples
- An implementer receiving a task to code will use `agents/implementer.md` to ground its tools and complete the code-generation cycle in isolation before returning its proposed diff for review. The task ID may be canonical (`T004`) or review-generated (`T-REV-001`, `T-MR-001`).


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
I’ll verify the changed files against the spec surface, focusing on acceptance criteria and whether the new agent contract is actually enforceable.
exec
/bin/zsh -lc 'git diff -- agents/planning-router.md docs/human/agents.md docs/llm/agents.json docs/llm/INDEX.json' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
diff --git a/docs/human/agents.md b/docs/human/agents.md
index cfb4e56..7396ffa 100644
--- a/docs/human/agents.md
+++ b/docs/human/agents.md
@@ -1,13 +1,15 @@
 # Agents
 
-> Last updated: 2026-05-23
-> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/remote-runner.md, agents/spec-precheck.md
+> Last updated: 2026-05-24
+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
 
 ## Overview
 The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each subagent is configured with a tailored system prompt, dedicated tools, and appropriate model profiles (typically Sonnet or specialized consultant roles) to execute discrete, high-discipline steps.
 
 These agents act as isolated workers spawned in parallel or series by orchestration commands. By decomposing complex workflows—such as code generation, planning, security checks, and code reviews—into focused subagent roles with precise scopes, the system minimizes context drift and maximizes execution quality.
 
+The `planning-router` agent is a Haiku, read-only advisory classifier for ambiguous planning-family route decisions. It consumes compact caller-supplied signals, never edits files, and returns only the parseable route envelope that callers can accept, ignore, or convert into an AskUser handoff.
+
 ## Key entry points
 - `agents/auditor.md:1` — `auditor` — Scrutinizes target codebase files across correctness, perf, cleanliness, or design dimensions.
 - `agents/cluster-planner.md:1` — `cluster-planner` — Resolves specialized technical sub-tasks during large-scale workspace planning.
@@ -17,7 +19,8 @@ These agents act as isolated workers spawned in parallel or series by orchestrat
 - `agents/doc-fetcher.md:1` — `doc-fetcher` — Retrieves, filters, and ranks documentation concepts relevant to an ongoing plan phase.
 - `agents/doc-updater.md:1` — `doc-updater` — Rebuilds or updates concept documentation files to match source files under maintain-docs.
 - `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
-- `agents/implementer.md:1` — `implementer` — Executes the actual code-writing tasks under discrete plan targets.
+- `agents/implementer.md:1` — `implementer` — Executes a single passed task block, whether it came from canonical `TASKS.md` or a promoted review task artifact.
+- `agents/planning-router.md:1` — `planning-router` — Advises ambiguous `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`, and contextual route handoffs from compact signals.
 - `agents/remote-runner.md:1` — `remote-runner` — Executes verification tests and builds inside remote sandboxes for safety.
 - `agents/spec-precheck.md:1` — `spec-precheck` — Validates specifications, task lists, and designs for completeness before implementation.
 
@@ -29,6 +32,7 @@ These agents act as isolated workers spawned in parallel or series by orchestrat
 ## Edge cases / gotchas
 - Many agents operate in parallel (e.g., auditors, cluster planners, and implementers) which requires strict telemetry event logging using `log-phase.sh` to prevent execution tracing conflicts.
 - Memory preservation is mandatory for `doc-updater`: it must copy existing `memories[]` arrays verbatim without altering, adding, or deleting entries.
+- `planning-router` is advisory only: malformed input returns `STATUS: bad_input`, route-loop risk returns `STATUS: ask_user`, and the command/orchestrator owns the final handoff decision.
 
 ## Examples
-- An implementer receiving a task to code will use `agents/implementer.md` to ground its tools and complete the code-generation cycle in isolation before returning its proposed diff for review.
+- An implementer receiving a task to code will use `agents/implementer.md` to ground its tools and complete the code-generation cycle in isolation before returning its proposed diff for review. The task ID may be canonical (`T004`) or review-generated (`T-REV-001`, `T-MR-001`).
diff --git a/docs/llm/INDEX.json b/docs/llm/INDEX.json
index 90f0ada..ecebe64 100644
--- a/docs/llm/INDEX.json
+++ b/docs/llm/INDEX.json
@@ -15,6 +15,7 @@
         "agents/doc-updater.md",
         "agents/gemini-consultant.md",
         "agents/implementer.md",
+        "agents/planning-router.md",
         "agents/remote-runner.md",
         "agents/spec-precheck.md"
       ],
@@ -27,7 +28,7 @@
         "commands",
         "skills"
       ],
-      "summary": "Scrutinizes codebase targets across correctness/perf/cleanliness/design."
+      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
     },
     {
       "slug": "commands",
@@ -43,6 +44,7 @@
         "commands/z-improve.md",
         "commands/z-init-docs.md",
         "commands/z-maintain-docs.md",
+        "commands/z-mr-review.md",
         "commands/z-plan-light.md",
         "commands/z-plan-split.md",
         "commands/z-plan.md",
@@ -62,7 +64,7 @@
       "consumed_by": [
         "skills"
       ],
-      "summary": "Propagates targeted plan amendments consistently across plan artifacts."
+      "summary": "Slash command surfaces, including review-family finding promotion into task-shaped artifacts and /z-implement-all --tasks consumption."
     },
     {
       "slug": "scripts",
@@ -73,7 +75,7 @@
         "scripts/remote-sandbox-sync.sh",
         "scripts/version.sh"
       ],
-      "last_updated": "2026-05-23",
+      "last_updated": "2026-05-24",
       "confidence": "high",
       "depends_on": [],
       "consumed_by": [
@@ -128,7 +130,7 @@
         "scripts"
       ],
       "consumed_by": [],
-      "summary": "Checklists for amending spec, plan, and task checklists consistently."
+      "summary": "Operational checklists, including review finding promotion, z-amend safety gates, and explicit --tasks implementation queues."
     },
     {
       "slug": "providers-registry",
@@ -209,6 +211,35 @@
       ],
       "consumed_by": [],
       "summary": "Explicit in-place plugin update via /z-update; detects symlink vs tarball mode; git pull --ff-only for symlink, atomic swap for tarball; no autoupdate; version tracked by scripts/version.sh."
+    },
+    {
+      "slug": "lookup-contract",
+      "source_files": [
+        "agents/external-lookup.md"
+      ],
+      "last_updated": "2026-05-24",
+      "confidence": "high",
+      "depends_on": [
+        "agents"
+      ],
+      "consumed_by": [
+        "external-lookup-agent"
+      ],
+      "summary": "Output envelope contract (STATUS line + fixed Markdown sections) that all external/domain lookup subagents must emit."
+    },
+    {
+      "slug": "external-lookup-agent",
+      "source_files": [
+        "agents/external-lookup.md"
+      ],
+      "last_updated": "2026-05-24",
+      "confidence": "high",
+      "depends_on": [
+        "agents",
+        "lookup-contract"
+      ],
+      "consumed_by": [],
+      "summary": "Haiku-tier subagent for external retrieval (web docs, public APIs, library docs) that offloads lookups from main context while enforcing a read-only verb-blocklist."
     }
   ]
 }
diff --git a/docs/llm/agents.json b/docs/llm/agents.json
index 973f1e7..09de5ab 100644
--- a/docs/llm/agents.json
+++ b/docs/llm/agents.json
@@ -13,6 +13,7 @@
     "agents/doc-updater.md",
     "agents/gemini-consultant.md",
     "agents/implementer.md",
+    "agents/planning-router.md",
     "agents/remote-runner.md",
     "agents/spec-precheck.md"
   ],
@@ -112,7 +113,14 @@
       "line": 1,
       "symbol": "implementer",
       "kind": "module",
-      "summary": "Writes code and fulfills discrete task files."
+      "summary": "Writes code and fulfills a single passed task block, including canonical tasks and promoted review task IDs such as T-REV-001 or T-MR-001."
+    },
+    {
+      "file": "agents/planning-router.md",
+      "line": 1,
+      "symbol": "planning-router",
+      "kind": "module",
+      "summary": "Advisory Haiku router for ambiguous z-harness planning-family route decisions; returns routed, ask_user, or bad_input envelopes from compact caller-supplied signals."
     },
     {
       "file": "agents/remote-runner.md",

exec
/bin/zsh -lc 'rg -n "planning-router|plan_route_decision|PLAN_ROUTE_CHECK|z-audit-plan|external-lookup|gemini-consultant|consultant-primary|mr-reviewer" agents docs commands skills scripts -S' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
docs/human/agents.md:4:> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/reviewer.md, agents/complexity-classifier.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/implementer.md, agents/planning-router.md, agents/remote-runner.md, agents/spec-precheck.md
docs/human/agents.md:11:The `planning-router` agent is a Haiku, read-only advisory classifier for ambiguous planning-family route decisions. It consumes compact caller-supplied signals, never edits files, and returns only the parseable route envelope that callers can accept, ignore, or convert into an AskUser handoff.
docs/human/agents.md:21:- `agents/consultant-primary.md:1` — `consultant-primary` — Performs primary plan critiques and risk evaluations.
docs/human/agents.md:23:- `agents/planning-router.md:1` — `planning-router` — Advises ambiguous `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`, and contextual route handoffs from compact signals.
docs/human/agents.md:35:- `planning-router` is advisory only: malformed input returns `STATUS: bad_input`, route-loop risk returns `STATUS: ask_user`, and the command/orchestrator owns the final handoff decision.
docs/human/style-init.md:40:After the draft is generated from the Capture files and interview answers, the configured `consultant-primary` and `consultant-secondary` providers critique it in parallel (flagging missing categories, vague rules, contradictions). The critique is applied, and you are asked to approve, edit, re-critique, or abandon.
docs/human/style-init.md:69:Rule IDs are **append-only and never reused**. When a rule is retired, it is replaced by a tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that historical `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).
docs/human/style-init.md:74:- `docs/human/mr-reviewer.md` — the review command that consumes STYLE.md.
agents/external-lookup.md:2:name: external-lookup
commands/z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
commands/z-audit-plan.md:98:  subagent_type="consultant-primary",
commands/z-improve.md:117:Agent(subagent_type="consultant-primary",
docs/human/INDEX.md:13:| [agents](./agents.md) | high | `agents/auditor.md`, `agents/cluster-planner.md`, `agents/consultant-primary.md` | Scrutinizes codebase targets across correctness/perf/cleanliness/design. |
skills/z-review-all/SKILL.md:121:  subagent_type="consultant-primary",
agents/consultant-primary.md:2:name: consultant-primary
agents/consultant-primary.md:8:<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->
agents/consultant-primary.md:78:- **`mr-review`** (Step 4 of `mr-reviewer`): caller hands you active categories, full STYLE.md contents, and the full diff. Ask the provider to find quality issues (not correctness bugs) in the diff, citing STYLE.md rule IDs for style-drift findings and file:line for abstraction findings. Return RAW — the caller expects a fenced `json` block with `{"findings": [...]}` matching the schema in the prompt; do not apply the standard wrapper.
agents/consultant-primary.md:142:SLUG="consultant-primary-${PROVIDER}-$MODE"
commands/z-review-all.md:130:  subagent_type="consultant-primary",
commands/z-plan-light.md:80:  subagent_type="consultant-primary",
docs/human/mr-reviewer.md:4:> Covers source: commands/z-mr-review.md, agents/mr-reviewer.md, scripts/extract-dismissals.py
docs/human/mr-reviewer.md:10:The review fans out to all available LLM voices (Claude Sonnet inline, plus the configured `consultant-primary` and `consultant-secondary` providers). Findings are deduplicated, tagged by which voices raised them, ranked P0–P4, and written to `z-harness/<slug>/MR-REVIEW.md` in `TASKS.md`-compatible shape. The command **never blocks** — you triage by deleting unwanted findings from MR-REVIEW.md, then run `/z-implement-all --tasks=z-harness/<slug>/MR-REVIEW.md` on survivors.
docs/human/mr-reviewer.md:16:- As an optional post-mortem step in `/z-debug`: the debug command can invoke `mr-reviewer` on the fix diff and automatically promote P0/P1 findings to the post-mortem's preventative-action list.
docs/human/mr-reviewer.md:50:When the diff exceeds `Z_MR_DIFF_CHUNK_BYTES` (default 320 000 bytes, roughly 80K tokens), the orchestrator splits the diff per file and dispatches the `mr-reviewer` agent once per chunk. A final whole-diff abstraction-only pass catches cross-file duplication that per-chunk passes cannot see. The `--deep` flag upgrades that abstraction pass to Opus.
docs/human/mr-reviewer.md:61:- **Fold into `/z-audit`:** if the reviewer's findings achieve **>90% audit parity** with `/z-audit --dimension=cleanliness` on the same diffs, the two commands are redundant and `mr-reviewer` should be retired in favor of the audit pipeline.
docs/human/mr-reviewer.md:78:After committing a fix, `/z-debug`'s post-mortem phase offers (via `AskUserQuestion`) to run `/z-mr-review` on the fix diff. If accepted, the `mr-reviewer` agent runs with the debug run's slug. P0 and P1 findings are automatically appended to the post-mortem's "Preventative actions" section as bullet items, cited by `T-MR-NNN` ID. P2–P4 findings stay in MR-REVIEW.md only. See `commands/z-debug.md` for the integration details.
docs/human/STYLE-md-schema.md:27:| `repo` | string | Repository name (directory basename or org/repo). Used by `mr-reviewer` for display and archiving. |
docs/human/STYLE-md-schema.md:45:Additional sections are permitted but not consumed by `mr-reviewer` v1.
docs/human/STYLE-md-schema.md:62:Rules are **append-only and never reused**. When a rule is retired, it is replaced by a short tombstone comment (`<!-- EH-003 retired 2026-06-01 -->`) so that old `mr-reviewer` citations remain traceable. The `mr-reviewer` agent cites rules by their ID (e.g. `Citation: EH-001`).
docs/human/STYLE-md-schema.md:81:The example below is a valid STYLE.md for a hypothetical Rust web-service project. It serves as a test fixture for tasks that validate schema parsing and `mr-reviewer` citation logic. It has at least three rules per section.
commands/z-style-init.md:259:Dispatch `consultant-secondary` and `consultant-primary` **in parallel in a single message** with `MODE: style-critique`:
commands/z-style-init.md:280:  subagent_type="consultant-primary",
commands/z-plan.md:208:- `Agent(subagent_type="consultant-primary", ...)`
commands/z-plan.md:260:- consultant-primary: "Critique this plan. What's wrong, missing, or fragile?"
commands/z-plan.md:301:  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
docs/human/lookup-contract.md:9:z-harness delegates them to dedicated subagents (`external-lookup`,
docs/human/lookup-contract.md:178:   patterns are defined in `agents/external-lookup.md`; domain-specific agents
commands/z-amend.md:122:Agent(subagent_type="consultant-primary", description="Amend consult (Gemini) for <slug>",
skills/z-research/SKILL.md:222:  subagent_type="consultant-primary",
docs/llm/INDEX.json:16:        "agents/gemini-consultant.md",
docs/llm/INDEX.json:18:        "agents/planning-router.md",
docs/llm/INDEX.json:31:      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
docs/llm/INDEX.json:218:        "agents/external-lookup.md"
docs/llm/INDEX.json:226:        "external-lookup-agent"
docs/llm/INDEX.json:231:      "slug": "external-lookup-agent",
docs/llm/INDEX.json:233:        "agents/external-lookup.md"
skills/z-audit-plan/SKILL.md:2:name: z-audit-plan
skills/z-audit-plan/SKILL.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
skills/z-audit-plan/SKILL.md:98:  subagent_type="consultant-primary",
commands/z-maintain-docs.md:85:  subagent_type="consultant-primary",
scripts/extract-dismissals.py:164:    """Handles YAML scalar splitting at top-level commas; understands single+double quoted strings (with single-quote escape via doubled '') and bracket/brace nesting. Does NOT support YAML block scalars (|, >) or multi-line values — those are not emitted by mr-reviewer's findings_index writer.
commands/z-mr-review.md:427:### Step 2b — Dispatch mr-reviewer agent
commands/z-mr-review.md:435:  subagent_type="mr-reviewer",
commands/z-mr-review.md:483:  subagent_type="mr-reviewer",
commands/z-mr-review.md:507:  subagent_type="mr-reviewer",
commands/z-mr-review.md:540:Error: mr-reviewer agent returned no parseable findings JSON. The agent return was:
commands/z-mr-review.md:548:Parse each return in `CHUNK_AGENT_RETURNS` by locating its first fenced `json` block. For chunk returns that fail to parse (no valid JSON block), log `mr_voice_failed {voice: "mr-reviewer-chunk-<INDEX>", reason: "malformed_json"}` and skip. Collect all parseable per-chunk findings into `CHUNK_FINDINGS` (union; duplicates not yet removed).
commands/z-mr-review.md:550:Parse `ABSTRACTION_AGENT_RETURN` by locating its first fenced `json` block. If the abstraction-only return fails to parse, log `mr_voice_failed {voice: "mr-reviewer-abstraction", reason: "malformed_json"}` and treat abstraction findings as empty.
commands/z-mr-review.md:563:Error: all mr-reviewer chunk agents returned no parseable findings JSON.
agents/consultant-secondary.md:3:description: Routes to the secondary consultant LLM (resolved via providers registry) for a second opinion on an engineering decision or to review a plan. Use during /z-plan as the cross-LLM counterpart to consultant-primary — must resolve to a distinct provider.
agents/consultant-secondary.md:8:<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->
agents/consultant-secondary.md:78:- **`mr-review`** (Step 4 of `mr-reviewer`): caller hands you active categories, full STYLE.md contents, and the full diff. Ask the provider to find quality issues (not correctness bugs) in the diff, citing STYLE.md rule IDs for style-drift findings and file:line for abstraction findings. Return RAW — the caller expects a fenced `json` block with `{"findings": [...]}` matching the schema in the prompt; do not apply the standard wrapper.
commands/z-test.md:110:  subagent_type="consultant-primary",
commands/z-test.md:227:- **No new agents dispatched.** Reuses `consultant-primary` and `consultant-secondary` only.
agents/planning-router.md:2:name: planning-router
agents/planning-router.md:36:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
agents/planning-router.md:62:- `/z-audit-plan`
agents/planning-router.md:68:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
agents/planning-router.md:126:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
scripts/export-agy.py:121:    "mr-reviewer",
agents/reviewer.md:8:<!-- auto-generated shape: consultant-primary | consultant-secondary | reviewer differ only in ROLE below -->
agents/mr-reviewer.md:2:name: mr-reviewer
agents/mr-reviewer.md:191:**Consultant prompt shape (same for both consultant-secondary and consultant-primary):**
agents/mr-reviewer.md:195:  subagent_type="consultant-secondary",   # or "consultant-primary"
commands/z-audit.md:138:  subagent_type="consultant-primary",
commands/z-brainstorm.md:149:  subagent_type="consultant-primary",
commands/z-fix.md:104:  subagent_type="consultant-primary",
docs/llm/external-lookup-agent.json:2:  "slug": "external-lookup-agent",
docs/llm/external-lookup-agent.json:3:  "summary": "Haiku-tier subagent dispatched by the main thread to handle external retrieval (web docs, public APIs, paginated JSON, library docs outside training cutoff) without polluting the main context. Defined in agents/external-lookup.md. All responses must conform to the output envelope in docs/llm/lookup-contract.json: a STATUS-headed Markdown body with fixed sections (## Answer, ## Provenance, ## Unresolved, optional ## Raw artifact pointer), total response capped at 3 KB. The agent is read-only; mutating shell commands are blocked via a verb-blocklist enforced before every Bash invocation.",
docs/llm/external-lookup-agent.json:14:    { "path": "agents/external-lookup.md", "why": "The agent file itself — defines mission, output contract, tool whitelist, verb-blocklist patterns, budget rules, and all invariants." },
docs/llm/agents.json:7:    "agents/mr-reviewer.md",
docs/llm/agents.json:14:    "agents/gemini-consultant.md",
docs/llm/agents.json:16:    "agents/planning-router.md",
docs/llm/agents.json:23:      "file": "agents/mr-reviewer.md",
docs/llm/agents.json:25:      "symbol": "mr-reviewer",
docs/llm/agents.json:92:      "file": "agents/gemini-consultant.md",
docs/llm/agents.json:94:      "symbol": "gemini-consultant",
docs/llm/agents.json:119:      "file": "agents/planning-router.md",
docs/llm/agents.json:121:      "symbol": "planning-router",
skills/z-debug/SKILL.md:160:     subagent_type="consultant-primary",
skills/z-debug/SKILL.md:195:  subagent_type="consultant-primary",
skills/z-debug/SKILL.md:362:   Agent(subagent_type="consultant-primary", description="Fix consult for <slug>",
commands/z-debug.md:167:     subagent_type="consultant-primary",
commands/z-debug.md:202:  subagent_type="consultant-primary",
commands/z-debug.md:369:   Agent(subagent_type="consultant-primary", description="Fix consult for <slug>",
skills/z-test/SKILL.md:110:  subagent_type="consultant-primary",
skills/z-test/SKILL.md:227:- **No new agents dispatched.** Reuses `consultant-primary` and `consultant-secondary` only.
skills/z-maintain-docs/SKILL.md:85:  subagent_type="consultant-primary",
docs/llm/style-init.json:24:    "Rule IDs are append-only and never reused. Retired rules get a tombstone comment so historical mr-reviewer citations remain traceable.",
docs/llm/style-init.json:52:    "mr-reviewer",
docs/llm/style-init.json:63:    "mr-reviewer"
skills/z-improve/SKILL.md:118:Agent(subagent_type="consultant-primary",
skills/z-plan-light/SKILL.md:81:  subagent_type="consultant-primary",
docs/llm/lookup-contract.json:12:    { "path": "agents/external-lookup.md", "why": "Agent prompt that implements the lookup contract — defines the required output structure and section semantics." },
skills/z-brainstorm/SKILL.md:150:  subagent_type="consultant-primary",
docs/llm/mr-reviewer.json:2:  "concept": "mr-reviewer",
docs/llm/mr-reviewer.json:7:    "agents/mr-reviewer.md",
docs/llm/mr-reviewer.json:20:      "file": "agents/mr-reviewer.md",
docs/llm/mr-reviewer.json:22:      "symbol": "mr-reviewer",
docs/llm/mr-reviewer.json:37:    "The mr-reviewer agent always receives a single diff_path pointing to one .patch file. Orchestrator handles chunking; agent contract is not polymorphic.",
commands/z-research.md:221:  subagent_type="consultant-primary",
skills/z-amend/SKILL.md:125:Agent(subagent_type="consultant-primary", description="Amend consult (Gemini) for <slug>",
skills/z-plan/SKILL.md:201:- `Agent(subagent_type="consultant-primary", ...)`
skills/z-plan/SKILL.md:253:- consultant-primary: "Critique this plan. What's wrong, missing, or fragile?"

exec
/bin/zsh -lc 'git status --short' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
 M README.md
 M agents/consultant-primary.md
 M agents/consultant-secondary.md
 A agents/external-lookup.md
 M agents/implementer.md
 M agents/reviewer.md
 M commands/z-audit.md
 M commands/z-implement-all.md
 M commands/z-mr-review.md
 M commands/z-plan.md
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
 M exports/agy/.agent/rules/z-harness-implementer.md
 M exports/agy/.agent/skills/z-amend/SKILL.md
 M exports/agy/.agent/skills/z-implement-all/SKILL.md
 M exports/agy/.agent/skills/z-review-all/SKILL.md
 M exports/agy/.agent/workflows/z-audit.md
 M exports/agy/.agent/workflows/z-implement-all.md
 M exports/agy/.agent/workflows/z-mr-review.md
 M exports/agy/.agent/workflows/z-plan.md
 M exports/agy/.agent/workflows/z-review-all.md
 M exports/agy/agy-plugin.yaml
 M exports/agy/prompts/implementer.md
 M exports/agy/prompts/skill-z-amend.md
 M exports/agy/prompts/skill-z-implement-all.md
 M exports/agy/prompts/skill-z-review-all.md
 M exports/agy/prompts/z-audit.md
 M exports/agy/prompts/z-implement-all.md
 M exports/agy/prompts/z-mr-review.md
 M exports/agy/prompts/z-plan.md
 M exports/agy/prompts/z-review-all.md
 M exports/codex/AGENTS.md
 M exports/codex/prompts/z-amend.md
 M exports/codex/prompts/z-audit.md
 M exports/codex/prompts/z-implement-all.md
 M exports/codex/prompts/z-mr-review.md
 M exports/codex/prompts/z-review-all.md
 M exports/cursor/.cursor/rules/implementer.mdc
 M exports/cursor/.cursor/rules/z-amend.mdc
 M exports/cursor/.cursor/rules/z-audit.mdc
 M exports/cursor/.cursor/rules/z-implement-all.mdc
 M exports/cursor/.cursor/rules/z-mr-review.mdc
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
?? exports/agy/.agent/skills/z-audit-plan/
?? exports/agy/.agent/workflows/z-audit-plan.md
?? exports/agy/prompts/external-lookup.md
?? exports/agy/prompts/skill-z-audit-plan.md
?? exports/agy/prompts/z-audit-plan.md
?? exports/codex/prompts/z-audit-plan.md
?? exports/cursor/.cursor/rules/external-lookup.mdc
?? exports/cursor/.cursor/rules/z-audit-plan.mdc
?? skills/z-audit-plan/
?? z-harness/archive/20260524T184104Z-lookup-subagent/
?? z-harness/archive/20260524T184351Z-lookup-subagent/
?? z-harness/archive/20260524T190609Z-lookup-subagent/
?? z-harness/archive/20260524T201705Z-review/
?? z-harness/archive/20260524T203829Z-subagent-liveness/
?? z-harness/archive/consult-lookup-architecture/
?? z-harness/archive/consults/
?? z-harness/archive/lookup-subagent-brainstorm/
?? z-harness/archive/lookup-subagent-review/
?? z-harness/archive/plan-bail-router/
?? z-harness/archive/tasks/T002/review.prompt.md
?? z-harness/archive/tasks/T002/review.response.md
?? z-harness/archive/tasks/subagent-liveness/
?? z-harness/archive/unified-review-tasks/
?? z-harness/plan-variant-bail-routing/
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

codex
The main code path is small, so I’m also checking the doc index promises because this task’s acceptance hinges on future doc-fetcher visibility, not just the agent file existing.
exec
/bin/zsh -lc "nl -ba docs/llm/INDEX.json | sed -n '1,90p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "version": "1",
     3	  "generated_at": "2026-05-24T00:00:00Z",
     4	  "z_harness_version": "64a3dbe",
     5	  "concepts": [
     6	    {
     7	      "slug": "agents",
     8	      "source_file": [
     9	        "agents/auditor.md",
    10	        "agents/cluster-planner.md",
    11	        "agents/codex-consultant.md",
    12	        "agents/codex-reviewer.md",
    13	        "agents/complexity-classifier.md",
    14	        "agents/doc-fetcher.md",
    15	        "agents/doc-updater.md",
    16	        "agents/gemini-consultant.md",
    17	        "agents/implementer.md",
    18	        "agents/planning-router.md",
    19	        "agents/remote-runner.md",
    20	        "agents/spec-precheck.md"
    21	      ],
    22	      "last_updated": "2026-05-24",
    23	      "confidence": "high",
    24	      "depends_on": [
    25	        "scripts"
    26	      ],
    27	      "consumed_by": [
    28	        "commands",
    29	        "skills"
    30	      ],
    31	      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
    32	    },
    33	    {
    34	      "slug": "commands",
    35	      "source_file": [
    36	        "commands/z-amend.md",
    37	        "commands/z-audit.md",
    38	        "commands/z-brainstorm.md",
    39	        "commands/z-debug.md",
    40	        "commands/z-do.md",
    41	        "commands/z-fix.md",
    42	        "commands/z-implement-all.md",
    43	        "commands/z-implement-next.md",
    44	        "commands/z-improve.md",
    45	        "commands/z-init-docs.md",
    46	        "commands/z-maintain-docs.md",
    47	        "commands/z-mr-review.md",
    48	        "commands/z-plan-light.md",
    49	        "commands/z-plan-split.md",
    50	        "commands/z-plan.md",
    51	        "commands/z-research.md",
    52	        "commands/z-review-all.md",
    53	        "commands/z-skill-fix.md",
    54	        "commands/z-stats.md",
    55	        "commands/z-suggest-memory.md",
    56	        "commands/z-test.md"
    57	      ],
    58	      "last_updated": "2026-05-24",
    59	      "confidence": "high",
    60	      "depends_on": [
    61	        "agents",
    62	        "scripts"
    63	      ],
    64	      "consumed_by": [
    65	        "skills"
    66	      ],
    67	      "summary": "Slash command surfaces, including review-family finding promotion into task-shaped artifacts and /z-implement-all --tasks consumption."
    68	    },
    69	    {
    70	      "slug": "scripts",
    71	      "source_file": [
    72	        "scripts/log-event.sh",
    73	        "scripts/log-phase.sh",
    74	        "scripts/regenerate-memories-flat.py",
    75	        "scripts/remote-sandbox-sync.sh",
    76	        "scripts/version.sh"
    77	      ],
    78	      "last_updated": "2026-05-24",
    79	      "confidence": "high",
    80	      "depends_on": [],
    81	      "consumed_by": [
    82	        "agents",
    83	        "commands",
    84	        "skills"
    85	      ],
    86	      "summary": "Appends standard JSON events to run and global logs."
    87	    },
    88	    {
    89	      "slug": "z-fix",
    90	      "source_file": [

exec
/bin/zsh -lc "nl -ba agents/planning-router.md | sed -n '1,180p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	---
     2	name: planning-router
     3	description: Cheap Haiku ambiguity resolver for z-harness plan-family route decisions. Reads a compact signal payload and recommends the best command or contextual exit; advisory only.
     4	tools: Read, Grep, Glob
     5	model: haiku
     6	---
     7	
     8	## Mission
     9	
    10	You are a cheap, read-only ambiguity resolver for z-harness planning-family route decisions. The caller has already collected compact deterministic signals and needs an advisory recommendation only when hard thresholds did not settle the route.
    11	
    12	You do not edit files, do not call other agents, do not run shell commands, and do not perform broad repo exploration. Prefer the caller's supplied signals over inventing facts.
    13	
    14	## Inputs From Caller
    15	
    16	The caller prompt must provide:
    17	
    18	- `current_command`: the command currently running.
    19	- `task_or_topic`: the user's task or topic, kept compact.
    20	- `signals_json`: JSON object containing deterministic route signals.
    21	- `route_chain_json`: JSON array of prior route hops, or `[]`.
    22	- `repo_root`: absolute path to the repo root.
    23	
    24	The caller may also provide:
    25	
    26	- `existing_artifacts`: compact list of relevant artifacts such as `SPEC.md`, `PLAN.md`, `TASKS.md`, `FIX.md`, `RESEARCH.md`, or `BRAINSTORM.md`.
    27	
    28	Treat missing required inputs, malformed JSON, unknown `current_command`, or invalid signal types as malformed input.
    29	
    30	## Output Contract
    31	
    32	Return exactly this parseable shape and no prose before or after:
    33	
    34	```text
    35	STATUS: routed | ask_user | bad_input
    36	RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
    37	ROUTE_CLASS: primary | contextual | none
    38	CONFIDENCE: high | medium | low
    39	REASON_CODES: <comma-separated stable reason codes>
    40	REASON: <one line, <=160 chars>
    41	```
    42	
    43	`STATUS: routed` requires `RECOMMENDED` to be one concrete command and `ROUTE_CLASS` to be `primary` or `contextual`.
    44	
    45	`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
    46	
    47	`STATUS: bad_input` is only for malformed or missing required inputs. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, `CONFIDENCE: low`, and include `bad_input` in `REASON_CODES`.
    48	
    49	## Route Targets
    50	
    51	Primary route targets:
    52	
    53	- `/z-do`
    54	- `/z-plan-light`
    55	- `/z-plan`
    56	- `/z-plan-split`
    57	- `/z-brainstorm`
    58	- `/z-research`
    59	
    60	Contextual exits:
    61	
    62	- `/z-audit-plan`
    63	- `/z-fix`
    64	- `/z-debug`
    65	- `/z-amend`
    66	- `/z-maintain-docs`
    67	
    68	Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
    69	
    70	## Stable Reason Codes
    71	
    72	Use only these reason codes:
    73	
    74	- `tiny_task`
    75	- `small_fix`
    76	- `medium_plan`
    77	- `large_split`
    78	- `needs_research`
    79	- `needs_brainstorm`
    80	- `existing_plan_audit`
    81	- `existing_plan_amend`
    82	- `diagnosed_bug`
    83	- `unknown_bug`
    84	- `docs_stale`
    85	- `docs_drift`
    86	- `cross_module`
    87	- `schema_or_persistence`
    88	- `too_many_decisions`
    89	- `too_many_files`
    90	- `too_many_tasks`
    91	- `too_few_clusters`
    92	- `too_many_clusters`
    93	- `ambiguous_route`
    94	- `route_loop_risk`
    95	- `bad_input`
    96	
    97	## Expected Signals
    98	
    99	`signals_json` may include:
   100	
   101	- `candidate_files`: integer or `null`
   102	- `expected_tasks`: integer or `null`
   103	- `non_obvious_decisions`: integer or `null`
   104	- `cluster_seams`: integer or `null`
   105	- `cross_module`: boolean
   106	- `schema_or_persistence`: boolean
   107	- `public_api_or_wire_format`: boolean
   108	- `terrain_uncertain`: boolean
   109	- `approach_uncertain`: boolean
   110	- `has_bug_diagnosis`: boolean
   111	- `has_unknown_bug_symptom`: boolean
   112	- `has_existing_plan`: boolean
   113	- `has_fix_artifact`: boolean
   114	- `docs_stale_or_drifted`: boolean
   115	
   116	If a relevant signal is missing, reason from what is present and lower confidence. Do not infer file counts, task counts, or artifact existence from the filesystem unless the caller supplied an `existing_artifacts` list to interpret.
   117	
   118	## Decision Rules
   119	
   120	Apply these rules in order:
   121	
   122	1. If any required input is absent or malformed, return `STATUS: bad_input`.
   123	2. Inspect `route_chain_json` before recommending a target. If the chain already contains two prior entries, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
   124	3. If the best recommendation would send the user back to the immediate prior `from_command`, return `STATUS: ask_user` with `REASON_CODES: route_loop_risk`.
   125	4. Prefer contextual exits when their preconditions are explicit:
   126	   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
   127	   - `has_existing_plan` plus requested plan modification -> `/z-amend`
   128	   - `has_bug_diagnosis` -> `/z-fix`
   129	   - `has_unknown_bug_symptom` -> `/z-debug`
   130	   - `docs_stale_or_drifted` -> `/z-maintain-docs`
   131	5. If `terrain_uncertain` is true, recommend `/z-research`.
   132	6. If `approach_uncertain` is true and terrain is known enough to compare approaches, recommend `/z-brainstorm`.
   133	7. If `candidate_files <= 3`, no cross-module impact, no schema or persistence impact, and `non_obvious_decisions` is `0` or `null`, recommend `/z-do`.
   134	8. If `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no public API, wire-format, schema, or persistence impact, recommend `/z-plan-light`.
   135	9. If `expected_tasks > 25` or `cluster_seams` is between 2 and 6, recommend `/z-plan-split`.
   136	10. If `cluster_seams == 1`, recommend `/z-plan` with `too_few_clusters`.
   137	11. Otherwise recommend `/z-plan`.
   138	
   139	If two or more plausible targets remain tied after applying the rules, return `STATUS: ask_user` with `REASON_CODES: ambiguous_route`.
   140	
   141	## Confidence Guidance
   142	
   143	- `high`: supplied signals point clearly to one target and required preconditions are explicit.
   144	- `medium`: one target is likely but some quantitative signals are `null` or weak.
   145	- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
   146	
   147	The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.

exec
/bin/zsh -lc "rg -n 'z-audit-plan|planning-router|route policy|plan_route_decision|route-decision|PLAN_ROUTE_CHECK' docs/human/commands.md docs/human/skills.md docs/llm/commands.json docs/llm/skills.json docs/llm/INDEX.json commands/*.md skills/*/SKILL.md -S" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-audit-plan.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.
docs/llm/INDEX.json:18:        "agents/planning-router.md",
docs/llm/INDEX.json:31:      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
commands/z-plan.md:301:  /z-audit-plan     — (recommended) audit spec & tasks against codebase reality and best practices
skills/z-audit-plan/SKILL.md:2:name: z-audit-plan
skills/z-audit-plan/SKILL.md:6:You are running **z-harness `/z-audit-plan`** — a structured, pre-implementation plan audit pipeline. The output is a comprehensive `PLAN_AUDIT_REPORT.md` (detailing all findings) under `$Z_HARNESS_PLAN_DIR/`.

exec
/bin/zsh -lc "nl -ba docs/llm/commands.json | sed -n '1,50p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "concept": "commands",
     3	  "last_updated": "2026-05-24",
     4	  "covers_spec": "none",
     5	  "source_file": [
     6	    "commands/z-amend.md",
     7	    "commands/z-audit.md",
     8	    "commands/z-brainstorm.md",
     9	    "commands/z-debug.md",
    10	    "commands/z-mr-review.md",
    11	    "commands/z-style-init.md",
    12	    "commands/z-do.md",
    13	    "commands/z-implement-all.md",
    14	    "commands/z-implement-next.md",
    15	    "commands/z-improve.md",
    16	    "commands/z-init-docs.md",
    17	    "commands/z-maintain-docs.md",
    18	    "commands/z-plan-light.md",
    19	    "commands/z-plan-split.md",
    20	    "commands/z-plan.md",
    21	    "commands/z-research.md",
    22	    "commands/z-review-all.md",
    23	    "commands/z-skill-fix.md",
    24	    "commands/z-stats.md",
    25	    "commands/z-suggest-memory.md",
    26	    "commands/z-fix.md",
    27	    "commands/z-test.md"
    28	  ],
    29	  "confidence": "high",
    30	  "entry_points": [
    31	    {
    32	      "file": "commands/z-mr-review.md",
    33	      "line": 1,
    34	      "symbol": "z-mr-review",
    35	      "kind": "module",
    36	      "summary": "Orchestrates multi-LLM code-quality review of a branch diff; writes P0-P4 findings to MR-REVIEW.md as a task-shaped promotion artifact consumable via /z-implement-all --tasks."
    37	    },
    38	    {
    39	      "file": "commands/z-style-init.md",
    40	      "line": 1,
    41	      "symbol": "z-style-init",
    42	      "kind": "module",
    43	      "summary": "Authors or amends the project STYLE.md via Capture-first grounding and interactive interview."
    44	    },
    45	    {
    46	      "file": "commands/z-amend.md",
    47	      "line": 1,
    48	      "symbol": "z-amend",
    49	      "kind": "module",
    50	      "summary": "Propagates targeted plan amendments consistently across plan artifacts."

exec
/bin/zsh -lc "nl -ba docs/llm/INDEX.json | sed -n '88,125p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
    88	    {
    89	      "slug": "z-fix",
    90	      "source_file": [
    91	        "commands/z-fix.md"
    92	      ],
    93	      "last_updated": "2026-05-24",
    94	      "confidence": "high",
    95	      "depends_on": [
    96	        "agents",
    97	        "commands"
    98	      ],
    99	      "consumed_by": [
   100	        "commands"
   101	      ],
   102	      "summary": "Lightweight bug-fix command for the case where the user already has a diagnosis; single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem."
   103	    },
   104	    {
   105	      "slug": "skills",
   106	      "source_file": [
   107	        "skills/z-amend/SKILL.md",
   108	        "skills/z-brainstorm/SKILL.md",
   109	        "skills/z-debug/SKILL.md",
   110	        "skills/z-do/SKILL.md",
   111	        "skills/z-implement-all/SKILL.md",
   112	        "skills/z-implement-next/SKILL.md",
   113	        "skills/z-improve/SKILL.md",
   114	        "skills/z-init-docs/SKILL.md",
   115	        "skills/z-maintain-docs/SKILL.md",
   116	        "skills/z-plan-light/SKILL.md",
   117	        "skills/z-plan-split/SKILL.md",
   118	        "skills/z-plan/SKILL.md",
   119	        "skills/z-research/SKILL.md",
   120	        "skills/z-review-all/SKILL.md",
   121	        "skills/z-stats/SKILL.md",
   122	        "skills/z-suggest-memory/SKILL.md",
   123	        "skills/z-test/SKILL.md"
   124	      ],
   125	      "last_updated": "2026-05-23",

exec
/bin/zsh -lc "nl -ba docs/llm/skills.json | sed -n '1,55p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	{
     2	  "concept": "skills",
     3	  "last_updated": "2026-05-24",
     4	  "covers_spec": "none",
     5	  "source_file": [
     6	    "skills/z-amend/SKILL.md",
     7	    "skills/z-brainstorm/SKILL.md",
     8	    "skills/z-debug/SKILL.md",
     9	    "skills/z-do/SKILL.md",
    10	    "skills/z-implement-all/SKILL.md",
    11	    "skills/z-implement-next/SKILL.md",
    12	    "skills/z-improve/SKILL.md",
    13	    "skills/z-init-docs/SKILL.md",
    14	    "skills/z-maintain-docs/SKILL.md",
    15	    "skills/z-plan-light/SKILL.md",
    16	    "skills/z-plan-split/SKILL.md",
    17	    "skills/z-plan/SKILL.md",
    18	    "skills/z-research/SKILL.md",
    19	    "skills/z-review-all/SKILL.md",
    20	    "skills/z-stats/SKILL.md",
    21	    "skills/z-suggest-memory/SKILL.md",
    22	    "skills/z-test/SKILL.md"
    23	  ],
    24	  "confidence": "high",
    25	  "entry_points": [
    26	    {
    27	      "file": "skills/z-amend/SKILL.md",
    28	      "line": 1,
    29	      "symbol": "z-amend",
    30	      "kind": "module",
    31	      "summary": "Checklists for amending spec, plan, and task checklists consistently; review-generated amendment proposals route through this gate."
    32	    },
    33	    {
    34	      "file": "skills/z-brainstorm/SKILL.md",
    35	      "line": 1,
    36	      "symbol": "z-brainstorm",
    37	      "kind": "module",
    38	      "summary": "Checklists for parallel candidate plan brainstorming and bias filters."
    39	    },
    40	    {
    41	      "file": "skills/z-debug/SKILL.md",
    42	      "line": 1,
    43	      "symbol": "z-debug",
    44	      "kind": "module",
    45	      "summary": "Checklists for bug isolation, hypothesis generation, and post-mortems."
    46	    },
    47	    {
    48	      "file": "skills/z-do/SKILL.md",
    49	      "line": 1,
    50	      "symbol": "z-do",
    51	      "kind": "module",
    52	      "summary": "Checklists for small targeted code updates under code reviews."
    53	    },
    54	    {
    55	      "file": "skills/z-implement-all/SKILL.md",

exec
/bin/zsh -lc 'rg -n "planning-router|PLAN_ROUTE_CHECK_START" exports -S' in /Users/zeke/dev/z-harness
 exited 1 in 0ms:
codex
- **blocker** — `commands/z-do.md`, `commands/z-plan-light.md`, `commands/z-plan.md`, `commands/z-plan-split.md`, `commands/z-brainstorm.md`, `commands/z-research.md`, `commands/z-audit-plan.md`, and matching `skills/*/SKILL.md`: the required `<!-- PLAN_ROUTE_CHECK_START -->` blocks are absent, so none of the command insertion points, AskUser gates, route artifacts, or `plan_route_decision` telemetry are actually documented in the command/skill sources. Add the bracketed route-check section to every required command and skill, including each command-specific routing rule.

- **blocker** — `exports/`: `rg` finds no `planning-router` or `PLAN_ROUTE_CHECK_START` in generated exports, so Cursor/Codex/Antigravity prompts do not include the new agent or route policy. Run the export pipeline after updating canonical sources and verify the generated surfaces include the agent and route-check sections.

- **major** — [docs/llm/INDEX.json](/Users/zeke/dev/z-harness/docs/llm/INDEX.json:35), [docs/llm/commands.json](/Users/zeke/dev/z-harness/docs/llm/commands.json:5), and [docs/llm/skills.json](/Users/zeke/dev/z-harness/docs/llm/skills.json:5): `commands/z-audit-plan.md` and `skills/z-audit-plan/SKILL.md` are still missing from the relevant concept source lists despite being explicitly required. Add both files to `INDEX.json`, `commands.json`, and `skills.json` with matching entry-point summaries so doc-fetcher can discover them.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:133): the router treats `non_obvious_decisions: null` as eligible for `/z-do`, but the spec’s `/z-do` threshold requires no non-obvious decisions, while `null` means not known. Require `non_obvious_decisions == 0` for `/z-do`; when it is `null`, lower confidence and route to a safer planning path or `ask_user`.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:135): `cluster_seams` in `2..6` unconditionally recommends `/z-plan-split`, dropping the required “each seam is independently plannable” condition and making sparse seam counts enough to split. Add an explicit caller-supplied signal/precondition for independently plannable seams, otherwise return `/z-plan` or `ask_user` with lower confidence.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:133): the file-count downroutes run before the `cluster_seams == 1` rule, so `/z-plan-split` with one seam and a small file count can incorrectly recommend `/z-do` instead of the required `/z-plan` too-few-clusters exit. Prioritize split-specific seam invariants before generic tiny/small task routing, at least when `current_command` is `/z-plan-split`.
tokens used
68,568
- **blocker** — `commands/z-do.md`, `commands/z-plan-light.md`, `commands/z-plan.md`, `commands/z-plan-split.md`, `commands/z-brainstorm.md`, `commands/z-research.md`, `commands/z-audit-plan.md`, and matching `skills/*/SKILL.md`: the required `<!-- PLAN_ROUTE_CHECK_START -->` blocks are absent, so none of the command insertion points, AskUser gates, route artifacts, or `plan_route_decision` telemetry are actually documented in the command/skill sources. Add the bracketed route-check section to every required command and skill, including each command-specific routing rule.

- **blocker** — `exports/`: `rg` finds no `planning-router` or `PLAN_ROUTE_CHECK_START` in generated exports, so Cursor/Codex/Antigravity prompts do not include the new agent or route policy. Run the export pipeline after updating canonical sources and verify the generated surfaces include the agent and route-check sections.

- **major** — [docs/llm/INDEX.json](/Users/zeke/dev/z-harness/docs/llm/INDEX.json:35), [docs/llm/commands.json](/Users/zeke/dev/z-harness/docs/llm/commands.json:5), and [docs/llm/skills.json](/Users/zeke/dev/z-harness/docs/llm/skills.json:5): `commands/z-audit-plan.md` and `skills/z-audit-plan/SKILL.md` are still missing from the relevant concept source lists despite being explicitly required. Add both files to `INDEX.json`, `commands.json`, and `skills.json` with matching entry-point summaries so doc-fetcher can discover them.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:133): the router treats `non_obvious_decisions: null` as eligible for `/z-do`, but the spec’s `/z-do` threshold requires no non-obvious decisions, while `null` means not known. Require `non_obvious_decisions == 0` for `/z-do`; when it is `null`, lower confidence and route to a safer planning path or `ask_user`.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:135): `cluster_seams` in `2..6` unconditionally recommends `/z-plan-split`, dropping the required “each seam is independently plannable” condition and making sparse seam counts enough to split. Add an explicit caller-supplied signal/precondition for independently plannable seams, otherwise return `/z-plan` or `ask_user` with lower confidence.

- **major** — [agents/planning-router.md](/Users/zeke/dev/z-harness/agents/planning-router.md:133): the file-count downroutes run before the `cluster_seams == 1` rule, so `/z-plan-split` with one seam and a small file count can incorrectly recommend `/z-do` instead of the required `/z-plan` too-few-clusters exit. Prioritize split-specific seam invariants before generic tiny/small task routing, at least when `current_command` is `/z-plan-split`.
