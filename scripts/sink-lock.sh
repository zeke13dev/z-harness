#!/usr/bin/env bash
# sink-lock.sh — Generic per-entry flock + heartbeat + stale-takeover primitive.
#
# Uses Python 3 + fcntl.flock for portable atomic locking (works on macOS and
# Linux without requiring the `flock` util from util-linux).
#
# LIFETIME MODEL
# ==============
# The OS-level LOCK_EX flock must be held for the *lifetime* of the lock, not
# just during the `acquire` call. Since each `sink-lock.sh` invocation is a
# separate process, a "background holder daemon" model is used:
#
#   acquire  — forks a small background Python daemon that opens the .flock
#              file, takes LOCK_EX (non-blocking), writes the JSON holder
#              record (with pid = the daemon's own PID), signals the parent
#              via a read-pipe (writes "ok\n"), then blocks on a write-pipe
#              waiting for SIGTERM/SIGHUP. The parent reads the confirmation
#              and exits 0.  The daemon's PID is stored in the `pid` field of
#              the JSON holder record — that is the process whose liveness
#              indicates whether the lock is genuinely held.
#
#              The daemon is the SINGLE arbitration point: if the daemon's
#              nonblocking flock attempt fails, we have contention; if it
#              succeeds, we have the lock. No pre-probe pattern is used
#              (avoids TOCTOU races).
#
#   heartbeat — takes LOCK_EX on the .hb.lock sentinel (same sentinel used
#               everywhere for JSON content) to update `last_heartbeat` in
#               the JSON. Verifies the daemon PID is still alive before
#               extending the timestamp (prevents dead daemons from having
#               their records refreshed indefinitely).
#
#   release  — reads the daemon PID from the JSON holder record (under .hb.lock),
#              optionally validates expected-holder/expected-pid ownership,
#              sends SIGTERM to the daemon, waits for flock availability via
#              a nonblocking LOCK_EX probe on the .flock file, then zeros the
#              content file under .hb.lock.
#
#   check-stale — takes LOCK_SH on .hb.lock to read the JSON; checks PID
#                 liveness and heartbeat age.
#
# SERIALIZATION MODEL (single, consistent)
# =========================================
# ALL JSON reads and writes use the .hb.lock file for serialization:
#   - Daemon startup: briefly acquires .hb.lock before writing initial record
#   - Daemon SIGTERM handler: briefly acquires .hb.lock before zeroing content
#   - heartbeat: LOCK_EX on .hb.lock during read+write
#   - check-stale: LOCK_SH on .hb.lock during read
#   - release: LOCK_EX on .hb.lock during read (ownership check) + final zero
#
# JSON CLASSIFICATION
# ====================
# read_lock_json() returns one of four values:
#   None          — free: empty/missing file, or literal JSON null
#   dict          — valid holder record with exactly {holder, pid, started_at,
#                   last_heartbeat} of the required types
#   _WRONG_SCHEMA — parseable JSON but not a valid holder record (e.g. '{}',
#                   record with pid as a string); treated as stale (subject to
#                   TTL takeover), NOT as free
#   _CORRUPT      — non-empty content that failed JSON parsing altogether;
#                   requires manual cleanup (exit 3)
#
# STALE-HEARTBEAT TAKEOVER
# ========================
# If the lock JSON says the holder is alive (pid alive) but the heartbeat is
# older than TTL, acquire performs a stale-heartbeat takeover:
#   1. Under .hb.lock: re-read JSON, re-check staleness, kill daemon PID.
#   2. Wait (up to 2s) for the .flock to become available via nonblocking probe.
#   3. Spawn the new daemon (which wins the LOCK_EX race).
#   4. Emit a stale-takeover log and return exit 2.
#
# Usage:
#   scripts/sink-lock.sh acquire <lock-path> <holder-id> [--ttl-seconds=N]
#   scripts/sink-lock.sh heartbeat <lock-path>
#   scripts/sink-lock.sh release <lock-path> [--expected-holder=X] [--expected-pid=N]
#   scripts/sink-lock.sh check-stale <lock-path> [--ttl-seconds=N]
#   scripts/sink-lock.sh read-holder <lock-path> [--ttl-seconds=N]
#
# Exit codes — acquire:
#   0 — acquired successfully (daemon running, flock held)
#   1 — contention (lock is live, held by a live daemon process)
#   2 — stale-takeover succeeded (stale lock replaced by new daemon)
#   3 — corrupt lock file (non-empty but JSON-unparseable); manual cleanup required
# Exit codes — heartbeat:
#   0 — updated successfully
#   1 — lock file not found, empty, or daemon no longer alive
# Exit codes — release:
#   0 — released (daemon killed, content zeroed)
#   1 — lock file not found
#   4 — ownership validation failed (wrong holder or wrong PID)
#   5 — release failed: daemon did not exit within timeout (flock still held)
# Exit codes — check-stale (read-only, no takeover):
#   0 — held and live
#   1 — free (no lock file or empty)
#   2 — stale (held but PID dead or heartbeat too old; also wrong-schema JSON)
#   3 — corrupt lock file (non-empty but JSON-unparseable); manual cleanup required
# Exit codes — read-holder (read-only, prints JSON to stdout):
#   0 — printed {"state":"held",...} or {"state":"free"}
#   3 — corrupt lock file (non-empty but JSON-unparseable); manual cleanup required

set -euo pipefail

_usage() {
    cat >&2 <<'EOF'
Usage:
  scripts/sink-lock.sh acquire <lock-path> <holder-id> [--ttl-seconds=N]
  scripts/sink-lock.sh heartbeat <lock-path>
  scripts/sink-lock.sh release <lock-path> [--expected-holder=X] [--expected-pid=N]
  scripts/sink-lock.sh check-stale <lock-path> [--ttl-seconds=N]
  scripts/sink-lock.sh read-holder <lock-path> [--ttl-seconds=N]
EOF
    exit 2
}

