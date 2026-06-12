#!/usr/bin/env python3
"""
hermes-execute.py — Hermes orchestrator CLI entry point.

Usage:
    python3 scripts/hermes-execute.py --slug=<slug>
"""

import argparse
import asyncio
import os
import signal
import subprocess
import sys
import time
import types as _types_mod
from pathlib import Path

from hermes.schema import (
    parse_workstreams_json,
    validate_manifest,
    validate_slug,
    write_resolve_json,
    ResolveAnswer,
)
from hermes.state import (
    OrchestratorState,
    WorkstreamState,
    save_state,
    load_state,
    clear_state,
)
from hermes.config import load_config
from hermes.worktree import (
    create_worktree,
    delete_worktree,
    cleanup_orphaned,
)
from hermes.session import (
    spawn_session,
    poll_session,
    kill_session,
    is_session_alive,
    check_stall,
    check_timeout,
)
from hermes.merge import (
    merge_workstream,
    abort_merge,
)
from hermes.recovery import attempt_recovery
from hermes import cross_plan as _cross_plan


# ---------------------------------------------------------------------------
def _validate_slug_set_args(args) -> list[str]:
    """Enforce 'exactly one of {--slug, --slugs, --plan-set} provided'.

    Returns the resolved slug list on success.
    Prints to stderr and exits with code 2 on violation.
    """
    provided = []
    if getattr(args, "slug", None):
        provided.append("--slug")
    if getattr(args, "slugs", None):
        provided.append("--slugs")
    if getattr(args, "plan_set", None):
        provided.append("--plan-set")

    if len(provided) == 0:
        print(
            "ERROR: one of --slug, --slugs, or --plan-set is required",
            file=sys.stderr,
        )
        sys.exit(2)

    if len(provided) > 1:
        print(
            f"ERROR: {' and '.join(provided)} are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(2)

    if getattr(args, "slug", None):
        return [args.slug]

    if getattr(args, "slugs", None):
        return [s.strip() for s in args.slugs.split(",") if s.strip()]

    # --plan-set: one slug per line, skip blank lines and comments
    try:
        lines = Path(args.plan_set).read_text().splitlines()
    except OSError as exc:
        print(f"ERROR: cannot read --plan-set file: {exc}", file=sys.stderr)
        sys.exit(2)
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def parse_args():
    p = argparse.ArgumentParser(description="Hermes orchestrator")
    # --slug is no longer unconditionally required; mutual-exclusion enforced
    # in _validate_slug_set_args after parsing so the error message is clear.
    p.add_argument("--slug", default=None, help="Single plan slug (default mode)")
    p.add_argument(
        "--slugs",
        default=None,
        help="Comma-separated list of plan slugs for cross-plan execution",
    )
    p.add_argument(
        "--plan-set",
        default=None,
        metavar="FILE",
        help="File with one slug per line for cross-plan execution",
    )
    p.add_argument("--plan-dir", help="Plan directory override (single-plan only)")
    return p.parse_args()


def resolve_plan_dir(slug: str, explicit: str = None) -> str:
    if explicit:
        return explicit
    try:
        r = subprocess.run(
            ["bash", "scripts/plan-path.sh", "resolve_plan_path", slug],
            capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except Exception:
        pass
    legacy = Path("z-harness") / slug
    if legacy.exists():
        return str(legacy)
    raise FileNotFoundError(f"Cannot resolve plan dir for '{slug}'")


def validate_gates(manifest, plan_dir: str) -> list[str]:
    errors = []
    if manifest.protocol != "hermes-v1":
        errors.append(f"Unsupported protocol '{manifest.protocol}'")
    schema_errs = validate_manifest(manifest)
    errors.extend(f"Schema: {e}" for e in schema_errs)
    if manifest.partial_tree:
        failed = [w.id for w in manifest.workstreams if w.status == "failed"]
        print(f"WARNING: partial_tree=true, skipping failed: {failed}")
    sc = Path(plan_dir) / "SHARED-CONCERNS.md"
    if sc.exists():
        text = sc.read_text()
        import re
        m = re.search(r"overlap_count:\s*(\d+)", text)
        if m and int(m.group(1)) > 0 and "acknowledged: true" not in text:
            errors.append("SHARED-CONCERNS.md has unacknowledged overlaps")
    return errors


# ---------------------------------------------------------------------------
async def relay_halt_question(ws_id, status, wt_path, tasks_path, config) -> bool:
    """Relay a halt question via Discord. Returns True if resolved, False to abort."""
    try:
        from hermes.discord_relay import relay_halt
        answer = await relay_halt(
            ws_id, status.halt_reason or "unknown",
            status.halt_description or "", 30,
        )
    except Exception:
        answer = None
    
    if answer is None:
        print(f"  Halt unresolved — aborting {ws_id}")
        return False
    
    resolve_path = os.path.join(wt_path, "hermes-resolve.json")
    write_resolve_json(resolve_path, ResolveAnswer(
        decision_id=f"DEC-{ws_id}", chosen=answer,
    ))
    print(f"  Resolved: {answer}")
    return True


# ---------------------------------------------------------------------------
async def run_workstream(ws, state, config, args, repo_root, plan_dir, completed, *, merge_lock=None):
    """Run a single workstream end-to-end: worktree → spawn → monitor → merge.

    Lifted verbatim from the former per-workstream body of the `for ws_id in
    exec_order` loop. Behavior is identical to the legacy sequential path
    (INV-5); no concurrency primitives are introduced here.

    `completed` is the caller's running list of merged workstream IDs — passed
    through solely so the abort-plan branch can revert them, matching the
    legacy semantics. On success the workstream's id is appended to it.

    `merge_lock` (asyncio.Lock or None): when provided, the merge step is
    serialized behind this lock so concurrent workstreams (or concurrent plans)
    never perform `git merge` simultaneously. When None (default), the merge
    runs without a lock — safe for the sequential cap=1 path.

    Returns the terminal status string for this workstream:
      "done"    — monitored to completion and merged (or merge conflict left
                  for manual fix, matching legacy: still counted completed)
      "failed"  — worktree/spawn/timeout/crash/halt-unresolved failure
      "skipped" — merge conflict resolved as "skip"
    """
    ws_id = ws.id

    print(f"\n--- {ws_id}: {ws.name} ---")
    ws_state = state.workstreams.get(ws_id, WorkstreamState(ws_id=ws_id))
    ws_state.tasks_total = len(ws.tasks)
    state.workstreams[ws_id] = ws_state

    # Create worktree (skip if recovered)
    if not ws_state.worktree_path:
        try:
            wt_path = create_worktree(args.slug, ws_id, repo_root, config.paths.worktree_base)
            ws_state.worktree_path = wt_path
        except Exception as e:
            print(f"  Worktree ERROR: {e}")
            ws_state.status = "failed"
            save_state(state, plan_dir)
            return "failed"
    else:
        wt_path = ws_state.worktree_path
        print(f"  Reusing worktree: {wt_path}")

    # Spawn session (skip if recovered and alive)
    tasks_path = os.path.join(ws.path, "TASKS.md")
    if not os.path.exists(os.path.join(wt_path, tasks_path)):
        print(f"  TASKS.md not found at {wt_path}/{tasks_path}")
        ws_state.status = "failed"
        save_state(state, plan_dir)
        return "failed"
    resume_pid = ws_state.pid if ws_state.pid and is_session_alive(ws_state.pid) else None

    if not resume_pid:
        try:
            pid = spawn_session(wt_path, tasks_path)
            ws_state.pid = pid
        except Exception as e:
            print(f"  Spawn ERROR: {e}")
            ws_state.status = "failed"
            save_state(state, plan_dir)
            return "failed"
    else:
        pid = resume_pid
        print(f"  Resumed session: PID {pid}")

    # Monitor
    session_start = time.time()
    last_progress = time.time()
    last_done = ws_state.tasks_done

    while True:
        await asyncio.sleep(5)

        # Timeout
        if check_timeout(session_start, config.timeouts.per_workstream_minutes):
            print(f"  TIMEOUT")
            ws_state.status = "failed"
            try: kill_session(pid)
            except: pass
            break

        # Poll status FIRST — then check liveness only if not done
        # Wrapped in asyncio.to_thread so blocking I/O in poll_session
        # (subprocess/file reads) does not stall the event loop and delay
        # sibling workstream monitors (required for T010 gather concurrency).
        status = await asyncio.to_thread(poll_session, wt_path)

        # Crash (only if process dead AND status is not done/paused)
        if not is_session_alive(pid):
            if status and status.status in ("done", "paused"):
                pass  # Normal exit — process ended cleanly
            else:
                ws_state.retry_count += 1
                if ws_state.retry_count <= config.retry.max_retries:
                    print(f"  Crash — retry {ws_state.retry_count}")
                    await asyncio.sleep(config.retry.retry_delay_seconds)
                    try: pid = spawn_session(wt_path, tasks_path); ws_state.pid = pid
                    except: pass
                    continue
                else:
                    print(f"  Max retries exhausted")
                    ws_state.status = "failed"
                    break

        if status is None:
            continue

        if status.tasks_done > last_done:
            last_progress = time.time(); last_done = status.tasks_done
            ws_state.tasks_done = status.tasks_done
            ws_state.current_task = status.current_task
            print(f"  Progress: {status.tasks_done}/{status.tasks_total}")

        if check_stall(status, status.updated_at, config.stall_detection.no_progress_minutes):
            print(f"  STALL: {ws_id} no progress for {config.stall_detection.no_progress_minutes}min")
            # TODO: surface stall via Discord (m3 fix)

        if status.status == "done":
            print(f"  DONE")
            ws_state.status = "done"
            break

        elif status.status == "halted":
            print(f"  HALTED: {status.halt_reason}")
            ws_state.status = "halted"
            ws_state.halt_reason = status.halt_reason
            save_state(state, plan_dir)

            # Relay question via Discord (M1)
            resolved = await relay_halt_question(ws_id, status, wt_path, tasks_path, config)
            if not resolved:
                ws_state.status = "failed"
                break

            # Kill and re-spawn
            try: kill_session(pid)
            except: pass
            await asyncio.sleep(1)
            try:
                pid = spawn_session(wt_path, tasks_path)
                ws_state.pid = pid
                ws_state.status = "running"
                print(f"  Re-spawned")
            except Exception as e:
                print(f"  Re-spawn ERROR: {e}")
                ws_state.status = "failed"
                break

        elif status.status == "paused":
            print(f"  PAUSED — re-spawning")
            try: kill_session(pid)
            except: pass
            await asyncio.sleep(1)
            try:
                pid = spawn_session(wt_path, tasks_path)
                ws_state.pid = pid
                ws_state.status = "running"
            except Exception as e:
                print(f"  Re-spawn ERROR: {e}")
                ws_state.status = "failed"
                break

    # Determine terminal status from monitor outcome
    terminal = "done" if ws_state.status == "done" else "failed"

    # Merge — serialized behind merge_lock when provided so concurrent
    # workstreams (or concurrent plans sharing a shared lock) never perform
    # `git merge` simultaneously. The lock is held only around the merge call
    # itself; sessions still run concurrently outside of this critical section.
    if terminal == "done":
        print(f"  Merging...")
        merge_ok = False
        try:
            if merge_lock is not None:
                async with merge_lock:
                    result = merge_workstream(ws_id, args.slug, repo_root)
            else:
                result = merge_workstream(ws_id, args.slug, repo_root)
            if result.success:
                print(f"  MERGED")
                merge_ok = True
            else:
                print(f"  CONFLICT: {result.conflicted_files}")
                # TODO: relay merge conflict via Discord
        except Exception as e:
            print(f"  Merge ERROR: {e}")

        if merge_ok:
            completed.append(ws_id)
            try:
                delete_worktree(args.slug, ws_id, repo_root, config.paths.worktree_base)
                print(f"  Cleaned up")
            except Exception as e:
                print(f"  Cleanup WARNING: {e}")
        else:
            # Merge had conflicts — handle resolution
            completed.append(ws_id)
            print(f"  Conflict resolution needed for {ws_id}")
            try:
                from hermes.discord_relay import relay_merge_conflict
                resolution = await relay_merge_conflict(
                    result.conflicted_files[0] if result.conflicted_files else "unknown",
                    [ws_id],
                    result.diff or "",
                )
            except Exception:
                resolution = None

            if resolution == "1":  # Resolve manually
                print(f"  Waiting for manual resolution...")
                # User resolves, then orchestrator continues
            elif resolution == "2":  # Spawn resolution session
                print(f"  Spawning resolution session...")
                # Spawn pi to resolve
            elif resolution == "3":  # Skip
                from hermes.merge import abort_merge
                abort_merge(repo_root)
                print(f"  Skipped {ws_id}")
                save_state(state, plan_dir)
                return "skipped"
            elif resolution == "4":  # Abort plan
                from hermes.merge import abort_merge, revert_all_completed
                abort_merge(repo_root)
                revert_all_completed(completed, args.slug, repo_root)
                print(f"  Aborted plan")
                sys.exit(1)
            else:
                print(f"  No resolution — keeping worktree for manual fix")

    save_state(state, plan_dir)
    return terminal


# ---------------------------------------------------------------------------
def partition_level(ready_level, manifest, config):
    """Partition a ready level into sub-batches for conflict-safe execution.

    Returns a list of sub-batches (list[list[Workstream]]) where no two
    workstreams in the same sub-batch share a HIGH-severity file_conflicts
    entry (when gated by config.concurrency.serialize_high_severity).

    Fail-safe rules (INV-4):
    - manifest.scope_unknown=True  → fully serial (singleton sub-batches)
    - config.concurrency.serialize_all=True → fully serial
    - config.concurrency.serialize_high_severity=False → no HIGH-severity
      separation; all workstreams may share one sub-batch

    Otherwise: greedy graph-coloring over HIGH-severity conflict edges.
    Two workstreams A and B have an edge iff there exists a file_conflicts
    entry with severity=="high" that lists both A and B (restricted to
    members present in this ready_level). Workstreams are assigned in the
    deterministic order of ready_level; each is placed in the first existing
    sub-batch that has no HIGH-conflict edge to any of its current members,
    or a new sub-batch is started.
    """
    # Fail-safe: fully serial
    if manifest.scope_unknown or config.concurrency.serialize_all:
        return [[ws] for ws in ready_level]

    # Build the conflict-edge set for this level
    level_ids = {ws.id for ws in ready_level}

    if config.concurrency.serialize_high_severity:
        # Collect HIGH-severity edges restricted to workstreams in this level
        conflict_edges: set[frozenset] = set()
        for fc in manifest.file_conflicts:
            if fc.severity != "high":
                continue
            # Only members present in this ready_level matter
            members_here = [wid for wid in fc.workstreams if wid in level_ids]
            # Add an edge between every pair of members in this level
            for i in range(len(members_here)):
                for j in range(i + 1, len(members_here)):
                    conflict_edges.add(frozenset({members_here[i], members_here[j]}))
    else:
        # serialize_high_severity=False: no separation for HIGH conflicts
        conflict_edges = set()

    if not conflict_edges:
        # No HIGH-conflict edges → one sub-batch containing all workstreams
        return [list(ready_level)]

    # Greedy graph-coloring: assign each ws to the first sub-batch with no
    # HIGH-conflict edge to any existing member of that sub-batch.
    sub_batches: list[list] = []
    for ws in ready_level:
        placed = False
        for batch in sub_batches:
            # Check if ws conflicts with any member in this batch
            has_conflict = any(
                frozenset({ws.id, member.id}) in conflict_edges
                for member in batch
            )
            if not has_conflict:
                batch.append(ws)
                placed = True
                break
        if not placed:
            sub_batches.append([ws])

    return sub_batches


# ---------------------------------------------------------------------------
def compute_ready_level(runnable, terminal_status):
    """Return the deterministically-ordered set of workstreams that are READY.

    A workstream is READY iff it is not yet terminal and every id in its
    `depends_on` has reached terminal status "done". `runnable` is the ordered
    list of candidate workstreams (already sorted into the legacy execution
    order); `terminal_status` maps ws_id → terminal status string for any
    workstream that has finished. Order is preserved from `runnable`, so for a
    linear / empty-depends_on manifest the ready sets reproduce the legacy
    sequential order exactly (INV-5).
    """
    ready = []
    for ws in runnable:
        if ws.id in terminal_status:
            continue  # already finished (done/failed/skipped) or recovered-done
        if all(terminal_status.get(d) == "done" for d in ws.depends_on):
            ready.append(ws)
    return ready


# ---------------------------------------------------------------------------
async def run_single_plan(slug: str, plan_dir_override, config, repo_root, *, merge_lock=None) -> int:
    """Execute one plan's within-plan DAG scheduler end-to-end.

    Returns an int exit-code-like status:
      0  — success (no failed/blocked workstreams)
      1  — plan failed or workstreams blocked
      2  — setup/gate error (workstreams.json missing, gate check failed, etc.)

    Does NOT call sys.exit — the caller decides process exit.

    `merge_lock` (asyncio.Lock or None): shared merge mutex threaded down to
    each run_workstream call. When None (standalone single-plan path), a
    per-run lock is created here so even concurrent workstreams within a single
    plan serialize their merges (deterministic, conflict-free base mutation).
    When provided (cross-plan path), the SAME lock is shared across all plans,
    ensuring no two plans merge concurrently.
    """
    plan_dir = resolve_plan_dir(slug, plan_dir_override)
    print(f"Plan dir: {plan_dir}")

    ws_path = os.path.join(plan_dir, "workstreams.json")
    if not os.path.exists(ws_path):
        print(f"ERROR: workstreams.json not found", file=sys.stderr)
        return 2

    manifest = parse_workstreams_json(ws_path)
    print(f"Loaded: {len(manifest.workstreams)} ws, protocol={manifest.protocol}")

    gate_errs = validate_gates(manifest, plan_dir)
    if gate_errs:
        for e in gate_errs:
            print(f"GATE: {e}", file=sys.stderr)
        return 2
    print("Gates: PASSED")

    # --- Crash recovery (M2) ---
    state = attempt_recovery(slug, plan_dir, repo_root)
    if state:
        print(f"Resuming from previous run (phase: {state.phase})")
    else:
        state = OrchestratorState(slug=slug, phase="running")

    # --- Discord connect ---
    try:
        from hermes.discord_relay import connect, disconnect
        await connect(config)
    except Exception as e:
        print(f"Discord: {e} — continuing without relay")

    # --- Main loop (V1 sequential with optional DAG) ---
    ready = [w for w in manifest.workstreams if w.status == "ready"]

    # Build execution order: respects depends_on DAG, falls back to merge_order
    has_deps = any(w.depends_on for w in ready)
    if has_deps:
        # Topological sort respecting depends_on
        from collections import deque
        ws_map = {w.id: w for w in ready}
        in_degree = {w.id: len([d for d in w.depends_on if d in ws_map]) for w in ready}
        queue = deque([wid for wid, deg in in_degree.items() if deg == 0])
        exec_order = []
        while queue:
            wid = queue.popleft()
            exec_order.append(wid)
            for w in ready:
                if wid in w.depends_on:
                    in_degree[w.id] -= 1
                    if in_degree[w.id] == 0:
                        queue.append(w.id)
        # Append any remaining (shouldn't happen if no cycles)
        exec_order += [w.id for w in ready if w.id not in exec_order]
    else:
        # V1: use merge_order (sequential, all depends_on empty)
        order_map = {ws_id: i for i, ws_id in enumerate(manifest.merge_order)}
        exec_order = [w.id for w in sorted(ready, key=lambda w: order_map.get(w.id, 999))]

    completed, failed, skipped = [], [], []

    # --- Level-aware sequential scheduler (INV-2: depends_on drives readiness) ---
    # `exec_order` above gives the deterministic legacy ordering; build the
    # runnable candidate list in that order so each ready level preserves the
    # legacy execution sequence (INV-5: cap=1 == legacy sequential).
    order_index = {ws_id: i for i, ws_id in enumerate(exec_order)}
    runnable = sorted(ready, key=lambda w: order_index.get(w.id, 999))

    completed, failed, skipped = [], [], []

    # terminal_status: ws_id -> "done" | "failed" | "skipped" for finished ws.
    # Seed with recovery: workstreams already "done" are never re-run (skip).
    terminal_status = {}
    for ws in runnable:
        rec = state.workstreams.get(ws.id)
        if rec and rec.status == "done":
            print(f"\n--- {ws.id}: {ws.name} --- [already done]")
            terminal_status[ws.id] = "done"
            completed.append(ws.id)

    # Semaphore created ONCE for the entire run — held across the FULL
    # spawn→monitor→merge lifetime of each run_workstream call (not released
    # after spawn). This bounds the number of concurrently-live sessions, not
    # just the spawn rate. At max_parallel_workstreams=1, this serializes to
    # exactly one-at-a-time, preserving the legacy sequential order (INV-5).
    sem = asyncio.Semaphore(config.concurrency.max_parallel_workstreams)

    # Merge mutex: serializes all `git merge` calls so base-branch mutations
    # are never concurrent. If a shared lock was passed in (cross-plan path),
    # reuse it so ALL plans share one mutex. Otherwise create a per-run lock
    # (standalone single-plan path) — still needed when cap>1 allows concurrent
    # workstreams within one plan.
    _merge_lock: asyncio.Lock = merge_lock if merge_lock is not None else asyncio.Lock()

    # gc safety: disable concurrent git auto-gc and optional lock acquisition
    # for the duration of the run. GIT_OPTIONAL_LOCKS=0 prevents git from
    # acquiring optional index/ref locks that cause contention across worktrees.
    # gc.auto suppression relies on GIT_OPTIONAL_LOCKS plus not invoking gc
    # directly (no `git gc` calls in merge_workstream).
    _prior_git_optional_locks = os.environ.get("GIT_OPTIONAL_LOCKS")

    # Construct a per-plan args-like namespace so run_workstream can pass the
    # slug to merge_workstream without depending on a global args object.
    plan_args = _types_mod.SimpleNamespace(slug=slug, plan_dir=plan_dir_override)

    async def _run_one(ws):
        """Semaphore-bounded wrapper: holds sem for the full run_workstream lifetime."""
        async with sem:
            try:
                result = await run_workstream(
                    ws, state, config, plan_args, repo_root, plan_dir, completed,
                    merge_lock=_merge_lock,
                )
                return ws.id, result
            except Exception as e:
                print(f"  EXCEPTION in {ws.id}: {e}")
                return ws.id, "failed"

    try:
        os.environ["GIT_OPTIONAL_LOCKS"] = "0"

        # Drive level by level: compute the ready set, partition into sub-batches
        # (conflict-aware), then run all workstreams in a sub-batch concurrently
        # via gather. Sub-batches still run one-after-another, preserving conflict
        # ordering and the partition contract. At cap=1 the semaphore serializes
        # each sub-batch to sequential execution (INV-5 parity).
        while True:
            ready_level = compute_ready_level(runnable, terminal_status)
            if not ready_level:
                break
            sub_batches = partition_level(ready_level, manifest, config)
            for sub_batch in sub_batches:
                results = await asyncio.gather(
                    *[_run_one(ws) for ws in sub_batch],
                    return_exceptions=True,
                )
                # Post-process gather results from main coroutine (thread-safe:
                # asyncio is single-threaded; writes happen after all tasks done).
                for item in results:
                    if isinstance(item, Exception):
                        # Belt-and-suspenders: _run_one already catches exceptions
                        # and returns (ws.id, "failed"). This branch only fires if
                        # _run_one itself somehow raised (e.g. CancelledError).
                        print(f"  Unhandled exception in gather: {item}")
                        # Cannot record without ws.id — skip to avoid KeyError.
                        continue
                    wid, result = item
                    terminal_status[wid] = result
                    if result == "failed":
                        failed.append(wid)
                    elif result == "skipped":
                        skipped.append(wid)
                    # "done" already appended to `completed` inside run_workstream.
    finally:
        # Restore GIT_OPTIONAL_LOCKS to its prior value (or unset it).
        if _prior_git_optional_locks is None:
            os.environ.pop("GIT_OPTIONAL_LOCKS", None)
        else:
            os.environ["GIT_OPTIONAL_LOCKS"] = _prior_git_optional_locks

    # Workstreams that never ran because a dependency failed (blocked).
    blocked = [w.id for w in runnable if w.id not in terminal_status]

    # Final
    print(f"\n--- Done ---")
    print(f"  Completed: {completed}")
    print(f"  Failed: {failed}")
    if skipped:
        print(f"  Skipped: {skipped}")
    if blocked:
        print(f"  Blocked (dependency failed): {blocked}")
    cleanup_orphaned(slug, set(completed + failed + skipped), repo_root, config.paths.worktree_base)
    clear_state(plan_dir)

    # T013: merge mutex is active — the shared asyncio.Lock created in
    # run_cross_plan (or per-run lock created here when merge_lock=None) was
    # threaded through _run_one → run_workstream and held exclusively around
    # each merge_workstream() call, ensuring no concurrent git merges.

    try:
        from hermes.discord_relay import disconnect
        await disconnect()
    except Exception:
        pass

    return 0 if not (failed or blocked) else 1


# ---------------------------------------------------------------------------
async def run_cross_plan(slugs: list[str], config, repo_root: str) -> int:
    """Schedule and execute multiple plans with deadlock-free locking.

    1. Builds the cross-plan conflict graph.
    2. Acquires per-slug plan-claim.sh locks in sorted ascending order
       (deadlock-free: both sides of any pair always acquire in the same order).
    3. Partitions slugs into conflict-free batches via greedy graph-coloring.
    4. Runs each batch concurrently (bounded by config.concurrency.max_parallel_plans).
       Plans within a batch are conflict-free (scope-disjoint). Batches are
       sequential (conflicting plans are in different batches).
    5. Failure isolation: a failed plan releases its lock and does not abort
       disjoint peers; other plans in the same or later batches continue.
    6. Releases all remaining locks after all batches complete.

    Returns 0 iff all plans succeeded, else 1.

    T013: a single shared asyncio.Lock (shared_merge_lock) is created here and
    passed into every run_single_plan call, which threads it down to each
    run_workstream. This ensures all git merges across all plans are serialized
    behind one mutex — no two merges ever run concurrently.
    """
    print(f"[cross-plan] Slugs: {slugs}")
    graph = _cross_plan.build_plan_conflict_graph(slugs)
    edges = sorted(
        (a, b)
        for a, peers in graph.items()
        for b in peers
        if a < b
    )
    if edges:
        print(f"[cross-plan] Conflict edges:")
        for a, b in edges:
            print(f"  {a} <-> {b}")
    else:
        print("[cross-plan] No conflicts detected between plans.")

    # Mint session_id and run_id for lock acquisition.
    session_id = _get_session_id()
    run_id = str(int(time.time()))

    acquired_ok, acquired = _cross_plan.acquire_plan_locks(
        slugs, session_id=session_id, run_id=run_id,
    )
    if not acquired_ok:
        print("[cross-plan] ERROR: failed to acquire all plan locks", file=sys.stderr)
        return 1

    # Track which slugs still hold their lock (released on failure).
    still_held: set[str] = set(acquired)
    any_failed = False

    batches = _cross_plan.schedule_batches(slugs, graph)
    print(f"[cross-plan] Batches: {batches}")

    plan_sem = asyncio.Semaphore(config.concurrency.max_parallel_plans)

    # Shared merge mutex: ONE lock shared by ALL plans so no two `git merge`
    # calls ever run concurrently, regardless of which plan or workstream they
    # belong to. Created here in run_cross_plan and threaded into every
    # run_single_plan → run_workstream call chain.
    shared_merge_lock = asyncio.Lock()

    try:
        for batch in batches:
            async def _run_plan(slug):
                """Semaphore-bounded plan runner with per-plan failure isolation."""
                async with plan_sem:
                    try:
                        code = await run_single_plan(slug, None, config, repo_root, merge_lock=shared_merge_lock)
                    except Exception as exc:
                        print(f"[cross-plan] EXCEPTION in plan {slug}: {exc}")
                        code = 1
                    if code != 0:
                        # Release this plan's lock immediately on failure.
                        if slug in still_held:
                            _cross_plan.release_plan_locks(
                                [slug],
                                session_id=session_id,
                                run_id=run_id,
                            )
                            still_held.discard(slug)
                    return slug, code

            results = await asyncio.gather(
                *[_run_plan(slug) for slug in batch],
                return_exceptions=True,
            )
            for item in results:
                if isinstance(item, Exception):
                    print(f"[cross-plan] Unhandled exception in gather: {item}")
                    any_failed = True
                    continue
                slug, code = item
                if code != 0:
                    any_failed = True
                    print(f"[cross-plan] Plan {slug} FAILED (code={code})")
                else:
                    print(f"[cross-plan] Plan {slug} SUCCEEDED")
    finally:
        # Release all still-held locks.
        if still_held:
            _cross_plan.release_plan_locks(
                list(still_held),
                session_id=session_id,
                run_id=run_id,
            )

    return 1 if any_failed else 0


def _get_session_id() -> str:
    """Retrieve the current session ID via active-plan-registry.py, or fall back."""
    try:
        result = subprocess.run(
            ["python3", "scripts/active-plan-registry.py", "session-id"],
            capture_output=True,
            text=True,
        )
        sid = result.stdout.strip()
        if sid:
            return sid
    except (subprocess.SubprocessError, OSError):
        pass
    # Fallback: generate a timestamp-based ID.
    return f"hermes-{int(time.time())}"


async def main_async():
    args = parse_args()

    # Resolve slug list; enforce mutual exclusion across --slug/--slugs/--plan-set.
    slugs = _validate_slug_set_args(args)

    # Load config and repo_root once — shared by both single-plan and cross-plan paths.
    config = load_config()
    repo_root = os.getcwd()

    # Install signal handler.
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))

    # --- Cross-plan path: only when there is genuinely more than one plan ---
    if len(slugs) > 1:
        for slug in slugs:
            if not validate_slug(slug):
                print(f"ERROR: Invalid slug '{slug}'", file=sys.stderr)
                sys.exit(2)
        sys.exit(await run_cross_plan(slugs, config, repo_root))

    # --- Single-slug path: --slug OR single-element --slugs/--plan-set ---
    slug = slugs[0]
    if not validate_slug(slug):
        print(f"ERROR: Invalid slug '{slug}'", file=sys.stderr)
        sys.exit(2)

    # plan_dir override is only meaningful for --slug; for --slugs/--plan-set it is None.
    plan_dir_override = getattr(args, "plan_dir", None)
    sys.exit(await run_single_plan(slug, plan_dir_override, config, repo_root))


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
