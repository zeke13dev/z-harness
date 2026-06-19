#!/usr/bin/env bash
# test_supervised_run.sh — Shell-level tests for scripts/supervised-run.sh
#
# Run with:
#   bash scripts/test_supervised_run.sh
#
# Coverage:
#   TEST-001  Fast command returns its real exit code and stdout intact
#   TEST-002  Missing "--" separator exits 2
#   TEST-003  Timeout path (sleep 30 --timeout 2) → exit 124 within grace
#   TEST-004  Telemetry fail-open: log-event.sh failure → cmd still runs
#   TEST-005  Stderr diagnostics do NOT pollute captured stdout
#   TEST-006  dispatch_id generated and present in BOTH dispatch_start + dispatch_end
#   TEST-007  Custom --dispatch-id propagated to both events
#   TEST-008  --timeout 0 resolves default from config (uses cargo=1800 default)
#   TEST-009  --run and --type are required (exits 2 without them)
#   TEST-010  watchdog_timeout event emitted on deadline expiry
#
# Hermetic: all tests write events under a temp Z_HARNESS_BASE_DIR + Z_HARNESS_SLUG
# so no real plan archive is touched.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
SUPERVISED_RUN="${SCRIPTS_DIR}/supervised-run.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/test_supervised_run_XXXXXX"
}

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label"
    echo "        expected: [$expected]"
    echo "        actual:   [$actual]"
    FAIL=$(( FAIL + 1 ))
  fi
}

assert_contains() {
  local label="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label"
    echo "        expected substring: [$needle]"
    echo "        in: [$haystack]"
    FAIL=$(( FAIL + 1 ))
  fi
}

assert_not_contains() {
  local label="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $label (found unwanted substring)"
    echo "        unwanted: [$needle]"
    echo "        in: [$haystack]"
    FAIL=$(( FAIL + 1 ))
  else
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  fi
}

assert_le() {
  local label="$1" max="$2" actual="$3"
  if [[ "$actual" -le "$max" ]]; then
    echo "  PASS: $label ($actual <= $max)"
    PASS=$(( PASS + 1 ))
  else
    echo "  FAIL: $label"
    echo "        expected <= $max but got $actual"
    FAIL=$(( FAIL + 1 ))
  fi
}

# Set up a hermetic base dir in the CURRENT shell (not a subshell).
# Sets HERMETIC_BASE, Z_HARNESS_BASE_DIR, Z_HARNESS_SLUG, Z_HARNESS_PLANS_DIR.
# IMPORTANT: call as "_hermetic_env slug run" — NOT via $() — so the export
# statements propagate to the current shell.
# Caller must rm -rf "$HERMETIC_BASE" in teardown.
_hermetic_env() {
  local slug="${1:-srun-test}"
  local run="${2:-testrun-$$}"
  HERMETIC_BASE="$(_tmpdir)"
  export Z_HARNESS_BASE_DIR="$HERMETIC_BASE"
  export Z_HARNESS_SLUG="$slug"
  export Z_HARNESS_PLANS_DIR="$HERMETIC_BASE/plans"
  mkdir -p "$HERMETIC_BASE/plans/$slug/archive/$run"
}

# Locate the events.jsonl for a run (uses current env slug/base).
_events_file() {
  local base="$1" slug="$2" run="$3"
  printf '%s/plans/%s/archive/%s/events.jsonl' "$base" "$slug" "$run"
}

# ---------------------------------------------------------------------------
# TEST-001: Fast command returns real exit code + stdout intact
# ---------------------------------------------------------------------------
echo ""
echo "TEST-001: fast command exits with real exit code and stdout intact"

RUN_001="test-srun-001-$$"
_hermetic_env "srun-test-001" "$RUN_001"
BASE_001="$HERMETIC_BASE"

# Use a temp file for stdout so we can capture both the output and the exit code.
# (Using $() would either mask the exit code via '|| true' or abort the script
# when set -e is active and the child exits non-zero.)
STDOUT_FILE_001="${TMPDIR:-/tmp}/sr_stdout_001_$$"
EXIT_001=0
bash "$SUPERVISED_RUN" \
  --run "$RUN_001" --type bash --timeout 5 \
  -- bash -c 'printf "hello world\n"; exit 7' \
  >"$STDOUT_FILE_001" 2>/dev/null || EXIT_001=$?
STDOUT_001="$(cat "$STDOUT_FILE_001")"
rm -f "$STDOUT_FILE_001"

