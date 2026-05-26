# TASKS — z-audit-plan

Status legend: `[ ]` pending · `[~]` in_progress · `[x]` done.

### [ ] T001 — Create core command commands/z-audit-plan.md
- **Context:** Design the full `/z-audit-plan` command workflow, including reality check, best practices audit, adversarial consultant dispatch, synthesis, and user gate.
- **Files:** `commands/z-audit-plan.md` (new).
- **Acceptance:** Valid YAML frontmatter description and argument hint. Complete detailed markdown body containing all phases (Phase 0 Setup, Phase 1 Reality Check, Phase 2 Design Check, Phase 3 Adversarial Review, Phase 4 Synthesis, Phase 5 User Gate).
- **Complexity:** medium

### [ ] T002 — Create workspace skill skills/z-audit-plan/SKILL.md
- **Context:** Package the `/z-audit-plan` command as a reusable workspace skill.
- **Files:** `skills/z-audit-plan/SKILL.md` (new).
- **Acceptance:** Valid skill frontmatter with `name: z-audit-plan` and description. Identical markdown body to `commands/z-audit-plan.md`.
- **Complexity:** low

### [ ] T003 — Update commands/z-plan.md recommendations
- **Context:** Suggest running `/z-audit-plan` at the end of a successful planning phase.
- **Files:** `commands/z-plan.md` (modified).
- **Acceptance:** Add `/z-audit-plan` recommendation in Phase 9 block.
- **Complexity:** low

### [ ] T004 — Register in agy-plugin.yaml configuration
- **Context:** Register the new command and skill in the export manifest.
- **Files:** `exports/agy/agy-plugin.yaml` (modified).
- **Acceptance:** Entry added to `workflows` (id `z-audit-plan`) and `skills` (id `z-audit-plan`) with correct source/output paths and descriptions.
- **Complexity:** low

### [ ] T005 — Run export scripts and verify
- **Context:** Run the export scripts to generate output for cursor, codex, and agy, and verify all generated rules/workflows pass validation.
- **Files:** None (verify only).
- **Acceptance:** Commands `python3 scripts/export-agy.py`, `python3 scripts/export-cursor.py`, and `python3 scripts/export-codex.py` execute successfully and all files pass validation with no errors.
- **Complexity:** low
