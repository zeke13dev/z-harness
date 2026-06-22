#!/usr/bin/env bash
# test_bench_autonomy.sh — Tests for the bench-autonomy-check gate and
# the runtime fail-closed unhandled_gate mechanism (H4).
#
# Run with:
#   bash scripts/test_bench_autonomy.sh
#
# Tests:
#   1. Under policy mode (NO_ASK=halt + AUTODECIDE_EFFECTIVE set), a registered
#      but uncovered gate yields {"result": "unhandled_gate", ...} — NOT a plain
#      halt or a silent block.
#   2. Under non-policy mode (NO_ASK=halt but no AUTODECIDE vars), a registered
#      uncovered gate yields plain {"result": "halt", ...} (existing behavior
#      unchanged).
#   3. Under policy mode, a gate COVERED by the policy yields {"result": "proceed"}.
#   4. bench-autonomy-check.sh FAILS (exit non-zero) when the policy is missing a
#      required hot-path gate.
#   5. bench-autonomy-check.sh PASSES (exit 0) when the policy is complete.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
CONFIG_PY="$SCRIPTS_DIR/config.py"
BENCH_CHECK="$SCRIPTS_DIR/bench-autonomy-check.sh"
PYTHON="${PYTHON:-python3}"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    echo "        expected: $(printf '%q' "$expected")"
    echo "        actual:   $(printf '%q' "$actual")"
    FAIL=$((FAIL + 1))
  fi
}

assert_json_field() {
  local label="$1" field="$2" expected="$3" json="$4"
  local actual
  actual="$(echo "$json" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('$field','<missing>'))")"
  assert_eq "$label (.${field}=${expected})" "$expected" "$actual"
}

assert_exit_zero() {
  local label="$1" exit_code="$2"
  if [[ "$exit_code" -eq 0 ]]; then
    echo "  PASS: $label (exit 0)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — expected exit 0, got $exit_code"
    FAIL=$((FAIL + 1))
  fi
}

assert_exit_nonzero() {
  local label="$1" exit_code="$2"
  if [[ "$exit_code" -ne 0 ]]; then
    echo "  PASS: $label (exit $exit_code != 0)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — expected non-zero exit, got 0"
    FAIL=$((FAIL + 1))
  fi
}

# Build a clean env with Z_HARNESS_* vars stripped
clean_env() {
  env -i PATH="$PATH" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" \
    XDG_CONFIG_HOME="$(mktemp -d /tmp/zhtest-xdg-XXXXXX)" \
    "$@"
}

# ---------------------------------------------------------------------------
# TEST 1: policy mode + uncovered gate → unhandled_gate (NOT halt or silent block)
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 1: policy mode, uncovered registered gate → unhandled_gate ---"

# workflow.review_all_proceed is registered but NOT in OVERNIGHT_AUTODECIDE_QIDS_DEFAULT
# and NOT covered by the policy AUTODECIDE_EFFECTIVE below.  Under policy mode it must
# yield unhandled_gate, proving the fail-closed guard (H4) fires correctly.
#
# Note: OVERNIGHT_AUTODECIDE_QIDS_DEFAULT merges in workflow.slug_confirm and
# workflow.audit_to_amend automatically; we must use a gate absent from both the
# defaults AND the EFFECTIVE payload to trigger the unhandled_gate path.
AUTODECIDE='{"workflow.slug_confirm":"auto_accept","workflow.plan_decisions_approval":"approve","workflow.implement_all_proceed":"auto_resume"}'

OUT="$(clean_env \
  Z_HARNESS_NO_ASK=halt \
  Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE="$AUTODECIDE" \
  $PYTHON "$CONFIG_PY" check-no-ask --question-id workflow.review_all_proceed)"
EC=$?

assert_exit_zero "TEST1: exit 0" "$EC"
assert_json_field "TEST1: result=unhandled_gate" "result" "unhandled_gate" "$OUT"
assert_json_field "TEST1: rule_id=unhandled_gate" "rule_id" "unhandled_gate" "$OUT"
assert_json_field "TEST1: question_id preserved" "question_id" "workflow.review_all_proceed" "$OUT"

# Verify the 'reason' field is present (non-empty)
REASON="$(echo "$OUT" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('reason') else 'missing')")"
assert_eq "TEST1: reason field present" "ok" "$REASON"

# ---------------------------------------------------------------------------
# TEST 2: non-policy mode (NO_ASK=halt, no AUTODECIDE vars) + uncovered gate → plain halt
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 2: non-policy mode, uncovered registered gate → plain halt (unchanged) ---"

# workflow.review_all_proceed is not in OVERNIGHT_AUTODECIDE_QIDS_DEFAULT either,
# so with NO_ASK=halt and NO policy env vars it should return plain halt (not unhandled_gate).
OUT="$(clean_env \
  Z_HARNESS_NO_ASK=halt \
  $PYTHON "$CONFIG_PY" check-no-ask --question-id workflow.review_all_proceed)"
EC=$?

assert_exit_zero "TEST2: exit 0" "$EC"
assert_json_field "TEST2: result=halt" "result" "halt" "$OUT"

