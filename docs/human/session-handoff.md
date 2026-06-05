# session-handoff — SESSION.md context handoff for /z-implement-all

> Last updated: 2026-06-05
> Covers source: scripts/session-helpers.sh, agents/context-curator.md, commands/z-implement-all.md

## Overview

The session-handoff system adds a durable `SESSION.md` artifact to each `/z-implement-all` plan so the orchestrator can `/clear` aggressively at its existing batch breakpoint and re-seed its context from a small, bounded file on resume — eliminating the O(N²) `cache_read` growth where every task re-reads the entire growing orchestrator window.

The write path is **hybrid**:
- The orchestrator drops **notable-only breadcrumbs** into the event stream after each task completes (E2 — high-signal, low-noise).
- A Haiku **context-curator** subagent folds the events delta + git diff + TASKS.md + prior SESSION.md into a compact SESSION.md synchronously at the compaction breakpoint, before the "/clear & resume" notice fires (E3).

On next invocation, the orchestrator reads SESSION.md's frontmatter, compares the stored `done_ids_hash` with the current TASKS.md done-set, and re-inlines the body only when the hashes match (E1).

---

## The SESSION.md artifact

`SESSION.md` lives alongside SPEC.md / PLAN.md / TASKS.md in `$Z_HARNESS_PLAN_DIR/`. It is written atomically via a temp-file + rename (never torn on crash/interrupt).

### Frontmatter schema

```yaml
---
artifact: session
slug: <slug>
schema_version: 1
last_gate: <ISO-8601>         # timestamp of the last curation
done_count: <int>             # number of [x] tasks at curation
done_ids_hash: <sha256>       # THE resume key — sha256 of sorted [x] task-id list
last_gate_task_id: <e.g. T012>  # human-readable hint, not load-bearing
next_pending: <e.g. T013 | none>  # human-readable hint, not load-bearing
generated_by: context-curator
context_hash: <sha256 of body>  # observability only — NOT part of resume predicate
diff_unavailable: false       # true if git diff failed at curation time
overflow: false
truncated_sections: []
---
```

### Body sections

| Section | Entry cap | Format |
|---|---|---|
| `## Decisions` | ≤10 | ≤3 lines each; resolved decisions collapse to heading-only line |
| `## Landmines` | ≤10 | `**<task-id>**: <one sentence>` |
| `## Invariants` | ≤15 | 1 line each |
| `## Open threads` | ≤10 | 1 line each |

The total body is bounded by `Z_SESSION_MAX_CHARS` (default 28 000 characters ≈ ~7 K tokens). When that ceiling is exceeded, entries are dropped oldest-first within over-cap sections, `overflow: true` is set, and `truncated_sections` lists the affected section names.

---

## The context-curator agent

`agents/context-curator.md` defines a Haiku subagent (`model: haiku`) dispatched synchronously at the compaction breakpoint.

### Input contract

The orchestrator passes these fields in the prompt:
- `plan_dir` — absolute path to `$Z_HARNESS_PLAN_DIR`
- `run_id` — current `$RUN`
- `repo_root` — absolute repo root
- `last_gate_task_id` — id of the last `[x]` task (the gate this curation represents)
- `tasks_file` — absolute path to TASKS.md
- `event_source` — absolute path to `$ZH_BASE/metrics.jsonl` (the repo-wide sink)
- `slug` — `$Z_HARNESS_SLUG` (used to filter events to this plan)
- `since_marker` — ts of the last `context_curated` event, or `none`

### Ordered behavior

1. Read prior SESSION.md (parse frontmatter + 4 section bodies); start from empty on first run.
2. Read the events delta from `event_source` (`metrics.jsonl`) — **not** the per-plan `events.jsonl` or the orchestration-only `events.jsonl`. Only `metrics.jsonl` aggregates both task-tier events (`task_halt`, `spec_precheck`) and orchestration-tier events (`review_agent_failed`, `compaction_pause`). Read backward from EOF, stopping at the first line where `ts <= since_marker`. Filter to `slug == <slug>`. Extract `context_breadcrumb.intent` entries and structural landmines (`task_halt`, `spec_precheck` with `status == spec_problem`, `decision_needed`, `review_agent_failed`, per-task review-fail events).
3. Read TASKS.md for completion state and run `git diff --stat` for file churn. If `git diff` exits non-zero, continue without diff and set `diff_unavailable: true` — never a hard fail.
4. Fold all content into the 4 capped sections with the overflow rule: apply entry caps → collapse resolved-decision bodies → if still over ceiling, drop oldest entries → set `overflow: true` and emit `context_curation_truncated`.
5. Compute `done_ids_hash` by calling `bash scripts/session-helpers.sh done_set_hash "$tasks_file"`. **Never re-implement this inline** — the writer (curator) and reader (E1) must produce byte-identical hashes from the same helper, or resume silently never fires.
6. Write atomically: write to `SESSION.md.tmp.<PID>`, then `mv` over `SESSION.md`.
7. Emit `context_curated {last_gate, done_count, done_ids_hash, context_hash, bytes}` via `log-event.sh` with label `"orchestration"` so the next curation's `since_marker` lookup finds it in `metrics.jsonl`.
8. Return `STATUS: curated done_ids_hash=<hash> bytes=<n>` (success) or `STATUS: failed reason=<...>` (non-zero exit).

### Failure-stub path

