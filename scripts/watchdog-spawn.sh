#!/usr/bin/env bash
# watchdog-spawn.sh — Atomic single-spawn guard for watchdog-sweep.sh.
#
# Ensures exactly one live watchdog-sweep.sh process runs per run_id.
# Uses a flock'd PID file as the authoritative single-spawn guard.
#
# Usage:
#   watchdog-spawn.sh --run <run_id> [--plan-dir <dir>]
#
# --plan-dir: path to Z_HARNESS_PLAN_DIR (default: $Z_HARNESS_PLAN_DIR env).
#
# Exit codes:
#   0 — sweep spawned (new) or already live (idempotent skip)
#   1 — bad arguments
#   2 — sweep script not found
#
# PID file location:
#   $Z_HARNESS_PLAN_DIR/active/<run>.watchdog.pid
#
# Daemonization:
#   The sweep is spawned with stdio fully detached (</dev/null >/dev/null 2>&1)
#   and nohup so it survives the spawning shell's exit.  On platforms where
#   setsid(1) is available it is used for a new session; on macOS (no setsid
#   binary), Python os.setsid() achieves the same in the inline spawn logic.
#
# Lock model (authoritative):
#   The PID file is flock'd (Python fcntl.flock) during the check-and-spawn
#   critical section only (short-lived, not held for the daemon lifetime).
#   Unlike sink-lock.sh's long-lived holder daemon, this lock is released
#   immediately after writing the new PID.  Two concurrent spawn calls racing
#   on the same run_id will serialize through this flock: the first acquires,
#   spawns, writes pid, and releases; the second acquires, reads the live pid,
#   and skips.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve plugin root.
# ---------------------------------------------------------------------------
_WS_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
_WS_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Arg parse
# ---------------------------------------------------------------------------
RUN=""
PLAN_DIR_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN="$2"
      shift 2
      ;;
    --plan-dir)
      PLAN_DIR_ARG="$2"
      shift 2
      ;;
    *)
      echo "watchdog-spawn.sh: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$RUN" ]]; then
  echo "watchdog-spawn.sh: --run <run_id> is required" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Resolve plan dir
# ---------------------------------------------------------------------------
if [[ -n "$PLAN_DIR_ARG" ]]; then
  _WS_PLAN_DIR="$PLAN_DIR_ARG"
elif [[ -n "${Z_HARNESS_PLAN_DIR:-}" ]]; then
  _WS_PLAN_DIR="$Z_HARNESS_PLAN_DIR"
else
  _WS_PLAN_DIR="$_WS_PLUGIN_ROOT/z-harness"
fi

# active/ dir — must exist before the pid file can be written.
_WS_ACTIVE_DIR="$_WS_PLAN_DIR/active"
mkdir -p "$_WS_ACTIVE_DIR"

# PID file path (authoritative single-spawn store).
_WS_PID_FILE="$_WS_ACTIVE_DIR/${RUN}.watchdog.pid"

# Sweep script path (overridable for tests).
_WS_SWEEP="${WATCHDOG_SWEEP_SCRIPT:-$_WS_SCRIPTS_DIR/watchdog-sweep.sh}"

if [[ ! -f "$_WS_SWEEP" ]]; then
  echo "watchdog-spawn.sh: sweep script not found: $_WS_SWEEP" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Atomic check-and-spawn via inline Python (fcntl.flock on the PID file).
#
# The Python process:
#   1. Opens (O_CREAT | O_RDWR) the pid file.
#   2. Takes LOCK_EX (blocking — will serialize concurrent callers).
#   3. Reads the existing pid (if any).
#   4. If alive (kill -0 equivalent), prints "skip:<pid>" and exits 0.
#   5. Else spawns the sweep daemonized, writes new pid, prints "spawned:<pid>".
#   6. Releases the lock (file closed → OS releases flock).
#
# Daemonization in Python:
#   - os.setsid() — new session, no controlling terminal (available on macOS).
#   - Redirect stdin/stdout/stderr to /dev/null.
#   - os._exit(0) in child so atexit/Python cleanup doesn't fire.
#   Note: We use a fork-exec model (fork in Python, exec the sweep) so the
#   intermediate Python child can setsid before exec.  The grandchild (sweep)
#   inherits the new session and fully detaches.
# ---------------------------------------------------------------------------
_WS_RESULT="$(python3 - "$_WS_PID_FILE" "$_WS_SWEEP" "$RUN" \
  "$_WS_PLAN_DIR" \
  "${Z_HARNESS_REGISTRY_ENABLED:-1}" \
  <<'PYEOF'
import fcntl
import os
import sys
import time

