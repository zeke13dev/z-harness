2026-05-25T00:18:42.496334Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-25T00:18:42.496357Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-25T00:18:42.496359Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5c7f-8890-79e1-b1ca-9ac9e97e3f14
--------
user
You are reviewing code that Claude just wrote for task T002: Add shared route contract to lightweight execution paths.

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
- Existing escalation text is replaced or aliased so no duplicate/conflicting user-facing prompts remain.
- `$CURRENT_ARCHIVE_DIR`, `route-decision.md`, and `plan_route_decision` are specified.
- `/z-do` can route to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` only under SPEC conditions.
- `/z-plan-light` can route down, up, sideways, or to contextual bug workflows only under SPEC conditions.

Relevant docs and invariants (read for drift; invariant violations are blockers):
=== /Users/zeke/dev/z-harness/docs/llm/commands.json ===
{
  "concept": "commands",
  "last_updated": "2026-05-24",
  "covers_spec": "none",
  "source_file": [
    "commands/z-amend.md",
    "commands/z-audit.md",
    "commands/z-brainstorm.md",
    "commands/z-debug.md",
    "commands/z-mr-review.md",
    "commands/z-style-init.md",
    "commands/z-do.md",
    "commands/z-implement-all.md",
    "commands/z-implement-next.md",
    "commands/z-improve.md",
    "commands/z-init-docs.md",
    "commands/z-maintain-docs.md",
    "commands/z-plan-light.md",
    "commands/z-plan-split.md",
    "commands/z-plan.md",
    "commands/z-research.md",
    "commands/z-review-all.md",
    "commands/z-skill-fix.md",
    "commands/z-stats.md",
    "commands/z-suggest-memory.md",
    "commands/z-fix.md",
    "commands/z-test.md"
  ],
  "confidence": "high",
  "entry_points": [
    {
      "file": "commands/z-mr-review.md",
      "line": 1,
      "symbol": "z-mr-review",
      "kind": "module",
      "summary": "Orchestrates multi-LLM code-quality review of a branch diff; writes P0-P4 findings to MR-REVIEW.md as a task-shaped promotion artifact consumable via /z-implement-all --tasks."
    },
    {
      "file": "commands/z-style-init.md",
      "line": 1,
      "symbol": "z-style-init",
      "kind": "module",
      "summary": "Authors or amends the project STYLE.md via Capture-first grounding and interactive interview."
    },
    {
      "file": "commands/z-amend.md",
      "line": 1,
      "symbol": "z-amend",
      "kind": "module",
      "summary": "Propagates targeted plan amendments consistently across plan artifacts."
    },
    {
      "file": "commands/z-audit.md",
      "line": 1,
      "symbol": "z-audit",
      "kind": "module",
      "summary": "Coordinates parallel multi-dimensional code auditing and rubric checks; preserves REPORT.md evidence and promotes actionable findings into TASKS.md."
    },
    {
      "file": "commands/z-brainstorm.md",
      "line": 1,
      "symbol": "z-brainstorm",
      "kind": "module",
      "summary": "Seeds plan definitions via parallel ideation models and anti-bias passes."
    },
    {
      "file": "commands/z-debug.md",
      "line": 1,
      "symbol": "z-debug",
      "kind": "module",
      "summary": "Heavy hypothesis-tournament debugging pipeline: 3-LLM 2-round adversarial hypothesis generation, ordinal Bayesian scoring, consensus-first ranking with forced outlier carve-out, 3-5 isolation rounds, fix-gate requires highest posterior and full evidence coverage. Single unified DEBUG.md artifact.",
      "last_updated": "2026-05-24"
    },
    {
      "file": "commands/z-do.md",
      "line": 1,
      "symbol": "z-do",
      "kind": "module",
      "summary": "Applies small plan-free changes directly to source code under peer review."
    },
    {
      "file": "commands/z-implement-all.md",
      "line": 1,
      "symbol": "z-implement-all",
      "kind": "module",
      "summary": "Executes pending tasks from canonical TASKS.md or an explicit --tasks path using isolated implementer and reviewer subagents."
    },
    {
      "file": "commands/z-implement-next.md",
      "line": 1,
      "symbol": "z-implement-next",
      "kind": "module",
      "summary": "Implements the next pending plan task under code review safety gates."
    },
    {
      "file": "commands/z-improve.md",
      "line": 1,
      "symbol": "z-improve",
      "kind": "module",
      "summary": "Surfaces project infrastructure suggestions from run event logs."
    },
    {
      "file": "commands/z-init-docs.md",
      "line": 1,
      "symbol": "z-init-docs",
      "kind": "module",
      "summary": "Initializes the two-tier human and LLM concept documentation system."
    },
    {
      "file": "commands/z-maintain-docs.md",
      "line": 1,
      "symbol": "z-maintain-docs",
      "kind": "module",
      "summary": "Drift-checks and refreshes stale or drifted concept documentation."
    },
    {
      "file": "commands/z-plan-light.md",
      "line": 1,
      "symbol": "z-plan-light",
      "kind": "module",
      "summary": "Creates lightweight bug fix plans bypassing full subagent overhead."
    },
    {
      "file": "commands/z-plan-split.md",
      "line": 1,
      "symbol": "z-plan-split",
      "kind": "module",
      "summary": "Splits a large plan into parallel sub-planning sessions."
    },
    {
      "file": "commands/z-plan.md",
      "line": 1,
      "symbol": "z-plan",
      "kind": "module",
      "summary": "Executes the core planning pipeline creating spec, plan, and task files."
    },
    {
      "file": "commands/z-research.md",
      "line": 1,
      "symbol": "z-research",
      "kind": "module",
      "summary": "Explores a codebase and charts its constraints before defining a plan."
    },
    {
      "file": "commands/z-review-all.md",
      "line": 1,
      "symbol": "z-review-all",
      "kind": "module",
      "summary": "Validates the complete set of generated code diffs against spec requirements and promotes accepted review findings into REVIEW-TASKS.md."
    },
    {
      "file": "commands/z-skill-fix.md",
      "line": 1,
      "symbol": "z-skill-fix",
      "kind": "module",
      "summary": "Safely mutates system plugin skill definitions."
    },
    {
      "file": "commands/z-stats.md",
      "line": 1,
      "symbol": "z-stats",
      "kind": "module",
      "summary": "Analyzes historical run logs to aggregate token metrics and run times."
    },
    {
      "file": "commands/z-suggest-memory.md",
      "line": 1,
      "symbol": "z-suggest-memory",
      "kind": "module",
      "summary": "Appends key lessons and edge case memories to concept documentation JSON."
    },
    {
      "file": "commands/z-fix.md",
      "line": 1,
      "symbol": "z-fix",
      "kind": "module",
      "summary": "Lightweight bug-fix command for the case where the user already has a diagnosis; single light-fix consult, inline implementation, non-negotiable Codex review, optional post-mortem."
    },
    {
      "file": "commands/z-test.md",
      "line": 1,
      "symbol": "z-test",
      "kind": "module",
      "summary": "Constructs rich semantic test-case plans to link within task items."
    }
  ],
  "depends_on": [
    "agents",
    "scripts",
    "z-plan-light"
  ],
  "consumed_by": [
    "skills"
  ],
  "invariants": [
    "Every execution event must be routed to metrics.jsonl and per-run event logs.",
    "Commands must resolve plan directories via scripts/plan-path.sh (plan_dir or resolve_plan_path), not by constructing z-harness/<slug> paths directly. New canonical path: ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>/. Commands must try the new path first; on miss, resolve_plan_path falls back to the legacy z-harness/<slug>/ path and warns once per process (Z_HARNESS_LEGACY_WARNED guard) with the exact migration command: scripts/migrate-plan-layout.sh <slug>.",
    "Review-family commands preserve evidence artifacts and promote only actionable findings into task-shaped artifacts. Spec gaps route through /z-amend; review-all must not directly mutate SPEC.md or canonical TASKS.md."
  ],
  "gotchas": [
    "Orchestrating large plans directly in the main thread is context-heavy; delegate to subagents.",
    "Promoted review artifacts such as REVIEW-TASKS.md and MR-REVIEW.md are applied with /z-implement-all --tasks <path>, not by appending directly to canonical TASKS.md."
  ],
  "memories": []
}

=== /Users/zeke/dev/z-harness/docs/human/commands.md ===
# Commands

> Last updated: 2026-05-24
> Covers source: commands/z-amend.md, commands/z-audit.md, commands/z-brainstorm.md, commands/z-debug.md, commands/z-do.md, commands/z-implement-all.md, commands/z-implement-next.md, commands/z-improve.md, commands/z-init-docs.md, commands/z-maintain-docs.md, commands/z-plan-light.md, commands/z-plan-split.md, commands/z-plan.md, commands/z-research.md, commands/z-review-all.md, commands/z-skill-fix.md, commands/z-stats.md, commands/z-suggest-memory.md, commands/z-test.md

## Overview
The commands concept covers the complete set of slash commands that provide a structured CLI-like interface for executing z-harness tasks. These commands partition harness behaviors into clear logical operations—such as parallel brainstorming, deep pre-plan terrain research, comprehensive planning, targeted hotfixes, checklist implementation, automatic code review, test case generation, and documentation maintenance.

Each command is specified in a Markdown file under the commands/ directory, which details the strict multi-phase procedures, setup configurations, input arguments, telemetry logging expectations, and safety checks required for the orchestrator model to follow.

## Key entry points
- `commands/z-amend.md:1` — `z-amend` — Propagates target plan changes consistently across planning and task artifacts.
- `commands/z-audit.md:1` — `z-audit` — Executes multi-dimensional, rubrics-grounded code reviews in parallel.
- `commands/z-brainstorm.md:1` — `z-brainstorm` — Seeds plans via parallel candidate generation and bias checking.
- `commands/z-debug.md:1` — `z-debug` — Investigates regressions with hypothesis isolation and lightweight fix loops.
- `commands/z-do.md:1` — `z-do` — Performs small, plan-free coding changes with review safety gates.
- `commands/z-implement-all.md:1` — `z-implement-all` — Automates task implementation with parallel agents and peer reviews.
- `commands/z-implement-next.md:1` — `z-implement-next` — Implements the next pending task from the plan queue with review.
- `commands/z-improve.md:1` — `z-improve` — Suggests platform improvements based on aggregate post-run telemetry logs.
- `commands/z-init-docs.md:1` — `z-init-docs` — Bootstraps the human and LLM-tier two-tier documentation system in a repo.
- `commands/z-maintain-docs.md:1` — `z-maintain-docs` — Scans for doc drifts and auto-refreshes outdated concept documentation.
- `commands/z-plan-light.md:1` — `z-plan-light` — Handles targeted bug fixes and refactor plans without subagent overhead.
- `commands/z-plan-split.md:1` — `z-plan-split` — Decomposes high-scope plans across multiple sub-planners.
- `commands/z-plan.md:1` — `z-plan` — Runs the rigorous planning pipeline producing SPEC.md, PLAN.md, and TASKS.md.
- `commands/z-research.md:1` — `z-research` — Performs early codebase scans and terrain mapping before designing a plan.
- `commands/z-review-all.md:1` — `z-review-all` — Audits the entire task diff queue against the complete design spec and promotes accepted findings into review task artifacts.
- `commands/z-skill-fix.md:1` — `z-skill-fix` — Safely applies direct changes to z-harness platform skills.
- `commands/z-stats.md:1` — `z-stats` — Evaluates local runtime performance and token costs across past runs.
- `commands/z-suggest-memory.md:1` — `z-suggest-memory` — appends lessons-learned memories to targeted concept documentation files.
- `commands/z-test.md:1` — `z-test` — Drafts semantic test plans targeting edge cases and off-by-ones.

## How it interacts with others
- `skills` — Commands are the user-facing entry points that invoke the deeper instructions and checklists stored within the skills directory.
- `agents` — Commands instantiate and direct subagent teams (e.g. auditors, reviewers, implementers, plan consultants) to safely delegate heavy workloads.
- `scripts` — Commands execute core utility scripts to version resources, log telemetry timing, and synchronize sandboxes.
- Review-family commands (`z-review-all`, `z-audit`, `z-mr-review`) share a finding-promotion pattern: preserve evidence in a report, promote only actionable findings into task-shaped artifacts, and let `/z-implement-all --tasks <path>` consume the approved survivors.

## Edge cases / gotchas
- Namespacing is strictly enforced via the `Z_HARNESS_SLUG` environment variable. Every shell call and subagent invocation must inherit this slug to target files in the correct run directory.
- Grounding checks during planning commands use `doc-fetcher` to consult the `docs/llm/INDEX.json` instead of reading files directly to preserve main context tokens.
- `z-review-all` must not mutate `SPEC.md` or canonical `TASKS.md` directly. Spec gaps become amendment proposals and completed-task contradictions become superseding review tasks.

## Examples
- Bootstrapping a repository's documentation:
  `/z-init-docs`
- Starting a fresh feature design phase:
  `/z-plan "Implement client-side request timeout handling"`

=== /Users/zeke/dev/z-harness/docs/llm/skills.json ===
{
  "concept": "skills",
  "last_updated": "2026-05-24",
  "covers_spec": "none",
  "source_file": [
    "skills/z-amend/SKILL.md",
    "skills/z-brainstorm/SKILL.md",
    "skills/z-debug/SKILL.md",
    "skills/z-do/SKILL.md",
    "skills/z-implement-all/SKILL.md",
    "skills/z-implement-next/SKILL.md",
    "skills/z-improve/SKILL.md",
    "skills/z-init-docs/SKILL.md",
    "skills/z-maintain-docs/SKILL.md",
    "skills/z-plan-light/SKILL.md",
    "skills/z-plan-split/SKILL.md",
    "skills/z-plan/SKILL.md",
    "skills/z-research/SKILL.md",
    "skills/z-review-all/SKILL.md",
    "skills/z-stats/SKILL.md",
    "skills/z-suggest-memory/SKILL.md",
    "skills/z-test/SKILL.md"
  ],
  "confidence": "high",
  "entry_points": [
    {"file": "skills/z-amend/SKILL.md", "line": 1, "symbol": "z-amend", "kind": "module", "summary": "Amend SPEC/PLAN/TASKS or FIX.md; uses $Z_HARNESS_PLAN_DIR; re-classifies complexity stamps for changed task blocks."},
    {"file": "skills/z-brainstorm/SKILL.md", "line": 1, "symbol": "z-brainstorm", "kind": "module", "summary": "Three-vendor parallel ideation (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check; produces BRAINSTORM.md."},
    {"file": "skills/z-debug/SKILL.md", "line": 1, "symbol": "z-debug", "kind": "module", "summary": "Heavy hypothesis-tournament pipeline: Phase 0 wrong-tool gate, rounds of parallel hypothesis generation, fix with /z-plan-light mechanics, mandatory post-mortem."},
    {"file": "skills/z-do/SKILL.md", "line": 1, "symbol": "z-do", "kind": "module", "summary": "Lightest harness on-ramp: no plan artifacts, doc-fetcher grounding, inline implementation, mandatory reviewer gate; logs to z-harness/adhoc/."},
    {"file": "skills/z-implement-all/SKILL.md", "line": 1, "symbol": "z-implement-all", "kind": "module", "summary": "Full task-queue orchestrator: --tasks fast path, tree-rooted MANIFEST support, spec-precheck, TESTS.md integration, hard caps MAX_ATTEMPTS/wall-clock/halts."},
    {"file": "skills/z-implement-next/SKILL.md", "line": 1, "symbol": "z-implement-next", "kind": "module", "summary": "Single-task implementation; model selected from **Complexity:** stamp; no auto-retry; single-shot design forces fresh context per task."},
    {"file": "skills/z-improve/SKILL.md", "line": 1, "symbol": "z-improve", "kind": "module", "summary": "Post-run retro: reads events.jsonl friction signals, proposes <=5 z-harness edits, applies accepted edits, invokes /z-suggest-memory with derived concept_hints."},
    {"file": "skills/z-init-docs/SKILL.md", "line": 1, "symbol": "z-init-docs", "kind": "module", "summary": "Bootstraps two-tier docs: doc-updater per concept, INDEX.json aggregation, TAGS.txt 15-tag seed, MEMORIES-FLAT.md init via regenerate-memories-flat.py."},
    {"file": "skills/z-maintain-docs/SKILL.md", "line": 1, "symbol": "z-maintain-docs", "kind": "module", "summary": "Refreshes stale concept docs: doc-updater with dedup_tags:true, stale-memory UI, TAG_COLLISIONS surface, MEMORIES-FLAT.md regen after every write."},
    {"file": "skills/z-plan-light/SKILL.md", "line": 1, "symbol": "z-plan-light", "kind": "module", "summary": "Lightweight planner for small fixes: inline orchestrator implementation, FIX.md only, mandatory reviewer gate, auto-bail at >5 files or >2 non-obvious decisions."},
    {"file": "skills/z-plan-split/SKILL.md", "line": 1, "symbol": "z-plan-split", "kind": "module", "summary": "Scope splitter into 2-6 clusters: kebab-slug security gate, file-overlap reconciliation from TASKS.md canonical, MANIFEST.md + SHARED-CONCERNS.md output."},
    {"file": "skills/z-plan/SKILL.md", "line": 1, "symbol": "z-plan", "kind": "module", "summary": "Full rigorous planning: docs-freshness gate, Explore cap 3, batch decisions, single bundled cross-LLM consult, parallel Haiku complexity classifier per task."},
    {"file": "skills/z-research/SKILL.md", "line": 1, "symbol": "z-research", "kind": "module", "summary": "Terrain mapping: cost gate, doc-fetcher first, up to 3 parallel Explore subagents, bundled cross-LLM critique, mandatory ## No-recommendation section."},
    {"file": "skills/z-review-all/SKILL.md", "line": 1, "symbol": "z-review-all", "kind": "module", "summary": "Final-gate two-pronged review: Phase 3.5 runs TESTS.md suite (blocker on failure), parallel consultants on cumulative diff, promotes findings to REVIEW-TASKS.md."},
    {"file": "skills/z-stats/SKILL.md", "line": 1, "symbol": "z-stats", "kind": "module", "summary": "Read-only diagnostic: shell+jq+awk only, no subagent calls; wall time, token spend, halts, stalls, plugin version history, suggested next command."},
    {"file": "skills/z-suggest-memory/SKILL.md", "line": 1, "symbol": "z-suggest-memory", "kind": "module", "summary": "Sole authoring path for memories[]: append/edit/delete modes, schema validation, atomic writes, MEMORIES-FLAT.md regen, optional human-tier refresh. Default: Cancel."},
    {"file": "skills/z-test/SKILL.md", "line": 1, "symbol": "z-test", "kind": "module", "summary": "Semantic test-case planner: risk-ranks tasks, requires non-trivial failure classes, cross-LLM consult drops trivial drafts, writes TESTS.md + cross-links into TASKS.md."}
  ],
  "depends_on": ["agents", "commands", "scripts"],
  "consumed_by": [],
  "invariants": [
    "All plan artifact paths are resolved through scripts/plan-path.sh to $Z_HARNESS_PLAN_DIR; no skill hardcodes z-harness/<slug>/ paths.",
    "Cross-LLM consult agents are always referenced as consultant-primary and consultant-secondary; code review uses the reviewer agent.",
    "Phase telemetry (log-phase.sh start/end) is mandatory for every skill execution.",
    "Review-generated spec-gap tasks are inputs to z-amend and must not authorize implementers to mutate planning artifacts directly.",
    "All skills implement idempotent run patterns; re-running modifies only targeted resources.",
    "z-suggest-memory is the sole path for creating, editing, or deleting memories[] entries; doc-updater only copies them verbatim."
  ],
  "gotchas": [
    "z-implement-all --tasks <path> skips slug discovery, tree validation, and ack/force-partial gates; $BASE is derived from the task file's parent directory.",
    "z-plan-split uses two distinct per-cluster identifiers: cluster_id (C1..CN) for telemetry, cluster_slug (kebab-case) for on-disk paths - never swap them.",
    "z-implement-all hard caps (MAX_ATTEMPTS=2, MAX_TASK_WALL_MS=45min, MAX_DISTINCT_HALTS=3) are unconditional and cannot be caught by skip-marker text matching.",
    "z-debug Phase 0 wrong-tool gate is non-skippable: if user already has a hypothesis, skill exits with /z-fix recommendation.",
    "z-review-all Phase 3.5 TESTS.md suite run is a blocker gate - any test failure halts the review before consultants are spawned.",
    "z-suggest-memory and z-init-docs both write docs/llm/TAGS.txt with the same 15-tag controlled seed via atomic write; neither overwrites if the file already exists."
  ],
  "memories": []
}

=== /Users/zeke/dev/z-harness/docs/human/skills.md ===
# Skills

> Last updated: 2026-05-24
> Covers source: skills/z-amend/SKILL.md, skills/z-brainstorm/SKILL.md, skills/z-debug/SKILL.md, skills/z-do/SKILL.md, skills/z-implement-all/SKILL.md, skills/z-implement-next/SKILL.md, skills/z-improve/SKILL.md, skills/z-init-docs/SKILL.md, skills/z-maintain-docs/SKILL.md, skills/z-plan-light/SKILL.md, skills/z-plan-split/SKILL.md, skills/z-plan/SKILL.md, skills/z-research/SKILL.md, skills/z-review-all/SKILL.md, skills/z-stats/SKILL.md, skills/z-suggest-memory/SKILL.md, skills/z-test/SKILL.md

## Overview

The skills concept covers the core operational guidelines, detailed checklists, and phase-by-phase procedures that govern every z-harness slash command execution. Each slash command maps to a matching skill directory containing a SKILL.md file. These documents are the ultimate authority on how planning, implementation, review, debugging, and documentation-maintenance runs are structured — including exact telemetry event shapes, subagent dispatch patterns, user-gate rules, and hard safety caps.

All skills share a common set of infrastructure assumptions established in the 2026-05-24 portable-harness migration: plan artifacts are resolved via `scripts/plan-path.sh` to `$Z_HARNESS_PLAN_DIR` (rather than hardcoded `z-harness/<slug>/` paths), cross-LLM consults use the provider-registry agents `consultant-primary` and `consultant-secondary`, and code review uses the `reviewer` agent. These agent names are stable identifiers that map to actual CLI vendors through the provider registry — skills never reference `gemini-consultant`, `codex-consultant`, or `codex-reviewer` directly.

## Key entry points

- `skills/z-amend/SKILL.md:1` — `z-amend` — Amend SPEC/PLAN/TASKS or FIX.md artifacts consistently. Phase 0 discovers the plan slug via `$Z_HARNESS_PLAN_DIR`. Complexity re-classification fires in Phase 6 for any task block whose body changed.
- `skills/z-brainstorm/SKILL.md:1` — `z-brainstorm` — Parallel pre-plan ideation: three vendor-diverse ideators (Claude + consultant-primary + consultant-secondary) with mandatory anti-bias check, producing BRAINSTORM.md with `chosen_framing`.
- `skills/z-debug/SKILL.md:1` — `z-debug` — Heavy hypothesis-tournament debug pipeline. Phase 0 wrong-tool gate redirects to `/z-fix` if user already has a hypothesis. Phases 3a/3b use rounds of parallel consultant hypothesis generation. Phase 9 post-mortem optionally invokes `/z-mr-review` and `/z-suggest-memory`.
- `skills/z-do/SKILL.md:1` — `z-do` — Lightest harness on-ramp for plan-less small tasks. Logs to `z-harness/adhoc/`. Codex review via `reviewer` agent is mandatory. Auto-bails at 3 files or non-obvious decisions.
- `skills/z-implement-all/SKILL.md:1` — `z-implement-all` — Orchestrates full task queue implementation. Supports `--tasks <path>` fast path for review artifacts (REVIEW-TASKS.md, MR-REVIEW.md). Tree-rooted plan support with MANIFEST.md/SHARED-CONCERNS.md validation gates and `--ack`/`--force-partial` overrides. Hard caps: `MAX_ATTEMPTS=2`, `MAX_TASK_WALL_MS=45min`, `MAX_DISTINCT_HALTS=3` per task.
- `skills/z-implement-next/SKILL.md:1` — `z-implement-next` — Single-task implementation. Picks implementer model from the task block's `**Complexity:**` stamp (`low|medium` → Sonnet, `high` → Opus). Single-shot; does not auto-retry on review failure.
- `skills/z-improve/SKILL.md:1` — `z-improve` — Post-run retro: analyzes `events.jsonl` friction signals, proposes ≤5 edits to z-harness files, applies accepted edits, then invokes `/z-suggest-memory` with derived `concept_hints`.
- `skills/z-init-docs/SKILL.md:1` — `z-init-docs` — Bootstraps the two-tier docs system. Phase 2 spawns `doc-updater` subagents per concept. Phase 4 writes `TAGS.txt` (15-tag controlled seed) and initializes `MEMORIES-FLAT.md` via `scripts/regenerate-memories-flat.py`.
- `skills/z-maintain-docs/SKILL.md:1` — `z-maintain-docs` — Refreshes stale docs. Phase 2 spawns `doc-updater` subagents with `dedup_tags: true`. Phase 3 surfaces stale memories and TAG_COLLISIONS. Phase 4.5 regenerates MEMORIES-FLAT.md after every write. Supports `--apply` and `--audit` flags.
- `skills/z-plan-light/SKILL.md:1` — `z-plan-light` — Lightweight planner for small fixes. Inline orchestrator implementation (no implementer subagent); Codex review via `reviewer` is non-negotiable. FIX.md is the only artifact. Auto-bails at >5 files or >2 non-obvious decisions.
- `skills/z-plan-split/SKILL.md:1` — `z-plan-split` — Pre-emptive scope splitter into 2-6 clusters. Enforces kebab-slug security gate. Phase 4 reconciles file-path overlaps from TASKS.md (canonical) against `FILES_TOUCHED` summary. Writes MANIFEST.md and SHARED-CONCERNS.md. MANIFEST uses stable `cluster_id` (C1…CN) for telemetry and `cluster_slug` for on-disk paths.
- `skills/z-plan/SKILL.md:1` — `z-plan` — Full rigorous planning pipeline. Docs-freshness gate checks `INDEX.json` staleness before Phase 1. Explore capped at 3 subagents. Phase 8 complexity-classifier stamps each task in parallel (Haiku).
- `skills/z-research/SKILL.md:1` — `z-research` — Terrain-mapping pre-plan research. Cost gate at Phase 0 (up to 3 Explores or 1). Phase 4 bundled cross-LLM critique. RESEARCH.md has mandatory `## No-recommendation` section with locked canonical text.
- `skills/z-review-all/SKILL.md:1` — `z-review-all` — Final-gate two-pronged cross-LLM review of cumulative diff. Phase 3.5 runs the full TESTS.md suite across affected modules before consulting LLMs (blocker if any test fails). Promotes findings to REVIEW-TASKS.md.
- `skills/z-stats/SKILL.md:1` — `z-stats` — Read-only diagnostic. Shell + jq + awk only; no subagent dispatch; no writes. Phases: plan progress, wall time per phase, token spend by model, recent halts, stall detection, plugin version history, suggested next command.
- `skills/z-suggest-memory/SKILL.md:1` — `z-suggest-memory` — Sole authoring path for `memories[]` in concept JSONs. Supports append/edit/delete modes. Validates against memory schema, writes atomically, regenerates MEMORIES-FLAT.md, optionally refreshes human-tier doc. Default outcome is Cancel.
- `skills/z-test/SKILL.md:1` — `z-test` — Semantic test-case planner between `/z-plan` and `/z-implement-all`. Risk-ranks tasks on domain criticality, surface area, and test-gap signal. Non-trivial failure classes required; trivial mechanical tests rejected by cross-LLM consult. Writes TESTS.md and cross-links `**Tests:**` lines into TASKS.md.

