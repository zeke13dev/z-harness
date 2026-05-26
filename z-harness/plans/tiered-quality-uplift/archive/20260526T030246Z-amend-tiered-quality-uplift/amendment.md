# Amendment: apply PLAN_AUDIT_REPORT blockers + majors

**Run:** 20260526T030246Z-amend-tiered-quality-uplift
**Mode:** full
**Requested change:** apply all 4 blockers and all 8 majors from PLAN_AUDIT_REPORT.md. Minors deferred to in-task polish.

## What this affects

### SPEC.md
- L100–L102 (cross-cutting dispatch): rename `z-harness:gemini-consultant` → `consultant-primary`, `z-harness:codex-consultant` → `consultant-secondary`. Drop hardcoded Gemini/Codex labels.
- L121 (auditor dispatch): change `rubric: <STYLE.md content…>` to `rubric_path: <abs path to STYLE.md or empty>`.
- L123 (per-component consult): rename to `consultant-primary` / `consultant-secondary`.
- L126 (reviewer): rename to `reviewer`.
- L171–172 ("no new agents" list): align agent names.
- L31 (STYLE gate halt): append "After running `/z-style-init`, re-invoke `/z-uplift` to continue."
- L33 (Phase 1 AskUser): drop "edit-and-confirm" option; keep "proceed / abort". Add note "to revise: abort, edit COMPONENTS.md, re-invoke".
- L46 (`--dimensions` flag): inline rationale "perf excluded by default to bound cost".
- L101 (cross-cutting source map): define entry-file heuristic (README.md → src/lib.rs → src/main.rs → __init__.py → package.json → first non-test source by lexicographic order → component root).
- L194 + L196 (z-uplift.json reference): change schema anchor from implied z-audit.json to `docs/llm/style-init.json` / `docs/llm/z-update.json`.
- L209 (gotchas: text-grep dependents): note "labeled as 'potential / incomplete' in REPORT.md and MANIFEST.md".
- L217 (skill pattern): change "matching `skills/z-audit/SKILL.md`" → "matching `skills/z-improve/SKILL.md`".

### PLAN.md
- L4, L9, L23, L30: rename consultant agent names; drop hardcoded provider labels.
- Add `## Amendments` section at bottom recording this change.

### TASKS.md
- **New tasks:** none.
- **Modified tasks:**
  - T001: add STYLE halt resume instruction; surface `--dimensions` rationale at flag definition.
  - T002: drop "edit-and-confirm" AskUser option.
  - T003: replace JS regex with concrete bash path computation; rename consultant calls.
  - T004: rename consultant + reviewer calls; switch rubric injection to `rubric_path`; add text-grep dependents incomplete-labeling acceptance bullet; define entry-file heuristic (or reference SPEC).
  - T006: add `[i] implementing` resume branch acceptance bullet; add backup-before-delete for `--refresh-component`.
  - T008: retarget skill pattern from `skills/z-audit/SKILL.md` to `skills/z-improve/SKILL.md`; point schema anchor at `docs/llm/style-init.json` or `docs/llm/z-update.json`.
  - T010: remove auto-cleanup line; document manual cleanup.
- **Removed tasks:** none.
- **Touched-but-completed tasks:** none (all tasks `[ ]`).

### FIX.md
- N/A (full mode).

## Risk
- New external dependency: **no**.
- Public API / wire format / schema change: **no**.
- Cross-module impact: **no** — pure planning-artifact edits before implementation begins.
- Algorithm swap with materially different Big-O / memory: **no**.
- Persistence change: **no**.

**Consult required:** **No** — amendment is surgical (rename, doc clarifications, bug fixes in planning prose). Skip Phase 5.

## Re-classification of complexity

All modified tasks already exist at `medium` (T001, T002, T003, T005, T007, T008, T009, T010) or `high` (T004, T006). The amendment changes:
- T001, T002, T008, T010: documentation/clarity adjustments, no scope expansion → tier unchanged, **skip classifier**.
- T003: replaces pseudocode with concrete expression — clarifies, does not expand scope → tier unchanged, **skip classifier**.
- T004: adds two acceptance bullets (rubric_path, text-grep labeling) + rename — still high; classifier re-stamp not needed for narrowed clarity → **skip classifier**.
- T006: adds two acceptance bullets (resume branch + backup-before-delete) — still high → **skip classifier**.

Per the amend skill: re-classify only if a block changes in a way that materially shifts complexity. None of these do; skipping classifier and preserving stamps byte-for-byte.
