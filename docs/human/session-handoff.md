# session-handoff — SESSION.md context handoff for /z-execute

> Last updated: 2026-07-09
> Covers source: scripts/session-helpers.sh, agents/context-curator.md, skills/z-execute/SKILL.md, scripts/write-handoff.sh

## Overview

The session-handoff system adds a durable `SESSION.md` artifact to each `/z-execute` plan so the orchestrator can `/clear` aggressively at its existing batch/DAG-settle breakpoint and re-seed its context from a small, bounded file on resume — eliminating the O(N²) `cache_read` growth where every task re-reads the entire growing orchestrator window.

The write path is hybrid: the orchestrator drops notable-only breadcrumbs into the event stream after each task completes (E2 — high-signal, low-noise), and a Haiku `context-curator` subagent folds the events delta + git diff + TASKS.md + prior SESSION.md into a compact SESSION.md synchronously at the clear checkpoint, before the "/clear & resume" notice fires (E3, inside `execute_clear_checkpoint_protocol`). On next invocation, the orchestrator reads SESSION.md's frontmatter, compares the stored `done_ids_hash` with the current TASKS.md done-set, and re-inlines the body only when the hashes match (E1). The resulting `handoff.json` — written via `scripts/write-clear-checkpoint.sh`'s call into `scripts/write-handoff.sh` — is a machine-readable continuation token for Oh My Pi, Hermes, MCP, `/z-attend`, or any future watcher.

**Scope note (2026-07-09 refresh):** `scripts/write-clear-checkpoint.sh` (and therefore `write-handoff.sh`) is no longer a `/z-execute`-only mechanism — it is now the shared durable-checkpoint front door used by `/z-plan`, `/z-audit`, `/z-test`, `/z-explore`, `/z-debug`, `/z-research`, `/z-review-all`, `/z-handoff`, and `/z-maintain-docs`. This doc stays scoped to the `/z-execute`-specific SESSION.md curation loop (E1/E2/E3) plus the `write-handoff.sh` schema writer itself; the generic checkpoint-hook layer (`write-clear-checkpoint.sh`, `check-compaction.sh`) is a candidate for its own concept doc.

## Key entry points

