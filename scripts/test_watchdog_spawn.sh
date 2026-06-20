#!/usr/bin/env bash
# test_watchdog_spawn.sh — Shell tests for scripts/watchdog-spawn.sh.
#
# Tests covered:
#   TEST-SP-001: two concurrent spawn calls for the same run → exactly one live sweep.
#   TEST-SP-002: stale pid file (dead pid) → re-spawn allowed.
#   TEST-SP-003: spawn returns promptly and sweep survives the spawning shell.
#
# Timing notes:
#   All tests use poll-based waits (not fixed sleeps) with generous deadlines
#   to remain robust under CI load.  Teardown always kills spawned sweeps.
#
# Run with:
#   bash scripts/test_watchdog_spawn.sh

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SPAWN="$SCRIPTS_DIR/watchdog-spawn.sh"
WATCHDOG="$SCRIPTS_DIR/watchdog-sweep.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/test_watchdog_spawn_XXXXXX"
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

assert_true() {
  local label="$1" cond_rc="$2"
  if [[ "$cond_rc" -eq 0 ]]; then
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label"
    FAIL=$(( FAIL + 1 ))
  fi
}

assert_false() {
  local label="$1" cond_rc="$2"
  if [[ "$cond_rc" -ne 0 ]]; then
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label (expected non-zero, got 0)"
    FAIL=$(( FAIL + 1 ))
  fi
}

# Kill all processes listed in a pid file (best-effort teardown).
_kill_pid_file() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 0
  local pid
  pid="$(cat "$pid_file" 2>/dev/null | tr -dc '0-9')" || return 0
  [[ -z "$pid" || "$pid" -eq 0 ]] && return 0
  kill -TERM "$pid" 2>/dev/null || true
  local i=0
  while kill -0 "$pid" 2>/dev/null && [[ $i -lt 30 ]]; do
    sleep 0.1
    i=$(( i + 1 ))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

