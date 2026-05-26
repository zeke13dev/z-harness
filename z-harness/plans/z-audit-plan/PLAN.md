# PLAN — z-audit-plan

## Goals
- Add the `z-audit-plan` command and skill to the `z-harness` repository.
- Reality-check references in `SPEC.md` / `TASKS.md` against the active codebase (symbols, files, tables, configs described as "MUST EXIST NOW") to prevent spec hallucinations.
- Audit plan architecture and style choices against KISS, DRY, SOLID, and `STYLE.md` (if exists).
- Dispatch Gemini and Codex in parallel as adversarial plan reviewers to audit logic, edge cases, vulnerabilities, and test coverage.
- Merge findings and promote them to a final report (`PLAN_AUDIT_REPORT.md`) while filtering false positives using the "one reason it might be wrong" pushback rule.
- Hook into the multi-IDE export configuration and run export scripts to generate updated artifacts for all target IDEs.

## Non-goals
- Modifying any active codebase files during the audit process (the audit is strictly read-only).
- Automating fixes to the plan files without user review and confirmation.

## Decisions
- **Decision 1: Command & Skill Naming**
  - *Options:* `z-audit-plan` (aligned with `z-audit`), `z-plan-audit`.
  - *Call:* `z-audit-plan` for clear symmetry with `z-audit`.
- **Decision 2: Core Command Path**
  - *Call:* `commands/z-audit-plan.md` to house the full pipeline logic.
- **Decision 3: Workspace Skill Path**
  - *Call:* `skills/z-audit-plan/SKILL.md` with identical body logic and skill frontmatter.
- **Decision 4: Integration Gate Recommendation**
  - *Call:* Suggest `/z-audit-plan` in Phase 9 of `commands/z-plan.md` as a key step before starting implementation.

## Phases
- **Phase A (Scaffolding):** Define the `/z-audit-plan` command and skill structures.
- **Phase B (Verification Logic):** Detail the Reality Check and Best Practices / Style Audit logic.
- **Phase C (Adversarial Consult):** Define the Gemini + Codex parallel adversarial review prompt and synthesis template.
- **Phase D (IDE Exports):** Register in the export configuration and execute multi-IDE export scripts.
