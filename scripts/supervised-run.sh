#!/usr/bin/env bash
# supervised-run.sh — Run one external command under a hard deadline.
#
# Usage:
#   supervised-run.sh --run <run_id> --type <type> --timeout <secs> \
#                     [--dispatch-id <id>] [--grace <secs>] \
#                     [--provider-role <role>] -- <cmd> [args...]
#
# Arguments:
#   --run         run id (passed to log-event.sh)
#   --type        dispatch type string (ssh, rsync, cargo, reviewer, bash, …)
#   --timeout     deadline in seconds; 0 means resolve from config
#                 watchdog.timeout_secs.<type> (default 600 if type unknown)
#   --dispatch-id optional; generated as <run>-<type>-<epoch_ms>-<rand4> if absent
#   --grace       SIGTERM→SIGKILL grace seconds; default from watchdog.kill_grace_secs (10)
#   --provider-role optional provider role propagated to child provider shims
#   --            separator: everything after is the command to run
#
# Behaviour:
#   - Missing "--" separator → exit 2
#   - Emits dispatch_start{dispatch_id,type,pid,timeout_s,deadline_ts} via log-event.sh
#   - Runs cmd under timeout(1)/gtimeout(1) when available (timeout_backend == timeout|gtimeout)
#     or leaves a clean seam for the bash fallback (T004) when backend == bash_fallback
#   - Emits dispatch_end{dispatch_id,exit_code,wall_ms}
#   - Exit-code contract:
#       124            iff THIS wrapper enforced the deadline
#       passthrough    child's own exit code otherwise
#   - Stdout: byte-for-byte from child (no tee, no buffering)
#   - Stderr: wrapper diagnostics only; child stderr passes through
#   - Telemetry fail-open: log-event.sh failure never prevents the command from running
#
# Seam for T004 (bash fallback):
#   When timeout_backend() returns "bash_fallback", this script falls through to
#   _run_bash_fallback() which currently runs the command bare (no deadline enforcement)
#   and exits with the child's passthrough code.  T004 replaces _run_bash_fallback()
#   with the full setsid+reaper implementation.  The rest of the wrapper (arg parse,
#   event emission, exit-code contract) is already correct and must not be changed by T004.
#
# Addenda honoured:
#   A: dispatch_id mandatory in both events; generated if absent
#   B: 124 iff wrapper-enforced deadline; passthrough otherwise
#   C: child stdout byte-for-byte; all diagnostics to stderr; stdin piped through
#   E: telemetry fail-open (warn to stderr; never blocks cmd)

set -euo pipefail

# ---------------------------------------------------------------------------
# Locate scripts dir (tolerates being called from any cwd)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ---------------------------------------------------------------------------
# Source timeout backend resolver (T002)
# ---------------------------------------------------------------------------
# shellcheck source=scripts/check-timeout.sh
source "${SCRIPT_DIR}/check-timeout.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_usage() {
  printf 'Usage: supervised-run.sh --run R --type T --timeout N [--dispatch-id D] [--grace G] [--provider-role ROLE] -- cmd [args...]\n' >&2
  exit 2
}

# Emit a log-event.sh call; warn to stderr if it fails (telemetry fail-open).
_emit_event() {
  local run="$1" kind="$2" payload="$3"
  if ! bash "${SCRIPT_DIR}/log-event.sh" "$run" "$kind" "$payload" >/dev/null 2>&1; then
    printf '[supervised-run] WARNING: failed to emit %s event (log-event.sh failed); continuing.\n' "$kind" >&2
  fi
}

# Portable millisecond timestamp.
_now_ms() {
  # python3 is always available in this repo; avoids platform differences in 'date'.
  python3 -c 'import time; print(int(time.time() * 1000))'
}

# Resolve default timeout for a given dispatch type from config.
# Falls back to 600 if type unknown or config read fails.
_resolve_timeout() {
  local type="$1"
  local secs
  secs="$(python3 "${SCRIPT_DIR}/config.py" get "watchdog.timeout_secs.${type}" 2>/dev/null || true)"
  if [[ -z "$secs" ]] || ! [[ "$secs" =~ ^[0-9]+$ ]]; then
    secs=600
  fi
  printf '%s' "$secs"
}

# Resolve kill grace seconds from config, default 10.
_resolve_grace() {
  local grace
  grace="$(python3 "${SCRIPT_DIR}/config.py" get watchdog.kill_grace_secs 2>/dev/null || true)"
  if [[ -z "$grace" ]] || ! [[ "$grace" =~ ^[0-9]+$ ]]; then
    grace=10
  fi
  printf '%s' "$grace"
}

