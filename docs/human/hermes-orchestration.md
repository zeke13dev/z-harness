# Hermes Orchestration

> Last updated: 2026-06-26
> Covers source: scripts/hermes-execute.py, scripts/hermes/config.py, scripts/hermes/cross_plan.py, scripts/generate-workstreams.py, scripts/hermes/merge.py, scripts/hermes/schema.py, scripts/hermes/worktree.py, scripts/hermes/session.py, scripts/hermes/discord_relay.py, scripts/hermes/so_mcp.py, scripts/so-mcp-server.py, docs/human/hermes-integration-v1.md

## Overview

Hermes is the z-harness parallelism layer: a Python asyncio orchestrator that executes plan workstreams across isolated git worktrees. It reads `workstreams.json`, spawns per-workstream `pi z-execute` sessions, monitors their status, and merges completed branches through a single merge lock.

**Dormant by default.** Hermes entry points are behind `workflow.hermes_enabled=false` unless explicitly enabled. The files remain in-tree to prevent bit-rot; the ordinary single-session path remains the default.

## Discord `so` sessions

Hermes also owns the experimental Discord `so` session path. The inbound
message grammar is `so <host> <project> <task...> [using <z-command>]`.
`scripts/hermes/discord_relay.py` parses and authorizes the message using
configured users, channels, hosts, and project aliases. `so` is not a local
z-harness CLI.

Accepted commands call the MCP-backed
`scripts/hermes/mcp-hermes-orchestrator.py` server. The server owns tmux
session lifecycle internally and exposes structured tools:
`so_start_session`, `so_send`, `so_read`, and `so_list_sessions`. The Discord
layer remains a thin parse/authorize/relay path.

The orchestrator persists lightweight MCP session metadata in
`so-mcp-sessions.json` under the configured Hermes state root. The metadata
tracks Discord ids, requester, host/project, execution host, transport/SSH
target, workdir, task, z-command, tmux session name, turn count, status, and
latest on-demand read output. It is not the old job-registry/supervisor
backend and it does not consume watchdog webhooks.

Remote aliases use the recorded alias transport. For the `qt-bot` alias this
means the MCP server runs tmux commands through SSH on `zeke-pc` in
`/home/zeke/dev/qt-bot`; local aliases run in their configured workdir. The
initial prompt contains the Discord task and requested z-command.

The retired tmux/job-registry/watchdog backend files remain only as reference:
`scripts/hermes/so_jobs.py`, `scripts/hermes/supervisor.py`,
`scripts/hermes/watchdog_webhook.py`, `scripts/notify-watchdog.sh`, and
`scripts/hang-check.sh` are deprecated for Discord `so`. `scripts/hermes/session.py`
remains for legacy Hermes `pi z-execute` lifecycle helpers, not Discord `so`.

## Scheduling model

- `generate-workstreams.py` parses each task block's `**Files:**` line. Missing or unparseable scope sets `scope_unknown=true`, forcing serialization.
- Workstreams form a `depends_on` DAG. `assign_ws_depths` assigns derived `parallel_group="level-N"`; the scheduler gates on dependencies, not on the label.
- Within a ready level, `partition_level` greedily splits workstreams so HIGH-severity file conflicts do not share a sub-batch. `serialize_all` and unknown scope force singleton batches.
- `run_workstream` holds the concurrency semaphore from worktree creation through merge, bounding live sessions rather than just spawn rate.
- `merge_workstream` runs under an in-process `asyncio.Lock`; no two merges happen concurrently inside a Hermes run.

## Cross-plan mode

`run_cross_plan` builds a plan conflict graph from active-plan registry scope records. Unknown, low-confidence, or missing scope conflicts with everything. It acquires plan locks in sorted slug order to avoid deadlock, partitions conflict-free plans into batches, and threads one shared merge lock into each plan runner.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/hermes-execute.py:180` — `run_workstream` — worktree -> spawn -> monitor -> merge coroutine; semaphore spans full lifetime.
- `scripts/hermes-execute.py:414` — `partition_level` — conflict-safe sub-batch partitioning for a ready level.
- `scripts/hermes-execute.py:484` — `compute_ready_level` — dependency-complete workstream selection.
- `scripts/hermes-execute.py:505` — `run_single_plan` — one plan DAG scheduler and cleanup.
- `scripts/hermes-execute.py:711` — `run_cross_plan` — multi-plan scheduler with sorted locks and shared merge lock.
- `scripts/hermes/cross_plan.py:157` — `build_plan_conflict_graph` — fail-safe plan conflict graph from registry scopes.
- `scripts/hermes/cross_plan.py:240` — `acquire_plan_locks` — sorted deadlock-free claim acquisition.
- `scripts/hermes/cross_plan.py:314` — `schedule_batches` — greedy conflict-free plan batching.
- `scripts/generate-workstreams.py:383` — `assign_ws_depths` — longest-path DAG depth and derived `parallel_group`.
- `scripts/generate-workstreams.py:474` — `parse_task_files` — parses task `**Files:**` scope; missing scope triggers `scope_unknown`.
- `scripts/hermes/merge.py:28` — `merge_workstream` — synchronous `git merge --no-ff` for Hermes branch.
- `scripts/hermes/config.py:90` — `load_config` — reads `hermes-config.yaml`; only Discord credentials have env overrides.
- `scripts/hermes/schema.py:54` — `parse_workstreams_json` — typed manifest parse and schema validation.
- `scripts/hermes/worktree.py:58` — `create_worktree` — safe-ref git worktree creation and recovery.
- `scripts/hermes/session.py:25` — `spawn_session` — detached `pi z-execute --tasks=<path>` process.
<!-- AUTO-END: entry-points -->

## Gotchas

- `workflow.hermes_enabled` is the command-level master gate; `hermes-config.yaml` controls runtime concurrency/retry/timeout behavior.
- Legacy `HERMES_MAX_PARALLEL`, `HERMES_SERIALIZE_ALL`, and related env vars have no effect; only Discord env overrides remain.
- File-conflict modeling does not cover non-file shared state such as databases, ports, remotes, or caches.
- `scope_unknown=true` is intentionally conservative and serializes the plan.
- `GIT_OPTIONAL_LOCKS=0` is set during runs to avoid object-store contention.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/hermes-orchestration.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