assert_eq "stdout is 'hello world'" "hello world" "$STDOUT_001"
assert_eq "exit code passthrough 7" "7" "$EXIT_001"

rm -rf "$BASE_001"

# ---------------------------------------------------------------------------
# TEST-002: Missing "--" separator → exit 2
# ---------------------------------------------------------------------------
echo ""
echo "TEST-002: missing -- exits 2"

# No hermetic env needed; script exits before any event emission.
EXIT_002=0
bash "$SUPERVISED_RUN" --run noop --type bash --timeout 5 echo hello 2>/dev/null || EXIT_002=$?
assert_eq "missing -- exits 2" "2" "$EXIT_002"

# Also test with no arguments at all.
EXIT_002b=0
bash "$SUPERVISED_RUN" 2>/dev/null || EXIT_002b=$?
assert_eq "no-args exits 2" "2" "$EXIT_002b"

# ---------------------------------------------------------------------------
# TEST-003: Timeout path → exit 124 within reasonable time
# ---------------------------------------------------------------------------
echo ""
echo "TEST-003: timeout path kills sleep + returns 124"

RUN_003="test-srun-003-$$"
_hermetic_env "srun-test-003" "$RUN_003"
BASE_003="$HERMETIC_BASE"

TSTART_003=$(date +%s)
EXIT_003=0
bash "$SUPERVISED_RUN" \
  --run "$RUN_003" --type bash --timeout 2 --grace 1 \
  -- sleep 30 \
  2>/dev/null || EXIT_003=$?
TEND_003=$(date +%s)
ELAPSED_003=$(( TEND_003 - TSTART_003 ))

assert_eq "timeout path exits 124" "124" "$EXIT_003"
# Should finish within 10 seconds (2s timeout + 1s grace + overhead)
assert_le "timeout path finishes within 10s" "10" "$ELAPSED_003"

rm -rf "$BASE_003"

# ---------------------------------------------------------------------------
# TEST-004: Telemetry fail-open — log-event.sh failure → cmd still runs
# ---------------------------------------------------------------------------
echo ""
echo "TEST-004: telemetry fail-open"

RUN_004="test-srun-004-$$"
FAKE_BASE_004="$(_tmpdir)"
export Z_HARNESS_BASE_DIR="$FAKE_BASE_004"
export Z_HARNESS_SLUG="srun-test-004"
export Z_HARNESS_PLANS_DIR="$FAKE_BASE_004/plans"
mkdir -p "$FAKE_BASE_004/plans/srun-test-004/archive/$RUN_004"

# Build a hermetic copy of supervised-run.sh that points to a broken log-event.sh.
FAKE_SCRIPTS_004="$(_tmpdir)"
cp "$SUPERVISED_RUN" "$FAKE_SCRIPTS_004/supervised-run.sh"
cp "${SCRIPTS_DIR}/check-timeout.sh" "$FAKE_SCRIPTS_004/check-timeout.sh"
cp "${SCRIPTS_DIR}/plan-path.sh" "$FAKE_SCRIPTS_004/plan-path.sh"
# config.py must be accessible (for timeout resolution)
cp "${SCRIPTS_DIR}/config.py" "$FAKE_SCRIPTS_004/config.py"

# Create a log-event.sh that always fails
printf '#!/usr/bin/env bash\nexit 1\n' > "$FAKE_SCRIPTS_004/log-event.sh"
chmod +x "$FAKE_SCRIPTS_004/log-event.sh"
chmod +x "$FAKE_SCRIPTS_004/supervised-run.sh"

STDOUT_FILE_004="${TMPDIR:-/tmp}/sr_stdout_004_$$"
STDERR_FILE_004="${TMPDIR:-/tmp}/sr_stderr_004_$$"
EXIT_004=0
bash "$FAKE_SCRIPTS_004/supervised-run.sh" \
  --run "$RUN_004" --type bash --timeout 5 \
  -- echo 'cmd-ran-despite-telemetry-failure' \
  >"$STDOUT_FILE_004" 2>"$STDERR_FILE_004" || EXIT_004=$?

STDOUT_004="$(cat "$STDOUT_FILE_004")"
STDERR_004="$(cat "$STDERR_FILE_004")"
rm -f "$STDOUT_FILE_004" "$STDERR_FILE_004"

assert_eq "cmd stdout present despite telemetry failure" \
  "cmd-ran-despite-telemetry-failure" "$STDOUT_004"
assert_eq "cmd exit 0 despite telemetry failure" "0" "$EXIT_004"
assert_contains "telemetry warning on stderr" "[supervised-run] WARNING" "$STDERR_004"

