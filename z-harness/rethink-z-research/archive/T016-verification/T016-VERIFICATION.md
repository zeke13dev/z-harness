# T016 Post-Implementation Rename Verification

Run date: 2026-05-26
Grep pattern: `/z-research|z-research|RESEARCH\.md|needs_research`
Exclusions: `z-harness/**`, `docs/llm/MEMORIES-FLAT.md`, `exports/**`
Final hit count: 208 lines across 26 files

## Class (b) misses fixed

### Fix 1: `.agent/workflows/z-research.md` — old terrain content replaced
- **File:** `/Users/zeke/dev/z-harness/.agent/workflows/z-research.md`
- **Problem:** Contained old terrain-mapping skill description ("pre-plan terrain mapping", "does not recommend an approach", "it maps terrain, it does not pick an approach").
- **Fix:** Replaced with content from `exports/agy/.agent/workflows/z-research.md` (new meta-orchestrator version, 1147 lines).
- **Verification:** File now describes the meta-orchestrator pipeline with adversarial synthesis panel.

Note: `.agent/workflows/z-research.md` did NOT appear in the grep output because the grep glob `!z-harness/**` does not exclude `.agent/` (a different top-level directory). The KNOWN MISS flag in the task block was correct — the file existed with old content and has been replaced.

### Fix 2: `docs/human/telemetry.md` — `research_temptation` attribution corrected
- **File:** `/Users/zeke/dev/z-harness/docs/human/telemetry.md`
- **Problem:** Row `research_temptation` attributed event to `/z-research` (old terrain behavior). Post-rename, this event is emitted by `/z-map` (`commands/z-map.md`). Note: `skills/z-map/SKILL.md` uses the name `map_temptation` for the same invariant (inconsistency between commands and skills files — noted for follow-up).
- **Fix:** Updated "Emitted by" to `/z-map (commands/z-map.md)` and added note about the `map_temptation` vs `research_temptation` inconsistency.
- **Section header updated:** from `/z-brainstorm` and `/z-research` to `/z-brainstorm`, `/z-map`, and `/z-research`.

## Remaining class (a) hits — NEW /z-research orchestrator (leave)

All remaining 208 lines reference the NEW `/z-research` meta-orchestrator (composes /z-map + /z-brainstorm, adversarial synthesis panel, RESEARCH.md with 10-section schema). Files:

- `commands/z-research.md` — IS the new orchestrator command
- `skills/z-research/SKILL.md` — IS the new orchestrator SKILL
- `agents/research-judge.md` — IS the new judge agent for /z-research panel
- `README.md` — command catalogue entry for /z-research
- `commands/z-map.md` — references /z-research for synthesis routing
- `commands/z-plan.md` — RESEARCH.md precontext (new schema), /z-research routing
- `commands/z-brainstorm.md` — RESEARCH.md legacy fallback + /z-research routing
- `skills/z-brainstorm/SKILL.md` — same as commands/z-brainstorm.md
- `skills/z-map/SKILL.md` — references /z-research for synthesis routing
- `skills/z-plan/SKILL.md` — RESEARCH.md precontext + /z-research routing
- `skills/z-plan-light/SKILL.md` — routes to /z-research when terrain uncertain
- `skills/z-plan-split/SKILL.md` — routes to /z-research for unknown terrain
- `skills/z-do/SKILL.md` — routes to /z-research when terrain uncertain
- `agents/research-judge.md` — final synthesizer for /z-research panel
- `agents/planning-router.md` — recommends /z-research as route option
- `docs/human/PLAN-LAYOUT.md` — shows RESEARCH.md artifact in plan directory tree
- `docs/human/agents.md` — documents research-judge for /z-research
- `docs/human/commands.md` — documents /z-research as meta-orchestrator
- `docs/human/limitations.md` — references /z-research artifacts
- `docs/human/skills.md` — documents z-research SKILL
- `docs/human/telemetry.md` — events for /z-research (cost_gate_decision, research_run_start/end)
- `docs/llm/INDEX.json` — indexes commands/z-research.md
- `docs/llm/agents.json` — research-judge summary for /z-research
- `docs/llm/commands.json` — /z-research command entry
- `docs/llm/skills.json` — z-research SKILL entry

## Remaining class (c) hits — deprecated alias (leave with comment)

- `agents/planning-router.md:81` — `needs_research` marked as `DEPRECATED ALIAS` in the file itself, with explicit note to drop in next major version. Maps to `needs_terrain_map` → `/z-map`. The deprecation comment is present inline.

## Out-of-scope observations (not fixed, flagged for follow-up)

1. **`agents/consultant-primary.md` and `agents/consultant-secondary.md`** — Both contain a `research-review` mode description ("Phase 4 of `/z-research`") that was part of the OLD /z-research terrain-mapping workflow. The new `/z-research` meta-orchestrator does NOT use `research-review` mode — it dispatches custom inline prompts to consultants for the adversarial panel. This is dead code but was not in scope of any task in the rethink-z-research plan. Recommend adding a cleanup task to remove or update the `research-review` mode in a future pass.

2. **`research_temptation` vs `map_temptation` event name inconsistency** — `commands/z-map.md` emits `research_temptation` while `skills/z-map/SKILL.md` emits `map_temptation` for the same "no-recommendation" invariant. These should be unified. The `scripts/log-event.sh` collects these events; having two different names for the same invariant complicates telemetry queries. Recommend standardizing to `map_temptation` in a future task.
