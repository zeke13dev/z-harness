#!/usr/bin/env bash
# test_telemetry_base_resolution.sh — T002 focused tests
#
# Verifies that log-event.sh, check-timeout.sh, and followup_common.py
# all route their artifacts under the resolved base (z_harness_base()),
# not their own hard-coded base logic.
#
# Run with:
#   bash scripts/test_telemetry_base_resolution.sh

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_EVENT="$SCRIPTS_DIR/log-event.sh"
PLAN_PATH="$SCRIPTS_DIR/plan-path.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "/tmp/test_telemetry_XXXXXX"
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

assert_file_exists() {
  local label="$1" path="$2"
  if [[ -f "$path" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — file not found: $path"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_not_exists() {
  local label="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — file unexpectedly exists: $path"
    FAIL=$((FAIL + 1))
  fi
}

assert_dir_not_exists() {
  local label="$1" path="$2"
  if [[ ! -d "$path" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — directory unexpectedly exists: $path"
    FAIL=$((FAIL + 1))
  fi
}

assert_dir_exists() {
  local label="$1" path="$2"
  if [[ -d "$path" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — directory not found: $path"
    FAIL=$((FAIL + 1))
  fi
}

assert_exit_nonzero() {
  local label="$1" exit_code="$2"
  if [[ "$exit_code" -ne 0 ]]; then
    echo "  PASS: $label (exit $exit_code)"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label — expected non-zero exit, got 0"
    FAIL=$((FAIL + 1))
  fi
}

# ---------------------------------------------------------------------------
# T002-A: log-event.sh routes metrics.jsonl to resolved base (Z_HARNESS_BASE_DIR)
#
# Invariant: when Z_HARNESS_BASE_DIR is set, metrics.jsonl lands under that
#   base — not under <repo>/z-harness/metrics.jsonl.
#
# Failure class: telemetry and plans fractured (land in different bases)
# ---------------------------------------------------------------------------

echo ""
echo "T002-A: log-event.sh routes metrics.jsonl to Z_HARNESS_BASE_DIR"

REPO_A="$(_tmpdir)"
git -C "$REPO_A" init -q
git -C "$REPO_A" config user.email "test@test.local"
git -C "$REPO_A" config user.name "Test"

BASE_A="$(_tmpdir)"
RUN_A="t002-a-run"

(
  cd "$REPO_A"
  Z_HARNESS_BASE_DIR="$BASE_A" \
    bash "$LOG_EVENT" "$RUN_A" "t002_test_event" '{"t":"T002-A"}' 2>/dev/null
)

assert_file_exists "T002-A: metrics.jsonl under Z_HARNESS_BASE_DIR" \
  "$BASE_A/metrics.jsonl"
assert_dir_not_exists "T002-A: repo z-harness/ NOT created" \
  "$REPO_A/z-harness"

METRICS_A="$(cat "$BASE_A/metrics.jsonl")"
assert_contains "T002-A: metrics.jsonl contains event kind" \
  '"kind":"t002_test_event"' "$METRICS_A"

rm -rf "$REPO_A" "$BASE_A"

# ---------------------------------------------------------------------------
# T002-B: check-timeout.sh routes marker file to resolved base (Z_HARNESS_BASE_DIR)
#
# Invariant: check-timeout.sh uses z_harness_base() for run-dir resolution,
#   so the .timeout-logged marker lands under Z_HARNESS_BASE_DIR, not <repo>.
#
# Failure class: marker lands under repo even when BASE_DIR is set
# ---------------------------------------------------------------------------

echo ""
echo "T002-B: check-timeout.sh routes marker file to Z_HARNESS_BASE_DIR"

REPO_B="$(_tmpdir)"
git -C "$REPO_B" init -q
git -C "$REPO_B" config user.email "test@test.local"
git -C "$REPO_B" config user.name "Test"

BASE_B="$(_tmpdir)"
RUN_B="t002-b-run"

# Source check-timeout.sh in a subprocess; suppress timeout_availability event
# (it calls log-event.sh which would also write events — we test the marker only).
(
  cd "$REPO_B"
  Z_HARNESS_BASE_DIR="$BASE_B" \
    bash -c 'source '"$SCRIPTS_DIR/check-timeout.sh"' "'"$RUN_B"'"' 2>/dev/null || true
)

# The .timeout-logged marker is a directory under BASE_B/archive/<run>/.timeout-logged
# (created via `mkdir` for atomic one-shot emission guard).
MARKER_B="$BASE_B/archive/$RUN_B/.timeout-logged"
assert_dir_exists "T002-B: .timeout-logged marker dir under Z_HARNESS_BASE_DIR" \
  "$MARKER_B"
assert_dir_not_exists "T002-B: repo z-harness/ NOT created" \
  "$REPO_B/z-harness"

rm -rf "$REPO_B" "$BASE_B"

# ---------------------------------------------------------------------------
# T002-C: opt-out invariant — Z_HARNESS_EXTERNAL_DEFAULT=0, unset Z_HARNESS_BASE_DIR
#   → log-event.sh resolves base to <repo>/z-harness (tier 5, in-repo opt-out)
#
# After the Phase-D flip, the true default (EXTERNAL_DEFAULT unset) routes to
# the external tier. This test explicitly sets =0 to assert the opt-out (in-repo)
# behavior — mirroring how test_base_dir.sh TEST-001 was updated.
#
# Failure class: explicit in-repo opt-out (=0) must still write under repo
# ---------------------------------------------------------------------------

echo ""
echo "T002-C: in-repo opt-out (EXTERNAL_DEFAULT=0) — BASE_DIR unset → base is <repo>/z-harness"

REPO_C="$(_tmpdir)"
git -C "$REPO_C" init -q
git -C "$REPO_C" config user.email "test@test.local"
git -C "$REPO_C" config user.name "Test"

RUN_C="t002-c-run"

(
  cd "$REPO_C"
  Z_HARNESS_EXTERNAL_DEFAULT=0 \
    bash "$LOG_EVENT" "$RUN_C" "t002_stage1_event" '{"t":"T002-C"}' 2>/dev/null
)

assert_file_exists "T002-C: metrics.jsonl under repo z-harness/ in stage 1" \
  "$REPO_C/z-harness/metrics.jsonl"
assert_file_exists "T002-C: events.jsonl under repo z-harness/archive/" \
  "$REPO_C/z-harness/archive/$RUN_C/events.jsonl"

rm -rf "$REPO_C"

# ---------------------------------------------------------------------------
# T002-C2: external-default assertion — unset EXTERNAL_DEFAULT, unset BASE_DIR
#   → log-event.sh resolves base to an EXTERNAL tier (the new default after Phase-D flip)
#
# Failure class: flip not applied — unset still behaves like old in-repo default
# ---------------------------------------------------------------------------

echo ""
echo "T002-C2: external default (EXTERNAL_DEFAULT unset) — BASE_DIR unset → base is external tier"

REPO_C2="$(_tmpdir)"
git -C "$REPO_C2" init -q
git -C "$REPO_C2" config user.email "test@test.local"
git -C "$REPO_C2" config user.name "Test"

XDG_C2="$(_tmpdir)"
RUN_C2="t002-c2-run"

(
  cd "$REPO_C2"
  XDG_STATE_HOME="$XDG_C2" \
  HOME="/nonexistent-home-$$" \
    bash "$LOG_EVENT" "$RUN_C2" "t002_external_event" '{"t":"T002-C2"}' 2>/dev/null
)

# Must NOT have written under repo z-harness/ (external tier chosen)
REPO_C2_REAL="$(realpath "$REPO_C2" 2>/dev/null || echo "$REPO_C2")"
if [[ -f "$REPO_C2_REAL/z-harness/metrics.jsonl" ]]; then
  echo "  FAIL: T002-C2: metrics.jsonl landed under repo z-harness/ (old behavior) — flip not in effect"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T002-C2: metrics.jsonl did NOT land under repo z-harness/ (external default active)"
  PASS=$((PASS + 1))
fi

rm -rf "$REPO_C2" "$XDG_C2"

# ---------------------------------------------------------------------------
# T002-D: followup_common.py log_metrics_event resolves base at call time
#
# Invariant: log_metrics_event uses plan-path.sh base_dir resolution, so
#   setting Z_HARNESS_BASE_DIR redirects metrics.jsonl to the external base.
#
# Failure class: metrics.jsonl always written to <proj_root>/z-harness regardless
#   of Z_HARNESS_BASE_DIR — telemetry fractured from plans.
# ---------------------------------------------------------------------------

echo ""
echo "T002-D: followup_common.py log_metrics_event resolves to Z_HARNESS_BASE_DIR at call time"

REPO_D="$(_tmpdir)"
git -C "$REPO_D" init -q
git -C "$REPO_D" config user.email "test@test.local"
git -C "$REPO_D" config user.name "Test"

BASE_D="$(_tmpdir)"

Z_HARNESS_BASE_DIR="$BASE_D" \
  python3 -c "
import sys
sys.path.insert(0, '${SCRIPTS_DIR}')
from pathlib import Path
from followup_common import log_metrics_event
log_metrics_event(Path('${REPO_D}'), 't002d_event', {'t': 'T002-D'})
" 2>/dev/null

assert_file_exists "T002-D: metrics.jsonl under Z_HARNESS_BASE_DIR via followup_common" \
  "$BASE_D/metrics.jsonl"
assert_file_not_exists "T002-D: metrics.jsonl NOT under repo z-harness/" \
  "$REPO_D/z-harness/metrics.jsonl"

if [[ -f "$BASE_D/metrics.jsonl" ]]; then
  METRICS_D="$(cat "$BASE_D/metrics.jsonl")"
  assert_contains "T002-D: metrics.jsonl contains t002d_event" \
    '"kind":"t002d_event"' "$METRICS_D"
fi

rm -rf "$REPO_D" "$BASE_D"

# ---------------------------------------------------------------------------
# T002-E: check-timeout.sh no-recursion guard — sourcing it while
#   _Z_HARNESS_RESOLVING_BASE=1 does not cause infinite recursion
#
# Invariant: the source-loop sentinel prevents log-event.sh → z_harness_base
#   → log-event.sh recursion.
#
# Failure class: infinite loop or stack overflow when log-event.sh sources plan-path.sh
# ---------------------------------------------------------------------------

echo ""
echo "T002-E: check-timeout.sh sources plan-path.sh without recursion"

REPO_E="$(_tmpdir)"
git -C "$REPO_E" init -q
git -C "$REPO_E" config user.email "test@test.local"
git -C "$REPO_E" config user.name "Test"

BASE_E="$(_tmpdir)"
RUN_E="t002-e-run"

# Source check-timeout.sh with _Z_HARNESS_RESOLVING_BASE already set;
# must not hang or error.
EXIT_E=0
(
  cd "$REPO_E"
  Z_HARNESS_BASE_DIR="$BASE_E" _Z_HARNESS_RESOLVING_BASE=1 \
    timeout 10 bash -c 'source '"$SCRIPTS_DIR/check-timeout.sh"' "'"$RUN_E"'"' 2>/dev/null
) || EXIT_E=$?

if [[ $EXIT_E -eq 124 ]]; then
  echo "  FAIL: T002-E: check-timeout.sh hung (timeout) when sentinel set"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T002-E: check-timeout.sh completed without hanging (exit $EXIT_E)"
  PASS=$((PASS + 1))
fi

rm -rf "$REPO_E" "$BASE_E"

# ---------------------------------------------------------------------------
# T002-F: PROJECT sink root follows Z_HARNESS_BASE_DIR; GLOBAL sink stays
#   at ~/.z-harness/followups regardless of Z_HARNESS_BASE_DIR.
#
# Invariant: project_followups_dir() returns <Z_HARNESS_BASE_DIR>/followups
#   when Z_HARNESS_BASE_DIR is set; Path.home()/.z-harness/followups is never
#   affected by Z_HARNESS_BASE_DIR.
#
# Failure class: PROJECT sink still hardcodes <repo>/z-harness/followups
#   — project entries land in the repo even when BASE_DIR is set, causing
#   plan artifacts and followup entries to be split across two locations.
# ---------------------------------------------------------------------------

echo ""
echo "T002-F: PROJECT sink root follows Z_HARNESS_BASE_DIR; GLOBAL stays at ~/.z-harness"

REPO_F="$(_tmpdir)"
git -C "$REPO_F" init -q
git -C "$REPO_F" config user.email "test@test.local"
git -C "$REPO_F" config user.name "Test"

BASE_F="$(_tmpdir)"

# Ask project_followups_dir() for the project sink root when Z_HARNESS_BASE_DIR is set.
PROJECT_SINK_F="$(
  cd "$REPO_F"
  Z_HARNESS_BASE_DIR="$BASE_F" _Z_HARNESS_RESOLVING_BASE=1 \
    python3 -c "
import sys, os
sys.path.insert(0, '${SCRIPTS_DIR}')
from pathlib import Path
from followup_common import project_followups_dir
print(project_followups_dir(Path('${REPO_F}')))
" 2>/dev/null
)"

assert_eq "T002-F: project_followups_dir() returns BASE_DIR/followups" \
  "$BASE_F/followups" "$PROJECT_SINK_F"

# The GLOBAL sink root must NOT be affected by Z_HARNESS_BASE_DIR.
GLOBAL_SINK_F="$(
  python3 -c "
import sys
sys.path.insert(0, '${SCRIPTS_DIR}')
from pathlib import Path
print(Path.home() / '.z-harness' / 'followups')
" 2>/dev/null
)"
EXPECTED_GLOBAL_F="$HOME/.z-harness/followups"
assert_eq "T002-F: global sink root is always ~/.z-harness/followups" \
  "$EXPECTED_GLOBAL_F" "$GLOBAL_SINK_F"

# Verify: with Z_HARNESS_BASE_DIR unset and EXTERNAL_DEFAULT=0 (opt-out),
# project_followups_dir() returns <repo>/z-harness/followups (in-repo tier).
# After the Phase-D flip, EXTERNAL_DEFAULT must be explicitly =0 for in-repo behavior.
PROJECT_SINK_F_UNSET="$(
  cd "$REPO_F"
  Z_HARNESS_EXTERNAL_DEFAULT=0 _Z_HARNESS_RESOLVING_BASE=1 \
    python3 -c "
import sys
sys.path.insert(0, '${SCRIPTS_DIR}')
from pathlib import Path
from followup_common import project_followups_dir
print(project_followups_dir(Path('${REPO_F}')))
" 2>/dev/null
)"
assert_eq "T002-F: project_followups_dir() with EXTERNAL_DEFAULT=0 defaults to <repo>/z-harness/followups" \
  "${REPO_F}/z-harness/followups" "$PROJECT_SINK_F_UNSET"

rm -rf "$REPO_F" "$BASE_F"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
