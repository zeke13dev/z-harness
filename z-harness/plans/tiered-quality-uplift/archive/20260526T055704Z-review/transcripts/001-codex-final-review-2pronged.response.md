## Codex consultation: `/z-uplift` Final Review — Critical Issues Found

**Recommendation:** Do not ship `/z-uplift` in current state. One BLOCKER and six MAJOR issues must be resolved. BLOCKER is a logic gap that breaks D6 (process cross-cutting first). The MAJORs are real deferred items from the task notes.

**Reasoning:**

Codex performed targeted code inspection on commands/z-uplift.md (2742 lines), scripts, and docs. Key findings:

1. **BLOCKER — Cross-cutting row never implemented (Prong A, commands/z-uplift.md:1523,1572,2374):** Phase 2 creates the synthetic `-cross-cutting` row in state `[ ] pending`. Phase 3 explicitly excludes it from audit loop. Phase 5 only queues rows in `[a] audited` or `[i] implementing` state. Result: the global-task work is created but never entered the implement queue, violating PLAN D6 ("synthetic `-cross-cutting` is processed FIRST in Phase 5"). Either:
   - Insert the synthetic row as `[a] audited` after Phase 2 completes, OR
   - Modify Phase 5 Step 1 queue builder to explicitly include pending rows where `component.endswith("-cross-cutting")` or `slug == "(global)"`.

2. **MAJOR — MANIFEST atomic write inconsistency (Prong A, commands/z-uplift.md:1545):** Cross-cutting row insertion writes `MANIFEST.md` directly: `with open(..., "w") as f: f.write(content)`. Every other MANIFEST mutation uses `tmpfile + os.replace` for atomic writes. This can corrupt MANIFEST on interrupt mid-write, breaking resume authority. Use the same `manifest_write(path, content)` helper defined at line 1644.

3. **MAJOR — CRIT_HIGH_COUNT logic (Prong A, commands/z-uplift.md:1892):** Counts string occurrences of `CRITICAL` or `HIGH` in the entire report. A single finding mentioning "HIGH" twice triggers bail. Should count distinct findings whose severity field is CRITICAL or HIGH, not substring matches. Recommend: parse REPORT.md finding structure and count severity-matched entries.

4. **MAJOR — Unguarded git grep scope (Prong A, commands/z-uplift.md:1957):** `git grep -l "$COMP_BASENAME" -- $OTHER_COMP_PATHS` is unguarded. If `OTHER_COMP_PATHS` is empty, `git grep ... --` searches the whole repo, not "other components." Can report current component or unrelated files as dependents. Deferred T004 note confirmed real. Guard with `if [ -n "$OTHER_COMP_PATHS" ]; then ...`.

5. **MAJOR — N-way collision handling incomplete (Prong A, commands/z-uplift.md:895):** Collision resolution only handles pairwise collisions (first two sorted components). For three colliding basenames, the third retains original slug. Custom user choices are not re-collision-checked before MANIFEST write. Deferred T002 note confirmed real. Recommend: loop until no collisions remain, validate custom slugs against full set, fail before MANIFEST write if duplicates remain.

6. **MAJOR — Cross-cutting parser regex fragility (Prong B, commands/z-uplift.md:1271):** Parser only accepts bullet lines starting with `G-NNN`, `C-NNN`, or `R-NNN`. Findings without exact prefix are silently dropped. SPEC does not mandate strict machine-readable output format from consultants. Deferred T003 note confirmed real. Recommend: update SPEC acceptance criteria to require structured JSON output from cross-cutting consultants, emit parse-error report on unparseable findings, and add a retry/review gate.

7. **MINOR — Export collision scope (Prong A, scripts/export-cursor.py:190, export-codex.py:244):** Skill/command collision fix is correct and prevents overwrite. Does not extend to agent/command or agent/skill collisions in Cursor (all kinds share `.cursor/rules/{id}.mdc`). Low risk today (no known collisions), but edge case. Recommend: document collision scope in export scripts or generalize ID allocation by kind.

**Tradeoffs / risks flagged:**

- Fixing BLOCKER requires design choice: should synthetic cross-cutting row be audited (and generate REPORT/TASKS), or pre-audited (hand-written from CROSS-CUTTING.md)? SPEC says hand-written but doesn't set state. Current code does hand-written + `[ ] pending`, which loses the row.
- CRIT_HIGH_COUNT fix changes bail threshold semantics; may result in different components bailing. Recommend updating acceptance test to verify counts match real findings.
- N-way collision support is complex; simple fix is to error on >2 collisions with "pass `--components=<file>` to override."
- Cross-cutting parser rework is moderate scope: requires consultant prompt alignment + parse error handling.

**Additional considerations Codex raised:**

- Phase-skip guards (SKIP_TO_PHASE) are correctly implemented and consistent.
- MANIFEST atomic-write pattern is sound everywhere except the one cross-cutting insertion.
- Resume detection logic (phase3_pending / phase5_implementing / phase5_ready branches) is correct.
- Telemetry events are comprehensively wired (phase_end, component_* events, run_end).
- Rubric_path injection (not inline) is correctly specified and avoids large prompt bloat.
- Exports collision fix is a real bug that was fixed correctly.

**Bottom line:** Implementation is >90% faithful but has one logic-flow blocker and six deferred items that are now confirmed real. Address the BLOCKER before any user-facing run. Schedule T002/T003/T004 follow-up tasks to fix the MAJORs.

Estimated effort: BLOCKER (1–2 hr design + code), MAJOR 2/4/5 (2 hr each), MAJOR 3 (3 hr), MAJOR 6 (4 hr). Total ~15 hrs remediation.
