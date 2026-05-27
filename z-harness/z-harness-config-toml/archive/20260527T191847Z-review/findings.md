# Final review — z-harness-config-toml

- **Run:** 20260527T191847Z-review
- **Base ref:** HEAD (c5fa111) — all slice 1 work is uncommitted
- **Diff stats:** 58 files, +2224 / -489 lines (filtered, excluding archive/metrics noise)
- **Test status:** 45 unit tests passing (scripts/test_config.py)

## Prong A — Implementation drift

### Severity: blocker
None.

### Severity: major
- **[gemini] Stale `exports/`** — 140+ `Z_HARNESS_NOTIFY` references in `exports/agy`, `exports/codex`, `exports/cursor` (these are the canonical artifacts for cross-IDE distribution via Cursor/Codex/Antigravity, generated from SKILL.md sources). T009 cleaned the sources but didn't regenerate exports. **Fixed inline:** ran `scripts/export-{codex,cursor,agy}.py`. Verified `grep -rE 'Z_HARNESS_NOTIFY([^_]|$)' exports/` returns 0.

### Severity: minor
- **[codex] config.md intro polish** — `docs/human/config.md` intro uses bare `scripts/config.py export-env` while the CLI reference section correctly shows the full `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/config.py export-env` invocation. Cosmetic; not actionable.

## Prong B — Spec gaps

### Severity: blocker
None.

### Severity: major
None.

### Severity: minor
- Both consultants noted PLAN's slice-2 deferral (z-debug/z-implement-all/z-review-all migration) is correctly documented but recommend slice 2 prioritize it. Acknowledged in PLAN.md non-goals; no action.

## Consensus vs disagreement

**Both consultants flagged:**
- Slice 2 deferred items (z-debug, z-implement-all, z-review-all not yet migrated). Already documented.

**Only one flagged:**
- Gemini: stale `exports/` (real, fixed inline). Codex didn't surface this — likely scoped its review to source files, not generated artifacts.
- Codex: config.md intro polish. Gemini didn't surface; cosmetic.

## Pushback summary (one-reason-it-might-be-wrong)

- **Gemini's exports finding:** "Exports might be developer-only tooling, not user-facing" → CHECKED: exports/ is tracked in git, .gitignore comments confirm "canonical sources live under exports/". Real user-facing artifact. Accept and fix.
- **Codex's intro polish:** "Maybe consistency is required across all examples" → docs/human/config.md uses prose-style references in intro and exec-style in CLI reference; both readable. Reject as cosmetic.

## Verdict

**Slice 1 is clean to merge.** 0 blockers, 1 major fixed inline (exports regenerated), 1 minor declined as cosmetic.
