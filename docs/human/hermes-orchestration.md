# Hermes Orchestration

> Last updated: 2026-06-19
> Covers source: scripts/hermes-execute.py, scripts/hermes/config.py, scripts/hermes/cross_plan.py, scripts/generate-workstreams.py, scripts/hermes/merge.py, scripts/hermes/schema.py, scripts/hermes/worktree.py, scripts/hermes/session.py, docs/human/hermes-integration-v1.md

## Overview

Hermes is the z-harness parallelism layer — a Python-native asyncio orchestrator that executes plan workstreams concurrently across isolated git worktrees. It reads a machine-readable `workstreams.json` manifest (written by `generate-workstreams.py`) and drives per-workstream sessions via `pi z-execute`, monitoring `session-status.json` for progress, relaying halts, and merging completed branches back to the base. The contract between the planning layer and the orchestrator is defined in `docs/human/hermes-integration-v1.md` (currently at protocol version hermes-v1, spec v1.4).

**Status: DORMANT by default.** As of v1.4 (2026-06-16), all Hermes entry points in `/z-plan`, `/z-execute`, and `/z-plan-split` are guarded by the `workflow.hermes_enabled` config knob, which defaults to `false`. The `scripts/hermes/` directory and `scripts/hermes-execute.py` are intentionally kept (not deleted) to prevent bit-rot while dormant — a future cleanup task will remove them once the gating strategy is confirmed. To activate Hermes, set `workflow.hermes_enabled = true` in `.z-harness/config.toml`.

## Key entry points

- `scripts/hermes-execute.py:180` — `run_workstream` — Async coroutine for one workstream: creates git worktree, spawns `pi z-execute`, polls `session-status.json` in a 5-second loop, handles crash retries and halt relay, acquires `merge_lock` around `merge_workstream`. The semaphore is held for the full lifetime (spawn through merge), not just at spawn time.
- `scripts/hermes-execute.py:414` — `partition_level` — Greedy graph-coloring: splits a dependency-level's ready workstreams into sub-batches where no two in the same batch share a HIGH-severity `file_conflicts` entry. Falls back to fully serial (singleton sub-batches) when `scope_unknown=True` or `serialize_all=True`.
- `scripts/hermes-execute.py:484` — `compute_ready_level` — Returns the workstreams whose entire `depends_on` set has reached terminal status `"done"`. The sole scheduling gate (INV-2); `parallel_group` is a derived label, not a gate.
- `scripts/hermes-execute.py:505` — `run_single_plan` — Async: resolves plan dir, reads `workstreams.json`, applies crash recovery, runs the compute-ready/partition/gather loop, cleans up worktrees. Accepts `merge_lock` from `run_cross_plan` for cross-plan merge serialization.
- `scripts/hermes-execute.py:711` — `run_cross_plan` — Multi-slug entry point. Builds conflict graph, acquires plan-claim locks in sorted ascending order (INV-6), partitions plans into conflict-free batches, runs batches via `asyncio.gather` bounded by `plan_sem`. Creates a single shared `asyncio.Lock` threaded into every `run_single_plan`.
- `scripts/hermes/cross_plan.py:157` — `build_plan_conflict_graph` — Builds adjacency map of plan-level conflicts: two plans conflict if their file-scope path-sets intersect, or either plan is `scope_unknown`/low-confidence/missing from the registry. Fail-safe: unknown scope always conflicts.
- `scripts/hermes/cross_plan.py:240` — `acquire_plan_locks` — Acquires `plan-claim.sh` locks in sorted ascending slug order (INV-6: deadlock-free). Releases all on any single failure.
- `scripts/hermes/cross_plan.py:314` — `schedule_batches` — Greedy batch coloring: groups conflict-free plans in the same batch, serializes conflicting plans across batches.
- `scripts/generate-workstreams.py:384` — `assign_ws_depths` — Computes longest-path depth for each workstream over the `depends_on` DAG. Sets `parallel_group="level-{depth}"`. All workstreams at the same depth are mutually independent by Rule 7.
- `scripts/generate-workstreams.py:475` — `parse_task_files` — Parses `**Files:**` lines from each task block in `TASKS.md`. If any task block lacks a parseable `**Files:**` line, `scope_unknown=True` is emitted — triggers full serialization (INV-4).
- `scripts/hermes/merge.py:28` — `merge_workstream` — Synchronous `git merge --no-ff hermes/<slug>/<ws_id>`. Called under the in-process `asyncio.Lock`; never runs concurrently across workstreams or plans.
- `scripts/hermes/config.py:90` — `load_config` — Reads `hermes-config.yaml` (repo root or `~/.config/hermes/config.yaml`) into `HermesConfig`. Concurrency/retry/timeout knobs are file-only; Discord credentials may be overridden via `HERMES_DISCORD_TOKEN` / `HERMES_DISCORD_USER_ID`.
- `scripts/hermes/schema.py:54` — `parse_workstreams_json` — Parses `workstreams.json` into typed `WorkstreamsManifest` dataclass. Runs 7-rule schema validation.
- `scripts/hermes/worktree.py:58` — `create_worktree` — Creates `git worktree add ../hermes-<slug>-<ws_id> -b hermes/<slug>/<ws_id>`. Validates slug/ws_id against safe-ref regex. Handles crash recovery (branch-exists-but-worktree-missing path).
- `scripts/hermes/session.py:26` — `spawn_session` — Runs `pi z-execute --tasks=<path>` in the worktree as a detached subprocess (`start_new_session=True`). Returns PID.

