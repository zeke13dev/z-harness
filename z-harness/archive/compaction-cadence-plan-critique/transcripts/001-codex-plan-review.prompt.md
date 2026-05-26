MODE: plan-review

## SPEC + PLAN (compaction-cadence)

SPEC summary:
- Delete dead Z_HARNESS_PAUSE_AT_PCT guard (never functioned — zero usage_pause events in qt-bot history)
- Replace with deterministic breakpoints in /z-implement-all (5 tasks OR 30 wall-min, counters reset per pause), /z-review-all (unconditional pre-Phase-4), /z-maintain-docs --audit (pre-consultant-batch)
- Recommend /clear over /compact on resume (idempotent via TASKS.md, no orchestrator state)
- Invariant 2: "No orchestrator-side cross-task memory" — all signals must be in TASKS.md before task marked complete
- New event type: compaction_pause (not usage_pause)
- Resume: idempotent, marker-file scheme for pre-consult acknowledgment in /z-review-all and /z-maintain-docs

PLAN: 7 phases covering deletion, adding counters + batch-settle trigger, pre-Phase-4 pause + AskUserQuestion + marker file, pre-audit-batch pause, doc updates, export sync.

## Key implementation details extracted from current codebase:

### /z-implement-all dispatch to implementer/reviewer (from lines 273-379):
- Implementer gets task block verbatim, $BASE path, relevant_docs paths (step 4b: read via INDEX.json file-overlap or explicit **DOCS:** tag)
- Implementer reads SPEC.md, PLAN.md, concept docs themselves (line 125: "Do NOT pre-extract SPEC/PLAN slices in main thread")
- Reviewer gets task description, acceptance criteria, diff.patch path, related downstream files paths, relevant_docs paths, $BASE path
- Reviewer reads SPEC.md itself from $BASE (line 317)
- Between attempts (cycle ≥ 2): implementer sees prior diff + reviewer findings ONLY (delta pattern, lines 354-359)
- Step 4a reads "Depends on:" to find downstream related_files (lines 231-236)

### /z-review-all pre-Phase-4 breakpoint (per PLAN Phase 3):
- New Phase 3.7 between Phase 3.5 (test run) and Phase 4 (consultants)
- AskUserQuestion with two options: "Pause for /clear" OR "Proceed now"
- Marker file: `archive/<run>/.pre_consult_acknowledged` — if present on resume, skip Phase 3.7 and jump directly to Phase 4
- Resume detection: "phase 3.5 artifacts (cumulative.diff, test results) already exist and skips back to Phase 3.7 → Phase 4"

## Critique focus (per user request, ≤300 words):

1. **Invariant 2 violation check**: Is "no orchestrator-side cross-task memory" actually true today? Anything in current implementer/reviewer dispatch code that passes state across tasks (beyond TASKS.md)?

2. **Batch-settle pause fragility**: What happens if a batch has parallel tasks that reach terminal status at different times? The spec says "after all in-flight tasks... reach terminal status AND TASKS.md has been written" — but is there a race condition between writing TASKS.md atomically and the trigger check?

3. **Marker-file resume scheme in /z-review-all**: The plan says "skip back to Phase 3.7 → Phase 4" on resume if artifacts exist. But Phase 3.7 decides between two options via AskUserQuestion:
   - If marker file `.pre_consult_acknowledged` is present, does the code actually skip the entire AskUserQuestion (i.e., the decision was memoized)?
   - What if the user picks "Pause" but doesn't actually clear? They re-invoke without clearing — the cumulative.diff is stale, but the marker file exists. Does the code re-run Phase 3 (rebuild cumulative.diff from current HEAD) or reuse the stale diff?
   - Similarly for /z-maintain-docs --audit: is the "ack'ed" state per-run or global?

Ask Codex: which of these is actually broken, fragile, or missing? Prioritize specificity — cite code locations and exact scenarios.