pid_file   = sys.argv[1]
sweep_path = sys.argv[2]
run_id     = sys.argv[3]
plan_dir   = sys.argv[4]
registry_enabled = sys.argv[5]  # pass through to sweep via env

def pid_alive(pid):
    """Return True if the process is alive on this host."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but we lack permission to signal it — it's alive.
        return True

# Open the pid file (create if needed) and take an exclusive lock.
fd = os.open(pid_file, os.O_CREAT | os.O_RDWR, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX)

    # --- Critical section: check live pid, spawn if dead/absent. ---

    # Read existing pid.
    existing_pid = 0
    try:
        content = os.read(fd, 32).decode("utf-8", errors="replace").strip()
        if content.isdigit():
            existing_pid = int(content)
    except OSError:
        pass

    if existing_pid > 0 and pid_alive(existing_pid):
        # Already live — idempotent skip.
        print(f"skip:{existing_pid}")
        sys.exit(0)

    # Stale or empty — spawn a new sweep daemon.
    #
    # Fork an intermediate child.  The child calls os.setsid() (new session,
    # detaches from any controlling terminal), redirects stdio to /dev/null,
    # then execs the sweep.  The parent (this Python) reaps the intermediate
    # child immediately via waitpid; the exec'd grandchild (the actual sweep)
    # is adopted by init/launchd because its parent (the intermediate child)
    # execs away and the grandchild already has no controlling terminal.
    #
    # We capture the grandchild PID via a pipe written by the intermediate child
    # before exec'ing the sweep.

    pid_r, pid_w = os.pipe()

    child = os.fork()
    if child == 0:
        # --- Intermediate child ---
        # Close parent-read end; we write grandchild pid on pid_w.
        os.close(pid_r)
        # Detach from session.
        os.setsid()
        # Redirect stdin/stdout/stderr to /dev/null so the sweep never
        # inherits the calling tool's stdout fd.
        devnull = os.open("/dev/null", os.O_RDWR)
        os.dup2(devnull, 0)  # stdin
        os.dup2(devnull, 1)  # stdout
        os.dup2(devnull, 2)  # stderr
        if devnull > 2:
            os.close(devnull)

        # Fork the grandchild (actual sweep process).
        grandchild = os.fork()
        if grandchild == 0:
            # --- Grandchild (sweep) ---
            # Close the pipe fd — we don't need it.
            os.close(pid_w)
            # Build env for the sweep: pass plan_dir and registry_enabled.
            env = os.environ.copy()
            env["Z_HARNESS_PLAN_DIR"] = plan_dir
            env["Z_HARNESS_REGISTRY_ENABLED"] = registry_enabled
            os.execve(
                "/usr/bin/env",
                ["/usr/bin/env", "bash", sweep_path, "--run", run_id],
                env,
            )
            # execve never returns; if it does, hard exit.
            os._exit(127)
        else:
            # --- Intermediate child after forking grandchild ---
            # Write grandchild PID to pipe so parent can write the pid file.
            os.write(pid_w, str(grandchild).encode())
            os.close(pid_w)
            # Exit immediately so the grandchild is reparented to init.
            os._exit(0)
    else:
        # --- Parent ---
        os.close(pid_w)
        # Read grandchild PID from pipe.
        buf = b""
        while True:
            chunk = os.read(pid_r, 32)
            if not chunk:
                break
            buf += chunk
        os.close(pid_r)
        # Reap the intermediate child.
        try:
            os.waitpid(child, 0)
        except ChildProcessError:
            pass

        grandchild_pid_str = buf.decode("utf-8", errors="replace").strip()
        grandchild_pid = int(grandchild_pid_str) if grandchild_pid_str.isdigit() else 0

        # Write the new pid to the file (truncate first).
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, (str(grandchild_pid) + "\n").encode())

        print(f"spawned:{grandchild_pid}")

finally:
    # Close fd — OS releases LOCK_EX automatically on close.
    os.close(fd)
PYEOF
)"

_WS_RC="$?"

if [[ "$_WS_RC" -ne 0 ]]; then
  echo "watchdog-spawn.sh: spawn logic failed (rc=$_WS_RC)" >&2
  exit "$_WS_RC"
fi

# Log the outcome (non-fatal if log-event.sh is unavailable).
if [[ "$_WS_RESULT" == skip:* ]]; then
  : # already live — no action needed
elif [[ "$_WS_RESULT" == spawned:* ]]; then
  _WS_NEW_PID="${_WS_RESULT#spawned:}"
  # Best-effort telemetry (non-fatal).
  bash "$_WS_SCRIPTS_DIR/log-event.sh" "$RUN" "watchdog_spawned" \
    '{"run":"'"$RUN"'","pid":'"${_WS_NEW_PID:-0}"'}' \
    >/dev/null 2>&1 || true
fi

exit 0
