#!/usr/bin/env bash
# test_log_subagent.sh — T005 focused tests
#
# Verifies that scripts/log-subagent.sh emits correct subagent_call events:
#   T005-A: emitted event validates and carries required fields; chars kept separate
#   T005-B: omitting provider tokens is valid (fields absent, not null/0)
#   T005-C: forced failure (bad args) still returns 0 / never blocks caller
#   T005-D: provider_input_tokens + provider_output_tokens appear when passed
#
# Run with:
#   bash scripts/test_log_subagent.sh

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_SUBAGENT="$SCRIPTS_DIR/log-subagent.sh"
TEST_SLUG="test-log-subagent-t005"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "${TMPDIR:-/tmp}/test_log_subagent_XXXXXX"
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
  if printf '%s' "$haystack" | grep -qF "$needle"; then
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
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    echo "  FAIL: $label (found unwanted substring)"
    echo "        unwanted: $needle"
    echo "        in: $haystack"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  fi
}

# Run log-subagent.sh with a hermetic env so events go to a temp base dir.
# Uses Z_HARNESS_BASE_DIR (no slug — simpler for these tests).
run_subagent_log() {
  local base_dir="$1" run_id="$2"
  shift 2
  # cd to a temp git repo so log-event.sh can resolve REPO_ROOT
  local tmp_repo
  tmp_repo="$(_tmpdir)"
  git -C "$tmp_repo" init -q 2>/dev/null
  git -C "$tmp_repo" config user.email "test@test.local"
  git -C "$tmp_repo" config user.name "Test"
  (
    cd "$tmp_repo"
    Z_HARNESS_BASE_DIR="$base_dir" Z_HARNESS_HOST="claude-test" \
      bash "$LOG_SUBAGENT" --run "$run_id" "$@"
  )
  rm -rf "$tmp_repo"
}

# ---------------------------------------------------------------------------
# T005-A: emitted event validates and carries required fields; chars kept separate
#
# Invariant: every subagent_call event has kind, role, subagent_type,
#   subagent_model, prompt_chars, response_chars — all present as separate fields.
# Failure class: fields missing or chars collapsed into a single est_tokens field.
# ---------------------------------------------------------------------------

echo ""
echo "T005-A: emitted event carries required fields; chars kept separate"

BASE_A="$(_tmpdir)"
RUN_A="t005-a-run"

run_subagent_log "$BASE_A" "$RUN_A" \
  --role "reviewer" \
  --subagent-type "codex-reviewer" \
  --subagent-model "sonnet" \
  --prompt-chars "1234" \
  --response-chars "5678"

METRICS_A="$(cat "$BASE_A/metrics.jsonl" 2>/dev/null || echo "")"
EVENTS_A="$(cat "$BASE_A/archive/$RUN_A/events.jsonl" 2>/dev/null || echo "")"

assert_contains "T005-A: kind=subagent_call present" \
  '"kind":"subagent_call"' "$EVENTS_A"
assert_contains "T005-A: role field present" \
  '"role":"reviewer"' "$EVENTS_A"
assert_contains "T005-A: subagent_type field present" \
  '"subagent_type":"codex-reviewer"' "$EVENTS_A"
assert_contains "T005-A: subagent_model field present" \
  '"subagent_model":"sonnet"' "$EVENTS_A"
assert_contains "T005-A: prompt_chars field present (separate)" \
  '"prompt_chars":1234' "$EVENTS_A"
assert_contains "T005-A: response_chars field present (separate)" \
  '"response_chars":5678' "$EVENTS_A"
# D9 guard: no collapsed est_tokens field
assert_not_contains "T005-A: no est_tokens field (D9 — chars kept separate)" \
  '"est_tokens"' "$EVENTS_A"
# host is stamped by log-event.sh
assert_contains "T005-A: host field present (stamped by log-event.sh)" \
  '"host":' "$EVENTS_A"
# event also lands in metrics.jsonl
assert_contains "T005-A: event also in metrics.jsonl" \
  '"kind":"subagent_call"' "$METRICS_A"

# Validate JSON structure (python3 parse — if it throws, the event is malformed)
JSON_VALID_A="ok"
python3 -c '
import json, sys
for line in sys.stdin:
    line = line.strip()
    if line:
        json.loads(line)
' <<< "$EVENTS_A" 2>/dev/null || JSON_VALID_A="fail"
assert_eq "T005-A: events.jsonl is valid JSON Lines" "ok" "$JSON_VALID_A"

rm -rf "$BASE_A"

# ---------------------------------------------------------------------------
# T005-B: omitting provider tokens is valid (fields absent, not null/0)
#
# Invariant: when --provider-input-tokens and --provider-output-tokens are
#   not passed, the emitted event must NOT contain those keys at all — not
#   null, not 0.  Native Claude subagents don't expose real token usage.
# Failure class: provider_*_tokens appear as null/0 when omitted — misleads
#   cost model into thinking usage was zero rather than unknown.
# ---------------------------------------------------------------------------

echo ""
echo "T005-B: omitting provider tokens yields absent fields (not null/0)"

