# Amendment: apply 9 audit must-fix items + 5 minor cleanups

**Mode:** full
**Source:** PLAN_AUDIT_REPORT.md (2 BLOCKERS, 7 MAJORS).
**Pre-approved:** user selected "/z-amend with the 9 must-fix items (recommended)" via the audit gate; no further Phase-4 confirmation needed.

## What this affects

### SPEC.md
- Tri-state → binary for `docs.always_apply` (drop "auto").
- Add `export Z_HARNESS_RUN="$RUN"` to §"File 7" and §"File 8" setup snippets.
- §"export-env": META_KEYS exclusion for `schema_version`.
- §"Edge cases": drop /z-update claim; replace with manual invocation guidance.
- §"Behavioral invariants": subagents must not re-invoke export-env.
- §"export-env" transliteration: regex key-format validation.
- Find/replace `$PLUGIN_ROOT` shorthand → `${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}`.
- §"Layered validation rules" cleanup of any residual contradictions.

### PLAN.md
- Update D7 line: `"always" | "never"`, default `"always"`.
- Phase 7 review section: note the post-audit changes (binary enum, RUN export, META_KEYS, /z-update drop).
- Non-goals: add slice-2 mandate "auto-generate config.md knobs table before adding 3rd knob."

### TASKS.md
- **Modified:** T001 (re-sequencing prose), T002 (META_KEYS, regex validation, RUN env), T005 (expanded matrix), T006 (both files + pre-flight + RUN export + binary enum), T007 (both files + pre-flight + RUN export), T008 (XDG isolation + payload assertions + env-shadows-repo).
- **New:** T009 — mechanical prose pass for Z_HARNESS_NOTIFY refs in non-migrated commands. Complexity: low. Depends: T002, T003.
- **Re-sequence:** PR1 = T001+T002+T003+T004+T005; PR2 = T006+T007+T008+T009.
- **Removed:** none.
- **Touched-but-completed:** none (no [x] tasks).

## Risk
None of the consult triggers fire: no new external dep, no public API change beyond original plan (binary vs tri-state is a value-set tightening), no schema change to existing systems, no algorithm swap. **Skip Phase 5 consult.**
