---
artifact: review-tasks
slug: memory-self-improve-loop
run_id: 20260526T002218Z-review
source_findings: archive/20260526T002218Z-review/findings.md
drift_findings: 6
spec_gap_findings: 5
escalations: 0
---

# Review Tasks — memory-self-improve-loop

Findings promoted from `/z-review-all`. Delete any candidate you do not want fixed, then run:

`/z-implement-all --tasks z-harness/plans/memory-self-improve-loop/REVIEW-TASKS.md`

## Candidate fixup tasks

### [ ] T-REV-001 — [blocker] Align Phase 9 `phase_end` shape with Phase 7
- **Class:** implementation_drift
- **Source:** Prong A blocker; both consultants; `commands/z-implement-all.md:773` vs `commands/z-review-all.md:447`
- **Pushback:** `/z-stats` may tolerate the divergent shape today; this is a contract bug, not a runtime crash.
- **Files:** `commands/z-implement-all.md` (line 773 phase_end payload), `skills/z-implement-all/SKILL.md` (mirror)
- **Depends on:** none
- **Acceptance:** Phase 9 final `phase_end` emits the same key set as Phase 7: `phase, name, wall_ms, accepted, edited, skipped, candidates_emitted` (renaming `candidates_accepted` → `accepted`, `candidates_skipped` → `skipped`, adding `wall_ms` and `edited`). Skill mirror updated. Grep for the new payload in both files matches; no remaining `candidates_accepted` / `candidates_skipped` references inside Phase 9.

### [ ] T-REV-002 — [major] Add bash snippet for `review_agent_suggest_failed` in Phase 7
- **Class:** implementation_drift
- **Source:** Prong A major; codex; `commands/z-review-all.md:434-437`
- **Pushback:** prose may be intentionally terse since z-implement-all has the full pattern 60 lines away — but a forked skill loses that cross-reference.
- **Files:** `commands/z-review-all.md`, `skills/z-review-all/SKILL.md`
- **Depends on:** none
- **Acceptance:** Phase 7 Accept-path bash includes an inline `bash "${ANTIGRAVITY_PLUGIN_ROOT…}/scripts/log-event.sh" "$RRUN" review_agent_suggest_failed '{…}'` snippet matching the structure used in `commands/z-implement-all.md:748`. Skill mirror updated.

