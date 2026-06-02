#!/usr/bin/env bash
# overnight-preflight.sh — /z-overnight Phase-0 preflight checks.
#
# Usage:
#   bash scripts/overnight-preflight.sh check-collisions \
#       --chain <comma-or-arrow-separated-steps> \
#       --base <plan-base-dir>
#   bash scripts/overnight-preflight.sh --self-test
#
# Subcommands:
#   check-collisions --chain <steps> --base <dir>
#       Validates the given chain against existing artifacts under <dir>.
#       Exits 0 if safe. Exits nonzero if a collision is detected; on
#       collision, emits a slug_collision_halt event via log-event.sh first.
#
#       v1 rule (per SPEC C13):
#         If the first step in the chain is "plan" or "research" AND
#         <dir>/PLAN.md already exists → slug_collision_halt.
#
# Chain grammar: comma- or arrow-separated step names, e.g.:
#   "plan,test,implement-all,review-all"
#   "plan → test → implement-all → review-all"
#   "research,plan,test,implement-all"
#
# Remediation message on collision:
#   "Slug $SLUG already has a finished plan. Pass a fresh slug or run
#    `/z-overnight resume <prior-RUN>` if you meant to continue."

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPTS_DIR" rev-parse --show-toplevel 2>/dev/null || pwd)"

# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------

