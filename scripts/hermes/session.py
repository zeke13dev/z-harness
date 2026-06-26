"""
session.py — Pi session lifecycle management.

C3 of the Hermes orchestrator. Spawns pi sessions in worktrees,
polls session-status.json, detects stalled/timed-out sessions,
and handles kill + re-spawn with retry counting.
"""

import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional, Protocol

from hermes.discord_relay import SoCommand
from hermes.schema import parse_session_status, SessionStatus
from hermes.so_jobs import SoJobRecord, SoJobRegistry, new_job_id


class CommandRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        ...


class SubprocessCommandRunner:
    def run(
        self,
        argv: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


class TmuxLaunchError(RuntimeError):
    pass


def hermes_tmux_session_name(job_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", job_id).strip("-")
    return f"hermes-so-{safe}"


def build_initial_so_prompt(command: SoCommand, job_id: str) -> str:
    z_part = (
        f"Use the z-harness command `{command.z_command}`."
        if command.z_command
        else "Use the appropriate z-harness command for this task."
    )
    return (
        "You are running under Hermes Discord supervision. "
        f"Hermes job id: {job_id}. "
        f"{z_part} "
        f"User task: {command.task}"
    )


def launch_so_job(
    command: SoCommand,
    registry: SoJobRegistry,
    *,
    runner: Optional[CommandRunner] = None,
    job_id: Optional[str] = None,
) -> SoJobRecord:
    """Create and launch a tmux-backed Hermes `so` job."""
    runner = runner or SubprocessCommandRunner()
    job_id = job_id or new_job_id()
    tmux_session = hermes_tmux_session_name(job_id)
    alias = command.project_alias
    record = SoJobRecord(
        job_id=job_id,
        discord_channel_id=command.discord_channel_id,
        discord_message_id=command.discord_message_id,
        discord_thread_id=command.discord_thread_id or command.discord_channel_id,
        requester_user_id=command.requester_user_id,
        host=command.host,
        project=command.project,
        repo_root=alias.repo_root,
        execution_host=alias.execution_host,
        transport=alias.transport,
        ssh_target=alias.ssh_target,
        workdir=alias.workdir,
        z_command=command.z_command,
        task=command.task,
        tmux_session=tmux_session,
        status="starting",
    )
    registry.create(record)

    env = dict(os.environ)
    env["HERMES_SO_JOB_ID"] = job_id
    workdir = alias.workdir or None
    new_session = runner.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            tmux_session,
            "-c",
            alias.workdir,
            command.host,
        ],
        cwd=workdir,
        env=env,
    )
    if new_session.returncode != 0:
        registry.transition(job_id, "failed")
        raise TmuxLaunchError(new_session.stderr or "tmux new-session failed")

    pid = None
    display = runner.run(
        ["tmux", "display-message", "-p", "-t", tmux_session, "#{pane_pid}"],
        cwd=workdir,
        env=env,
    )
    if display.returncode == 0:
        try:
            pid = int(display.stdout.strip())
        except ValueError:
            pid = None
    if pid is not None:
        record.pid = pid
        registry.save(record)

    prompt = build_initial_so_prompt(command, job_id)
    send = runner.run(
        ["tmux", "send-keys", "-t", tmux_session, prompt, "C-m"],
        cwd=workdir,
        env=env,
    )
    if send.returncode != 0:
        registry.transition(job_id, "failed")
        raise TmuxLaunchError(send.stderr or "tmux send-keys failed")

    return registry.transition(job_id, "running", pid=pid)


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
