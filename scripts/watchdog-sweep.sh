#!/usr/bin/env bash
# watchdog-sweep.sh — Backgrounded stall-detection poller for z-harness runs.
#
# Spawned at run start by long-running commands via the single-spawn guard
# (T008).  Runs detached (daemonized — setsid/nohup) so it survives the
# spawning tool's shell session.
#
# Invocation:
#   watchdog-sweep.sh --run <run_id>
#
# Self-exit conditions (checked at the TOP of each loop iteration):
#   1. Stop-flag set (SIGTERM received) — clean exit between iterations.
#   2. Run record gone / deregistered — dead-man backstop against orphan leak.
#   3. watchdog.enabled=false — live off-switch (re-read each loop).
#   4. Z_HARNESS_REGISTRY_ENABLED=0 — env-inherited once at spawn.
#   5. max_lifetime exceeded — orphan-leak backstop.
#
# Self-guarded reads: each events.jsonl / registry read is wrapped in its
# own short deadline via the bash-fallback timer or timeout(1); on read timeout
# emit watchdog_scan_inconclusive and continue (never hang the watchdog itself).
#
# SIGTERM trap: sets stop-flag checked at the TOP of each loop iteration.
# The watchdog exits BETWEEN iterations — never mid-log-event.sh emit — so
# no partial JSON line is ever written to events.jsonl.
#
# Detection + action ladder (T007 seam):
#   [T007] Implement the detection ladder here:
#     - events.jsonl: dispatch_start with no matching dispatch_end past deadline_ts
#     - liveness.sh: unmatched subagent *_start past stale threshold
#   [T007] Implement the action ladder here (watchdog.intervention_level):
#     - observe: emit watchdog_stall only
#     - notify: emit watchdog_stall + call notify-watchdog.sh (notify-once per reason)
#   [T007] Overnight halt: if Z_HARNESS_NO_ASK=halt + confirmed stall → write HALT sentinel
#
# Single-spawn guard (T008 seam):
#   [T008] Wrap the spawn in flock'd .watchdog.pid to ensure exactly one
#          sweep runs per run. This file (watchdog-sweep.sh itself) does NOT
#          implement the spawn guard — it is the process that runs AFTER the
#          guard has already selected it. T008 writes the pid file at spawn time.

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve plugin root (same pattern as log-event.sh / log-phase.sh)
# ---------------------------------------------------------------------------
_WD_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"
_WD_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Arg parse — only --run is accepted.
# ---------------------------------------------------------------------------
RUN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN="$2"
      shift 2
      ;;
    *)
      echo "watchdog-sweep.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$RUN" ]]; then
  echo "watchdog-sweep.sh: --run <run_id> is required" >&2
  exit 2
fi

# ---------------------------------------------------------------------------
# Source check-timeout.sh for TIMEOUT_CMD + timeout_backend().
# Addendum K: additive — does not change existing behaviour.
# ---------------------------------------------------------------------------
# shellcheck source=scripts/check-timeout.sh
source "$_WD_SCRIPTS_DIR/check-timeout.sh" "$RUN" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Z_HARNESS_REGISTRY_ENABLED: read at spawn, env-inherited once (Addendum J).
# If disabled, exit immediately — no need to poll when registry is off.
# ---------------------------------------------------------------------------
if [[ "${Z_HARNESS_REGISTRY_ENABLED:-1}" == "0" ]]; then
  exit 0
fi

# ---------------------------------------------------------------------------
# Resolve Z_HARNESS_PLAN_DIR for this run so we can create active/ dir and
# write marker files.
#
# Priority order:
#   1. Z_HARNESS_PLAN_DIR env var (set by orchestrators at spawn time — authoritative).
#   2. Derived from log-event.sh resolve-run-dir (strips /archive/<run> suffix).
#   3. Z_HARNESS_BASE_DIR or plugin root fallback.
# ---------------------------------------------------------------------------
_WD_PLAN_DIR=""

# Priority 1: env var set by spawner (most reliable in tests and production).
if [[ -n "${Z_HARNESS_PLAN_DIR:-}" ]]; then
  _WD_PLAN_DIR="$Z_HARNESS_PLAN_DIR"
fi