## How it interacts with others

- `commands` — Slash commands are the user-facing triggers that invoke the skill pipelines defined here.
- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic.
- `scripts` — Skills call `plan-path.sh` to resolve `$Z_HARNESS_PLAN_DIR`, `log-event.sh` for telemetry, `version.sh` for run stamps, `log-phase.sh` for timing, and `regenerate-memories-flat.py` for memory flat-file sync.
- `z-amend` remains the authority for applying review-generated spec-gap proposals; promoted amendment tasks in REVIEW-TASKS.md are inputs to the amendment workflow, not permission for implementers to edit planning artifacts autonomously.

## Edge cases / gotchas

- All skills resolve plan artifact paths via `$Z_HARNESS_PLAN_DIR` (set by `scripts/plan-path.sh`), not by hardcoded `z-harness/<slug>/` paths. Legacy flat layout (`z-harness/TASKS.md`) is still supported by most skills.
- `z-implement-all --tasks <path>` skips slug discovery, tree validation, and `--ack`/`--force-partial` checks. `$BASE` is derived from the task file's parent directory, so SPEC.md and archive paths resolve next to the promoted artifact.
- `z-debug` Phase 0 wrong-tool gate is non-skippable. If the user already has a hypothesis, the skill exits with a `/z-fix` recommendation rather than proceeding.
- `z-plan-split` uses two distinct identifiers per cluster: `cluster_id` (`C1`, `C2`, …) for telemetry payloads, and `cluster_slug` (kebab-case name) for on-disk directory paths. These must never be swapped.
- `z-implement-all` has unconditional hard caps (`MAX_ATTEMPTS=2` per task, 45-min wall clock per track, `MAX_DISTINCT_HALTS=3`) that override skip-marker lists and cannot be caught by static text matching alone.
- `z-suggest-memory` bootstraps `docs/llm/TAGS.txt` in Phase 0 if it is absent; `z-init-docs` Phase 4 also writes it. Both use the same 15-tag controlled seed and atomic write pattern.
- Phase telemetry (log-phase.sh start/end) is mandatory for every skill. Missing brackets make `/z-stats` wall-time analysis incorrect.

