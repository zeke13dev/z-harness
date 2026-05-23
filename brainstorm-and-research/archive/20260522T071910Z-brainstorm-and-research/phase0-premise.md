# Phase 0 — Premise check

## Premise accepted (with notes)

**Stated goal:** Add `/z-brainstorm` and `/z-research` as opt-in pre-plan commands so the harness can separate exploration from plan-commitment.

**Premise check passes** because the alternative paths were already exhausted in conversation:
- *Auto-detect inside `/z-plan`?* Rejected — violates explicit-commands preference ([[feedback-explicit-commands]]).
- *Flag on `/z-plan`?* Rejected for same reason.
- *Single `/z-plan-multi` that fans out N full plans?* Rejected — pays full-plan cost N× and the cross-LLM consult already gives perspective-diversity at the decision level for ~1/Nth the cost.
- *Two-stage chainable commands?* Chosen — lightweight exploration, then commitment.

**One reason this might be wrong (mechanical pushback):** these commands might be rarely used in practice. If 90% of `/z-plan` runs don't need pre-plan exploration, we're adding 2 commands + 4 files of harness surface area for narrow value. Mitigation: ship as opt-in; if usage data after some weeks shows <5% adoption, deprecate. Adding telemetry (`brainstorm_run_start` / `research_run_start` events) lets `/z-stats` answer this empirically.

**Goal restated for the user to correct if wrong:**

Build two opt-in slash commands that the user invokes when they explicitly want pre-plan exploration. `/z-brainstorm` is a cheap fan-out across model vendors (Claude / Codex / Gemini) producing N candidate problem-framings; the user picks one. `/z-research` is a heavier terrain-mapping pass using doc-fetcher + Explore + cross-LLM critique that produces a findings note with no recommendation. Both are chainable into `/z-plan` (which reads their artifacts as Phase-0 seed context).

## Out-of-bounds risks worth noting (not decisions, just flags)

- **Cost runaway on `/z-research`:** 2M-token target is aspirational; an over-curious orchestrator could blow through it. Mitigate via explicit pre-confirmation gate + hard Explore cap.
- **Skill-mirror duplication:** every command must be authored twice (`commands/X.md` and `skills/X/SKILL.md`). This was flagged in the per-task-model-selection retro but is out of scope here.
- **Ideator self-bias:** if Claude is also an ideator AND orchestrator, there's a small risk it favors its own framing in synthesis. Surfaced as a Phase 3 consult question.
