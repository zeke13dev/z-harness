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
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_001" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_001" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_001" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  timeout 10 bash "$WATCHDOG" --run "test-run-001" \
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
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_002" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_002" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_002" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  timeout 10 bash "$WATCHDOG" --run "test-run-002" \
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
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_003" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_003" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_003" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  timeout 10 bash "$WATCHDOG" --run "test-run-003" \
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
FAKE_RUN_PRESENT=1 \
WD_ENABLED=true \
WD_INTERVAL=3 \
WATCHDOG_REGISTRY_SCRIPT="$REG_SCRIPT_004" \
WATCHDOG_CONFIG_SCRIPT="$CFG_SCRIPT_004" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_004" \
Z_HARNESS_REGISTRY_ENABLED=1 \
  bash "$WATCHDOG" --run "test-run-004" &
WD_PID_004=$!

# Give watchdog time to start and enter the sleep phase after first sweep.
sleep 2

# Send SIGTERM mid-sleep (between iterations).
kill -TERM "$WD_PID_004" 2>/dev/null || true

# Wait for watchdog to exit cleanly (up to 5 seconds).
WD_EXIT_004=0
wait "$WD_PID_004" 2>/dev/null || WD_EXIT_004=$?

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
# runs in background and we POLL events.jsonl for up to 15s (check every 0.5s).
# As soon as the event appears we assert (a) the watchdog was still alive (no
# false-self-exit) and (b) the event genuinely emitted.  This removes the race
# between first-emit timing and a hard wall-clock cap.
# WATCHDOG_GUARD_TIMEOUT=1 (was 2) ensures the first inconclusive event fires
# within ~1s, well inside the 15s polling budget even under heavy system load.
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

# Poll for the target event for up to 15 seconds (check every 0.5s).
# This avoids any race between first-emit timing and a fixed outer cap.
_POLL_DEADLINE_005=$(( $(date +%s) + 15 ))
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

# Clean up: SIGTERM the watchdog and wait for it.
kill -TERM "$WD_PID_005" 2>/dev/null || true
wait "$WD_PID_005" 2>/dev/null || true

# Assertion (a): watchdog was still alive when the event appeared (no false-self-exit).
assert_eq \
  "watchdog still looping when event appeared (not false-self-exited)" \
  "1" "$WD_STILL_ALIVE_005"

# Assertion (b): the event was genuinely emitted.
if [[ "$INCONCLUSIVE_COUNT_005" -gt 0 ]]; then
  echo "  PASS: watchdog_scan_inconclusive(registry_read_timeout) emitted ($INCONCLUSIVE_COUNT_005 times)"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: watchdog_scan_inconclusive(registry_read_timeout) not found in events at $EVENTS_005 after 15s"
  FAIL=$(( FAIL + 1 ))
fi

rm -rf "$TD_005"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
