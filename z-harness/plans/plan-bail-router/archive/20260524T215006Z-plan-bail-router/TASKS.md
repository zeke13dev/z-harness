# Tasks: Plan Bail Router

## T001 - Add planning-router agent

**Status:** [ ]
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

**Status:** [ ]
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

**Status:** [ ]
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

**Status:** [ ]
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

**Status:** [ ]
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

**Status:** [ ]
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

**Status:** [ ]
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