# Priority 2: derive from run archive dir via log-event.sh path resolution.
if [[ -z "$_WD_PLAN_DIR" ]]; then
  _WD_RUN_DIR=""
  _WD_RUN_DIR="$(bash "$_WD_SCRIPTS_DIR/log-event.sh" resolve-run-dir "$RUN" 2>/dev/null || true)"
  if [[ -n "$_WD_RUN_DIR" ]]; then
    _WD_PLAN_DIR="${_WD_RUN_DIR%/archive/*}"
    # If stripping didn't change the path (no /archive/ present), discard.
    [[ "$_WD_PLAN_DIR" == "$_WD_RUN_DIR" ]] && _WD_PLAN_DIR=""
  fi
fi

# Priority 3: fallback to base dir.
if [[ -z "$_WD_PLAN_DIR" ]]; then
  _WD_PLAN_DIR="${Z_HARNESS_BASE_DIR:-$_WD_PLUGIN_ROOT/z-harness}"
fi

# ---------------------------------------------------------------------------
# Create the active/ dir at startup (acceptance criterion).
# This is where .watchdog.pid (T008) and .notified.<reason> (T007) markers live.
# ---------------------------------------------------------------------------
_WD_ACTIVE_DIR="$_WD_PLAN_DIR/active"
mkdir -p "$_WD_ACTIVE_DIR"

# ---------------------------------------------------------------------------
# SIGTERM trap — sets stop-flag; checked at loop top, never mid-emit.
# Addendum G: exit BETWEEN iterations only.
# ---------------------------------------------------------------------------
_WD_STOP=0
trap '_WD_STOP=1' TERM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Emit a log event (best-effort — failure is non-fatal per Addendum E).
_emit() {
  local kind="$1" payload="$2"
  bash "$_WD_SCRIPTS_DIR/log-event.sh" "$RUN" "$kind" "$payload" >/dev/null 2>&1 || true
}

# Self-guarded read: run a command with a short deadline.
# On timeout, emit watchdog_scan_inconclusive and return non-zero.
# Uses timeout(1) if available (via check-timeout.sh), else bash kill-after-sleep.
_GUARD_TIMEOUT="${WATCHDOG_GUARD_TIMEOUT:-10}"  # seconds per self-guarded read (overridable for tests)

_guarded_read() {
  # Run "$@" under a $GUARD_TIMEOUT-second deadline.
  # Returns the command's exit code, or 124 on timeout.
  if [[ -n "${TIMEOUT_CMD:-}" ]]; then
    "$TIMEOUT_CMD" "$_GUARD_TIMEOUT" "$@"
    return $?
  fi

  # Bash-fallback timer: spawn command in background, kill after timeout.
  local child_pid exit_code=0 timed_out=0

  "$@" &
  child_pid=$!

  # Reaper: after GUARD_TIMEOUT seconds, kill the child if still alive.
  ( sleep "$_GUARD_TIMEOUT"
    kill -0 "$child_pid" 2>/dev/null && kill -TERM "$child_pid" 2>/dev/null
  ) &
  local reaper_pid=$!

  wait "$child_pid" 2>/dev/null || exit_code=$?

  # Kill reaper sentinel if it is still running.
  kill -0 "$reaper_pid" 2>/dev/null && kill -TERM "$reaper_pid" 2>/dev/null || true
  wait "$reaper_pid" 2>/dev/null || true

  # Distinguish timeout (SIGTERM from reaper = 143) from natural failure.
  if [[ $exit_code -eq 143 || $exit_code -eq 137 ]]; then
    return 124
  fi
  return $exit_code
}

# Check whether the run record still exists in the registry.
# Returns:
#   0   — run is present in the registry
#   1   — run is absent / deregistered (or non-timeout read error)
#   124 — registry read timed out (caller should emit watchdog_scan_inconclusive)
_run_record_exists() {
  local list_output rc=0
  list_output="$(_guarded_read \
    python3 "$_WD_REGISTRY_SCRIPT" list --json 2>/dev/null)" || rc=$?
  if [[ $rc -ne 0 ]]; then
    [[ $rc -eq 124 ]] && return 124  # propagate timeout to caller
    return 1                          # other errors = record absent
  fi

  # Parse JSON list for our run_id.
  python3 -c '
import json, sys
data = json.loads(sys.argv[1])
run = sys.argv[2]
found = any(r.get("run_id") == run for r in data)
sys.exit(0 if found else 1)
' "$list_output" "$RUN" 2>/dev/null
}

