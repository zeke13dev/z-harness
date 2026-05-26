# Phase 1 Scaffolding — memory-self-improve-loop

## Topic

Investigate how to include memories in the self-improvement loop after `/z-review-all` and `/z-implement-all`. Three threads:

1. **Push self-improvement harder after runs** — `/z-improve` is opt-in and rarely fired. How do we make post-run retro + memory capture more reliable / harder to skip without being annoying?
2. **Persist memories and docs across sessions** so we don't repeat the same mistakes or re-litigate decisions. What gets written where (`docs/llm` memory layer vs auto-memory vs CLAUDE.md vs doc-fetcher index), how it's surfaced to the next session, how stale entries get pruned, conflict resolution when memory contradicts code.
3. **Hermes agent (open source) long-term memory RL** — investigate mimicking or building off their RL approach. What is the RL signal? How do they store/retrieve? What maps onto z-harness's existing `/z-improve` + `docs/llm` + auto-memory stack vs. what requires new infra?

Goal: vendor-diverse ideation on concrete mechanisms we could add to z-harness commands/agents/scripts to make memory persistence + self-improvement an automatic part of the loop after major runs.

---

## Doc-fetcher synthesis (existing state)

### Core memory authoring path
- `z-suggest-memory` is the **sole authoring path** for `docs/llm/<slug>.json` memories. Schema-validated, atomic writes (tmpfile + `os.replace()`).
- Auto-regenerates `docs/llm/MEMORIES-FLAT.md` (sorted by slug asc, date desc within slug). Format: `[<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: t1, t2)`.
- Controlled tag seed at `docs/llm/TAGS.txt` (15 core tags incl. correctness, perf, data-quality, schema, time-window, units, api-boundary, retry-loop, race-condition, dependency, deprecation, lossy-default, ux, observability, compliance).
- Optional human refresh extracts memory to `docs/human/<slug>.md`.

### Post-run hooks (current)
- `/z-implement-all` and `/z-review-all` emit telemetry via `scripts/log-event.sh` (`run_start`, `phase_end`, `task_start`, `task_review_retry`, `doc_drift`, etc. → `$RUN_DIR/events.jsonl`).
- **No auto-invocation of `/z-improve` after completion.** Opt-in only — user must explicitly run `/z-improve <slug>`.
- `/z-improve` Phase 7 (after user accepts harness edits): mandatorily calls `/z-suggest-memory --concept-hints <slugs from touched files>`.
- `/z-suggest-memory` default outcome is **Cancel** — low bar for memory creation; only persist novel anti-patterns or decision rationale.
- `/z-debug` Phase 9 post-mortem: README says it calls `/z-suggest-memory` "mandatorily" but spec at `commands/z-debug.md:424-467` does **not** explicitly mention it → possible drift.

### Retrieval path (doc-fetcher)
- Main thread never reads `docs/llm/*.json` directly; always dispatches `doc-fetcher` (Haiku).
- Doc-fetcher's two-phase search: (1) INDEX.json lookup by slug/summary; (2) MEMORIES-FLAT.md ripgrep with word-boundary tokens + tag constraints.
- Per matched concept includes ≤3 most-recent memories, truncated to 120 chars if synthesis > 1500 bytes.
- Drift detection: compares `last_updated` in concept JSON vs source file mtimes; emits `DRIFT WARNING`.

### Artifacts table
| Layer | Artifact | Owner | Consumers |
|-------|----------|-------|-----------|
| Memory | `docs/llm/<slug>.json` (memories[]) | z-suggest-memory (sole mutator) | doc-fetcher, /z-maintain-docs |
| Memory index | `docs/llm/MEMORIES-FLAT.md` | regenerate-memories-flat.py | doc-fetcher ripgrep |
| Tag registry | `docs/llm/TAGS.txt` | z-suggest-memory Phase 0 | z-suggest-memory, /z-maintain-docs |
| Improvement proposals | `improvements/<DATE>-<slug>.md` | z-improve Phase 3/7 | user review |
| Friction analysis | `$RUN_DIR/analysis.md` | z-improve Phase 2 | z-improve Phase 3 |
| Events | `$RUN_DIR/events.jsonl` | orchestrators | z-improve Phase 1 |

### Identified gaps
1. No auto-invocation of `/z-improve` after `/z-implement-all` or `/z-review-all` — entirely opt-in.
2. Z-debug → z-suggest-memory mandatory call is documented but not specced in Phase 9.
3. No automatic memory writes — all writes require explicit user approval via Phase 2 + Phase 3 (default Cancel).
4. `/z-review-all` Phase 3.7 pre-consult compaction is mentioned but no memory-layer integration.

### Auto-memory (orthogonal system)
- Global `~/.claude/projects/<project-slug>/memory/MEMORY.md` + per-type memory files (user, feedback, project, reference). Different from `docs/llm/` memory layer. Lives outside repo; not committed.