### [ ] T-REV-003 — [major] Backfill event-kind reference table in Phase 9
- **Class:** implementation_drift
- **Source:** Prong A major; both consultants; `commands/z-implement-all.md:777-787`
- **Pushback:** events are visible in the code body above; table may be intended as quick-reference.
- **Files:** `commands/z-implement-all.md`, `skills/z-implement-all/SKILL.md`
- **Depends on:** none
- **Acceptance:** the event-kind table in `commands/z-implement-all.md` Phase 9 lists `review_agent_suggest_failed` and `review_candidate_skipped` (matching z-review-all Phase 7's table at line 454-460). Skill mirror updated.

### [ ] T-REV-004 — [major] Make hardcoded `index_path` absolute
- **Class:** implementation_drift
- **Source:** Prong A major; gemini; `commands/z-implement-all.md:642` + `commands/z-review-all.md:407`
- **Pushback:** orchestrator always runs from repo root; real failure risk is near-zero. Mostly a contract-hygiene fix.
- **Files:** `commands/z-implement-all.md`, `commands/z-review-all.md`, plus skill mirrors
- **Depends on:** none
- **Acceptance:** both command files dispatch the agent with `index_path: $(pwd)/docs/llm/INDEX.json` (or `$REPO_ROOT/docs/llm/INDEX.json` derived once at Setup). Skill mirrors updated.

### [ ] T-REV-005 — [minor] Add `review-agent` row to README Subagents table
- **Class:** implementation_drift
- **Source:** Prong A minor; codex; `README.md:73-83`; SPEC.md:194 explicitly called for it.
- **Pushback:** none — straightforward one-line edit.
- **Files:** `README.md`
- **Depends on:** none
- **Acceptance:** Subagents table includes a row for `review-agent` naming the Haiku tier and one-line description matching `agents/review-agent.md` frontmatter.

## Amendment proposals

### [ ] T-REV-006 — [major] Amend SPEC: add `index_path` to caller-input contract
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong A/B major; both consultants; `z-harness/plans/memory-self-improve-loop/SPEC.md:48-53`
- **Pushback:** could alternatively be classified as a SPEC amendment from T003's reviewer cycle that should have been logged as an in-flight SPEC patch. Either framing produces the same fix.
- **Files:** `z-harness/plans/memory-self-improve-loop/SPEC.md`
- **Depends on:** none
- **Acceptance:** run `/z-amend "Add index_path: absolute path to docs/llm/INDEX.json as the 7th caller-input field in the agent contract; update Procedure step 1 to reference it; note that the agent must enumerate existing concept slugs from index_path before suggesting a new slug."`; resulting SPEC reflects the amendment and PLAN.md/TASKS.md remain consistent.

### [ ] T-REV-007 — [major] Amend SPEC: pin down `--from-candidate-json` phase boundaries
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B major; both consultants; `z-harness/plans/memory-self-improve-loop/SPEC.md:158-159`
- **Pushback:** detail already lives in `skills/z-suggest-memory/SKILL.md` (T002+T009); SPEC could just cross-reference.
- **Files:** `z-harness/plans/memory-self-improve-loop/SPEC.md`
- **Depends on:** none
- **Acceptance:** run `/z-amend "Specify --from-candidate-json contract: bypasses /z-suggest-memory Phases 3a-3f, runs Phase 4 (validation) through Phase 6 (MEMORIES-FLAT regen); concept slug is inferred from candidate's suggested_concept_slug field (--concept flag optional); source prefix incident:<RUN_ID> per T009."`; SPEC updated, PLAN unchanged.

### [ ] T-REV-008 — [minor] Amend SPEC: clarify `all_tasks_skipped` naming
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B minor; codex; `z-harness/plans/memory-self-improve-loop/SPEC.md:98-102`
- **Pushback:** in practice unambiguous since Phase 9 runs at run-end; pure naming nit.
- **Files:** `z-harness/plans/memory-self-improve-loop/SPEC.md`
- **Depends on:** none
- **Acceptance:** run `/z-amend "Rename all_tasks_skipped to no_tasks_completed (or add a one-sentence clarification) so the skip-reason name matches what scripts/run-memory-review.sh actually detects (zero [x] in TASKS.md, regardless of whether the run is fresh or user-skipped). Update scripts/run-memory-review.sh STATUS string to match."`; SPEC + script aligned.

### [ ] T-REV-009 — [minor] Amend SPEC: add v1 limitations section
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B minor; gemini; SPEC.md introduction
- **Pushback:** PLAN.md has it; SPEC ↔ PLAN cross-reference is the harness norm.
- **Files:** `z-harness/plans/memory-self-improve-loop/SPEC.md`
- **Depends on:** none
- **Acceptance:** run `/z-amend "Add a 'v1 limitations / non-goals' section to SPEC.md mirroring PLAN.md's Non-goals (v1) + Approved shortcuts list, so the spec is self-contained for future v2 amendment writers."`; SPEC includes the limitations list.

## Superseding tasks

None — no completed task contradicts another at the implementation level (the divergences are between files within tasks, not across superseded tasks).

## Escalations

None. No premise failures; both consultants confirm the design holds end-to-end.

## Report-only observations

- **[codex Prong B major, deferred]** `review_agent_suggest_failed` is not enumerated in SPEC's failure-mode section. Defensible to leave as observation: it's a downstream `/z-suggest-memory` error mode that's outside this plan's contract surface. Reconsider if v2 expands the failure-handling surface.
- **[codex Prong B minor, deferred]** `edited` counter increment-point is unspecified in SPEC. v1 metric is descriptive; tightening this is over-engineering until empirical use reveals confusion.
- **[gemini Prong A minor, deferred]** Edit UX field-by-field surface is one sentence in SPEC. Sufficient for the AskUserQuestion-constrained surface today; revisit on first user complaint.
