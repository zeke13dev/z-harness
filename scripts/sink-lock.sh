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
#
# The Python program lives in sink-lock.py, a real file — NOT a heredoc.
# A ~48KB heredoc deadlocks bash when temp-file staging fails (e.g. ENOSPC
# or unwritable TMPDIR): bash falls back to feeding the document through a
# pipe and blocks forever in write() before exec ever runs, wedging every
# caller behind the claim. Executing a file has no staging step at all.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/sink-lock.py" "$SUBCOMMAND" "$@"
