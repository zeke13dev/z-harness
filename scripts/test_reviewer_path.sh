#!/usr/bin/env bash
# test_reviewer_path.sh — Reviewer-path integration tests for T010.
#
# Validates that the four dispatch modes described in agents/reviewer.md work
# correctly when routed through supervised-run.sh instead of the old
# $TIMEOUT_CMD wrapper.  Uses only a mock "reviewer CLI" (printf/echo) so no
# real provider is needed.
#
# Coverage:
#   TEST-001  stdout-capture / args mode: review text captured byte-identically,
#             no supervised-run.sh diagnostics on stdout.
#   TEST-002  stdin-pipe mode: review text piped through supervised-run.sh
#             arrives byte-identically, no stdout pollution.
#   TEST-003  codex -o outfile mode: mock command writes review to $OUTFILE via
#             -o flag; supervised-run.sh passes -o as cmd arg, stdout clean.
#   TEST-004  outfile-fallback mode: when codex outfile is empty after the first
#             call, the fallback re-run via stdout still delivers review text
#             byte-identically.
#   TEST-005  no double-wrap: calling supervised-run.sh nested inside another
#             supervised-run.sh does not corrupt stdout (re-entrancy).
#
# Run with:
#   bash scripts/test_reviewer_path.sh
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
  mktemp -d "${TMPDIR:-/tmp}/test_reviewer_path_XXXXXX"
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
  if printf '%s' "$haystack" | grep -qF "$needle"; then
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
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $label (found unwanted substring)"
    echo "        unwanted: [$needle]"
    echo "        in: [$haystack]"
    FAIL=$(( FAIL + 1 ))
  else
    echo "  PASS: $label"
    PASS=$(( PASS + 1 ))
  fi
}

# Set up a hermetic base dir in the CURRENT shell (not a subshell).
# Sets HERMETIC_BASE, Z_HARNESS_BASE_DIR, Z_HARNESS_SLUG, Z_HARNESS_PLANS_DIR.
# IMPORTANT: call as "_hermetic_env slug run" — NOT via $() — so the export
# statements propagate to the current shell.
# Caller must rm -rf "$HERMETIC_BASE" in teardown.
_hermetic_env() {
  local slug="${1:-rp-test}"
  local run="${2:-testrun-$$}"
  HERMETIC_BASE="$(_tmpdir)"
  export Z_HARNESS_BASE_DIR="$HERMETIC_BASE"
  export Z_HARNESS_SLUG="$slug"
  export Z_HARNESS_PLANS_DIR="$HERMETIC_BASE/plans"
  mkdir -p "$HERMETIC_BASE/plans/$slug/archive/$run"
}

# ---------------------------------------------------------------------------
# TEST-001: stdout-capture / args mode
#
# Exercises the non-stdin dispatch path from reviewer.md:
#   RESPONSE="$(bash supervised-run.sh --run "$RUN" --type reviewer \
#     --timeout "$TIMEOUT" -- $COMMAND $ARGS "$PROMPT")"
#
# The mock command echoes a known review string to stdout.
# Invariant: captured RESPONSE == exactly that string; no [supervised-run] prefix.
# Failure class: any supervised-run.sh diagnostic leaked to stdout would corrupt
# the reviewer's captured $RESPONSE — same bug the $TIMEOUT_CMD migration fixed.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-001: stdout-capture / args mode — review text byte-identical, no stdout pollution"

RUN_001="test-rp-001-$$"
_hermetic_env "rp-test-001" "$RUN_001"
BASE_001="$HERMETIC_BASE"

EXPECTED_REVIEW_001="No blockers or majors found."

# Simulate: COMMAND=printf, ARGS="%s", PROMPT="$EXPECTED_REVIEW_001"
STDOUT_FILE_001="${TMPDIR:-/tmp}/rp_stdout_001_$$"
RESPONSE_001=""
bash "$SUPERVISED_RUN" \
  --run "$RUN_001" --type reviewer --timeout 10 \
  -- printf '%s' "$EXPECTED_REVIEW_001" \
  >"$STDOUT_FILE_001" 2>/dev/null
RESPONSE_001="$(cat "$STDOUT_FILE_001")"
rm -f "$STDOUT_FILE_001"

assert_eq "args mode: response byte-identical" "$EXPECTED_REVIEW_001" "$RESPONSE_001"
assert_not_contains "args mode: no [supervised-run] in stdout" "[supervised-run]" "$RESPONSE_001"

rm -rf "$BASE_001"

# ---------------------------------------------------------------------------
# TEST-002: stdin-pipe mode
#
# Exercises the stdin-pipe dispatch path from reviewer.md:
#   RESPONSE="$(printf '%s' "$PROMPT" | bash supervised-run.sh --run "$RUN" \
#     --type reviewer --timeout "$TIMEOUT" -- $COMMAND $ARGS)"
#
# The mock command reads stdin and echoes it back.
# Invariant: stdin passes through supervised-run.sh unchanged; captured RESPONSE
# is byte-identical to what was piped in; no diagnostics on stdout.
# Failure class: supervised-run.sh eating or mangling stdin would produce an
# empty/wrong RESPONSE in the reviewer's $(...) capture.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-002: stdin-pipe mode — stdin passes through, stdout clean"

