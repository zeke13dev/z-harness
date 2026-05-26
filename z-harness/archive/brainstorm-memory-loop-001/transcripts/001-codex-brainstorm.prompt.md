MODE: brainstorm

Topic: Include memories in the self-improvement loop after `/z-review-all` and `/z-implement-all`. Three threads: (1) make post-run retro + memory capture harder to skip without being annoying, (2) persist memories/docs across sessions to avoid re-litigating decisions or repeating mistakes, (3) mimic / build off the Hermes open-source agent's RL approach for long-term memories. Goal: vendor-diverse ideation on concrete mechanisms we can add to z-harness commands/agents/scripts.

## Existing state

**Memory authoring**: `/z-suggest-memory` is the sole authoring path for `docs/llm/<slug>.json` memories. Schema-validated, atomic writes. Auto-regenerates `docs/llm/MEMORIES-FLAT.md` (format: `[<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: t1, t2)`). Controlled tag seed at `docs/llm/TAGS.txt` (15 tags: correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance). Default outcome in suggest-memory is **Cancel** — low bar; only persist novel anti-patterns or decision rationale.

**Post-run hooks (current)**: `/z-implement-all` and `/z-review-all` emit telemetry via `scripts/log-event.sh` to `$RUN_DIR/events.jsonl` (`run_start`, `phase_end`, `task_start`, `task_review_retry`, `doc_drift`, etc.). **No auto-invocation of `/z-improve` after completion** — entirely opt-in. `/z-improve` Phase 7 mandatorily calls `/z-suggest-memory --concept-hints <slugs>` after the user accepts harness edits.

**Retrieval**: main thread never reads `docs/llm/*.json` directly; always dispatches `doc-fetcher` (Haiku). Doc-fetcher two-phase search: (1) INDEX.json lookup; (2) MEMORIES-FLAT.md ripgrep. ≤3 most-recent memories per concept, truncated to 120 chars if synthesis > 1500 bytes. Drift detection: `last_updated` in concept JSON vs source file mtimes.

**Auto-memory (orthogonal)**: Global `~/.claude/projects/<slug>/memory/MEMORY.md` + per-type files (user, feedback, project, reference). Lives outside repo; not committed; cross-conversation persistence.

**Gaps identified**: (a) no auto-invocation of `/z-improve` after major runs; (b) z-debug → z-suggest-memory mandatory call is documented but not specced in Phase 9; (c) all memory writes require explicit user approval (default Cancel); (d) `/z-review-all` Phase 3.7 pre-consult compaction has no memory-layer integration.

---

Return exactly five sections: (1) **Framing**, (2) **Core hypothesis**, (3) **Risks**, (4) **Plan implications**, (5) **What would change my mind**. Do not add other sections.