rm -rf "$FAKE_BASE_004" "$FAKE_SCRIPTS_004"

# ---------------------------------------------------------------------------
# TEST-005: Wrapper stderr diagnostics do NOT pollute captured stdout
# ---------------------------------------------------------------------------
echo ""
echo "TEST-005: stderr diagnostics don't pollute captured stdout"

RUN_005="test-srun-005-$$"
_hermetic_env "srun-test-005" "$RUN_005"
BASE_005="$HERMETIC_BASE"

# Capture stdout to a file; redirect stderr to /dev/null.
STDOUT_FILE_005="${TMPDIR:-/tmp}/sr_stdout_005_$$"
bash "$SUPERVISED_RUN" \
  --run "$RUN_005" --type bash --timeout 5 \
  -- printf 'ONLY_ON_STDOUT' \
  >"$STDOUT_FILE_005" 2>/dev/null
STDOUT_005="$(cat "$STDOUT_FILE_005")"
rm -f "$STDOUT_FILE_005"

assert_eq "stdout is exactly the command output" "ONLY_ON_STDOUT" "$STDOUT_005"
assert_not_contains "no supervised-run prefix in stdout" "[supervised-run]" "$STDOUT_005"

rm -rf "$BASE_005"

# ---------------------------------------------------------------------------
# TEST-006: dispatch_id generated and present in BOTH dispatch_start + dispatch_end
# ---------------------------------------------------------------------------
echo ""
echo "TEST-006: dispatch_id in both dispatch_start and dispatch_end"

RUN_006="test-srun-006-$$"
_hermetic_env "srun-test-006" "$RUN_006"
BASE_006="$HERMETIC_BASE"

bash "$SUPERVISED_RUN" \
  --run "$RUN_006" --type bash --timeout 5 \
  -- echo hello \
  2>/dev/null

EVENTS_006_FILE="$(_events_file "$BASE_006" "srun-test-006" "$RUN_006")"
EVENTS_006="$(cat "$EVENTS_006_FILE")"

# Extract dispatch_id from dispatch_start event
DID_START_006="$(echo "$EVENTS_006" | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e.get("kind") == "dispatch_start":
        print(e.get("dispatch_id", ""))
        break
')"

# Extract dispatch_id from dispatch_end event
DID_END_006="$(echo "$EVENTS_006" | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e.get("kind") == "dispatch_end":
        print(e.get("dispatch_id", ""))
        break
')"

# dispatch_id must be non-empty
if [[ -n "$DID_START_006" ]]; then
  echo "  PASS: dispatch_id is non-empty in start"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: dispatch_id is empty in dispatch_start"
  FAIL=$(( FAIL + 1 ))
fi
assert_eq "dispatch_id matches between start and end" "$DID_START_006" "$DID_END_006"

# dispatch_id format: <run>-<type>-<epoch_ms>-<rand4>
case "$DID_START_006" in
  ${RUN_006}-bash-*)
    echo "  PASS: dispatch_id format matches <run>-<type>-<epoch_ms>-<rand4>"
    PASS=$(( PASS + 1 ))
    ;;
  *)
    echo "  FAIL: dispatch_id format unexpected: [$DID_START_006]"
    FAIL=$(( FAIL + 1 ))
    ;;
esac

rm -rf "$BASE_006"

# ---------------------------------------------------------------------------
# TEST-007: Custom --dispatch-id propagated to both events
# ---------------------------------------------------------------------------
echo ""
echo "TEST-007: custom --dispatch-id in both events"

RUN_007="test-srun-007-$$"
_hermetic_env "srun-test-007" "$RUN_007"
BASE_007="$HERMETIC_BASE"
CUSTOM_DID="my-custom-dispatch-id-007"

bash "$SUPERVISED_RUN" \
  --run "$RUN_007" --type bash --timeout 5 \
  --dispatch-id "$CUSTOM_DID" \
  -- echo hello \
  2>/dev/null

EVENTS_007="$(cat "$(_events_file "$BASE_007" "srun-test-007" "$RUN_007")")"

DID_START_007="$(echo "$EVENTS_007" | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e.get("kind") == "dispatch_start":
        print(e.get("dispatch_id", ""))
        break
')"

DID_END_007="$(echo "$EVENTS_007" | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e.get("kind") == "dispatch_end":
        print(e.get("dispatch_id", ""))
        break
')"

