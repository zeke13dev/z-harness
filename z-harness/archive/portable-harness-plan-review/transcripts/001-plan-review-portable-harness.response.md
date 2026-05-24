Gemini Plan-Review Critique

**Drift & Contradictions**
- Legacy Removal: SPEC lists "legacy removal in this plan" as a non-goal (line 198), but PLAN Phase 5 says "delete legacy" and context notes "legacy agent shims are ripped" is locked. SPEC non-goals must be updated to remove this contradiction.
- ENV Overrides: SPEC mandates `Z_HARNESS_PLANS_DIR` override (edge case, line 187). PLAN Phase 1 (`plan-path.sh`) fails to mention environment variable support.
- Update Safety: SPEC lists `/z-update` with uncommitted changes as an edge case (line 188). PLAN Phase 8 fails to include the git-tree cleanliness check prior to pulling/swapping.
- Discovery script language drift: SPEC appears to imply Python (`discover-providers.sh` as deterministic shell, line 108), but PLAN Phase 4 & D7 are clear on shell. Verify SPEC doesn't mention Python elsewhere for discovery.

**Ordering Risks (Critical)**
- Phase 6 (Agy Research) happens too late: Researching target IDE schemas (Agy) in Phase 6 *after* locking in the canonical agent rewrites in Phase 5 risks rework. If Agy requires specific prompt boundaries or metadata, Phase 5 will need to be redone. Move P6 *before* P5.
- Phase 6 scope missing Cursor/Codex coverage: Phase 6 specifically calls out Agy research, but assumes Cursor and Codex CLI shapes are fully known. If they are not, research for *all* export targets must block P7.
- Export Drift: Phase 7 builds the export pipeline, but Phase 8 (`bundle-plugin.sh` / `/z-update`) does not explicitly hook it. The export step must be a hard dependency of the build/update scripts, or IDE adapters will silently drift from Claude Code source-of-truth.
- Double-touching files (Phase 2 & Phase 5): Phase 2 sweeps all commands to update path logic. Phase 5 sweeps all commands *again* to update agent dispatch names. Combine sweeps to modify command files once.
- Tarball pollution (Phase 7 before Phase 8): Phase 7 generates `exports/` tree. Phase 8 creates distribution tarball. SPEC's exclude list for `bundle-plugin.sh` (line 153) does not explicitly exclude `exports/` folder. If Phase 8 runs after Phase 7, target-specific IDE adapters will leak into the canonical tarball.

**Implementation Fragility (KISS / Edge Cases)**
- Bash JSON Parsing (Phase 3/4): Implementing "precedence per-key, not whole-file merge" for `providers.json` via shell (`resolve-provider.sh`) is notoriously fragile without tooling. Hard-require `jq` or rewrite as Python (reuse pattern from `extract-dismissals.py`). SPEC line 74 mandates per-key precedence; PLAN Phase 3 omits this complexity.
- Missing distinct-provider invariant enforcement: SPEC (line 190) forbids `consultant-primary` and `consultant-secondary` from resolving to the same provider. PLAN Phase 3 completely omits the pre-flight check in `resolve-provider.sh`.
- Role Fallback Logic (Phase 5): SPEC lists "unbound roles" as an edge case (line 185). If `consultant-secondary.md` is requested but no secondary provider is configured, does the dispatch fail-fast or fallback to primary? PLAN Phase 5 needs an explicit fallback strategy.
- In-flight `TASKS.md` crash: While `migrate-plan-layout.sh` migrates directories, deleting legacy agent files immediately (Phase 5) will hard-fail if in-flight plans' `TASKS.md` explicitly instruct calling `codex-consultant` or `gemini-consultant`. Need a grace period or explicit per-TASKS-version note.
- Dual-read warning spam: SPEC states dual-read fallback emits a warning (line 23). Without a run-level state check, every single command invocation in a legacy plan will spam the migration warning. Add run-start de-duplication or per-command silence flag.
- Dual-read scope (Phase 1 vs Phase 5): If legacy shims are ripped (P5), but dual-read fallback is kept for paths (P1), ensure dual-read logic explicitly *only* applies to plan data directories, not agent execution paths, to avoid masking "missing agent" errors.

**Missing Coverage**
- Missing export lint script: SPEC requires automated export filter audit to block bad tarballs (line 189: exclusion rules). PLAN Phase 7/8 omits this requirement. Add audit step that rejects any export tar including `providers.json`, `.z-harness/`, `z-harness/plans/`, `z-harness/archive/`, or `~/` patterns.
- `/z-update` dirty-tree check: SPEC mandates git-tree cleanliness check before pull/swap (line 188). PLAN Phase 8 misses this detail.
- Smoke-test scope clarification: Phase 7 states "at least one command + one agent verified to load by hand in target IDE" (SPEC line 140). What counts as "verified to load"? Does it include sub-agent dispatch? Does it test that exported commands can actually *run* in the target IDE, or just syntax validity? Define acceptance criteria.
- Tarball versioning key: SPEC mentions `scripts/version.sh` includes build-time short SHA (line 159). PLAN Phase 8 doesn't specify how tarball versioning is keyed — git tag? Contents hash? This affects `/z-update` atomic swap logic.
- Shadowing UX: SPEC says shadowing emits `provider_shadowed` event (line 74, 82). What is the **user-visible** output? Is it just event log, or stdout warning? Does shadowing halt the command or only warn?

**DRY / KISS / SOLID Violations**
- Export Script Duplication: Each of the three export adapters (`export-cursor.py`, `export-codex.py`, `export-agy.py`) will likely duplicate file enumeration and CAPABILITIES.md schema logic. SPEC mentions `scripts/export-common.sh` (line 173), but Phase 7 doesn't explicitly define what goes in there (e.g., shared functions for path enumeration, schema validation, exclusion audit).

**Summary of Pre-Implementation Fixes**
1. Move Phase 6 (agy research) *before* Phase 5 (consultant rewrites).
2. Combine Phase 2 + Phase 5 sweeps to avoid double-touching command files.
3. Update SPEC non-goals to remove legacy-removal (it's now a goal per user override, line 198).
4. Add Phase 1 implementation details: `Z_HARNESS_PLANS_DIR` override support in `plan-path.sh`.
5. Add Phase 3 implementation details: per-key JSON merge with `jq`, distinct-provider pre-flight check in `resolve-provider.sh`.
6. Add Phase 8 implementation details: git-tree cleanliness check, tarball versioning logic, installation-mode detection (symlink vs tarball).
7. Add Phase 7/8: automated export filter audit lint script.
8. Clarify Phase 5 fallback strategy for unbound secondary provider.
9. Clarify Phase 1 dual-read: apply only to plan data dirs, not agent paths. Add run-start warning de-duplication.
10. Clarify Phase 7 smoke-test acceptance criteria (syntax vs runtime, sub-agent dispatch coverage).
11. Document shadowing UX: stdout warning or silent? Halt or warn-only?
12. Explicitly exclude `exports/` tree from Phase 8 tarball (or document why it should be included).
