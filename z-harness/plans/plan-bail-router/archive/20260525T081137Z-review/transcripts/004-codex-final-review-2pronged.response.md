2026-05-25T08:14:23.550657Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-maintain-docs/SKILL.md: invalid YAML: did not find expected key at line 3 column 41, while parsing a block mapping
2026-05-25T08:14:23.551128Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-stats/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
2026-05-25T08:14:23.551138Z ERROR codex_core::session::session: failed to load skill /Users/zeke/.codex/skills/z-review-all/SKILL.md: invalid YAML: did not find expected key at line 3 column 32, while parsing a block mapping
OpenAI Codex v0.133.0
--------
workdir: /Users/zeke/dev/z-harness
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
reasoning effort: medium
reasoning summaries: none
session id: 019e5e33-0620-7670-8fb1-450203a0b09e
--------
user
Mode: final-review-2pronged

You are Codex performing the Codex-side final gate review for a z-harness plan.

Repo root: /Users/zeke/dev/z-harness
Plan slug: plan-bail-router
Base: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router
Review run: 20260525T081137Z-review
Base ref: HEAD working tree; changes are uncommitted. Base short message is recorded at /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/base-ref.txt

Inputs to read:
- SPEC: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/SPEC.md
- PLAN: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/PLAN.md
- TASKS: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/TASKS.md
- cumulative diff: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff
- cumulative stat: /Users/zeke/dev/z-harness/z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.stat
- docs index: /Users/zeke/dev/z-harness/docs/llm/INDEX.json
- relevant concept docs: /Users/zeke/dev/z-harness/docs/llm/agents.json, /Users/zeke/dev/z-harness/docs/llm/commands.json, /Users/zeke/dev/z-harness/docs/llm/skills.json

Important context:
- The cumulative diff is a scoped working-tree diff, including untracked plan-critical additions as /dev/null diffs. Review the diff file, not only git status.
- The diff is large (~820k chars), so use focused read/search commands if needed.
- Treat this as a read-only review. Do not edit files.

Spec summary to check against:
- Add a shared routing policy for planning-family commands: /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research.
- Contextual exits: /z-audit-plan, /z-fix, /z-debug, /z-amend, /z-maintain-docs.
- Every bail/recommend flow must write route-decision.md, emit plan_route_decision, present AskUser handoff unless terminal hard refusal, stop if switch, and preserve existing telemetry/run-end events.
- Route artifacts must contain Recommendation, Reason, Signals, Route Chain, Resume Context.
- Telemetry requires fields: from_command, to_command, route_class, reason_codes, signals, confidence, classifier_used, artifact_path, route_chain, user_choice.
- planning-router agent must be read-only/advisory, parseable status routed|ask_user|bad_input, distinguish primary vs contextual, detect loop risk, and avoid inventing facts.
- Add sentineled Plan Route Check sections to canonical command and skill sources for z-do, z-plan-light, z-plan, z-plan-split, z-brainstorm, z-research, z-audit-plan.
- Update docs/memory and regenerate Cursor/Codex/Antigravity exports.
- Invariants: no automatic cross-command execution; standalone exports; hard gates stay stricter; /z-research never recommends implementation approach inside RESEARCH.md; /z-audit-plan stays read-only; planning-router advisory only; existing telemetry preserved.

Known context snippets observed before invoking you:
- agents/planning-router.md exists with Read/Grep/Glob tools and model haiku; it says no shell commands, no edits, compact signals only, exact parseable return shape, and explicit contextual-exit preconditions.
- commands/z-plan.md has a route block after setup that recommends /z-do, /z-plan-light, /z-plan-split, /z-research, /z-brainstorm, contextual exits, route-decision.md, plan_route_decision, AskUser handoff, and loop prevention.
- commands/z-audit-plan.md now exists and states it is read-only, routes to /z-plan when no plan artifacts exist, stays in audit when artifacts exist, and routes to /z-amend or /z-maintain-docs after final report.
- One possible drift candidate noticed: skills/z-plan/SKILL.md setup still says "Run `ls z-harness/` to check for existing slug dirs" whereas commands/z-plan.md was updated to check canonical plans dir plus legacy. Decide whether this is actionable drift or harmless export/source mismatch.

Ask:
Run a final two-pronged review.

Prong A - Implementation faithfulness. Does the cumulative diff implement SPEC.md as written? List drift: files that should have changed but did not, changed files that do not match spec, cross-task drift, stale references, missing tests/assertions called out by acceptance.

Prong B - Spec correctness. Now that implementation exists, is the spec correct/sufficient? List spec gaps: wrong decisions, impossible invariants, missed edge cases, public surfaces too broad/narrow, categories of behavior not anticipated.

For every finding include exactly:
- severity: blocker | major | minor
- prong: A | B
- file/path if applicable
- evidence
- recommendation
- one reason the finding might be wrong

Prioritize concrete blockers and majors. If there are no findings for a prong, say none clearly. Do not include speculative low-value nits unless they could actually matter to the plan shipping.
codex
I’ll run this as a read-only review and use focused searches against the archived cumulative diff plus the plan docs. I’ll start by loading the plan acceptance criteria and diff stats, then drill into routed command/skill sources and generated exports where the spec says they must align.
exec
/bin/zsh -lc "sed -n '1,260p' z-harness/plans/plan-bail-router/TASKS.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,240p' z-harness/plans/plan-bail-router/SPEC.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,260p' z-harness/plans/plan-bail-router/PLAN.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc 'cat z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.stat' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
 commands/z-brainstorm.md                           |  20 ++
 commands/z-do.md                                   |  48 ++-
 commands/z-plan-light.md                           |  45 ++-
 commands/z-plan-split.md                           |  29 +-
 commands/z-plan.md                                 |  41 ++-
 commands/z-research.md                             |  20 ++
 docs/human/agents.md                               |  58 +++-
 docs/human/commands.md                             |  49 ++-
 docs/human/skills.md                               |  72 ++--
 docs/llm/INDEX.json                                |  51 ++-
 docs/llm/agents.json                               | 158 ++-------
 docs/llm/commands.json                             |  62 +++-
 docs/llm/skills.json                               | 164 ++-------
 .../.agent/rules/z-harness-consultant-primary.md   |  20 +-
 .../.agent/rules/z-harness-consultant-secondary.md |  20 +-
 exports/agy/.agent/rules/z-harness-implementer.md  |  22 +-
 exports/agy/.agent/rules/z-harness-reviewer.md     |  15 +-
 exports/agy/.agent/skills/z-amend/SKILL.md         |   2 +
 exports/agy/.agent/skills/z-brainstorm/SKILL.md    |  20 ++
 exports/agy/.agent/skills/z-do/SKILL.md            |  46 ++-
 exports/agy/.agent/skills/z-implement-all/SKILL.md | 108 +++++-
 exports/agy/.agent/skills/z-maintain-docs/SKILL.md |  40 ++-
 exports/agy/.agent/skills/z-plan-light/SKILL.md    |  45 ++-
 exports/agy/.agent/skills/z-plan-split/SKILL.md    |  29 +-
 exports/agy/.agent/skills/z-plan/SKILL.md          |  41 ++-
 exports/agy/.agent/skills/z-research/SKILL.md      |  20 ++
 exports/agy/.agent/skills/z-review-all/SKILL.md    | 189 +++++++++-
 exports/agy/.agent/workflows/z-audit.md            |   9 +
 exports/agy/.agent/workflows/z-brainstorm.md       |  20 ++
 exports/agy/.agent/workflows/z-do.md               |  46 ++-
 exports/agy/.agent/workflows/z-implement-all.md    |  77 ++++-
 exports/agy/.agent/workflows/z-maintain-docs.md    |  40 ++-
 exports/agy/.agent/workflows/z-mr-review.md        |  10 +
 exports/agy/.agent/workflows/z-plan-light.md       |  45 ++-
 exports/agy/.agent/workflows/z-plan-split.md       |  29 +-
 exports/agy/.agent/workflows/z-plan.md             |  41 ++-
 exports/agy/.agent/workflows/z-research.md         |  20 ++
 exports/agy/.agent/workflows/z-review-all.md       | 205 ++++++++++-
 exports/agy/agy-plugin.yaml                        |  22 +-
 exports/agy/prompts/consultant-primary.md          |  20 +-
 exports/agy/prompts/consultant-secondary.md        |  20 +-
 exports/agy/prompts/implementer.md                 |  22 +-
 exports/agy/prompts/reviewer.md                    |  15 +-
 exports/agy/prompts/skill-z-amend.md               |   2 +
 exports/agy/prompts/skill-z-brainstorm.md          |  20 ++
 exports/agy/prompts/skill-z-do.md                  |  46 ++-
 exports/agy/prompts/skill-z-implement-all.md       | 108 +++++-
 exports/agy/prompts/skill-z-maintain-docs.md       |  40 ++-
 exports/agy/prompts/skill-z-plan-light.md          |  45 ++-
 exports/agy/prompts/skill-z-plan-split.md          |  29 +-
 exports/agy/prompts/skill-z-plan.md                |  41 ++-
 exports/agy/prompts/skill-z-research.md            |  20 ++
 exports/agy/prompts/skill-z-review-all.md          | 189 +++++++++-
 exports/agy/prompts/z-audit.md                     |   9 +
 exports/agy/prompts/z-brainstorm.md                |  20 ++
 exports/agy/prompts/z-do.md                        |  46 ++-
 exports/agy/prompts/z-implement-all.md             |  77 ++++-
 exports/agy/prompts/z-maintain-docs.md             |  40 ++-
 exports/agy/prompts/z-mr-review.md                 |  10 +
 exports/agy/prompts/z-plan-light.md                |  45 ++-
 exports/agy/prompts/z-plan-split.md                |  29 +-
 exports/agy/prompts/z-plan.md                      |  41 ++-
 exports/agy/prompts/z-research.md                  |  20 ++
 exports/agy/prompts/z-review-all.md                | 205 ++++++++++-
 exports/codex/AGENTS.md                            | 382 ++++++++++++++++++++-
 exports/codex/prompts/z-amend.md                   |   2 +
 exports/codex/prompts/z-audit.md                   |   9 +
 exports/codex/prompts/z-brainstorm.md              |  20 ++
 exports/codex/prompts/z-do.md                      |  46 ++-
 exports/codex/prompts/z-implement-all.md           | 108 +++++-
 exports/codex/prompts/z-maintain-docs.md           |  40 ++-
 exports/codex/prompts/z-mr-review.md               |  10 +
 exports/codex/prompts/z-plan-light.md              |  43 ++-
 exports/codex/prompts/z-plan-split.md              |  29 +-
 exports/codex/prompts/z-plan.md                    |  41 ++-
 exports/codex/prompts/z-research.md                |  20 ++
 exports/codex/prompts/z-review-all.md              | 189 +++++++++-
 .../cursor/.cursor/rules/consultant-primary.mdc    |  20 +-
 .../cursor/.cursor/rules/consultant-secondary.mdc  |  20 +-
 exports/cursor/.cursor/rules/implementer.mdc       |  22 +-
 exports/cursor/.cursor/rules/reviewer.mdc          |  15 +-
 exports/cursor/.cursor/rules/z-amend.mdc           |   2 +
 exports/cursor/.cursor/rules/z-audit.mdc           |   9 +
 exports/cursor/.cursor/rules/z-brainstorm.mdc      |  20 ++
 exports/cursor/.cursor/rules/z-do.mdc              |  48 ++-
 exports/cursor/.cursor/rules/z-implement-all.mdc   | 108 +++++-
 exports/cursor/.cursor/rules/z-maintain-docs.mdc   |  40 ++-
 exports/cursor/.cursor/rules/z-mr-review.mdc       |  10 +
 exports/cursor/.cursor/rules/z-plan-light.mdc      |  45 ++-
 exports/cursor/.cursor/rules/z-plan-split.mdc      |  29 +-
 exports/cursor/.cursor/rules/z-plan.mdc            |  41 ++-
 exports/cursor/.cursor/rules/z-research.mdc        |  20 ++
 exports/cursor/.cursor/rules/z-review-all.mdc      | 189 +++++++++-
 skills/z-brainstorm/SKILL.md                       |  21 ++
 skills/z-do/SKILL.md                               |  49 ++-
 skills/z-plan-light/SKILL.md                       |  46 ++-
 skills/z-plan-split/SKILL.md                       |  30 +-
 skills/z-plan/SKILL.md                             |  42 ++-
 skills/z-research/SKILL.md                         |  21 ++
 99 files changed, 4066 insertions(+), 877 deletions(-)
 agents/planning-router.md | new file
 commands/z-audit-plan.md | new file
 exports/agy/.agent/rules/z-harness-external-lookup.md | new file
 exports/agy/.agent/rules/z-harness-planning-router.md | new file
 exports/agy/.agent/skills/z-audit-plan/SKILL.md | new file
 exports/agy/.agent/workflows/z-audit-plan.md | new file
 exports/agy/prompts/external-lookup.md | new file
 exports/agy/prompts/planning-router.md | new file
 exports/agy/prompts/skill-z-audit-plan.md | new file
 exports/agy/prompts/z-audit-plan.md | new file
 exports/codex/prompts/z-audit-plan.md | new file
 exports/cursor/.cursor/rules/external-lookup.mdc | new file
 exports/cursor/.cursor/rules/planning-router.mdc | new file
 exports/cursor/.cursor/rules/z-audit-plan.mdc | new file
 skills/z-audit-plan/SKILL.md | new file

 succeeded in 0ms:
# Tasks: Plan Bail Router

## T001 - Add planning-router agent

**Status:** [x]
**Completion:** T001 done; reviewer blockers/majors resolved after targeted retries; no tests declared.
**Files:**
- `agents/planning-router.md`
- `docs/llm/agents.json`
- `docs/llm/INDEX.json`
- `docs/human/agents.md`
**Depends:** none
**Acceptance:**
- [ ] `agents/planning-router.md` exists with Haiku/read-only frontmatter.
- [ ] Agent return shape matches SPEC exactly.
- [ ] Agent docs/memory include `planning-router`.
- [ ] Malformed input and route-loop behavior are specified.
**DOCS:** agents
**Complexity:** high

## T002 - Add shared route contract to lightweight execution paths

