#!/usr/bin/env bash
# test_log_phase.sh — Regression tests for scripts/log-phase.sh
#
# Run with:
#   bash scripts/test_log_phase.sh
#
# Each test uses a hermetic temp directory (TMPDIR-based) to avoid polluting
# the z-harness archive.  Tests exit non-zero on any assertion failure.
#
# Hermetic isolation: set Z_HARNESS_PLANS_DIR to a temp dir and Z_HARNESS_SLUG
# so log-event.sh writes to <tmpdir>/<slug>/archive/<run>/events.jsonl instead
# of the real z-harness/archive/.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_PHASE="$SCRIPTS_DIR/log-phase.sh"

PASS=0
FAIL=0
TEST_SLUG="test-log-phase-regression"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/test_log_phase_XXXXXX"
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        expected: $expected"
    echo "        actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        expected substring: $needle"
    echo "        in: $haystack"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $label (found unwanted substring)"
    echo "        unwanted: $needle"
    echo "        in: $haystack"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  fi
}

# Run log-phase.sh with hermetic env.
# Z_HARNESS_PLANS_DIR + Z_HARNESS_SLUG route events to the temp dir.
run_phase() {
  local plans_dir="$1" run_id="$2"
  shift 2
  Z_HARNESS_PLANS_DIR="$plans_dir" \
  Z_HARNESS_SLUG="$TEST_SLUG" \
    bash "$LOG_PHASE" "$@"
}

# Find the events.jsonl file for a given plans_dir + run_id.
events_file() {
  local plans_dir="$1" run_id="$2"
  echo "$plans_dir/$TEST_SLUG/archive/$run_id/events.jsonl"
}

# ---------------------------------------------------------------------------
# TEST-001: wall_ms overflow guard emits telemetry_anomaly and exits 0
# ---------------------------------------------------------------------------
#
# Invariant: When T0 is in seconds (not ms) and T1 is in ms, the diff is
# Unix-epoch-scale (> 604_800_000 ms = 7 days) and MUST NOT be recorded as
# wall_ms in a *_end event.  Instead, a telemetry_anomaly event must be written
# and the script must exit 0.
#
# Failure class: bogus wall_ms corrupts /z-stats aggregate analysis
# ---------------------------------------------------------------------------

echo ""
echo "TEST-001: wall_ms overflow guard"

PLANS_DIR_001="$(_tmpdir)"
RUN_ID="test-run-overflow-001"

# Build a token where T0 is seconds-scale (1_700_000_000 s) and the current
# time is milliseconds-scale.  The difference will be >> 604_800_000 ms,
# simulating the macOS BSD `date +%s%3N` fallback returning seconds instead.
T0_SECONDS=1700000000   # seconds-scale value (Unix timestamp in seconds)
OVERFLOW_TOKEN="${RUN_ID}|implement|${T0_SECONDS}"

# Invoke end mode with the overflow token; capture exit code.
EXIT_CODE=0
run_phase "$PLANS_DIR_001" "$RUN_ID" \
  end "$OVERFLOW_TOKEN" '{"status":"ok"}' || EXIT_CODE=$?

assert_eq "exit code is 0 on overflow" "0" "$EXIT_CODE"

EVENTS_FILE_001="$(events_file "$PLANS_DIR_001" "$RUN_ID")"
if [[ ! -f "$EVENTS_FILE_001" ]]; then
  echo "  FAIL: no events.jsonl found at $EVENTS_FILE_001"
  FAIL=$((FAIL + 1))
else
  EVENTS="$(cat "$EVENTS_FILE_001")"

  # Must contain telemetry_anomaly event kind
  assert_contains \
    "events.jsonl contains telemetry_anomaly kind" \
    '"kind":"telemetry_anomaly"' \
    "$EVENTS"

  # Must contain reason: wall_ms_overflow
  assert_contains \
    "telemetry_anomaly has reason wall_ms_overflow" \
    '"reason":"wall_ms_overflow"' \
    "$EVENTS"

  # Must contain the raw t_start value
  assert_contains \
    "telemetry_anomaly has t_start field" \
    '"t_start":1700000000' \
    "$EVENTS"

  # Must NOT contain an implement_end event (the bogus wall_ms event)
  assert_not_contains \
    "events.jsonl does NOT contain implement_end with bogus wall_ms" \
    '"kind":"implement_end"' \
    "$EVENTS"
fi

rm -rf "$PLANS_DIR_001"

# ---------------------------------------------------------------------------
# TEST-002: normal (non-overflow) end mode still writes *_end event correctly
# ---------------------------------------------------------------------------
#
# Regression guard: the overflow fix must not break the normal happy path.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-002: normal end mode still works after overflow guard"

PLANS_DIR_002="$(_tmpdir)"
RUN_ID_2="test-run-normal-002"

# Start a phase normally (T0 will be current ms).
TOKEN_NORMAL="$(run_phase "$PLANS_DIR_002" "$RUN_ID_2" \
  start "$RUN_ID_2" "mytest" '{"id":"TEST-002"}' 2>/dev/null)"

EXIT_CODE_NORMAL=0
run_phase "$PLANS_DIR_002" "$RUN_ID_2" \
  end "$TOKEN_NORMAL" '{"status":"ok"}' || EXIT_CODE_NORMAL=$?

assert_eq "normal end exits 0" "0" "$EXIT_CODE_NORMAL"

EVENTS_FILE_002="$(events_file "$PLANS_DIR_002" "$RUN_ID_2")"
if [[ ! -f "$EVENTS_FILE_002" ]]; then
  echo "  FAIL: no events.jsonl found at $EVENTS_FILE_002"
  FAIL=$((FAIL + 1))
