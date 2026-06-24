# session-handoff — SESSION.md context handoff for /z-execute

> Last updated: 2026-06-19
> Covers source: scripts/session-helpers.sh, agents/context-curator.md, skills/z-execute/SKILL.md, scripts/write-handoff.sh

## Overview

The session-handoff system adds a durable `SESSION.md` artifact to each `/z-execute` plan so the orchestrator can `/clear` aggressively at its existing batch breakpoint and re-seed its context from a small, bounded file on resume — eliminating the O(N²) `cache_read` growth where every task re-reads the entire growing orchestrator window.

The write path is hybrid: the orchestrator drops notable-only breadcrumbs into the event stream after each task completes (E2 — high-signal, low-noise), and a Haiku `context-curator` subagent folds the events delta + git diff + TASKS.md + prior SESSION.md into a compact SESSION.md synchronously at the clear checkpoint, before the "/clear & resume" notice fires (E3). On next invocation, the orchestrator reads SESSION.md's frontmatter, compares the stored `done_ids_hash` with the current TASKS.md done-set, and re-inlines the body only when the hashes match (E1). The `handoff.json` artifact produced by `write-clear-checkpoint.sh` provides a machine-readable continuation token for Oh My Pi, Hermes, MCP, `/z-attend`, or any future watcher.

## Key entry points

- `scripts/session-helpers.sh:66` — `done_set_hash` — sha256 of sorted, newline-joined `[x]` task-ids from TASKS.md; the shared hash function used by both the curator (writer) and E1 (reader); never re-implement inline
- `scripts/session-helpers.sh:146` — `last_done_task` — id of the last `[x]` heading; human hint, not load-bearing
- `scripts/session-helpers.sh:197` — `next_pending_task` — first `[ ]` task id whose deps are all `[x]`; dep-gated; used by E1 pending detection
- `scripts/session-helpers.sh:321` — `last_curated_marker` — ts of most recent `context_curated` event; used by E3 to compute `since_marker`
- `scripts/session-helpers.sh:369` — `session_frontmatter_field` — reads a scalar YAML frontmatter field from SESSION.md cheaply without loading the body
- `scripts/session-helpers.sh:423` — `validate_intent` — thin shell wrapper over `scripts/intent-schema.py validate-intent`; exit 0=valid, 1=errors, 2=usage; also supports `lint` mode
- `agents/context-curator.md:1` — `context-curator` — Haiku subagent; dispatched synchronously at the clear checkpoint; 8-step ordered behavior producing SESSION.md
- `skills/z-execute/SKILL.md:1129` — E1 resume injection — reads SESSION.md frontmatter via helpers; inlines body when schema_version/done_ids_hash/pending all pass
- `skills/z-execute/SKILL.md:1279` — clear checkpoint policy — after `compaction_pause`, before push-notify; one retry at 2× timeout; hash-verified before `/clear & resume` notice
- `skills/z-execute/SKILL.md:2531` — E2 notable-only breadcrumb — emit `context_breadcrumb` only when a concrete trigger held (decision, halt, spec-deviation, reviewer-retry)
- `scripts/write-clear-checkpoint.sh:1` — `write-clear-checkpoint.sh` — generic watcher-readable checkpoint producer; writes `handoff.json` and emits `clear_checkpoint_written`

## How it interacts with others

- `active-plan-registry` — serializes concurrent orchestrators per plan; the session-handoff checkpoint pause interacts with the registry's deregister rule (pause does NOT deregister)
- `attend` — `/z-attend` calls `write-handoff.sh` at yield points with `Z_HARNESS_ATTEND_RESUME=1` to produce a protocol-1.1 handoff with an `attend_resume` predicate; also calls `session-helpers.sh done_set_hash` for its resume validation
- `handoff-protocol` — `write-clear-checkpoint.sh` is the generic watcher-facing producer for protocol 1.0 clear checkpoints; `write-handoff.sh` remains the low-level schema writer and protocol-1.1 attend-yield producer
- `adaptive-intent` — the INTENT BFS level checkpoint (`.bfs_level_state`) uses `done_set_hash` from `session-helpers.sh` to detect TASKS.md drift between pauses and resume from the correct BFS level
- `intent-schema` — `session-helpers.sh validate_intent` wraps `scripts/intent-schema.py` for shell-layer INTENT.md validation
- `scripts` — `log-event.sh` is called for all session-handoff telemetry events; `plan-path.sh` resolves the metrics.jsonl path