[[ $# -lt 1 ]] && _usage

SUBCOMMAND="$1"
shift

# All real work is delegated to Python (fcntl.flock is cross-platform and
# avoids the macOS fork-safety crash when using bash-subshell flock).
exec python3 - "$SUBCOMMAND" "$@" <<'PYEOF'
import fcntl
import json
import os
import signal
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_TTL_SECONDS = 7200


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_to_epoch(ts: str) -> int:
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


_CORRUPT      = object()  # sentinel: non-empty content that failed JSON parse
_WRONG_SCHEMA = object()  # sentinel: parseable JSON but not a valid holder record

# Required holder-record fields and their expected Python types.
_REQUIRED_FIELDS = {
    "holder": str,
    "pid": int,
    "started_at": str,
    "last_heartbeat": str,
}


def _is_valid_timestamp(ts) -> bool:
    """Return True only if ts is a string matching strict UTC ISO-8601: YYYY-MM-DDTHH:MM:SSZ."""
    if not isinstance(ts, str):
        return False
    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return True
    except ValueError:
        return False


def _is_valid_holder_record(parsed) -> bool:
    """Return True only if parsed is a dict with exactly the required fields and types.

    Timestamps (started_at, last_heartbeat) must be strict UTC ISO-8601
    (YYYY-MM-DDTHH:MM:SSZ with valid calendar values); any non-parseable or
    out-of-range value (e.g. 2026-13-45T99:99:99Z) is rejected as wrong-schema.
    """
    if not isinstance(parsed, dict):
        return False
    if set(parsed.keys()) != set(_REQUIRED_FIELDS.keys()):
        return False
    for field, expected_type in _REQUIRED_FIELDS.items():
        if not isinstance(parsed[field], expected_type):
            return False
    # holder must be non-empty
    if not parsed["holder"]:
        return False
    # pid must be a positive integer in a plausible range
    pid = parsed["pid"]
    if not isinstance(pid, int) or pid <= 0 or pid > 4194304:
        return False
    # timestamps must be strict UTC ISO-8601 with valid calendar values
    if not _is_valid_timestamp(parsed["started_at"]):
        return False
    if not _is_valid_timestamp(parsed["last_heartbeat"]):
        return False
    return True


def read_lock_json(lock_path: Path):
    """Return parsed lock dict, None (free/empty), _WRONG_SCHEMA, or _CORRUPT.

    - None          → legitimately released (zero bytes / empty content / null JSON)
    - dict          → valid holder record (exactly {holder, pid, started_at, last_heartbeat})
    - _WRONG_SCHEMA → parseable JSON but wrong schema (e.g. '{}', pid as string);
                      treated as stale by callers (subject to TTL takeover, not free)
    - _CORRUPT      → non-empty file that failed JSON parsing; requires manual cleanup

    This three-way split enforces the holder-record contract from finding 8:
    non-empty JSON that is not a valid holder record is treated as stale (takeover),
    NOT as free — preventing silent overwrites of non-empty malformed lock files.
    """
    try:
        content = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return _CORRUPT
    # null → free (explicit "no record" marker)
    if parsed is None:
        return None
    # Valid holder record?
    if _is_valid_holder_record(parsed):
        return parsed
    # Parseable JSON but wrong schema → treat as stale (not free, not corrupt)
    return _WRONG_SCHEMA


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # PID exists but we can't signal it — still alive
        return True


def _pid_is_sink_lock_daemon(pid: int, lock_path: Path = None) -> bool:
    """Return True if the process at pid appears to be a sink-lock daemon.

    The daemon is a Python process whose argv contains the lock file path (and
    related sentinel paths derived from it).  We look for a unique marker string
    embedded in the daemon's -c code: 'zero_lock_under_hblock', which is a
    function name that only appears in _DAEMON_CODE.

    Additional confirmation: if lock_path is provided, the lock path string
    must appear in the command line.

    If the identity cannot be determined (process gone, permissions denied,
    or the query fails), returns None to indicate "unknown" — the caller
    will proceed with kill on unknown (safe default: if the process has our
    recorded PID it almost certainly is our daemon, and if it exited the kill
    will be a benign ESRCH).
    Returns False only when we can confirm it is NOT our daemon.

    Reads /proc/<pid>/cmdline on Linux; falls back to `ps -o command= -p <pid>`
    on macOS and other POSIX systems.
    """
    import subprocess as _subprocess

    _DAEMON_MARKER = "zero_lock_under_hblock"

    def _check_cmdline(cmdline: str):
        """Return True/False/None for the tri-state identity check.

        True  — _DAEMON_MARKER is present (and lock_path matches if provided) →
                confirmed our daemon, safe to kill.
        False — process cmdline is readable but _DAEMON_MARKER is absent →
                confirmed NOT our daemon, must NOT kill.
        None  — cmdline is empty or indeterminate → unknown, callers fall back
                to their existing unknown-handling.

        Requiring the marker (not just the lock path) prevents false confirmation
        of unrelated processes (debuggers, CI runners, scripts) that happen to
        receive the lock path as an argument.
        """
        if not cmdline:
            return None
        if _DAEMON_MARKER not in cmdline:
            # Marker absent — confirmed NOT our daemon regardless of path
            return False
        # Marker present; if lock_path provided, also require path match to
        # distinguish two concurrent daemons for different lock files.
        if lock_path is not None and str(lock_path) not in cmdline:
            return False
        return True

    # Linux: /proc/<pid>/cmdline is NUL-separated argv
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            raw = proc_cmdline.read_bytes()
            cmdline = " ".join(a.decode(errors="replace") for a in raw.split(b"\x00") if a)
            result = _check_cmdline(cmdline)
            if result is not None:
                return result
            return None  # empty cmdline — unknown
        except OSError:
            pass

    # macOS / other POSIX: use `ps -o command= -p <pid>`
    try:
        result = _subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            # ps failed — process may have exited; treat as unknown (allow kill)
            return None
        cmd_text = result.stdout.strip()
        chk = _check_cmdline(cmd_text)
        if chk is not None:
            return chk
        return None  # empty cmdline from ps — unknown
    except (OSError, _subprocess.TimeoutExpired):
        pass

    # Cannot determine — unknown
    return None


def is_lock_stale(data: dict, ttl: int) -> bool:
    """Return True if the lock should be considered stale.

    Stale if PID is dead OR heartbeat is older than TTL (either condition alone
    is sufficient per spec: "PID check OR heartbeat older than TTL").
    """
    held_pid = data.get("pid")
    held_hb = data.get("last_heartbeat", "")

    pid_dead = True
    if held_pid is not None:
        try:
            pid_dead = not pid_alive(int(held_pid))
        except (ValueError, TypeError, OverflowError):
            # Non-numeric, non-castable, or astronomically large pid — treat as dead (stale)
            pid_dead = True

    hb_old = True
    if held_hb:
        try:
            hb_epoch = iso_to_epoch(held_hb)
            age = int(datetime.now(timezone.utc).timestamp()) - hb_epoch
            hb_old = age >= ttl
        except ValueError:
            pass

    return pid_dead or hb_old


def _hb_lock_path(lock_path: Path) -> Path:
    """Return the .hb.lock sentinel path used for ALL JSON content serialization."""
    return Path(str(lock_path) + ".hb.lock")


def _acquire_hb_lock(lock_path: Path, shared: bool = False) -> int:
    """Open the .hb.lock sentinel and take LOCK_EX (or LOCK_SH if shared=True).

    Returns the open fd.  Caller is responsible for os.close(fd).
    """
    hb_lock_file = _hb_lock_path(lock_path)
    hb_fd = os.open(str(hb_lock_file), os.O_CREAT | os.O_RDWR, 0o644)
    mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    fcntl.flock(hb_fd, mode)
    return hb_fd


# ---------------------------------------------------------------------------
# Background holder daemon
# ---------------------------------------------------------------------------
# The daemon is a standalone Python program (embedded as a string) that:
#   1. Opens the .flock file and takes LOCK_EX (non-blocking) — this is the
#      SINGLE arbitration point; no pre-probe in the parent.
#   2. On success, installs SIGTERM/SIGHUP handlers BEFORE publishing the
#      holder record (fixes signal-handler installation race: finding 7).
#   3. Briefly acquires .hb.lock (LOCK_EX), writes the JSON holder record,
#      releases .hb.lock.  Then signals the parent via the ready-pipe.
#   4. On failure (contention) writes "err:1:contention\n" and exits.
#   5. Blocks indefinitely using signal.pause() until SIGTERM/SIGHUP fires.
#      The signal handler: briefly acquires .hb.lock, zeros the content file,
#      releases .hb.lock, closes the flock fd, and exits.
#
# Communication: parent creates one pipe before forking.
#   ready_r, ready_w  — daemon writes "ok\n" or "err:<code>:<msg>\n" then
#                       closes ready_w.  Parent reads this to know the outcome.
#
# On macOS (and many Linux configs), os.pipe() returns fds with FD_CLOEXEC set.
# We clear FD_CLOEXEC on ready_w (the daemon-facing end) so it survives execv.

_DAEMON_CODE = textwrap.dedent("""\
    import fcntl, json, os, signal, sys, time
    from datetime import datetime, timezone
    from pathlib import Path

    def iso_now():
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def write_lock_json_under_hblock(hb_lock_file, lock_path, holder, pid, started_at, last_heartbeat):
        hb_fd = os.open(str(hb_lock_file), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(hb_fd, fcntl.LOCK_EX)
            obj = {"holder": holder, "pid": pid,
                   "started_at": started_at, "last_heartbeat": last_heartbeat}
            tmp = lock_path.parent / (lock_path.name + f".tmp.{os.getpid()}")
            tmp.write_text(json.dumps(obj) + "\\n", encoding="utf-8")
            tmp.rename(lock_path)
        finally:
            os.close(hb_fd)

    def zero_lock_under_hblock(hb_lock_file, lock_path):
        hb_fd = os.open(str(hb_lock_file), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(hb_fd, fcntl.LOCK_EX)
            try:
                lock_path.write_text("", encoding="utf-8")
            except OSError:
                pass
        finally:
            os.close(hb_fd)

    flock_file_str, lock_path_str, hb_lock_file_str, holder_id, started_at, ready_w_fd_str = sys.argv[1:]
    ready_w = int(ready_w_fd_str)

    flock_file    = Path(flock_file_str)
    lock_path     = Path(lock_path_str)
    hb_lock_file  = Path(hb_lock_file_str)

    # Open flock sentinel file
    try:
        fd = os.open(str(flock_file), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        os.write(ready_w, ("err:3:open_failed:" + str(e) + "\\n").encode())
        os.close(ready_w)
        sys.exit(3)

    # Non-blocking exclusive flock — single arbitration point (no TOCTOU probe)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Could not get the flock — contention
        os.close(fd)
        os.write(ready_w, b"err:1:contention\\n")
        os.close(ready_w)
        sys.exit(1)

    # We hold the flock.

    # Install SIGTERM/SIGHUP handlers BEFORE publishing the holder record.
    # This eliminates the signal-handler installation race (finding 7): if a
    # SIGTERM arrives in the window between "flock acquired" and "handlers
    # installed", the handler fires and cleans up correctly rather than leaving
    # stale JSON in the lock file.
    _fd = fd
    _lock_path = lock_path
    _hb_lock_file = hb_lock_file

    def _on_exit(signum, frame):
        try:
            zero_lock_under_hblock(_hb_lock_file, _lock_path)
        except Exception:
            pass
        try:
            os.close(_fd)
        except OSError:
            pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_exit)
    signal.signal(signal.SIGHUP,  _on_exit)

    # Write the holder record AFTER handlers are installed.
    now = iso_now()
    daemon_pid = os.getpid()
    write_lock_json_under_hblock(hb_lock_file, lock_path, holder_id, daemon_pid, started_at, now)

    # Signal parent: acquired
    os.write(ready_w, b"ok\\n")
    os.close(ready_w)

    # Block indefinitely waiting for SIGTERM/SIGHUP from cmd_release.
    # signal.pause() sleeps until any signal arrives.  We loop in case
    # non-terminal signals arrive (e.g. SIGCHLD).
    while True:
        signal.pause()
""")


def _spawn_holder_daemon(
    flock_file: Path,
    lock_path: Path,
    hb_lock_file: Path,
    holder_id: str,
    started_at: str,
) -> tuple[int, str]:
    """Fork a background flock-holder daemon.

    Returns (exit_code, message) where exit_code is:
      0  — daemon is running and holds the lock; daemon PID is in lock JSON
      1  — contention (another process holds the flock)
      3  — error (open failure or unexpected)
    """
    # Create the ready-pipe: daemon writes "ok\n" or "err:<code>:<msg>\n"
    ready_r, ready_w = os.pipe()

    # On macOS (and many Linux configs), os.pipe() sets FD_CLOEXEC by default.
    # Ensure FD_CLOEXEC on the parent-read end (ready_r) so it doesn't leak
    # into unrelated subprocesses, and CLEAR FD_CLOEXEC on ready_w so the
    # daemon inherits it across execv.
    flags = fcntl.fcntl(ready_r, fcntl.F_GETFD)
    fcntl.fcntl(ready_r, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
    flags = fcntl.fcntl(ready_w, fcntl.F_GETFD)
    fcntl.fcntl(ready_w, fcntl.F_SETFD, flags & ~fcntl.FD_CLOEXEC)

    child_pid = os.fork()
    if child_pid == 0:
        # --- CHILD (daemon) ---
        # Close parent-only end
        os.close(ready_r)
        # Detach from terminal / session
        os.setsid()
        # Redirect stdio to /dev/null to fully daemonize.
        # Guard: only close devnull if it doesn't overlap with ready_w.
        devnull = os.open("/dev/null", os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        if devnull != ready_w:
            os.close(devnull)
        # Exec the daemon code in the same Python interpreter
        os.execv(sys.executable, [
            sys.executable, "-c", _DAEMON_CODE,
            str(flock_file), str(lock_path), str(hb_lock_file),
            holder_id, started_at,
            str(ready_w),
        ])
        # execv never returns; if it fails, exit
        os._exit(127)

    # --- PARENT ---
    # Close daemon-only end
    os.close(ready_w)

    # Read the ready signal from daemon (blocks until daemon writes or exits)
    buf = b""
    try:
        while b"\n" not in buf:
            chunk = os.read(ready_r, 64)
            if not chunk:
                break
            buf += chunk
    except OSError:
        pass
    finally:
        os.close(ready_r)

    # Reap the child if it exited immediately (contention / error paths)
    try:
        os.waitpid(child_pid, os.WNOHANG)
    except ChildProcessError:
        pass

    line = buf.decode(errors="replace").strip()
    if line == "ok":
        return 0, "acquired"
    if line.startswith("err:"):
        parts = line.split(":", 2)
        try:
            code = int(parts[1])
        except (IndexError, ValueError):
            code = 3
        msg = parts[2] if len(parts) > 2 else "unknown"
        return code, msg
    # Unexpected / empty → treat as error
    return 3, f"unexpected daemon response: {line!r}"


def _wait_flock_free(flock_file: Path, max_wait: float = 2.0, poll_interval: float = 0.05) -> bool:
    """Poll until the .flock file becomes acquirable via LOCK_EX|LOCK_NB.

    Returns True if the flock became free within max_wait seconds, False if it
    remained contended.  Does NOT hold the lock — opens, tries, closes.
    """
    deadline = time.monotonic() + max_wait
    while True:
        probe_fd = os.open(str(flock_file), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Acquired — flock is free
            return True
        except BlockingIOError:
            pass
        finally:
            os.close(probe_fd)
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


def _do_stale_takeover(
    lock_path: Path,
    flock_file: Path,
    hb_lock_file: Path,
    holder_id: str,
    stale_data,  # dict or _WRONG_SCHEMA
    ttl: int,
) -> int:
    """Perform stale-takeover: kill stale daemon, wait for flock, spawn new daemon.

    Returns:
      2  — takeover succeeded
      1  — flock still held after timeout (bail out)
      3  — spawn error
    """
    stale_pid = stale_data.get("pid") if isinstance(stale_data, dict) else None
    stale_holder = stale_data.get("holder") if isinstance(stale_data, dict) else "<wrong-schema>"

    print(
        f"sink-lock: stale-takeover of lock '{lock_path}' "
        f"(previous holder='{stale_holder}' pid={stale_pid})",
        file=sys.stderr,
    )

    # Kill stale daemon under .hb.lock (serialize against heartbeat)
    hb_fd = _acquire_hb_lock(lock_path)
    try:
        # Re-verify: only kill if the record still looks stale
        data2 = read_lock_json(lock_path)
        kill_pid = None
        if data2 is _WRONG_SCHEMA:
            # Wrong-schema data: still extract a plausible integer pid if present,
            # so we can kill the stale daemon holding the flock.
            try:
                raw_json = lock_path.read_text(encoding="utf-8").strip()
                parsed_ws = json.loads(raw_json)
                if isinstance(parsed_ws, dict):
                    candidate = parsed_ws.get("pid")
                    if isinstance(candidate, int) and 0 < candidate <= 4194304:
                        kill_pid = candidate
            except (OSError, json.JSONDecodeError, TypeError):
                pass
        elif isinstance(data2, dict) and is_lock_stale(data2, ttl):
            kill_pid = data2.get("pid")

        if kill_pid is not None:
            try:
                kill_pid = int(kill_pid)
                # Safety check: verify the target is actually our daemon before signaling.
                identity = _pid_is_sink_lock_daemon(kill_pid, lock_path=lock_path)
                if identity is False:
                    # Confirmed NOT our daemon — do not kill; treat as contention
                    print(
                        f"sink-lock: stale-takeover: pid={kill_pid} failed identity check "
                        f"(not a sink-lock daemon); skipping kill",
                        file=sys.stderr,
                    )
                    kill_pid = None
                else:
                    # identity is True (confirmed) or None (unknown but plausible) — kill
                    os.kill(kill_pid, signal.SIGTERM)
            except (ValueError, TypeError, OverflowError, ProcessLookupError, PermissionError):
                pass
    finally:
        os.close(hb_fd)

    # Wait for the .flock to be released by the dying daemon
    flock_free = _wait_flock_free(flock_file, max_wait=2.0)
    if not flock_free:
        print(
            f"sink-lock: stale-takeover failed: flock still held after 2s "
            f"(pid={stale_pid}); aborting takeover",
            file=sys.stderr,
        )
        return 1

    # Spawn new daemon
    now2 = iso_now()
    code2, msg2 = _spawn_holder_daemon(flock_file, lock_path, hb_lock_file, holder_id, now2)
    if code2 == 0:
        return 2
    if code2 == 1:
        return 1  # lost the race
    print(
        f"sink-lock: daemon failed to acquire lock '{lock_path}': {msg2}",
        file=sys.stderr,
    )
    return 3


def cmd_acquire(lock_path: Path, holder_id: str, ttl: int) -> int:
    """Acquire the per-entry lock via a background holder daemon.

    The daemon is the SINGLE arbitration point: it opens the .flock sentinel
    file and attempts LOCK_EX|LOCK_NB.  Success → acquired; failure →
    contention.  No pre-probe pattern is used, eliminating the TOCTOU race.

    Stale-heartbeat takeover path (when the flock IS contended but the JSON
    says the holder's heartbeat is expired):
      1. Under .hb.lock: re-verify staleness, kill the recorded daemon PID.
      2. Wait for the .flock to become free (up to 2s).
      3. Spawn new daemon (which wins the newly-free LOCK_EX).
      4. Return exit 2.

    Wrong-schema JSON (e.g. '{}', non-numeric pid) is treated as stale for
    takeover purposes (finding 8) — it is NOT treated as free.

    Exit codes:
      0 — acquired (daemon running, flock held)
      1 — contention (another daemon holds the flock and is live)
      2 — stale-takeover (old lock was stale; new daemon now holds it)
      3 — corrupt lock or open failure
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flock_file = Path(str(lock_path) + ".flock")
    flock_file.parent.mkdir(parents=True, exist_ok=True)
    hb_lock_file = _hb_lock_path(lock_path)

    # Read JSON under .hb.lock for a consistent snapshot BEFORE spawning.
    # This lets us classify the pre-existing state (free/stale/live/corrupt)
    # before the daemon wins or loses the flock.
    hb_fd = _acquire_hb_lock(lock_path)
    try:
        pre_data = read_lock_json(lock_path)
    finally:
        os.close(hb_fd)

    if pre_data is _CORRUPT:
        print(
            f"sink-lock: corrupt lock file '{lock_path}' — "
            "non-empty but JSON-unparseable; manual cleanup required",
            file=sys.stderr,
        )
        return 3

    # Determine pre-spawn classification:
    #   pre_is_stale  — whether the pre-existing content is stale/wrong-schema
    #   pre_has_data  — whether there was any pre-existing content
    pre_has_data = pre_data is not None
    if pre_data is _WRONG_SCHEMA:
        pre_is_stale = True
    elif isinstance(pre_data, dict):
        pre_is_stale = is_lock_stale(pre_data, ttl)
    else:
        pre_is_stale = False

    now = iso_now()

    # Spawn daemon — LOCK_EX|LOCK_NB is the single arbitration point.
    code, msg = _spawn_holder_daemon(flock_file, lock_path, hb_lock_file, holder_id, now)

    if code == 0:
        # Daemon won the flock.  If there was pre-existing content (stale or
        # apparently-live-but-flock-was-free because previous daemon died),
        # report as takeover.
        if pre_has_data:
            if pre_data is _WRONG_SCHEMA or pre_is_stale:
                print(
                    f"sink-lock: stale-takeover of lock '{lock_path}' "
                    f"(flock was free; previous content was stale/wrong-schema)",
                    file=sys.stderr,
                )
            else:
                # Pre-existing content looked live but flock was free (daemon died)
                print(
                    f"sink-lock: stale-takeover of lock '{lock_path}' "
                    f"(flock was free but content appeared live; previous daemon likely died)",
                    file=sys.stderr,
                )
            return 2
        return 0

    if code == 1:
        # Flock is contended.
        if not pre_has_data:
            # No content — daemon may be in startup. Contention.
            return 1

        if pre_data is _WRONG_SCHEMA:
            # Wrong-schema JSON with a live flock → stale takeover
            return _do_stale_takeover(lock_path, flock_file, hb_lock_file,
                                      holder_id, pre_data, ttl)

        if not pre_is_stale:
            # Live lock, live daemon. Contention.
            return 1

        # Stale content + contended flock → stale-heartbeat takeover
        return _do_stale_takeover(lock_path, flock_file, hb_lock_file,
                                  holder_id, pre_data, ttl)

    # code == 3 or unexpected error from daemon
    print(
        f"sink-lock: daemon failed to acquire lock '{lock_path}': {msg}",
        file=sys.stderr,
    )
    return 3


def cmd_heartbeat(lock_path: Path) -> int:
    if not lock_path.exists():
        print(f"sink-lock: lock file not found: {lock_path}", file=sys.stderr)
        return 1

    # Take LOCK_EX on .hb.lock — the single consistent serialization for JSON I/O.
    hb_fd = _acquire_hb_lock(lock_path)
    try:
        data = read_lock_json(lock_path)
        if data is _CORRUPT:
            print(
                f"sink-lock: corrupt lock file '{lock_path}' — "
                "non-empty but JSON-unparseable; manual cleanup required",
                file=sys.stderr,
            )
            return 3
        if data is _WRONG_SCHEMA or data is None:
            # Wrong-schema or empty — nothing live to heartbeat
            return 1

        # MAJOR 5: Verify the daemon PID is still alive before extending
        # last_heartbeat.  A dead daemon's record must not be refreshed
        # indefinitely, as that would defeat TTL-based stale detection.
        daemon_pid = data.get("pid")
        if daemon_pid is None or not pid_alive(int(daemon_pid)):
            print(
                f"sink-lock: heartbeat skipped: daemon pid={daemon_pid} is no longer alive",
                file=sys.stderr,
            )
            return 1

        data["last_heartbeat"] = iso_now()
        tmp = lock_path.parent / (lock_path.name + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(data) + "\n", encoding="utf-8")
        tmp.rename(lock_path)
        return 0
    finally:
        os.close(hb_fd)


def cmd_release(lock_path: Path, expected_holder: str | None, expected_pid: int | None) -> int:
    """Release the lock by killing the holder daemon and zeroing the content.

    If expected_holder and/or expected_pid are provided, the caller's identity
    is verified against the JSON record before killing the daemon.  A mismatch
    returns exit 4 (ownership validation failed) without touching the lock.

    After sending SIGTERM to the daemon, waits for the .flock to become free
    via a nonblocking probe (finding 6: zombie detection).  If the flock
    remains held after the timeout, returns exit 5 rather than silently
    declaring success.

    Exit codes:
      0 — released
      1 — lock file not found
      4 — ownership validation failed
      5 — release failed: flock still held after timeout
    """
    if not lock_path.exists():
        print(f"sink-lock: lock file not found: {lock_path}", file=sys.stderr)
        return 1

    flock_file = Path(str(lock_path) + ".flock")
    daemon_pid = None
    _wrong_schema_release = False  # set if we took the wrong-schema kill path

    # Read the holder record under .hb.lock for a consistent snapshot.
    hb_fd = _acquire_hb_lock(lock_path)
    try:
        data = read_lock_json(lock_path)
        if data is _CORRUPT:
            # Corrupt — zero the file and move on (no daemon to kill)
            lock_path.write_text("", encoding="utf-8")
            return 0
        if data is _WRONG_SCHEMA:
            # Wrong-schema: attempt to extract a plausible integer pid and kill
            # the daemon that may still be holding the OS-level flock.  Without
            # this step, a live daemon keeps the flock held forever while the JSON
            # looks "released" — a deadlock for all future acquires.
            ws_kill_pid = None
            try:
                raw_ws = lock_path.read_text(encoding="utf-8").strip()
                parsed_ws = json.loads(raw_ws)
                if isinstance(parsed_ws, dict):
                    candidate = parsed_ws.get("pid")
                    if isinstance(candidate, int) and 0 < candidate <= 4194304:
                        ws_kill_pid = candidate
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            if ws_kill_pid is not None:
                try:
                    identity = _pid_is_sink_lock_daemon(ws_kill_pid, lock_path=lock_path)
                    if identity is False:
                        print(
                            f"sink-lock: release wrong-schema: pid={ws_kill_pid} failed identity "
                            f"check (not a sink-lock daemon); skipping kill",
                            file=sys.stderr,
                        )
                        ws_kill_pid = None
                    else:
                        os.kill(ws_kill_pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError, ValueError, TypeError, OverflowError):
                    ws_kill_pid = None
            daemon_pid = ws_kill_pid
            _wrong_schema_release = True
        if not _wrong_schema_release:
            # Normal path: None / valid-dict
            if data is None:
                # Already released
                return 0

            daemon_pid = data.get("pid")

            # Ownership validation (finding 4)
            if expected_holder is not None and data.get("holder") != expected_holder:
                print(
                    f"sink-lock: release ownership mismatch: "
                    f"expected holder='{expected_holder}' but lock has holder='{data.get('holder')}'",
                    file=sys.stderr,
                )
                return 4
            if expected_pid is not None and daemon_pid != expected_pid:
                print(
                    f"sink-lock: release ownership mismatch: "
                    f"expected pid={expected_pid} but lock has pid={daemon_pid}",
                    file=sys.stderr,
                )
                return 4

            # Kill the daemon — but first verify identity to avoid killing unrelated processes.
            if daemon_pid is not None:
                try:
                    daemon_pid_int = int(daemon_pid)
                    # Safety check: verify the target is actually our daemon before signaling.
                    identity = _pid_is_sink_lock_daemon(daemon_pid_int, lock_path=lock_path)
                    if identity is False:
                        # Confirmed NOT our daemon — do not kill.
                        print(
                            f"sink-lock: release: pid={daemon_pid_int} failed identity check "
                            f"(not a sink-lock daemon); skipping kill",
                            file=sys.stderr,
                        )
                        daemon_pid = None
                    else:
                        # identity is True (confirmed) or None (unknown but plausible) — kill
                        os.kill(daemon_pid_int, signal.SIGTERM)
                        daemon_pid = daemon_pid_int
                except (ValueError, TypeError, OverflowError, ProcessLookupError):
                    daemon_pid = None  # already dead — fine
    finally:
        os.close(hb_fd)

    # Wait for the .flock to be released (finding 6: zombie/stuck-daemon detection).
    # _wait_flock_free probes via LOCK_EX|LOCK_NB — correctly distinguishes
    # "daemon exited and released the fd" from "zombie still holds the fd open".
    flock_free = _wait_flock_free(flock_file, max_wait=2.0)
    if not flock_free:
        print(
            f"sink-lock: release timed out: flock still held after 2s "
            f"(daemon pid={daemon_pid} may be a zombie); manual cleanup required",
            file=sys.stderr,
        )
        return 5

    # Try to reap if this process is the parent (avoids zombie accumulation)
    if daemon_pid is not None:
        try:
            os.waitpid(int(daemon_pid), os.WNOHANG)
        except (ChildProcessError, OSError, ValueError, TypeError):
            pass

    # BLOCKER fix: Compare-and-clear the content file under .hb.lock.
    # A new concurrent acquire may have won the flock in the window between our
    # SIGTERM and here.  Only zero the record if it still belongs to the daemon
    # we just killed (matching pid+holder).  If the record has changed, a new
    # holder wrote their record — do NOT zero it.
    # Note: `data` may be _WRONG_SCHEMA here if we took the wrong-schema kill path;
    # released_holder is derived safely via isinstance(data, dict) guard.
    released_pid = daemon_pid  # pid we sent SIGTERM to (may be None if already dead)
    released_holder = data.get("holder") if isinstance(data, dict) else None

    hb_fd2 = _acquire_hb_lock(lock_path)
    try:
        current = read_lock_json(lock_path)
        should_zero = False
        if current is None:
            # Daemon's own SIGTERM handler already zeroed it — nothing to do
            should_zero = False
        elif current is _CORRUPT or current is _WRONG_SCHEMA:
            # Unexpected state after release — zero as cleanup
            should_zero = True
        elif isinstance(current, dict):
            # Only zero if the record still matches the daemon we released.
            # Match on pid (if we had one) or holder as fallback.
            if released_pid is not None:
                should_zero = current.get("pid") == released_pid
            else:
                # daemon was already dead when we read it; match by holder
                should_zero = current.get("holder") == released_holder

        if should_zero:
            try:
                lock_path.write_text("", encoding="utf-8")
            except OSError as e:
                print(f"sink-lock: warning: could not zero lock content: {e}", file=sys.stderr)
    finally:
        os.close(hb_fd2)

    return 0


def cmd_check_stale(lock_path: Path, ttl: int) -> int:
    if not lock_path.exists():
        return 1

    # Take LOCK_SH on .hb.lock — consistent with all other JSON readers.
    hb_fd = _acquire_hb_lock(lock_path, shared=True)
    try:
        data = read_lock_json(lock_path)
        if data is _CORRUPT:
            print(
                f"sink-lock: corrupt lock file '{lock_path}' — "
                "non-empty but JSON-unparseable; manual cleanup required",
                file=sys.stderr,
            )
            return 3
        if data is _WRONG_SCHEMA:
            # Wrong-schema JSON is treated as stale (not free, not corrupt)
            return 2
        if data is None:
            return 1
        if is_lock_stale(data, ttl):
            return 2
        return 0
    finally:
        os.close(hb_fd)


def cmd_read_holder(lock_path: Path, ttl: int) -> int:
    """Print a JSON snapshot of the current lock holder to stdout; exit 0 or 3.

    Takes LOCK_SH on the .hb.lock sentinel (same discipline as check-stale) and
    reads the holder record via read_lock_json().

    Prints to stdout:
      {"state":"held", "holder": ..., "pid": ..., "started_at": ...,
       "last_heartbeat": ..., "heartbeat_age_s": N, "stale": bool}
      — when the lock is held by a valid holder record.

      {"state":"free"}
      — when the lock file is absent, empty, or JSON null.

    Wrong-schema JSON (parseable but not a valid holder record) is treated as a
    held-but-stale lock (same as check-stale): the raw parsed dict is used to
    populate the output as best-effort, with stale=true.  heartbeat_age_s is
    computed as floor(now_epoch − last_heartbeat_epoch); -1 if unparseable.

    Exit codes:
      0 — printed {"state":"held",...} or {"state":"free"}
      3 — corrupt lock content (non-empty but JSON-unparseable)
    """
    # Take LOCK_SH on .hb.lock — same shared-read discipline as check-stale.
    hb_fd = _acquire_hb_lock(lock_path, shared=True)
    try:
        data = read_lock_json(lock_path)
        if data is _CORRUPT:
            print(
                f"sink-lock: corrupt lock file '{lock_path}' — "
                "non-empty but JSON-unparseable; manual cleanup required",
                file=sys.stderr,
            )
            return 3
        if data is None:
            # Free: absent, empty, or explicit null
            print(json.dumps({"state": "free"}))
            return 0

        now_epoch = int(datetime.now(timezone.utc).timestamp())

        if data is _WRONG_SCHEMA:
            # Parseable JSON but not a valid holder record — treat as stale.
            # Emit what we can from the raw content (best-effort).
            try:
                raw = lock_path.read_text(encoding="utf-8").strip()
                raw_dict = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                raw_dict = {}
            holder = raw_dict.get("holder", "") if isinstance(raw_dict, dict) else ""
            pid = raw_dict.get("pid", None) if isinstance(raw_dict, dict) else None
            started_at = raw_dict.get("started_at", "") if isinstance(raw_dict, dict) else ""
            last_hb = raw_dict.get("last_heartbeat", "") if isinstance(raw_dict, dict) else ""
            hb_age = -1
            if last_hb:
                try:
                    hb_age = now_epoch - iso_to_epoch(last_hb)
                except ValueError:
                    pass
            result = {
                "state": "held",
                "holder": holder,
                "pid": pid,
                "started_at": started_at,
                "last_heartbeat": last_hb,
                "heartbeat_age_s": hb_age,
                "stale": True,
            }
            print(json.dumps(result))
            return 0

        # Valid holder record (dict with required fields).
        last_hb = data.get("last_heartbeat", "")
        hb_age = -1
        if last_hb:
            try:
                hb_age = now_epoch - iso_to_epoch(last_hb)
            except ValueError:
                pass
        stale = is_lock_stale(data, ttl)
        result = {
            "state": "held",
            "holder": data["holder"],
            "pid": data["pid"],
            "started_at": data["started_at"],
            "last_heartbeat": last_hb,
            "heartbeat_age_s": hb_age,
            "stale": stale,
        }
        print(json.dumps(result))
        return 0
    finally:
        os.close(hb_fd)


def main():
    args = sys.argv[1:]  # argv[0] is the subcommand (injected by bash)
    if not args:
        print("sink-lock: no subcommand given", file=sys.stderr)
        sys.exit(2)

    subcommand = args[0]
    rest = args[1:]

    ttl = DEFAULT_TTL_SECONDS

    if subcommand == "acquire":
        if len(rest) < 2:
            print("sink-lock acquire: requires <lock-path> <holder-id>", file=sys.stderr)
            sys.exit(2)
        lock_path = Path(rest[0])
        holder_id = rest[1]
        extra = rest[2:]
        for arg in extra:
            if arg.startswith("--ttl-seconds="):
                try:
                    ttl = int(arg.split("=", 1)[1])
                except ValueError:
                    print(f"sink-lock: invalid --ttl-seconds value: {arg}", file=sys.stderr)
                    sys.exit(2)
            else:
                print(f"sink-lock: unknown option: {arg}", file=sys.stderr)
                sys.exit(2)
        rc = cmd_acquire(lock_path, holder_id, ttl)
        sys.exit(rc)

    elif subcommand == "heartbeat":
        if len(rest) < 1:
            print("sink-lock heartbeat: requires <lock-path>", file=sys.stderr)
            sys.exit(2)
        rc = cmd_heartbeat(Path(rest[0]))
        sys.exit(rc)

    elif subcommand == "release":
        if len(rest) < 1:
            print("sink-lock release: requires <lock-path>", file=sys.stderr)
            sys.exit(2)
        lock_path = Path(rest[0])
        expected_holder = None
        expected_pid = None
        extra = rest[1:]
        for arg in extra:
            if arg.startswith("--expected-holder="):
                expected_holder = arg.split("=", 1)[1]
            elif arg.startswith("--expected-pid="):
                try:
                    expected_pid = int(arg.split("=", 1)[1])
                except ValueError:
                    print(f"sink-lock: invalid --expected-pid value: {arg}", file=sys.stderr)
                    sys.exit(2)
            else:
                print(f"sink-lock: unknown option: {arg}", file=sys.stderr)
                sys.exit(2)
        rc = cmd_release(lock_path, expected_holder, expected_pid)
        sys.exit(rc)

    elif subcommand == "check-stale":
        if len(rest) < 1:
            print("sink-lock check-stale: requires <lock-path>", file=sys.stderr)
            sys.exit(2)
        lock_path = Path(rest[0])
        extra = rest[1:]
        for arg in extra:
            if arg.startswith("--ttl-seconds="):
                try:
                    ttl = int(arg.split("=", 1)[1])
                except ValueError:
                    print(f"sink-lock: invalid --ttl-seconds value: {arg}", file=sys.stderr)
                    sys.exit(2)
            else:
                print(f"sink-lock: unknown option: {arg}", file=sys.stderr)
                sys.exit(2)
        rc = cmd_check_stale(lock_path, ttl)
        sys.exit(rc)

    elif subcommand == "read-holder":
        if len(rest) < 1:
            print("sink-lock read-holder: requires <lock-path>", file=sys.stderr)
            sys.exit(2)
        lock_path = Path(rest[0])
        extra = rest[1:]
        for arg in extra:
            if arg.startswith("--ttl-seconds="):
                try:
                    ttl = int(arg.split("=", 1)[1])
                except ValueError:
                    print(f"sink-lock: invalid --ttl-seconds value: {arg}", file=sys.stderr)
                    sys.exit(2)
            else:
                print(f"sink-lock: unknown option: {arg}", file=sys.stderr)
                sys.exit(2)
        rc = cmd_read_holder(lock_path, ttl)
        sys.exit(rc)

    else:
        print(f"sink-lock: unknown subcommand: {subcommand}", file=sys.stderr)
        sys.exit(2)


main()
PYEOF
