#!/usr/bin/env bash
# bench-autonomy-check.sh — pre-run gate for benchmark autonomy policy.
#
# Checks:
#   1. lint-askuser --strict: asserts that all AskUserQuestion callsites in the
#      quick-build hot-path files (skills/z-plan/SKILL.md,
#      skills/z-execute/SKILL.md) are REGISTERED (paired with a
#      resolve-question or check-no-ask call).
#   2. Policy coverage: every quick-build hot-path gate (question_id referenced in
#      those files) is present in z-harness/bench/pier/benchmark-autonomy.yaml
#      and the policy loads without validation errors.
#
# Exit 0 only if both checks pass; non-zero (loud) otherwise.
#
# Usage:
#   scripts/bench-autonomy-check.sh [--policy <path>]
#
# --policy: optional override for the benchmark-autonomy.yaml path.
#           Defaults to z-harness/bench/pier/benchmark-autonomy.yaml (relative
#           to the repo root resolved from this script's location).

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

POLICY_PATH=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --policy)
      shift
      POLICY_PATH="$1"
      shift
      ;;
    *)
      echo "bench-autonomy-check: unknown argument: $1" >&2
      echo "Usage: $0 [--policy <path>]" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$POLICY_PATH" ]]; then
  POLICY_PATH="$REPO_ROOT/z-harness/bench/pier/benchmark-autonomy.yaml"
fi

FAIL=0

# ---------------------------------------------------------------------------
# Step 1: lint-askuser --strict scoped to quick-build hot-path files
# ---------------------------------------------------------------------------

echo "==> bench-autonomy-check step 1: lint-askuser --strict (hot-path callsite audit)"
echo "    Scoping to: skills/z-plan/SKILL.md, skills/z-execute/SKILL.md"

HOT_PATH_FILES=(
  "$REPO_ROOT/skills/z-plan/SKILL.md"
  "$REPO_ROOT/skills/z-execute/SKILL.md"
)

UNREGISTERED_HOT=0
for f in "${HOT_PATH_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "  ERROR: hot-path file not found: $f" >&2
    FAIL=1
    continue
  fi

  # Check if the file has AskUserQuestion callsites
  if ! grep -q "AskUserQuestion" "$f" 2>/dev/null; then
    echo "  OK: no AskUserQuestion in $f"
    continue
  fi

  # A callsite is REGISTERED if the same file has resolve-question or check-no-ask
  if grep -q "resolve-question\|check-no-ask" "$f" 2>/dev/null; then
    echo "  OK: REGISTERED callsite(s) in ${f#"$REPO_ROOT/"}"
  else
    echo "  FAIL: UNREGISTERED AskUserQuestion callsite(s) in ${f#"$REPO_ROOT/"}" >&2
    UNREGISTERED_HOT=$((UNREGISTERED_HOT + 1))
    FAIL=1
  fi
done

if [[ "$UNREGISTERED_HOT" -gt 0 ]]; then
  echo "  ERROR: $UNREGISTERED_HOT hot-path file(s) have unregistered AskUserQuestion callsites." >&2
  echo "  These gates will fail-open (block headless runs) under Z_HARNESS_NO_ASK=halt." >&2
  echo "  Register them with resolve-question or check-no-ask before running the benchmark." >&2
else
  echo "  All hot-path callsites are registered."
fi

# ---------------------------------------------------------------------------
# Step 2: Policy coverage assertion
# ---------------------------------------------------------------------------

echo ""
echo "==> bench-autonomy-check step 2: policy coverage assertion"
echo "    Policy file: $POLICY_PATH"

if [[ ! -f "$POLICY_PATH" ]]; then
  echo "  ERROR: policy file not found: $POLICY_PATH" >&2
  FAIL=1
else
  # Use Python to load + validate the policy and check coverage of hot-path gates.
  PIER_PKG_DIR="$REPO_ROOT/z-harness/bench/pier"

  python3 - <<PYEOF
import sys
import os

# Add pier package to path so we can import zharness_pier.policy
pier_pkg = "$PIER_PKG_DIR"
sys.path.insert(0, pier_pkg)

try:
    from zharness_pier.policy import load_policy, PolicyError, _get_registered_question_ids
except ImportError as e:
    print(f"  ERROR: cannot import zharness_pier.policy: {e}", file=sys.stderr)
    sys.exit(1)

policy_path = "$POLICY_PATH"
try:
    policy = load_policy(policy_path)
except PolicyError as e:
    print(f"  ERROR: policy validation failed: {e}", file=sys.stderr)
    sys.exit(1)

gates_in_policy = set(policy.get("gates", {}).keys())
policy_version = policy.get("policy_version", "<unknown>")
print(f"  Policy version: {policy_version}")
print(f"  Gates in policy: {sorted(gates_in_policy)}")

# Quick-build hot-path gate set: question_ids referenced in z-plan.md and
# z-execute.md.
import re
repo_root = "$REPO_ROOT"
hot_path_files = [
    os.path.join(repo_root, "skills", "z-plan", "SKILL.md"),
    os.path.join(repo_root, "skills", "z-execute", "SKILL.md"),
]