## Examples

- Reading the z-amend workflow to understand how review-generated amendment proposals are routed:
  Read `skills/z-amend/SKILL.md` Phase 4 (user gate) and Phase 6 (propagation) for the full checklist.
- Checking why `/z-implement-all` refused a tree-rooted plan:
  Read `skills/z-implement-all/SKILL.md` Setup 2b for the MANIFEST validation gate sequence (6 checks before any task runs).


Diff (primary artifact — focus your scrutiny on what changed):

diff --git a/commands/z-do.md b/commands/z-do.md
index b510391..143c04b 100644
--- a/commands/z-do.md
+++ b/commands/z-do.md
@@ -1,5 +1,5 @@
 ---
-description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
+description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
 argument-hint: <small task description>
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
diff --git a/commands/z-plan-light.md b/commands/z-plan-light.md
index 4fed423..48a3515 100644
--- a/commands/z-plan-light.md
+++ b/commands/z-plan-light.md
@@ -1,5 +1,5 @@
 ---
-description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan if scope grows beyond ~5 files or >2 non-obvious decisions.
+description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit.
 argument-hint: <fix description>
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
diff --git a/skills/z-do/SKILL.md b/skills/z-do/SKILL.md
index b510391..4136a29 100644
--- a/skills/z-do/SKILL.md
+++ b/skills/z-do/SKILL.md
@@ -1,5 +1,6 @@
 ---