# Poll until a condition command exits 0 or the deadline is passed.
# Returns 0 if the condition became true before the deadline, else 1.
_poll_until() {
  local deadline="$1"
  shift
  while [[ $(date +%s) -lt $deadline ]]; do
    if "$@" 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

# Write a fake watchdog-sweep.sh that just sleeps (for isolation).
# The fake sweep creates a marker file so we can count live instances.
_write_fake_sweep() {
  local dir="$1" marker_dir="$2"
  local script="$dir/fake-sweep.sh"
  cat > "$script" <<SWEEPEOF
#!/usr/bin/env bash
# Fake sweep: sleep indefinitely, removing marker on exit.
mkdir -p "${marker_dir}"
MARKER="${marker_dir}/\$\$.alive"
touch "\$MARKER"
trap 'rm -f "\$MARKER"' EXIT TERM INT
# Drain any Z_HARNESS_ env check — always treat registry as enabled.
# Just sleep; the real sweep would poll; we only need longevity here.
while true; do sleep 1; done
SWEEPEOF
  chmod +x "$script"
  echo "$script"
}

# Count alive marker files in the marker dir (each live fake-sweep creates one).
_count_alive() {
  local marker_dir="$1"
  [[ -d "$marker_dir" ]] || { echo 0; return; }
  local count
  count="$(find "$marker_dir" -name '*.alive' | wc -l | tr -d ' ')"
  echo "$count"
}

# ---------------------------------------------------------------------------
# TEST-SP-001: two concurrent spawn calls → exactly ONE live sweep
# ---------------------------------------------------------------------------
# Invariant: the flock'd PID file ensures at most one sweep per run.
# Failure class: two sweeps run concurrently → duplicate stall detection +
#   double alerts.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-SP-001: two concurrent spawn calls → exactly one live sweep"

TD_001="$(_tmpdir)"
PLAN_DIR_001="$TD_001/plan"
MARKER_DIR_001="$TD_001/markers"
mkdir -p "$PLAN_DIR_001" "$MARKER_DIR_001"

FAKE_SWEEP_001="$(_write_fake_sweep "$TD_001" "$MARKER_DIR_001")"

RC_SP1=0 RC_SP2=0

# Launch two concurrent spawns; they race on the flock.
WATCHDOG_SWEEP_SCRIPT="$FAKE_SWEEP_001" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_001" \
  bash "$SPAWN" --run "test-sp-001" &
SP1_PID=$!

WATCHDOG_SWEEP_SCRIPT="$FAKE_SWEEP_001" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_001" \
  bash "$SPAWN" --run "test-sp-001" &
SP2_PID=$!

# Wait for both spawn calls to complete (they should return promptly).
# Bounded: poll up to 10s each, then force-kill and record failure.
_bounded_wait_spawn() {
  local pid="$1" rc_var="$2"
  local _w=0
  while kill -0 "$pid" 2>/dev/null && [[ $_w -lt 100 ]]; do
    sleep 0.1
    _w=$(( _w + 1 ))
  done
  if kill -0 "$pid" 2>/dev/null; then
    # Did NOT return within 10s — force-kill and signal failure.
    kill -KILL "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    printf -v "$rc_var" '%s' "1"
  else
    local _exit=0
    wait "$pid" 2>/dev/null || _exit=$?
    printf -v "$rc_var" '%s' "$_exit"
  fi
}
_bounded_wait_spawn "$SP1_PID" RC_SP1
_bounded_wait_spawn "$SP2_PID" RC_SP2

assert_eq "both spawn calls exit 0" "0" "$(( RC_SP1 + RC_SP2 ))"

# Poll until at least one sweep is alive (allow up to 10s for the daemon to start).
DEADLINE_001=$(( $(date +%s) + 10 ))
_is_alive_001() { [[ "$(_count_alive "$MARKER_DIR_001")" -ge 1 ]]; }
_poll_until "$DEADLINE_001" _is_alive_001 || true

# Give any duplicate a brief window to also start (2s generous).
sleep 2

ALIVE_001="$(_count_alive "$MARKER_DIR_001")"
assert_eq "exactly one live sweep after two concurrent spawn calls" "1" "$ALIVE_001"

# Teardown: kill the sweep via pid file.
_kill_pid_file "$PLAN_DIR_001/active/test-sp-001.watchdog.pid"
rm -rf "$TD_001"

# ---------------------------------------------------------------------------
# TEST-SP-002: stale pid file (dead pid) → re-spawn allowed
# ---------------------------------------------------------------------------
# Invariant: if the pid in the file is dead, spawn treats the slot as empty
#   and starts a new sweep.
# Failure class: stale pid prevents watchdog restart after a crash.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-SP-002: stale pid file → re-spawn allowed"

TD_002="$(_tmpdir)"
PLAN_DIR_002="$TD_002/plan"
MARKER_DIR_002="$TD_002/markers"
ACTIVE_DIR_002="$PLAN_DIR_002/active"
mkdir -p "$ACTIVE_DIR_002" "$MARKER_DIR_002"

FAKE_SWEEP_002="$(_write_fake_sweep "$TD_002" "$MARKER_DIR_002")"
PID_FILE_002="$ACTIVE_DIR_002/test-sp-002.watchdog.pid"

# Write a definitely-dead pid (PID 1 is init and cannot be killed; use a
# never-alive pid in the high range — most systems won't have PID 2000000).
# We start a subshell, capture its PID, kill it, then use that dead PID.
bash -c 'sleep 999' &
DEAD_PID=$!
kill -KILL "$DEAD_PID" 2>/dev/null || true
wait "$DEAD_PID" 2>/dev/null || true
# $DEAD_PID is now definitely dead.
echo "$DEAD_PID" > "$PID_FILE_002"

RC_002=0
WATCHDOG_SWEEP_SCRIPT="$FAKE_SWEEP_002" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_002" \
  bash "$SPAWN" --run "test-sp-002" || RC_002=$?

assert_eq "spawn with stale pid exits 0" "0" "$RC_002"

# Poll until sweep is alive.
DEADLINE_002=$(( $(date +%s) + 10 ))
_is_alive_002() { [[ "$(_count_alive "$MARKER_DIR_002")" -ge 1 ]]; }
_poll_true_002=0
_poll_until "$DEADLINE_002" _is_alive_002 && _poll_true_002=1 || true

assert_true "new sweep is alive after stale-pid re-spawn" "$( [[ $_poll_true_002 -eq 1 ]] && echo 0 || echo 1 )"

# Verify the pid file now holds a NEW (different) pid.
NEW_PID_002="$(cat "$PID_FILE_002" 2>/dev/null | tr -dc '0-9' || echo 0)"
PIDS_DIFFER_002=1
[[ "$NEW_PID_002" != "$DEAD_PID" && -n "$NEW_PID_002" && "$NEW_PID_002" -gt 0 ]] && PIDS_DIFFER_002=0
assert_true "pid file updated to new pid (not the stale dead pid)" "$PIDS_DIFFER_002"

_kill_pid_file "$PID_FILE_002"
rm -rf "$TD_002"

# ---------------------------------------------------------------------------
# TEST-SP-003: spawn returns promptly AND sweep survives spawning shell exit
# ---------------------------------------------------------------------------
# Invariant: the spawn call does NOT block on the sweep's stdout fd; the sweep
#   continues running after the spawning process exits.
# Failure class: (a) Bash tool call hangs waiting for inherited stdout fd;
#   (b) sweep is SIGHUP'd when spawning shell dies.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-SP-003: spawn returns promptly + sweep survives spawning shell"

TD_003="$(_tmpdir)"
PLAN_DIR_003="$TD_003/plan"
MARKER_DIR_003="$TD_003/markers"
mkdir -p "$PLAN_DIR_003" "$MARKER_DIR_003"

FAKE_SWEEP_003="$(_write_fake_sweep "$TD_003" "$MARKER_DIR_003")"

# Measure how long the spawn call takes.
T_START_003="$(date +%s)"

WATCHDOG_SWEEP_SCRIPT="$FAKE_SWEEP_003" \
Z_HARNESS_PLAN_DIR="$PLAN_DIR_003" \
  bash "$SPAWN" --run "test-sp-003"

T_END_003="$(date +%s)"
ELAPSED_003=$(( T_END_003 - T_START_003 ))

# Spawn must return in under 10 seconds (typically < 1s).
PROMPT_003=1
[[ $ELAPSED_003 -le 10 ]] && PROMPT_003=0
assert_true "spawn call returns promptly (elapsed=${ELAPSED_003}s ≤ 10s)" "$PROMPT_003"

# Now verify the sweep is alive a few seconds after the spawn call returned
# (i.e., it survived after the spawning shell finished).
sleep 2

ALIVE_003="$(_count_alive "$MARKER_DIR_003")"
SURVIVES_003=1
[[ "$ALIVE_003" -ge 1 ]] && SURVIVES_003=0
assert_true "sweep is alive after spawning shell returned (alive=$ALIVE_003)" "$SURVIVES_003"

_kill_pid_file "$PLAN_DIR_003/active/test-sp-003.watchdog.pid"
rm -rf "$TD_003"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
