"""
recovery.py — Crash recovery and state reconstruction.

C6 of the Hermes orchestrator. Persists orchestrator state for
crash resumption. On restart, reconstructs execution state from
workstreams.json, git branches, and session-status.json.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

from hermes.schema import (
    parse_workstreams_json,
    parse_session_status,
    WorkstreamsManifest,
    SessionStatus,
)
from hermes.state import (
    OrchestratorState,
    WorkstreamState,
    MergeProgress,
    save_state,
    load_state,
    clear_state,
)
from hermes.worktree import list_worktrees, get_worktree_info, SAFE_REF_RE


# ---------------------------------------------------------------------------
# Branch scanning (T002)
# ---------------------------------------------------------------------------

def scan_branches(slug: str, repo_root: str = ".") -> list[dict]:
    """Scan git branches for existing worktree state.
    
    Returns list of dicts with {ws_id, branch, worktree_path, head}.
    """
    existing = list_worktrees(slug, repo_root)
    result = []
    
    for ws_id in existing:
        info = get_worktree_info(slug, ws_id, repo_root)
        if info:
            result.append({
                "ws_id": ws_id,
                "branch": f"hermes/{slug}/{ws_id}",
                "worktree_path": info.get("path", ""),
                "head": info.get("head", ""),
            })
        else:
            result.append({
                "ws_id": ws_id,
                "branch": f"hermes/{slug}/{ws_id}",
                "worktree_path": "",
                "head": "",
            })
    
    return result


# ---------------------------------------------------------------------------
# State reconstruction (T003)
# ---------------------------------------------------------------------------

def reconstruct_state(
    slug: str,
    manifest: WorkstreamsManifest,
    plan_dir: str,
    repo_root: str = ".",
) -> OrchestratorState:
    """Reconstruct execution state after a crash.
    
    1. Reads workstreams.json for expected workstreams
    2. Scans git branches for existing worktrees
    3. Reads session-status.json per worktree for session state
    4. Merges with persisted hermes-state.json (persisted state wins)
    5. Returns reconstructed OrchestratorState
    """
    # Try loading persisted state first
    persisted = load_state(plan_dir)
    
    # Build fresh state from expected workstreams
    state = OrchestratorState(slug=slug, phase="init")
    
    active_ids = {w.id for w in manifest.workstreams if w.status == "ready"}
    failed_ids = {w.id for w in manifest.workstreams if w.status == "failed"}
    
    # Scan existing branches
    branches = scan_branches(slug, repo_root)
    branch_map = {b["ws_id"]: b for b in branches}
    
    # Reconstruct each workstream
    for ws in manifest.workstreams:
        ws_state = WorkstreamState(ws_id=ws.id, tasks_total=len(ws.tasks))
        
        if ws.id in failed_ids:
            ws_state.status = "failed"
            state.workstreams[ws.id] = ws_state
            continue
        
        branch_info = branch_map.get(ws.id)
        
        if branch_info and branch_info.get("worktree_path"):
            ws_state.worktree_path = branch_info["worktree_path"]
            ws_state.branch = branch_info["branch"]
            
            # Try reading session-status.json (check root + one level of subdirs)
            candidates = [os.path.join(branch_info["worktree_path"], "session-status.json")]
            try:
                for entry in os.scandir(branch_info["worktree_path"]):
                    if entry.is_dir() and not entry.name.startswith("."):
                        sub = os.path.join(entry.path, "session-status.json")
                        if os.path.exists(sub):
                            candidates.append(sub)
            except OSError:
                pass
            status = None
            for sp in candidates:
                status = parse_session_status(sp)
                if status is not None:
                    break
            
            if status:
                ws_state.tasks_done = status.tasks_done
                ws_state.current_task = status.current_task
                
                if status.status == "done":
                    ws_state.status = "done"
                elif status.status == "halted":
                    ws_state.status = "halted"
                    ws_state.halt_reason = status.halt_reason
                elif status.status == "paused":
                    ws_state.status = "running"  # Will be re-spawned
                else:
                    ws_state.status = "running"
            else:
                # No status file — session was just spawned or crashed
                ws_state.status = "running"
        else:
            # No branch exists — not started yet
            ws_state.status = "pending"
        
        state.workstreams[ws.id] = ws_state
    
    # Determine phase from workstream states
    statuses = [ws.status for ws in state.workstreams.values()]
    
    if any(s == "running" or s == "halted" for s in statuses):
        state.phase = "running"
    elif all(s in ("done", "failed", "skipped") for s in statuses):
        state.phase = "merging"
    elif all(s == "pending" for s in statuses):
        state.phase = "init"
    else:
        state.phase = "running"  # Conservative
    
    # Merge with persisted state (persisted state takes precedence for merge_progress)
    if persisted and persisted.merge_progress:
        state.merge_progress = persisted.merge_progress
        # Persisted phase may be more accurate for merge state
        if persisted.phase in ("merging", "cleanup"):
            state.phase = persisted.phase
    
    # Merge persisted workstream states (pid, retry_count)
    if persisted:
        for ws_id, pws in persisted.workstreams.items():
            if ws_id in state.workstreams:
                if pws.pid is not None:
                    state.workstreams[ws_id].pid = pws.pid
                state.workstreams[ws_id].retry_count = pws.retry_count
    
    print(f"  Reconstructed state: phase={state.phase}, "
          f"workstreams={len(state.workstreams)}")
    
    return state


# ---------------------------------------------------------------------------
# Recovery entry point (T004)
# ---------------------------------------------------------------------------

def attempt_recovery(
    slug: str,
    plan_dir: str,
    repo_root: str = ".",
) -> Optional[OrchestratorState]:
    """Attempt crash recovery on orchestrator start.
    
    Returns reconstructed state if a previous run was in progress,
    or None if this is a fresh start.
    """
    # Check for persisted state
    persisted = load_state(plan_dir)
    
    if not persisted:
        # No state file — check for branches (state file may have been lost)
        branches = scan_branches(slug, repo_root)
        if not branches:
            return None  # Fresh start
        else:
            print(f"  No state file, but {len(branches)} branch(es) found — reconstructing")
    else:
        print(f"  Found persisted state from {persisted.updated_at} (phase: {persisted.phase})")
    
    # Load manifest
    ws_path = os.path.join(plan_dir, "workstreams.json")
    if not os.path.exists(ws_path):
        print("  WARNING: workstreams.json not found — cannot reconstruct")
        return None
    
    manifest = parse_workstreams_json(ws_path)
    
    # Reconstruct
    state = reconstruct_state(slug, manifest, plan_dir, repo_root)
    
    # Determine if there's work to resume
    active = [
        ws_id for ws_id, ws in state.workstreams.items()
        if ws.status in ("running", "halted")
    ]
    pending = [
        ws_id for ws_id, ws in state.workstreams.items()
        if ws.status == "pending"
    ]
    
    if active or (state.phase == "merging"):
        print(f"  Recovery: {len(active)} active, {len(pending)} pending")
        return state
    
    print("  Recovery: no active work found — fresh start")
    clear_state(plan_dir)
    return None