-description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Auto-bails to /z-plan-light if scope grows past ~3 files or any non-obvious decision surfaces.
+name: z-do
+description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
 argument-hint: <small task description>
 ---
 
@@ -16,7 +17,8 @@ $ARGUMENTS
 1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
 2. `export Z_HARNESS_SLUG=adhoc`
 3. `mkdir -p z-harness/adhoc/archive/$RUN`
-4. **Version stamp + log:**
+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
+5. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -26,18 +28,38 @@ $ARGUMENTS
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
 
@@ -72,7 +94,7 @@ In a single short message to yourself, state:
 
 Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
 
-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
 
 ## Phase 4 — Implement inline
 
@@ -85,9 +107,8 @@ Edit / Write the files. Apply the implementer self-check:
 5. No stale docstrings / comments left behind.
 
 If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
-- "Continue in z-do — update approach.md"
-- "Escalate to /z-plan-light"
-- "Escalate to /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
 - "Abandon"
 
 Hard limit: if you find yourself touching >5 files inline, halt regardless.
@@ -153,7 +174,7 @@ Apply the "one reason it might be wrong" check to each finding. If it raises a r
 - **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
 - **No upfront cross-LLM consult.** Only at the end, only if triggered.
 - **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Never read `docs/llm/*.json` from main thread.**
 - **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
 - **No emojis.**