## How it interacts with others

- `active-plan-registry` — `cross_plan.py` queries `active-plan-registry.py list --json` for per-plan scope records; `_get_session_id()` queries `session-id` to mint the cross-plan lock holder string.
- `plan-claim` — `acquire_plan_locks` and `release_plan_locks` call `scripts/plan-claim.sh acquire/release` in sorted slug order. This is the cross-plan deadlock-safety invariant (INV-6).
- `scripts` — `hermes-execute.py` calls `scripts/plan-path.sh` to resolve plan directories.
- `commands` (z-plan, z-execute) — Hermes-specific machinery remains behind `workflow.hermes_enabled`; generic clear checkpoints are watcher-readable and are no longer Hermes-gated.
- `config` — `scripts/config.py` provides `workflow.hermes_enabled` (the TOML master gate read by commands). This is separate from `hermes/config.py` which reads `hermes-config.yaml` for Hermes runtime behavior.

## Edge cases / gotchas

- **DORMANT BY DEFAULT.** `workflow.hermes_enabled` defaults to `false`. Hermes workstream-generation and cross-plan dispatch calls are no-ops unless `workflow.hermes_enabled = true` is set in `.z-harness/config.toml`. Generic `handoff.json` clear checkpoints are produced by `write-clear-checkpoint.sh` outside this Hermes gate.
- **Two separate config systems.** The TOML gate (`workflow.hermes_enabled`, read by `scripts/config.py`) controls whether commands invoke Hermes. The Hermes runtime behavior (concurrency caps, retries, timeouts) is configured via `hermes-config.yaml` (read by `scripts/hermes/config.py`). Setting knobs in `.z-harness/config.toml` under `[workflow]` does NOT directly flow into the Hermes runtime config — the integration doc's table of `workflow.*` keys reflects a desired alignment that may diverge from what `hermes/config.py` actually reads.
- **HERMES_* env vars are removed.** `HERMES_MAX_PARALLEL`, `HERMES_MAX_PARALLEL_PLANS`, `HERMES_SERIALIZE_ALL`, `HERMES_SERIALIZE_HIGH_SEVERITY`, `HERMES_WORKSTREAM_TIMEOUT_MINUTES`, and `HERMES_MAX_RETRIES` have no effect. Only `HERMES_DISCORD_TOKEN` and `HERMES_DISCORD_USER_ID` remain as env overrides (Discord credentials only).
- **Semaphore held for full lifetime.** The `asyncio.Semaphore` is acquired at the start of `run_workstream` and released only after merge. This bounds the number of live sessions, not just spawn rate — a critical distinction from naive spawn-rate limiting.
- **Merge lock is global within a run.** A single in-process `asyncio.Lock` serializes all `merge_workstream` calls across both workstreams and plans in a `run_cross_plan` invocation. No two merges ever run concurrently.
- **`scope_unknown` propagates fail-safe.** If any task block in `TASKS.md` lacks a parseable `**Files:**` line, `scope_unknown=True` is set on the manifest, `file_conflicts` is forced to `[]`, and the orchestrator treats the plan as fully serial. This is conservative but correct — blind parallelism is forbidden when scope is unknown.
- **Non-file shared state.** The file-conflict layer only models git working-tree isolation. Databases, ports, remote sandboxes, and in-memory caches are not modeled. If workstreams share any such resource, set `workflow.serialize_all = true` in `hermes-config.yaml` (or `max_parallel_workstreams = 1`).
- **`GIT_OPTIONAL_LOCKS=0`** is set around the full run and restored after. This prevents concurrent git auto-gc contention against the shared object store when multiple worktrees are active.
- **`poll_session` runs via `asyncio.to_thread`.** Blocking I/O in the poll (subprocess/file reads) does not stall the event loop or delay sibling workstream monitors.

## Examples

Single-slug sequential run (default, harmless even without `hermes_enabled`):
```bash
python3 scripts/hermes-execute.py --slug my-plan
```

Cross-plan run with comma-separated slugs:
```bash
python3 scripts/hermes-execute.py --slugs plan-a,plan-b,plan-c
```

Cross-plan run from a file listing:
```bash
python3 scripts/hermes-execute.py --plan-set plans.txt
```

Enabling within-plan parallelism (in `hermes-config.yaml`):
```yaml
concurrency:
  max_parallel_workstreams: 3
  serialize_high_severity: true
```

Escaping non-file shared-state contention (in `hermes-config.yaml`):
```yaml
concurrency:
  serialize_all: true
```