- `scripts/session-helpers.sh:75` — `done_set_hash` — sha256 of sorted, newline-joined `[x]` task-ids from TASKS.md; the shared hash function used by both the curator (writer) and E1 (reader); never re-implement inline
- `scripts/session-helpers.sh:155` — `last_done_task` — id of the last `[x]` heading; human hint, not load-bearing
- `scripts/session-helpers.sh:208` — `completed_task_ids` — comma-separated ids for every `[x]` task in file order; the metadata contract for parallel-batch/INTENT-BFS-level curator dispatch (not just the last task)
- `scripts/session-helpers.sh:266` — `next_pending_task` — first `[ ]` task id whose deps are all `[x]`; dep-gated; used by E1 pending detection
- `scripts/session-helpers.sh:390` — `task_status_counts` — `done=<n> pending=<n> in_progress=<n> other=<n>` counts using the same inline-heading/list-checkbox parser as `done_set_hash`; also consumed by `check-compaction.sh` and `scripts/resume-context.py` (outside this concept's direct scope)
- `scripts/session-helpers.sh:474` — `last_curated_marker` — ts of most recent `context_curated` event; used by E3 to compute `since_marker`
- `scripts/session-helpers.sh:522` — `session_frontmatter_field` — reads a scalar YAML frontmatter field from SESSION.md cheaply without loading the body
- `scripts/session-helpers.sh:576` — `validate_intent` — thin shell wrapper over `scripts/intent-schema.py validate-intent`; exit 0=valid, 1=errors, 2=usage; also supports `lint` mode
- `agents/context-curator.md:1` — `context-curator` — Haiku subagent; dispatched synchronously at the clear checkpoint; 8-step ordered behavior producing SESSION.md
- `agents/context-curator.md:12` — Inputs from caller — `plan_dir`, `run_id`, `repo_root`, `last_gate_task_id`, `completed_task_ids`, `tasks_file`, `event_source`, `slug`, `since_marker`
- `agents/context-curator.md:161` — Failure-stub path — frontmatter-only SESSION.md on persistent failure; `done_ids_hash` computed independently of the (possibly failed) event read
- `skills/z-execute/SKILL.md:1591` — E1 resume injection (step 4a) — reads SESSION.md frontmatter via helpers; inlines body when schema_version/done_ids_hash/pending all pass
- `skills/z-execute/SKILL.md:1744` — `## Clear checkpoint policy` — INTENT-mode DAG-settle vs legacy batch-settle triggers, plus the reusable `execute_clear_checkpoint_protocol` block
- `skills/z-execute/SKILL.md:1791` — `execute_clear_checkpoint_protocol()` — dispatches context-curator (1 retry at 2× timeout), verifies the returned `done_ids_hash` against current TASKS.md, then routes to exactly one push-notify (success vs failure/disabled)
- `skills/z-execute/SKILL.md:3208` — E2 notable-only breadcrumb (step 8.3b) — emit `context_breadcrumb` only when a concrete trigger held (decision_gate, task_halt_recovered, spec_deviation, reviewer_retry), priority-ordered
- `scripts/write-clear-checkpoint.sh:1` — generic watcher-readable checkpoint producer (NOT in this concept's source_file scope, but the direct caller of `write-handoff.sh` from `/z-execute`'s clear checkpoint); writes `handoff.json` unconditionally and emits `clear_checkpoint_written`
- `scripts/write-handoff.sh:1` — `write-handoff.sh` — low-level schema writer for `handoff.json` (protocol 1.0 default, protocol 1.1 for `/z-attend` yield when `Z_HARNESS_ATTEND_RESUME=1` with all 5 attend env vars set); extracts task counts from TASKS.md and session metadata from SESSION.md; atomic tmp+rename write

## How it interacts with others

- `active-plan-registry` — serializes concurrent orchestrators per plan; the session-handoff checkpoint pause interacts with the registry's deregister rule (pause does NOT deregister)
- `attend` — `/z-attend` calls `write-handoff.sh` **directly** (not via `write-clear-checkpoint.sh`) at yield points with `Z_HARNESS_ATTEND_RESUME=1` to produce a protocol-1.1 handoff with an `attend_resume` predicate; also calls `session-helpers.sh done_set_hash` for its own DIRTY_FP/resume-token construction
- `handoff-protocol` — `write-handoff.sh` is the canonical low-level schema writer for both protocol 1.0 (generic clear checkpoints) and protocol 1.1 (`/z-attend` yield); `scripts/write-clear-checkpoint.sh` wraps it as the shared, non-Hermes-specific front door used across many commands (see Overview scope note)
- `adaptive-intent` — the INTENT BFS level checkpoint (`.bfs_level_state`) uses `done_set_hash` from `session-helpers.sh` to detect TASKS.md drift between pauses and resume from the correct BFS level
- `intent-schema` — `session-helpers.sh validate_intent` wraps `scripts/intent-schema.py` for shell-layer INTENT.md validation
- `scripts` — `log-event.sh` is called for all session-handoff telemetry events; `check-compaction.sh` and `scripts/resume-context.py` also call `session-helpers.sh task_status_counts` outside the curator/E1 loop proper

## Edge cases / gotchas

- Re-implementing `done_set_hash` inline in the curator or any caller breaks the DRY contract: writer and reader will produce different hashes and resume will silently never fire.
- The `event_source` for the curator must be `$ZH_BASE/metrics.jsonl`, not the per-plan `events.jsonl` or orchestration-only `events.jsonl`. Only `metrics.jsonl` aggregates both task-tier events (`task_halt`, `spec_precheck`) and orchestration-tier events (`review_agent_failed`, `compaction_pause`). Reading either alone makes the landmine backstop inert.
- The "/clear & resume" notice fires only after curation succeeds AND the curator's returned `done_ids_hash` matches the current TASKS.md done-set. Emitting it before that check is a security-of-resume contract violation.
- E1 pending detection uses `next_pending_task` (Python-based), not a bespoke line-start grep. A `^\s*[-*]?\s*\[ \]` grep does NOT match the inline-heading status format `## T002 — title `[ ]`` and returns 0 tasks, making the resume predicate fall to `no_pending` for every production plan (feature inert).
- **CORRECTED 2026-07-09:** `write-clear-checkpoint.sh` (and thus `write-handoff.sh` when called through it, e.g. from `/z-execute`'s `execute_clear_checkpoint_protocol`) is called **unconditionally** on curator success — it is NOT gated by `workflow.hermes_enabled`. Any watcher (Hermes, OMP, MCP, a human) may consume the emitted `handoff.json` plus `clear_checkpoint_written` event regardless of that config flag. (The prior version of this doc incorrectly stated the compaction-breakpoint write was hermes-gated; that was already stale relative to the shipped code.)
- Protocol-1.1 handoff requires all five attend env vars to be non-empty: `Z_HARNESS_ATTEND_HEAD_SHA`, `Z_HARNESS_ATTEND_PHASE`, `Z_HARNESS_ATTEND_DONE_SET_HASH`, `Z_HARNESS_ATTEND_DIRTY_FP`, `Z_HARNESS_ATTEND_SESSION_ID`. Missing any causes `write-handoff.sh` to exit non-zero.
- `Z_SESSION_CURATOR_TIMEOUT_S=0` disables the entire subsystem; no SESSION.md is written and no "/clear & resume" notice fires; `context_curation_failed` is correctly NOT emitted in this disabled case (only on an actual dispatched-and-failed curator).
- Overflow order matters: apply entry caps first, then collapse resolved-decision bodies, then drop oldest entries if still over ceiling. Applying in a different order changes which entries survive.
- `context_curated` must be emitted AFTER the atomic rename succeeds; a crash between write and event leaves `metrics.jsonl` with a stale `since_marker`.
- The failure-stub SESSION.md has `overflow: true` and empty sections; E1 will still resume (the `done_ids_hash` is valid), but the body inlining provides no useful context.
- The INTENT BFS `.bfs_level_state` checkpoint also uses `done_set_hash`; a hash mismatch there causes BFS to restart from level 0 (safe but potentially redundant work).
- After curator dispatch, `execute_clear_checkpoint_protocol` re-verifies the returned `done_ids_hash` against a fresh `done_set_hash "$CHECKPOINT_TASKS_FILE"` read — this guards against a stale curator return being trusted when TASKS.md was written between dispatch and return; a mismatch is treated as a checkpoint failure (`done_ids_hash_mismatch`), not a success.

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

Curator dispatch at clear checkpoint (E3, inside `execute_clear_checkpoint_protocol`):

```bash
SINCE_MARKER="$(bash scripts/session-helpers.sh last_curated_marker "$ZH_BASE/metrics.jsonl")"
COMPLETED_TASK_IDS="$(bash scripts/session-helpers.sh completed_task_ids "$CHECKPOINT_TASKS_FILE")"
# Agent(subagent_type="context-curator", ...) with plan_dir, run_id, event_source, since_marker, completed_task_ids
# On STATUS: curated — re-verify done_ids_hash against a fresh done_set_hash read, then
# call write-clear-checkpoint.sh (unconditional, not hermes-gated) and emit /clear & resume notice
```