diff --git a/skills/z-plan-light/SKILL.md b/skills/z-plan-light/SKILL.md
index 4fed423..aa52538 100644
--- a/skills/z-plan-light/SKILL.md
+++ b/skills/z-plan-light/SKILL.md
@@ -1,5 +1,6 @@
 ---
-description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Auto-bails to /z-plan if scope grows beyond ~5 files or >2 non-obvious decisions.
+name: z-plan-light
+description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit.
 argument-hint: <fix description>
 ---
 
@@ -11,7 +12,7 @@ $ARGUMENTS
 
 **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
 
-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
 
 ## Setup
 
@@ -19,7 +20,8 @@ This command is for **small, focused changes**. If at any phase you realize the
 2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
 3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
 4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
-5. **Version stamp + log:**
+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
+6. **Version stamp + log:**
    ```bash
    VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    START_PAYLOAD="$(python3 -c '
@@ -29,10 +31,25 @@ This command is for **small, focused changes**. If at any phase you realize the
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
 
@@ -41,7 +58,12 @@ At any phase, if you discover:
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
 
@@ -63,13 +85,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
 
 Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
 
-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
 
 ## Phase 2 — Identify the single key decision
 
 Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
 
-If there are >2 truly non-obvious decisions, **bail to `/z-plan`** — the cross-decision interaction analysis that full `/z-plan` does is worth it.
+If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
 
 ## Phase 3 — Bundled cross-LLM consult
 
@@ -168,8 +190,8 @@ The orchestrator (you, in main thread) reads the files listed in FIX.md "Files t
 If you applied any fix from the checklist, note it in the user-facing summary later.
 
 **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
-- "Continue in light mode — update FIX.md and proceed"
-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
+- "Switch to the recommended routed command"
+- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
 - "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"
 
 Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.
@@ -215,7 +237,7 @@ Parse the return (already capped at 8 KB, blockers + majors only).
 ## Hard rules
 
 - **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
-- **Never proceed past auto-bail thresholds** without explicit user override.
+- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
 - **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.
 - **Never overwrite an existing `$Z_HARNESS_PLAN_DIR/` directory** without asking the user.
 - **No emojis** anywhere in artifacts.


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
I’ll verify the changed files directly so the review can point at concrete line numbers and catch any nearby context the diff omitted.
exec
/bin/zsh -lc "nl -ba skills/z-plan-light/SKILL.md | sed -n '1,120p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba commands/z-plan-light.md | sed -n '1,120p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba skills/z-do/SKILL.md | sed -n '1,130p'" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "nl -ba commands/z-do.md | sed -n '1,130p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
     1	---
     2	description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
     3	argument-hint: <small task description>
     4	---
     5	
     6	You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
     7	
     8	Task (from `$ARGUMENTS`):
     9	
    10	$ARGUMENTS
    11	
    12	**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.
    13	
    14	## Setup
    15	
    16	1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
    17	2. `export Z_HARNESS_SLUG=adhoc`
    18	3. `mkdir -p z-harness/adhoc/archive/$RUN`
    19	4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
    20	5. **Version stamp + log:**
    21	   ```bash
    22	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    23	   START_PAYLOAD="$(python3 -c '
    24	   import json, sys
    25	   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
    26	   print(json.dumps(v))
    27	   ' "$VERSION_BLOB" "<arguments>")"
    28	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    29	   ```
    30	6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
    31	
    32	## Plan Route Check
    33	
    34	<!-- PLAN_ROUTE_CHECK_START -->
    35	Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
    36	
    37	Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
    38	
    39	Deterministic routes:
    40	- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
    41	- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
    42	- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
    43	- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
    44	- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
    45	- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
    46	
    47	Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
    48	
    49	If at any point you discover:
    50	
    51	- **>3 files** need editing
    52	- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
    53	- **Cross-module / cross-crate impact** OR **schema change**
    54	- User says "this might be bigger than I thought"
    55	
    56	→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
    57	
    58	`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
    59	
    60	Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
    61	<!-- PLAN_ROUTE_CHECK_END -->
    62	
    63	## Phase 1 — Premise check (mandatory, quick)
    64	
    65	One paragraph in main thread: is the stated task actually the right problem? Could it be config, expected behavior, or symptom of something else? Is there a materially better path?
    66	
    67	If a concern surfaces → raise via `AskUserQuestion` before proceeding. Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.
    68	
    69	Save to `z-harness/adhoc/archive/$RUN/premise.md`.
    70	
    71	## Phase 2 — Ground (doc-fetcher first)
    72	
    73	Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
    74	
    75	```
    76	Agent(subagent_type="doc-fetcher",
    77	      description="Doc context for: <task>",
    78	      prompt="query: <one-sentence task>\nrepo_root: <abs path>\ndepth: standard")
    79	```
    80	
    81	Use its return to constrain what files you read next. If `STATUS: no_docs` / `no_match` / `partial`, fall back to direct Read/Grep/Glob — do NOT spawn Explore in `/z-do` (too expensive for this command).
    82	
    83	Read at most 3-5 files from main thread to fill gaps.
    84	
    85	If a `DRIFT WARNING` came back, log `doc_drift` and continue.
    86	
    87	## Phase 3 — Inline approach note (NO decisions.md, NO upfront consult)
    88	
    89	In a single short message to yourself, state:
    90	- What you're about to change (2-3 sentences)
    91	- Files to touch (list)
    92	- Acceptance: how you'll know it worked
    93	
    94	Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
    95	
    96	**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
    97	
    98	## Phase 4 — Implement inline
    99	
   100	Edit / Write the files. Apply the implementer self-check:
   101	
   102	1. No broad exception handlers added.
   103	2. No scope expansion outside `approach.md` "Files to touch".
   104	3. No unsolicited validation / error paths.
   105	4. No new public surface beyond what `approach.md` describes.
   106	5. No stale docstrings / comments left behind.
   107	
   108	If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
   109	- "Switch to the recommended routed command"
   110	- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
   111	- "Abandon"
   112	
   113	Hard limit: if you find yourself touching >5 files inline, halt regardless.
   114	
   115	## Phase 5 — Codex review (MANDATORY safety gate)
   116	
   117	Non-negotiable. This is what makes `/z-do` z-harness rather than freewheeling.
   118	
   119	```bash
   120	git diff > z-harness/adhoc/archive/$RUN/diff.patch
   121	```
   122	
   123	Spawn the reviewer:
   124	
   125	```
   126	Agent(
   127	  subagent_type="reviewer",
   128	  description="Codex review of /z-do <run>",
   129	  prompt="task id: <RUN>\ntask description: <approach.md body, ≤500 chars>\nacceptance criteria: <approach.md Acceptance line>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\n$BASE: z-harness/adhoc/archive/$RUN  (read approach.md and premise.md yourself if you need more context)"
   130	)

 succeeded in 0ms:
     1	---
     2	name: z-plan-light
     3	description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit.
     4	argument-hint: <fix description>
     5	---
     6	
     7	You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.
     8	
     9	Task (from `$ARGUMENTS`):
    10	
    11	$ARGUMENTS
    12	
    13	**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
    14	
    15	This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
    16	
    17	## Setup
    18	
    19	1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
    20	2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
    21	3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
    22	4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
    23	5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
    24	6. **Version stamp + log:**
    25	   ```bash
    26	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    27	   START_PAYLOAD="$(python3 -c '
    28	   import json, sys
    29	   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
    30	   print(json.dumps(v))
    31	   ' "$VERSION_BLOB" "<arguments>")"
    32	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    33	   ```
    34	7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
    35	8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
    36	
    37	## Plan Route Check
    38	
    39	<!-- PLAN_ROUTE_CHECK_START -->
    40	Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
    41	
    42	Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
    43	
    44	Deterministic routes:
    45	- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
    46	- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
    47	- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
    48	- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
    49	- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
    50	- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
    51	
    52	Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
    53	
    54	At any phase, if you discover:
    55	
    56	- **>5 candidate files** need editing
    57	- **>2 non-obvious decisions** (per the rules `/z-plan` uses: new dep, public API change, algorithm with materially different tradeoffs, persistence change)
    58	- **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
    59	- **The user explicitly says** "this might be bigger than I thought"
    60	
    61	→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
    62	
    63	`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
    64	
    65	Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
    66	<!-- PLAN_ROUTE_CHECK_END -->
    67	
    68	## Phase 1 — Premise + quick exploration (combined)
    69	
    70	**Premise check.** Don't take the task description for granted:
    71	- Is this actually a bug? Could it be config / expected behavior / a symptom of something else?
    72	- Will the proposed fix (if the user named one) actually solve the underlying problem?
    73	- Is there a materially better path the user hasn't considered?
    74	
    75	If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.
    76	
    77	**Quick exploration.**
    78	1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
    79	   ```
    80	   Agent(subagent_type="doc-fetcher",
    81	         description="Doc context for <slug>",
    82	         prompt="query: <one-sentence fix description>\nrepo_root: <abs path>\ndepth: standard")
    83	   ```
    84	2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
    85	
    86	Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
    87	
    88	**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
    89	
    90	## Phase 2 — Identify the single key decision
    91	
    92	Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
    93	
    94	If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
    95	
    96	## Phase 3 — Bundled cross-LLM consult
    97	
    98	Spawn both consultants in parallel in a single message:
    99	
   100	```
   101	Agent(
   102	  subagent_type="consultant-primary",
   103	  description="Light-fix consult (Gemini) for <slug>",
   104	  prompt="MODE: light-fix\n\nProblem: <1-paragraph>\nContext: <1-paragraph>\nKey decision: <statement>\nCandidate options (if any): <list with one-line tradeoffs>\nRelevant code snippets:\n<short quoted code with file:line markers>\n\nAsk: recommend an option with reasoning. Identify tradeoffs. Flag anything I haven't considered. Be concise — this is a single small fix, not a feature."
   105	)
   106	Agent(
   107	  subagent_type="consultant-secondary",
   108	  description="Light-fix consult (Codex) for <slug>",
   109	  prompt="MODE: light-fix\n\n<same prompt body>"
   110	)
   111	```
   112	
   113	Both transcripts archive themselves under `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/`.
   114	
   115	## Phase 4 — Synthesize + push back
   116	
   117	When both return:
   118	
   119	1. **One reason it might be wrong.** For each recommendation, articulate one concrete reason it could be wrong before accepting it. Mechanical, not optional.
   120	2. **Synthesize.** Make the final call yourself, citing what you weighed.

 succeeded in 0ms:
     1	---
     2	description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit.
     3	argument-hint: <fix description>
     4	---
     5	
     6	You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.
     7	
     8	Task (from `$ARGUMENTS`):
     9	
    10	$ARGUMENTS
    11	
    12	**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
    13	
    14	This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
    15	
    16	## Setup
    17	
    18	1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
    19	2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
    20	3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
    21	4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
    22	5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
    23	6. **Version stamp + log:**
    24	   ```bash
    25	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    26	   START_PAYLOAD="$(python3 -c '
    27	   import json, sys
    28	   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
    29	   print(json.dumps(v))
    30	   ' "$VERSION_BLOB" "<arguments>")"
    31	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
    32	   ```
    33	7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
    34	8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.
    35	
    36	## Plan Route Check
    37	
    38	<!-- PLAN_ROUTE_CHECK_START -->
    39	Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.
    40	
    41	Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.
    42	
    43	Deterministic routes:
    44	- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
    45	- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
    46	- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
    47	- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
    48	- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
    49	- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.
    50	
    51	Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
    52	
    53	At any phase, if you discover:
    54	
    55	- **>5 candidate files** need editing
    56	- **>2 non-obvious decisions** (per the rules `/z-plan` uses: new dep, public API change, algorithm with materially different tradeoffs, persistence change)
    57	- **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
    58	- **The user explicitly says** "this might be bigger than I thought"
    59	
    60	→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
    61	
    62	`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
    63	
    64	Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
    65	<!-- PLAN_ROUTE_CHECK_END -->
    66	
    67	## Phase 1 — Premise + quick exploration (combined)
    68	
    69	**Premise check.** Don't take the task description for granted:
    70	- Is this actually a bug? Could it be config / expected behavior / a symptom of something else?
    71	- Will the proposed fix (if the user named one) actually solve the underlying problem?
    72	- Is there a materially better path the user hasn't considered?
    73	
    74	If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.
    75	
    76	**Quick exploration.**
    77	1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
    78	   ```
    79	   Agent(subagent_type="doc-fetcher",
    80	         description="Doc context for <slug>",
    81	         prompt="query: <one-sentence fix description>\nrepo_root: <abs path>\ndepth: standard")
    82	   ```
    83	2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.
    84	
    85	Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.
    86	
    87	**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
    88	
    89	## Phase 2 — Identify the single key decision
    90	
    91	Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.
    92	
    93	If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.
    94	
    95	## Phase 3 — Bundled cross-LLM consult
    96	
    97	Spawn both consultants in parallel in a single message:
    98	
    99	```
   100	Agent(
   101	  subagent_type="consultant-primary",
   102	  description="Light-fix consult (Gemini) for <slug>",
   103	  prompt="MODE: light-fix\n\nProblem: <1-paragraph>\nContext: <1-paragraph>\nKey decision: <statement>\nCandidate options (if any): <list with one-line tradeoffs>\nRelevant code snippets:\n<short quoted code with file:line markers>\n\nAsk: recommend an option with reasoning. Identify tradeoffs. Flag anything I haven't considered. Be concise — this is a single small fix, not a feature."
   104	)
   105	Agent(
   106	  subagent_type="consultant-secondary",
   107	  description="Light-fix consult (Codex) for <slug>",
   108	  prompt="MODE: light-fix\n\n<same prompt body>"
   109	)
   110	```
   111	
   112	Both transcripts archive themselves under `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/`.
   113	
   114	## Phase 4 — Synthesize + push back
   115	
   116	When both return:
   117	
   118	1. **One reason it might be wrong.** For each recommendation, articulate one concrete reason it could be wrong before accepting it. Mechanical, not optional.
   119	2. **Synthesize.** Make the final call yourself, citing what you weighed.
   120	3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.

 succeeded in 0ms:
     1	---
     2	name: z-do
     3	description: Plan-less z-harness execution for small tasks. Brings the harness discipline — premise check, doc-fetcher grounding, codex review safety gate, structured logging — without SPEC/PLAN/TASKS/FIX.md ceremony. Logs to z-harness/adhoc/ so /z-improve can retro it. Routes to the right planning/debug workflow when scope or bug signals exceed direct execution.
     4	argument-hint: <small task description>
     5	---
     6	
     7	You are running **z-harness `/z-do`** — the lightest harness on-ramp. No slug, no plan artifacts, no upfront cross-LLM consult. Just: premise check, doc-fetcher grounding, inline implementation, codex review.
     8	
     9	Task (from `$ARGUMENTS`):
    10	
    11	$ARGUMENTS
    12	
    13	**If empty**, use `AskUserQuestion`: "What's the task?" Block until answered.
    14	
    15	## Setup
    16	
    17	1. Pick run id: `RUN=$(date -u +%Y-%m-%dT%H:%M:%SZ)-do`
    18	2. `export Z_HARNESS_SLUG=adhoc`
    19	3. `mkdir -p z-harness/adhoc/archive/$RUN`
    20	4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
    21	5. **Version stamp + log:**
    22	   ```bash
    23	   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
    24	   START_PAYLOAD="$(python3 -c '
    25	   import json, sys
    26	   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
    27	   print(json.dumps(v))
    28	   ' "$VERSION_BLOB" "<arguments>")"
    29	   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
    30	   ```
    31	6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
    32	
    33	## Plan Route Check
    34	
    35	<!-- PLAN_ROUTE_CHECK_START -->
    36	Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.
    37	
    38	Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.
    39	
    40	Deterministic routes:
    41	- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
    42	- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
    43	- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
    44	- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
    45	- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
    46	- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.
    47	
    48	Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
    49	
    50	If at any point you discover:
    51	
    52	- **>3 files** need editing
    53	- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
    54	- **Cross-module / cross-crate impact** OR **schema change**
    55	- User says "this might be bigger than I thought"
    56	
    57	→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
    58	
    59	`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
    60	
    61	Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
    62	<!-- PLAN_ROUTE_CHECK_END -->
    63	
    64	## Phase 1 — Premise check (mandatory, quick)
    65	
    66	One paragraph in main thread: is the stated task actually the right problem? Could it be config, expected behavior, or symptom of something else? Is there a materially better path?
    67	
    68	If a concern surfaces → raise via `AskUserQuestion` before proceeding. Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.
    69	
    70	Save to `z-harness/adhoc/archive/$RUN/premise.md`.
    71	
    72	## Phase 2 — Ground (doc-fetcher first)
    73	
    74	Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:
    75	
    76	```
    77	Agent(subagent_type="doc-fetcher",
    78	      description="Doc context for: <task>",
    79	      prompt="query: <one-sentence task>\nrepo_root: <abs path>\ndepth: standard")
    80	```
    81	
    82	Use its return to constrain what files you read next. If `STATUS: no_docs` / `no_match` / `partial`, fall back to direct Read/Grep/Glob — do NOT spawn Explore in `/z-do` (too expensive for this command).
    83	
    84	Read at most 3-5 files from main thread to fill gaps.
    85	
    86	If a `DRIFT WARNING` came back, log `doc_drift` and continue.
    87	
    88	## Phase 3 — Inline approach note (NO decisions.md, NO upfront consult)
    89	
    90	In a single short message to yourself, state:
    91	- What you're about to change (2-3 sentences)
    92	- Files to touch (list)
    93	- Acceptance: how you'll know it worked
    94	
    95	Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.
    96	
    97	**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
    98	
    99	## Phase 4 — Implement inline
   100	
   101	Edit / Write the files. Apply the implementer self-check:
   102	
   103	1. No broad exception handlers added.
   104	2. No scope expansion outside `approach.md` "Files to touch".
   105	3. No unsolicited validation / error paths.
   106	4. No new public surface beyond what `approach.md` describes.
   107	5. No stale docstrings / comments left behind.
   108	
   109	If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
   110	- "Switch to the recommended routed command"
   111	- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
   112	- "Abandon"
   113	
   114	Hard limit: if you find yourself touching >5 files inline, halt regardless.
   115	
   116	## Phase 5 — Codex review (MANDATORY safety gate)
   117	
   118	Non-negotiable. This is what makes `/z-do` z-harness rather than freewheeling.
   119	
   120	```bash
   121	git diff > z-harness/adhoc/archive/$RUN/diff.patch
   122	```
   123	
   124	Spawn the reviewer:
   125	
   126	```
   127	Agent(
   128	  subagent_type="reviewer",
   129	  description="Codex review of /z-do <run>",
   130	  prompt="task id: <RUN>\ntask description: <approach.md body, ≤500 chars>\nacceptance criteria: <approach.md Acceptance line>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\n$BASE: z-harness/adhoc/archive/$RUN  (read approach.md and premise.md yourself if you need more context)"

codex
- **Major** — [commands/z-do.md](/Users/zeke/dev/z-harness/commands/z-do.md:56) and [skills/z-do/SKILL.md](/Users/zeke/dev/z-harness/skills/z-do/SKILL.md:57): the legacy `escalation.md` artifact is removed without making it a compatibility copy or pointer, so existing consumers that expect `escalation.md` lose the branch artifact even though the spec allows replacement only if legacy terminal/run-end compatibility is preserved. Add an explicit instruction to write `escalation.md` as a pointer/copy to `$CURRENT_ARCHIVE_DIR/route-decision.md` or otherwise prove no consumer depends on it.

- **Major** — [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:60) and [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:61): the old `$Z_HARNESS_PLAN_DIR/escalation.md` artifact is dropped with only vague “legacy escalation status” wording, which does not satisfy the compatibility-copy/pointer path and can break tools or humans looking for the prior escalation file. Add a concrete compatibility instruction to create `$Z_HARNESS_PLAN_DIR/escalation.md` as a pointer/copy to `$CURRENT_ARCHIVE_DIR/route-decision.md`.

- **Major** — [commands/z-do.md](/Users/zeke/dev/z-harness/commands/z-do.md:58), [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:62), [skills/z-do/SKILL.md](/Users/zeke/dev/z-harness/skills/z-do/SKILL.md:59), [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:63): the route artifact contract is underspecified and omits the required Markdown section template, including exact heading shape, `## Recommendation`, `## Reason`, `## Signals`, `## Route Chain`, and `## Resume Context`. Insert the required template verbatim so route artifacts are parseable and consistent across commands.