if [[ "${1:-}" == "--self-test" ]]; then
  PASS=0
  FAIL=0

  _assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [[ "$actual" == "$expected" ]]; then
      echo "  PASS: $label"
      PASS=$((PASS + 1))
    else
      echo "  FAIL: $label"
      printf "        expected: %s\n" "$expected"
      printf "        actual:   %s\n" "$actual"
      FAIL=$((FAIL + 1))
    fi
  }

  _assert_exit() {
    local label="$1" expected_exit="$2" actual_exit="$3"
    if [[ "$actual_exit" == "$expected_exit" ]]; then
      echo "  PASS: $label (exit $actual_exit)"
      PASS=$((PASS + 1))
    else
      echo "  FAIL: $label"
      printf "        expected exit: %s\n" "$expected_exit"
      printf "        actual exit:   %s\n" "$actual_exit"
      FAIL=$((FAIL + 1))
    fi
  }

  TMPDIR_ROOT="${TMPDIR:-/tmp}"

  # ---- Test 1: chain starting with "plan" + no PLAN.md → exit 0 --------

  TD1="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_t1_XXXXXX")"
  mkdir -p "$TD1/archive"
  EXIT1=0
  Z_HARNESS_SLUG="test-slug-1" bash "$0" check-collisions \
    --chain "plan,test,implement-all,review-all" \
    --base "$TD1" || EXIT1=$?
  _assert_exit "no PLAN.md + plan chain → exit 0" "0" "$EXIT1"
  rm -rf "$TD1"

  # ---- Test 2: chain starting with "plan" + PLAN.md exists → exit nonzero + event ----

  TD2="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_t2_XXXXXX")"
  mkdir -p "$TD2/archive"
  printf '# PLAN\n' > "$TD2/PLAN.md"
  # Pin the artifact base to a temp dir (the default base is now external).
  # The collision event must land under the configured canonical base, not under
  # the --base plan dir or cwd; this keeps that assertion hermetic.
  ZH_BASE2="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_zhbase2_XXXXXX")"
  EXIT2=0
  OUTPUT2="$(Z_HARNESS_BASE_DIR="$ZH_BASE2" Z_HARNESS_SLUG="test-slug-2" bash "$0" check-collisions \
    --chain "plan,test,implement-all,review-all" \
    --base "$TD2" 2>&1)" || EXIT2=$?
  _assert_exit "PLAN.md exists + plan chain → exit nonzero" "1" "$EXIT2"
  # Verify a slug_collision_halt event was written.
  # log-event.sh routes to the canonical plan dir: <base>/plans/<slug>/archive/<run>/events.jsonl
  EVENT_FILE2="$ZH_BASE2/plans/test-slug-2/archive/preflight-test-slug-2/events.jsonl"
  if [[ -f "$EVENT_FILE2" ]]; then
    EVENT_CONTENT2="$(cat "$EVENT_FILE2")"
    if printf '%s' "$EVENT_CONTENT2" | grep -q "slug_collision_halt"; then
      echo "  PASS: slug_collision_halt event written to events.jsonl"
      PASS=$((PASS + 1))
    else
      echo "  FAIL: slug_collision_halt event NOT found in events.jsonl"
      printf "        content: %s\n" "$EVENT_CONTENT2"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "  FAIL: events.jsonl not created at $EVENT_FILE2"
    FAIL=$((FAIL + 1))
  fi
  rm -rf "$ZH_BASE2"
  # Verify remediation message in output
  if printf '%s' "$OUTPUT2" | grep -q "already has a finished plan"; then
    echo "  PASS: remediation message emitted"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: remediation message NOT in output"
    printf "        output: %s\n" "$OUTPUT2"
    FAIL=$((FAIL + 1))
  fi
  rm -rf "$TD2"

  # ---- Test 3: chain NOT starting with plan/research → exit 0 even if PLAN.md exists ----

  TD3="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_t3_XXXXXX")"
  mkdir -p "$TD3/archive"
  printf '# PLAN\n' > "$TD3/PLAN.md"
  EXIT3=0
  Z_HARNESS_SLUG="test-slug-3" bash "$0" check-collisions \
    --chain "implement-all,review-all" \
    --base "$TD3" || EXIT3=$?
  _assert_exit "non-plan chain + PLAN.md exists → exit 0" "0" "$EXIT3"
  rm -rf "$TD3"

  # ---- Test 4: chain starting with "research" + PLAN.md exists → exit nonzero ----

  TD4="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_t4_XXXXXX")"
  mkdir -p "$TD4/archive"
  printf '# PLAN\n' > "$TD4/PLAN.md"
  EXIT4=0
  Z_HARNESS_SLUG="test-slug-4" bash "$0" check-collisions \
    --chain "research,plan,test" \
    --base "$TD4" || EXIT4=$?
  _assert_exit "research-led chain + PLAN.md exists → exit nonzero" "1" "$EXIT4"
  # Clean up the test artifact from log-event.sh's canonical plan dir
  rm -rf "$REPO_ROOT/z-harness/plans/test-slug-4"
  rm -rf "$TD4"

  # ---- Test 5: arrow-separated chain syntax is handled ----

  TD5="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_t5_XXXXXX")"
  mkdir -p "$TD5/archive"
  EXIT5=0
  Z_HARNESS_SLUG="test-slug-5" bash "$0" check-collisions \
    --chain "plan → test → implement-all" \
    --base "$TD5" || EXIT5=$?
  _assert_exit "arrow-separated chain (no PLAN.md) → exit 0" "0" "$EXIT5"
  rm -rf "$TD5"

  # ---- Test 6: --chain without value → exit 2 --------------------------------

  EXIT6=0
  bash "$0" check-collisions --chain 2>/dev/null || EXIT6=$?
  _assert_exit "--chain with no value → exit 2" "2" "$EXIT6"

  # ---- Test 7: --base without value → exit 2 ---------------------------------

  EXIT7=0
  bash "$0" check-collisions --base 2>/dev/null || EXIT7=$?
  _assert_exit "--base with no value → exit 2" "2" "$EXIT7"

  # ---- Test 8: collision event written even when invoked from /tmp -----------
  # Simulates being called with an absolute path from outside the repo to verify
  # that log-event.sh still writes to the canonical repo path (Finding 2 fix).

  TD8="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_t8_XXXXXX")"
  mkdir -p "$TD8/archive"
  printf '# PLAN\n' > "$TD8/PLAN.md"
  # Pin the artifact base to an absolute temp dir. The point of this test is
  # cwd-independence: invoked from /tmp, the event must still land under the
  # configured canonical base (not a cwd-derived path), which the pinned
  # absolute Z_HARNESS_BASE_DIR makes verifiable and hermetic.
  ZH_BASE8="$(mktemp -d "${TMPDIR_ROOT}/overnight_preflight_zhbase8_XXXXXX")"
  EXIT8=0
  # Run from /tmp (not the repo root) using absolute path to the script
  OUTPUT8="$(cd /tmp && Z_HARNESS_BASE_DIR="$ZH_BASE8" Z_HARNESS_SLUG="test-slug-8" bash "$SCRIPTS_DIR/overnight-preflight.sh" check-collisions \
    --chain "plan,test" \
    --base "$TD8" 2>&1)" || EXIT8=$?
  _assert_exit "collision from /tmp cwd → exit nonzero" "1" "$EXIT8"
  # The event must appear under the configured canonical base, not /tmp
  EVENT_FILE8="$ZH_BASE8/plans/test-slug-8/archive/preflight-test-slug-8/events.jsonl"
  if [[ -f "$EVENT_FILE8" ]]; then
    if grep -q "slug_collision_halt" "$EVENT_FILE8"; then
      echo "  PASS: slug_collision_halt event written to canonical base path (not /tmp)"
      PASS=$((PASS + 1))
    else
      echo "  FAIL: slug_collision_halt event NOT found in canonical events.jsonl"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "  FAIL: events.jsonl not created at canonical path $EVENT_FILE8"
    FAIL=$((FAIL + 1))
  fi
  rm -rf "$ZH_BASE8" "$TD8"

  # ---- Summary ---------------------------------------------------------------

  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  if [[ "$FAIL" -gt 0 ]]; then
    exit 1
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Parse the first step from a chain string.
# Handles both comma-separated and arrow-separated (→ or ->) forms.
# Strips leading/trailing whitespace from each token.
first_step_of_chain() {
  local chain="$1"
  # Normalize: replace → and -> with comma
  local normalized
  normalized="${chain//→/,}"
  normalized="${normalized//->/,}"
  # Get the first field (trim whitespace)
  local first
  first="$(printf '%s' "$normalized" | cut -d',' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  printf '%s' "$first"
}