# Script paths — overridable via env for testing.
# WATCHDOG_REGISTRY_SCRIPT: override for active-plan-registry.py (tests).
# WATCHDOG_CONFIG_SCRIPT: override for config.py (tests).
_WD_REGISTRY_SCRIPT="${WATCHDOG_REGISTRY_SCRIPT:-$_WD_SCRIPTS_DIR/active-plan-registry.py}"
_WD_CONFIG_SCRIPT="${WATCHDOG_CONFIG_SCRIPT:-$_WD_SCRIPTS_DIR/config.py}"

# Read a config value via config.py get.
# Returns the value on stdout, or empty string on failure.
_config_get() {
  local key="$1"
  python3 "$_WD_CONFIG_SCRIPT" get "$key" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Read spawn-time config values (used for max_lifetime only — enabled and
# sweep_interval are re-read each loop per Addendum J).
# ---------------------------------------------------------------------------
_WD_SPAWN_TS="$(date +%s 2>/dev/null || python3 -c 'import time; print(int(time.time()))')"

# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------
_one_sweep() {
  # === Self-exit check 1: SIGTERM stop-flag ===
  if [[ "$_WD_STOP" -eq 1 ]]; then
    return 1  # signal loop to exit
  fi

  # === Self-exit check 2: run record gone ===
  # Use _guarded_read; on timeout emit watchdog_scan_inconclusive and continue.
  local rec_check_rc=0
  _run_record_exists || rec_check_rc=$?
  if [[ $rec_check_rc -eq 124 ]]; then
    # Read timed out — inconclusive, continue.
    _emit "watchdog_scan_inconclusive" \
      '{"run":"'"$RUN"'","reason":"registry_read_timeout"}'
    return 0
  fi
  if [[ $rec_check_rc -ne 0 ]]; then
    # Run record absent — dead-man exit.
    return 1
  fi

  # === Self-exit check 3: watchdog.enabled live re-read (Addendum J) ===
  local enabled
  enabled="$(_config_get "watchdog.enabled" 2>/dev/null || echo "true")"
  if [[ "$enabled" == "false" || "$enabled" == "0" ]]; then
    return 1  # signal loop to exit
  fi

  # === Self-exit check 4: max_lifetime exceeded ===
  local max_lifetime
  max_lifetime="$(_config_get "watchdog.max_lifetime_secs" 2>/dev/null || echo "86400")"
  local now_ts
  now_ts="$(date +%s 2>/dev/null || python3 -c 'import time; print(int(time.time()))')"
  local age_s=$(( now_ts - _WD_SPAWN_TS ))
  if [[ $age_s -ge ${max_lifetime:-86400} ]]; then
    _emit "watchdog_scan_inconclusive" \
      '{"run":"'"$RUN"'","reason":"max_lifetime_exceeded","age_s":'"$age_s"'}'
    return 1
  fi

  # === Detection + action ladder (T007 seam) ===
  # [T007] Insert detection calls here:
  #   - Scan events.jsonl for dispatch_start with no dispatch_end past deadline_ts
  #   - Call liveness.sh --run "$RUN" --stale-seconds <stale_secs>
  #   - On confirmed stall: emit watchdog_stall, optionally call notify-watchdog.sh
  #   - Overnight halt: if Z_HARNESS_NO_ASK=halt, write "$_WD_PLAN_DIR/HALT"
  # Leave this seam intentionally empty in T006.

  return 0
}

# Read sweep interval (default 60s).
_sweep_interval() {
  local v
  v="$(_config_get "watchdog.sweep_interval_secs" 2>/dev/null || echo "60")"
  # Validate: must be a positive integer; default to 60 if not.
  if [[ "$v" =~ ^[0-9]+$ ]] && [[ "$v" -gt 0 ]]; then
    echo "$v"
  else
    echo "60"
  fi
}

while true; do
  # Check stop-flag at the TOP of each iteration (Addendum G).
  if [[ "$_WD_STOP" -eq 1 ]]; then
    break
  fi

  # Run one sweep iteration.
  if ! _one_sweep; then
    break
  fi

  # Read sweep interval fresh each iteration (allows live tuning).
  _WD_INTERVAL="$(_sweep_interval)"

  # Sleep in short increments so SIGTERM is noticed promptly.
  # We break the sleep into 1-second chunks, checking stop-flag between each.
  _WD_SLEPT=0
  while [[ $_WD_SLEPT -lt $_WD_INTERVAL ]]; do
    if [[ "$_WD_STOP" -eq 1 ]]; then
      break
    fi
    sleep 1
    _WD_SLEPT=$(( _WD_SLEPT + 1 ))
  done
done

exit 0
