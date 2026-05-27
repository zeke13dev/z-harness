# Plugin-author Conventions

> Last updated: 2026-05-27

Conventions for downstream repos that define `.claude/skills/` files
interoperating with z-harness.

## Conventions

- End each skill file with `## Anti-patterns (push back)` and `## Out of scope`
  sections — they're the cheapest place to encode failure modes and handoff
  boundaries.
- Skills that diagnose should NOT also apply patches. Hand off to `/z-plan-light`
  (small fix) or `/z-plan` (structural) for any code change beyond initial
  scaffolding.
- Skills that orchestrate should call cross-LLM consult (`consultant-primary`,
  `consultant-secondary`) at premise / red-team gates, not run them inline.
- Use explicit slash commands instead of flag-routed `mode:` parameters — one
  skill per mode (`/qt-audit-strategy`, not `/qt-audit mode=strategy`).
- Domain-specific audit checklists live under `.claude/audit-rubrics/<component>.md`
  and are consumed by `/z-audit` via its rubric-file slot — keep them as plain
  checklists, not scaffolding.

## Operating principles

These apply to all z-harness commands and skills:

- Push back by default — on Gemini, Codex, and the user.
- Always ask when unclear. No silent assumptions.
- No shortcuts without explicit user approval.
- DRY / KISS / SOLID are non-negotiable in the final plan.