## Edge cases / gotchas

- Re-implementing `done_set_hash` inline in the curator or any caller breaks the DRY contract: writer and reader will produce different hashes and resume will silently never fire.
- The `event_source` for the curator must be `$ZH_BASE/metrics.jsonl`, not the per-plan `events.jsonl` or orchestration-only `events.jsonl`. Only `metrics.jsonl` aggregates both task-tier events (`task_halt`, `spec_precheck`) and orchestration-tier events (`review_agent_failed`, `compaction_pause`). Reading either alone makes the landmine backstop inert.
- The "/clear & resume" notice fires only after curation succeeds AND the curator's returned `done_ids_hash` matches the current TASKS.md done-set. Emitting it before that check is a security-of-resume contract violation.
- E1 pending detection uses `next_pending_task` (Python-based), not a bespoke line-start grep. A `^\s*[-*]?\s*\[ \]` grep does NOT match the inline-heading status format `## T002 — title `[ ]`` and returns 0 tasks, making the resume predicate fall to `no_pending` for every production plan (feature inert).
- `write-clear-checkpoint.sh` is not Hermes-specific and is not gated by `workflow.hermes_enabled`; any watcher may consume the emitted `handoff.json` plus `clear_checkpoint_written` event.
- Protocol-1.1 handoff requires all five attend env vars to be non-empty: `Z_HARNESS_ATTEND_HEAD_SHA`, `Z_HARNESS_ATTEND_PHASE`, `Z_HARNESS_ATTEND_DONE_SET_HASH`, `Z_HARNESS_ATTEND_DIRTY_FP`, `Z_HARNESS_ATTEND_SESSION_ID`. Missing any causes `write-handoff.sh` to exit non-zero.
- `Z_SESSION_CURATOR_TIMEOUT_S=0` disables the entire subsystem; no SESSION.md is written and no "/clear & resume" notice fires.
- Overflow order matters: apply entry caps first, then collapse resolved-decision bodies, then drop oldest entries if still over ceiling. Applying in a different order changes which entries survive.
- `context_curated` must be emitted AFTER the atomic rename succeeds; a crash between write and event leaves `metrics.jsonl` with a stale `since_marker`.
- The failure-stub SESSION.md has `overflow: true` and empty sections; E1 will still resume (the `done_ids_hash` is valid), but the body inlining provides no useful context.
- The INTENT BFS `.bfs_level_state` checkpoint also uses `done_set_hash`; a hash mismatch there causes BFS to restart from level 0 (safe but potentially redundant work).

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/session-handoff.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: this section is omitted entirely when `memories: []`._

## Examples

Resume predicate check in `/z-execute` step 4a:

```bash
CUR_HASH="$(bash scripts/session-helpers.sh done_set_hash "$TASKS_FILE")"
SV="$(bash scripts/session-helpers.sh session_frontmatter_field "$SESSION_FILE" schema_version)"
DH="$(bash scripts/session-helpers.sh session_frontmatter_field "$SESSION_FILE" done_ids_hash)"
NEXT_PENDING_NOW="$(bash scripts/session-helpers.sh next_pending_task "$TASKS_FILE")"
# Resume fires iff SV="1" AND DH==CUR_HASH AND NEXT_PENDING_NOW is non-empty
```

Curator dispatch at clear checkpoint (E3):

```bash
SINCE_MARKER="$(bash scripts/session-helpers.sh last_curated_marker "$ZH_BASE/metrics.jsonl")"
# Agent(subagent_type="context-curator", ...) with plan_dir, run_id, event_source, since_marker
# On STATUS: curated — verify done_ids_hash, then emit /clear & resume notice
```