When curation cannot complete after one inline retry, the curator writes a **frontmatter-only stub** SESSION.md: `done_ids_hash` is computed directly from TASKS.md via the helper (event-independent, so the stub's resume key is always valid), `overflow: true`, empty sections. Returns `STATUS: failed`.

---

## Breadcrumb / curate cadence

The two mechanisms operate at different granularities:

**E2 — Notable-only breadcrumb (per-task done path, `z-implement-all.md:1427`):**
After a task transitions to `[x]`, emit `context_breadcrumb {task, intent}` **only** when at least one concrete trigger held:
- (a) A design decision or default-override was made
- (b) A `task_halt` occurred
- (c) A shortcut or spec-deviation was taken
- (d) A reviewer retry happened

Clean completions emit nothing. The curator's event-mining (step 2 above) independently catches `task_halt`, `spec_precheck`, `decision_needed`, and `review_agent_failed` from the structural event stream — this is the backstop when no breadcrumb was emitted.

**E3 — Full curation at the compaction breakpoint (`z-implement-all.md:529`):**
After emitting `compaction_pause` (when the batch trigger fires), dispatch context-curator synchronously before the push-notify. One inline retry at 2× timeout. The full dispatch+notify is time-bounded (worst case ≈ 360 s = 120 s + one 240 s retry).

On success: emit the existing "/clear & resume" push-notify.
On persistent failure: write a frontmatter-only stub, emit `context_curation_failed`, push-notify with `/compact`-or-continue notice (never suggest `/clear`).

The "/clear & resume" notice fires **only** when curation succeeded and the curator's `done_ids_hash` matches the current TASKS.md done-set.

---

## Done-set hash resume predicate (E1)

**Location:** `z-implement-all.md:373` — immediately after TASKS.md is in memory, before any task is dispatched.

**Predicate:** use SESSION.md iff:
1. `SESSION.md` exists at `$BASE/SESSION.md`
2. `schema_version` is supported (currently `1`)
3. `frontmatter.done_ids_hash == CUR_HASH` where `CUR_HASH = done_set_hash(TASKS.md)`
4. At least one pending `[ ]` task remains

**On match:** Read and inline the SESSION.md body into the orchestrator context (explicit Read call — not `@`-include, for driver portability). Export `SESSION_MD_PATH`. Emit `session_resumed`.

**On skip:** Emit `session_resume_skipped {reason}` with one of: `no_file`, `done_set_mismatch`, `no_pending`, `schema_version`. On `done_set_mismatch`, surface a one-line user note: "SESSION.md present but TASKS.md done-set changed since last pause — resuming without re-seed."

The hash is **set-based and position-independent**: same `[x]` task-ids in any line order produce the same hash. Any addition, removal, or change to the `[x]` set changes the hash → safe skip rather than a wrong re-seed. This handles tasks completed offline between pause and resume.

---

## Session-helpers.sh

`scripts/session-helpers.sh` provides pure shell helpers (sourceable or callable). All functions are stdout-only, no side effects, exit 0 always (empty output = not found). All `[x]` detection uses the orchestrator's canonical pattern `^\s*[-*]?\s*\[x\]`.

| Function | Purpose |
|---|---|
| `done_set_hash <tasks_file>` | sha256 of sorted, newline-joined `[x]` task-ids; empty set → hash of `""` |
| `last_done_task <tasks_file>` | id of the last `[x]` heading (human hint) |
| `next_pending_task <tasks_file>` | first `[ ]` task id whose deps are all `[x]` |
| `last_curated_marker <events_file>` | ts of the most recent `context_curated` event (`none` if absent) |
| `session_frontmatter_field <session_file> <field>` | scalar value from YAML frontmatter |

---

## New event kinds

| Kind | When | Fields |
|---|---|---|
| `context_breadcrumb` | Notable trigger on a `[x]` task (E2) | `task`, `intent` |
| `context_curated` | Curator wrote SESSION.md successfully | `last_gate`, `done_count`, `done_ids_hash`, `context_hash`, `bytes` |
| `context_curation_truncated` | Overflow forced entry drops (step 4) | `sections`, `dropped` |
| `context_curation_failed` | Curator failed/timed out after one retry | `reason` |
| `session_resumed` | Orchestrator inlined SESSION.md at startup (E1 match) | `done_ids_hash`, `last_gate_task_id`, `next_pending` |
| `session_resume_skipped` | SESSION.md present but not used, or absent | `reason` |

All events are logged via `log-event.sh` with label `"orchestration"` so they appear in both the per-run `archive/<run>/events.jsonl` and the repo-wide `metrics.jsonl`.

---

## Env knobs

| Variable | Default | Effect |
|---|---|---|
| `Z_SESSION_CURATOR_TIMEOUT_S` | `120` | Per-attempt timeout for curator dispatch. `0` disables curator entirely — falls back to today's plain pause notice without SESSION.md curation. |
| `Z_SESSION_MAX_CHARS` | `28000` | Character ceiling for the SESSION.md body. Curator collapses entries until under this threshold. Passed to the curator at dispatch time. |

---

## Edge cases

- **Concurrent orchestrators on the same plan:** the active-plan registry serializes orchestrators per plan. Even without that, an atomic tmp+rename prevents torn writes; a non-matching `done_ids_hash` on resume is safe-skipped (no corruption).
- **TASKS.md edited offline:** the set-based hash detects any change to the `[x]` set → `done_set_mismatch` skip.
- **Unknown `schema_version`:** emit `session_resume_skipped {reason: schema_version}`.
- **Empty plan (no `[x]` yet):** curator writes a minimal SESSION.md; resume predicate fires only once the `[x]` set is non-empty.
- **`Z_SESSION_CURATOR_TIMEOUT_S=0`:** curator disabled; behavior identical to today (no SESSION.md written).
- **`git diff` failure at curation time:** `diff_unavailable: true` in frontmatter; curation continues from events + TASKS only.

---

## Out of scope (v1)

- Non-plan `/goal` and other commands without TASKS.md/breakpoint.
- Any change to `/compact` itself.
