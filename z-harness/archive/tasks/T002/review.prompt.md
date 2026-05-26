You are reviewing code that Claude just wrote for task T002: Implement Phase 1 (decomposition): polyglot detection + COMPONENTS.md + AskUser gate.

This is ROUND v2 — focus on whether the prior v1 findings were addressed. Do NOT re-flag v1 issues outside the delta; only flag NEW issues or if v1 fixes are incomplete/incorrect.

Prior v1 findings (2 blockers + 8 majors):
- B1. --components=<file> parsing prose-only, missing executable code.
- B2. Slug collision handling prose-only, never mutates COMPONENTS_JSON before COMPONENTS.md write.
- M1. --components=<file> silently drops --component extras; must merge with de-dup.
- M2. Unclaimed classification used bool(components), should use MANIFEST_EXISTS check.
- M3. --component <path> may duplicate into Unclaimed.
- M4. No cross-method de-dup (Cargo + package.json claiming same path → 2 rows).
- M5. Poetry parsing ignores `from` field.
- M6. setup.cfg skips `packages = find:` form.
- M7. EXTRA_COMPONENTS uninitialized under set -u.
- M8. Telemetry check=False silently swallows failures.

Spec excerpt:
- Component detection (L71-95): Five-step detection order (Cargo, pyproject, setup.cfg, package.json, top-level dirs); unclaimed set for dirs not covered by steps 1-4; slug collision check with AskUser gate.
- Phase 1 Step 1 (L142-160): Parse --components=<file> newline-delimited, skip blank/comment lines; honors --component <path> overrides; collision detection before COMPONENTS.md write.

Acceptance criteria:
- Phase 1 heredoc produces COMPONENTS.md with top-level dirs.
- Slug collisions trigger AskUser.
- CLI override flags work.

Delta (v2 patch against v1):
Lines 7-38: EXTRA_COMPONENTS initialization + bash arg parser for all flags (addresses M7, M1 header)
Lines 50-96: Executable Python heredoc for --components=<file> reading + de-dup with EXTRA_COMPONENTS (addresses B1, M1)
Lines 98-179: Auto-detection Python block:
  - MANIFEST_FILES constant + MANIFEST_EXISTS precompute (addresses M2)
  - detected_by_path dict for cross-method de-dup (addresses M4)
  - Poetry from+include resolution (addresses M5)
  - setup.cfg find: support (addresses M6)
  - Manual path tracking to exclude from unclaimed (addresses M3)
Lines 305-392: Executable Python heredoc for collision detection + resolution (addresses B2)
Lines 406-408: Telemetry with returncode check + stderr warning (addresses M8)

Review scope:
1. Are the v1 fixes actually present and correct in the delta?
2. Are there new blockers introduced by the patch?
3. Are there correctness issues in the v2 implementations?
4. Edge cases / error handling gaps in the new code.

Scrutinize strictly. Focus only on:
- Blockers (breaks acceptance criteria or spec)
- Major issues (serious correctness bug or missing error handling)

Do NOT list minors/nits unless they hide a correctness bug.