- **Major** — [commands/z-do.md](/Users/zeke/dev/z-harness/commands/z-do.md:58), [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:62), [skills/z-do/SKILL.md](/Users/zeke/dev/z-harness/skills/z-do/SKILL.md:59), [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:63): telemetry is described only as field names, with no required `log-event.sh` invocation shape or requirement that `artifact_path` be relative to repo root and `reason_codes`/`signals`/`route_chain` be JSON values. Add the concrete `bash ... log-event.sh "$RUN" plan_route_decision "$(printf ...)"` pattern or equivalent explicit JSON construction rules.

- **Major** — [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:168) and [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:190): the mid-implementation escape hatch still has an independent user prompt path and includes “Spawn implementer subagent” even after the route contract says routing decisions must use the shared route artifact and AskUser handoff gate. Replace this branch with the Plan Route Check gate, remove non-route options that can conflict with the routed recommendation, and log `plan_route_decision` before asking.
tokens used
70,314
- **Major** — [commands/z-do.md](/Users/zeke/dev/z-harness/commands/z-do.md:56) and [skills/z-do/SKILL.md](/Users/zeke/dev/z-harness/skills/z-do/SKILL.md:57): the legacy `escalation.md` artifact is removed without making it a compatibility copy or pointer, so existing consumers that expect `escalation.md` lose the branch artifact even though the spec allows replacement only if legacy terminal/run-end compatibility is preserved. Add an explicit instruction to write `escalation.md` as a pointer/copy to `$CURRENT_ARCHIVE_DIR/route-decision.md` or otherwise prove no consumer depends on it.

