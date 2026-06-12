---
artifact: review-tasks
slug: z-harness-parallelism
run_id: 20260612T211949Z-review
source_findings: archive/20260612T211949Z-review/findings.md
drift_findings: 1
spec_gap_findings: 3
escalations: 0
---

# Review Tasks — z-harness-parallelism

Final review (`/z-review-all`) returned **0 blockers, 0 majors** — both Gemini and Codex APPROVE.
The candidates below are all **minor / optional** (docs, one clarifying test, one belt-and-suspenders
hardening). None gate shipping. Delete any you don't want, then:

`/z-implement-all --tasks plans/z-harness-parallelism/REVIEW-TASKS.md`

## Candidate fixup tasks

### [ ] T-REV-001 — [minor] Explicit gc.auto=0 on the concurrent merge path
- **Class:** implementation_drift
- **Disposition:** candidate_task
- **Source:** Prong A; gemini; "gc.auto not set in spawn env (SPEC D3 wording)"
- **Pushback:** Already mitigated — `GIT_OPTIONAL_LOCKS=0` plus never invoking `git gc` covers the index.lock hazard (documented at scripts/hermes-execute.py:617-621). This is belt-and-suspenders, not a correctness fix.
- **Files:** `scripts/hermes/merge.py` (add `-c gc.auto=0` to the `git merge` invocation) or `scripts/hermes-execute.py`
- **Depends on:** none
- **Acceptance:** the concurrent merge runs with `gc.auto=0` in effect; existing merge tests stay green.

### [ ] T-REV-002 — [minor] Clarifying test: per-level partition isolation
- **Class:** implementation_drift (test gap)
- **Disposition:** candidate_task
- **Source:** Prong B; codex; "B4 — no test of cross-level partition isolation"
- **Pushback:** Safe by construction — `partition_level` runs per ready-level and INV-2 (`depends_on`) drives eligibility, so no cross-level conflict state is needed. The test clarifies intent for future maintainers; it cannot catch a current bug.
- **Files:** `tests/test_hermes_execute.py`
- **Depends on:** none
- **Acceptance:** a test shows a ws separated from a HIGH peer at level N can co-batch with a different peer at level N+1, and asserts the per-level partition makes no cross-level coercion.

## Amendment proposals

### [ ] T-REV-003 — [minor] Document the scope_unknown serialization cliff + non-file-resource caveat
- **Class:** spec_gap
- **Disposition:** amendment_proposal
- **Source:** Prong B; codex; "B2 (one missing **Files:** line → full serialization) + B3 (path-based matching of logical resources)"
- **Pushback:** Both are the safe failure direction (over-serialize, never mis-parallelize); arguably the existing hermes-integration-v1.md non-file-shared-state note already covers B3. Low value.
- **Files:** `plans/z-harness-parallelism/SPEC.md`, `docs/human/hermes-integration-v1.md`
- **Depends on:** none
- **Acceptance:** run `/z-amend "document that any task lacking a parseable **Files:** line sets scope_unknown=true ⇒ fully-serial execution, and that file-conflict matching is path-string based so logical resources (DB URLs/ports) should use serialize_all"`; SPEC/docs reflect the caveat; completed-task state preserved.

## Escalations
None.

## Report-only observations
- B1 (blocked workstreams in final summary) — REFUTED: already printed at `scripts/hermes-execute.py:691-692`. No action.
- Plan-claim TTL expiry mid-run (gemini/codex both noted) — out of scope; governed by `plan-claim.sh`'s own TTL contract, not this layer.
