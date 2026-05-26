# Phase 1 Scaffolding — memory-self-improvement-loop

## Topic
Include memories in the self-improvement loop after `/z-review-all` and `/z-implement-all`. Three threads: (1) make post-run retro + memory capture harder to skip without being annoying, (2) persist memories/docs across sessions to avoid re-litigating decisions or repeating mistakes, (3) mimic / build off the Hermes open-source agent's RL approach for long-term memories. Goal: vendor-diverse ideation on concrete mechanisms we can add to z-harness commands/agents/scripts.

## Doc-fetcher synthesis
STATUS: partial
No memory-layer concepts in docs/llm/INDEX.json yet. MEMORIES-FLAT.md is empty.

From reading source files:
- /z-suggest-memory: sole authoring path (schema-validated atomic writes to docs/llm/<slug>.json, regenerates MEMORIES-FLAT.md). Default outcome = Cancel. Called mandatorily from /z-improve Phase 7, /z-debug post-mortem (documented but not specced in Phase 9).
- /z-implement-all finalize push-notify: recommends /z-review-all and /z-maintain-docs. No /z-improve or /z-suggest-memory in the finalize chain.
- /z-review-all Phase 6 final push-notify: recommends /z-maintain-docs. No /z-improve or /z-suggest-memory.
- /z-improve: opt-in only. Analyzes events.jsonl for friction signals. Phase 7 mandatorily calls /z-suggest-memory --concept-hints after user accepts harness edits. Proposals capped at 5.
- Telemetry events in events.jsonl per run: run_start, phase_end, task_start, task_review_retry, doc_drift, task_done, compaction_pause, batch_done. No retro_start, memory_capture_start events.
- /z-maintain-docs: triggered post-run but doc-focused, not behavior/pattern-focused.
- Global auto-memory at ~/.claude/projects/<slug>/memory/MEMORY.md (user, feedback, project, reference types). Lives outside repo, not committed.
- Hermes: treat as research-grade — RL-for-long-term-memory project (specifics unverified).

KEY GAPS: (a) no auto-invocation of /z-improve after major runs; (b) /z-review-all Phase 3.7 pre-consult compaction has no memory-layer integration; (c) all memory writes require explicit user approval (Cancel default); (d) no cross-run pattern aggregation; (e) retro is per-run with no multi-run synthesis.

## Explore synthesis
(skipped — Z_HARNESS_BRAINSTORM_EXPLORE not set)

## RESEARCH.md
(not present)

## input_hash
d210ec313aec1552