# ---------------------------------------------------------------------------
# Bash fallback stub — T004 replaces the body of this function.
# Contract (T004 must uphold):
#   - Run CMD_ARGS[@] (already set in the outer scope) with no additional shell re-parsing.
#   - Enforce a deadline of TIMEOUT_S seconds; kill child + reap process group.
#   - Write child PID to CHILD_PID (global) immediately after launch.
#   - Set EXIT_CODE to 124 iff wrapper enforced the deadline.
#   - Set EXIT_CODE to the child's exit code on normal exit.
#   - Emit one-time-per-run timeout_degraded{backend:bash_fallback} event (atomic mkdir).
#   - Child stdout byte-for-byte; all diagnostics to stderr.
# ---------------------------------------------------------------------------
_run_bash_fallback() {
  # Full setsid+reaper implementation (T004).
  #
  # Globals consumed (set by outer arg-parse):
  #   CMD_ARGS[@]  — command to run (no re-parsing)
  #   TIMEOUT_S    — deadline in seconds
  #   GRACE_S      — SIGTERM→SIGKILL grace seconds
  #   RUN          — run id for event emission
  #   SCRIPT_DIR   — scripts directory
  #
  # Globals written:
  #   CHILD_PID    — PID of the launched child (set immediately after launch)
  #   EXIT_CODE    — 124 (deadline/SIGTERM), 137 (SIGKILL-after-grace), or child's passthrough
  #
  # No-orphan scope: SIGKILL is sent to the child's *process group* (kill -KILL -PGID),
  # which reaps all descendants that share the pgroup.  Descendants that call setsid()
  # themselves or double-fork into a new session escape the group and are NOT reaped —
  # this carve-out is intentional and documented.

  # ---- One-time-per-run timeout_degraded event (atomic mkdir guard) ----
  if [[ -n "${RUN}" ]]; then
    local _zh_base
    _zh_base="$(_Z_HARNESS_RESOLVING_BASE=1 \
      bash -c "source \"${SCRIPT_DIR}/plan-path.sh\"; z_harness_base")"
    local _run_dir
    if [[ -n "${Z_HARNESS_SLUG:-}" ]]; then
      local _plans_dir="${Z_HARNESS_PLANS_DIR:-${_zh_base}/plans}"
      _run_dir="${_plans_dir}/${Z_HARNESS_SLUG}/archive/${RUN}"
    else
      _run_dir="${_zh_base}/archive/${RUN}"
    fi
    mkdir -p "$_run_dir"
    local _marker_dir="${_run_dir}/.timeout-degraded-logged"
    if mkdir "$_marker_dir" 2>/dev/null; then
      _emit_event "$RUN" "timeout_degraded" \
        '{"backend":"bash_fallback","recommend":"brew install coreutils"}'
    fi
  fi

  printf '[supervised-run] WARNING: no timeout(1)/gtimeout binary — using bash fallback with process-group deadline enforcement.\n' >&2

  # ---- Launch child in its own process group ----
  # setsid(1) is not available on macOS by default.  We use "set -m" (job control)
  # which causes bash to place each background job in its own process group.
  # This is the portable macOS-compatible equivalent.
  set -m
  "${CMD_ARGS[@]}" &
  CHILD_PID=$!  # written to global immediately (contract requirement)

  # ---- Emit dispatch_start IMMEDIATELY after child launch ----
  # SPEC addendum A: dispatch_start must be in events.jsonl BEFORE the deadline
  # window elapses so the backgrounded sweep can detect in-progress stalls.
  # We emit here (with the real pid) rather than after the blocking wait below.
  # Telemetry fail-open (addendum E): emission failure must not prevent deadline
  # enforcement — _emit_event already warns and continues on failure.
  local _fb_start_payload
  _fb_start_payload="$(python3 -c '