assert_eq "custom dispatch_id in dispatch_start" "$CUSTOM_DID" "$DID_START_007"
assert_eq "custom dispatch_id in dispatch_end" "$CUSTOM_DID" "$DID_END_007"

rm -rf "$BASE_007"

# ---------------------------------------------------------------------------
# TEST-008: --timeout 0 resolves default from config
# ---------------------------------------------------------------------------
echo ""
echo "TEST-008: --timeout 0 resolves default from watchdog.timeout_secs.<type>"

RUN_008="test-srun-008-$$"
_hermetic_env "srun-test-008" "$RUN_008"
BASE_008="$HERMETIC_BASE"

bash "$SUPERVISED_RUN" \
  --run "$RUN_008" --type cargo --timeout 0 \
  -- echo hello \
  2>/dev/null

EVENTS_008="$(cat "$(_events_file "$BASE_008" "srun-test-008" "$RUN_008")")"

TIMEOUT_S_008="$(echo "$EVENTS_008" | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e.get("kind") == "dispatch_start":
        print(e.get("timeout_s", ""))
        break
')"

# Config default for cargo is 1800; fallback is 600 if config unreachable.
case "$TIMEOUT_S_008" in
  600|1800)
    echo "  PASS: timeout resolved to $TIMEOUT_S_008 from config (600 or 1800 both valid)"
    PASS=$(( PASS + 1 ))
    ;;
  *)
    echo "  FAIL: unexpected timeout_s=$TIMEOUT_S_008 (expected 600 or 1800)"
    FAIL=$(( FAIL + 1 ))
    ;;
esac

rm -rf "$BASE_008"

# ---------------------------------------------------------------------------
# TEST-009: --run and --type are required
# ---------------------------------------------------------------------------
echo ""
echo "TEST-009: missing required args exits 2"

EXIT_009a=0
bash "$SUPERVISED_RUN" --type bash --timeout 5 -- echo hello 2>/dev/null || EXIT_009a=$?
assert_eq "missing --run exits 2" "2" "$EXIT_009a"

EXIT_009b=0
bash "$SUPERVISED_RUN" --run testr --timeout 5 -- echo hello 2>/dev/null || EXIT_009b=$?
assert_eq "missing --type exits 2" "2" "$EXIT_009b"

# ---------------------------------------------------------------------------
# TEST-010: watchdog_timeout event emitted when deadline fires
# ---------------------------------------------------------------------------
echo ""
echo "TEST-010: watchdog_timeout event emitted on deadline expiry"

RUN_010="test-srun-010-$$"
_hermetic_env "srun-test-010" "$RUN_010"
BASE_010="$HERMETIC_BASE"

EXIT_010=0
bash "$SUPERVISED_RUN" \
  --run "$RUN_010" --type bash --timeout 2 --grace 1 \
  -- sleep 30 \
  2>/dev/null || EXIT_010=$?

assert_eq "timeout exit code 124" "124" "$EXIT_010"

EVENTS_010="$(cat "$(_events_file "$BASE_010" "srun-test-010" "$RUN_010")")"

# All three event types must be present
assert_contains "dispatch_start emitted" '"kind":"dispatch_start"' "$EVENTS_010"
assert_contains "dispatch_end emitted" '"kind":"dispatch_end"' "$EVENTS_010"
assert_contains "watchdog_timeout emitted" '"kind":"watchdog_timeout"' "$EVENTS_010"
assert_contains "watchdog_timeout has killed:true" '"killed":true' "$EVENTS_010"

# dispatch_id must be consistent between dispatch_start and dispatch_end
DID_010_START="$(echo "$EVENTS_010" | python3 -c '
import json, sys
for l in sys.stdin:
    e = json.loads(l)
    if e.get("kind") == "dispatch_start":
        print(e.get("dispatch_id", ""))
        break
')"
DID_010_END="$(echo "$EVENTS_010" | python3 -c '
import json, sys
for l in sys.stdin:
    e = json.loads(l)
    if e.get("kind") == "dispatch_end":
        print(e.get("dispatch_id", ""))
        break
')"
assert_eq "dispatch_id consistent across start+end" "$DID_010_START" "$DID_010_END"

# exit_code in dispatch_end must be 124
EXIT_CODE_010="$(echo "$EVENTS_010" | python3 -c '
import json, sys
for l in sys.stdin:
    e = json.loads(l)
    if e.get("kind") == "dispatch_end":
        print(e.get("exit_code", ""))
        break
')"
assert_eq "dispatch_end records exit_code 124" "124" "$EXIT_CODE_010"

rm -rf "$BASE_010"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