**Status:** [x]
**Completion:** T002 done; reviewer found no blockers or majors; no tests declared.
**Files:**
- `commands/z-do.md`
- `commands/z-plan-light.md`
- `skills/z-do/SKILL.md`
- `skills/z-plan-light/SKILL.md`
**Depends:** T001
**Acceptance:**
- [ ] Sentineled `Plan Route Check` blocks exist in all four files.
- [ ] Existing escalation text is replaced or aliased so no duplicate/conflicting user-facing prompts remain.
- [ ] `$CURRENT_ARCHIVE_DIR`, `route-decision.md`, and `plan_route_decision` are specified.
- [ ] `/z-do` can route to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` only under SPEC conditions.
- [ ] `/z-plan-light` can route down, up, sideways, or to contextual bug workflows only under SPEC conditions.
**DOCS:** commands, skills
**Complexity:** high

## T003 - Add route check to full and split planning paths

**Status:** [x]
**Completion:** T003 done; reviewer found no blockers or majors; no tests declared.
**Files:**
- `commands/z-plan.md`
- `commands/z-plan-split.md`
- `skills/z-plan/SKILL.md`
- `skills/z-plan-split/SKILL.md`
**Depends:** T001
**Acceptance:**
- [ ] Sentineled `Plan Route Check` blocks exist in all four files.
- [ ] `/z-plan` insertion points are after setup/precontext/docs gates and after decisions when split risk is clear.
- [ ] `/z-plan-split` preserves the 2-6 cluster invariant.
- [ ] Too-few cluster seams route to `/z-plan`; unknown seams can route to `/z-research`.
- [ ] Route-chain and ping-pong prevention are included.
**DOCS:** commands, skills
**Complexity:** high

## T004 - Add route check to precontext and audit paths

**Status:** [x]
**Completion:** T004 done; reviewer found no blockers or majors; no tests declared.
**Files:**
- `commands/z-brainstorm.md`
- `commands/z-research.md`
- `commands/z-audit-plan.md`
- `skills/z-brainstorm/SKILL.md`
- `skills/z-research/SKILL.md`
- `skills/z-audit-plan/SKILL.md`
**Depends:** T001
**Acceptance:**
- [ ] Sentineled `Plan Route Check` blocks exist in all six files.
- [ ] `/z-brainstorm` routes to `/z-research`, `/z-plan`, or `/z-plan-light` only before ideator dispatch.
- [ ] `/z-research` preserves the no-recommendation invariant inside `RESEARCH.md`.
- [ ] `/z-audit-plan` remains read-only and contextual-only.
- [ ] Missing plan artifacts in `/z-audit-plan` route to `/z-plan` rather than pretending audit can proceed.
**DOCS:** commands, skills
**Complexity:** high

## T005 - Update docs and LLM memory for route policy drift

**Status:** [x]
**Completion:** T005 done; reviewer found no blockers or majors; JSON validation reported by implementer.
**Files:**
- `docs/human/commands.md`
- `docs/human/skills.md`
- `docs/human/agents.md`
- `docs/llm/INDEX.json`
- `docs/llm/commands.json`
- `docs/llm/skills.json`
- `docs/llm/agents.json`
**Depends:** T001, T002, T003, T004
**Acceptance:**
- [ ] `commands/z-audit-plan.md` is included in command docs/memory where missing.
- [ ] `skills/z-audit-plan/SKILL.md` is included in skill docs/memory where missing.
- [ ] `planning-router` is included in agent docs/memory.
- [ ] Route classes, telemetry, and contextual exits are documented.
- [ ] JSON files validate with `python3 -m json.tool`.
**DOCS:** commands, skills, agents
**Complexity:** high

## T006 - Regenerate multi-IDE exports

**Status:** [x]
**Completion:** T006 done; reviewer found no blockers or majors after retry; export scripts succeeded per implementer.
**Files:**
- `exports/cursor/.cursor/rules/*.mdc`
- `exports/codex/prompts/*.md`
- `exports/agy/prompts/*.md`
- `exports/agy/.agent/rules/*.md`
- `exports/agy/.agent/skills/*/SKILL.md`
- `exports/agy/.agent/workflows/*.md`
- `exports/agy/agy-plugin.yaml`
**Depends:** T002, T003, T004, T005
**Acceptance:**
- [ ] `python3 scripts/export-cursor.py` succeeds.
- [ ] `python3 scripts/export-codex.py` succeeds.
- [ ] `python3 scripts/export-agy.py` succeeds.
- [ ] Generated exports include route checks for all touched commands/skills.
- [ ] Generated exports include the `planning-router` agent where target format supports agents/rules.
**DOCS:** multi-ide-exports
**Complexity:** high

## T007 - Validate route coverage and scenarios

**Status:** [x]
**Completion:** T007 done; reviewer found no blockers or majors after final z-plan guard/docs-route fixes.
**Files:**
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
**Depends:** T002, T003, T004, T006
**Acceptance:**
- [ ] Sentinel search confirms `PLAN_ROUTE_CHECK_START` and `PLAN_ROUTE_CHECK_END` in all intended canonical sources.
- [ ] Scenario checklist from SPEC is manually verified in the implementation summary.
- [ ] Route telemetry fields and reason-code enums are consistent across route blocks.
- [ ] No route block says switching automatically runs another command.
- [ ] No route block makes `/z-audit-plan` a fresh-intent front-door planner.
**DOCS:** commands, skills
**Complexity:** high

 succeeded in 0ms:
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

 succeeded in 0ms:
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

codex
The plan docs confirm this is mostly prompt/source propagation, not production code. The stat also shows generated exports changed beyond the listed canonical files, so I’ll check whether that is normal export fallout or policy leaking into unrelated commands.
exec
/bin/zsh -lc "sed -n '241,520p' z-harness/plans/plan-bail-router/SPEC.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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

exec
/bin/zsh -lc 'rg -n "''^diff --git|''^'"\\+\\+\\+ b/|"'^--- a/" z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
1:diff --git a/commands/z-brainstorm.md b/commands/z-brainstorm.md
3:--- a/commands/z-brainstorm.md
4:+++ b/commands/z-brainstorm.md
32:diff --git a/commands/z-do.md b/commands/z-do.md
34:--- a/commands/z-do.md
35:+++ b/commands/z-do.md
129:diff --git a/commands/z-plan-light.md b/commands/z-plan-light.md
131:--- a/commands/z-plan-light.md
132:+++ b/commands/z-plan-light.md
238:diff --git a/commands/z-plan-split.md b/commands/z-plan-split.md
240:--- a/commands/z-plan-split.md
241:+++ b/commands/z-plan-split.md
292:diff --git a/commands/z-plan.md b/commands/z-plan.md
294:--- a/commands/z-plan.md
295:+++ b/commands/z-plan.md
384:diff --git a/commands/z-research.md b/commands/z-research.md
386:--- a/commands/z-research.md
387:+++ b/commands/z-research.md
415:diff --git a/docs/human/agents.md b/docs/human/agents.md
417:--- a/docs/human/agents.md
418:+++ b/docs/human/agents.md
493:diff --git a/docs/human/commands.md b/docs/human/commands.md
495:--- a/docs/human/commands.md
496:+++ b/docs/human/commands.md
578:diff --git a/docs/human/skills.md b/docs/human/skills.md
580:--- a/docs/human/skills.md
581:+++ b/docs/human/skills.md
668:diff --git a/docs/llm/INDEX.json b/docs/llm/INDEX.json
670:--- a/docs/llm/INDEX.json
671:+++ b/docs/llm/INDEX.json
797:diff --git a/docs/llm/agents.json b/docs/llm/agents.json
799:--- a/docs/llm/agents.json
800:+++ b/docs/llm/agents.json
980:diff --git a/docs/llm/commands.json b/docs/llm/commands.json
982:--- a/docs/llm/commands.json
983:+++ b/docs/llm/commands.json
1100:diff --git a/docs/llm/skills.json b/docs/llm/skills.json
1102:--- a/docs/llm/skills.json
1103:+++ b/docs/llm/skills.json
1289:diff --git a/exports/agy/.agent/rules/z-harness-consultant-primary.md b/exports/agy/.agent/rules/z-harness-consultant-primary.md
1291:--- a/exports/agy/.agent/rules/z-harness-consultant-primary.md
1292:+++ b/exports/agy/.agent/rules/z-harness-consultant-primary.md
1320:diff --git a/exports/agy/.agent/rules/z-harness-consultant-secondary.md b/exports/agy/.agent/rules/z-harness-consultant-secondary.md
1322:--- a/exports/agy/.agent/rules/z-harness-consultant-secondary.md
1323:+++ b/exports/agy/.agent/rules/z-harness-consultant-secondary.md
1351:diff --git a/exports/agy/.agent/rules/z-harness-implementer.md b/exports/agy/.agent/rules/z-harness-implementer.md
1353:--- a/exports/agy/.agent/rules/z-harness-implementer.md
1354:+++ b/exports/agy/.agent/rules/z-harness-implementer.md
1398:diff --git a/exports/agy/.agent/rules/z-harness-reviewer.md b/exports/agy/.agent/rules/z-harness-reviewer.md
1400:--- a/exports/agy/.agent/rules/z-harness-reviewer.md
1401:+++ b/exports/agy/.agent/rules/z-harness-reviewer.md
1424:diff --git a/exports/agy/.agent/skills/z-amend/SKILL.md b/exports/agy/.agent/skills/z-amend/SKILL.md
1426:--- a/exports/agy/.agent/skills/z-amend/SKILL.md
1427:+++ b/exports/agy/.agent/skills/z-amend/SKILL.md
1437:diff --git a/exports/agy/.agent/skills/z-brainstorm/SKILL.md b/exports/agy/.agent/skills/z-brainstorm/SKILL.md
1439:--- a/exports/agy/.agent/skills/z-brainstorm/SKILL.md
1440:+++ b/exports/agy/.agent/skills/z-brainstorm/SKILL.md
1468:diff --git a/exports/agy/.agent/skills/z-do/SKILL.md b/exports/agy/.agent/skills/z-do/SKILL.md
1470:--- a/exports/agy/.agent/skills/z-do/SKILL.md
1471:+++ b/exports/agy/.agent/skills/z-do/SKILL.md
1558:diff --git a/exports/agy/.agent/skills/z-implement-all/SKILL.md b/exports/agy/.agent/skills/z-implement-all/SKILL.md
1560:--- a/exports/agy/.agent/skills/z-implement-all/SKILL.md
1561:+++ b/exports/agy/.agent/skills/z-implement-all/SKILL.md
1746:diff --git a/exports/agy/.agent/skills/z-maintain-docs/SKILL.md b/exports/agy/.agent/skills/z-maintain-docs/SKILL.md
1748:--- a/exports/agy/.agent/skills/z-maintain-docs/SKILL.md
1749:+++ b/exports/agy/.agent/skills/z-maintain-docs/SKILL.md
1811:diff --git a/exports/agy/.agent/skills/z-plan-light/SKILL.md b/exports/agy/.agent/skills/z-plan-light/SKILL.md
1813:--- a/exports/agy/.agent/skills/z-plan-light/SKILL.md
1814:+++ b/exports/agy/.agent/skills/z-plan-light/SKILL.md
1921:diff --git a/exports/agy/.agent/skills/z-plan-split/SKILL.md b/exports/agy/.agent/skills/z-plan-split/SKILL.md
1923:--- a/exports/agy/.agent/skills/z-plan-split/SKILL.md
1924:+++ b/exports/agy/.agent/skills/z-plan-split/SKILL.md
1975:diff --git a/exports/agy/.agent/skills/z-plan/SKILL.md b/exports/agy/.agent/skills/z-plan/SKILL.md
1977:--- a/exports/agy/.agent/skills/z-plan/SKILL.md
1978:+++ b/exports/agy/.agent/skills/z-plan/SKILL.md
2067:diff --git a/exports/agy/.agent/skills/z-research/SKILL.md b/exports/agy/.agent/skills/z-research/SKILL.md
2069:--- a/exports/agy/.agent/skills/z-research/SKILL.md
2070:+++ b/exports/agy/.agent/skills/z-research/SKILL.md
2098:diff --git a/exports/agy/.agent/skills/z-review-all/SKILL.md b/exports/agy/.agent/skills/z-review-all/SKILL.md
2100:--- a/exports/agy/.agent/skills/z-review-all/SKILL.md
2101:+++ b/exports/agy/.agent/skills/z-review-all/SKILL.md
2331:diff --git a/exports/agy/.agent/workflows/z-audit.md b/exports/agy/.agent/workflows/z-audit.md
2333:--- a/exports/agy/.agent/workflows/z-audit.md
2334:+++ b/exports/agy/.agent/workflows/z-audit.md
2351:diff --git a/exports/agy/.agent/workflows/z-brainstorm.md b/exports/agy/.agent/workflows/z-brainstorm.md
2353:--- a/exports/agy/.agent/workflows/z-brainstorm.md
2354:+++ b/exports/agy/.agent/workflows/z-brainstorm.md
2382:diff --git a/exports/agy/.agent/workflows/z-do.md b/exports/agy/.agent/workflows/z-do.md
2384:--- a/exports/agy/.agent/workflows/z-do.md
2385:+++ b/exports/agy/.agent/workflows/z-do.md
2472:diff --git a/exports/agy/.agent/workflows/z-implement-all.md b/exports/agy/.agent/workflows/z-implement-all.md
2474:--- a/exports/agy/.agent/workflows/z-implement-all.md
2475:+++ b/exports/agy/.agent/workflows/z-implement-all.md
2595:diff --git a/exports/agy/.agent/workflows/z-maintain-docs.md b/exports/agy/.agent/workflows/z-maintain-docs.md
2597:--- a/exports/agy/.agent/workflows/z-maintain-docs.md
2598:+++ b/exports/agy/.agent/workflows/z-maintain-docs.md
2660:diff --git a/exports/agy/.agent/workflows/z-mr-review.md b/exports/agy/.agent/workflows/z-mr-review.md
2662:--- a/exports/agy/.agent/workflows/z-mr-review.md
2663:+++ b/exports/agy/.agent/workflows/z-mr-review.md
2681:diff --git a/exports/agy/.agent/workflows/z-plan-light.md b/exports/agy/.agent/workflows/z-plan-light.md
2683:--- a/exports/agy/.agent/workflows/z-plan-light.md
2684:+++ b/exports/agy/.agent/workflows/z-plan-light.md
2790:diff --git a/exports/agy/.agent/workflows/z-plan-split.md b/exports/agy/.agent/workflows/z-plan-split.md
2792:--- a/exports/agy/.agent/workflows/z-plan-split.md
2793:+++ b/exports/agy/.agent/workflows/z-plan-split.md
2844:diff --git a/exports/agy/.agent/workflows/z-plan.md b/exports/agy/.agent/workflows/z-plan.md
2846:--- a/exports/agy/.agent/workflows/z-plan.md
2847:+++ b/exports/agy/.agent/workflows/z-plan.md
2936:diff --git a/exports/agy/.agent/workflows/z-research.md b/exports/agy/.agent/workflows/z-research.md
2938:--- a/exports/agy/.agent/workflows/z-research.md
2939:+++ b/exports/agy/.agent/workflows/z-research.md
2967:diff --git a/exports/agy/.agent/workflows/z-review-all.md b/exports/agy/.agent/workflows/z-review-all.md
2969:--- a/exports/agy/.agent/workflows/z-review-all.md
2970:+++ b/exports/agy/.agent/workflows/z-review-all.md
3216:diff --git a/exports/agy/agy-plugin.yaml b/exports/agy/agy-plugin.yaml
3218:--- a/exports/agy/agy-plugin.yaml
3219:+++ b/exports/agy/agy-plugin.yaml
3284:diff --git a/exports/agy/prompts/consultant-primary.md b/exports/agy/prompts/consultant-primary.md
3286:--- a/exports/agy/prompts/consultant-primary.md
3287:+++ b/exports/agy/prompts/consultant-primary.md
3315:diff --git a/exports/agy/prompts/consultant-secondary.md b/exports/agy/prompts/consultant-secondary.md
3317:--- a/exports/agy/prompts/consultant-secondary.md
3318:+++ b/exports/agy/prompts/consultant-secondary.md
3346:diff --git a/exports/agy/prompts/implementer.md b/exports/agy/prompts/implementer.md
3348:--- a/exports/agy/prompts/implementer.md
3349:+++ b/exports/agy/prompts/implementer.md
3393:diff --git a/exports/agy/prompts/reviewer.md b/exports/agy/prompts/reviewer.md
3395:--- a/exports/agy/prompts/reviewer.md
3396:+++ b/exports/agy/prompts/reviewer.md
3419:diff --git a/exports/agy/prompts/skill-z-amend.md b/exports/agy/prompts/skill-z-amend.md
3421:--- a/exports/agy/prompts/skill-z-amend.md
3422:+++ b/exports/agy/prompts/skill-z-amend.md
3432:diff --git a/exports/agy/prompts/skill-z-brainstorm.md b/exports/agy/prompts/skill-z-brainstorm.md
3434:--- a/exports/agy/prompts/skill-z-brainstorm.md
3435:+++ b/exports/agy/prompts/skill-z-brainstorm.md
3463:diff --git a/exports/agy/prompts/skill-z-do.md b/exports/agy/prompts/skill-z-do.md
3465:--- a/exports/agy/prompts/skill-z-do.md
3466:+++ b/exports/agy/prompts/skill-z-do.md
3553:diff --git a/exports/agy/prompts/skill-z-implement-all.md b/exports/agy/prompts/skill-z-implement-all.md
3555:--- a/exports/agy/prompts/skill-z-implement-all.md
3556:+++ b/exports/agy/prompts/skill-z-implement-all.md
3741:diff --git a/exports/agy/prompts/skill-z-maintain-docs.md b/exports/agy/prompts/skill-z-maintain-docs.md
3743:--- a/exports/agy/prompts/skill-z-maintain-docs.md
3744:+++ b/exports/agy/prompts/skill-z-maintain-docs.md
3806:diff --git a/exports/agy/prompts/skill-z-plan-light.md b/exports/agy/prompts/skill-z-plan-light.md
3808:--- a/exports/agy/prompts/skill-z-plan-light.md
3809:+++ b/exports/agy/prompts/skill-z-plan-light.md
3915:diff --git a/exports/agy/prompts/skill-z-plan-split.md b/exports/agy/prompts/skill-z-plan-split.md
3917:--- a/exports/agy/prompts/skill-z-plan-split.md
3918:+++ b/exports/agy/prompts/skill-z-plan-split.md
3969:diff --git a/exports/agy/prompts/skill-z-plan.md b/exports/agy/prompts/skill-z-plan.md
3971:--- a/exports/agy/prompts/skill-z-plan.md
3972:+++ b/exports/agy/prompts/skill-z-plan.md
4061:diff --git a/exports/agy/prompts/skill-z-research.md b/exports/agy/prompts/skill-z-research.md
4063:--- a/exports/agy/prompts/skill-z-research.md
4064:+++ b/exports/agy/prompts/skill-z-research.md
4092:diff --git a/exports/agy/prompts/skill-z-review-all.md b/exports/agy/prompts/skill-z-review-all.md
4094:--- a/exports/agy/prompts/skill-z-review-all.md
4095:+++ b/exports/agy/prompts/skill-z-review-all.md
4325:diff --git a/exports/agy/prompts/z-audit.md b/exports/agy/prompts/z-audit.md
4327:--- a/exports/agy/prompts/z-audit.md
4328:+++ b/exports/agy/prompts/z-audit.md
4345:diff --git a/exports/agy/prompts/z-brainstorm.md b/exports/agy/prompts/z-brainstorm.md
4347:--- a/exports/agy/prompts/z-brainstorm.md
4348:+++ b/exports/agy/prompts/z-brainstorm.md
4376:diff --git a/exports/agy/prompts/z-do.md b/exports/agy/prompts/z-do.md
4378:--- a/exports/agy/prompts/z-do.md
4379:+++ b/exports/agy/prompts/z-do.md
4466:diff --git a/exports/agy/prompts/z-implement-all.md b/exports/agy/prompts/z-implement-all.md
4468:--- a/exports/agy/prompts/z-implement-all.md
4469:+++ b/exports/agy/prompts/z-implement-all.md
4589:diff --git a/exports/agy/prompts/z-maintain-docs.md b/exports/agy/prompts/z-maintain-docs.md
4591:--- a/exports/agy/prompts/z-maintain-docs.md
4592:+++ b/exports/agy/prompts/z-maintain-docs.md
4654:diff --git a/exports/agy/prompts/z-mr-review.md b/exports/agy/prompts/z-mr-review.md
4656:--- a/exports/agy/prompts/z-mr-review.md
4657:+++ b/exports/agy/prompts/z-mr-review.md
4675:diff --git a/exports/agy/prompts/z-plan-light.md b/exports/agy/prompts/z-plan-light.md
4677:--- a/exports/agy/prompts/z-plan-light.md
4678:+++ b/exports/agy/prompts/z-plan-light.md
4784:diff --git a/exports/agy/prompts/z-plan-split.md b/exports/agy/prompts/z-plan-split.md
4786:--- a/exports/agy/prompts/z-plan-split.md
4787:+++ b/exports/agy/prompts/z-plan-split.md
4838:diff --git a/exports/agy/prompts/z-plan.md b/exports/agy/prompts/z-plan.md
4840:--- a/exports/agy/prompts/z-plan.md
4841:+++ b/exports/agy/prompts/z-plan.md
4930:diff --git a/exports/agy/prompts/z-research.md b/exports/agy/prompts/z-research.md
4932:--- a/exports/agy/prompts/z-research.md
4933:+++ b/exports/agy/prompts/z-research.md
4961:diff --git a/exports/agy/prompts/z-review-all.md b/exports/agy/prompts/z-review-all.md
4963:--- a/exports/agy/prompts/z-review-all.md
4964:+++ b/exports/agy/prompts/z-review-all.md
5210:diff --git a/exports/codex/AGENTS.md b/exports/codex/AGENTS.md
5212:--- a/exports/codex/AGENTS.md
5213:+++ b/exports/codex/AGENTS.md
5649:diff --git a/exports/codex/prompts/z-amend.md b/exports/codex/prompts/z-amend.md
5651:--- a/exports/codex/prompts/z-amend.md
5652:+++ b/exports/codex/prompts/z-amend.md
5662:diff --git a/exports/codex/prompts/z-audit.md b/exports/codex/prompts/z-audit.md
5664:--- a/exports/codex/prompts/z-audit.md
5665:+++ b/exports/codex/prompts/z-audit.md
5682:diff --git a/exports/codex/prompts/z-brainstorm.md b/exports/codex/prompts/z-brainstorm.md
5684:--- a/exports/codex/prompts/z-brainstorm.md
5685:+++ b/exports/codex/prompts/z-brainstorm.md
5713:diff --git a/exports/codex/prompts/z-do.md b/exports/codex/prompts/z-do.md
5715:--- a/exports/codex/prompts/z-do.md
5716:+++ b/exports/codex/prompts/z-do.md
5803:diff --git a/exports/codex/prompts/z-implement-all.md b/exports/codex/prompts/z-implement-all.md
5805:--- a/exports/codex/prompts/z-implement-all.md
5806:+++ b/exports/codex/prompts/z-implement-all.md
5991:diff --git a/exports/codex/prompts/z-maintain-docs.md b/exports/codex/prompts/z-maintain-docs.md
5993:--- a/exports/codex/prompts/z-maintain-docs.md
5994:+++ b/exports/codex/prompts/z-maintain-docs.md
6056:diff --git a/exports/codex/prompts/z-mr-review.md b/exports/codex/prompts/z-mr-review.md
6058:--- a/exports/codex/prompts/z-mr-review.md
6059:+++ b/exports/codex/prompts/z-mr-review.md
6077:diff --git a/exports/codex/prompts/z-plan-light.md b/exports/codex/prompts/z-plan-light.md
6079:--- a/exports/codex/prompts/z-plan-light.md
6080:+++ b/exports/codex/prompts/z-plan-light.md
6179:diff --git a/exports/codex/prompts/z-plan-split.md b/exports/codex/prompts/z-plan-split.md
6181:--- a/exports/codex/prompts/z-plan-split.md
6182:+++ b/exports/codex/prompts/z-plan-split.md
6233:diff --git a/exports/codex/prompts/z-plan.md b/exports/codex/prompts/z-plan.md
6235:--- a/exports/codex/prompts/z-plan.md
6236:+++ b/exports/codex/prompts/z-plan.md
6325:diff --git a/exports/codex/prompts/z-research.md b/exports/codex/prompts/z-research.md
6327:--- a/exports/codex/prompts/z-research.md
6328:+++ b/exports/codex/prompts/z-research.md
6356:diff --git a/exports/codex/prompts/z-review-all.md b/exports/codex/prompts/z-review-all.md
6358:--- a/exports/codex/prompts/z-review-all.md
6359:+++ b/exports/codex/prompts/z-review-all.md
6589:diff --git a/exports/cursor/.cursor/rules/consultant-primary.mdc b/exports/cursor/.cursor/rules/consultant-primary.mdc
6591:--- a/exports/cursor/.cursor/rules/consultant-primary.mdc
6592:+++ b/exports/cursor/.cursor/rules/consultant-primary.mdc
6620:diff --git a/exports/cursor/.cursor/rules/consultant-secondary.mdc b/exports/cursor/.cursor/rules/consultant-secondary.mdc
6622:--- a/exports/cursor/.cursor/rules/consultant-secondary.mdc
6623:+++ b/exports/cursor/.cursor/rules/consultant-secondary.mdc
6651:diff --git a/exports/cursor/.cursor/rules/implementer.mdc b/exports/cursor/.cursor/rules/implementer.mdc
6653:--- a/exports/cursor/.cursor/rules/implementer.mdc
6654:+++ b/exports/cursor/.cursor/rules/implementer.mdc
6698:diff --git a/exports/cursor/.cursor/rules/reviewer.mdc b/exports/cursor/.cursor/rules/reviewer.mdc
6700:--- a/exports/cursor/.cursor/rules/reviewer.mdc
6701:+++ b/exports/cursor/.cursor/rules/reviewer.mdc
6724:diff --git a/exports/cursor/.cursor/rules/z-amend.mdc b/exports/cursor/.cursor/rules/z-amend.mdc
6726:--- a/exports/cursor/.cursor/rules/z-amend.mdc
6727:+++ b/exports/cursor/.cursor/rules/z-amend.mdc
6737:diff --git a/exports/cursor/.cursor/rules/z-audit.mdc b/exports/cursor/.cursor/rules/z-audit.mdc
6739:--- a/exports/cursor/.cursor/rules/z-audit.mdc
6740:+++ b/exports/cursor/.cursor/rules/z-audit.mdc
6757:diff --git a/exports/cursor/.cursor/rules/z-brainstorm.mdc b/exports/cursor/.cursor/rules/z-brainstorm.mdc
6759:--- a/exports/cursor/.cursor/rules/z-brainstorm.mdc
6760:+++ b/exports/cursor/.cursor/rules/z-brainstorm.mdc
6788:diff --git a/exports/cursor/.cursor/rules/z-do.mdc b/exports/cursor/.cursor/rules/z-do.mdc
6790:--- a/exports/cursor/.cursor/rules/z-do.mdc
6791:+++ b/exports/cursor/.cursor/rules/z-do.mdc
6885:diff --git a/exports/cursor/.cursor/rules/z-implement-all.mdc b/exports/cursor/.cursor/rules/z-implement-all.mdc
6887:--- a/exports/cursor/.cursor/rules/z-implement-all.mdc
6888:+++ b/exports/cursor/.cursor/rules/z-implement-all.mdc
7073:diff --git a/exports/cursor/.cursor/rules/z-maintain-docs.mdc b/exports/cursor/.cursor/rules/z-maintain-docs.mdc
7075:--- a/exports/cursor/.cursor/rules/z-maintain-docs.mdc
7076:+++ b/exports/cursor/.cursor/rules/z-maintain-docs.mdc
7138:diff --git a/exports/cursor/.cursor/rules/z-mr-review.mdc b/exports/cursor/.cursor/rules/z-mr-review.mdc
7140:--- a/exports/cursor/.cursor/rules/z-mr-review.mdc
7141:+++ b/exports/cursor/.cursor/rules/z-mr-review.mdc
7159:diff --git a/exports/cursor/.cursor/rules/z-plan-light.mdc b/exports/cursor/.cursor/rules/z-plan-light.mdc
7161:--- a/exports/cursor/.cursor/rules/z-plan-light.mdc
7162:+++ b/exports/cursor/.cursor/rules/z-plan-light.mdc
7268:diff --git a/exports/cursor/.cursor/rules/z-plan-split.mdc b/exports/cursor/.cursor/rules/z-plan-split.mdc
7270:--- a/exports/cursor/.cursor/rules/z-plan-split.mdc
7271:+++ b/exports/cursor/.cursor/rules/z-plan-split.mdc
7322:diff --git a/exports/cursor/.cursor/rules/z-plan.mdc b/exports/cursor/.cursor/rules/z-plan.mdc
7324:--- a/exports/cursor/.cursor/rules/z-plan.mdc
7325:+++ b/exports/cursor/.cursor/rules/z-plan.mdc
7414:diff --git a/exports/cursor/.cursor/rules/z-research.mdc b/exports/cursor/.cursor/rules/z-research.mdc
7416:--- a/exports/cursor/.cursor/rules/z-research.mdc
7417:+++ b/exports/cursor/.cursor/rules/z-research.mdc
7445:diff --git a/exports/cursor/.cursor/rules/z-review-all.mdc b/exports/cursor/.cursor/rules/z-review-all.mdc
7447:--- a/exports/cursor/.cursor/rules/z-review-all.mdc
7448:+++ b/exports/cursor/.cursor/rules/z-review-all.mdc
7678:diff --git a/skills/z-brainstorm/SKILL.md b/skills/z-brainstorm/SKILL.md
7680:--- a/skills/z-brainstorm/SKILL.md
7681:+++ b/skills/z-brainstorm/SKILL.md
7715:diff --git a/skills/z-do/SKILL.md b/skills/z-do/SKILL.md
7717:--- a/skills/z-do/SKILL.md
7718:+++ b/skills/z-do/SKILL.md
7813:diff --git a/skills/z-plan-light/SKILL.md b/skills/z-plan-light/SKILL.md
7815:--- a/skills/z-plan-light/SKILL.md
7816:+++ b/skills/z-plan-light/SKILL.md
7923:diff --git a/skills/z-plan-split/SKILL.md b/skills/z-plan-split/SKILL.md
7925:--- a/skills/z-plan-split/SKILL.md
7926:+++ b/skills/z-plan-split/SKILL.md
7983:diff --git a/skills/z-plan/SKILL.md b/skills/z-plan/SKILL.md
7985:--- a/skills/z-plan/SKILL.md
7986:+++ b/skills/z-plan/SKILL.md
8081:diff --git a/skills/z-research/SKILL.md b/skills/z-research/SKILL.md
8083:--- a/skills/z-research/SKILL.md
8084:+++ b/skills/z-research/SKILL.md
8118:diff --git a/agents/planning-router.md b/agents/planning-router.md
8122:+++ b/agents/planning-router.md
8278:diff --git a/commands/z-audit-plan.md b/commands/z-audit-plan.md
8282:+++ b/commands/z-audit-plan.md
8485:diff --git a/exports/agy/.agent/rules/z-harness-external-lookup.md b/exports/agy/.agent/rules/z-harness-external-lookup.md
8489:+++ b/exports/agy/.agent/rules/z-harness-external-lookup.md
8640:diff --git a/exports/agy/.agent/rules/z-harness-planning-router.md b/exports/agy/.agent/rules/z-harness-planning-router.md
8644:+++ b/exports/agy/.agent/rules/z-harness-planning-router.md
8798:diff --git a/exports/agy/.agent/skills/z-audit-plan/SKILL.md b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
8802:+++ b/exports/agy/.agent/skills/z-audit-plan/SKILL.md
9005:diff --git a/exports/agy/.agent/workflows/z-audit-plan.md b/exports/agy/.agent/workflows/z-audit-plan.md
9009:+++ b/exports/agy/.agent/workflows/z-audit-plan.md
9211:diff --git a/exports/agy/prompts/external-lookup.md b/exports/agy/prompts/external-lookup.md
9215:+++ b/exports/agy/prompts/external-lookup.md
9366:diff --git a/exports/agy/prompts/planning-router.md b/exports/agy/prompts/planning-router.md
9370:+++ b/exports/agy/prompts/planning-router.md
9524:diff --git a/exports/agy/prompts/skill-z-audit-plan.md b/exports/agy/prompts/skill-z-audit-plan.md
9528:+++ b/exports/agy/prompts/skill-z-audit-plan.md
9731:diff --git a/exports/agy/prompts/z-audit-plan.md b/exports/agy/prompts/z-audit-plan.md
9735:+++ b/exports/agy/prompts/z-audit-plan.md
9938:diff --git a/exports/codex/prompts/z-audit-plan.md b/exports/codex/prompts/z-audit-plan.md
9942:+++ b/exports/codex/prompts/z-audit-plan.md
10142:diff --git a/exports/cursor/.cursor/rules/external-lookup.mdc b/exports/cursor/.cursor/rules/external-lookup.mdc
10146:+++ b/exports/cursor/.cursor/rules/external-lookup.mdc
10297:diff --git a/exports/cursor/.cursor/rules/planning-router.mdc b/exports/cursor/.cursor/rules/planning-router.mdc
10301:+++ b/exports/cursor/.cursor/rules/planning-router.mdc
10455:diff --git a/exports/cursor/.cursor/rules/z-audit-plan.mdc b/exports/cursor/.cursor/rules/z-audit-plan.mdc
10459:+++ b/exports/cursor/.cursor/rules/z-audit-plan.mdc
10662:diff --git a/skills/z-audit-plan/SKILL.md b/skills/z-audit-plan/SKILL.md
10666:+++ b/skills/z-audit-plan/SKILL.md

exec
/bin/zsh -lc 'rg -n "PLAN_ROUTE_CHECK|plan_route_decision|route-decision|Route Decision|planning-router|CURRENT_ARCHIVE_DIR|AskUser|Switch to|Continue here|Abandon|automatically|auto" z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
9:+<!-- PLAN_ROUTE_CHECK_START -->
22:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
24:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
27:+<!-- PLAN_ROUTE_CHECK_END -->
48:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
63:+<!-- PLAN_ROUTE_CHECK_START -->
76:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
89:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
91:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
94:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
95:+<!-- PLAN_ROUTE_CHECK_END -->
103:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
104:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
111: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
115:+- "Switch to the recommended routed command"
117: - "Abandon"
124:-- **Never proceed past auto-bail thresholds** without explicit user override.
142: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
144:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
145:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
154:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
171:+<!-- PLAN_ROUTE_CHECK_START -->
184:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
193:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
195:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
197:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
198:+<!-- PLAN_ROUTE_CHECK_END -->
202:@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
206:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
207:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
221: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
223:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
224:+- "Switch to the recommended routed command"
233:-- **Never proceed past auto-bail thresholds** without explicit user override.
248:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
250:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
271:+<!-- PLAN_ROUTE_CHECK_START -->
283:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
285:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
288:+<!-- PLAN_ROUTE_CHECK_END -->
307:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
310:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
312:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
319:+<!-- PLAN_ROUTE_CHECK_START -->
332:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
334:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
337:+<!-- PLAN_ROUTE_CHECK_END -->
382:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
392:+<!-- PLAN_ROUTE_CHECK_START -->
405:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
407:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
410:+<!-- PLAN_ROUTE_CHECK_END -->
425:+> Covers source: agents/auditor.md, agents/cluster-planner.md, agents/complexity-classifier.md, agents/consultant-primary.md, agents/consultant-secondary.md, agents/doc-fetcher.md, agents/doc-updater.md, agents/external-lookup.md, agents/implementer.md, agents/mr-reviewer.md, agents/planning-router.md, agents/remote-runner.md, agents/reviewer.md, agents/spec-precheck.md
428:-The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each subagent is configured with a tailored system prompt, dedicated tools, and appropriate model profiles (typically Sonnet or specialized consultant roles) to execute discrete, high-discipline steps.
431:+The agents concept represents the complete suite of specialized subagent profiles that drive the automated plan-and-implement workflow in z-harness. Each agent is a markdown file with a frontmatter header (`name`, `description`, `tools`, `model`) that configures its context, available tools, and target model tier (Haiku for cheap mechanical work, Sonnet for implementation and review, Haiku-proxied consultant agents that shell out to an external provider CLI resolved via `scripts/resolve-provider.sh`). Agents are spawned fresh per invocation — isolated workers with no shared mutable state.
433:+These agents decompose complex workflows into focused roles: planning (cluster-planner), planning-route disambiguation (planning-router), implementation (implementer), correctness review (reviewer), code quality review (mr-reviewer), spec validation (spec-precheck), complexity routing (complexity-classifier), documentation (doc-fetcher, doc-updater), remote execution (remote-runner), external retrieval (external-lookup), auditing (auditor), and cross-LLM consultation (consultant-primary, consultant-secondary). The consultant and reviewer agents are provider-agnostic proxies: they call `scripts/resolve-provider.sh` to discover which CLI (Codex, Gemini, or another) is registered for each role, then shell out to that CLI. This replaced the earlier hard-coded `codex-consultant.md`, `codex-reviewer.md`, and `gemini-consultant.md` files.
458:+- `agents/planning-router.md:1` — `planning-router` — Cheap Haiku, read-only ambiguity resolver for plan-family route decisions. It accepts compact caller-supplied signals, returns the exact `STATUS`/`RECOMMENDED`/`ROUTE_CLASS`/`CONFIDENCE`/`REASON_CODES`/`REASON` shape, treats malformed input as `bad_input`, and asks the user on route-loop or conflicting-signal risk.
468:+- `skills` — Skills define the exact operational boundaries, steps, and telemetry wrappers that direct subagent execution. Planning skills pass `planning-router` only compact already-known signals when deterministic route thresholds do not settle the next command.
471:+- `planning-router` supports the shared route policy but does not own it. The caller owns the final decision, writes `route-decision.md`, emits `plan_route_decision`, and presents the AskUser handoff gate.
481:+- `planning-router` is advisory only: it does not edit, call agents, or run shell commands. It must not route tiny/small tasks when `non_obvious_decisions` is unknown, and it must not recommend `/z-plan-split` unless split seams are explicitly independently plannable.
482:+- `planning-router` distinguishes primary route targets (`/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, `/z-research`) from contextual exits (`/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, `/z-maintain-docs`) and returns `ask_user` rather than a concrete route when loop risk or conflicting signals make automation unsafe.
506: The commands concept covers the complete set of slash commands that provide a structured CLI-like interface for executing z-harness tasks. These commands partition harness behaviors into clear logical operations—such as parallel brainstorming, deep pre-plan terrain research, comprehensive planning, targeted hotfixes, checklist implementation, automatic code review, test case generation, and documentation maintenance.
529:+- `agents` — Commands instantiate and direct subagent teams (e.g. auditors, reviewers, implementers, plan consultants) to safely delegate heavy workloads. Planning-family commands may call `planning-router` only for ambiguous route decisions after deterministic signals have been collected.
532:+- Planning-family commands share a route policy: primary routes are `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, and `/z-research`; contextual exits are `/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, and `/z-maintain-docs`. A route writes `route-decision.md`, emits `plan_route_decision`, presents an AskUser handoff gate, and never auto-executes the recommended command.
564:+An unconditional breakpoint fires before the cross-LLM consultant batch spawns (between Phase 3.5 and Phase 4). No env var gate. An `AskUserQuestion` offers two options: "Pause for /clear" (exit, no state written) or "Proceed now" (write slug-scoped `.review_state.json` at `z-harness/plans/<slug>/.review_state.json` and continue). On the next invocation, if HEAD matches and the diff file is still present, the command fast-forwards to Phase 4 without re-running the expensive earlier phases.
570:+An unconditional breakpoint fires before the first audit-consultant batch dispatches (Phase 2.3). Same two-option `AskUserQuestion` pattern. State file: `docs/llm/.maintain_docs_audit_state.json`. Fast-forward triggers when the stale concept set matches `stale_concepts_at_ack`; stale-set changes invalidate the marker and re-prompt. Plain (non-`--audit`) `/z-maintain-docs` runs are not affected.
623:+- `skills/z-implement-next/SKILL.md:1` — `z-implement-next` — Single-task implementation. Picks implementer model from the task block's `**Complexity:**` stamp (`low|medium` → Sonnet, `high` → Opus). Single-shot; does not auto-retry on review failure.
642:+- `agents` — Skills define the exact subagent types, models, and prompt shapes dispatched during runs. The provider-registry agents (`consultant-primary`, `consultant-secondary`, `reviewer`) abstract CLI vendor selection away from skill logic; `planning-router` is an advisory Haiku helper used only when deterministic route signals conflict.
644:+- `z-amend` remains the authority for applying review-generated spec-gap proposals; promoted amendment tasks in REVIEW-TASKS.md are inputs to the amendment workflow, not permission for implementers to edit planning artifacts autonomously.
645:+- Planning skills mirror the shared route classes: primary routes are `/z-do`, `/z-plan-light`, `/z-plan`, `/z-plan-split`, `/z-brainstorm`, and `/z-research`; contextual exits are `/z-audit-plan`, `/z-fix`, `/z-debug`, `/z-amend`, and `/z-maintain-docs`. Route bails write `route-decision.md`, emit `plan_route_decision`, preserve existing telemetry, and stop rather than auto-running the target command.
687:+        "agents/planning-router.md",
698:+      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
722:+      "summary": "Slash command surfaces, including planning-family route checks, contextual exits such as /z-audit-plan, plan_route_decision telemetry, review-family finding promotion, and /z-implement-all --tasks consumption."
764:       "summary": "Explicit in-place plugin update via /z-update; detects symlink vs tarball mode; git pull --ff-only for symlink, atomic swap for tarball; no autoupdate; version tracked by scripts/version.sh."
818:+    "agents/planning-router.md",
952:+    {"file": "agents/planning-router.md", "line": 1, "symbol": "planning-router", "kind": "module", "summary": "Haiku; read-only advisory router for ambiguous plan-family route decisions; requires exact parseable return shape and explicit split preconditions."},
967:+    "planning-router is advisory only: callers own route artifacts, plan_route_decision telemetry, AskUser handoffs, and final routing decisions."
976:+    "planning-router distinguishes primary route targets (/z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research) from contextual exits (/z-audit-plan, /z-fix, /z-debug, /z-amend, /z-maintain-docs), and returns ask_user for loop-risk or conflicting-signal cases."
1089:+    "Planning-family route bails write route-decision.md, emit plan_route_decision with route_class/reason_codes/signals/confidence/classifier_used/artifact_path/route_chain/user_choice, present an AskUser handoff gate, and never auto-execute another command."
1245:+    {"file": "skills/z-audit-plan/SKILL.md", "line": 1, "symbol": "z-audit-plan", "kind": "module", "summary": "Read-only pre-implementation plan audit; verifies SPEC/PLAN/TASKS, writes PLAN_AUDIT_REPORT.md, and routes contextually to /z-plan, /z-amend, or /z-maintain-docs through route-decision.md."},
1250:+    {"file": "skills/z-implement-next/SKILL.md", "line": 1, "symbol": "z-implement-next", "kind": "module", "summary": "Single-task implementation; model selected from **Complexity:** stamp; no auto-retry; single-shot design forces fresh context per task."},
1254:+    {"file": "skills/z-plan-light/SKILL.md", "line": 1, "symbol": "z-plan-light", "kind": "module", "summary": "Lightweight planner for small fixes: inline orchestrator implementation, FIX.md only, mandatory reviewer gate, auto-bail at >5 files or >2 non-obvious decisions."},
1274:+    "Planning-family skills share the route policy: route bails write route-decision.md, emit plan_route_decision, preserve existing telemetry, present an AskUser handoff, and stop instead of auto-running the target command."
1432:+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
1445:+<!-- PLAN_ROUTE_CHECK_START -->
1458:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
1460:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
1463:+<!-- PLAN_ROUTE_CHECK_END -->
1477:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
1492:+<!-- PLAN_ROUTE_CHECK_START -->
1505:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
1518:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
1520:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
1523:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
1524:+<!-- PLAN_ROUTE_CHECK_END -->
1532:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
1533:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
1540: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
1544:+- "Switch to the recommended routed command"
1546: - "Abandon"
1553:-- **Never proceed past auto-bail thresholds** without explicit user override.
1765:+   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
1766:+   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
1777:+`AskUserQuestion` with two options:
1825: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
1827:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
1828:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
1837:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
1854:+<!-- PLAN_ROUTE_CHECK_START -->
1867:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
1876:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
1878:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
1880:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
1881:+<!-- PLAN_ROUTE_CHECK_END -->
1885:@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
1889:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
1890:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
1904: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
1906:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
1907:+- "Switch to the recommended routed command"
1916:-- **Never proceed past auto-bail thresholds** without explicit user override.
1931:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
1933:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
1954:+<!-- PLAN_ROUTE_CHECK_START -->
1966:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
1968:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
1971:+<!-- PLAN_ROUTE_CHECK_END -->
1990:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
1993:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
1995:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
2002:+<!-- PLAN_ROUTE_CHECK_START -->
2015:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
2017:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
2020:+<!-- PLAN_ROUTE_CHECK_END -->
2065:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
2075:+<!-- PLAN_ROUTE_CHECK_START -->
2088:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
2090:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
2093:+<!-- PLAN_ROUTE_CHECK_END -->
2171:+Present an `AskUserQuestion` with exactly two options:
2301:-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
2326:-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
2327:+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
2346:+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
2350: 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
2359:+<!-- PLAN_ROUTE_CHECK_START -->
2372:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
2374:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
2377:+<!-- PLAN_ROUTE_CHECK_END -->
2391:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
2406:+<!-- PLAN_ROUTE_CHECK_START -->
2419:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
2432:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
2434:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
2437:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
2438:+<!-- PLAN_ROUTE_CHECK_END -->
2446:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
2447:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
2454: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
2458:+- "Switch to the recommended routed command"
2460: - "Abandon"
2467:-- **Never proceed past auto-bail thresholds** without explicit user override.
2614:+   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
2615:+   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
2626:+`AskUserQuestion` with two options:
2694: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
2696:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
2697:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
2706:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
2723:+<!-- PLAN_ROUTE_CHECK_START -->
2736:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
2745:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
2747:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
2749:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
2750:+<!-- PLAN_ROUTE_CHECK_END -->
2754:@@ -62,13 +83,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
2758:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
2759:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
2773: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
2775:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
2776:+- "Switch to the recommended routed command"
2785:-- **Never proceed past auto-bail thresholds** without explicit user override.
2800:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
2802:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
2823:+<!-- PLAN_ROUTE_CHECK_START -->
2835:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
2837:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
2840:+<!-- PLAN_ROUTE_CHECK_END -->
2859:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
2862:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
2864:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
2871:+<!-- PLAN_ROUTE_CHECK_START -->
2884:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
2886:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
2889:+<!-- PLAN_ROUTE_CHECK_END -->
2934:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
2944:+<!-- PLAN_ROUTE_CHECK_START -->
2957:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
2959:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
2962:+<!-- PLAN_ROUTE_CHECK_END -->
3040:+Present an `AskUserQuestion` with exactly two options:
3186:-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
3211:-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
3212:+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
3256:+  - id: planning-router
3257:+    source: agents/planning-router.md
3258:+    output: .agent/rules/z-harness-planning-router.md
3427:+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
3440:+<!-- PLAN_ROUTE_CHECK_START -->
3453:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
3455:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
3458:+<!-- PLAN_ROUTE_CHECK_END -->
3472:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
3487:+<!-- PLAN_ROUTE_CHECK_START -->
3500:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
3513:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
3515:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
3518:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
3519:+<!-- PLAN_ROUTE_CHECK_END -->
3527:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
3528:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
3535: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
3539:+- "Switch to the recommended routed command"
3541: - "Abandon"
3548:-- **Never proceed past auto-bail thresholds** without explicit user override.
3760:+   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
3761:+   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
3772:+`AskUserQuestion` with two options:
3819: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
3821:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
3822:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
3831:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
3848:+<!-- PLAN_ROUTE_CHECK_START -->
3861:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
3870:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
3872:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
3874:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
3875:+<!-- PLAN_ROUTE_CHECK_END -->
3879:@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
3883:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
3884:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
3898: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
3900:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
3901:+- "Switch to the recommended routed command"
3910:-- **Never proceed past auto-bail thresholds** without explicit user override.
3925:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
3927:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
3948:+<!-- PLAN_ROUTE_CHECK_START -->
3960:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
3962:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
3965:+<!-- PLAN_ROUTE_CHECK_END -->
3984:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
3987:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
3989:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
3996:+<!-- PLAN_ROUTE_CHECK_START -->
4009:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
4011:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
4014:+<!-- PLAN_ROUTE_CHECK_END -->
4059:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
4069:+<!-- PLAN_ROUTE_CHECK_START -->
4082:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
4084:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
4087:+<!-- PLAN_ROUTE_CHECK_END -->
4165:+Present an `AskUserQuestion` with exactly two options:
4295:-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
4320:-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
4321:+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
4340:+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
4344: 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
4353:+<!-- PLAN_ROUTE_CHECK_START -->
4366:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
4368:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
4371:+<!-- PLAN_ROUTE_CHECK_END -->
4385:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
4400:+<!-- PLAN_ROUTE_CHECK_START -->
4413:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
4426:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
4428:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
4431:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
4432:+<!-- PLAN_ROUTE_CHECK_END -->
4440:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
4441:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
4448: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
4452:+- "Switch to the recommended routed command"
4454: - "Abandon"
4461:-- **Never proceed past auto-bail thresholds** without explicit user override.
4608:+   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
4609:+   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
4620:+`AskUserQuestion` with two options:
4688: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
4690:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
4691:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
4700:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
4717:+<!-- PLAN_ROUTE_CHECK_START -->
4730:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
4739:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
4741:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
4743:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
4744:+<!-- PLAN_ROUTE_CHECK_END -->
4748:@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
4752:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
4753:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
4767: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
4769:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
4770:+- "Switch to the recommended routed command"
4779:-- **Never proceed past auto-bail thresholds** without explicit user override.
4794:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
4796:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
4817:+<!-- PLAN_ROUTE_CHECK_START -->
4829:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
4831:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
4834:+<!-- PLAN_ROUTE_CHECK_END -->
4853:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
4856:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
4858:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
4865:+<!-- PLAN_ROUTE_CHECK_START -->
4878:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
4880:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
4883:+<!-- PLAN_ROUTE_CHECK_END -->
4928:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
4938:+<!-- PLAN_ROUTE_CHECK_START -->
4951:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
4953:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
4956:+<!-- PLAN_ROUTE_CHECK_END -->
5034:+Present an `AskUserQuestion` with exactly two options:
5180:-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
5205:-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
5206:+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
5470:+## planning-router
5511:+`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
5618:+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
5620:+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
5657:+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
5677:+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
5681: 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
5690:+<!-- PLAN_ROUTE_CHECK_START -->
5703:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
5705:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
5708:+<!-- PLAN_ROUTE_CHECK_END -->
5722:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
5737:+<!-- PLAN_ROUTE_CHECK_START -->
5750:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
5763:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
5765:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
5768:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
5769:+<!-- PLAN_ROUTE_CHECK_END -->
5777:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
5778:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
5785: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
5789:+- "Switch to the recommended routed command"
5791: - "Abandon"
5798:-- **Never proceed past auto-bail thresholds** without explicit user override.
6010:+   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
6011:+   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
6022:+`AskUserQuestion` with two options:
6083: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
6085:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
6086:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
6095:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
6112:+<!-- PLAN_ROUTE_CHECK_START -->
6125:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
6134:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
6136:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
6138:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
6139:+<!-- PLAN_ROUTE_CHECK_END -->
6143:@@ -60,13 +81,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
6147:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
6148:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
6162: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
6164:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
6165:+- "Switch to the recommended routed command"
6174:-- **Never proceed past auto-bail thresholds** without explicit user override.
6189:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
6191:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
6212:+<!-- PLAN_ROUTE_CHECK_START -->
6224:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
6226:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
6229:+<!-- PLAN_ROUTE_CHECK_END -->
6248:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
6251:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
6253:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
6260:+<!-- PLAN_ROUTE_CHECK_START -->
6273:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
6275:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
6278:+<!-- PLAN_ROUTE_CHECK_END -->
6323:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
6333:+<!-- PLAN_ROUTE_CHECK_START -->
6346:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
6348:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
6351:+<!-- PLAN_ROUTE_CHECK_END -->
6429:+Present an `AskUserQuestion` with exactly two options:
6559:-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
6584:-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
6585:+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
6732:+Review-generated amendment proposals (for example from `/z-review-all` `REVIEW-TASKS.md`) are inputs to this command, not permission for an implementer to mutate planning artifacts autonomously. If a promoted review task says `Class: spec_gap` or `Disposition: amendment_proposal`, route the change through `/z-amend` so the normal impact analysis, user gate, and completed-task supersession rules still apply.
6752:+Each promoted audit task must preserve the finding's source dimension, severity, evidence, files, recommendation, and verifiable acceptance criteria. Observations with no clear fix stay in `REPORT.md`. Structural or premise-level findings that exceed the audit auto-bail thresholds become `escalation.md` instead of task blocks. This command may use its own severity labels and filenames, but the artifact must remain task-shaped and consumable by `/z-implement-all`.
6756: 1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
6765:+<!-- PLAN_ROUTE_CHECK_START -->
6778:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
6780:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
6783:+<!-- PLAN_ROUTE_CHECK_END -->
6804:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
6819:+<!-- PLAN_ROUTE_CHECK_START -->
6832:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
6845:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
6847:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
6850:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
6851:+<!-- PLAN_ROUTE_CHECK_END -->
6859:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
6860:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
6867: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
6871:+- "Switch to the recommended routed command"
6873: - "Abandon"
6880:-- **Never proceed past auto-bail thresholds** without explicit user override.
7092:+   - If the sets are **equal**: fast-forward — skip the AskUserQuestion below, proceed directly to Phase 2.5. Log a `maintain_docs_audit_fast_forward` event.
7093:+   - If the sets **differ**: delete the stale state file and continue to the AskUserQuestion prompt below (re-prompt).
7104:+`AskUserQuestion` with two options:
7172: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
7174:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
7175:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
7184:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
7201:+<!-- PLAN_ROUTE_CHECK_START -->
7214:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
7223:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
7225:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
7227:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
7228:+<!-- PLAN_ROUTE_CHECK_END -->
7232:@@ -63,13 +84,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
7236:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
7237:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
7251: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
7253:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
7254:+- "Switch to the recommended routed command"
7263:-- **Never proceed past auto-bail thresholds** without explicit user override.
7278:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
7280:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
7301:+<!-- PLAN_ROUTE_CHECK_START -->
7313:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
7315:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
7318:+<!-- PLAN_ROUTE_CHECK_END -->
7337:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
7340:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
7342:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
7349:+<!-- PLAN_ROUTE_CHECK_START -->
7362:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
7364:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
7367:+<!-- PLAN_ROUTE_CHECK_END -->
7412:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
7422:+<!-- PLAN_ROUTE_CHECK_START -->
7435:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
7437:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
7440:+<!-- PLAN_ROUTE_CHECK_END -->
7518:+Present an `AskUserQuestion` with exactly two options:
7648:-Present a short version to the user (counts + top blockers) and ask via `AskUserQuestion` what to do with the findings. Options:
7673:-- **Never** edit SPEC.md or TASKS.md automatically. Always present changes to the user first (use `AskUserQuestion` for confirmation on each substantive edit, or stage edits in a draft file and let the user accept).
7674:+- **Never** edit SPEC.md or TASKS.md automatically. Stage review findings in `REVIEW-TASKS.md` or an amendment proposal and let the user prune/apply them.
7692:+<!-- PLAN_ROUTE_CHECK_START -->
7705:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
7707:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
7710:+<!-- PLAN_ROUTE_CHECK_END -->
7732:+4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
7747:+<!-- PLAN_ROUTE_CHECK_START -->
7760:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
7773:+→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
7775:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
7778:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
7779:+<!-- PLAN_ROUTE_CHECK_END -->
7787:-**Check auto-bail thresholds before implementing.** If the file list is >3 or any item is a non-obvious decision, halt now and recommend escalation.
7788:+**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.
7795: If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
7799:+- "Switch to the recommended routed command"
7801: - "Abandon"
7808:-- **Never proceed past auto-bail thresholds** without explicit user override.
7827: **If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.
7829:-This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the auto-bail thresholds below, STOP, save context, and recommend `/z-plan` instead.
7830:+This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.
7839:+5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
7856:+<!-- PLAN_ROUTE_CHECK_START -->
7869:+Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.
7878:+→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.
7880:+`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
7882:+Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
7883:+<!-- PLAN_ROUTE_CHECK_END -->
7887:@@ -63,13 +85,13 @@ If any concern surfaces → raise it with the user via `AskUserQuestion` before
7891:-**Check auto-bail thresholds.** If reading reveals >5 candidate files or cross-module impact, bail now.
7892:+**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.
7906: **Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
7908:-- "Switch to full `/z-plan` — abort this run, save context, run /z-plan"
7909:+- "Switch to the recommended routed command"
7918:-- **Never proceed past auto-bail thresholds** without explicit user override.
7939:-11. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
7941:+10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.
7962:+<!-- PLAN_ROUTE_CHECK_START -->
7974:+Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.
7976:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
7979:+<!-- PLAN_ROUTE_CHECK_END -->
8004:-   The user can override via `AskUserQuestion` ("refresh now" / "proceed with stale docs" / "abandon"). If they proceed with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
8007:+8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
8009:     - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
8016:+<!-- PLAN_ROUTE_CHECK_START -->
8029:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8031:+If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.
8034:+<!-- PLAN_ROUTE_CHECK_END -->
8079:   /z-implement-all  — orchestrate the queue (auto-includes TESTS.md if present, or /z-implement-next for one-at-a-time)
8095:+<!-- PLAN_ROUTE_CHECK_START -->
8108:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8110:+If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.
8113:+<!-- PLAN_ROUTE_CHECK_END -->
8118:diff --git a/agents/planning-router.md b/agents/planning-router.md
8122:+++ b/agents/planning-router.md
8125:+name: planning-router
8168:+`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
8275:+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
8277:+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
8293:+<!-- PLAN_ROUTE_CHECK_START -->
8306:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8308:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
8311:+<!-- PLAN_ROUTE_CHECK_END -->
8326:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
8327:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
8467:+3. **Ask user via `AskUserQuestion`:**
8640:diff --git a/exports/agy/.agent/rules/z-harness-planning-router.md b/exports/agy/.agent/rules/z-harness-planning-router.md
8644:+++ b/exports/agy/.agent/rules/z-harness-planning-router.md
8688:+`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
8795:+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
8797:+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
8813:+<!-- PLAN_ROUTE_CHECK_START -->
8826:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
8828:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
8831:+<!-- PLAN_ROUTE_CHECK_END -->
8846:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
8847:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
8987:+3. **Ask user via `AskUserQuestion`:**
9019:+<!-- PLAN_ROUTE_CHECK_START -->
9032:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
9034:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
9037:+<!-- PLAN_ROUTE_CHECK_END -->
9052:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
9053:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
9193:+3. **Ask user via `AskUserQuestion`:**
9366:diff --git a/exports/agy/prompts/planning-router.md b/exports/agy/prompts/planning-router.md
9370:+++ b/exports/agy/prompts/planning-router.md
9414:+`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
9521:+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
9523:+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
9539:+<!-- PLAN_ROUTE_CHECK_START -->
9552:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
9554:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
9557:+<!-- PLAN_ROUTE_CHECK_END -->
9572:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
9573:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
9713:+3. **Ask user via `AskUserQuestion`:**
9746:+<!-- PLAN_ROUTE_CHECK_START -->
9759:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
9761:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
9764:+<!-- PLAN_ROUTE_CHECK_END -->
9779:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
9780:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
9920:+3. **Ask user via `AskUserQuestion`:**
9950:+<!-- PLAN_ROUTE_CHECK_START -->
9963:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
9965:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
9968:+<!-- PLAN_ROUTE_CHECK_END -->
9983:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
9984:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
10124:+3. **Ask user via `AskUserQuestion`:**
10297:diff --git a/exports/cursor/.cursor/rules/planning-router.mdc b/exports/cursor/.cursor/rules/planning-router.mdc
10301:+++ b/exports/cursor/.cursor/rules/planning-router.mdc
10345:+`STATUS: ask_user` is only for loop-risk or conflicting-signal cases where another automatic recommendation would be unsafe. It must use `RECOMMENDED: ask_user`, `ROUTE_CLASS: none`, and include `route_loop_risk` or `ambiguous_route` in `REASON_CODES`.
10452:+- `low`: conflicting or sparse signals remain; prefer `STATUS: ask_user` if an automatic route would be unsafe.
10454:+The caller owns the final decision. A malformed return is ignored by the caller, which falls back to deterministic routing or an AskUser choice.
10470:+<!-- PLAN_ROUTE_CHECK_START -->
10483:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
10485:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
10488:+<!-- PLAN_ROUTE_CHECK_END -->
10503:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
10504:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
10644:+3. **Ask user via `AskUserQuestion`:**
10677:+<!-- PLAN_ROUTE_CHECK_START -->
10690:+Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.
10692:+If routing after a plan is selected, write `$BASE/archive/$RUN/route-decision.md` after `$BASE` and `$RUN` are known. If routing because no plan artifacts exist, use the pre-discovery `$NO_PLAN_ARCHIVE_DIR/route-decision.md` and `$NO_PLAN_RUN` initialized in Phase 0. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue only when plan artifacts exist, or abandon. Do not execute the next command automatically.
10695:+<!-- PLAN_ROUTE_CHECK_END -->
10710:+   - If multiple candidates -> use `AskUserQuestion` to select the slug (or honor `--slug <slug>` argument if provided).
10711:+   - If zero -> `mkdir -p "$NO_PLAN_ARCHIVE_DIR"`, write `$NO_PLAN_ARCHIVE_DIR/route-decision.md` recommending `/z-plan`, emit `plan_route_decision` under `$NO_PLAN_RUN`, ask the user to switch or abandon, and stop. Do not create an audit report without plan artifacts.
10851:+3. **Ask user via `AskUserQuestion`:**

exec
/bin/zsh -lc "sed -n '1,220p' commands/z-do.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
4. `CURRENT_ARCHIVE_DIR="z-harness/adhoc/archive/$RUN"`
5. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_start "$START_PAYLOAD"
   ```
6. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).

## Plan Route Check

<!-- PLAN_ROUTE_CHECK_START -->
Run this check after premise/doc grounding and before writing `approach.md`; run it again before implementation if the file count or decision count grows. `/z-do` may route only to `/z-plan-light`, `/z-plan`, `/z-research`, `/z-brainstorm`, `/z-fix`, or `/z-debug` under the conditions below. It must not route to `/z-plan-split` directly.

Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route to `/z-plan-light <task>` when this is still a small targeted implementation/fix but exceeds `/z-do` limits: `candidate_files > 3` or `non_obvious_decisions > 0`, while `candidate_files <= 5`, `non_obvious_decisions <= 2`, and there is no cross-module, schema, persistence, public API, or wire-format impact.
- Route to `/z-plan <task>` when the task has cross-module impact, schema/persistence impact, public API or wire-format impact, more than 5 candidate files, or more than 2 non-obvious decisions.
- Route to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or this is no-code terrain mapping.
- Route to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
- Route to `/z-fix <diagnosis>` only when the user has a concrete bug hypothesis or diagnosis.
- Route to `/z-debug <symptom>` only when the user has an observed bug/symptom and the root cause is unknown.

Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.

If at any point you discover:

- **>3 files** need editing
- **Any non-obvious decision** surfaces (new dep, public API change, persistence change, algorithm choice with materially different tradeoffs)
- **Cross-module / cross-crate impact** OR **schema change**
- User says "this might be bigger than I thought"

→ Halt the current flow behind a route gate: write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, log the legacy `do_escalation` event as compatibility telemetry if this replaces an old escalation branch, push-notify, and ask the user to switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.

`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase 1 — Premise check (mandatory, quick)

One paragraph in main thread: is the stated task actually the right problem? Could it be config, expected behavior, or symptom of something else? Is there a materially better path?

If a concern surfaces → raise via `AskUserQuestion` before proceeding. Otherwise, write a single-sentence "premise accepted: <restated goal>" and continue.

Save to `z-harness/adhoc/archive/$RUN/premise.md`.

## Phase 2 — Ground (doc-fetcher first)

Per the global rule, if `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) BEFORE any other reading:

```
Agent(subagent_type="doc-fetcher",
      description="Doc context for: <task>",
      prompt="query: <one-sentence task>\nrepo_root: <abs path>\ndepth: standard")
```

Use its return to constrain what files you read next. If `STATUS: no_docs` / `no_match` / `partial`, fall back to direct Read/Grep/Glob — do NOT spawn Explore in `/z-do` (too expensive for this command).

Read at most 3-5 files from main thread to fill gaps.

If a `DRIFT WARNING` came back, log `doc_drift` and continue.

## Phase 3 — Inline approach note (NO decisions.md, NO upfront consult)

In a single short message to yourself, state:
- What you're about to change (2-3 sentences)
- Files to touch (list)
- Acceptance: how you'll know it worked

Save to `z-harness/adhoc/archive/$RUN/approach.md`. This is the entire "plan" — no PLAN.md, no TASKS.md, no FIX.md.

**Check the Plan Route Check before implementing.** If the file list is >3 or any item is a non-obvious decision, use `$CURRENT_ARCHIVE_DIR/route-decision.md` and the `plan_route_decision` gate instead of a separate escalation prompt.

## Phase 4 — Implement inline

Edit / Write the files. Apply the implementer self-check:

1. No broad exception handlers added.
2. No scope expansion outside `approach.md` "Files to touch".
3. No unsolicited validation / error paths.
4. No new public surface beyond what `approach.md` describes.
5. No stale docstrings / comments left behind.

If mid-implementation you discover scope growth → halt and `AskUserQuestion`:
- "Switch to the recommended routed command"
- "Continue in z-do — update approach.md" (only if no hard threshold forbids continuation)
- "Abandon"

Hard limit: if you find yourself touching >5 files inline, halt regardless.

## Phase 5 — Codex review (MANDATORY safety gate)

Non-negotiable. This is what makes `/z-do` z-harness rather than freewheeling.

```bash
git diff > z-harness/adhoc/archive/$RUN/diff.patch
```

Spawn the reviewer:

```
Agent(
  subagent_type="reviewer",
  description="Codex review of /z-do <run>",
  prompt="task id: <RUN>\ntask description: <approach.md body, ≤500 chars>\nacceptance criteria: <approach.md Acceptance line>\ndiff.patch path: <abs path>\nchanged files: <abs paths>\n$BASE: z-harness/adhoc/archive/$RUN  (read approach.md and premise.md yourself if you need more context)"
)
```

Parse the return (capped at 8 KB, blockers + majors only).

**On blockers/majors:**
- First failure: re-edit inline. Re-run diff; if byte-identical → halt `no_change_on_retry`. Else re-spawn reviewer once.
- Second failure: `AskUserQuestion` — proceed anyway / patch manually / abandon.

**No blockers/majors** → accept.

## Phase 6 — (Optional) end-of-run cross-LLM consult

This phase is **off by default**. Only run if any of:

- User explicitly asked for a consult ("get a second opinion")
- A non-obvious decision DID surface mid-run but you continued (rare — usually you'd escalate)
- The implementation diverges meaningfully from the stated approach.md

If running, spawn one or both consultants on the **diff + approach**, framed as "review this small change — anything wrong?":

```
Agent(subagent_type="consultant-secondary",
      description="End-of-run consult for /z-do <RUN>",
      prompt="MODE: post-do-review\n\nTask: <approach summary>\nDiff: <inline or path>\nCodex-reviewer findings: <accepted / what was waived>\n\nAsk: is this change sound? Anything the reviewer missed?")
```

Apply the "one reason it might be wrong" check to each finding. If it raises a real concern, halt and ask the user.

## Phase 7 — Finalize

1. Log run end:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" do_run_end \
     "$(printf '{"status":"shipped","files_changed":%d,"review_cycles":%d,"consult_at_end":%s}' \
        "$N_FILES" "$CYCLES" "$DID_CONSULT")"
   ```
2. Push-notify (if policy ≠ `off`): "z-do complete. <N> files changed; review passed."
3. Brief 2-3 sentence summary to user: what changed, what's next.
4. If non-trivial friction surfaced during the run (auto-bail considered, doc_drift, retry on review), suggest: "Consider `/z-improve adhoc/$RUN` to retro this run."

## Hard rules

- **Doc-fetcher first** (per global CLAUDE.md rule) whenever `docs/llm/INDEX.json` exists.
- **No upfront cross-LLM consult.** Only at the end, only if triggered.
- **Codex review is non-negotiable.** Skipping it makes /z-do not-z-harness.
- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
- **Never read `docs/llm/*.json` from main thread.**
- **Always log to `z-harness/adhoc/archive/$RUN/`** — `/z-improve` reads this.
- **No emojis.**

exec
/bin/zsh -lc "sed -n '1,240p' commands/z-plan-light.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Lightweight planner for small targeted changes / bug fixes. Bundled cross-LLM consult, single FIX.md artifact, inline implementation in the orchestrator (no implementer subagent), codex review still runs as the safety gate. Routes down, up, sideways, or to contextual bug workflows when light mode is not the best fit.
argument-hint: <fix description>
---

You are running **z-harness `/z-plan-light`** — a fast path for one-file-or-few-files fixes. Target: ≤10 min wall time end-to-end.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty** — use `AskUserQuestion` to ask "What's the fix?" before proceeding. Do not invent.

This command is for **small, focused changes**. If at any phase you realize the task is genuinely bigger than the Plan Route Check thresholds below, STOP, save context in `route-decision.md`, and recommend the routed command instead.

## Setup

1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
2. Export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
3. Pick run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
5. `CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"`
6. **Version stamp + log:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_start "$START_PAYLOAD"
   ```
7. Notification policy: read `Z_HARNESS_NOTIFY` (default `approval_only`).
8. If `docs/llm/INDEX.json` exists → note it. Phase 1 will dispatch `doc-fetcher` (Haiku). Do NOT read INDEX.json or per-concept JSONs from main thread.

## Plan Route Check

<!-- PLAN_ROUTE_CHECK_START -->
Run this check after quick exploration and before Phase 2 decision selection; run it again before inline implementation if scope grows. `/z-plan-light` may route down, up, sideways, or to contextual bug workflows only under the conditions below.

Collect only already-known deterministic signals: `candidate_files`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route down to `/z-do <task>` only before writing `FIX.md` when this is a tiny implementation task with `candidate_files <= 3`, no non-obvious decisions, and no cross-module, schema, persistence, public API, or wire-format impact.
- Route up to `/z-plan <task>` when there are more than 5 candidate files, more than 2 non-obvious decisions, cross-module impact, schema/persistence impact, or public API/wire-format impact.
- Route sideways to `/z-research <topic>` when terrain is uncertain, source facts cannot yet be cited, or no-code terrain mapping is the next needed step.
- Route sideways to `/z-brainstorm <topic>` when terrain is sufficiently known but multiple plausible framings or approaches would materially change the plan.
- Route contextually to `/z-fix <diagnosis>` only when the user already has a concrete bug hypothesis or diagnosis.
- Route contextually to `/z-debug <symptom>` only when there is an observed bug/symptom and the root cause is unknown.

Call `planning-router` only when deterministic signals conflict, confidence is medium, no hard threshold already mandates a route, and the same `reason_codes` have not already used the router in this run.

At any phase, if you discover:

- **>5 candidate files** need editing
- **>2 non-obvious decisions** (per the rules `/z-plan` uses: new dep, public API change, algorithm with materially different tradeoffs, persistence change)
- **Cross-module / cross-crate impact** (the fix touches multiple crates, public APIs, wire formats, or schemas)
- **The user explicitly says** "this might be bigger than I thought"

→ STOP behind a route gate. Write `$CURRENT_ARCHIVE_DIR/route-decision.md`, emit `plan_route_decision`, preserve `light_run_end` and any legacy escalation status as compatibility telemetry, and push-notify. Use `AskUserQuestion` with switch / continue if the hard threshold allows continuation / abandon. If the user chooses switch, stop after presenting the exact next command invocation; do not execute it.

`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

Loop prevention: carry forward the latest route chain from any supplied or discovered `route-decision.md`; if the chain already has two entries, ask the user to choose instead of routing again; if the target equals the immediate prior source command, present both route artifacts and ask the user to choose.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase 1 — Premise + quick exploration (combined)

**Premise check.** Don't take the task description for granted:
- Is this actually a bug? Could it be config / expected behavior / a symptom of something else?
- Will the proposed fix (if the user named one) actually solve the underlying problem?
- Is there a materially better path the user hasn't considered?

If any concern surfaces → raise it with the user via `AskUserQuestion` before proceeding. Don't plan around a flawed premise.

**Quick exploration.**
1. **If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku) FIRST** — it's the cheapest grounding available. One call, returns ≤2 KB synthesis:
   ```
   Agent(subagent_type="doc-fetcher",
         description="Doc context for <slug>",
         prompt="query: <one-sentence fix description>\nrepo_root: <abs path>\ndepth: standard")
   ```
2. After doc-fetcher returns (or if no INDEX.json), Read 3-5 source files MAX to fill gaps. **DO NOT spawn the `Explore` subagent** — too expensive for light-mode. Use Read/Grep/Glob directly from main thread.

Output: 1-paragraph problem statement + 1-paragraph context. Save to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-context.md`.

**Check the Plan Route Check.** If reading reveals >5 candidate files or cross-module impact, write `$CURRENT_ARCHIVE_DIR/route-decision.md` and use the `plan_route_decision` handoff gate now.

## Phase 2 — Identify the single key decision

Most light tasks have ONE root question (e.g. "what's the right algorithm?", "what's the root cause?", "where should this live?"). Articulate it explicitly.

If there are >2 truly non-obvious decisions, use the Plan Route Check to recommend `/z-plan` — the cross-decision interaction analysis that full `/z-plan` does is worth it.

## Phase 3 — Bundled cross-LLM consult

Spawn both consultants in parallel in a single message:

```
Agent(
  subagent_type="consultant-primary",
  description="Light-fix consult (Gemini) for <slug>",
  prompt="MODE: light-fix\n\nProblem: <1-paragraph>\nContext: <1-paragraph>\nKey decision: <statement>\nCandidate options (if any): <list with one-line tradeoffs>\nRelevant code snippets:\n<short quoted code with file:line markers>\n\nAsk: recommend an option with reasoning. Identify tradeoffs. Flag anything I haven't considered. Be concise — this is a single small fix, not a feature."
)
Agent(
  subagent_type="consultant-secondary",
  description="Light-fix consult (Codex) for <slug>",
  prompt="MODE: light-fix\n\n<same prompt body>"
)
```

Both transcripts archive themselves under `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts/`.

## Phase 4 — Synthesize + push back

When both return:

1. **One reason it might be wrong.** For each recommendation, articulate one concrete reason it could be wrong before accepting it. Mechanical, not optional.
2. **Synthesize.** Make the final call yourself, citing what you weighed.
3. **Flag shortcuts.** If any option is a shortcut over the robust long-lasting solution, mark it explicitly — needs Phase 5 user approval.
4. **Cross-LLM disagreement.** If Gemini and Codex disagree substantively, surface the disagreement to the user in Phase 5 — do not silently pick one.

## Phase 5 — Present + approve

Send `PushNotification` (if policy != `off`): "Light-mode decision ready for review."

Present a brief synthesis (3-5 bullets) via `AskUserQuestion`:
- "Approve fix as proposed"
- "Modify — I want to change <X>" (free-text follow-up)
- "Abandon — this isn't the right approach"

For any flagged shortcut: separate explicit approval via `AskUserQuestion` (default to robust if not approved).

If user picks **Abandon** → write nothing more; log `light_run_end` with `status: abandoned`; exit.

## Phase 6 — Write FIX.md

Write `$Z_HARNESS_PLAN_DIR/FIX.md`:

```markdown
# Fix: <slug>

**Run:** <RUN>
**Status:** approved (not yet shipped)
**Plugin version:** <z_harness_version from setup>

## Problem
<1 paragraph>

## Root cause
<1 paragraph>

## Approach
<concrete plan: what files change, what stays the same>

## Files to change
- `<abs path 1>`
- `<abs path 2>`

## Acceptance
- [ ] <criterion 1>
- [ ] <criterion 2>

## Cross-LLM consensus
- Gemini: <one-line recommendation>
- Codex:  <one-line recommendation>
- Synthesized call: <your decision + brief rationale>

## Approved shortcuts
<list each shortcut + why approved; or "none">

## Docs touched
<slug(s) from docs/llm/ matching changed files, or "none"; consumed by /z-maintain-docs later>
```

No SPEC.md / PLAN.md / TASKS.md generated. FIX.md is the whole plan.

## Phase 7 — Inline implementation (NO implementer subagent)

The orchestrator (you, in main thread) reads the files listed in FIX.md "Files to change" and applies the edits directly with the Edit / Write tools. For 1-5 file edits the main thread already has all the context — spawning a fresh implementer just doubles token cost.

**Apply the same self-check the implementer subagent would** (from `agents/implementer.md`):
1. No broad exception handlers added.
2. No scope expansion outside FIX.md's "Files to change" list.
3. No unsolicited validation / error paths.
4. No new public surface beyond what FIX.md describes.
5. No stale docstrings / comments left behind.

If you applied any fix from the checklist, note it in the user-facing summary later.

**Escape hatch — mid-implementation scope growth.** If you discover mid-edit that the change needs more files than FIX.md anticipated, OR a new non-obvious decision surfaces, STOP and ask the user via `AskUserQuestion`:
- "Switch to the recommended routed command"
- "Continue in light mode — update FIX.md and proceed" (only if no hard threshold forbids continuation)
- "Spawn implementer subagent for isolation — keep light mode but isolate the implementation"

Hard limit: if you find yourself touching >7 files inline, halt regardless — that's no longer a light-mode fix.

## Phase 8 — Codex review (safety gate, kept)

This step is non-negotiable. Even in light mode, post-implementation review is the correctness guarantee.

```bash
git diff > $Z_HARNESS_PLAN_DIR/archive/$RUN/diff.patch
```

Spawn the reviewer:

```
Agent(
  subagent_type="reviewer",
  description="Codex review of <slug>",
  prompt="task id: <slug>\ntask description: <FIX.md Approach summary>\nacceptance criteria: <FIX.md Acceptance list>\ndiff.patch path: <abs path>\nchanged files: <abs paths from FIX.md>\nrelevant_docs (paths — verify the diff didn't break invariants stated here): <paths from FIX.md Docs touched>\n$BASE: $Z_HARNESS_PLAN_DIR  (read FIX.md yourself if you need more context)"
)
```

Parse the return (already capped at 8 KB, blockers + majors only).

**On blockers or majors:**
- **First failure**: re-edit inline based on findings. Re-run `git diff`; if byte-identical to prior diff (you pushed back instead of editing), halt with `no_change_on_retry`. Otherwise re-spawn `reviewer` once.
- **Second failure**: halt; `AskUserQuestion` — proceed anyway / patch manually / abandon.

**No blockers/majors** → accept.

## Phase 9 — Finalize

1. Update FIX.md `Status:` to `shipped` and check off the acceptance boxes you verified.
2. Mark the run done:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" light_run_end \
     "$(printf '{"status":"shipped","files_changed":%d,"review_cycles":%d}' "$N_FILES" "$CYCLES")"
   ```
3. Push-notify (if policy != `off`): "Fix complete. <N> files changed; review passed (<N> blockers/<M> majors resolved across <C> cycles)."
4. **If FIX.md "Docs touched" is non-empty**, suggest: "Run `/z-maintain-docs --audit` to refresh affected concepts."
5. Brief summary to user (3-5 sentences): what changed, what the reviewer flagged, what's next.

## Hard rules

- **Never skip the codex review.** Light mode is about cutting planning overhead, not correctness.
- **Never proceed past Plan Route Check hard thresholds** without explicit user override.
- **Always emit cross-LLM consult** — both Gemini and Codex, in parallel.

exec
/bin/zsh -lc "sed -n '1,220p' commands/z-plan-split.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,240p' commands/z-plan.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Pre-emptive scope splitter — fan a big topic out into N narrow cluster-planner subagents in parallel, then reconcile file-path overlaps into SHARED-CONCERNS.md + MANIFEST.md.
argument-hint: <topic> [--slug=<root-slug>] [--clusters="a,b,c"]
---

You are running the **z-harness `/z-plan-split`** pipeline.

Topic + flags (from `$ARGUMENTS`):

$ARGUMENTS

**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I split?". Wait for their reply. Treat the reply as the topic and continue.

`/z-plan-split` is a **pre-emptive scope splitter** for topics that would otherwise produce a sprawling ≥40-task `/z-plan` run. Instead of one mega-plan, it dispatches N parallel `cluster-planner` subagents (each producing a focused 5-15-task plan), then writes `SHARED-CONCERNS.md` (file-overlap observation, ack-gated) and `MANIFEST.md` (cluster listing + run order). It does NOT produce production code. One-level recursion only — nested MANIFESTs are explicitly out of scope.

## Setup

1. **Derive root slug.**
   - If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim.
   - Else if `$ARGUMENTS` contains `--clusters="a,b,c"`, the slug is auto-derived from the topic (kebab-case, 2-4 words). The `--clusters` flag overrides Phase 1's automatic proposal.
   - Otherwise auto-derive from the topic (kebab-case, 2-4 words). If non-obvious, confirm via `AskUserQuestion`.
2. **Validate the slug (mandatory — security gate).** The slug is interpolated into filesystem paths and must be a single safe segment. Reject (refuse with a clear error and exit cleanly) if the slug:
   - is empty or whitespace-only;
   - contains any character outside `[a-z0-9-]` (kebab-case only — no `/`, `\`, spaces, `:`, `..`, `~`, `$`, quotes, etc.);
   - contains `..` anywhere (even as a substring);
   - starts with `-` or `.`, or ends with `-`;
   - contains `//` or path separators of any kind.

   Concretely: the slug must match the anchored regex `^[a-z0-9]+(-[a-z0-9]+)*$`. Reject values like `../x`, `foo/bar`, `.hidden`, `a b`, empty string, `a..b`. Error message: `"Invalid slug: must be a single kebab-case segment matching ^[a-z0-9]+(-[a-z0-9]+)*$ (no slashes, dots, or path traversal). Got: <value>"`. Do not fall through to a sanitized version; force the user to re-invoke with a valid slug.
3. **Export** `Z_HARNESS_SLUG=<root-slug>` for all subsequent shell calls and subagents — this namespaces every output path under `z-harness/<root-slug>/`.
4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
   - **overwrite** — move the **entire prior tree** (every file and subdirectory under `$Z_HARNESS_PLAN_DIR/` *except* the just-created `archive/<RUN>/` directory itself) into `$Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree/`. This includes the old `MANIFEST.md`, `SHARED-CONCERNS.md`, all prior `<cluster-slug>/` subdirectories, and any other stale artifacts — so no stale cluster trees survive into the new run. Implementation sketch: `mkdir -p $Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree && find $Z_HARNESS_PLAN_DIR/ -mindepth 1 -maxdepth 1 ! -name archive -exec mv {} $Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree/ \;` (move any existing `archive/previous-*` subdirs separately if needed). Then start fresh.
   - **abort** — exit cleanly with no changes. Per the Early-exit telemetry contract, emit `plan_split_run_end` with `status: "aborted_existing_tree"` before returning (no `phase_end` — no phase is active yet at Setup time).
   No "append" option (D10 — append flow was under-specified; drop it).
7. **Version stamp + log run start.** Merge the version blob with the topic and emit `plan_split_run_start` with `topic_chars`:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1])
   v["topic"] = sys.argv[2]
   v["topic_chars"] = len(sys.argv[2])
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<topic-text>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_start "$START_PAYLOAD"
   ```
   Output lands under `z-harness/<root-slug>/archive/$RUN/events.jsonl`.
8. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
9. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, do NOT read it from main thread. Note its existence; Phase 1 may dispatch `doc-fetcher` (Haiku) for one-shot topic grounding. Skip the docs-freshness gate — this command does not itself touch INDEX.json; cluster-planners handle their own doc reads.
10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.

**All paths in subsequent phases live under `z-harness/<root-slug>/`:**
- `z-harness/<root-slug>/MANIFEST.md`
- `z-harness/<root-slug>/SHARED-CONCERNS.md`
- `z-harness/<root-slug>/<cluster-slug>/{SPEC.md,PLAN.md,TASKS.md}` (one per cluster — directory uses the kebab-case `cluster_slug`)
- `z-harness/<root-slug>/archive/<RUN>/...`

## Cluster identity (terminology — used consistently below)

Every cluster has **two distinct stable fields**:

- **`cluster_id`** — a short, stable, opaque handle of the form `C1`, `C2`, …, `CN`, assigned in confirmation order. Used in **telemetry payloads** (every event's `cluster_id` field), MANIFEST table's first column, and cross-references in SHARED-CONCERNS.md (`Touched by: <cluster_id> (<task_id>)`). Never used as a path segment.
- **`cluster_slug`** — the kebab-case name the user (or the auto-proposer) chose, e.g. `auth-refactor`. Must independently match `^[a-z0-9]+(-[a-z0-9]+)*$` (same validator as the root slug, step 2). Used as the **on-disk directory name** under `z-harness/<root-slug>/<cluster_slug>/`. Never used in telemetry payloads.

Where this doc previously wrote `<cluster-id>` in a filesystem path, read it as `<cluster_slug>`. Where this doc writes a `cluster_id` field in a JSON payload, it is the `C1`/`C2` form. MANIFEST.md rows include both: `ID` column = `cluster_id`, `Path` column = `<root-slug>/<cluster_slug>/`.

## Early-exit telemetry contract (mandatory for every exit path)

**Every** exit from this command — successful, refused, aborted, paused, or failed — MUST emit the matching `phase_end` for the currently-active phase (if any) **and** a single `plan_split_run_end` event before returning. The `status` field on `plan_split_run_end` distinguishes the exit reason. No exit path may silently skip these events; the post-run analyzer relies on `plan_split_run_end` always being present.

Allowed `status` values on `plan_split_run_end`:

- `ready` — Phase 5 finalized with all clusters ready.
- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
- `abandoned_by_user` — user picked "Abandon" in Phase 1d (or "Abandon this cluster" elided the last surviving cluster).
- `aborted_existing_tree` — user picked "abort" at the existing-slug prompt (Setup step 6). No `phase_end` to emit (no phase active yet).
- `aborted_too_few_clusters` — Phase 1 refused (<2 seams). Emit `phase_end` for Phase 1 first.
- `aborted_too_many_clusters` — Phase 1 refused (>6 seams). Emit `phase_end` for Phase 1 first.
- `aborted_invalid_slug` — Setup step 2 / 10 rejected the slug or a cluster name. No `phase_end` (no phase active yet).
- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.

Payload shape for early exits (when full counts aren't available yet, use `null` or `0`):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_end \
  "$(printf '{"status":"%s","total_clusters":%s,"clusters_ready":%s,"clusters_failed":%s,"overlap_count":%s,"partial_tree":%s,"reason":"%s"}' \
     "$STATUS" "${N:-0}" "${K:-0}" "${F:-0}" "${O:-0}" "${PT:-false}" "$REASON_SHORT")"
```

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 5), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so post-run analysis can separate machine time from human-wait time:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Cluster proposal

Main thread only. **Do NOT spawn a subagent** — cluster proposal is small-context and benefits from sitting alongside the topic.

### 1a. Optional doc grounding (if INDEX.json exists, Setup step 9)

If `docs/llm/INDEX.json` exists, dispatch ONE `doc-fetcher` (Haiku) call for topic grounding:

```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <root-slug>",
  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
)
```

If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept. Use its synthesis to inform cluster naming. If it returns `STATUS: no_docs` / `no_match`, proceed without doc grounding.

### 1b. Propose 2-6 clusters

Read the topic (+ doc-fetcher synthesis if present). Propose **2-6 narrow scopes**, each as:

- A **kebab-case name** (this becomes the cluster slug + directory name, e.g. `auth-refactor`).
- A **1-line scope description** stating what the cluster IS responsible for and what it is NOT (handoff boundary with siblings).

**Hard limits:**
- If fewer than 2 distinct seams surface, **refuse** the split: print "Topic does not warrant /z-plan-split — only 1 coherent seam found. Run /z-plan <topic> directly." Then emit `phase_end` for Phase 1 and `plan_split_run_end` with `status: "aborted_too_few_clusters"` (per the Early-exit telemetry contract), and exit cleanly. Do not write MANIFEST.md.
- If more than 6 seams surface, **refuse** the split: print "Topic too broad — >6 seams found. Narrow the topic and re-invoke, or accept a coarser split." Then emit `phase_end` for Phase 1 and `plan_split_run_end` with `status: "aborted_too_many_clusters"`, and exit cleanly.

If `--clusters="a,b,c"` was passed in Setup step 10, the proposed name list is the parsed flag value; still validate 2-6 bounds. Phase 1 must still derive a one-line scope per name — either inferred from the topic text or asked interactively (see Setup step 10). Same refusal + telemetry rules apply if the post-derivation list violates 2-6 bounds.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Phase 1b proposes cluster seams and before user confirmation or writing `proposed-clusters.md`. Preserve the 2-6 cluster invariant: fewer than 2 seams must not continue as `/z-plan-split`, and more than 6 seams must not dispatch cluster-planners without topic narrowing or a coarser split. Use only already-known signals: `cluster_seams`, `expected_tasks`, `terrain_uncertain`, `approach_uncertain`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `candidate_files`, `docs_stale_or_drifted`, and the current route chain.

Deterministic routes:
- If `cluster_seams < 2`, write a route decision to `/z-plan` with `reason_codes: ["too_few_clusters"]`, emit the existing `aborted_too_few_clusters` terminal telemetry, and stop. This hard-refusal branch may use `user_choice: "not_asked"` because continuation would violate the split invariant.
- If `cluster_seams > 6`, stop before planner dispatch; recommend narrowing the topic or routing to `/z-research` when the excess seams come from unknown terrain (`reason_codes: ["too_many_clusters"]` or `["too_many_clusters","needs_research"]`).
- If seams are unknown because terrain or ownership boundaries cannot be cited, route to `/z-research` with `reason_codes: ["needs_research"]`.
- If `cluster_seams` is in `2..6` and each seam is independently plannable, stay in `/z-plan-split`.
- If the request is actually a small concrete fix or medium coherent plan with no independent seams, route to `/z-plan-light` or `/z-plan` using the primary route matrix.

Call `planning-router` only when the seam count is plausible but conflicting signals make `/z-plan`, `/z-plan-split`, and `/z-research` comparably reasonable. It receives a compact signal payload plus the route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an explicit AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

### 1c. Write proposal artifact

Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/proposed-clusters.md` with one block per cluster (name + scope). For each proposed cluster, log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_proposed \
  "$(printf '{"cluster_id":"%s","cluster_name":"%s","scope":%s}' \
     "$CLUSTER_ID" "$CLUSTER_NAME" "$(printf '%s' "$SCOPE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')")"
```

### 1d. User confirmation

Bracket the wait with `user_wait_start` / `user_wait_end`. Use `AskUserQuestion` with previews — one option per proposed cluster (preview = `<name>: <scope>`), plus three meta-options:

- **Approve as proposed** — proceed to Phase 2 with the listed clusters.
- **Edit** — free-text follow-up; user can rename clusters, rewrite scopes, add/drop clusters (still bounded 2-6).
- **Abandon** — exit cleanly with no further work. Per the Early-exit telemetry contract: emit `phase_end` for Phase 1 first, then `plan_split_run_end` with `status: "abandoned_by_user"` and a short `reason` (e.g. `user_abandoned_phase1`).

If the user picks **Edit**, re-loop Phase 1c after applying their edits (re-write `proposed-clusters.md`, re-confirm). Maximum 3 edit iterations to avoid pathological loops — after that, ask the user to abandon or commit.

### 1e. Write confirmed-clusters artifact

After approval, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/confirmed-clusters.md` with the final cluster list (name + scope, one block per cluster, fixed display order matching MANIFEST run-order). For each confirmed cluster, log:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cluster_confirmed \
  "$(printf '{"cluster_id":"%s","confirmed_clusters_total":%d}' "$CLUSTER_ID" "$TOTAL")"
```

Send a `PushNotification` if `Z_HARNESS_NOTIFY` is `approval_only` or `all`.

---

## Phase 2 — Parallel cluster-planner dispatch

Spawn **all N cluster-planners in parallel in a single message**. Each receives the **identical** root-topic context + the full sibling-cluster list (so each leaf knows what its siblings own and can stay in-scope).

For each confirmed cluster, build the prompt:

```
<topic context — verbatim from $ARGUMENTS>

Sibling clusters (for scope-boundary awareness):
- C1 <name>: <scope>
- C2 <name>: <scope>
- ...

cluster-id: <Cn>
cluster-name: <name>
cluster-scope: <scope>
root-slug: <root-slug>
output-path: z-harness/<root-slug>/<cluster-id>/
run-id: <RUN>
repo-root: <abs path to repo root>
```

Dispatch (single message, N parallel calls):


 succeeded in 0ms:
---
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
argument-hint: <feature or task description>
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Check for existing slug dirs in the canonical plans directory (`z-harness/plans/`) and the legacy directory (`z-harness/`). If a matching slug dir is found:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
   Then log provider resolution (once per run, guarded against re-emission):
   ```bash
   if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN"
     touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
   fi
   ```
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.

The four resulting cases:
- **(a) Skip doc-fetcher only** — RESEARCH.md has findings for touched files but has open questions → run Explore, skip doc-fetcher.
- **(b) Skip Explore only** — RESEARCH.md has no findings for touched files but has no open questions → run doc-fetcher, skip Explore.
- **(c) Skip both** — RESEARCH.md has findings for touched files AND no open questions → skip both, proceed to Phase 2.
- **(d) Run both** — RESEARCH.md is stale, absent, or meets neither skip condition → run both doc-fetcher and Explore.

**Rule: doc-fetcher FIRST, Explore for gaps.** The two-tier docs at `docs/llm/` are a cheap pre-built oracle. The orchestrator must consult them via the `doc-fetcher` (Haiku) subagent before dispatching the (expensive) Explore subagent.

### 1a. Dispatch doc-fetcher (if INDEX.json exists)

If Setup step 7 noted `docs/llm/INDEX.json` exists, spawn ONE `doc-fetcher` call with the task's keywords:

```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the task>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed to Explore with no grounding. If it returns `STATUS: partial`, Explore must fill the gap it named.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

### 1b. Explore for gaps (Haiku by default)

Now identify what doc-fetcher did NOT cover (or what's absent entirely if no docs exist): touched files, reusable patterns, constraints, adjacent code that could regress.

**Explore is dispatched with `model: "haiku"` by default.** Pass it the doc-fetcher synthesis as scaffolding so it doesn't re-derive what we already have:

```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Find <thing> related to <slug>",
  prompt="<TARGETED question that fills a specific gap from doc-fetcher>\n\nAlready known (from doc-fetcher): <paste tight summary>\n\nFocus only on what is NOT covered above."
)
```

**When to upgrade Explore to Sonnet:** if the question requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Sonnet. Interpreting > Sonnet. Default > Haiku.

**Cap `Explore` subagent dispatches at 3 total per `/z-plan` run.** Each Explore (even Haiku) is a repo-mapping pass that consumes meaningful cache-read context. In the data-overhaul run, 5 Opus Explores ate 13.9 M tokens — ~93% of the entire planning budget. Haiku materially cuts that, but the cap stays: if 3 is not enough, prefer direct Read/Grep/Glob from the orchestrator over a 4th Explore. Override via `Z_HARNESS_MAX_EXPLORE=N` only with explicit user request.

Output a one-paragraph context summary. Checkpoint: `phase1-context.md`.

## Phase 2 — Decisions document

Enumerate **every** decision needed to implement this task — obvious and non-obvious. Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/decisions.md`. For each decision:

- **Decision:** what's being decided
- **Options:** ≥1 candidate, with one-line tradeoffs
- **Tentative call:** your current pick
- **Consult? (yes/no):** apply the rules below
- **Trigger:** which rule made it consult-worthy (if yes)

### Consultation rules

A decision is **non-obvious (consult)** if *any* applies:

- Introduces a new external dependency
- Defines or changes a public API / module boundary / wire format
- Picks an algorithm or data structure where Big-O or memory differ between candidates
- Touches concurrency, shared state, or ordering guarantees
- Touches persistence: schema, migration, indexes, retention
- Names something on a public surface (hard to rename later)
- Affects >1 module or crosses a layer boundary
- **Reversibility:** if wrong, >1 hour to undo
- **Articulation:** you can name ≥2 candidate options with materially different tradeoffs

A decision is **obvious (skip consult)** if:
- Following an existing convention in the same file/module
- Local variable naming, internal helper structure
- Mechanical refactor with no behavior change
- Bug fix with root cause already identified

## Phase 2.5 — User gate

Show `decisions.md` to the user. They are the gate:
- Can flip any decision's consult flag
- Can override your tentative call
- Can kill scope

**Hard cap: 5 consult-flagged decisions per bundle.** If more, ask the user to pick the top 5 or split the plan into multiple `/z-plan` runs.

Block here until the user has approved the decisions doc. Send a `PushNotification` if policy is `approval_only` or `all`.

## Phase 3 — Bundled cross-LLM consultation

Spawn **both** consultants in parallel in a single message:

- `Agent(subagent_type="consultant-primary", ...)`
- `Agent(subagent_type="consultant-secondary", ...)`

Each gets the **entire approved decisions doc** with the consult-flagged decisions highlighted. They can see all decisions and flag interactions between them. Two calls total, regardless of feature size.

When both return:
1. For each recommendation, articulate **one concrete reason it might be wrong** before accepting it. This is mechanical, not optional.
2. Synthesize. Make the final call yourself, citing which inputs you weighed.
3. Flag any shortcut over the robust long-lasting solution — requires explicit user approval in Phase 5.

Save transcripts (the consultants do this themselves). Checkpoint: `phase3-decisions-final.md`.

## Phase 4 — Final clarifications

If anything is still unclear about scope, constraints, or success criteria — ask the user. No silent assumptions.

## Phase 5 — Present + approve

If notification policy ≠ `off`, send a `PushNotification`: "Decisions ready for review."

exec
/bin/zsh -lc "sed -n '1,240p' commands/z-research.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,220p' commands/z-brainstorm.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
description: Cheap parallel pre-plan ideation — dispatch 3 vendor-diverse ideators (Claude + Codex + Gemini), perform a mandatory anti-bias check, and produce BRAINSTORM.md to seed /z-plan.
argument-hint: <topic to brainstorm> [--slug=<kebab>]
---

You are running the **z-harness `/z-brainstorm`** pipeline.

Topic (from `$ARGUMENTS`):

$ARGUMENTS

**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I brainstorm?". Wait for their reply. Treat the reply as the topic and continue.

`/z-brainstorm` is **cheap, opt-in pre-planning**. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` later. Cost target: ≤200K tokens end-to-end. If you exceed that, log a warning and continue.

## Setup

1. **Derive slug.** If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim. Otherwise auto-derive from the topic: short kebab-case, 2-4 words (e.g. "rethink batting order model" → `rethink-batting-order`). If the auto-derived slug is non-obvious, confirm via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
   - **overwrite** — archive existing `BRAINSTORM.md` to `$Z_HARNESS_PLAN_DIR/archive/$RUN/BRAINSTORM.md.previous-<N>` (where `<N>` is the next free integer in that archive dir) and start fresh
   - **abort** — exit cleanly with no changes
6. **Version stamp + log run start:**
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["topic"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" brainstorm_run_start "$START_PAYLOAD"
   ```
7. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
8. **Cost guardrail.** Target ≤200K tokens. If the running total exceeds 200K (rough estimate: sum prompt+response chars across consult events ÷ 4), log a warning event and continue — do not halt.

**All paths live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`
- `$Z_HARNESS_PLAN_DIR/archive/<RUN>/...`

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Phase 1 scaffolding is assembled and before Phase 2 ideator dispatch. `/z-brainstorm` may route only before ideators are spawned; once ideation starts, finish the brainstorm flow instead of switching commands mid-run.

Use only already-known signals from the topic, doc-fetcher synthesis, optional Explore, and any ingested `RESEARCH.md`: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route unknown terrain, missing citations, or insufficient source facts to `/z-research`.
- Route a framing that is already clear and ready for task planning to `/z-plan`.
- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.
- Stay in `/z-brainstorm` when the terrain is known enough but multiple plausible framings remain.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 4), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so we can separate machine time from human-wait time:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Scaffolding

Build a shared scaffolding payload that **all three ideators receive identically** (no read-by-reference asymmetry). Components:

### 1a. Doc-fetcher (if INDEX.json exists)

If `docs/llm/INDEX.json` exists in the repo root, dispatch ONE `doc-fetcher` (Haiku) call. **Never read INDEX.json or per-concept `<slug>.json` from main thread** — that's what doc-fetcher is for.

```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the topic>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis (matched concepts, key files with line ranges, invariants). If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed with empty doc synthesis. If it emits a `DRIFT WARNING`, log a `doc_drift` event per affected concept.

### 1b. Optional Explore

If env `Z_HARNESS_BRAINSTORM_EXPLORE=1`, dispatch ONE Explore subagent (Haiku by default) to fill scaffolding gaps:

```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Brainstorm scaffolding for <slug>",
  prompt="<TARGETED question about the topic's adjacent code / constraints>\n\nAlready known (from doc-fetcher): <paste synthesis>\n\nFocus only on what is NOT covered above."
)
```

If `Z_HARNESS_BRAINSTORM_EXPLORE` is unset or `0`, skip this step entirely — brainstorming is supposed to be cheap.

### 1c. RESEARCH.md ingestion

If `$Z_HARNESS_PLAN_DIR/RESEARCH.md` exists, read it.

- **≤20 KB:** inline the full content into the scaffolding payload.
- **>20 KB:** produce an **extractive summary** that preserves citations and constraints (do not paraphrase; copy the cited bullets and constraint statements verbatim, drop the prose). Write the summary to `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-summary-for-brainstorm.md`. Inline the summary instead of the full file.

Record `depends_on: [RESEARCH.md]` in the eventual BRAINSTORM.md frontmatter if RESEARCH.md was ingested.

### 1d. Assemble and hash

Compute the `input_hash` per SPEC:

```
input_hash = sha256(canonicalize(
    topic + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_synthesis_or_empty + "\n---\n" +
    research_md_or_summary_or_empty
)).hexdigest()[:16]
```

`canonicalize`: strip leading/trailing whitespace; collapse all internal runs of whitespace to a single space.

Checkpoint: write the assembled scaffolding to `$Z_HARNESS_PLAN_DIR/archive/$RUN/phase1-scaffolding.md`.

---

## Phase 2 — Parallel ideator dispatch

Spawn **all three ideators in parallel in a single message**, each receiving the **identical** scaffolding payload from Phase 1 (topic + doc-fetcher synthesis + Explore findings if any + RESEARCH content/summary if any). No read-by-reference asymmetry.

Define a shared instruction block `IDEATOR_SCHEMA` (used verbatim in all three prompts):

```
Return exactly five sections: (1) Framing, (2) Core hypothesis, (3) Risks, (4) Plan implications, (5) What would change my mind. Mark any section you cannot produce as `<missing>`. Do not add other sections or a recommendation. Be bold and distinct — diversity across the three ideators is the point.
```

Then dispatch:

```
Agent(
  subagent_type="general-purpose",
  model="sonnet",
  description="Claude ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<paste assembled payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="consultant-secondary",
  description="Codex ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
Agent(
  subagent_type="consultant-primary",
  description="Gemini ideator for <slug>",
  prompt="MODE: brainstorm\n\nTopic: <topic>\n\nScaffolding:\n<same payload>\n\n<IDEATOR_SCHEMA>"
)
```

All three ideators see byte-identical scaffolding AND byte-identical schema instructions. The consultants return RAW (per the `MODE: brainstorm` contract in their agent files) — no standard wrapper. The Claude ideator (general-purpose Sonnet) returns the same five-section block.

### Ideator failure policy

Treat an ideator as failed if it returns an error, times out, or returns no parseable five-section block.

- **1/3 fail** → proceed with the surviving two. Record the failed member as `"<id>:failed"` in the `ideators` frontmatter list using the canonical id (`claude:failed` | `codex:failed` | `gemini:failed`). The Phase 3 anti-bias check becomes a two-way comparison (still mandatory). Log `ideator_failed` with `{vendor, reason}`.
- **2/3 fail** → halt. Use `AskUserQuestion` with options:
  - **retry** (default) — re-dispatch the failed ideators once
  - **proceed-with-1** — record the two failed members and run Phase 3 with a single framing (anti-bias check becomes "single framing — no comparison possible; flag inherent bias risk")
  - **abandon** — write a minimal abandoned BRAINSTORM.md (frontmatter: `artifact`, `slug`, `generated_at`, `command`, `input_hash`, `ideators` with `:failed` suffix on the failed members, `ideator_models`, `status: abandoned`, `chosen_framing: abandoned`; body: a single `## Abandoned` section with one sentence of context) so `/z-plan` can detect the prior attempt, then exit.
- **3/3 fail** → hard halt. Log `total_ideator_failure`, push-notify the user, exit. Do not write BRAINSTORM.md.

Log every individual failure as `ideator_failed` regardless of the bucket above.

---

## Phase 3 — Synthesis + mandatory anti-bias check

1. **Parse** the three (or two, or one) returns. For each ideator, extract the five sections. If a section is missing or malformed, record it as `<missing>` rather than omitting it.

2. **Anti-bias check (MANDATORY).** Section-by-section, compare what each ideator said and identify which framing wins that dimension. **If you (the orchestrator, running on Claude) find yourself picking the Claude ideator over a peer for a given section, you must write an explicit justification for that pick.** "Claude wins" without justification is not acceptable — every Claude-favoring call needs a concrete reason (e.g. "Claude wins on Risks because it surfaced the data-leakage edge case that Codex and Gemini missed"). For two-way comparisons (one ideator failed), the same rule applies.

3. **Orchestrator recommendation.** Pick one framing as your tentative recommendation with a one-line rationale. The user is free to override.

4. **Write `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md`** with YAML frontmatter:

   ```yaml
   ---
   artifact: brainstorm
   slug: <slug>
   generated_at: <UTC ISO 8601>
   command: /z-brainstorm <args>
   input_hash: <16 hex from Phase 1d>
   depends_on: [<RESEARCH.md if ingested>]
   ideators:
     - claude
     - codex
     - gemini
     # failed members recorded as "<id>:failed" (e.g. claude:failed)
   ideator_models:
     claude: sonnet
     codex: default
     gemini: default
   status: complete
   chosen_framing: pending

 succeeded in 0ms:
---
description: Structured pre-plan terrain mapping — up to 3 parallel Explore subagents, bundled cross-LLM critique, produce RESEARCH.md with file:line citations to ground /z-plan. Explicitly does not recommend an approach.
argument-hint: <question or technical area to research>
---

You are running the **z-harness `/z-research`** pipeline.

Question (from `$ARGUMENTS`):

$ARGUMENTS

**If the question above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask "What question should I research?". Wait for their reply. Treat their reply as the question and continue. Do not proceed past this point without a concrete question.

Strict, multi-phase. Do not skip phases. `/z-research` produces a research note only — it maps terrain, it does not pick an approach. Implementation and approach-selection happen later via `/z-brainstorm` or `/z-plan`.

**Known v1 limitation:** `Agent()` does not expose a per-call wall-clock timeout. Subagents that hang block the run. User escape: ctrl-c.

## Setup

1. **Parse `--slug=<value>` flag** from `$ARGUMENTS` first. If present, strip the entire `--slug=<value>` token from the arguments — the remainder is the research question, and the explicit slug overrides auto-derivation. The stripped `--slug=` token MUST NOT appear in any prompt to subagents and MUST NOT be included in the canonical text fed into `input_hash` (use only the cleaned research question + any non-`--slug` flags). Store the original normalized invocation (question + supported flags) separately for the final `command:` frontmatter.

   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.

   If `--slug=` was explicitly provided, skip auto-derivation but still defer collision handling to Phase 0.5.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["question"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_run_start "$START_PAYLOAD"
   ```
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists, note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku). The orchestrator never reads `docs/llm/*.json` directly from main thread.

**Setup does NOT mutate `$Z_HARNESS_PLAN_DIR/RESEARCH.md` or any sibling artifact.** All collision/archive decisions happen in Phase 0.5, AFTER the user clears the cost gate.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/RESEARCH.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check before the Phase 0 cost gate when the request is clearly not research. After Phase 6 finalization, route language may appear only as a next-step handoff outside `RESEARCH.md`; never put approach recommendations in the research note.

Use only already-known signals from the question, slug/artifact collision check, and docs availability: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Stay in `/z-research` when terrain is uncertain, citations/source facts are missing, or the user asks to map code constraints before choosing an approach.
- Route clearly framed planning work with enough terrain to `/z-plan`.
- Route multiple plausible framings with enough terrain to `/z-brainstorm`.
- Route a small concrete fix (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing before research starts, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0, 0.5, 1 through 6), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 0 — Cost-confirmation gate

Research can be expensive. The default fan-out is up to 3 parallel `Explore` subagents (Haiku) plus a bundled cross-LLM critique pass. Target spend: **≤2M tokens / 5-10 min wall time.** If you exceed 2M tokens at any point, log a `cost_warning` event and surface it to the user.

Present the cost up front via `AskUserQuestion` with three options:

- **Proceed (~2M tokens)** — full fan-out, up to 3 parallel Explores.
- **Reduce to 1 Explore** — single Explore, lighter spend (~700k-1M tokens).
- **Abandon** — exit cleanly, write nothing.

Log the user's pick:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" cost_gate_decision \
  "$(printf '{"choice":"%s"}' "<proceed|reduce|abandon>")"
```

If `abandon`: exit. If `reduce`: set `EXPLORE_BUDGET=1`. Otherwise `EXPLORE_BUDGET=3`.

Checkpoint: `phase0-cost-gate.md`.

## Phase 0.5 — Slug + artifact collision handling

This phase runs **only if** the user picked `proceed` or `reduce` in Phase 0. The `abandon` path must never reach this phase, so the existing workspace stays untouched.

1. **Slug-dir collision (deferred from Setup step 1).** If the chosen slug (auto-derived or `--slug=`) matches an existing `$Z_HARNESS_PLAN_DIR/` dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious (and `--slug=` was not provided), confirm with the user via `AskUserQuestion`.

2. **Existing-RESEARCH.md handling (deferred from old Setup step 7).** If `$Z_HARNESS_PLAN_DIR/RESEARCH.md` exists, prompt the user via `AskUserQuestion` with three options:
   - **archive-and-start-fresh** — archive the existing note (`mv $Z_HARNESS_PLAN_DIR/RESEARCH.md $Z_HARNESS_PLAN_DIR/archive/$RUN/RESEARCH.previous.md`) and proceed with a clean draft.
   - **continue (re-use existing)** — leave the existing RESEARCH.md in place and treat this run as a refinement; the existing note's findings become inputs to Phase 3.
   - **abort** — exit cleanly. **Do NOT touch the existing RESEARCH.md or any sibling file.** Log a `phase0_5_abort` event and return.

   Log the user's pick:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_collision_decision \
     "$(printf '{"choice":"%s"}' "<archive-and-start-fresh|continue|abort>")"
   ```

Checkpoint: `phase0_5-collision.md`.

## Phase 1 — Scaffolding

**Rule: doc-fetcher FIRST.** If Setup step 8 noted `docs/llm/INDEX.json` exists, spawn **ONE** `doc-fetcher` call with the question's keywords:

```
Agent(
  subagent_type="doc-fetcher",
  description="Doc context for <slug>",
  prompt="query: <one-sentence summary of the question>\nrepo_root: <abs path>\ndepth: standard"
)
```

It returns a tight synthesis: matched concepts, key files with line ranges, invariants. If it returns `STATUS: no_docs` or `STATUS: no_match`, proceed without doc grounding. If `STATUS: partial`, note the gap for Phase 2.

If a `DRIFT WARNING` block appears in the return, log a `doc_drift` event per affected slug:
```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" doc_drift \
  '{"concept":"<slug>","claim":"<what doc said>","reality":"<what code says>","file":"<path>"}'
```

**No Explore here.** Phase 1 is doc-fetcher only. Explore happens in Phase 2.

Checkpoint: `phase1-scaffolding.md`.

## Phase 2 — Parallel Explores

Dispatch up to `EXPLORE_BUDGET` parallel `Explore` subagents (Haiku) on **distinct facets** of the question. Each Explore must answer a targeted sub-question; do not dispatch overlapping queries.

**Hard cap: 3.** No env override in v1. If `EXPLORE_BUDGET=1` from Phase 0, dispatch a single Explore covering the most important facet.

Send all calls in **one message** so they run in parallel:

```
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Facet A: <short label>",
  prompt="<TARGETED sub-question>\n\nAlready known (from doc-fetcher): <paste tight summary or 'none'>\n\nReturn findings with file:line citations. Do NOT recommend an approach — this is terrain mapping."
)
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Facet B: <short label>",
  prompt="<TARGETED sub-question>\n\n..."
)
Agent(
  subagent_type="Explore",
  model: "haiku",
  description="Facet C: <short label>",
  prompt="<TARGETED sub-question>\n\n..."
)
```

**When to upgrade Explore to Sonnet:** if the facet requires *interpretation* (e.g. "explain the control flow of X" rather than "where is X defined"), upgrade by setting `model: "sonnet"`. Locating > Haiku. Interpreting > Sonnet.

**Track three counts separately:**

- `EXPLORE_BUDGET` — the planned cap from Phase 0 (1 or 3).
- `EXPLORES_DISPATCHED` — the number of `Explore` `Agent()` calls you actually sent in the parallel message (≤ `EXPLORE_BUDGET`).
- `EXPLORES_SUCCEEDED` — the number of those calls that returned a usable result (no error, non-empty findings). Failed, malformed, or empty returns do NOT count.

For every Explore that fails or returns malformed output, log it and surface the failure as an **Open question** in Phase 3:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" explore_failure \
  "$(printf '{"facet":"%s","reason":"%s"}' "<facet-label>" "<short reason>")"
```

The final frontmatter uses **`EXPLORES_SUCCEEDED`** for `explore_calls:`. If `EXPLORES_DISPATCHED - EXPLORES_SUCCEEDED > 0`, emit an additional `explore_failures: <N>` frontmatter field. Do not fabricate `explore_calls` from `EXPLORE_BUDGET`.

Checkpoint: `phase2-explores.md` (synthesis of all Explore returns).

## Phase 3 — Draft research note

Write `$Z_HARNESS_PLAN_DIR/archive/$RUN/research-draft.md` with **these mandatory sections, in this exact order**:

```markdown
## Findings
- <claim> (path/to/file.rs:42)
- <claim> (path/to/other.py:117-130)

## Constraints discovered
- <constraint with citation>

## Open questions
- <question the Explores could not resolve>

## No-recommendation
This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.
```

**Citation requirement.** Every finding MUST cite a `file:line` (or `file:line-line` range) using the broadened regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`, plus extensionless allowlist `Makefile`, `Dockerfile`. Markdown link form `[label](path:line)` is allowed.

**Demotion rule.** Findings without a `file:line` citation are demoted to **Open questions** — do not silently drop them, and do not add a fake citation.

**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" research_temptation \
  '{"location":"<section>","removed_text":"<short excerpt>"}'
```

Checkpoint: `research-draft.md` (this file).

## Phase 4 — Bundled cross-LLM critique

Spawn **both** consultants in parallel in a single message with `MODE: research-review`. They return RAW critique (Gaps / Errors / Missing constraints) — no standard wrapper. They are explicitly forbidden from recommending an approach.

```
Agent(

exec
/bin/zsh -lc "sed -n '1,260p' commands/z-audit-plan.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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

exec
/bin/zsh -lc "sed -n '1,220p' agents/planning-router.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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

codex
I’ve got the main route blocks loaded. The broad shape matches the spec, but I’m checking two risky areas now: whether the route artifact contract is precise enough in every runnable prompt, and whether exported/generated changes went outside the plan’s stated surfaces in a way that changes behavior.
exec
/bin/zsh -lc 'rg -n "Run `ls z-harness/`|ls z-harness/|canonical plans directory|legacy directory" commands skills exports/codex/prompts/z-plan.md exports/codex/prompts/z-plan-split.md exports/codex/prompts/z-research.md exports/codex/prompts/z-brainstorm.md' in /Users/zeke/dev/z-harness
 exited 2 in 0ms:
rg: the literal "\n" is not allowed in a regex

Consider enabling multiline mode with the --multiline flag (or -U for short).
When multiline mode is enabled, new line characters can be matched.

exec
/bin/zsh -lc 'rg -n "plan_route_decision|route-decision|planning-router|z-audit-plan|primary routes|contextual" docs/llm/INDEX.json docs/llm/agents.json docs/llm/commands.json docs/llm/skills.json' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
docs/llm/skills.json:7:    "skills/z-audit-plan/SKILL.md",
docs/llm/skills.json:28:    {"file": "skills/z-audit-plan/SKILL.md", "line": 1, "symbol": "z-audit-plan", "kind": "module", "summary": "Read-only pre-implementation plan audit; verifies SPEC/PLAN/TASKS, writes PLAN_AUDIT_REPORT.md, and routes contextually to /z-plan, /z-amend, or /z-maintain-docs through route-decision.md."},
docs/llm/skills.json:55:    "Planning-family skills share the route policy: route bails write route-decision.md, emit plan_route_decision, preserve existing telemetry, present an AskUser handoff, and stop instead of auto-running the target command."
docs/llm/skills.json:64:    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, and /z-research; contextual exits are /z-audit-plan, /z-fix, /z-debug, /z-amend, and /z-maintain-docs.",
docs/llm/skills.json:65:    "Contextual exits require their preconditions: /z-audit-plan needs existing SPEC/PLAN/TASKS, /z-amend needs an existing plan to modify, /z-fix needs a diagnosis, /z-debug needs an unknown-cause symptom, and /z-maintain-docs needs relevant docs drift."
docs/llm/commands.json:8:    "commands/z-audit-plan.md",
docs/llm/commands.json:61:      "file": "commands/z-audit-plan.md",
docs/llm/commands.json:63:      "symbol": "z-audit-plan",
docs/llm/commands.json:65:      "summary": "Read-only audit for existing SPEC/PLAN/TASKS artifacts; writes PLAN_AUDIT_REPORT.md and uses contextual route exits to /z-plan, /z-amend, or /z-maintain-docs."
docs/llm/commands.json:240:    "Planning-family route bails write route-decision.md, emit plan_route_decision with route_class/reason_codes/signals/confidence/classifier_used/artifact_path/route_chain/user_choice, present an AskUser handoff gate, and never auto-execute another command."
docs/llm/commands.json:245:    "Route classes are distinct: primary targets are /z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, and /z-research; contextual exits are /z-audit-plan, /z-fix, /z-debug, /z-amend, and /z-maintain-docs.",
docs/llm/commands.json:246:    "/z-audit-plan is contextual only and requires existing plan artifacts; when no plan exists it routes to /z-plan instead of auditing."
docs/llm/INDEX.json:19:        "agents/planning-router.md",
docs/llm/INDEX.json:33:      "summary": "Specialized subagents, including auditors/reviewers, implementers, and the advisory planning-router for ambiguous plan-family route decisions."
docs/llm/INDEX.json:40:        "commands/z-audit-plan.md",
docs/llm/INDEX.json:70:      "summary": "Slash command surfaces, including planning-family route checks, contextual exits such as /z-audit-plan, plan_route_decision telemetry, review-family finding promotion, and /z-implement-all --tasks consumption."
docs/llm/INDEX.json:111:        "skills/z-audit-plan/SKILL.md",
docs/llm/INDEX.json:137:      "summary": "Operational checklists, including planning-family route policy, z-audit-plan plan audits, review finding promotion, z-amend safety gates, and explicit --tasks implementation queues."
docs/llm/agents.json:16:    "agents/planning-router.md",
docs/llm/agents.json:33:    {"file": "agents/planning-router.md", "line": 1, "symbol": "planning-router", "kind": "module", "summary": "Haiku; read-only advisory router for ambiguous plan-family route decisions; requires exact parseable return shape and explicit split preconditions."},
docs/llm/agents.json:46:    "planning-router is advisory only: callers own route artifacts, plan_route_decision telemetry, AskUser handoffs, and final routing decisions."
docs/llm/agents.json:54:    "planning-router distinguishes primary route targets (/z-do, /z-plan-light, /z-plan, /z-plan-split, /z-brainstorm, /z-research) from contextual exits (/z-audit-plan, /z-fix, /z-debug, /z-amend, /z-maintain-docs), and returns ask_user for loop-risk or conflicting-signal cases."

exec
/bin/zsh -lc 'rg -n "PLAN_ROUTE_CHECK_START|PLAN_ROUTE_CHECK_END" commands skills | sort' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-audit-plan.md:10:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-audit-plan.md:28:<!-- PLAN_ROUTE_CHECK_END -->
commands/z-brainstorm.md:42:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-brainstorm.md:60:<!-- PLAN_ROUTE_CHECK_END -->
commands/z-do.md:34:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-do.md:61:<!-- PLAN_ROUTE_CHECK_END -->
commands/z-plan-light.md:38:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan-light.md:65:<!-- PLAN_ROUTE_CHECK_END -->
commands/z-plan-split.md:144:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan-split.md:161:<!-- PLAN_ROUTE_CHECK_END -->
commands/z-plan.md:62:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-plan.md:80:<!-- PLAN_ROUTE_CHECK_END -->
commands/z-research.md:47:<!-- PLAN_ROUTE_CHECK_START -->
commands/z-research.md:65:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-audit-plan/SKILL.md:10:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-audit-plan/SKILL.md:28:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-brainstorm/SKILL.md:43:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-brainstorm/SKILL.md:61:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-do/SKILL.md:35:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-do/SKILL.md:62:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-plan-light/SKILL.md:39:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan-light/SKILL.md:66:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-plan-split/SKILL.md:145:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan-split/SKILL.md:162:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-plan/SKILL.md:55:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-plan/SKILL.md:73:<!-- PLAN_ROUTE_CHECK_END -->
skills/z-research/SKILL.md:48:<!-- PLAN_ROUTE_CHECK_START -->
skills/z-research/SKILL.md:66:<!-- PLAN_ROUTE_CHECK_END -->

exec
/bin/zsh -lc 'rg -n "# Route Decision|## Recommendation|## Reason|## Signals|## Route Chain|## Resume Context|route-decision.md must include|recommended command, reason" commands skills exports/codex/prompts exports/cursor/.cursor/rules exports/agy/prompts exports/agy/.agent/workflows exports/agy/.agent/skills exports/agy/.agent/rules' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
skills/z-do/SKILL.md:59:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
commands/z-do.md:58:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/.agent/skills/z-do/SKILL.md:58:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
commands/z-plan-light.md:62:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
skills/z-plan-light/SKILL.md:63:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/.agent/skills/z-plan-light/SKILL.md:62:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/.agent/workflows/z-do.md:57:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/.agent/workflows/z-plan-light.md:61:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/cursor/.cursor/rules/z-plan-light.mdc:62:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/codex/prompts/z-do.md:55:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/prompts/skill-z-do.md:58:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/codex/prompts/z-plan-light.md:59:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/prompts/z-plan-light.md:62:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/prompts/skill-z-plan-light.md:62:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/agy/prompts/z-do.md:58:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.
exports/cursor/.cursor/rules/z-do.mdc:58:`route-decision.md` must include the recommended command, reason, deterministic signals, route chain, and resume context. Emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`.

exec
/bin/zsh -lc "sed -n '1,120p' skills/z-plan/SKILL.md" in /Users/zeke/dev/z-harness
exec
/bin/zsh -lc "sed -n '1,120p' skills/z-plan-split/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
---
name: z-plan
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
argument-hint: <feature or task description>
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If the phase blocks on `AskUserQuestion`, separately log `user_wait_start` / `user_wait_end` events bracketing that wait so we can compute machine-time vs human-wait-time after the fact:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

This makes post-run analysis trivial: total run time = sum(`phase_end.wall_ms`); machine time = that minus sum(`user_wait_end.wall_ms`); per-LLM costs already covered by the existing `consult` events.

---

## Phase 0 — Premise check

**Do not take the prompt's premises for granted.** If `BRAINSTORM.md` or `RESEARCH.md` were detected in Setup step 9, **inject their content here** as input to the premise check (extracting core hypothesis + findings). Do not re-derive context already covered by these artifacts.

Before any planning, ask:

- Does the stated goal actually solve the underlying problem? (e.g. if the user asks for a faster cache, is caching even the right answer?)
- Will the proposed approach actually work? (e.g. for a quant strategy: is the edge real, will it survive transaction costs, is the backtest leaking? for an architecture: will it scale to the stated load?)
- Is there a materially better path the user hasn't considered?

If any of these surface a real concern, **stop and raise it with the user before moving on.** Do not plan around a flawed premise. Use `AskUserQuestion` if there's a structured choice.

If nothing concerning surfaces, write a one-paragraph "premise accepted, here's what I take the goal to be" summary so the user can correct your read.

Checkpoint: `phase0-premise.md`.

## Phase 1 — Exploration

**RESEARCH.md shortcut:** If RESEARCH.md was detected (Setup step 9) and is non-stale, it may make doc-fetcher and/or Explore optional. The two skip conditions are **independent** — evaluate each separately:

- **Skip doc-fetcher** iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set.
- **Skip Explore** iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.


 succeeded in 0ms:
---
name: z-plan-split
description: Pre-emptive scope splitter — fan a big topic out into N narrow cluster-planner subagents in parallel, then reconcile file-path overlaps into SHARED-CONCERNS.md + MANIFEST.md.
argument-hint: <topic> [--slug=<root-slug>] [--clusters="a,b,c"]
---

You are running the **z-harness `/z-plan-split`** pipeline.

Topic + flags (from `$ARGUMENTS`):

$ARGUMENTS

**If the topic above is empty or whitespace**, do this first: use `AskUserQuestion` to ask "What topic should I split?". Wait for their reply. Treat the reply as the topic and continue.

`/z-plan-split` is a **pre-emptive scope splitter** for topics that would otherwise produce a sprawling ≥40-task `/z-plan` run. Instead of one mega-plan, it dispatches N parallel `cluster-planner` subagents (each producing a focused 5-15-task plan), then writes `SHARED-CONCERNS.md` (file-overlap observation, ack-gated) and `MANIFEST.md` (cluster listing + run order). It does NOT produce production code. One-level recursion only — nested MANIFESTs are explicitly out of scope.

## Setup

1. **Derive root slug.**
   - If `$ARGUMENTS` contains `--slug=<value>`, use that verbatim.
   - Else if `$ARGUMENTS` contains `--clusters="a,b,c"`, the slug is auto-derived from the topic (kebab-case, 2-4 words). The `--clusters` flag overrides Phase 1's automatic proposal.
   - Otherwise auto-derive from the topic (kebab-case, 2-4 words). If non-obvious, confirm via `AskUserQuestion`.
2. **Validate the slug (mandatory — security gate).** The slug is interpolated into filesystem paths and must be a single safe segment. Reject (refuse with a clear error and exit cleanly) if the slug:
   - is empty or whitespace-only;
   - contains any character outside `[a-z0-9-]` (kebab-case only — no `/`, `\`, spaces, `:`, `..`, `~`, `$`, quotes, etc.);
   - contains `..` anywhere (even as a substring);
   - starts with `-` or `.`, or ends with `-`;
   - contains `//` or path separators of any kind.

   Concretely: the slug must match the anchored regex `^[a-z0-9]+(-[a-z0-9]+)*$`. Reject values like `../x`, `foo/bar`, `.hidden`, `a b`, empty string, `a..b`. Error message: `"Invalid slug: must be a single kebab-case segment matching ^[a-z0-9]+(-[a-z0-9]+)*$ (no slashes, dots, or path traversal). Got: <value>"`. Do not fall through to a sanitized version; force the user to re-invoke with a valid slug.
3. **Export** `Z_HARNESS_SLUG=<root-slug>` for all subsequent shell calls and subagents — this namespaces every output path under `z-harness/<root-slug>/`.
4. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`.
5. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`.
6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
   - **overwrite** — move the **entire prior tree** (every file and subdirectory under `$Z_HARNESS_PLAN_DIR/` *except* the just-created `archive/<RUN>/` directory itself) into `$Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree/`. This includes the old `MANIFEST.md`, `SHARED-CONCERNS.md`, all prior `<cluster-slug>/` subdirectories, and any other stale artifacts — so no stale cluster trees survive into the new run. Implementation sketch: `mkdir -p $Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree && find $Z_HARNESS_PLAN_DIR/ -mindepth 1 -maxdepth 1 ! -name archive -exec mv {} $Z_HARNESS_PLAN_DIR/archive/<RUN>/prior-tree/ \;` (move any existing `archive/previous-*` subdirs separately if needed). Then start fresh.
   - **abort** — exit cleanly with no changes. Per the Early-exit telemetry contract, emit `plan_split_run_end` with `status: "aborted_existing_tree"` before returning (no `phase_end` — no phase is active yet at Setup time).
   No "append" option (D10 — append flow was under-specified; drop it).
7. **Version stamp + log run start.** Merge the version blob with the topic and emit `plan_split_run_start` with `topic_chars`:
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1])
   v["topic"] = sys.argv[2]
   v["topic_chars"] = len(sys.argv[2])
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<topic-text>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_start "$START_PAYLOAD"
   ```
   Output lands under `z-harness/<root-slug>/archive/$RUN/events.jsonl`.
8. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
9. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, do NOT read it from main thread. Note its existence; Phase 1 may dispatch `doc-fetcher` (Haiku) for one-shot topic grounding. Skip the docs-freshness gate — this command does not itself touch INDEX.json; cluster-planners handle their own doc reads.
10. **Cluster proposal seed.** If `--clusters="a,b,c"` was passed, parse the comma-separated list into proposed cluster names (kebab-case, 2-6 entries — each name must independently pass the same `^[a-z0-9]+(-[a-z0-9]+)*$` validator from step 2; reject the entire flag on any invalid name). **`--clusters=` supplies names only, not scopes** — Phase 1 must still derive a one-line scope per cluster (either auto-derived from the topic text by Phase 1's main-thread reasoning, or interactively asked via `AskUserQuestion` if scopes can't be inferred unambiguously). Skip Phase 1's automatic name proposal (jump straight to Phase 1's scope-derivation + user confirmation, 1d). Otherwise proceed to Phase 1 normally.

**All paths in subsequent phases live under `z-harness/<root-slug>/`:**
- `z-harness/<root-slug>/MANIFEST.md`
- `z-harness/<root-slug>/SHARED-CONCERNS.md`
- `z-harness/<root-slug>/<cluster-slug>/{SPEC.md,PLAN.md,TASKS.md}` (one per cluster — directory uses the kebab-case `cluster_slug`)
- `z-harness/<root-slug>/archive/<RUN>/...`

## Cluster identity (terminology — used consistently below)

Every cluster has **two distinct stable fields**:

- **`cluster_id`** — a short, stable, opaque handle of the form `C1`, `C2`, …, `CN`, assigned in confirmation order. Used in **telemetry payloads** (every event's `cluster_id` field), MANIFEST table's first column, and cross-references in SHARED-CONCERNS.md (`Touched by: <cluster_id> (<task_id>)`). Never used as a path segment.
- **`cluster_slug`** — the kebab-case name the user (or the auto-proposer) chose, e.g. `auth-refactor`. Must independently match `^[a-z0-9]+(-[a-z0-9]+)*$` (same validator as the root slug, step 2). Used as the **on-disk directory name** under `z-harness/<root-slug>/<cluster_slug>/`. Never used in telemetry payloads.

Where this doc previously wrote `<cluster-id>` in a filesystem path, read it as `<cluster_slug>`. Where this doc writes a `cluster_id` field in a JSON payload, it is the `C1`/`C2` form. MANIFEST.md rows include both: `ID` column = `cluster_id`, `Path` column = `<root-slug>/<cluster_slug>/`.

## Early-exit telemetry contract (mandatory for every exit path)

**Every** exit from this command — successful, refused, aborted, paused, or failed — MUST emit the matching `phase_end` for the currently-active phase (if any) **and** a single `plan_split_run_end` event before returning. The `status` field on `plan_split_run_end` distinguishes the exit reason. No exit path may silently skip these events; the post-run analyzer relies on `plan_split_run_end` always being present.

Allowed `status` values on `plan_split_run_end`:

- `ready` — Phase 5 finalized with all clusters ready.
- `partial` — Phase 5 finalized with ≥1 cluster ready and ≥1 failed.
- `abandoned_by_user` — user picked "Abandon" in Phase 1d (or "Abandon this cluster" elided the last surviving cluster).
- `aborted_existing_tree` — user picked "abort" at the existing-slug prompt (Setup step 6). No `phase_end` to emit (no phase active yet).
- `aborted_too_few_clusters` — Phase 1 refused (<2 seams). Emit `phase_end` for Phase 1 first.
- `aborted_too_many_clusters` — Phase 1 refused (>6 seams). Emit `phase_end` for Phase 1 first.
- `aborted_invalid_slug` — Setup step 2 / 10 rejected the slug or a cluster name. No `phase_end` (no phase active yet).
- `total_cluster_failure` — Phase 3 (or Phase 4 after re-validation cascade) found all clusters failed. Emit `phase_end` for Phase 3 (or Phase 4) before returning; also emit the `total_cluster_failure` event as documented in Phase 3.

Payload shape for early exits (when full counts aren't available yet, use `null` or `0`):

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" plan_split_run_end \
  "$(printf '{"status":"%s","total_clusters":%s,"clusters_ready":%s,"clusters_failed":%s,"overlap_count":%s,"partial_tree":%s,"reason":"%s"}' \
     "$STATUS" "${N:-0}" "${K:-0}" "${F:-0}" "${O:-0}" "${PT:-false}" "$REASON_SHORT")"
```

## Phase telemetry (mandatory)

At the **start** of each phase (1 through 5), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```

If a phase blocks on `AskUserQuestion`, bracket the wait with `user_wait_start` / `user_wait_end` events so post-run analysis can separate machine time from human-wait time:

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_start '{"phase":<n>,"reason":"<short>"}'
# ... AskUserQuestion ...
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" user_wait_end '{"phase":<n>,"wall_ms":<delta>}'
```

---

## Phase 1 — Cluster proposal

Main thread only. **Do NOT spawn a subagent** — cluster proposal is small-context and benefits from sitting alongside the topic.

### 1a. Optional doc grounding (if INDEX.json exists, Setup step 9)

If `docs/llm/INDEX.json` exists, dispatch ONE `doc-fetcher` (Haiku) call for topic grounding:

exec
/bin/zsh -lc "rg -n \"route-decision\\.md.*(include|contain)|Recommendation|Resume Context|Route Chain|Signals|Reason\" commands/z-plan.md commands/z-plan-split.md commands/z-brainstorm.md commands/z-research.md commands/z-audit-plan.md skills/z-plan/SKILL.md skills/z-plan-split/SKILL.md skills/z-brainstorm/SKILL.md skills/z-research/SKILL.md skills/z-audit-plan/SKILL.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-audit-plan.md:143:2. **One-Reason-This-Might-Be-Wrong Gate:**
commands/z-audit-plan.md:172:   ## Actionable Recommendations
commands/z-research.md:226:**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:
skills/z-audit-plan/SKILL.md:143:2. **One-Reason-This-Might-Be-Wrong Gate:**
skills/z-audit-plan/SKILL.md:172:   ## Actionable Recommendations
skills/z-research/SKILL.md:227:**Recommendation invariant.** The `## No-recommendation` section is **MANDATORY and NON-DELETABLE**. The canonical text is exactly: `This research note explicitly does not recommend an approach. Use /z-brainstorm or /z-plan to pick one.` If you find yourself drafting a recommendation anywhere in the note (e.g. "we should use X", "the right approach is Y"), log a `research_temptation` event and **remove the recommendation before proceeding**:

exec
/bin/zsh -lc "rg -n 'Run "'`ls z-harness/`|ls z-harness/|canonical plans directory|legacy directory'"' commands skills exports/codex/prompts exports/cursor/.cursor/rules exports/agy/prompts exports/agy/.agent/workflows exports/agy/.agent/skills" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
commands/z-plan-split.md:33:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
exports/cursor/.cursor/rules/z-brainstorm.mdc:22:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/prompts/z-plan-split.md:33:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
skills/z-plan-split/SKILL.md:34:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/.agent/skills/z-plan-split/SKILL.md:33:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/.agent/workflows/z-plan-split.md:32:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
exports/codex/prompts/z-plan-split.md:30:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
commands/z-audit-plan.md:41:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
exports/agy/.agent/skills/z-brainstorm/SKILL.md:22:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/prompts/z-audit-plan.md:41:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
exports/cursor/.cursor/rules/z-audit-plan.mdc:41:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
exports/codex/prompts/z-audit-plan.md:38:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
exports/agy/.agent/workflows/z-audit-plan.md:40:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
skills/z-research/SKILL.md:23:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
skills/z-audit-plan/SKILL.md:41:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
commands/z-brainstorm.md:22:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/.agent/skills/z-plan-light/SKILL.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/.agent/skills/z-research/SKILL.md:22:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
exports/cursor/.cursor/rules/z-audit.mdc:27:1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
exports/agy/.agent/workflows/z-brainstorm.md:21:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
skills/z-brainstorm/SKILL.md:23:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/.agent/skills/z-audit-plan/SKILL.md:41:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
exports/codex/prompts/z-brainstorm.md:19:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
commands/z-research.md:22:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
exports/agy/.agent/skills/z-plan/SKILL.md:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
commands/z-plan-light.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/cursor/.cursor/rules/z-plan-split.mdc:33:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/.agent/workflows/z-research.md:21:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
skills/z-plan-light/SKILL.md:19:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/.agent/workflows/z-fix.md:17:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "null pointer on login" → `fix-null-pointer-login`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
commands/z-plan.md:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Check for existing slug dirs in the canonical plans directory (`z-harness/plans/`) and the legacy directory (`z-harness/`). If a matching slug dir is found:
exports/cursor/.cursor/rules/z-plan-light.mdc:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/codex/prompts/z-research.md:19:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
exports/agy/.agent/workflows/z-audit.md:26:1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
skills/z-plan/SKILL.md:19:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
exports/agy/.agent/workflows/z-plan-light.md:17:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/.agent/workflows/z-plan.md:17:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Check for existing slug dirs in the canonical plans directory (`z-harness/plans/`) and the legacy directory (`z-harness/`). If a matching slug dir is found:
commands/z-fix.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "null pointer on login" → `fix-null-pointer-login`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/prompts/skill-z-research.md:22:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
exports/cursor/.cursor/rules/z-research.mdc:22:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
exports/codex/prompts/z-plan-light.md:15:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/prompts/skill-z-audit-plan.md:41:   Enumerate subdirectories under the plans directory (`z-harness/plans/`) or legacy directory (`z-harness/`) that contain plan artifacts (`SPEC.md` / `PLAN.md` / `TASKS.md`).
exports/agy/prompts/z-brainstorm.md:22:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/prompts/skill-z-plan.md:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
exports/agy/prompts/z-fix.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "null pointer on login" → `fix-null-pointer-login`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/prompts/z-audit.md:27:1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
commands/z-audit.md:27:1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
exports/codex/prompts/z-plan.md:15:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
exports/agy/prompts/skill-z-brainstorm.md:22:5. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/BRAINSTORM.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/prompts/z-plan.md:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Check for existing slug dirs in the canonical plans directory (`z-harness/plans/`) and the legacy directory (`z-harness/`). If a matching slug dir is found:
exports/agy/prompts/skill-z-plan-split.md:33:6. **Existing slug-dir handling.** Run `ls z-harness/` to check for a matching slug dir. If `$Z_HARNESS_PLAN_DIR/MANIFEST.md` exists, prompt the user via `AskUserQuestion`:
exports/agy/prompts/z-research.md:22:   **Derive a research slug** (only if `--slug=` was not provided): from the cleaned question, short kebab-case, 2-4 words (e.g. "how does the retry logic interact with token bucket limits?" → `retry-token-bucket`). Run `ls z-harness/` to check for existing slug dirs. Slug-collision handling (precontext-only vs finished-plan dir, and the auto-derived-slug confirmation) is deferred to **Phase 0.5** below so we do not mutate the workspace before the user clears the cost gate.
exports/agy/prompts/z-plan-light.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/agy/prompts/skill-z-plan-light.md:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "off-by-one in nba parser" → `fix-nba-parser-off-by-one`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/cursor/.cursor/rules/z-fix.mdc:18:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "null pointer on login" → `fix-null-pointer-login`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/codex/prompts/z-fix.md:15:1. **Derive slug** — short kebab-case like `fix-<short-description>` (e.g. "null pointer on login" → `fix-null-pointer-login`). Confirm via `AskUserQuestion` if non-obvious or might collide with an existing slug (`ls z-harness/` first).
exports/codex/prompts/z-audit.md:24:1. **Derive slug** — short kebab-case like `audit-<component>` (e.g. target `strategies/kxbtc15m_fade_extremes` → `audit-kxbtc15m`). Confirm via `AskUserQuestion` if non-obvious. Check `ls z-harness/` first for collisions.
exports/cursor/.cursor/rules/z-plan.mdc:18:1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:

exec
/bin/zsh -lc "rg -n \"Z_HARNESS_PLAN_DIR=.*resolve_plan_path|Export.*Z_HARNESS_PLAN_DIR|CURRENT_ARCHIVE_DIR|route-decision\\.md\" commands/z-plan-split.md skills/z-plan-split/SKILL.md exports/codex/prompts/z-plan-split.md exports/cursor/.cursor/rules/z-plan-split.mdc exports/agy/prompts/z-plan-split.md exports/agy/.agent/workflows/z-plan-split.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
skills/z-plan-split/SKILL.md:159:If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
exports/codex/prompts/z-plan-split.md:155:If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
exports/agy/prompts/z-plan-split.md:158:If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
exports/agy/.agent/workflows/z-plan-split.md:157:If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
exports/cursor/.cursor/rules/z-plan-split.mdc:158:If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.
commands/z-plan-split.md:158:If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate when continuation is allowed: switch, continue, or abandon. Do not execute the next command automatically.

exec
/bin/zsh -lc 'rg -n "external-lookup|planning-router|z-audit-plan" exports/agy/agy-plugin.yaml exports/codex/AGENTS.md exports/cursor/.cursor/rules/planning-router.mdc exports/cursor/.cursor/rules/external-lookup.mdc' in /Users/zeke/dev/z-harness
 succeeded in 0ms:
exports/cursor/.cursor/rules/planning-router.mdc:34:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
exports/cursor/.cursor/rules/planning-router.mdc:60:- `/z-audit-plan`
exports/cursor/.cursor/rules/planning-router.mdc:66:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
exports/cursor/.cursor/rules/planning-router.mdc:127:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`
exports/agy/agy-plugin.yaml:18:  - id: z-audit-plan
exports/agy/agy-plugin.yaml:19:    source: commands/z-audit-plan.md
exports/agy/agy-plugin.yaml:20:    output: .agent/workflows/z-audit-plan.md
exports/agy/agy-plugin.yaml:157:  - id: external-lookup
exports/agy/agy-plugin.yaml:158:    source: agents/external-lookup.md
exports/agy/agy-plugin.yaml:159:    output: .agent/rules/z-harness-external-lookup.md
exports/agy/agy-plugin.yaml:172:  - id: planning-router
exports/agy/agy-plugin.yaml:173:    source: agents/planning-router.md
exports/agy/agy-plugin.yaml:174:    output: .agent/rules/z-harness-planning-router.md
exports/agy/agy-plugin.yaml:200:  - id: z-audit-plan
exports/agy/agy-plugin.yaml:201:    source: skills/z-audit-plan/SKILL.md
exports/agy/agy-plugin.yaml:202:    output: .agent/skills/z-audit-plan/SKILL.md
exports/codex/AGENTS.md:1143:## external-lookup
exports/codex/AGENTS.md:1742:## planning-router
exports/codex/AGENTS.md:1774:RECOMMENDED: /z-do | /z-plan-light | /z-plan | /z-plan-split | /z-brainstorm | /z-research | /z-audit-plan | /z-fix | /z-debug | /z-amend | /z-maintain-docs | ask_user
exports/codex/AGENTS.md:1800:- `/z-audit-plan`
exports/codex/AGENTS.md:1806:Contextual exits require their preconditions. In particular, `/z-audit-plan` requires existing plan artifacts, `/z-amend` requires an existing plan to change, `/z-fix` requires a concrete bug diagnosis, and `/z-debug` requires an observed bug symptom with unknown root cause.
exports/codex/AGENTS.md:1867:   - `has_existing_plan` plus a plan validation request or completed plan artifacts -> `/z-audit-plan`

exec
/bin/zsh -lc "sed -n '1,80p' exports/codex/prompts/z-plan.md && sed -n '1,80p' exports/cursor/.cursor/rules/z-plan.mdc && sed -n '1,80p' exports/agy/prompts/z-plan.md" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
# /z-plan

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
  "$(printf '{"phase":%d,"name":"%s","wall_ms":%d,"user_wait_ms":%d}' \
     <phase-num> "<phase-name>" "$WALL_MS" "$USER_WAIT_MS_THIS_PHASE")"
```
---
description: "Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md."
alwaysApply: false
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Run `ls z-harness/` to check for existing slug dirs. If the derived slug matches an existing dir:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

## Phase telemetry (mandatory)

At the **start** of each phase (0 through 9), record `T0=$(date +%s%3N)`. At the **end**, log:

```bash
WALL_MS=$(( $(date +%s%3N) - T0 ))
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" phase_end \
---
description: Run the rigorous z-harness planning pipeline — challenge premises, batch decisions, cross-consult Gemini + Codex once, and produce SPEC.md / PLAN.md / TASKS.md.
role: workflow
---

You are running the **z-harness `/z-plan`** pipeline.

Task (from `$ARGUMENTS`):

$ARGUMENTS

**If the task above is empty or whitespace**, do this first: use `AskUserQuestion` (or a direct question if a free-text answer is needed) to ask the user "What task should I plan?". Wait for their reply. Treat their reply as the task and continue. Do not proceed past this point without a concrete task description.

Strict, multi-phase. Do not skip phases. Do not write production code — `/z-plan` produces planning artifacts only; implementation happens later via `/z-implement-next`.

## Setup

1. **Derive a plan slug** from the task: short kebab-case, 2-4 words (e.g. "expand sports ML" → `expand-sports-ml`; "add rate limit middleware" → `add-rate-limit`). Check for existing slug dirs in the canonical plans directory (`z-harness/plans/`) and the legacy directory (`z-harness/`). If a matching slug dir is found:
   - **Precontext-only slug dir** (only `BRAINSTORM.md` and/or `RESEARCH.md` present, no `PLAN.md`/`SPEC.md`/`TASKS.md`): treat as continuation — no prompt, proceed with the existing slug.
   - **Finished-plan slug dir** (`PLAN.md` or `TASKS.md` exists): collision — prompt the user via `AskUserQuestion` to confirm or choose a different slug.
   If the auto-derived slug is non-obvious, confirm with the user via `AskUserQuestion`.
2. **Export** `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")` for all subsequent shell calls and subagents — this is what namespaces every output path.
3. Pick a run id: `RUN=$(date -u +%Y%m%dT%H%M%SZ)-<slug>`
4. `mkdir -p $Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts`
5. Capture the z-harness plugin version stamp and log the run start (merge version blob into the payload):
   ```bash
   VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
   START_PAYLOAD="$(python3 -c '
   import json, sys
   v = json.loads(sys.argv[1]); v["task"] = sys.argv[2]
   print(json.dumps(v))
   ' "$VERSION_BLOB" "<arguments>")"
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RUN" run_start "$START_PAYLOAD"
   ```
   Output lands under `$Z_HARNESS_PLAN_DIR/archive/$RUN/events.jsonl` (log-event.sh honors `Z_HARNESS_SLUG`).
   Then log provider resolution (once per run, guarded against re-emission):
   ```bash
   if [ ! -f "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged" ]; then
     bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-providers.sh" || true
     mkdir -p "$Z_HARNESS_PLAN_DIR/archive/$RUN"
     touch "$Z_HARNESS_PLAN_DIR/archive/$RUN/.providers-logged"
   fi
   ```
6. Notification policy: read env `Z_HARNESS_NOTIFY` (default `approval_only`). Values: `off`, `approval_only`, `all`.
7. **Check for LLM-tier docs.** If `docs/llm/INDEX.json` exists in the repo root, **do NOT read it from main thread.** Note its existence; Phase 1 will dispatch `doc-fetcher` (Haiku) to read it. The orchestrator never reads `docs/llm/*.json` directly — that's what burns main-thread context unnecessarily. If INDEX.json does not exist, note that fact and continue (Phase 1 will Explore without doc grounding).
8. **Docs-freshness route gate.** If `docs/llm/INDEX.json` exists, compute staleness across all its entries before Phase 1 starts. This step is the ONE exception where main thread reads INDEX.json — but only the lightweight metadata fields (`slug`, `last_updated`, `source_file`), never the per-concept `<slug>.json` bodies. For each concept entry, compare `entry.last_updated` against the max `mtime` of its `source_files`. A concept is **stale** if any source file's mtime exceeds `last_updated`. Compute `stale_pct = stale_concepts / total_concepts`. The threshold is `$Z_HARNESS_DOC_STALENESS_THRESHOLD` (default `20` — meaning 20 percent). If `stale_pct >= threshold`, handle it through the route-decision flow before Phase 1: write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command: "/z-plan"`, `to_command: "/z-maintain-docs"`, `route_class: "contextual"`, `reason_codes: ["docs_stale"]`, `signals.docs_stale_or_drifted: true`, `confidence: "high"`, `classifier_used: false`, `artifact_path`, `route_chain`, and the eventual `user_choice`, then push-notify and present the AskUser handoff gate: switch to `/z-maintain-docs`, continue here with stale docs, or abandon. Do not execute `/z-maintain-docs` automatically. If the user continues with stale docs, emit a `doc_drift_acknowledged` event and continue — Phase 1 still uses INDEX.json but the orchestrator should weight `relevant_concepts` hints less and verify against current code more aggressively.
9. **Pre-plan artifact detection.** Check `$Z_HARNESS_PLAN_DIR/` for `BRAINSTORM.md` and `RESEARCH.md`.
    - **Freshness check (RESEARCH.md only):** If `RESEARCH.md` exists, parse all file citations using regex `/[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?/`. Also scan for extensionless allowlist filenames (`Makefile`, `Dockerfile`). Markdown link form `[label](path:line)` — extract the inner path. For each cited path: follow symlinks; compare mtime to `generated_at`; for line-ranges, use min-line mtime (any modification within range → stale). If any stale citation found, warn the user via `AskUserQuestion` ("proceed with stale research" / "re-run research" / "abort"). Deleted-source detection: if a cited file no longer exists, emit a `precontext_source_deleted` event (higher severity than stale-mtime) **and** trigger the same `AskUserQuestion` warn path — deleted-source citations are treated as stale for the purposes of the user gate. Parse failure: emit `precontext_freshness_check_failed`, continue (fail-open).
    - **Conflict check:** If both `BRAINSTORM.md` and `RESEARCH.md` exist, scan for obvious contradictions (e.g. Brainstorm assumes X is possible; Research found constraint Y that prevents it). Surface contradictions to the user.
    - **Unfinalized brainstorm:** If `BRAINSTORM.md` is present but `status: complete` is missing or `chosen_framing` is absent, recommend the user run `/z-brainstorm` again before proceeding.

**All paths in subsequent phases live under `$Z_HARNESS_PLAN_DIR/`:**
- `$Z_HARNESS_PLAN_DIR/SPEC.md`
- `$Z_HARNESS_PLAN_DIR/PLAN.md`
- `$Z_HARNESS_PLAN_DIR/TASKS.md`
- `$Z_HARNESS_PLAN_DIR/archive/<run-id>/...`

Multiple slugs can coexist (parallel plans). The repo-wide `z-harness/metrics.jsonl` aggregates events across all slugs with a `slug` field in each event.

Each phase below ends with a checkpoint — write the phase's output to `$Z_HARNESS_PLAN_DIR/archive/$RUN/<phase>.md` so the run is resumable.

<!-- PLAN_ROUTE_CHECK_START -->
## Plan Route Check

Run this route check after Setup step 9's precontext/docs gates and before Phase 1 dispatch, then run it again after Phase 5 approval if the decisions or estimated task shape make split risk clear. Use only already-known signals: `candidate_files`, `expected_tasks`, `non_obvious_decisions`, `cluster_seams`, `cross_module`, `schema_or_persistence`, `public_api_or_wire_format`, `terrain_uncertain`, `approach_uncertain`, `has_bug_diagnosis`, `has_unknown_bug_symptom`, `has_existing_plan`, `has_fix_artifact`, and `docs_stale_or_drifted`.

Deterministic routes:
- Route tiny implementation-only work (`candidate_files <= 3`, no non-obvious decisions, no cross-module/schema/public surface impact) to `/z-do`.
- Route small targeted fixes (`candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact) to `/z-plan-light`; if the task is a diagnosed bug, use contextual `/z-fix`, and if it is an unknown bug symptom, use contextual `/z-debug`.
- Stay in `/z-plan` for coherent medium changes, especially `expected_tasks <= 25` with no clear independent cluster seams.
- Route large or independently separable work to `/z-plan-split` when `expected_tasks > 25` or `cluster_seams` is in `2..6`.
- Route unknown terrain or missing citations to `/z-research`; route multiple plausible framings with sufficient terrain to `/z-brainstorm`.
- Recommend contextual `/z-audit-plan` only after `SPEC.md`, `PLAN.md`, and `TASKS.md` exist; use `/z-amend` when the user is changing an existing plan, and `/z-maintain-docs` when doc drift blocks confidence.

Call `planning-router` only when deterministic signals conflict and no hard threshold already decides the route. It receives the compact signal payload plus the current route chain and is advisory; malformed or unavailable classifier output falls back to deterministic routing or an AskUser choice.

If routing, write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, emit `plan_route_decision` with `from_command`, `to_command`, `route_class`, `reason_codes`, `signals`, `confidence`, `classifier_used`, `artifact_path`, `route_chain`, and `user_choice`, then present the AskUser handoff gate: switch, continue when not forbidden by a hard threshold, or abandon. Do not execute the next command automatically.

Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
<!-- PLAN_ROUTE_CHECK_END -->

exec
/bin/zsh -lc 'python3 -m json.tool docs/llm/INDEX.json >/tmp/index.ok && python3 -m json.tool docs/llm/commands.json >/tmp/commands.ok && python3 -m json.tool docs/llm/skills.json >/tmp/skills.ok && python3 -m json.tool docs/llm/agents.json >/tmp/agents.ok && echo ok' in /Users/zeke/dev/z-harness
 succeeded in 346ms:
ok

exec
/bin/zsh -lc "find z-harness/plans/plan-bail-router -maxdepth 3 -type f | sort | sed -n '1,240p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/amendment.md
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/events.jsonl
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/base-ref.txt
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.diff
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/cumulative.stat
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/events.jsonl
z-harness/plans/plan-bail-router/archive/orchestration/events.jsonl
z-harness/plans/plan-bail-router/archive/plan-bail-router/events.jsonl
z-harness/plans/plan-bail-router/archive/unknown-run/events.jsonl

exec
/bin/zsh -lc "rg -n \"Scenario Acceptance|Tiny implementation|Small targeted|ping-pong|manually verified|route coverage|Scenario\" z-harness/plans/plan-bail-router commands skills docs exports z-harness/plans/plan-bail-router/archive/20260525T081137Z-review -g '"'!cumulative.diff'"'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
skills/z-plan-split/SKILL.md:161:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/SPEC.md:172:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/SPEC.md:206:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/SPEC.md:379:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/SPEC.md:382:## Scenario Acceptance
z-harness/plans/plan-bail-router/SPEC.md:386:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/SPEC.md:387:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/SPEC.md:395:- Immediate ping-pong route is blocked and surfaced to the user.
commands/z-plan-split.md:160:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/z-plan-split.md:160:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/z-brainstorm.md:59:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/PLAN.md:82:Loop prevention matters because the family includes both lighter and heavier modes. A route chain and ping-pong check are enough for v1; a global router state store would be unnecessary.
z-harness/plans/plan-bail-router/PLAN.md:173:- scenario checklist from SPEC is manually verified or recorded in the implementation summary
z-harness/plans/plan-bail-router/PLAN.md:200:- Scenario acceptance from SPEC is verified.
commands/z-audit-plan.md:27:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/z-plan.md:79:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/z-audit-plan.md:27:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/TASKS.md:55:- [ ] Route-chain and ping-pong prevention are included.
z-harness/plans/plan-bail-router/TASKS.md:124:## T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/TASKS.md:146:- [ ] Scenario checklist from SPEC is manually verified in the implementation summary.
docs/human/z-debug.md:79:### Scenario
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:221:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:255:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:428:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:431:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:435:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:436:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:444:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:532:Loop prevention matters because the family includes both lighter and heavier modes. A route chain and ping-pong check are enough for v1; a global router state store would be unnecessary.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:623:- scenario checklist from SPEC is manually verified or recorded in the implementation summary
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:650:- Scenario acceptance from SPEC is verified.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:711:- [ ] Route-chain and ping-pong prevention are included.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:780:## T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:802:- [ ] Scenario checklist from SPEC is manually verified in the implementation summary.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:967:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1228:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1277:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1350:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1480:+- Route chains prevent ping-pong between commands. If the chain already has two entries or the recommendation would immediately return to the prior command, commands ask the user to choose explicitly.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2403:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2911:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2960:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3033:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3317:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3780:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3829:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3902:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4398:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4905:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4954:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5027:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5311:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5774:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5823:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5896:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6648:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7169:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7218:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7291:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7723:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8258:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8307:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8380:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8650:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8919:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8974:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9053:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9251:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9771:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9977:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10497:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10704:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10908:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11428:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11635:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:171:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:205:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:376:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:379:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:383:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:384:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/SPEC.md:392:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/PLAN.md:80:Loop prevention matters because the family includes both lighter and heavier modes. A route chain and ping-pong check are enough for v1; a global router state store would be unnecessary.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/PLAN.md:171:- scenario checklist from SPEC is manually verified or recorded in the implementation summary
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/PLAN.md:198:- Scenario acceptance from SPEC is verified.
exports/agy/prompts/z-research.md:64:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/phase3-decisions-final.md:69:- If the recommended target equals the immediate prior `from_command`, do not ping-pong; surface both route notes and ask the user to choose.
skills/z-research/SKILL.md:65:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/skill-z-brainstorm.md:59:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/skill-z-plan.md:71:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
docs/human/commands.md:45:- Route chains prevent ping-pong between commands. If the chain already has two entries or the recommendation would immediately return to the prior command, commands ask the user to choose explicitly.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/TASKS.md:52:- [ ] Route-chain and ping-pong prevention are included.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/TASKS.md:118:## T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/TASKS.md:139:- [ ] Scenario checklist from SPEC is manually verified in the implementation summary.
commands/z-brainstorm.md:59:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260524T215006Z-plan-bail-router/phase1-context.md:11:- Routing must be acyclic per run: a command can recommend a better-fit variant, but the next invocation should record prior route context to avoid ping-pong.
skills/z-audit-plan/SKILL.md:27:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/skill-z-plan-split.md:160:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/skill-z-research.md:64:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
commands/z-research.md:64:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/agy/prompts/skill-z-audit-plan.md:27:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
skills/z-brainstorm/SKILL.md:60:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
skills/z-plan/SKILL.md:72:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:221:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:255:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:428:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:431:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:435:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:436:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:444:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:532:Loop prevention matters because the family includes both lighter and heavier modes. A route chain and ping-pong check are enough for v1; a global router state store would be unnecessary.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:623:- scenario checklist from SPEC is manually verified or recorded in the implementation summary
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:650:- Scenario acceptance from SPEC is verified.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:711:- [ ] Route-chain and ping-pong prevention are included.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:780:## T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:802:- [ ] Scenario checklist from SPEC is manually verified in the implementation summary.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:967:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1228:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1277:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1350:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:1480:+- Route chains prevent ping-pong between commands. If the chain already has two entries or the recommendation would immediately return to the prior command, commands ask the user to choose explicitly.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2403:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2911:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:2960:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3033:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3317:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3780:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3829:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:3902:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4398:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4905:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:4954:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5027:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5311:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5774:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5823:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:5896:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:6648:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7169:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7218:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7291:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:7723:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8258:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8307:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8380:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8650:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8919:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:8974:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9053:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9251:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9771:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:9977:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10497:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10704:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:10908:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11428:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/20260525T081137Z-review/transcripts/002-gemini-final-review-2pronged.prompt.md:11635:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/codex/prompts/z-plan-split.md:157:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
commands/z-plan.md:79:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/codex/prompts/z-audit-plan.md:24:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:45:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:137:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:229:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:321:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:413:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:505:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:603:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:659:+Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:754:+## Scenario Checklist
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:756:+- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:757:+- Small targeted fix in `/z-plan` recommends `/z-plan-light`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch:765:+- Immediate ping-pong route is blocked and surfaced to the user: verified in every route block's loop-prevention language.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:175:+| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:209:+- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:382:+- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:385:+## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:389:+- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:390:+- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/SPEC.md.diff:398:+- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/PLAN.md.diff:85:+Loop prevention matters because the family includes both lighter and heavier modes. A route chain and ping-pong check are enough for v1; a global router state store would be unnecessary.
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/PLAN.md.diff:176:+- scenario checklist from SPEC is manually verified or recorded in the implementation summary
z-harness/plans/plan-bail-router/archive/20260524T235017Z-amend-plan-bail-router/z-harness/plans/plan-bail-router/PLAN.md.diff:203:+- Scenario acceptance from SPEC is verified.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:40:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:100:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:160:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:220:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:280:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:340:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:400:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:466:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:495:+Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:621:+## Scenario Checklist
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:623:+- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:624:+- Small targeted fix in `/z-plan` recommends `/z-plan-light`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch:632:+- Immediate ping-pong route is blocked and surfaced to the user: verified in every route block's loop-prevention language.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:177:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:211:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:384:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:387:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:391:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:392:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:400:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:408:- Route-chain and ping-pong prevention are included.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:436:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:467:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:518:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:555:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:1:You are reviewing code that Claude just wrote for task T007: Validate route coverage and scenarios.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:201:- Scenario checklist from SPEC is manually verified in the implementation summary.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:326:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:891: +Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:927: +## Scenario Checklist
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:929: +- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:175:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:209:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:382:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:385:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:389:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:390:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:398:- Immediate ping-pong route is blocked and surfaced to the user.
exports/codex/prompts/z-brainstorm.md:56:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:192:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:226:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:399:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:402:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:406:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:407:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:415:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:423:- Route-chain and ping-pong prevention are included.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:451:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:482:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:533:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:570:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T005/diff.patch:125:+- Route chains prevent ping-pong between commands. If the chain already has two entries or the recommendation would immediately return to the prior command, commands ask the user to choose explicitly.
z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch:25:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch:56:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch:107:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T003/diff.patch:144:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:317:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:638:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:669:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:700:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:876:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1139:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1170:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1216:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1577:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1897:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1928:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:1959:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2135:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2398:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2429:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:2475:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3092:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3426:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3457:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3488:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:3785:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:4133:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:4164:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md:4195:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:190:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:224:- If `to_command` equals the immediate prior `from_command`, do not ping-pong. Present both route artifacts and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:397:- Route chain `/z-do -> /z-plan-light -> /z-do`: detect ping-pong and ask the user to choose.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:400:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:404:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:405:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:413:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/tasks/T004/diff.patch:26:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T004/diff.patch:57:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T004/diff.patch:94:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T004/diff.patch:131:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:19:You are reviewing code that Claude just wrote for task T007: Validate route coverage and scenarios.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:219:- Scenario checklist from SPEC is manually verified in the implementation summary.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:344:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:909: +Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:945: +## Scenario Checklist
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:947: +- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1034:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1094:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1154:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1214:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1274:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1334:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1394:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:1460:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
exports/codex/prompts/z-research.md:61:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:3:Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:129:## Scenario Checklist
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:131:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:132:- Small targeted fix in `/z-plan` recommends `/z-plan-light`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:140:- Immediate ping-pong route is blocked and surfaced to the user: verified in every route block's loop-prevention language.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:332:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:653:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:684:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:715:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:891:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1154:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1185:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1231:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1592:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1912:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1943:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:1974:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2150:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2413:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2444:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:2490:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3107:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3441:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3472:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3503:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:3800:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4148:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4179:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:4210:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:6415:    27	Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md:6505:    27	Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:147:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:477:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:508:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:539:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:715:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:987:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1018:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1064:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1425:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1754:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1785:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1816:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:1992:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2264:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2295:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2341:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:2958:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3301:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3332:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3363:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:3660:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4017:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4048:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4079:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4402:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:4922:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5128:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5648:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:5855:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6059:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6579:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch:6786:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:119:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:684: +Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:720: +## Scenario Checklist
z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch:722: +- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/SUMMARY.md:5:Validated canonical route coverage and scenarios, recorded evidence in `VALIDATION.md`, restored the `/z-plan` usage-limit guard, converted docs staleness to route-decision flow, and synced generated `z-plan` exports.
exports/codex/prompts/z-plan.md:68:Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:147:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:468:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:499:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:530:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:706:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:969:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1000:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1046:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1407:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1727:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1758:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1789:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:1965:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2228:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2259:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2305:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:2922:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3256:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3287:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3318:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3615:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3963:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:3994:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch:4025:+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:231:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:262:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:293:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:469:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:732:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:763:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:809:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1170:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1490:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1521:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1552:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1728:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:1991:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:2022:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:2068:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:2685:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3019:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3050:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3081:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3378:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3726:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3757:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:3788:-+Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4152:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4183:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4214:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4390:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4662:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4693:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:4739:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5100:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5429:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5460:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5491:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5667:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5939:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:5970:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:6016:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:6633:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:6976:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7007:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7038:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7335:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7692:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7723:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:7754:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8077:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8597:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:8803:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9323:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9530:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:9734:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10254:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch:10461:++Loop prevention: carry forward the latest route chain; if it already has two entries, ask the user to choose explicitly. If the recommended target equals the immediate prior `from_command`, block ping-pong, show both route artifacts, and ask the user to choose. If the user continues here, log the override and do not route again for the same `reason_codes` in this run.

exec
/bin/zsh -lc "find z-harness/plans/plan-bail-router/archive/tasks -maxdepth 3 -type f 2>/dev/null | sort | sed -n '1,240p'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
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
z-harness/plans/plan-bail-router/archive/tasks/T006/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T006/delta-v2.patch
z-harness/plans/plan-bail-router/archive/tasks/T006/diff-v1.patch
z-harness/plans/plan-bail-router/archive/tasks/T006/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T006/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T006/review.prompt.md
z-harness/plans/plan-bail-router/archive/tasks/T006/review.response.md
z-harness/plans/plan-bail-router/archive/tasks/T006/review.return.md
z-harness/plans/plan-bail-router/archive/tasks/T007/SUMMARY.md
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md
z-harness/plans/plan-bail-router/archive/tasks/T007/delta-v3.patch
z-harness/plans/plan-bail-router/archive/tasks/T007/diff-v2.patch
z-harness/plans/plan-bail-router/archive/tasks/T007/diff.patch
z-harness/plans/plan-bail-router/archive/tasks/T007/events.jsonl
z-harness/plans/plan-bail-router/archive/tasks/T007/review-meta-v3.json
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md
z-harness/plans/plan-bail-router/archive/tasks/T007/review.return.md

exec
/bin/zsh -lc "rg -n \"Scenario checklist|Scenario Acceptance|manually verified|Tiny implementation|Small targeted|Immediate ping-pong|scenario\" z-harness/plans/plan-bail-router/archive/tasks -g '*.md' -g '*.txt' -g '*.jsonl'" in /Users/zeke/dev/z-harness
 succeeded in 0ms:
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:1:You are reviewing code that Claude just wrote for task T007: Validate route coverage and scenarios.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:201:- Scenario checklist from SPEC is manually verified in the implementation summary.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:891: +Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/review.prompt.md:929: +- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:19:You are reviewing code that Claude just wrote for task T007: Validate route coverage and scenarios.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:219:- Scenario checklist from SPEC is manually verified in the implementation summary.
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:909: +Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/review.response.md:947: +- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:3:Task: T007 - Validate route coverage and scenarios
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:131:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:132:- Small targeted fix in `/z-plan` recommends `/z-plan-light`: verified in `/z-plan` command and skill route blocks.
z-harness/plans/plan-bail-router/archive/tasks/T007/VALIDATION.md:140:- Immediate ping-pong route is blocked and surfaced to the user: verified in every route block's loop-prevention language.
z-harness/plans/plan-bail-router/archive/tasks/T007/SUMMARY.md:5:Validated canonical route coverage and scenarios, recorded evidence in `VALIDATION.md`, restored the `/z-plan` usage-limit guard, converted docs staleness to route-decision flow, and synced generated `z-plan` exports.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:175:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:385:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:387:Implementation must document or manually verify these scenarios:
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:389:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:390:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.prompt.md:398:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:190:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:400:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:402:Implementation must document or manually verify these scenarios:
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:404:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:405:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T002/review.response.md:413:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:177:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:387:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:389:Implementation must document or manually verify these scenarios:
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:391:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:392:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.prompt.md:400:- Immediate ping-pong route is blocked and surfaced to the user.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:192:| Small targeted fix, `candidate_files <= 5`, `non_obvious_decisions <= 2`, no public API/schema impact | `/z-plan-light` | Produces `FIX.md` and implements inline. |
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:402:## Scenario Acceptance
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:404:Implementation must document or manually verify these scenarios:
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:406:- Tiny implementation task in `/z-plan` before Explore recommends `/z-do`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:407:- Small targeted fix in `/z-plan` recommends `/z-plan-light`.
z-harness/plans/plan-bail-router/archive/tasks/T003/review.response.md:415:- Immediate ping-pong route is blocked and surfaced to the user.

codex
Read-only final review completed. I found blockers/majors in both prongs.

**Prong A Findings**

- severity: blocker
- prong: A
- file/path if applicable: `commands/z-audit-plan.md`
- evidence: Phase 5 offers actions that violate the spec invariants: “Proceed as-is” says to “start implementation,” and “Reject & Re-plan” says to “Discard current plan artifacts and rerun `/z-plan`.” The spec requires `/z-audit-plan` to remain read-only, use contextual route exits, never auto-execute another command, and stop if the user switches.
- recommendation: Change Phase 5 options into route-decision handoffs: write `route-decision.md`, emit `plan_route_decision`, present switch/continue/abandon, and stop after presenting the exact next invocation. “Proceed as-is” should end the audit only, not start implementation.
- one reason the finding might be wrong: The text may be intended as user-facing next-step wording rather than instructions to execute those steps, but it is written imperatively enough that an agent could perform them.

- severity: major
- prong: A
- file/path if applicable: `commands/z-plan-split.md`, `skills/z-plan-split/SKILL.md`, generated `z-plan-split` exports
- evidence: The route block says to write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, but setup only exports `Z_HARNESS_SLUG`; it never defines `Z_HARNESS_PLAN_DIR`. Step 5 also uses `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts` before any assignment.
- recommendation: Define `Z_HARNESS_PLAN_DIR=$(.../scripts/plan-path.sh resolve_plan_path "$Z_HARNESS_SLUG")` during setup and define/use `CURRENT_ARCHIVE_DIR` immediately after creating the archive, matching the spec contract.
- one reason the finding might be wrong: A surrounding runtime might predefine `Z_HARNESS_PLAN_DIR`, but the prompt is meant to be standalone after export.

- severity: major
- prong: A
- file/path if applicable: `commands/z-plan.md`, `commands/z-plan-split.md`, `commands/z-brainstorm.md`, `commands/z-research.md`, `commands/z-audit-plan.md`, matching skills/exports
- evidence: The spec requires route artifacts to contain `Recommendation`, `Reason`, `Signals`, `Route Chain`, and `Resume Context`. Most route blocks only say “write route-decision.md” and list telemetry fields; only `/z-do` and `/z-plan-light` mention the artifact content, and even they do not specify the required section headings/template.
- recommendation: Add the required Markdown template or explicit required headings to every route block in canonical commands and skills, then regenerate exports.
- one reason the finding might be wrong: An agent may infer the required artifact structure from SPEC/docs memory, but the exported prompts are supposed to be standalone.

- severity: major
- prong: A
- file/path if applicable: `skills/z-plan/SKILL.md`, `exports/codex/prompts/z-plan.md`, `exports/cursor/.cursor/rules/z-plan.mdc`
- evidence: `commands/z-plan.md` was updated to check both `z-harness/plans/` and legacy `z-harness/` for existing slug dirs, but `skills/z-plan/SKILL.md` and Codex/Cursor exports still say to run `ls z-harness/` only. That can miss existing plans in the canonical directory and break existing-plan contextual routing.
- recommendation: Sync the skill source with the command source and regenerate exports so all surfaces check canonical plans plus legacy.
- one reason the finding might be wrong: This is adjacent to routing rather than inside the route block itself, but it directly affects `has_existing_plan` detection.

**Prong B Findings**

- severity: major
- prong: B
- file/path if applicable: `z-harness/plans/plan-bail-router/SPEC.md`
- evidence: The spec orders the route flow as write artifact, emit `plan_route_decision`, then present AskUser, while telemetry requires `user_choice`. That field is not known until after AskUser returns.
- recommendation: Specify either that `plan_route_decision` is emitted after AskUser with final `user_choice`, or split telemetry into `route_presented` and `route_choice`.
- one reason the finding might be wrong: The numbered list may not have been intended as strict execution order.

- severity: major
- prong: B
- file/path if applicable: `z-harness/plans/plan-bail-router/SPEC.md`
- evidence: `/z-audit-plan` must route to `/z-plan` when no plan artifacts exist, but the artifact path rule says `/z-audit-plan` writes under `$BASE/archive/$RUN`, where `$BASE=$Z_HARNESS_PLAN_DIR`. With no selected plan, there is no defined slug or `$Z_HARNESS_PLAN_DIR`.
- recommendation: Define a no-plan audit archive location and run id in the spec, or require deriving a synthetic slug before emitting the route.
- one reason the finding might be wrong: The implementation invented `z-harness/archive/$NO_PLAN_RUN`, which is reasonable, but it is not specified.

- severity: major
- prong: B
- file/path if applicable: `z-harness/plans/plan-bail-router/SPEC.md`
- evidence: Loop prevention depends on carrying `route_chain` across commands, but the spec does not define how the next command receives the prior `route-decision.md` or chain. “Discover in the active run archive” does not work reliably when switching from `/z-do` adhoc to a slugged plan command or between different plan dirs.
- recommendation: Add an explicit handoff mechanism, such as `--route-from <path>` or a required pasted route-chain/resume-context block in the exact next invocation.
- one reason the finding might be wrong: A user could manually paste context from the artifact, but the contract should not rely on that for loop prevention.
tokens used
143,408
Read-only final review completed. I found blockers/majors in both prongs.

**Prong A Findings**

- severity: blocker
- prong: A
- file/path if applicable: `commands/z-audit-plan.md`
- evidence: Phase 5 offers actions that violate the spec invariants: “Proceed as-is” says to “start implementation,” and “Reject & Re-plan” says to “Discard current plan artifacts and rerun `/z-plan`.” The spec requires `/z-audit-plan` to remain read-only, use contextual route exits, never auto-execute another command, and stop if the user switches.
- recommendation: Change Phase 5 options into route-decision handoffs: write `route-decision.md`, emit `plan_route_decision`, present switch/continue/abandon, and stop after presenting the exact next invocation. “Proceed as-is” should end the audit only, not start implementation.
- one reason the finding might be wrong: The text may be intended as user-facing next-step wording rather than instructions to execute those steps, but it is written imperatively enough that an agent could perform them.

- severity: major
- prong: A
- file/path if applicable: `commands/z-plan-split.md`, `skills/z-plan-split/SKILL.md`, generated `z-plan-split` exports
- evidence: The route block says to write `$Z_HARNESS_PLAN_DIR/archive/$RUN/route-decision.md`, but setup only exports `Z_HARNESS_SLUG`; it never defines `Z_HARNESS_PLAN_DIR`. Step 5 also uses `$Z_HARNESS_PLAN_DIR/archive/$RUN/transcripts` before any assignment.
- recommendation: Define `Z_HARNESS_PLAN_DIR=$(.../scripts/plan-path.sh resolve_plan_path "$Z_HARNESS_SLUG")` during setup and define/use `CURRENT_ARCHIVE_DIR` immediately after creating the archive, matching the spec contract.
- one reason the finding might be wrong: A surrounding runtime might predefine `Z_HARNESS_PLAN_DIR`, but the prompt is meant to be standalone after export.

- severity: major
- prong: A
- file/path if applicable: `commands/z-plan.md`, `commands/z-plan-split.md`, `commands/z-brainstorm.md`, `commands/z-research.md`, `commands/z-audit-plan.md`, matching skills/exports
- evidence: The spec requires route artifacts to contain `Recommendation`, `Reason`, `Signals`, `Route Chain`, and `Resume Context`. Most route blocks only say “write route-decision.md” and list telemetry fields; only `/z-do` and `/z-plan-light` mention the artifact content, and even they do not specify the required section headings/template.
- recommendation: Add the required Markdown template or explicit required headings to every route block in canonical commands and skills, then regenerate exports.
- one reason the finding might be wrong: An agent may infer the required artifact structure from SPEC/docs memory, but the exported prompts are supposed to be standalone.

- severity: major
- prong: A
- file/path if applicable: `skills/z-plan/SKILL.md`, `exports/codex/prompts/z-plan.md`, `exports/cursor/.cursor/rules/z-plan.mdc`
- evidence: `commands/z-plan.md` was updated to check both `z-harness/plans/` and legacy `z-harness/` for existing slug dirs, but `skills/z-plan/SKILL.md` and Codex/Cursor exports still say to run `ls z-harness/` only. That can miss existing plans in the canonical directory and break existing-plan contextual routing.
- recommendation: Sync the skill source with the command source and regenerate exports so all surfaces check canonical plans plus legacy.
- one reason the finding might be wrong: This is adjacent to routing rather than inside the route block itself, but it directly affects `has_existing_plan` detection.

**Prong B Findings**

- severity: major
- prong: B
- file/path if applicable: `z-harness/plans/plan-bail-router/SPEC.md`
- evidence: The spec orders the route flow as write artifact, emit `plan_route_decision`, then present AskUser, while telemetry requires `user_choice`. That field is not known until after AskUser returns.
- recommendation: Specify either that `plan_route_decision` is emitted after AskUser with final `user_choice`, or split telemetry into `route_presented` and `route_choice`.
- one reason the finding might be wrong: The numbered list may not have been intended as strict execution order.

- severity: major
- prong: B
- file/path if applicable: `z-harness/plans/plan-bail-router/SPEC.md`
- evidence: `/z-audit-plan` must route to `/z-plan` when no plan artifacts exist, but the artifact path rule says `/z-audit-plan` writes under `$BASE/archive/$RUN`, where `$BASE=$Z_HARNESS_PLAN_DIR`. With no selected plan, there is no defined slug or `$Z_HARNESS_PLAN_DIR`.
- recommendation: Define a no-plan audit archive location and run id in the spec, or require deriving a synthetic slug before emitting the route.
- one reason the finding might be wrong: The implementation invented `z-harness/archive/$NO_PLAN_RUN`, which is reasonable, but it is not specified.

- severity: major
- prong: B
- file/path if applicable: `z-harness/plans/plan-bail-router/SPEC.md`
- evidence: Loop prevention depends on carrying `route_chain` across commands, but the spec does not define how the next command receives the prior `route-decision.md` or chain. “Discover in the active run archive” does not work reliably when switching from `/z-do` adhoc to a slugged plan command or between different plan dirs.
- recommendation: Add an explicit handoff mechanism, such as `--route-from <path>` or a required pasted route-chain/resume-context block in the exact next invocation.
- one reason the finding might be wrong: A user could manually paste context from the artifact, but the contract should not rely on that for loop prevention.