import json, sys
d = {
  "dispatch_id": sys.argv[1],
  "type":        sys.argv[2],
  "pid":         int(sys.argv[3]),
  "timeout_s":   int(sys.argv[4]),
  "deadline_ts": int(sys.argv[5]),
}
print(json.dumps(d))
' "$DISPATCH_ID" "$TYPE" "$CHILD_PID" "$TIMEOUT_S" "$DEADLINE_TS")" || true
  if [[ -n "$_fb_start_payload" ]]; then
    _emit_event "$RUN" "dispatch_start" "$_fb_start_payload"
  else
    printf '[supervised-run] WARNING: failed to build dispatch_start payload for bash fallback; continuing.\n' >&2
  fi

  # Resolve the child's PGID.  With set -m the background job gets its own pgroup
  # (pgroup leader PID == CHILD_PID), so we can usually just use CHILD_PID directly.
  # We still read ps to be safe (race: on very fast kernels the process may already
  # have changed its own group).
  local CHILD_PGID
  CHILD_PGID="$(ps -o pgid= -p "$CHILD_PID" 2>/dev/null | tr -d ' ')" || true
  if [[ -z "$CHILD_PGID" ]] || ! [[ "$CHILD_PGID" =~ ^[0-9]+$ ]]; then
    CHILD_PGID="$CHILD_PID"
  fi

  # ---- Sentinel files for reaper↔main shell communication ----
  # Subshell variable changes don't propagate back; we use temp files.
  local _sent_base
  _sent_base="$(mktemp 2>/dev/null)" && rm -f "$_sent_base" || _sent_base="/tmp/_srun_$$"
  local _term_sent="${_sent_base}.term"  # created when reaper fires SIGTERM
  local _kill_sent="${_sent_base}.kill"  # created when reaper fires SIGKILL

  # ---- Reaper subshell ----
  # Fires SIGTERM at the whole pgroup after TIMEOUT_S, then SIGKILL after GRACE_S
  # if the group is still alive.  Every kill is preceded by kill -0 (no PID-reuse hit).
  (
    sleep "$TIMEOUT_S"
    if kill -0 -"$CHILD_PGID" 2>/dev/null; then
      touch "$_term_sent"
      kill -TERM -"$CHILD_PGID" 2>/dev/null || true
    fi
    sleep "$GRACE_S"
    if kill -0 -"$CHILD_PGID" 2>/dev/null; then
      touch "$_kill_sent"
      kill -KILL -"$CHILD_PGID" 2>/dev/null || true
    fi
  ) &
  local REAPER_PID=$!

  # ---- Wait for child ----
  # On normal exit: kill the reaper sentinel so it doesn't fire.
  # On timeout exit: reaper already fired; wait reflects signal death.
  local _wait_exit=0
  wait "$CHILD_PID" 2>/dev/null || _wait_exit=$?

  # Clean up reaper (no-op if already exited).
  kill "$REAPER_PID" 2>/dev/null || true
  wait "$REAPER_PID" 2>/dev/null || true  # reap to avoid zombie

  # ---- Determine exit code ----
  if [[ -f "$_kill_sent" ]]; then
    # Reaper had to SIGKILL (child survived SIGTERM through the grace window).
    EXIT_CODE=137
  elif [[ -f "$_term_sent" ]]; then
    # Reaper fired SIGTERM and child died (normal deadline path).
    EXIT_CODE=124
  else
    # Child exited on its own before the deadline.
    EXIT_CODE="$_wait_exit"
  fi

  rm -f "$_term_sent" "$_kill_sent"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

RUN=""
TYPE=""
TIMEOUT_S=""
DISPATCH_ID=""
GRACE_S=""
PROVIDER_ROLE=""
FOUND_DASHDASH=0
CMD_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)       RUN="${2:-}";         shift 2 ;;
    --type)      TYPE="${2:-}";        shift 2 ;;
    --timeout)   TIMEOUT_S="${2:-}";   shift 2 ;;
    --dispatch-id) DISPATCH_ID="${2:-}"; shift 2 ;;
    --grace)     GRACE_S="${2:-}";     shift 2 ;;
    --provider-role) PROVIDER_ROLE="${2:-}"; shift 2 ;;
    --)
      FOUND_DASHDASH=1
      shift
      CMD_ARGS=("$@")
      break
      ;;
    *)
      printf '[supervised-run] ERROR: unknown argument: %s\n' "$1" >&2
      _usage
      ;;
  esac
done

# Mandatory "--" check (Addendum A / invariant).
if [[ "$FOUND_DASHDASH" -eq 0 ]]; then
  printf '[supervised-run] ERROR: missing "--" separator before command.\n' >&2
  exit 2
fi

# Required arguments.
if [[ -z "$RUN" || -z "$TYPE" ]]; then
  printf '[supervised-run] ERROR: --run and --type are required.\n' >&2
  _usage
fi