BASE_B="$(_tmpdir)"
RUN_B="t005-b-run"

run_subagent_log "$BASE_B" "$RUN_B" \
  --role "consultant-primary" \
  --subagent-type "consultant" \
  --subagent-model "haiku" \
  --prompt-chars "800" \
  --response-chars "400"

EVENTS_B="$(cat "$BASE_B/archive/$RUN_B/events.jsonl" 2>/dev/null || echo "")"

assert_not_contains "T005-B: provider_input_tokens absent when not passed" \
  '"provider_input_tokens"' "$EVENTS_B"
assert_not_contains "T005-B: provider_output_tokens absent when not passed" \
  '"provider_output_tokens"' "$EVENTS_B"

# Required fields still present even without provider tokens
assert_contains "T005-B: prompt_chars still present" \
  '"prompt_chars":800' "$EVENTS_B"
assert_contains "T005-B: response_chars still present" \
  '"response_chars":400' "$EVENTS_B"

rm -rf "$BASE_B"

# ---------------------------------------------------------------------------
# T005-C: forced failure (bad/missing args) still returns 0 / never blocks
#
# Invariant: log-subagent.sh ALWAYS exits 0, even when required arguments
#   are missing or unknown flags are passed.  Callers must never be blocked.
# Failure class: non-zero exit when args are bad — blocks the orchestrator.
# ---------------------------------------------------------------------------

echo ""
echo "T005-C: forced failure (bad args) returns 0 / never blocks"

BASE_C="$(_tmpdir)"
REPO_C="$(_tmpdir)"
git -C "$REPO_C" init -q 2>/dev/null
git -C "$REPO_C" config user.email "test@test.local"
git -C "$REPO_C" config user.name "Test"

# Case 1: no arguments at all
EXIT_C1=0
(
  cd "$REPO_C"
  Z_HARNESS_BASE_DIR="$BASE_C" Z_HARNESS_HOST="claude-test" \
    bash "$LOG_SUBAGENT"
) || EXIT_C1=$?
assert_eq "T005-C: no-args invocation exits 0" "0" "$EXIT_C1"

# Case 2: unknown flag
EXIT_C2=0
(
  cd "$REPO_C"
  Z_HARNESS_BASE_DIR="$BASE_C" Z_HARNESS_HOST="claude-test" \
    bash "$LOG_SUBAGENT" --unknown-flag "value"
) || EXIT_C2=$?
assert_eq "T005-C: unknown-flag invocation exits 0" "0" "$EXIT_C2"

# Case 3: partial args (missing required fields)
EXIT_C3=0
(
  cd "$REPO_C"
  Z_HARNESS_BASE_DIR="$BASE_C" Z_HARNESS_HOST="claude-test" \
    bash "$LOG_SUBAGENT" --run "t005-c-partial" --role "reviewer"
) || EXIT_C3=$?
assert_eq "T005-C: partial-args invocation exits 0" "0" "$EXIT_C3"

# Case 4: invoked with `|| true` pattern (as callers do) — confirm no errexit bleed.
# We run the call in a subshell that applies `|| true`, then check the subshell's exit code.
EXIT_C4=0
(
  cd "$REPO_C"
  Z_HARNESS_BASE_DIR="$BASE_C" Z_HARNESS_HOST="claude-test" \
    bash "$LOG_SUBAGENT" || true
) || EXIT_C4=$?
assert_eq "T005-C: || true pattern never propagates non-zero" "0" "$EXIT_C4"

rm -rf "$BASE_C" "$REPO_C"

# ---------------------------------------------------------------------------
# T005-D: provider_input_tokens + provider_output_tokens present when passed
#
# Invariant: when --provider-input-tokens and --provider-output-tokens ARE
#   passed, both appear in the event as integer fields (for external CLIs
#   that print a usage line, e.g. codex-cli).
# Failure class: provider tokens silently dropped even when available.
# ---------------------------------------------------------------------------

echo ""
echo "T005-D: provider tokens appear in event when explicitly passed"

BASE_D="$(_tmpdir)"
RUN_D="t005-d-run"

run_subagent_log "$BASE_D" "$RUN_D" \
  --role "codex-reviewer" \
  --subagent-type "codex-reviewer" \
  --subagent-model "opus" \
  --prompt-chars "9000" \
  --response-chars "3000" \
  --provider-input-tokens "2250" \
  --provider-output-tokens "750"

EVENTS_D="$(cat "$BASE_D/archive/$RUN_D/events.jsonl" 2>/dev/null || echo "")"

assert_contains "T005-D: provider_input_tokens present as integer" \
  '"provider_input_tokens":2250' "$EVENTS_D"
assert_contains "T005-D: provider_output_tokens present as integer" \
  '"provider_output_tokens":750' "$EVENTS_D"
# prompt_chars and response_chars still kept separate (not replaced by provider tokens)
assert_contains "T005-D: prompt_chars still present alongside provider tokens" \
  '"prompt_chars":9000' "$EVENTS_D"
assert_contains "T005-D: response_chars still present alongside provider tokens" \
  '"response_chars":3000' "$EVENTS_D"

rm -rf "$BASE_D"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
