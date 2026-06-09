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


# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Hermes orchestrator")
    p.add_argument("--slug", required=True, help="Plan slug")
    p.add_argument("--plan-dir", help="Plan directory override")
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
async def main_async():
    args = parse_args()
    if not validate_slug(args.slug):
        print(f"ERROR: Invalid slug '{args.slug}'", file=sys.stderr)
        sys.exit(2)

    plan_dir = resolve_plan_dir(args.slug, args.plan_dir)
    print(f"Plan dir: {plan_dir}")

    ws_path = os.path.join(plan_dir, "workstreams.json")
    if not os.path.exists(ws_path):
        print(f"ERROR: workstreams.json not found", file=sys.stderr)
        sys.exit(2)

    manifest = parse_workstreams_json(ws_path)
    print(f"Loaded: {len(manifest.workstreams)} ws, protocol={manifest.protocol}")

    gate_errs = validate_gates(manifest, plan_dir)
    if gate_errs:
        for e in gate_errs:
            print(f"GATE: {e}", file=sys.stderr)
        sys.exit(2)
    print("Gates: PASSED")

    config = load_config()
    repo_root = os.getcwd()

    signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))

    # --- Crash recovery (M2) ---
    state = attempt_recovery(args.slug, plan_dir, repo_root)
    if state:
        print(f"Resuming from previous run (phase: {state.phase})")
    else:
        state = OrchestratorState(slug=args.slug, phase="running")

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

    for ws_id in exec_order:
        ws = next(w for w in ready if w.id == ws_id)
        
        # Skip already-completed workstreams (from recovery)
        if ws_id in state.workstreams and state.workstreams[ws_id].status == "done":
            print(f"\n--- {ws_id}: {ws.name} --- [already done]")
            completed.append(ws_id)
            continue
        
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
                ws_state.status = "failed"; failed.append(ws_id)
                save_state(state, plan_dir); continue
        else:
            wt_path = ws_state.worktree_path
            print(f"  Reusing worktree: {wt_path}")

        # Spawn session (skip if recovered and alive)
        tasks_path = os.path.join(ws.path, "TASKS.md")
        if not os.path.exists(os.path.join(wt_path, tasks_path)):
            print(f"  TASKS.md not found at {wt_path}/{tasks_path}")
            ws_state.status = "failed"; failed.append(ws_id)
            save_state(state, plan_dir); continue
        resume_pid = ws_state.pid if ws_state.pid and is_session_alive(ws_state.pid) else None
        
        if not resume_pid:
            try:
                pid = spawn_session(wt_path, tasks_path)
                ws_state.pid = pid
            except Exception as e:
                print(f"  Spawn ERROR: {e}")
                ws_state.status = "failed"; failed.append(ws_id)
                save_state(state, plan_dir); continue
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
                ws_state.status = "failed"; failed.append(ws_id)
                try: kill_session(pid)
                except: pass
                break

            # Poll status FIRST — then check liveness only if not done
            status = poll_session(wt_path)

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
                        ws_state.status = "failed"; failed.append(ws_id)
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
                ws_state.status = "done"; completed.append(ws_id)
                break

            elif status.status == "halted":
                print(f"  HALTED: {status.halt_reason}")
                ws_state.status = "halted"
                ws_state.halt_reason = status.halt_reason
                save_state(state, plan_dir)

                # Relay question via Discord (M1)
                resolved = await relay_halt_question(ws_id, status, wt_path, tasks_path, config)
                if not resolved:
                    ws_state.status = "failed"; failed.append(ws_id)
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
                    ws_state.status = "failed"; failed.append(ws_id)
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
                    ws_state.status = "failed"; failed.append(ws_id)
                    break

        # Merge
        if ws_id in completed:
            print(f"  Merging...")
            merge_ok = False
            try:
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
                try:
                    delete_worktree(args.slug, ws_id, repo_root, config.paths.worktree_base)
                    print(f"  Cleaned up")
                except Exception as e:
                    print(f"  Cleanup WARNING: {e}")
            elif ws_id in completed:
                # Merge had conflicts — handle resolution
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
                    skipped.append(ws_id)
                    print(f"  Skipped {ws_id}")
                elif resolution == "4":  # Abort plan
                    from hermes.merge import abort_merge, revert_all_completed
                    abort_merge(repo_root)
                    revert_all_completed(completed, args.slug, repo_root)
                    print(f"  Aborted plan")
                    sys.exit(1)
                else:
                    print(f"  No resolution — keeping worktree for manual fix")
                print(f"  Cleanup WARNING: {e}")

        save_state(state, plan_dir)

    # Final
    print(f"\n--- Done ---")
    print(f"  Completed: {completed}")
    print(f"  Failed: {failed}")
    cleanup_orphaned(args.slug, set(completed + failed + skipped), repo_root, config.paths.worktree_base)
    clear_state(plan_dir)

    try:
        from hermes.discord_relay import disconnect
        await disconnect()
    except Exception:
        pass

    sys.exit(0 if not failed else 1)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