if [[ ${#CMD_ARGS[@]} -eq 0 ]]; then
  printf '[supervised-run] ERROR: no command specified after "--".\n' >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Resolve timeout
# ---------------------------------------------------------------------------

if [[ -z "$TIMEOUT_S" ]] || [[ "$TIMEOUT_S" == "0" ]]; then
  TIMEOUT_S="$(_resolve_timeout "$TYPE")"
fi

# ---------------------------------------------------------------------------
# Resolve grace
# ---------------------------------------------------------------------------

if [[ -z "$GRACE_S" ]]; then
  GRACE_S="$(_resolve_grace)"
fi

# Provider child metadata. `omp-consult.sh` and similar provider shims use this
# for actionable preflight/fallback telemetry. Keep it out of event payloads.
if [[ -z "$PROVIDER_ROLE" ]]; then
  case "$TYPE" in
    reviewer|pre_reviewer|consultant_primary|consultant_secondary)
      PROVIDER_ROLE="$TYPE"
      ;;
  esac
fi
export Z_HARNESS_RUN_ID="$RUN"
if [[ -n "$PROVIDER_ROLE" ]]; then
  export Z_HARNESS_PROVIDER_ROLE="$PROVIDER_ROLE"
fi

# ---------------------------------------------------------------------------
# Generate dispatch_id if absent (Addendum A)
# Format: <run>-<type>-<epoch_ms>-<rand4>
# ---------------------------------------------------------------------------

if [[ -z "$DISPATCH_ID" ]]; then
  local_epoch_ms="$(_now_ms)"
  rand4="$(python3 -c 'import random,string; print("".join(random.choices(string.ascii_lowercase+string.digits,k=4)))')"
  DISPATCH_ID="${RUN}-${TYPE}-${local_epoch_ms}-${rand4}"
fi

# ---------------------------------------------------------------------------
# Emit dispatch_start (pid field depends on backend)
# ---------------------------------------------------------------------------

T_START_MS="$(_now_ms)"
DEADLINE_TS=$(( T_START_MS / 1000 + TIMEOUT_S ))

# ---------------------------------------------------------------------------
# Run the command
# ---------------------------------------------------------------------------

EXIT_CODE=0
CHILD_PID=0
BACKEND="$(timeout_backend)"

case "$BACKEND" in
  timeout|gtimeout)
    # The timeout(1)/gtimeout(1) binary owns the child; we cannot know the
    # real child pid before or after launch without OS-specific introspection.
    # Emit dispatch_start now with pid=0 (documented limitation for this path).
    START_PAYLOAD="$(python3 -c '
import json, sys
d = {
  "dispatch_id":  sys.argv[1],
  "type":         sys.argv[2],
  "pid":          0,
  "timeout_s":    int(sys.argv[3]),
  "deadline_ts":  int(sys.argv[4]),
}
print(json.dumps(d))
' "$DISPATCH_ID" "$TYPE" "$TIMEOUT_S" "$DEADLINE_TS")"
    _emit_event "$RUN" "dispatch_start" "$START_PAYLOAD"

    # Use the system timeout binary.
    # --kill-after=<grace>: SIGTERM first, then SIGKILL after grace seconds.
    # Child stdout is byte-for-byte (no tee, no process substitution).
    # timeout(1) exits 124 on deadline; we passthrough that code (Addendum B).
    EXIT_CODE=0
    "$TIMEOUT_CMD" "--kill-after=${GRACE_S}" "${TIMEOUT_S}" \
      "${CMD_ARGS[@]}" || EXIT_CODE=$?
    ;;

  bash_fallback)
    # _run_bash_fallback() emits dispatch_start IMMEDIATELY after launch with
    # the real CHILD_PID (SPEC addendum A: must be in events.jsonl before the
    # deadline window elapses so the backgrounded sweep can detect stalls).
    # After this returns, CHILD_PID and EXIT_CODE are set by the function.
    EXIT_CODE=0
    _run_bash_fallback || EXIT_CODE=$?
    ;;

  *)
    printf '[supervised-run] ERROR: unexpected timeout_backend value: %s\n' "$BACKEND" >&2
    exit 1
    ;;
esac

# ---------------------------------------------------------------------------
# Emit dispatch_end (Addendum A — dispatch_id in both events)
# wall_ms derived from event timestamps (T_START_MS captured before run)
# ---------------------------------------------------------------------------

T_END_MS="$(_now_ms)"
WALL_MS=$(( T_END_MS - T_START_MS ))

END_PAYLOAD="$(python3 -c '
import json, sys
d = {
  "dispatch_id": sys.argv[1],
  "exit_code":   int(sys.argv[2]),
  "wall_ms":     int(sys.argv[3]),
}
print(json.dumps(d))
' "$DISPATCH_ID" "$EXIT_CODE" "$WALL_MS")"

_emit_event "$RUN" "dispatch_end" "$END_PAYLOAD"

# ---------------------------------------------------------------------------
# If deadline fired, emit watchdog_timeout (Addendum B)
# timeout(1) exits 124 on deadline — we passthrough that code.
# ---------------------------------------------------------------------------

if [[ "$EXIT_CODE" -eq 124 ]] || [[ "$EXIT_CODE" -eq 137 ]]; then
  TIMEOUT_PAYLOAD="$(python3 -c '
import json, sys
d = {
  "dispatch_id": sys.argv[1],
  "type":        sys.argv[2],
  "timeout_s":   int(sys.argv[3]),
  "killed":      True,
}
print(json.dumps(d))
' "$DISPATCH_ID" "$TYPE" "$TIMEOUT_S")"
  _emit_event "$RUN" "watchdog_timeout" "$TIMEOUT_PAYLOAD"
fi

exit "$EXIT_CODE"