RUN_002="test-rp-002-$$"
_hermetic_env "rp-test-002" "$RUN_002"
BASE_002="$HERMETIC_BASE"

EXPECTED_REVIEW_002="FAIL
### Blockers
- **BLOCKER**: something wrong"

STDOUT_FILE_002="${TMPDIR:-/tmp}/rp_stdout_002_$$"
# Pipe the review prompt through; the mock cat command echoes stdin as stdout.
printf '%s' "$EXPECTED_REVIEW_002" \
  | bash "$SUPERVISED_RUN" \
      --run "$RUN_002" --type reviewer --timeout 10 \
      -- cat \
  >"$STDOUT_FILE_002" 2>/dev/null
RESPONSE_002="$(cat "$STDOUT_FILE_002")"
rm -f "$STDOUT_FILE_002"

assert_eq "stdin-pipe mode: response byte-identical" "$EXPECTED_REVIEW_002" "$RESPONSE_002"
assert_not_contains "stdin-pipe mode: no [supervised-run] in stdout" "[supervised-run]" "$RESPONSE_002"

rm -rf "$BASE_002"

# ---------------------------------------------------------------------------
# TEST-003: codex -o outfile mode
#
# Exercises the file-based capture path from reviewer.md (when CODEX_SUPPORTS_OUTFILE=1).
# The mock command simulates codex behavior: it writes its review to the file
# specified via '-o <outfile>' and exits 0.
#
# reviewer.md calls:
#   bash supervised-run.sh ... -- $COMMAND $ARGS -o "$OUTFILE" "$PROMPT"
# Then reads RESPONSE from $OUTFILE.
#
# Invariant: supervised-run.sh passes -o and the outfile path as args to the
# child command; the child writes to the file; stdout of supervised-run.sh stays
# clean (codex discards its own transcript to stdout in production; we verify
# the wrapper does not add stdout clutter of its own).
# Failure class: if supervised-run.sh stripped or reordered args, the '-o outfile'
# would not reach the mock command and the file would not be written.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-003: codex -o outfile mode — -o arg passes through, file written, stdout clean"

RUN_003="test-rp-003-$$"
_hermetic_env "rp-test-003" "$RUN_003"
BASE_003="$HERMETIC_BASE"

ARCHIVE_DIR_003="${HERMETIC_BASE}/plans/rp-test-003/archive/${RUN_003}/tasks/T-REV-001"
mkdir -p "$ARCHIVE_DIR_003"
OUTFILE_003="${ARCHIVE_DIR_003}/review-cycle1.md"
EXPECTED_REVIEW_003="PASS
No blockers or majors found."

# Mock command: writes $3 to the file given by -o $2, ignoring $1 (the prompt).
# Invocation from reviewer.md: $COMMAND $ARGS -o "$OUTFILE" "$PROMPT"
# Here: bash mock_codex.sh <ignored_args> -o <outfile> <prompt>
MOCK_CODEX_003="${TMPDIR:-/tmp}/mock_codex_003_$$.sh"
cat >"$MOCK_CODEX_003" <<'MOCKEOF'
#!/usr/bin/env bash
# Minimal codex mock: find '-o <file>' in args and write review text to it.
OUTFILE=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-o" && -n "${2:-}" ]]; then
    OUTFILE="$2"
    shift 2
  else
    shift
  fi
done
if [[ -n "$OUTFILE" ]]; then
  printf '%s' "$REVIEW_TEXT" >"$OUTFILE"
fi
# Stdout intentionally empty (codex discards transcript).
exit 0
MOCKEOF
chmod +x "$MOCK_CODEX_003"

STDOUT_FILE_003="${TMPDIR:-/tmp}/rp_stdout_003_$$"
CODEX_EXIT_003=0
REVIEW_TEXT="$EXPECTED_REVIEW_003" bash "$SUPERVISED_RUN" \
  --run "$RUN_003" --type reviewer --timeout 10 \
  -- bash "$MOCK_CODEX_003" -o "$OUTFILE_003" "the-review-prompt" \
  >"$STDOUT_FILE_003" 2>/dev/null || CODEX_EXIT_003=$?
STDOUT_003="$(cat "$STDOUT_FILE_003")"
rm -f "$STDOUT_FILE_003" "$MOCK_CODEX_003"

# Validate: exit 0, outfile written, stdout clean
assert_eq "codex -o mode: exit 0" "0" "$CODEX_EXIT_003"
if [[ -s "$OUTFILE_003" ]]; then
  echo "  PASS: codex -o mode: outfile written and non-empty"
  PASS=$(( PASS + 1 ))