else
  EVENTS_2="$(cat "$EVENTS_FILE_002")"

  # Must contain mytest_end
  assert_contains \
    "normal end produces mytest_end event" \
    '"kind":"mytest_end"' \
    "$EVENTS_2"

  # Must contain wall_ms field
  assert_contains \
    "normal end event has wall_ms field" \
    '"wall_ms":' \
    "$EVENTS_2"

  # Must NOT contain telemetry_anomaly
  assert_not_contains \
    "normal end does NOT produce telemetry_anomaly" \
    '"kind":"telemetry_anomaly"' \
    "$EVENTS_2"
fi

rm -rf "$PLANS_DIR_002"

# ---------------------------------------------------------------------------
# TEST-003: negative wall_ms (clock skew) emits telemetry_anomaly with
#           reason wall_ms_negative and exits 0
# ---------------------------------------------------------------------------
#
# Invariant: If T1 < T0 (clock skew / NTP jump), the computed wall_ms is
# negative and MUST NOT be recorded as wall_ms in a *_end event.  A
# telemetry_anomaly event with reason "wall_ms_negative" must be written.
#
# Failure class: negative wall_ms silently corrupts aggregate stats
# ---------------------------------------------------------------------------

echo ""
echo "TEST-003: negative wall_ms (clock skew) guard"

PLANS_DIR_003="$(_tmpdir)"
RUN_ID_3="test-run-negative-003"

# Build a token where T0 is in the future (year 2099 in ms) relative to the
# current clock, making WALL_MS = T1 - T0 negative.
T0_FUTURE=4102444800000   # 2100-01-01 00:00:00 UTC in ms — always > now
NEGATIVE_TOKEN="${RUN_ID_3}|implement|${T0_FUTURE}"

EXIT_CODE_3=0
run_phase "$PLANS_DIR_003" "$RUN_ID_3" \
  end "$NEGATIVE_TOKEN" '{"status":"ok"}' || EXIT_CODE_3=$?

assert_eq "exit code is 0 on negative wall_ms" "0" "$EXIT_CODE_3"

EVENTS_FILE_003="$(events_file "$PLANS_DIR_003" "$RUN_ID_3")"
if [[ ! -f "$EVENTS_FILE_003" ]]; then
  echo "  FAIL: no events.jsonl found at $EVENTS_FILE_003"
  FAIL=$((FAIL + 1))
else
  EVENTS_3="$(cat "$EVENTS_FILE_003")"

  # Must contain telemetry_anomaly event kind
  assert_contains \
    "events.jsonl contains telemetry_anomaly kind" \
    '"kind":"telemetry_anomaly"' \
    "$EVENTS_3"

  # Must contain reason: wall_ms_negative
  assert_contains \
    "telemetry_anomaly has reason wall_ms_negative" \
    '"reason":"wall_ms_negative"' \
    "$EVENTS_3"

  # Must contain the raw t_start value
  assert_contains \
    "telemetry_anomaly has t_start field" \
    '"t_start":4102444800000' \
    "$EVENTS_3"

  # Must NOT contain an implement_end event (the bogus wall_ms event)
  assert_not_contains \
    "events.jsonl does NOT contain implement_end with bogus wall_ms" \
    '"kind":"implement_end"' \
    "$EVENTS_3"
fi

rm -rf "$PLANS_DIR_003"

# ---------------------------------------------------------------------------
# TEST-004: 26-hour wall_ms (~93_600_000 ms) does NOT trigger anomaly
# ---------------------------------------------------------------------------
#
# Invariant: A session lasting exactly 26 hours is a valid long run and MUST
# produce a normal *_end event with wall_ms recorded, NOT a telemetry_anomaly.
# This is a regression guard confirming the raised threshold (604_800_000 ms)
# eliminates false positives for multi-hour sessions.
#
# Failure class: legitimate long runs silently dropped from /z-stats aggregates
# ---------------------------------------------------------------------------

echo ""
echo "TEST-004: 26-hour wall_ms does NOT trigger anomaly"

PLANS_DIR_004="$(_tmpdir)"
RUN_ID_4="test-run-26h-004"

# 26 hours = 93_600_000 ms.  Simulate a T0 that is 26 hours before now.
NOW_MS="$(python3 -c 'import time; print(int(time.time()*1000))')"
T0_26H=$(( NOW_MS - 93600000 ))
TOKEN_26H="${RUN_ID_4}|longrun|${T0_26H}"

EXIT_CODE_4=0
run_phase "$PLANS_DIR_004" "$RUN_ID_4" \
  end "$TOKEN_26H" '{"status":"ok"}' || EXIT_CODE_4=$?

assert_eq "26h end exits 0" "0" "$EXIT_CODE_4"

EVENTS_FILE_004="$(events_file "$PLANS_DIR_004" "$RUN_ID_4")"
if [[ ! -f "$EVENTS_FILE_004" ]]; then
  echo "  FAIL: no events.jsonl found at $EVENTS_FILE_004"
  FAIL=$((FAIL + 1))
else
  EVENTS_4="$(cat "$EVENTS_FILE_004")"

  # Must contain the normal longrun_end event
  assert_contains \
    "26h end produces longrun_end event" \
    '"kind":"longrun_end"' \
    "$EVENTS_4"

  # Must contain wall_ms field
  assert_contains \
    "26h end event has wall_ms field" \
    '"wall_ms":' \
    "$EVENTS_4"

  # Must NOT contain telemetry_anomaly (false-positive check)
  assert_not_contains \
    "26h end does NOT produce telemetry_anomaly" \
    '"kind":"telemetry_anomaly"' \
    "$EVENTS_4"
fi

rm -rf "$PLANS_DIR_004"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