pattern = re.compile(r'workflow\.[a-z_]+')
referenced_tokens = set()
for fp in hot_path_files:
    if not os.path.exists(fp):
        continue
    with open(fp) as fh:
        content = fh.read()
    for m in pattern.findall(content):
        referenced_tokens.add(m)

# Only registered question_ids are decision GATES that need an autonomy policy.
# `workflow.*` config KNOBS (e.g. workflow.planning_mode, workflow.intent_level)
# are behavior settings that get READ in command files, not ask-gates — filter
# them out so a config-knob reference is never mistaken for a hot-path gate.
registered_ids = set(_get_registered_question_ids())
hot_path_gates = referenced_tokens & registered_ids

non_gate_knobs = sorted(referenced_tokens - registered_ids)
if non_gate_knobs:
    print(f"  Note: ignoring non-gate workflow.* config knobs referenced on the hot path: {non_gate_knobs}")
print(f"  Hot-path gates (from command files): {sorted(hot_path_gates)}")

# Every hot-path gate must be in the policy
missing = hot_path_gates - gates_in_policy
if missing:
    print(f"  ERROR: missing from policy: {sorted(missing)}", file=sys.stderr)
    print(f"  Add these gate(s) to {policy_path} with a deliberate value + rationale.", file=sys.stderr)
    sys.exit(1)

print(f"  Coverage OK: all {len(hot_path_gates)} hot-path gate(s) are present in the policy.")
sys.exit(0)
PYEOF
  if [[ $? -ne 0 ]]; then
    FAIL=1
  fi
fi

# ---------------------------------------------------------------------------
# Step 3: Targeted assertion — config.py-registered gates must be in the policy
#
# For each question_id produced by `config.py list-question-ids`, if the id
# looks like a workflow gate that could appear in the quick-build hot path,
# assert it is present as a key in benchmark-autonomy.yaml's `gates:` block.
#
# Currently scoped to workflow.pre_run_cost_gate: this gate was added by
# T005 (token-estimates plan) and must appear in the policy so that headless
# benchmark runs never encounter an unhandled_gate abort on the cost gate.
#
# Extend the REQUIRED_IN_POLICY list below when additional gates need explicit
# benchmark coverage.  Do NOT add gates that are legitimately out-of-scope for
# the quick-build hot path (e.g. gates only reachable via full-build presets).
# ---------------------------------------------------------------------------

echo ""
echo "==> bench-autonomy-check step 3: targeted gate-coverage assertion"
echo "    Checking that config.py-registered gates required for the benchmark"
echo "    are present as keys in the policy's gates: block."

# Gates that MUST be explicitly covered in the policy file.
REQUIRED_IN_POLICY=(
  "workflow.pre_run_cost_gate"
)

# Fetch the registered question_ids once.
REGISTERED_IDS_JSON=""
if REGISTERED_IDS_JSON=$(python3 "$REPO_ROOT/scripts/config.py" list-question-ids 2>/dev/null); then
  : # success
else
  echo "  ERROR: 'config.py list-question-ids' failed (exit $?)" >&2
  FAIL=1
fi

if [[ -n "$REGISTERED_IDS_JSON" ]]; then
  STEP3_FAIL=0
  for qid in "${REQUIRED_IN_POLICY[@]}"; do
    # Check that the qid is registered in config.py.
    if ! python3 -c "import json, sys; ids=json.loads('$REGISTERED_IDS_JSON'); sys.exit(0 if '$qid' in ids else 1)" 2>/dev/null; then
      echo "  SKIP: $qid is not in config.py list-question-ids — no assertion needed."
      continue
    fi

    # The qid IS registered; it must also be a key in the policy's gates: block.
    if python3 - <<PYEOF2
import sys
try:
    import yaml
except ImportError:
    print("  ERROR: PyYAML not available; cannot parse policy file.", file=sys.stderr)
    sys.exit(1)
policy_path = "$POLICY_PATH"
qid = "$qid"
try:
    with open(policy_path) as fh:
        data = yaml.safe_load(fh)
except (yaml.YAMLError, OSError) as e:
    print(f"  ERROR: could not parse {policy_path}: {e}", file=sys.stderr)
    sys.exit(1)
gates = data.get("gates", {}) if isinstance(data, dict) else {}
if qid in gates:
    print(f"  OK: {qid} is present in the policy gates.")
    sys.exit(0)
else:
    print(
        f"  ERROR: {qid} is registered in config.py but is MISSING from "
        f"{policy_path} gates: block.",
        file=sys.stderr,
    )
    print(
        f"  Add a '{qid}:' entry under 'gates:' with a deliberate value + rationale.",
        file=sys.stderr,
    )
    sys.exit(1)
PYEOF2
    then
      : # gate found in policy
    else
      STEP3_FAIL=$((STEP3_FAIL + 1))
      FAIL=1
    fi
  done

  if [[ "$STEP3_FAIL" -eq 0 ]]; then
    echo "  All required gates are present in the policy."
  fi
fi

# ---------------------------------------------------------------------------
# Final verdict
# ---------------------------------------------------------------------------

echo ""
if [[ "$FAIL" -ne 0 ]]; then
  echo "bench-autonomy-check FAILED — fix the above errors before running the benchmark." >&2
  exit 1
else
  echo "bench-autonomy-check PASSED — policy is complete and all hot-path gates are registered."
  exit 0
fi