- **Major** — [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:60) and [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:61): the old `$Z_HARNESS_PLAN_DIR/escalation.md` artifact is dropped with only vague “legacy escalation status” wording, which does not satisfy the compatibility-copy/pointer path and can break tools or humans looking for the prior escalation file. Add a concrete compatibility instruction to create `$Z_HARNESS_PLAN_DIR/escalation.md` as a pointer/copy to `$CURRENT_ARCHIVE_DIR/route-decision.md`.

- **Major** — [commands/z-do.md](/Users/zeke/dev/z-harness/commands/z-do.md:58), [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:62), [skills/z-do/SKILL.md](/Users/zeke/dev/z-harness/skills/z-do/SKILL.md:59), [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:63): the route artifact contract is underspecified and omits the required Markdown section template, including exact heading shape, `## Recommendation`, `## Reason`, `## Signals`, `## Route Chain`, and `## Resume Context`. Insert the required template verbatim so route artifacts are parseable and consistent across commands.

- **Major** — [commands/z-do.md](/Users/zeke/dev/z-harness/commands/z-do.md:58), [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:62), [skills/z-do/SKILL.md](/Users/zeke/dev/z-harness/skills/z-do/SKILL.md:59), [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:63): telemetry is described only as field names, with no required `log-event.sh` invocation shape or requirement that `artifact_path` be relative to repo root and `reason_codes`/`signals`/`route_chain` be JSON values. Add the concrete `bash ... log-event.sh "$RUN" plan_route_decision "$(printf ...)"` pattern or equivalent explicit JSON construction rules.

- **Major** — [commands/z-plan-light.md](/Users/zeke/dev/z-harness/commands/z-plan-light.md:168) and [skills/z-plan-light/SKILL.md](/Users/zeke/dev/z-harness/skills/z-plan-light/SKILL.md:190): the mid-implementation escape hatch still has an independent user prompt path and includes “Spawn implementer subagent” even after the route contract says routing decisions must use the shared route artifact and AskUser handoff gate. Replace this branch with the Plan Route Check gate, remove non-route options that can conflict with the routed recommendation, and log `plan_route_decision` before asking.