# ---------------------------------------------------------------------------
# Subcommand: check-collisions
# ---------------------------------------------------------------------------

cmd_check_collisions() {
  local chain="" base=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --chain)
        if [[ -z "${2:-}" ]]; then
          echo "overnight-preflight.sh check-collisions: --chain requires a value" >&2
          exit 2
        fi
        shift
        chain="$1"
        shift
        ;;
      --base)
        if [[ -z "${2:-}" ]]; then
          echo "overnight-preflight.sh check-collisions: --base requires a value" >&2
          exit 2
        fi
        shift
        base="$1"
        shift
        ;;
      *)
        echo "Unknown option: $1" >&2
        exit 2
        ;;
    esac
  done

  if [[ -z "$chain" ]]; then
    echo "overnight-preflight.sh check-collisions: --chain is required" >&2
    exit 2
  fi
  if [[ -z "$base" ]]; then
    echo "overnight-preflight.sh check-collisions: --base is required" >&2
    exit 2
  fi

  local first_step
  first_step="$(first_step_of_chain "$chain")"

  # v1 rule: only check plan/research as first step
  if [[ "$first_step" != "plan" && "$first_step" != "research" ]]; then
    exit 0
  fi

  # Check if PLAN.md already exists under $BASE
  local plan_md="$base/PLAN.md"
  if [[ ! -f "$plan_md" ]]; then
    exit 0
  fi

  # Collision detected — derive slug for the event
  local slug="${Z_HARNESS_SLUG:-$(basename "$base")}"
  local run_id="preflight-${slug}"
  local conflicting_artifact="$plan_md"

  local payload
  payload="$(python3 -c '
import json, sys
slug, artifact, chain, first_step = sys.argv[1:5]
obj = {
    "slug": slug,
    "conflicting_artifact": artifact,
    "chain": chain,
    "first_step": first_step,
}
print(json.dumps(obj))
' "$slug" "$conflicting_artifact" "$chain" "$first_step")"

  # Emit slug_collision_halt event via log-event.sh.
  # cd to REPO_ROOT so log-event.sh resolves git rev-parse relative to the
  # canonical repo, not the caller's working directory.
  # We set Z_HARNESS_SLUG so log-event.sh routes to the right plan dir.
  (cd "$REPO_ROOT" && Z_HARNESS_SLUG="$slug" \
    bash "$SCRIPTS_DIR/log-event.sh" "$run_id" "slug_collision_halt" "$payload")

  # Emit remediation message to stderr
  printf 'Error: Slug %s already has a finished plan. Pass a fresh slug or run `/z-overnight resume <prior-RUN>` if you meant to continue.\n' \
    "$slug" >&2

  exit 1
}

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 {check-collisions|--self-test} [options]" >&2
  exit 2
fi

subcmd="$1"
shift

case "$subcmd" in
  check-collisions)
    cmd_check_collisions "$@"
    ;;
  *)
    echo "Unknown subcommand: $subcmd" >&2
    echo "Usage: $0 {check-collisions|--self-test} [options]" >&2
    exit 2
    ;;
esac
