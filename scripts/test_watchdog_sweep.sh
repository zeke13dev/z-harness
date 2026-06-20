#!/usr/bin/env bash
# test_watchdog_sweep.sh — Shell tests for scripts/watchdog-sweep.sh lifecycle.
#
# Tests covered:
#   TEST-001: active/ dir is created at startup.
#   TEST-002: watchdog exits when run record is absent (run-record-gone self-exit).
#   TEST-003: watchdog exits when watchdog.enabled=false (live off-switch).
#   TEST-004: SIGTERM mid-loop → clean exit + no partial JSON line in events.jsonl.
#
# Note on scope (T006 boundary):
#   These tests exercise the LOOP SKELETON + LIFECYCLE only.
#   Detection + action (T007) and single-spawn guard (T008) are not tested here.
#
# Run with:
#   bash scripts/test_watchdog_sweep.sh

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
WATCHDOG="$SCRIPTS_DIR/watchdog-sweep.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/test_watchdog_sweep_XXXXXX"
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label"
    echo "        expected: $expected"
    echo "        actual:   $actual"
    FAIL=$(( FAIL + 1 ))
  fi
}

assert_dir_exists() {
  local label="$1" path="$2"
  if [[ -d "$path" ]]; then
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label (dir not found: $path)"
    FAIL=$(( FAIL + 1 ))
  fi
}