# Confirm result is NOT unhandled_gate
RESULT_VAL="$(echo "$OUT" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('result',''))")"
if [[ "$RESULT_VAL" != "unhandled_gate" ]]; then
  echo "  PASS: TEST2: result is not unhandled_gate (it is '$RESULT_VAL')"
  PASS=$((PASS + 1))
else
  echo "  FAIL: TEST2: result should not be unhandled_gate in non-policy mode"
  FAIL=$((FAIL + 1))
fi

# ---------------------------------------------------------------------------
# TEST 3: policy mode, COVERED gate → proceed
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 3: policy mode, covered gate → proceed ---"

OUT="$(clean_env \
  Z_HARNESS_NO_ASK=halt \
  Z_HARNESS_OVERNIGHT_AUTODECIDE_EFFECTIVE="$AUTODECIDE" \
  $PYTHON "$CONFIG_PY" check-no-ask --question-id workflow.slug_confirm)"
EC=$?

assert_exit_zero "TEST3: exit 0" "$EC"
assert_json_field "TEST3: result=proceed" "result" "proceed" "$OUT"

# ---------------------------------------------------------------------------
# TEST 4 + 5 invoke bench-autonomy-check.sh, which imports the pier bench rig
# (zharness_pier.policy). That package lives under the gitignored z-harness/ tree
# and is therefore absent in CI and fresh clones — the check then exits nonzero
# regardless of policy content. Skip both tests when the rig is absent rather
# than failing on a missing fixture (the rig itself is what they exercise).
# ---------------------------------------------------------------------------
PIER_AVAILABLE=1
[[ -d "$REPO_ROOT/z-harness/bench/pier/zharness_pier" ]] || PIER_AVAILABLE=0

# ---------------------------------------------------------------------------
# TEST 4: bench-autonomy-check.sh FAILS on incomplete policy
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 4: bench-autonomy-check.sh fails on incomplete policy ---"

if [[ $PIER_AVAILABLE -eq 0 ]]; then
  echo "  SKIP: pier rig (zharness_pier) not present — bench-autonomy-check unavailable"
else
TMPDIR_POLICY="$(mktemp -d /tmp/zhtest-policy-XXXXXX)"

# Write an incomplete policy that is missing workflow.implement_all_proceed
cat > "$TMPDIR_POLICY/benchmark-autonomy-incomplete.yaml" <<'YAML'
policy_version: "test-incomplete"
gates:
  workflow.slug_confirm:
    value: auto_accept
    rationale: "test only"
  workflow.plan_decisions_approval:
    value: approve
    rationale: "test only"
YAML

EC_CHECK=0
bash "$BENCH_CHECK" --policy "$TMPDIR_POLICY/benchmark-autonomy-incomplete.yaml" \
  > /dev/null 2>&1 || EC_CHECK=$?

assert_exit_nonzero "TEST4: bench-autonomy-check exits non-zero on incomplete policy" "$EC_CHECK"

rm -rf "$TMPDIR_POLICY"
fi

# ---------------------------------------------------------------------------
# TEST 5: bench-autonomy-check.sh PASSES on complete policy
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 5: bench-autonomy-check.sh passes on complete (real) policy ---"

REAL_POLICY="$REPO_ROOT/z-harness/bench/pier/benchmark-autonomy.yaml"

if [[ $PIER_AVAILABLE -eq 0 ]]; then
  echo "  SKIP: pier rig (zharness_pier) not present — bench-autonomy-check unavailable"
elif [[ ! -f "$REAL_POLICY" ]]; then
  echo "  SKIP: real policy not found at $REAL_POLICY"
else
  EC_CHECK=0
  bash "$BENCH_CHECK" --policy "$REAL_POLICY" > /dev/null 2>&1 || EC_CHECK=$?
  assert_exit_zero "TEST5: bench-autonomy-check exits 0 on complete policy" "$EC_CHECK"
fi

# ---------------------------------------------------------------------------
# TEST 6 (regression): non-policy mode, unregistered gate → halt (not unhandled_gate)
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 6: non-policy mode, unregistered gate → halt (existing behavior) ---"

OUT="$(clean_env \
  Z_HARNESS_NO_ASK=halt \
  $PYTHON "$CONFIG_PY" check-no-ask --question-id workflow.completely_unknown_gate_xyz)"
EC=$?

assert_exit_zero "TEST6: exit 0" "$EC"
assert_json_field "TEST6: result=halt for unknown gate" "result" "halt" "$OUT"
assert_json_field "TEST6: rule_id=unknown_ask_blocked" "rule_id" "unknown_ask_blocked" "$OUT"

# ---------------------------------------------------------------------------
# TEST 7 (regression): NO_ASK not set → proceed (non-overnight mode unchanged)
# ---------------------------------------------------------------------------
echo ""
echo "--- TEST 7: NO_ASK unset → proceed (non-overnight mode unchanged) ---"

OUT="$(clean_env \
  $PYTHON "$CONFIG_PY" check-no-ask --question-id workflow.audit_to_amend)"
EC=$?

assert_exit_zero "TEST7: exit 0" "$EC"
assert_json_field "TEST7: result=proceed when NO_ASK not set" "result" "proceed" "$OUT"
assert_json_field "TEST7: rule_id=no_overnight_active" "rule_id" "no_overnight_active" "$OUT"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
echo "========================================"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
else
  exit 0
fi