else
  echo "  FAIL: codex -o mode: outfile missing or empty"
  FAIL=$(( FAIL + 1 ))
fi
FILE_CONTENT_003="$(cat "$OUTFILE_003" 2>/dev/null || true)"
assert_eq "codex -o mode: outfile content byte-identical" "$EXPECTED_REVIEW_003" "$FILE_CONTENT_003"
assert_not_contains "codex -o mode: no [supervised-run] on stdout" "[supervised-run]" "$STDOUT_003"

rm -rf "$BASE_003"

# ---------------------------------------------------------------------------
# TEST-004: outfile-fallback mode
#
# Exercises the review_capture_fallback path from reviewer.md:
# When the first codex -o call exits non-zero OR leaves an empty outfile,
# the reviewer falls back to a re-run WITHOUT -o to capture via stdout.
#
# This test simulates the fallback re-run:
#   RESPONSE="$(bash supervised-run.sh ... -- $COMMAND $ARGS)"
# where $COMMAND/$ARGS (without -o) now echo the review to stdout.
#
# Invariant: supervised-run.sh does not interfere with the fallback stdout
# capture; the RESPONSE equals the review text byte-identically.
# Failure class: if the fallback re-run introduced stdout diagnostics, the
# captured RESPONSE would contain garbage and parse as UNKNOWN verdict.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-004: outfile-fallback mode — fallback re-run captures stdout byte-identically"

RUN_004="test-rp-004-$$"
_hermetic_env "rp-test-004" "$RUN_004"
BASE_004="$HERMETIC_BASE"

EXPECTED_REVIEW_004="PASS
No blockers or majors found.
(outfile-fallback path)"

# Simulate fallback: a command that emits review to stdout (no -o flag).
STDOUT_FILE_004="${TMPDIR:-/tmp}/rp_stdout_004_$$"
bash "$SUPERVISED_RUN" \
  --run "$RUN_004" --type reviewer --timeout 10 \
  -- printf '%s' "$EXPECTED_REVIEW_004" \
  >"$STDOUT_FILE_004" 2>/dev/null
RESPONSE_004="$(cat "$STDOUT_FILE_004")"
rm -f "$STDOUT_FILE_004"

assert_eq "outfile-fallback mode: response byte-identical" "$EXPECTED_REVIEW_004" "$RESPONSE_004"
assert_not_contains "outfile-fallback mode: no [supervised-run] in stdout" "[supervised-run]" "$RESPONSE_004"

rm -rf "$BASE_004"

# ---------------------------------------------------------------------------
# TEST-005: no double-wrap (re-entrancy)
#
# Verifies that nesting supervised-run.sh (which would happen if reviewer.md
# still had the old $TIMEOUT_CMD wrap AND the new supervised-run.sh call) does
# not corrupt captured stdout or emit duplicate diagnostics on stdout.
#
# reviewer.md must NOT double-wrap; this test verifies that even if nesting
# occurs (regression guard), stdout is still byte-for-byte from the innermost
# child and no [supervised-run] prefixes leak.
#
# Invariant: stdout from a nested supervised-run.sh invocation is still exactly
# the child's output, not any wrapper diagnostic.
# Failure class: double-wrap stdout pollution was the exact bug the $TIMEOUT_CMD
# migration was designed to prevent; this is the regression guard.
# ---------------------------------------------------------------------------
echo ""
echo "TEST-005: no double-wrap — nested supervised-run.sh does not pollute stdout"

RUN_005_OUTER="test-rp-005-outer-$$"
RUN_005_INNER="test-rp-005-inner-$$"
_hermetic_env "rp-test-005" "$RUN_005_OUTER"
BASE_005="$HERMETIC_BASE"
# Create the inner run archive too
mkdir -p "${HERMETIC_BASE}/plans/rp-test-005/archive/${RUN_005_INNER}"

EXPECTED_REVIEW_005="PASS
No blockers or majors found."

STDOUT_FILE_005="${TMPDIR:-/tmp}/rp_stdout_005_$$"
# Outer supervised-run.sh wrapping an inner supervised-run.sh (simulates double-wrap)
bash "$SUPERVISED_RUN" \
  --run "$RUN_005_OUTER" --type reviewer --timeout 10 \
  -- bash "$SUPERVISED_RUN" \
       --run "$RUN_005_INNER" --type reviewer --timeout 10 \
       -- printf '%s' "$EXPECTED_REVIEW_005" \
  >"$STDOUT_FILE_005" 2>/dev/null
RESPONSE_005="$(cat "$STDOUT_FILE_005")"
rm -f "$STDOUT_FILE_005"

assert_eq "double-wrap: stdout byte-identical to child output" "$EXPECTED_REVIEW_005" "$RESPONSE_005"
assert_not_contains "double-wrap: no [supervised-run] prefix on stdout" "[supervised-run]" "$RESPONSE_005"

rm -rf "$BASE_005"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