# ---------------------------------------------------------------------------
# _kill_watchdog <pid>
# Guaranteed teardown: kill the watchdog process group and wait for it.
# Called after every test that backgrounds a watchdog, before cleanup.
# This prevents stale background watchdogs from a prior test from contending
# for CPU/IO during the next test (the root cause of load-induced failures).
# ---------------------------------------------------------------------------
_kill_watchdog() {
  local pid="$1"
  [[ -z "$pid" || "$pid" -eq 0 ]] && return 0
  # Kill the entire process group so child reaper-sleeps die too.
  kill -TERM "-${pid}" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  # Wait up to 3 seconds for clean exit; SIGKILL if still alive.
  local i=0
  while kill -0 "$pid" 2>/dev/null && [[ $i -lt 30 ]]; do
    sleep 0.1
    i=$(( i + 1 ))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "-${pid}" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# _poll_until <deadline_epoch> <check_fn>
# Poll check_fn every 0.5s until it returns true or the deadline is reached.
# Returns 0 if the condition became true, 1 if it timed out.
# ---------------------------------------------------------------------------
_poll_until() {
  local deadline="$1" check_fn="$2"
  while [[ $(date +%s) -lt $deadline ]]; do
    if "$check_fn" 2>/dev/null; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

# ---------------------------------------------------------------------------
# Hermetic environment helpers.
#
# We use WATCHDOG_REGISTRY_SCRIPT and WATCHDOG_CONFIG_SCRIPT env overrides
# (supported by watchdog-sweep.sh) to inject fake scripts without PATH tricks.
#
# FAKE_RUN_PRESENT=1  → registry lists our run (run exists).
# FAKE_RUN_PRESENT=0  → registry returns empty list (run gone).
# WD_ENABLED=false    → config returns false for watchdog.enabled.
# WD_INTERVAL=N       → sweep interval in seconds (use 1 for fast tests).
# ---------------------------------------------------------------------------

# Write a fake active-plan-registry.py into a temp dir.
# $1 = dir to write into, $2 = run_id
_write_fake_registry() {
  local dir="$1" run_id="$2"
  local script="$dir/fake-registry.py"
  printf '#!/usr/bin/env python3\n' > "$script"
  printf 'import json, sys, os\n' >> "$script"
  printf 'run_id = "%s"\n' "$run_id" >> "$script"
  printf 'args = sys.argv[1:]\n' >> "$script"
  printf 'if "list" in args:\n' >> "$script"
  printf '    present = os.environ.get("FAKE_RUN_PRESENT", "1")\n' >> "$script"
  printf '    if present == "1":\n' >> "$script"
  printf '        print(json.dumps([{"run_id": run_id, "status": "running"}]))\n' >> "$script"
  printf '    else:\n' >> "$script"
  printf '        print(json.dumps([]))\n' >> "$script"
  printf 'sys.exit(0)\n' >> "$script"
  chmod +x "$script"
  echo "$script"  # return path
}

# Write a fake config.py into a temp dir.
# Reads WD_ENABLED, WD_INTERVAL, WD_MAX_LIFETIME from env.
_write_fake_config() {
  local dir="$1"
  local script="$dir/fake-config.py"
  printf '#!/usr/bin/env python3\n' > "$script"
  printf 'import sys, os\n' >> "$script"
  printf 'args = sys.argv[1:]\n' >> "$script"
  printf 'if args and args[0] == "get":\n' >> "$script"
  printf '    key = args[1] if len(args) > 1 else ""\n' >> "$script"
  printf '    if key == "watchdog.enabled":\n' >> "$script"
  printf '        print(os.environ.get("WD_ENABLED", "true"))\n' >> "$script"
  printf '    elif key == "watchdog.sweep_interval_secs":\n' >> "$script"
  printf '        print(os.environ.get("WD_INTERVAL", "1"))\n' >> "$script"
  printf '    elif key == "watchdog.max_lifetime_secs":\n' >> "$script"
  printf '        print(os.environ.get("WD_MAX_LIFETIME", "86400"))\n' >> "$script"
  printf '    elif key == "watchdog.stale_secs":\n' >> "$script"
  printf '        print(os.environ.get("WD_STALE_SECS", "300"))\n' >> "$script"
  printf '    else:\n' >> "$script"
  printf '        sys.exit(1)\n' >> "$script"
  printf 'else:\n' >> "$script"
  printf '    sys.exit(1)\n' >> "$script"
  chmod +x "$script"
  echo "$script"  # return path
}

# ---------------------------------------------------------------------------
# TEST-001: active/ dir is created at startup
# ---------------------------------------------------------------------------
# Invariant: watchdog-sweep.sh creates $Z_HARNESS_PLAN_DIR/active/ before the
# first poll loop iteration, regardless of the run-record check outcome.
# Failure class: marker files can't be written → notify-once dedup (T007) breaks.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-001: active/ dir is created at startup"

TD_001="$(_tmpdir)"
PLAN_DIR_001="$TD_001/plan"
mkdir -p "$PLAN_DIR_001"
EVENTS_001="$TD_001/events.jsonl"
touch "$EVENTS_001"

REG_SCRIPT_001="$(_write_fake_registry "$TD_001" "test-run-001")"
CFG_SCRIPT_001="$(_write_fake_config "$TD_001")"

# FAKE_RUN_PRESENT=0 → registry returns empty list → watchdog exits after creating active/.
RC_001=0
FAKE_RUN_PRESENT=0 \
WD_INTERVAL=1 \
WATCHDOG_GUARD_TIMEOUT=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_001" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_001" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_001" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  timeout 30 bash "$WATCHDOG" --run "test-run-001" \
  || RC_001=$?  # exit 0 (run-record-gone) is expected

assert_dir_exists \
  "active/ dir exists after watchdog startup" \
  "$PLAN_DIR_001/active"

rm -rf "$TD_001"

# ---------------------------------------------------------------------------
# TEST-002: watchdog exits when run record is absent
# ---------------------------------------------------------------------------
# Invariant: if the run record is gone (deregistered or never registered),
# the sweep exits 0 cleanly — dead-man backstop to prevent orphan watchdogs.
# Failure class: orphan watchdog processes accumulate indefinitely.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-002: exits when run record absent"

TD_002="$(_tmpdir)"
PLAN_DIR_002="$TD_002/plan"
mkdir -p "$PLAN_DIR_002"
EVENTS_002="$TD_002/events.jsonl"
touch "$EVENTS_002"

REG_SCRIPT_002="$(_write_fake_registry "$TD_002" "test-run-002")"
CFG_SCRIPT_002="$(_write_fake_config "$TD_002")"

RC_002=0
FAKE_RUN_PRESENT=0 \
WD_INTERVAL=1 \
WATCHDOG_GUARD_TIMEOUT=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_002" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_002" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_002" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  timeout 30 bash "$WATCHDOG" --run "test-run-002" \
  || RC_002=$?

assert_eq \
  "watchdog exits 0 when run record absent" \
  "0" "$RC_002"

rm -rf "$TD_002"

# ---------------------------------------------------------------------------
# TEST-003: watchdog exits when watchdog.enabled=false
# ---------------------------------------------------------------------------
# Invariant: setting watchdog.enabled=false is a live off-switch — the sweep
# exits cleanly on the next iteration without any further action.
# Failure class: watchdog keeps polling after the operator disables it,
# wasting CPU and potentially alerting when the user explicitly opted out.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-003: exits when watchdog.enabled=false"

TD_003="$(_tmpdir)"
PLAN_DIR_003="$TD_003/plan"
mkdir -p "$PLAN_DIR_003"
EVENTS_003="$TD_003/events.jsonl"
touch "$EVENTS_003"

REG_SCRIPT_003="$(_write_fake_registry "$TD_003" "test-run-003")"
CFG_SCRIPT_003="$(_write_fake_config "$TD_003")"

RC_003=0
# FAKE_RUN_PRESENT=1 (record exists) but WD_ENABLED=false (live off-switch).
FAKE_RUN_PRESENT=1 \
WD_ENABLED=false \
WD_INTERVAL=1 \
WATCHDOG_GUARD_TIMEOUT=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_003" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_003" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_003" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  timeout 30 bash "$WATCHDOG" --run "test-run-003" \
  || RC_003=$?

assert_eq \
  "watchdog exits 0 when watchdog.enabled=false" \
  "0" "$RC_003"

rm -rf "$TD_003"

# ---------------------------------------------------------------------------
# TEST-004: SIGTERM mid-loop → clean exit, no partial JSON line in events.jsonl
# ---------------------------------------------------------------------------
# Invariant: SIGTERM sets stop-flag checked at the TOP of each loop iteration;
# the watchdog exits BETWEEN iterations, never mid-log-event.sh emit.
# Failure class: partial JSON line in events.jsonl corrupts downstream readers
# that expect one valid JSON object per line.
#
# Robustness design: instead of a fixed sleep 2 to wait for the watchdog to
# enter its sleep phase, we poll the process's existence + the active/ dir
# (created at startup before the first sweep) for up to 30s.  Only then do we
# send SIGTERM, guaranteeing the watchdog is truly running, not just starting.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-004: SIGTERM mid-loop → clean exit, no partial JSON line"

TD_004="$(_tmpdir)"
PLAN_DIR_004="$TD_004/plan"
mkdir -p "$PLAN_DIR_004"
EVENTS_004="$TD_004/events.jsonl"
touch "$EVENTS_004"

REG_SCRIPT_004="$(_write_fake_registry "$TD_004" "test-run-004")"
CFG_SCRIPT_004="$(_write_fake_config "$TD_004")"

# WD_INTERVAL=3 so the watchdog is sleeping when SIGTERM arrives mid-loop.
WD_PID_004=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=3 \
WATCHDOG_GUARD_TIMEOUT=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_004" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_004" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_004" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-004" &
WD_PID_004=$!

# Poll until watchdog has started (active/ dir created) — up to 30s.
# This replaces the fixed sleep 2 which races under scheduler load.
_STARTUP_DEADLINE_004=$(( $(date +%s) + 30 ))
while [[ $(date +%s) -lt $_STARTUP_DEADLINE_004 ]]; do
  [[ -d "$PLAN_DIR_004/active" ]] && kill -0 "$WD_PID_004" 2>/dev/null && break
  sleep 0.5
done

# Send SIGTERM mid-sleep (between iterations).
kill -TERM "$WD_PID_004" 2>/dev/null || true

# Bounded wait: poll for exit up to ~30s, then force-kill.
# A stuck watchdog produces a test FAILURE within the window — never an unbounded hang.
WD_EXIT_004=0
_WAITED_004=0
while kill -0 "$WD_PID_004" 2>/dev/null && [[ $_WAITED_004 -lt 300 ]]; do
  sleep 0.1
  _WAITED_004=$(( _WAITED_004 + 1 ))
done
if kill -0 "$WD_PID_004" 2>/dev/null; then
  # Did NOT exit within 30s — this is the failure the test should catch, not a hang.
  WD_EXIT_004=1   # non-zero sentinel: "still alive" = did not exit cleanly
  _kill_watchdog "$WD_PID_004"
else
  # Process exited; reap the zombie and capture its exit code.
  wait "$WD_PID_004" 2>/dev/null || WD_EXIT_004=$?
fi
WD_PID_004=0  # mark as reaped

assert_eq \
  "watchdog exits 0 after SIGTERM" \
  "0" "$WD_EXIT_004"

# Verify events.jsonl has no partial (non-JSON) lines.
# Every non-empty line must be valid JSON — if even one is partial, the
# SIGTERM landed mid-emit in violation of the invariant.
if [[ -f "$EVENTS_004" && -s "$EVENTS_004" ]]; then
  PARTIAL_LINES=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    if ! python3 -c "import json, sys; json.loads(sys.argv[1])" "$line" 2>/dev/null; then
      PARTIAL_LINES=$(( PARTIAL_LINES + 1 ))
      echo "    non-JSON line detected: $line" >&2
    fi
  done < "$EVENTS_004"
  assert_eq \
    "no partial JSON lines in events.jsonl after SIGTERM" \
    "0" "$PARTIAL_LINES"
else
  # No events written is also valid — sweep had nothing to emit.
  echo "  PASS: events.jsonl is empty (no events to check)"
  PASS=$(( PASS + 1 ))
fi

rm -rf "$TD_004"

# ---------------------------------------------------------------------------
# TEST-005: registry-read timeout → watchdog_scan_inconclusive emitted, loop continues
# ---------------------------------------------------------------------------
# Invariant: when the registry read times out, _run_record_exists() returns 124,
# the sweep emits watchdog_scan_inconclusive with reason=registry_read_timeout,
# and the loop continues to the next iteration (does NOT self-exit).
# Failure class: a read timeout is misclassified as "run record absent" causing
# a false self-exit instead of an inconclusive signal.
#
# Timing-robustness design: instead of a fixed outer timeout window, the watchdog
# runs in background and we POLL events.jsonl for up to 30s (check every 0.5s).
# As soon as the event appears we assert (a) the watchdog was still alive (no
# false-self-exit) and (b) the event genuinely emitted.  This removes the race
# between first-emit timing and a hard wall-clock cap.
# WATCHDOG_GUARD_TIMEOUT=1 ensures the first inconclusive event fires within ~1s,
# well inside the 30s polling budget even under heavy system load.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-005: registry-read timeout → watchdog_scan_inconclusive + loop continues"

TD_005="$(_tmpdir)"
PLAN_DIR_005="$TD_005/plan"
# Base dir for log-event.sh to write events into (legacy no-slug layout).
BASE_DIR_005="$TD_005/base"
# events.jsonl is written to $BASE_DIR_005/archive/<run>/events.jsonl
EVENTS_005="$BASE_DIR_005/archive/test-run-005/events.jsonl"
mkdir -p "$PLAN_DIR_005" "$BASE_DIR_005"

# Fake registry that always hangs, causing _guarded_read to time out.
SLEEPING_REG_005="$TD_005/sleeping-registry.py"
printf '#!/usr/bin/env python3\nimport time\ntime.sleep(999)\n' > "$SLEEPING_REG_005"
chmod +x "$SLEEPING_REG_005"

CFG_SCRIPT_005="$(_write_fake_config "$TD_005")"

# Helper: scan events.jsonl for the target event; echoes count found.
_count_inconclusive_005() {
  local count=0
  [[ -s "$EVENTS_005" ]] || { echo 0; return; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    # log-event.sh merges payload fields into the top-level event object.
    # So 'kind' and 'reason' are both top-level keys.
    if python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    ok = (d.get('kind') == 'watchdog_scan_inconclusive'
          and d.get('reason') == 'registry_read_timeout')
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
" "$line" 2>/dev/null; then
      count=$(( count + 1 ))
    fi
  done < "$EVENTS_005"
  echo "$count"
}

# Run the watchdog in background with:
#   WATCHDOG_GUARD_TIMEOUT=1  — registry times out within ~1s; first event ~1s
#   WD_INTERVAL=1             — fast loop so the event fires early
#   Z_HARNESS_BASE_DIR        — redirects log-event.sh output to our temp dir
WD_PID_005=0
WATCHDOG_REGISTRY_SCRIPT="$SLEEPING_REG_005" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_005" \
WATCHDOG_GUARD_TIMEOUT=1 \
WD_INTERVAL=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_005" \
Z_HARNESS_BASE_DIR="$BASE_DIR_005" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-005" &
WD_PID_005=$!

# Poll for the target event for up to 30 seconds (check every 0.5s).
# This avoids any race between first-emit timing and a fixed outer cap.
_POLL_DEADLINE_005=$(( $(date +%s) + 30 ))
INCONCLUSIVE_COUNT_005=0
WD_STILL_ALIVE_005=0

while [[ $(date +%s) -lt $_POLL_DEADLINE_005 ]]; do
  INCONCLUSIVE_COUNT_005="$(_count_inconclusive_005)"
  if [[ "$INCONCLUSIVE_COUNT_005" -gt 0 ]]; then
    # Event found — record whether watchdog was still alive at this moment
    # (no false-self-exit means the process should still be running).
    if kill -0 "$WD_PID_005" 2>/dev/null; then
      WD_STILL_ALIVE_005=1
    fi
    break
  fi
  sleep 0.5
done

# Clean up: guaranteed teardown before next test.
_kill_watchdog "$WD_PID_005"
WD_PID_005=0

# Assertion (a): watchdog was still alive when the event appeared (no false-self-exit).
assert_eq \
  "watchdog still looping when event appeared (not false-self-exited)" \
  "1" "$WD_STILL_ALIVE_005"

# Assertion (b): the event was genuinely emitted.
if [[ "$INCONCLUSIVE_COUNT_005" -gt 0 ]]; then
  echo "  PASS: watchdog_scan_inconclusive(registry_read_timeout) emitted ($INCONCLUSIVE_COUNT_005 times)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: watchdog_scan_inconclusive(registry_read_timeout) not found in events at $EVENTS_005 after 30s"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_005"

# ---------------------------------------------------------------------------
# Helper: write an events.jsonl with dispatch events for T007 tests.
# Writes minimal-valid JSON lines directly (no log-event.sh invocation).
#
# $1 = path to events.jsonl
# $2 = dispatch_id for the start event
# $3 = "include_end" | "omit_end" — whether to write a matching dispatch_end
# $4 = deadline_ts (epoch int, 0 = already past, use $(( $(date +%s) - 5 )) for "5s ago")
# ---------------------------------------------------------------------------
_write_dispatch_events() {
  local events_file="$1" dispatch_id="$2" end_mode="$3" deadline_ts="$4"
  local now_ts
  now_ts="$(date +%s)"
  local start_ts_iso
  start_ts_iso="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # dispatch_start (past deadline)
  printf '%s\n' \
    "{\"ts\":\"$start_ts_iso\",\"run\":\"__RUN__\",\"kind\":\"dispatch_start\",\"dispatch_id\":\"$dispatch_id\",\"type\":\"test_type\",\"pid\":0,\"timeout_s\":5,\"deadline_ts\":$deadline_ts,\"host\":\"test\"}" \
    >> "$events_file"

  # Optionally write a matching dispatch_end
  if [[ "$end_mode" == "include_end" ]]; then
    printf '%s\n' \
      "{\"ts\":\"$start_ts_iso\",\"run\":\"__RUN__\",\"kind\":\"dispatch_end\",\"dispatch_id\":\"$dispatch_id\",\"exit_code\":0,\"wall_ms\":100,\"host\":\"test\"}" \
      >> "$events_file"
  fi
}

# Helper: count watchdog_stall events in an events.jsonl file.
_count_stall_events() {
  local events_file="$1" match_key="${2:-}" count=0
  [[ -f "$events_file" ]] || { echo 0; return; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    if python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    key = sys.argv[2]
    if d.get('kind') != 'watchdog_stall':
        sys.exit(1)
    if key and d.get('dispatch_id') != key and d.get('reason') != key:
        sys.exit(1)
    sys.exit(0)
except Exception:
    sys.exit(1)
" "$line" "$match_key" 2>/dev/null; then
      count=$(( count + 1 ))
    fi
  done < "$events_file"
  echo "$count"
}

# ---------------------------------------------------------------------------
# TEST-006: dispatch_start past deadline with no dispatch_end → watchdog_stall
# ---------------------------------------------------------------------------
# Invariant: a dispatch_start event whose deadline_ts is in the past and which
# has no matching dispatch_end (same dispatch_id) triggers exactly one
# watchdog_stall emission per sweep detection.
# Failure class: hung supervisor subprocess goes undetected → silent ~20-min stall.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-006: unmatched dispatch_start past deadline → watchdog_stall"

TD_006="$(_tmpdir)"
PLAN_DIR_006="$TD_006/plan"
BASE_DIR_006="$TD_006/base"
EVENTS_006="$BASE_DIR_006/archive/test-run-006/events.jsonl"
mkdir -p "$PLAN_DIR_006" "$BASE_DIR_006/archive/test-run-006"
touch "$EVENTS_006"

REG_SCRIPT_006="$(_write_fake_registry "$TD_006" "test-run-006")"
CFG_SCRIPT_006="$(_write_fake_config "$TD_006")"

# Write a stale dispatch_start (deadline in the past, no matching end).
PAST_DEADLINE_006=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_006" "dispatch-006-stall" "omit_end" "$PAST_DEADLINE_006"

# Helper: count stall events in events.jsonl
_count_stall_006() {
  _count_stall_events "$EVENTS_006" "dispatch-006-stall"
}

# Run watchdog with WD_INTERVAL=1, observe mode (emit only, no notify).
WD_PID_006=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_006" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_006" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_006" \
Z_HARNESS_BASE_DIR="$BASE_DIR_006" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-006" &
WD_PID_006=$!

# Poll for a watchdog_stall event for up to 30 seconds.
_POLL_DEADLINE_006=$(( $(date +%s) + 30 ))
STALL_COUNT_006=0
while [[ $(date +%s) -lt $_POLL_DEADLINE_006 ]]; do
  STALL_COUNT_006="$(_count_stall_006)"
  [[ "$STALL_COUNT_006" -gt 0 ]] && break
  sleep 0.5
done

# Guaranteed teardown before next test.
_kill_watchdog "$WD_PID_006"
WD_PID_006=0

if [[ "$STALL_COUNT_006" -gt 0 ]]; then
  echo "  PASS: watchdog_stall emitted for unmatched dispatch_start (count=$STALL_COUNT_006)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: watchdog_stall not emitted within 30s for unmatched dispatch_start past deadline"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_006"

# ---------------------------------------------------------------------------
# TEST-007: dispatch_start WITH matching dispatch_end → no stall alert
# ---------------------------------------------------------------------------
# Invariant: a dispatch_start that has a matching dispatch_end (same dispatch_id)
# is NOT flagged as a stall — the pair resolved cleanly.
# Failure class: false-positive alert on completed dispatches.
#
# Robustness design: instead of a fixed sleep 3, we poll for evidence that the
# watchdog completed at least one sweep (stall count stays 0 throughout) and then
# force-kill it.  We give 10s for the first sweep to complete and verify no stall.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-007: matched dispatch_start+end → no watchdog_stall"

TD_007="$(_tmpdir)"
PLAN_DIR_007="$TD_007/plan"
BASE_DIR_007="$TD_007/base"
EVENTS_007="$BASE_DIR_007/archive/test-run-007/events.jsonl"
mkdir -p "$PLAN_DIR_007" "$BASE_DIR_007/archive/test-run-007"
touch "$EVENTS_007"

REG_SCRIPT_007="$(_write_fake_registry "$TD_007" "test-run-007")"
CFG_SCRIPT_007="$(_write_fake_config "$TD_007")"

# Write a dispatch_start with a matching dispatch_end (deadline past, but end present).
PAST_DEADLINE_007=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_007" "dispatch-007-ok" "include_end" "$PAST_DEADLINE_007"

_count_stall_007() {
  _count_stall_events "$EVENTS_007" "dispatch-007-ok"
}

# Run watchdog with WD_INTERVAL=1 for at least 3 sweep cycles.
WD_PID_007=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_007" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_007" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_007" \
Z_HARNESS_BASE_DIR="$BASE_DIR_007" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-007" &
WD_PID_007=$!

# Poll until at least one sweep completes (active/ dir created) then wait for 3s
# of additional sweep time to confirm no false positives appear.
# Give startup up to 30s, then allow 3 more seconds of run time.
_STARTUP_DEADLINE_007=$(( $(date +%s) + 30 ))
while [[ $(date +%s) -lt $_STARTUP_DEADLINE_007 ]]; do
  [[ -d "$PLAN_DIR_007/active" ]] && kill -0 "$WD_PID_007" 2>/dev/null && break
  sleep 0.5
done
# Let 3 additional sweep cycles pass (3 × 1s interval = minimum 3s).
sleep 3

# Guaranteed teardown before next test.
_kill_watchdog "$WD_PID_007"
WD_PID_007=0

STALL_COUNT_007="$(_count_stall_007)"

assert_eq \
  "no watchdog_stall for matched dispatch pair" \
  "0" "$STALL_COUNT_007"

rm -rf "$TD_007"

# ---------------------------------------------------------------------------
# TEST-008: two concurrent dispatches (distinct dispatch_ids) — each matched correctly
# ---------------------------------------------------------------------------
# Invariant: two concurrent same-type dispatches with distinct dispatch_ids are
# matched independently: each dispatch_start↔dispatch_end pair is matched strictly
# by dispatch_id, never by type or position. A dispatch_end for id-A does not
# close id-B's start.
# Failure class: cross-match false positive/negative — one stall goes undetected
# while a clean dispatch is flagged.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-008: two concurrent dispatches — each end attributed to its own start"

TD_008="$(_tmpdir)"
PLAN_DIR_008="$TD_008/plan"
BASE_DIR_008="$TD_008/base"
EVENTS_008="$BASE_DIR_008/archive/test-run-008/events.jsonl"
mkdir -p "$PLAN_DIR_008" "$BASE_DIR_008/archive/test-run-008"
touch "$EVENTS_008"

REG_SCRIPT_008="$(_write_fake_registry "$TD_008" "test-run-008")"
CFG_SCRIPT_008="$(_write_fake_config "$TD_008")"

# Write two concurrent dispatches (same type, distinct ids):
#   - dispatch-008-A: has start + end (clean)
#   - dispatch-008-B: has start only, no end (stall)
PAST_DEADLINE_008=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_008" "dispatch-008-A" "include_end" "$PAST_DEADLINE_008"
_write_dispatch_events "$EVENTS_008" "dispatch-008-B" "omit_end"    "$PAST_DEADLINE_008"

_count_stall_008_A() {
  _count_stall_events "$EVENTS_008" "dispatch-008-A"
}
_count_stall_008_B() {
  _count_stall_events "$EVENTS_008" "dispatch-008-B"
}

WD_PID_008=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_008" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_008" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_008" \
Z_HARNESS_BASE_DIR="$BASE_DIR_008" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-008" &
WD_PID_008=$!

# Poll until dispatch-008-B stall is detected (up to 30s).
_POLL_DEADLINE_008=$(( $(date +%s) + 30 ))
STALL_B_008=0
while [[ $(date +%s) -lt $_POLL_DEADLINE_008 ]]; do
  STALL_B_008="$(_count_stall_008_B)"
  [[ "$STALL_B_008" -gt 0 ]] && break
  sleep 0.5
done

# Guaranteed teardown before next test.
_kill_watchdog "$WD_PID_008"
WD_PID_008=0

STALL_A_008="$(_count_stall_008_A)"

# Clean dispatch (A) must NOT be flagged.
assert_eq \
  "clean dispatch-008-A not flagged as stall (no cross-match false positive)" \
  "0" "$STALL_A_008"

# Stalled dispatch (B) must BE flagged.
if [[ "$STALL_B_008" -gt 0 ]]; then
  echo "  PASS: stalled dispatch-008-B detected (count=$STALL_B_008)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: stalled dispatch-008-B not detected within 30s"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_008"

# ---------------------------------------------------------------------------
# TEST-009: observe level → watchdog_stall emitted but notify-watchdog.sh NOT called
# ---------------------------------------------------------------------------
# Invariant: at intervention_level=observe the sweep emits watchdog_stall but never
# invokes notify-watchdog.sh.  notify-watchdog.sh is replaced by a sentinel script
# that writes a flag file if called — absence of the flag proves non-invocation.
# Failure class: observe mode accidentally pages the user (alert fatigue).
# ---------------------------------------------------------------------------

echo ""
echo "TEST-009: observe level → stall emitted, notify NOT called"

TD_009="$(_tmpdir)"
PLAN_DIR_009="$TD_009/plan"
BASE_DIR_009="$TD_009/base"
EVENTS_009="$BASE_DIR_009/archive/test-run-009/events.jsonl"
mkdir -p "$PLAN_DIR_009" "$BASE_DIR_009/archive/test-run-009"
touch "$EVENTS_009"

REG_SCRIPT_009="$(_write_fake_registry "$TD_009" "test-run-009")"

# Fake config that returns intervention_level=observe
CFG_SCRIPT_009="$TD_009/cfg-observe.py"
printf '#!/usr/bin/env python3\nimport sys, os\nargs=sys.argv[1:]\nif args and args[0]=="get":\n    key=args[1] if len(args)>1 else ""\n    if key=="watchdog.enabled": print("true")\n    elif key=="watchdog.sweep_interval_secs": print(os.environ.get("WD_INTERVAL","1"))\n    elif key=="watchdog.max_lifetime_secs": print("86400")\n    elif key=="watchdog.stale_secs": print("1")\n    elif key=="watchdog.intervention_level": print("observe")\n    else: sys.exit(1)\nelse: sys.exit(1)\n' > "$CFG_SCRIPT_009"
chmod +x "$CFG_SCRIPT_009"

# Sentinel notify script: creates a flag file if called.
NOTIFY_FLAG_009="$TD_009/notify-called.flag"
FAKE_NOTIFY_009="$TD_009/fake-notify.sh"
printf '#!/usr/bin/env bash\ntouch "%s"\n' "$NOTIFY_FLAG_009" > "$FAKE_NOTIFY_009"
chmod +x "$FAKE_NOTIFY_009"

PAST_DEADLINE_009=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_009" "dispatch-009-stall" "omit_end" "$PAST_DEADLINE_009"

_count_stall_009() {
  _count_stall_events "$EVENTS_009" "dispatch-009-stall"
}

WD_PID_009=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_009" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_009" \
WATCHDOG_NOTIFY_SCRIPT="$FAKE_NOTIFY_009" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_009" \
Z_HARNESS_BASE_DIR="$BASE_DIR_009" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-009" &
WD_PID_009=$!

# Poll for stall event (proves detection ran) — up to 30s.
_POLL_DEADLINE_009=$(( $(date +%s) + 30 ))
STALL_COUNT_009=0
while [[ $(date +%s) -lt $_POLL_DEADLINE_009 ]]; do
  STALL_COUNT_009="$(_count_stall_009)"
  [[ "$STALL_COUNT_009" -gt 0 ]] && break
  sleep 0.5
done

# Guaranteed teardown before next test.
_kill_watchdog "$WD_PID_009"
WD_PID_009=0

# Brief wait for any background notify to potentially create the flag.
sleep 1

# Stall event must have been emitted.
if [[ "$STALL_COUNT_009" -gt 0 ]]; then
  echo "  PASS: watchdog_stall emitted in observe mode (count=$STALL_COUNT_009)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: watchdog_stall not emitted in observe mode"
  FAIL=$(( FAIL + 1 ))
fi

# Notify must NOT have been called.
if [[ ! -f "$NOTIFY_FLAG_009" ]]; then
  echo "  PASS: notify-watchdog.sh not invoked in observe mode"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: notify-watchdog.sh was invoked in observe mode (should be suppressed)"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_009"

# ---------------------------------------------------------------------------
# TEST-010: notify-once dedup — same stall re-detected → only ONE notification
# ---------------------------------------------------------------------------
# Invariant: repeated re-detection of the SAME stall (same dispatch_id) within
# one run must not trigger more than one notify-watchdog.sh invocation.
# The notify-once marker file prevents re-notification.
# Failure class: repeated re-detections re-spam the user (alert fatigue).
#
# Robustness design: instead of a fixed sleep 4 to let 4 sweep cycles pass,
# we poll until the first notification is confirmed (stall detected once), then
# wait for additional sweeps by polling for a stable notification count.  We
# assert that the count never exceeds 1 after 5s of additional run time.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-010: same stall re-detected → only one notification (notify-once)"

TD_010="$(_tmpdir)"
PLAN_DIR_010="$TD_010/plan"
BASE_DIR_010="$TD_010/base"
EVENTS_010="$BASE_DIR_010/archive/test-run-010/events.jsonl"
mkdir -p "$PLAN_DIR_010" "$BASE_DIR_010/archive/test-run-010"
touch "$EVENTS_010"

REG_SCRIPT_010="$(_write_fake_registry "$TD_010" "test-run-010")"
CFG_SCRIPT_010="$(_write_fake_config "$TD_010")"

# Sentinel notify: appends a line to a counter file each time it's called.
NOTIFY_COUNTER_010="$TD_010/notify-count.txt"
FAKE_NOTIFY_010="$TD_010/fake-notify.sh"
printf '#!/usr/bin/env bash\nprintf "notified\\n" >> "%s"\n' "$NOTIFY_COUNTER_010" > "$FAKE_NOTIFY_010"
chmod +x "$FAKE_NOTIFY_010"

# Stale dispatch: no end, deadline in the past.
PAST_DEADLINE_010=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_010" "dispatch-010-stall" "omit_end" "$PAST_DEADLINE_010"

WD_PID_010=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_010" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_010" \
WATCHDOG_NOTIFY_SCRIPT="$FAKE_NOTIFY_010" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_010" \
Z_HARNESS_BASE_DIR="$BASE_DIR_010" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-010" &
WD_PID_010=$!

# Poll until the notify counter file is created (first notification fired) — up to 30s.
_POLL_DEADLINE_010=$(( $(date +%s) + 30 ))
while [[ $(date +%s) -lt $_POLL_DEADLINE_010 ]]; do
  [[ -f "$NOTIFY_COUNTER_010" ]] && break
  sleep 0.5
done

# Allow 4 more sweep cycles (4 × 1s) to confirm no re-notification fires.
sleep 4

# Guaranteed teardown before next test.
_kill_watchdog "$WD_PID_010"
WD_PID_010=0

# Wait for any in-flight background notify to finish.
sleep 1

NOTIFY_CALL_COUNT_010=0
[[ -f "$NOTIFY_COUNTER_010" ]] && NOTIFY_CALL_COUNT_010="$(wc -l < "$NOTIFY_COUNTER_010" | tr -d ' ')"

assert_eq \
  "same stall re-detected → exactly one notify invocation" \
  "1" "$NOTIFY_CALL_COUNT_010"

rm -rf "$TD_010"

# ---------------------------------------------------------------------------
# TEST-011: two DISTINCT stalls → two notifications
# ---------------------------------------------------------------------------
# Invariant: two distinct stalls (different dispatch_ids) each trigger their own
# notify-watchdog.sh invocation — the notify-once dedup is per-stall, not global.
# Failure class: second distinct stall goes silently unnotified.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-011: two distinct stalls → two notifications"

TD_011="$(_tmpdir)"
PLAN_DIR_011="$TD_011/plan"
BASE_DIR_011="$TD_011/base"
EVENTS_011="$BASE_DIR_011/archive/test-run-011/events.jsonl"
mkdir -p "$PLAN_DIR_011" "$BASE_DIR_011/archive/test-run-011"
touch "$EVENTS_011"

REG_SCRIPT_011="$(_write_fake_registry "$TD_011" "test-run-011")"
CFG_SCRIPT_011="$(_write_fake_config "$TD_011")"

# Sentinel notify: appends a line each time called.
NOTIFY_COUNTER_011="$TD_011/notify-count.txt"
FAKE_NOTIFY_011="$TD_011/fake-notify.sh"
printf '#!/usr/bin/env bash\nprintf "notified\\n" >> "%s"\n' "$NOTIFY_COUNTER_011" > "$FAKE_NOTIFY_011"
chmod +x "$FAKE_NOTIFY_011"

# Two distinct stale dispatches (both past deadline, neither has a matching end).
PAST_DEADLINE_011=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_011" "dispatch-011-stall-X" "omit_end" "$PAST_DEADLINE_011"
_write_dispatch_events "$EVENTS_011" "dispatch-011-stall-Y" "omit_end" "$PAST_DEADLINE_011"

_count_stall_011_X() {
  _count_stall_events "$EVENTS_011" "dispatch-011-stall-X"
}
_count_stall_011_Y() {
  _count_stall_events "$EVENTS_011" "dispatch-011-stall-Y"
}

WD_PID_011=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_011" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_011" \
WATCHDOG_NOTIFY_SCRIPT="$FAKE_NOTIFY_011" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_011" \
Z_HARNESS_BASE_DIR="$BASE_DIR_011" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-011" &
WD_PID_011=$!

# Poll until both stalls are detected (up to 30s).
_POLL_DEADLINE_011=$(( $(date +%s) + 30 ))
STALL_X_011=0 STALL_Y_011=0
while [[ $(date +%s) -lt $_POLL_DEADLINE_011 ]]; do
  STALL_X_011="$(_count_stall_011_X)"
  STALL_Y_011="$(_count_stall_011_Y)"
  [[ "$STALL_X_011" -gt 0 && "$STALL_Y_011" -gt 0 ]] && break
  sleep 0.5
done

# Guaranteed teardown before next test.
_kill_watchdog "$WD_PID_011"
WD_PID_011=0

# Wait for background notify to finish.
sleep 1

NOTIFY_CALL_COUNT_011=0
[[ -f "$NOTIFY_COUNTER_011" ]] && NOTIFY_CALL_COUNT_011="$(wc -l < "$NOTIFY_COUNTER_011" | tr -d ' ')"

if [[ "$STALL_X_011" -gt 0 && "$STALL_Y_011" -gt 0 ]]; then
  echo "  PASS: both distinct stalls detected (X=$STALL_X_011, Y=$STALL_Y_011)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: not both stalls detected within 30s (X=$STALL_X_011, Y=$STALL_Y_011)"
  FAIL=$(( FAIL + 1 ))
fi

assert_eq \
  "two distinct stalls → exactly two notify invocations" \
  "2" "$NOTIFY_CALL_COUNT_011"

rm -rf "$TD_011"

# ---------------------------------------------------------------------------
# TEST-012: overnight Z_HARNESS_NO_ASK=halt → HALT sentinel written + self-exit
# ---------------------------------------------------------------------------
# Invariant: when Z_HARNESS_NO_ASK=halt and a confirmed stall is detected,
# the sweep writes $Z_HARNESS_PLAN_DIR/HALT and then self-exits (stop-flag set).
# Failure class: overnight run dead-waits indefinitely on a stall with no
# human present to intervene.
#
# Robustness design: replaced the fixed "timeout 15" wrapper (which races under
# load) with a background watchdog + poll loop that waits for EITHER the HALT
# sentinel file appearing OR the watchdog process self-exiting — whichever comes
# first — within a generous 30s budget.  This tolerates large scheduling jitter
# while still failing fast on a genuine miss.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-012: overnight NO_ASK=halt → HALT written + watchdog exits"

TD_012="$(_tmpdir)"
PLAN_DIR_012="$TD_012/plan"
BASE_DIR_012="$TD_012/base"
EVENTS_012="$BASE_DIR_012/archive/test-run-012/events.jsonl"
mkdir -p "$PLAN_DIR_012" "$BASE_DIR_012/archive/test-run-012"
touch "$EVENTS_012"

REG_SCRIPT_012="$(_write_fake_registry "$TD_012" "test-run-012")"
CFG_SCRIPT_012="$(_write_fake_config "$TD_012")"

PAST_DEADLINE_012=$(( $(date +%s) - 10 ))
_write_dispatch_events "$EVENTS_012" "dispatch-012-stall" "omit_end" "$PAST_DEADLINE_012"

# Run watchdog in background (not via timeout) with NO_ASK=halt.
# The watchdog should self-exit after writing HALT.
WD_PID_012=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
Z_HARNESS_NO_ASK=halt \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_012" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_012" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_012" \
Z_HARNESS_BASE_DIR="$BASE_DIR_012" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-012" &
WD_PID_012=$!

# Poll for EITHER the HALT sentinel appearing OR the watchdog process exiting
# (self-exit after writing HALT) — up to 30s.
# This replaces the old fixed "timeout 15" wrapper which raced under load.
_POLL_DEADLINE_012=$(( $(date +%s) + 30 ))
HALT_FOUND_012=0
WD_EXITED_012=0
while [[ $(date +%s) -lt $_POLL_DEADLINE_012 ]]; do
  if [[ -f "$PLAN_DIR_012/HALT" ]]; then
    HALT_FOUND_012=1
  fi
  if ! kill -0 "$WD_PID_012" 2>/dev/null; then
    WD_EXITED_012=1
  fi
  [[ "$HALT_FOUND_012" -eq 1 && "$WD_EXITED_012" -eq 1 ]] && break
  sleep 0.5
done

# Capture exit code — bounded: if the process is still alive after the poll loop
# deadline (WD_EXITED_012=0), it did NOT self-exit within 30s.  Force-kill and
# record a non-zero sentinel so the assertion below catches the failure.
RC_012=0
if [[ "$WD_EXITED_012" -eq 1 ]]; then
  # Process already exited; reap the zombie and capture its exit code.
  wait "$WD_PID_012" 2>/dev/null || RC_012=$?
else
  # Did NOT exit within the 30s window — this is the failure the test should catch.
  RC_012=1   # non-zero sentinel: "still alive" = did not self-exit after HALT
  _kill_watchdog "$WD_PID_012"
fi
WD_PID_012=0

# Watchdog should exit 0 (clean self-exit after writing HALT).
assert_eq \
  "watchdog exits 0 after writing HALT" \
  "0" "$RC_012"

# HALT sentinel must exist.
if [[ "$HALT_FOUND_012" -eq 1 ]]; then
  echo "  PASS: HALT sentinel written"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: HALT sentinel not found at $PLAN_DIR_012/HALT after 30s"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_012"

# ---------------------------------------------------------------------------
# TEST-013: liveness-detected subagent stall → watchdog_stall with phase=unmatched_subagent_start
# ---------------------------------------------------------------------------
# Invariant: when liveness.sh (exit 1) reports an unmatched subagent *_start,
# the sweep emits a watchdog_stall event with phase="unmatched_subagent_start"
# and a non-null reason derived from the liveness output.
# Failure class: native Agent() stalls (undetectable via dispatch lease) never
# surface as watchdog_stall → the human is never alerted.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-013: liveness-detected subagent stall → watchdog_stall with phase=unmatched_subagent_start"

TD_013="$(_tmpdir)"
PLAN_DIR_013="$TD_013/plan"
BASE_DIR_013="$TD_013/base"
EVENTS_013="$BASE_DIR_013/archive/test-run-013/events.jsonl"
mkdir -p "$PLAN_DIR_013" "$BASE_DIR_013/archive/test-run-013"
touch "$EVENTS_013"

REG_SCRIPT_013="$(_write_fake_registry "$TD_013" "test-run-013")"
CFG_SCRIPT_013="$(_write_fake_config "$TD_013")"

# Fake liveness.sh that exits 1 and prints a stale subagent line.
FAKE_LIVENESS_013="$TD_013/fake-liveness.sh"
cat > "$FAKE_LIVENESS_013" <<'LIVENESS_EOF'
#!/usr/bin/env bash
# Fake liveness.sh: always reports one stale subagent implement_start [T001].
echo ""
echo "Run: test-run-013"
echo "  events.jsonl: /fake/path"
echo "  possibly stuck (elapsed >= 1s):"
echo "    - implement_start [T001]: 600s ago  (ts=2024-01-01T00:00:00Z)"
exit 1
LIVENESS_EOF
chmod +x "$FAKE_LIVENESS_013"

# Helper: count watchdog_stall events with phase=unmatched_subagent_start
_count_liveness_stall_013() {
  local count=0
  [[ -f "$EVENTS_013" ]] || { echo 0; return; }
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" ]] && continue
    if python3 -c "
import json, sys
try:
    d = json.loads(sys.argv[1])
    ok = (d.get('kind') == 'watchdog_stall'
          and d.get('phase') == 'unmatched_subagent_start'
          and d.get('reason', '') != '')
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
" "$line" 2>/dev/null; then
      count=$(( count + 1 ))
    fi
  done < "$EVENTS_013"
  echo "$count"
}

WD_PID_013=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_013" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_013" \
WATCHDOG_LIVENESS_SCRIPT="$FAKE_LIVENESS_013" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_013" \
Z_HARNESS_BASE_DIR="$BASE_DIR_013" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-013" &
WD_PID_013=$!

# Poll for the liveness-sourced watchdog_stall event — up to 30s.
_POLL_DEADLINE_013=$(( $(date +%s) + 30 ))
LIVENESS_STALL_COUNT_013=0
while [[ $(date +%s) -lt $_POLL_DEADLINE_013 ]]; do
  LIVENESS_STALL_COUNT_013="$(_count_liveness_stall_013)"
  [[ "$LIVENESS_STALL_COUNT_013" -gt 0 ]] && break
  sleep 0.5
done

# Guaranteed teardown before summary.
_kill_watchdog "$WD_PID_013"
WD_PID_013=0

if [[ "$LIVENESS_STALL_COUNT_013" -gt 0 ]]; then
  echo "  PASS: liveness-detected stall emitted watchdog_stall(phase=unmatched_subagent_start) ($LIVENESS_STALL_COUNT_013)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: liveness-detected stall did not produce watchdog_stall within 30s"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_013"

# ---------------------------------------------------------------------------
# TEST-014: dispatch stall with real pid → notify-watchdog.sh called with --pid,
#           alert message contains "To kill: kill <pid>"
# ---------------------------------------------------------------------------
# Invariant: when a dispatch_start event carries a real (non-zero, non-null) pid,
# _wd_handle_stall forwards --pid <pid> to notify-watchdog.sh so the alert message
# includes "To kill: kill <pid>".
# Failure class: dispatch stall alerts omit the kill-pid line even when the pid
# is known, leaving the operator no actionable way to unblock the run.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-014: dispatch stall with real pid → notify called with --pid + kill line"

TD_014="$(_tmpdir)"
PLAN_DIR_014="$TD_014/plan"
BASE_DIR_014="$TD_014/base"
EVENTS_014="$BASE_DIR_014/archive/test-run-014/events.jsonl"
mkdir -p "$PLAN_DIR_014" "$BASE_DIR_014/archive/test-run-014"
touch "$EVENTS_014"

REG_SCRIPT_014="$(_write_fake_registry "$TD_014" "test-run-014")"
CFG_SCRIPT_014="$(_write_fake_config "$TD_014")"

# Sentinel notify: records all arguments it receives so we can inspect them.
NOTIFY_ARGS_014="$TD_014/notify-args.txt"
FAKE_NOTIFY_014="$TD_014/fake-notify.sh"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\n' "$NOTIFY_ARGS_014" > "$FAKE_NOTIFY_014"
chmod +x "$FAKE_NOTIFY_014"

# Write a dispatch_start with a REAL pid (non-zero, non-null).
REAL_PID_014=12345
PAST_DEADLINE_014=$(( $(date +%s) - 10 ))
local_ts_014="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\n' \
  "{\"ts\":\"$local_ts_014\",\"run\":\"test-run-014\",\"kind\":\"dispatch_start\",\"dispatch_id\":\"dispatch-014-stall\",\"type\":\"test_type\",\"pid\":$REAL_PID_014,\"timeout_s\":5,\"deadline_ts\":$PAST_DEADLINE_014,\"host\":\"test\"}" \
  >> "$EVENTS_014"

WD_PID_014=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_014" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_014" \
WATCHDOG_NOTIFY_SCRIPT="$FAKE_NOTIFY_014" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_014" \
Z_HARNESS_BASE_DIR="$BASE_DIR_014" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-014" &
WD_PID_014=$!

# Poll until notify is called (up to 30s).
_POLL_DEADLINE_014=$(( $(date +%s) + 30 ))
while [[ $(date +%s) -lt $_POLL_DEADLINE_014 ]]; do
  [[ -f "$NOTIFY_ARGS_014" ]] && break
  sleep 0.5
done

# Guaranteed teardown.
_kill_watchdog "$WD_PID_014"
WD_PID_014=0

# Brief wait for background notify to finish writing args.
sleep 0.5

if [[ -f "$NOTIFY_ARGS_014" ]]; then
  NOTIFY_ARGS_STR_014="$(cat "$NOTIFY_ARGS_014")"

  # Assert --pid 12345 was passed to notify-watchdog.sh.
  if echo "$NOTIFY_ARGS_STR_014" | grep -qF -- "--pid $REAL_PID_014"; then
    echo "  PASS: notify-watchdog.sh invoked with --pid $REAL_PID_014"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: notify-watchdog.sh not invoked with --pid $REAL_PID_014"
    echo "        actual args: $NOTIFY_ARGS_STR_014"
    FAIL=$(( FAIL + 1 ))
  fi
else
  echo "  FAIL: notify-watchdog.sh was never called within 30s"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_014"

# ---------------------------------------------------------------------------
# TEST-015: liveness (pid-less) stall → notify called WITHOUT --pid
# ---------------------------------------------------------------------------
# Invariant: for liveness-detected stalls (native Agent() stalls), no pid is
# known.  _wd_handle_stall must omit --pid entirely so notify-watchdog.sh does
# not emit a bogus "To kill: kill 0" or "To kill: kill null" line.
# Failure class: pid-less stall alert contains a bogus/misleading kill-pid line.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-015: liveness stall (no pid) → notify called WITHOUT --pid"

TD_015="$(_tmpdir)"
PLAN_DIR_015="$TD_015/plan"
BASE_DIR_015="$TD_015/base"
EVENTS_015="$BASE_DIR_015/archive/test-run-015/events.jsonl"
mkdir -p "$PLAN_DIR_015" "$BASE_DIR_015/archive/test-run-015"
touch "$EVENTS_015"

REG_SCRIPT_015="$(_write_fake_registry "$TD_015" "test-run-015")"
CFG_SCRIPT_015="$(_write_fake_config "$TD_015")"

# Sentinel notify: records all arguments it receives.
NOTIFY_ARGS_015="$TD_015/notify-args.txt"
FAKE_NOTIFY_015="$TD_015/fake-notify.sh"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\n' "$NOTIFY_ARGS_015" > "$FAKE_NOTIFY_015"
chmod +x "$FAKE_NOTIFY_015"

# Fake liveness.sh: reports a stale subagent start (pid-less liveness stall).
FAKE_LIVENESS_015="$TD_015/fake-liveness.sh"
cat > "$FAKE_LIVENESS_015" <<'LIVENESS_EOF'
#!/usr/bin/env bash
echo ""
echo "Run: test-run-015"
echo "  events.jsonl: /fake/path"
echo "  possibly stuck (elapsed >= 1s):"
echo "    - implement_start [T002]: 700s ago  (ts=2024-01-01T00:00:00Z)"
exit 1
LIVENESS_EOF
chmod +x "$FAKE_LIVENESS_015"

WD_PID_015=0
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=1 \
WD_STALE_SECS=1 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_015" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_015" \
WATCHDOG_NOTIFY_SCRIPT="$FAKE_NOTIFY_015" \
WATCHDOG_LIVENESS_SCRIPT="$FAKE_LIVENESS_015" \
WATCHDOG_GUARD_TIMEOUT=1 \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_015" \
Z_HARNESS_BASE_DIR="$BASE_DIR_015" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-015" &
WD_PID_015=$!

# Poll until notify is called (up to 30s).
_POLL_DEADLINE_015=$(( $(date +%s) + 30 ))
while [[ $(date +%s) -lt $_POLL_DEADLINE_015 ]]; do
  [[ -f "$NOTIFY_ARGS_015" ]] && break
  sleep 0.5
done

# Guaranteed teardown.
_kill_watchdog "$WD_PID_015"
WD_PID_015=0

sleep 0.5

if [[ -f "$NOTIFY_ARGS_015" ]]; then
  NOTIFY_ARGS_STR_015="$(cat "$NOTIFY_ARGS_015")"

  # Assert notify was called (proves detection ran and notified).
  echo "  PASS: notify-watchdog.sh was called for liveness stall"
  PASS=$(( PASS + 1 ))

  # Assert --pid was NOT passed (liveness stalls have no killable pid).
  if echo "$NOTIFY_ARGS_STR_015" | grep -qF -- "--pid"; then
    echo "  FAIL: notify-watchdog.sh incorrectly received --pid for pid-less liveness stall"
    echo "        actual args: $NOTIFY_ARGS_STR_015"
    FAIL=$(( FAIL + 1 ))
  else
    echo "  PASS: notify-watchdog.sh NOT called with --pid for liveness stall"
    PASS=$(( PASS + 1 ))
  fi
else
  echo "  FAIL: notify-watchdog.sh was never called for liveness stall within 30s"
  FAIL=$(( FAIL + 1 ))
  # Skip the --pid check since notify never fired.
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_015"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
