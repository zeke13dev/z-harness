"""
session.py — legacy pi z-execute lifecycle helpers.

Deprecated for Discord `so`: the former tmux launcher in this file was replaced
by `hermes/so_mcp.py`. Discord and gateway code must not import this module for
`so` orchestration.
"""

import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional

from hermes.schema import parse_session_status, SessionStatus




# ---------------------------------------------------------------------------
# spawn_session (T001)
# ---------------------------------------------------------------------------

def spawn_session(worktree_path: str, tasks_path: str) -> int:
    """Spawn pi z-execute in the worktree. Returns PID.
    
    The session runs in the worktree directory, targeting the
    workstream's TASKS.md via --tasks flag.
    """
    cmd = ["pi", "z-execute", f"--tasks={tasks_path}"]
    
    proc = subprocess.Popen(
        cmd,
        cwd=worktree_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # Detach from orchestrator's process group
    )
    
    print(f"  Spawned pi session: PID {proc.pid}, cwd={worktree_path}")
    return proc.pid


# ---------------------------------------------------------------------------
# poll_session (T002)
# ---------------------------------------------------------------------------

def poll_session(worktree_path: str) -> Optional[SessionStatus]:
    """Read session-status.json from the worktree.
    
    Returns SessionStatus or None if file missing/unparseable.
    """
    # session-status.json is written to $BASE/session-status.json
    # where $BASE is the workstream directory.
    # Check root first, then one level of subdirectories for z-plan-split plans.
    candidates = [os.path.join(worktree_path, "session-status.json")]
    try:
        for entry in os.scandir(worktree_path):
            if entry.is_dir() and not entry.name.startswith("."):
                sub = os.path.join(entry.path, "session-status.json")
                if os.path.exists(sub):
                    candidates.append(sub)
    except OSError:
        pass
    for path in candidates:
        status = parse_session_status(path)
        if status is not None:
            return status
    return None


# ---------------------------------------------------------------------------
# Stall detection + timeout enforcement (T003)
# ---------------------------------------------------------------------------

def check_stall(
    status: SessionStatus,
    last_updated_at: Optional[str],
    stall_minutes: int,
) -> bool:
    """Check if session appears stuck.
    
    Returns True if no progress detected within stall_minutes.
    """
    if status.status != "running":
        return False
    
    if last_updated_at is None:
        return False
    
    try:
        last = datetime.fromisoformat(last_updated_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        elapsed = (now - last).total_seconds() / 60
        return elapsed > stall_minutes
    except (ValueError, TypeError):
        return False


def check_timeout(
    session_start: float,
    timeout_minutes: int,
) -> bool:
    """Check if session exceeded wall-clock cap.
    
    Returns True if elapsed time exceeds timeout_minutes.
    """
    elapsed = (time.time() - session_start) / 60
    return elapsed > timeout_minutes


# ---------------------------------------------------------------------------
# Kill + re-spawn with retry counting (T004)
# ---------------------------------------------------------------------------

def kill_session(pid: int) -> None:
    """Kill a pi session gracefully, then forcefully.
    
    Sends SIGTERM to the process group (since spawn_session uses
    start_new_session=True), waits 5s, then SIGKILL if still alive.
    """
    if not is_session_alive(pid):
        return
    
    try:
        # Kill the process group to catch child subagents
        os.killpg(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(0.5)
            if not is_session_alive(pid):
                print(f"  Killed session PID {pid} (SIGTERM)")
                return
        
        # Force kill process group
        os.killpg(pid, signal.SIGKILL)
        time.sleep(0.5)
        print(f"  Force-killed session PID {pid} (SIGKILL)")
    except (OSError, ProcessLookupError):
        pass  # Already dead


def is_session_alive(pid: int) -> bool:
    """Check if process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def handle_crash(
    pid: int,
    retry_count: int,
    max_retries: int,
    retry_delay: int,
    worktree_path: str,
    tasks_path: str,
) -> tuple[Optional[int], int, bool]:
    """Handle a crashed session.
    
    Returns (new_pid, updated_retry_count, should_abort).
    """
    retry_count += 1
    
    if retry_count > max_retries:
        print(f"  Session crashed — max retries ({max_retries}) exhausted")
        return None, retry_count, True
    
    print(f"  Session crashed — retry {retry_count}/{max_retries}")
    time.sleep(retry_delay)
    
    new_pid = spawn_session(worktree_path, tasks_path)
    return new_pid, retry_count, False
