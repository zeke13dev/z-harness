# Escalation: plan-variant-bail-routing

Light mode should stop here.

## Why

The requested change affects the shared behavior of the plan-family commands, not a small localized fix. Candidate source surfaces already exceed the `/z-plan-light` edit threshold:

- `commands/z-plan.md`
- `commands/z-plan-light.md`
- `commands/z-plan-split.md`
- `commands/z-brainstorm.md`
- `commands/z-research.md`
- `commands/z-audit-plan.md`
- `skills/z-plan/SKILL.md`
- `skills/z-plan-light/SKILL.md`
- `skills/z-plan-split/SKILL.md`
- `skills/z-brainstorm/SKILL.md`
- `skills/z-research/SKILL.md`
- `skills/z-audit-plan/SKILL.md`

Exports and docs would also need propagation after the source policy is settled.

## Recommended Next Command

Run `/z-plan make all z-plan variants able to bail to each other`.

## Design Seed

Use a small shared "planning router" rubric rather than pairwise ad hoc bail text in every command. The router can combine deterministic signals, such as candidate file count, estimated task count, affected modules, schema/API impact, ambiguity, and known artifacts, with an optional cheap complexity-classifier subagent when the deterministic score lands in an uncertain band.

The likely route matrix:

- Tiny implementation task -> `/z-do`
- Small targeted fix with one key decision -> `/z-plan-light`
- Medium coherent feature/change -> `/z-plan`
- Very large topic with separable clusters -> `/z-plan-split`
- Unclear approach space -> `/z-brainstorm`
- Unknown terrain / fact-finding needed -> `/z-research`
- Existing plan artifacts need validation before execution -> `/z-audit-plan`

Open design question: whether the classifier should decide the final route or only adjudicate borderline deterministic scores. Prefer the latter unless `/z-plan` determines that deterministic signals are too brittle.
