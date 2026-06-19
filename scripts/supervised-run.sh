#!/usr/bin/env bash
# supervised-run.sh — Run one external command under a hard deadline.
#
# Usage:
#   supervised-run.sh --run <run_id> --type <type> --timeout <secs> \
#                     [--dispatch-id <id>] [--grace <secs>] -- <cmd> [args...]
#
# Arguments:
#   --run         run id (passed to log-event.sh)
#   --type        dispatch type string (ssh, rsync, cargo, reviewer, bash, …)
#   --timeout     deadline in seconds; 0 means resolve from config
#                 watchdog.timeout_secs.<type> (default 600 if type unknown)
#   --dispatch-id optional; generated as <run>-<type>-<epoch_ms>-<rand4> if absent
#   --grace       SIGTERM→SIGKILL grace seconds; default from watchdog.kill_grace_secs (10)
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
  printf 'Usage: supervised-run.sh --run R --type T --timeout N [--dispatch-id D] [--grace G] -- cmd [args...]\n' >&2
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
  # Stub: runs the command without a deadline.  T004 replaces this with the
  # setsid+reaper implementation.  A timeout_degraded warning is emitted here
  # so the sweep can already see the degraded-backend state.

  # One-time-per-run timeout_degraded event (atomic mkdir guard).
  if [[ -n "${RUN}" ]]; then
    local _marker_dir
    # Resolve the run archive dir the same way check-timeout.sh does.
    local _zh_base
    _zh_base="$(_Z_HARNESS_RESOLVING_BASE=1 \
      bash -c "source \"${SCRIPT_DIR}/plan-path.sh\"; z_harness_base")"
    if [[ -n "${Z_HARNESS_SLUG:-}" ]]; then
      local _plans_dir="${Z_HARNESS_PLANS_DIR:-${_zh_base}/plans}"
      local _run_dir="${_plans_dir}/${Z_HARNESS_SLUG}/archive/${RUN}"
    else
      local _run_dir="${_zh_base}/archive/${RUN}"
    fi
    mkdir -p "$_run_dir"
    _marker_dir="${_run_dir}/.timeout-degraded-logged"
    if mkdir "$_marker_dir" 2>/dev/null; then
      _emit_event "$RUN" "timeout_degraded" \
        '{"backend":"bash_fallback","recommend":"brew install coreutils"}'
    fi
  fi

  printf '[supervised-run] WARNING: no timeout(1)/gtimeout binary — running without deadline enforcement (T004 not yet active).\n' >&2

  # Run the command bare — child PID not captured (needed only by T004's reaper).
  # Addendum C: stdin piped through unchanged; stdout byte-for-byte.
  "${CMD_ARGS[@]}"
  EXIT_CODE=$?
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

RUN=""
TYPE=""
TIMEOUT_S=""
DISPATCH_ID=""
GRACE_S=""
FOUND_DASHDASH=0
CMD_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)       RUN="${2:-}";         shift 2 ;;
    --type)      TYPE="${2:-}";        shift 2 ;;
    --timeout)   TIMEOUT_S="${2:-}";   shift 2 ;;
    --dispatch-id) DISPATCH_ID="${2:-}"; shift 2 ;;
    --grace)     GRACE_S="${2:-}";     shift 2 ;;
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
# Emit dispatch_start
# ---------------------------------------------------------------------------

T_START_MS="$(_now_ms)"
DEADLINE_TS=$(( T_START_MS / 1000 + TIMEOUT_S ))

# pid is unknown before child launch; emit 0 (advisory — this wrapper always
# wraps killable subprocesses; native Agent() is never routed through it).
# T004's bash-fallback path captures the real PID for dispatch_start.
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

# ---------------------------------------------------------------------------
# Run the command
# ---------------------------------------------------------------------------

EXIT_CODE=0
BACKEND="$(timeout_backend)"

case "$BACKEND" in
  timeout|gtimeout)
    # Use the system timeout binary.
    # --kill-after=<grace>: SIGTERM first, then SIGKILL after grace seconds.
    # Child stdout is byte-for-byte (no tee, no process substitution).
    # timeout(1) exits 124 on deadline; we passthrough that code (Addendum B).
    EXIT_CODE=0
    "$TIMEOUT_CMD" "--kill-after=${GRACE_S}" "${TIMEOUT_S}" \
      "${CMD_ARGS[@]}" || EXIT_CODE=$?
    ;;

  bash_fallback)
    # T004's domain.  Call the stub (defined above) which will be replaced.
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

if [[ "$EXIT_CODE" -eq 124 ]]; then
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
