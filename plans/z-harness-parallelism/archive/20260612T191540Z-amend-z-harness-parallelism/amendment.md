# Amendment: fold audit findings B1, M1, M3 into the parallelism plan

**Run:** 20260612T191540Z-amend-z-harness-parallelism
**Mode:** full
**Requested change:** Fold PLAN_AUDIT_REPORT.md findings B1, M1, M3.
- **B1** (scope-data chain broken): pivot T002/T003 to parse `**Files:**` lines from TASKS.md directly instead of reading a never-persisted `scope.json`; drop the `scope.json` dependency entirely.
- **M1** (semaphore lifetime): specify the `asyncio.Semaphore` is held for the full `run_workstream` lifetime via `async with sem:` (spawn → monitor → merge), not just around spawn; add a cap < ready-workstreams concurrency-bound test.
- **M3** (config knob collision): extend the existing `ConcurrencyConfig` (`max_parallel_sessions=3`, env `HERMES_MAX_PARALLEL`) in place rather than adding a new `Concurrency` dataclass; flip default to 1; reconcile naming.

## What this affects

### SPEC.md
- **`generate-workstreams.py` items 3–4 (B1):** rewrite "structured `file_conflicts`" to source per-workstream paths from each task's `**Files:**` line in TASKS.md (the same source `scope-extractor` reads), not an external `scope.json`. `scope_unknown` now means "a task block had no parseable `**Files:**` line." Remove the `scope.json` read.
- **`config.py` (M3):** replace "Add a `Concurrency` dataclass" with "extend the existing `ConcurrencyConfig`"; note existing `max_parallel_sessions=3` / `HERMES_MAX_PARALLEL`; default flips to 1; reconcile naming.
- **`hermes-execute.py` item 5 (M1):** semaphore held for whole `run_workstream` lifetime via `async with`, not around spawn. Add the concurrency-bound test to the Tests list.

### PLAN.md
- **D5 (B1):** reframe from "structured `scope-extractor` artifact (`scope.json`)" to "per-task `**Files:**` lines in TASKS.md" as the within-plan scope source; the "absent ⇒ `scope_unknown`" fail-safe is unchanged.
- Add an `## Amendments` section recording B1/M1/M3 with date + one-line rationale each.

### TASKS.md
- **New tasks:** none.
- **Modified tasks:**
  - **T002** — retitle + rewrite: parse `**Files:**` per task from TASKS.md; drop `scope.json` read. Files list drops the implied scope.json.
  - **T003** — adjust `scope_unknown` trigger to "task block missing a parseable `**Files:**` line"; acceptance updated.
  - **T006** — extend existing `ConcurrencyConfig` (not new dataclass); default 1; reconcile `max_parallel_sessions` naming + `HERMES_MAX_PARALLEL`.
  - **T010** — semaphore via `async with` for the full `run_workstream` lifetime; add cap<ready concurrency-bound test.
- **Removed tasks:** none.
- **Touched-but-completed tasks:** none (all `[ ]`).

## Risk
- No consult trigger fires: no new external dependency, no public API/wire/schema change, no persistence change. B1 *removes* a cross-artifact dependency (simplifies). M3 reconciles a naming collision within an already-planned file. M1 is a wording precision fix. The audit (PLAN_AUDIT_REPORT.md) was itself the cross-LLM review that produced these. Phase 5 consult skipped.
- Complexity re-classification: T002/T003/T006/T010 stay at their current tiers — B1 simplifies T002/T003 (no harder), M3 keeps T006 low, M1 keeps T010 high. No churn; stamps preserved.
