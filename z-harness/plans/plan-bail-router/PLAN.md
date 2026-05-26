# Plan: Plan Bail Router

## Goal

Make the z-harness planning-family entry points mutually route-aware so they can stop early, preserve context, and guide the user to the workflow that fits the current scope.

## Non-Goals

- Do not automatically execute another slash command from inside a running command.
- Do not replace existing command-specific safety gates.
- Do not make `/z-audit-plan` a front-door planning command.
- Do not add a generated include system for command Markdown in this plan.
- Do not implement production code during planning.

## Decisions

### Router Shape

Use a canonical route policy in docs/memory and embed compact standalone `Plan Route Check` blocks in participating commands and skills. The blocks should be bracketed with HTML sentinels so drift can be detected later.

Rejected:

- Runtime include only: breaks standalone exported prompts.
- Dedicated pre-router slash command only: adds friction and does not help mid-flow bails.

### Route Targets

Use two route classes.

Primary matrix:

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

`/z-audit-plan` is contextual because it requires existing plan artifacts.

### Metric and Classifier

Use deterministic signals first. Add a new `planning-router` Haiku agent only for ambiguous cases. Do not extend `complexity-classifier`; it classifies task blocks after planning, while route decisions classify a raw task/topic plus partial signals before or during planning.

Amendment 2026-05-24: `planning-router` has three parseable statuses: `routed` for concrete command recommendations, `ask_user` for loop-risk or conflicting-signal cases, and `bad_input` for malformed payloads.

### Bail Semantics

Use an AskUser handoff gate:

- write `route-decision.md`
- log `plan_route_decision`
- offer switch / continue if allowed / abandon
- stop current flow if the user chooses switch

This is less abrupt than pure halt-and-recommend, but avoids unsafe automatic handoff.

### Telemetry

Add shared `plan_route_decision` events. Keep existing command-specific run-end events and escalation statuses.

### Propagation

Edit canonical source files and docs/memory. Regenerate exports via existing scripts. Do not hand-edit generated exports as the source of truth.

## Approved Shortcuts

None.

## Design Notes

The router should be cheap. Commands should not do extra repo exploration only to decide whether they are the right command. They should use already-known signals from setup, docs gates, precontext artifacts, quick file estimates, and phase outputs. The optional `planning-router` agent is reserved for cases where those signals conflict.

Loop prevention matters because the family includes both lighter and heavier modes. A route chain and ping-pong check are enough for v1; a global router state store would be unnecessary.

## Implementation Phases

### Phase 1 - Add Planning Router Agent

Create `agents/planning-router.md` with a tight Haiku prompt and parseable return shape. Document that it is advisory, read-only, and only receives compact signals.

Update agent docs/memory to include the new agent.

### Phase 2 - Define Shared Contract and Legacy Compatibility

Add the route artifact template, `plan_route_decision` event contract, `$CURRENT_ARCHIVE_DIR` guidance, loop-prevention rules, and AskUser handoff language to the command/skill route blocks.

Explicitly reconcile existing escalation paths:

- `/z-do` should not have an independent old escalation prompt and a new route prompt.
- `/z-plan-light` should not have an independent old escalation prompt and a new route prompt.
- Existing legacy event names may stay as terminal compatibility events, but the user-facing artifact should be `route-decision.md`.

### Phase 3 - Define Route Check Blocks

Add `Plan Route Check` blocks to canonical command sources:

- `commands/z-do.md`
- `commands/z-plan-light.md`
- `commands/z-plan.md`
- `commands/z-plan-split.md`
- `commands/z-brainstorm.md`
- `commands/z-research.md`
- `commands/z-audit-plan.md`

Each block should be command-specific but follow the same structure:

- when to run the check
- signals to inspect
- deterministic routes
- when to call `planning-router`
- route artifact and telemetry
- AskUser handoff gate
- loop prevention

The insertion point for each command must match the SPEC's route-check insertion table.

### Phase 4 - Mirror Skill Checklists

Update matching skills:

- `skills/z-do/SKILL.md`
- `skills/z-plan-light/SKILL.md`
- `skills/z-plan/SKILL.md`
- `skills/z-plan-split/SKILL.md`
- `skills/z-brainstorm/SKILL.md`
- `skills/z-research/SKILL.md`
- `skills/z-audit-plan/SKILL.md`

The skill text should mirror command behavior closely enough that Cursor/Codex/Antigravity users get the same routing policy.

### Phase 5 - Docs and Memory Updates

Update stale docs/memory entries:

- include `z-audit-plan` in command and skill source lists and entry points
- include `planning-router` in agent lists and entry points
- document `plan_route_decision`
- document primary routes and contextual exits

Because docs are already stale, keep this task focused on route-related doc correctness and leave broader cleanup to `/z-maintain-docs`.

### Phase 6 - Regenerate Exports

Run:

```bash
python3 scripts/export-cursor.py
python3 scripts/export-codex.py
python3 scripts/export-agy.py
```

Verify generated exports include updated command/skill route checks and the new agent prompt.

### Phase 7 - Validation

Run lightweight checks:

- `python3 -m json.tool docs/llm/INDEX.json`
- `python3 -m json.tool docs/llm/commands.json`
- `python3 -m json.tool docs/llm/skills.json`
- `python3 -m json.tool docs/llm/agents.json`
- export scripts complete successfully
- targeted search confirms sentinels are present in all intended command and skill sources
- scenario checklist from SPEC is manually verified or recorded in the implementation summary

## DRY / KISS / SOLID

DRY: The policy has one canonical spec and mirrored compact blocks with sentinels. A code-generation system is intentionally deferred until drift proves painful.

KISS: Routing is deterministic by default. The classifier only handles ambiguity and has a small parseable contract.

SOLID: The new `planning-router` agent has one responsibility: classify ambiguous route decisions. Existing commands keep their own artifact and safety responsibilities.

## Risks

- Embedded blocks can drift. Mitigation: sentinels and docs/memory canonical policy.
- Classifier can overrule obvious thresholds. Mitigation: classifier is advisory and only used for ambiguous cases.
- User friction can increase. Mitigation: AskUser gate only appears when the command would otherwise bail or route.
- `/z-research` could accidentally recommend approaches. Mitigation: route recommendations happen before research or after finalization, never inside `RESEARCH.md`.
- Existing escalation text could conflict with route text. Mitigation: replace or alias old user-facing escalation artifacts rather than adding a second prompt.

## Acceptance

- Every primary route command has a route check block.
- Every matching skill has a route check block.
- `planning-router` exists and has a parseable return contract.
- `plan_route_decision` telemetry is specified in source prompts.
- `/z-audit-plan` is treated as contextual only.
- Docs/memory include `z-audit-plan` and `planning-router`.
- Exports regenerate successfully.
- Scenario acceptance from SPEC is verified.
