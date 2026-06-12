# Final review — z-harness-parallelism
Run: 20260612T211949Z-review
Base ref: HEAD (562518a) — all parallelism work uncommitted in working tree
Diff stats: 7 modified files (+1168/-297) + 6 new files (cross_plan.py, hermes-orchestration.json, 4 test modules)
Consultants: consultant-primary (Gemini), consultant-secondary (Codex) — both two-pronged

## Verdict: PASS — 0 blockers, 0 majors. Both LLMs independently APPROVE.

Per-invariant verification was consensus-CLEAN across both reviewers:
- INV-5 / audit-M1: Semaphore held for the FULL `run_workstream` lifetime (verified: `async with sem:` wraps the whole call; merge happens inside while held) — `test_semaphore_cap2_peak_never_exceeds_2` asserts peak ≤ cap.
- T013: merge mutex is ONE shared `asyncio.Lock` (object identity) created in `run_cross_plan`, threaded to every `run_single_plan` — verified by identity test.
- INV-6: sorted-order lock acquisition (`sorted(slugs)`), release-all-on-failure in reverse.
- INV-4: `scope_unknown` / low-confidence / missing-record force serialization (within-plan singleton batches; cross-plan edges-to-all).
- INV-2: `depends_on` is the sole scheduling gate; `parallel_group` never read for scheduling.
- INV-5: cap=1 reproduces legacy sequential order (`test_cap1_parity_sequential`, `test_cap1_equals_cap3_tree`).
- GIT_OPTIONAL_LOCKS env save/restore handles the was-unset case in a `finally`.

## Prong A — Implementation drift

### blocker / major
None.

### minor
- **[gemini] gc.auto not explicitly set.** SPEC D3 says "disable concurrent git auto-gc"; the code sets `GIT_OPTIONAL_LOCKS=0` and relies on never invoking `git gc` (documented at hermes-execute.py:617-621). **Pushback:** this is an intentional, documented design choice and the concurrency hazard (index.lock contention) is already covered by `GIT_OPTIONAL_LOCKS=0`; an explicit `-c gc.auto=0` on the merge invocation would be belt-and-suspenders, not a correctness fix. Disposition: candidate hardening task (optional).

## Prong B — Spec gaps

### blocker / major
None.

### minor
- **[codex] B1 — blocked workstreams in final summary.** REFUTED on verification: `hermes-execute.py:691-692` already prints `Blocked (dependency failed): {blocked}` and the exit code (707) accounts for blocked. No action. (report-only)
- **[codex] B2 — single missing `**Files:**` line serializes the whole plan.** Correct fail-safe behavior (INV-4) but undocumented; one malformed task silently disables all parallelism. **Pushback:** this is the deliberate conservative default and is the safe direction to fail; the cost is only lost parallelism, never incorrectness. Disposition: candidate doc task (add operator warning).
- **[codex] B3 — path-based conflict matching treats logical resources (DB URLs, ports) as strings.** Could produce false conflicts; escape hatch (`serialize_all`) documented in code but not SPEC. **Pushback:** false conflicts only over-serialize (safe); and the file-conflict layer is explicitly scoped to file paths per non-goals. Disposition: report-only (speculative future concern).
- **[codex] B4 — no test for cross-level partition isolation.** A ws separated from a HIGH peer at level N can co-batch with a different peer at level N+1; correct by construction (partition runs per-level, INV-2) but untested. **Pushback:** INV-2 makes this safe with no cross-level state, so the test is clarifying, not bug-catching. Disposition: candidate test task (optional).

## Consensus vs disagreement
- **Consensus (both APPROVE):** all 7 invariants satisfied; semaphore lifetime + merge mutex + sorted locking + fail-safe all correct; 183 tests passing; no blockers/majors.
- **Single-reviewer items:** gemini's gc.auto (Prong A minor); codex's B1–B4 (Prong B minors). B1 refuted on code inspection. None blocking.

## Gate decision
**SHIP.** No blocker or major findings from either LLM. The four surviving minors are documentation/test/optional-hardening — none gate the merge. Defaults remain opt-in (caps=1), so the change is inert until explicitly enabled.
