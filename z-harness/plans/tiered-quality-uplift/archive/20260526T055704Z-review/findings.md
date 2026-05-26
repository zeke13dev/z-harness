# Final review — tiered-quality-uplift

Run: 20260526T055704Z-review
Base ref: ddc52734a9a9ba10e0ae24e78f78d06807cce8e4 (Refresh z-harness docs)
Diff stats: 11,499 lines across commands/z-uplift.md (2,742 lines new), skills/z-uplift/SKILL.md, docs/llm/{INDEX.json,z-uplift.json,MEMORIES-FLAT.md}, docs/human/z-uplift.md, README.md, scripts/export-{cursor,codex}.py, and 6 export artifacts.

Consultants: gemini (consultant-primary) + codex (consultant-secondary), two-pronged.

## Prong A — Implementation drift

### Severity: blocker

**A-B1 (Codex only — verified).** Synthetic `<slug>-cross-cutting` row is stuck in `[ ] pending` forever.
- Evidence: Phase 2 Step 6 (commands/z-uplift.md:1523) inserts the synthetic row as `[ ] pending`. Phase 3 (line 1572) explicitly EXCLUDES rows ending in `-cross-cutting` from audit ("must not be re-audited here"). Phase 5 Step 1 (~line 12) only queues rows in `[a] audited` or `[i] implementing`. No phase transitions the synthetic row to `[a] audited`.
- Net: the global-task work is authored (hand-built TASKS.md) but never enters the implement queue. SPEC L139 + PLAN D6 require it run FIRST.
- Pushback: maybe Phase 5 implicitly accepts it? Verified — Step 1's queue filter is strict: `actionable = '[a] audited' in state or '[i] implementing' in state`. Not implicit.
- Why Gemini missed: Gemini verified the ordering rule but did not trace the state transition gap.
- Recommended fix: at end of Phase 2 Step 6 (after inserting the row), atomically transition state to `[a] audited`; or change Phase 5 Step 1 filter to accept `[ ] pending` for rows where `slug.endswith('-cross-cutting')`. Former is cleaner.

### Severity: major

**A-M1 (Codex only — verified).** Phase 2 Step 6 MANIFEST insertion is non-atomic.
- Evidence: commands/z-uplift.md:1545-1546 `with open(manifest_path, "w") as f: f.write(content)` — direct write bypasses the tmpfile + os.replace pattern used everywhere else (helper at ~line 1644, Phase 5 mutations at lines 2590+).
- Pushback: cross-cutting row is created exactly once per run; interruption window is narrow. True, but the orchestrator-wide invariant is "all MANIFEST writes atomic" — exception here is silent inconsistency.
- Fix: use the `manifest_write(path, content)` helper.

**A-M2 (Codex only — verified).** `CRIT_HIGH_COUNT` counts substring occurrences, not distinct findings.
- Evidence: commands/z-uplift.md:1892 `re.findall(r'\b(?:CRITICAL|HIGH)\b', text)` counts every match in the entire REPORT body. A finding saying "this is a HIGH severity issue with HIGH priority" counts as 2. The auto-bail threshold (`>10 CRIT-HIGH`) can fire on far fewer than 10 distinct findings.
- Pushback: REPORT.md severity tags are usually one per finding. But descriptive prose mentioning the words is realistic; the threshold's signal degrades with verbose findings.
- Fix: parse REPORT structurally (per-finding bullet/header), then count those with severity == CRITICAL or HIGH.

**A-M3 (both — already T004 Note).** Unguarded `git grep` searches the whole repo when OTHER_COMP_PATHS is empty.
- Evidence: commands/z-uplift.md:~1957 `git grep -l "$COMP_BASENAME" -- $OTHER_COMP_PATHS` — empty `OTHER_COMP_PATHS` collapses `--` and triggers a full-repo scan, yielding false positives in the "text-grep dependents" list.
- Already filed in TASKS.md T004 deferred Note. Promote to fix.

**A-M4 (both — already T002 Note).** N-way collision handling incomplete + custom-slug re-validation missing.
- Evidence: Phase 1 Step 2 (~line 895) resolves pairwise collisions but doesn't loop for N>2 cases (`foo/`, `bar/foo/`, `baz/foo/`); user-introduced custom slugs are not re-validated against `to_slug()` regex nor re-collision-checked before MANIFEST write.
- Already filed in T002 deferred Note. Promote to fix.

**A-M5 (both — already T003 Note).** Cross-cutting parser regex assumes G-/C-/R- prefix; findings without the prefix are dropped.
- Evidence: commands/z-uplift.md:~1271 split regex only matches `G-NNN | C-NNN | R-NNN` bullets. Real consultant output varies. SPEC does not mandate a strict machine-readable format.
- Already filed in T003 deferred Note. Promote to fix + tighten SPEC.

### Severity: minor

**A-mi1 (Codex).** Export-script collision fix is scope-limited to skill/command pairs.
- Evidence: scripts/export-cursor.py / export-codex.py append `-skill` suffix only when a skill ID collides with a command ID. Agent/command and agent/skill collisions (all kinds share `.cursor/rules/<id>.mdc` namespace) are not handled.
- Pushback: no such collisions exist today.
- Recommendation: document the scope, or generalize.

## Prong B — Spec gaps

### Severity: major

**B-M1 (Gemini).** Phase 4 informational summary doesn't surface the cross-cutting-first ordering.
- Evidence: Phase 4 (commands/z-uplift.md:~2333) prints component counts and bailed components but doesn't note that the synthetic `<slug>-cross-cutting` will be implemented FIRST per SPEC L139.
- Pushback: experienced users know the rule. Worth a one-line callout for new users.
- Fix: amend SPEC + add a line in Phase 4 summary code.

### Severity: minor

**B-mi1 (Gemini).** SPEC underspecifies the auditor-output format (F-/C-/P-/D- finding-ID convention).
- Pushback: implicit by linking to /z-audit.
- Fix: amend SPEC to spell out the format the auditor is expected to emit, so the parser contract is documented.

## Consensus vs disagreement

**Both LLMs flagged (high confidence):**
- A-M3 (git grep unbounded scope)
- A-M4 (N-way collision + custom-slug validation)
- A-M5 (cross-cutting parser prefix assumption)
- Three of these match deferred Notes on T002/T003/T004 — review independently confirms those were not edge-case fluff.

**Codex only (verified by orchestrator):**
- A-B1 BLOCKER (cross-cutting state lifecycle)
- A-M1 (non-atomic MANIFEST insert)
- A-M2 (CRIT_HIGH_COUNT substring counting)
- A-mi1 (export-collision scope)

**Gemini only:**
- B-M1 (Phase 4 summary clarity)
- B-mi1 (SPEC auditor-output format)

**Both verified CLEAN:**
- SKIP_TO_PHASE phase-guard correctness across all phases
- STYLE.md gate halt instruction shape
- Exact-slug context-injection match
- Phase 5 two-step handoff (correctly per SPEC's documented framework constraint)
- Export-collision fix (apart from the scope-limit note)

## Verdict

NOT shippable in current state. 1 BLOCKER + 5 MAJOR require fixes before the smoke test (T010) is meaningful — particularly A-B1 (cross-cutting state) since the smoke test command `/z-uplift --no-style --cross-cutting=skip --component scripts` deliberately skips cross-cutting, so the bug would not surface in T010 anyway.

Estimated remediation: ~10–15 hrs for blocker + 5 majors + 2 minors. Single follow-up batch via `/z-implement-all --tasks=z-harness/plans/tiered-quality-uplift/REVIEW-TASKS.md`.
