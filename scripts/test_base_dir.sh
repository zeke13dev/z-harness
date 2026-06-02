#!/usr/bin/env bash
# test_base_dir.sh — Integration tests for Z_HARNESS_BASE_DIR artifact relocation
#
# Run with:
#   bash scripts/test_base_dir.sh
#
# Tests:
#   1. Unset Z_HARNESS_BASE_DIR → events/metrics under <repo>/z-harness/ (default behavior)
#   2. Z_HARNESS_BASE_DIR=/tmp/... → events/metrics under that dir; nothing written to repo
#   3. Z_HARNESS_BASE_DIR=relative-path → plan-path.sh exits 1 with a clear error
#   4. plan_dir() uses Z_HARNESS_BASE_DIR/plans when Z_HARNESS_PLANS_DIR is unset
#   5. Z_HARNESS_PLANS_DIR takes precedence over Z_HARNESS_BASE_DIR for plan paths

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_EVENT="$SCRIPTS_DIR/log-event.sh"
PLAN_PATH="$SCRIPTS_DIR/plan-path.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Always use /tmp directly (not TMPDIR) so tmpdir-based repos are outside
# any enclosing git tree; this ensures git rev-parse --show-toplevel resolves
# to the hermetic repo, not the harness repo.
_tmpdir() {
  mktemp -d "/tmp/test_base_dir_XXXXXX"
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

# Invoke log-event.sh inside a hermetic git repo (tmpdir).
# Args: log_event_args...
# Env vars passed verbatim; REPO_ROOT is set to a temp git repo.
run_log_event_in_repo() {
  local repo_root="$1"; shift
  # log-event.sh uses `git rev-parse --show-toplevel` to find REPO_ROOT.
  # We run it with cwd=repo_root so git resolves to the tmp repo.
  (
    cd "$repo_root"
    bash "$LOG_EVENT" "$@"
  )
}

# ---------------------------------------------------------------------------
# Setup: create a hermetic tmp git repo for use in tests that need git context.
# ---------------------------------------------------------------------------

REPO="$(_tmpdir)"
git -C "$REPO" init -q
git -C "$REPO" config user.email "test@test.local"
git -C "$REPO" config user.name "Test"

# ---------------------------------------------------------------------------
# TEST-001: Z_HARNESS_EXTERNAL_DEFAULT=0 (opt-out) + unset Z_HARNESS_BASE_DIR
#           → default path under repo (old in-repo behavior)
# ---------------------------------------------------------------------------
#
# Invariant: When Z_HARNESS_BASE_DIR is unset AND Z_HARNESS_EXTERNAL_DEFAULT=0,
#   log-event.sh writes:
#   events.jsonl  → <repo>/z-harness/archive/<run>/events.jsonl (via PLANS_DIR override)
#   metrics.jsonl → <repo>/z-harness/metrics.jsonl
#
# Note: After the Phase-D flip, the true default (EXTERNAL_DEFAULT unset) routes
#   to the external tier. This test explicitly sets =0 to assert the opt-out behavior.
#   See TEST-001b for the new default assertion (unset → external).
#
# Failure class: explicit in-repo opt-out (=0) must still write under repo
# ---------------------------------------------------------------------------

echo ""
echo "TEST-001: EXTERNAL_DEFAULT=0 (opt-out) + unset BASE_DIR → events under repo z-harness/"

RUN_001="test-base-dir-001"
SLUG_001="test-slug-001"

EXIT_001=0
(
  cd "$REPO"
  Z_HARNESS_SLUG="$SLUG_001" \
  Z_HARNESS_PLANS_DIR="$REPO/zh-plans" \
  Z_HARNESS_EXTERNAL_DEFAULT=0 \
  bash "$LOG_EVENT" "$RUN_001" "test_event" '{"msg":"default"}' 2>/dev/null
) || EXIT_001=$?

# With SLUG set and Z_HARNESS_PLANS_DIR pointing to repo's zh-plans, events go there
EXPECTED_EVENTS_001="$REPO/zh-plans/$SLUG_001/archive/$RUN_001/events.jsonl"
EXPECTED_METRICS_001="$REPO/z-harness/metrics.jsonl"

assert_file_exists "TEST-001: events.jsonl created under Z_HARNESS_PLANS_DIR" "$EXPECTED_EVENTS_001"
assert_file_exists "TEST-001: metrics.jsonl under repo z-harness/ (EXTERNAL_DEFAULT=0 opt-out)" "$EXPECTED_METRICS_001"

# metrics must NOT be under any tmp dir (it's in the repo)
METRICS_CONTENT_001="$(cat "$EXPECTED_METRICS_001")"
assert_contains "TEST-001: metrics.jsonl contains test_event" '"kind":"test_event"' "$METRICS_CONTENT_001"

# Clean up test state (also remove the anchor written by z_harness_base() so
# subsequent tests that use a different Z_HARNESS_BASE_DIR are not blocked by
# the mismatch-detection invariant — each test that needs tier-1 uses a fresh base).
rm -rf "$REPO/zh-plans" "$REPO/z-harness"
rm -f "$REPO/.git/.z-harness-base"

# ---------------------------------------------------------------------------
# TEST-001b: unset Z_HARNESS_EXTERNAL_DEFAULT + unset Z_HARNESS_BASE_DIR
#            → NEW default: external tier (not repo/z-harness)
# ---------------------------------------------------------------------------
#
# Invariant: After the Phase-D flip, when BOTH Z_HARNESS_BASE_DIR and
#   Z_HARNESS_EXTERNAL_DEFAULT are unset, z_harness_base() resolves to an
#   external tier (XDG, HOME/.local/state, or .git/z-harness) — NOT pwd/z-harness.
#
# This is the key assertion that the flip is in effect.
#
# Failure class: flip not applied — unset still behaves like old stage-1 in-repo behavior
# ---------------------------------------------------------------------------

echo ""
echo "TEST-001b: unset EXTERNAL_DEFAULT + unset BASE_DIR → external tier (new default)"

REPO_001b="$(_tmpdir)"
git -C "$REPO_001b" init -q
git -C "$REPO_001b" config user.email "test@test.local"
git -C "$REPO_001b" config user.name "Test"

XDG_001b="$(_tmpdir)"

RESULT_001b="$(cd "$REPO_001b" && \
  XDG_STATE_HOME="$XDG_001b" \
  HOME="/nonexistent-home-$$" \
  bash "$PLAN_PATH" z_harness_base 2>/dev/null)"

# The result must NOT be under REPO_001b (not pwd/z-harness)
REPO_001b_REAL="$(realpath "$REPO_001b" 2>/dev/null || echo "$REPO_001b")"
if printf '%s' "$RESULT_001b" | grep -qF "$REPO_001b_REAL"; then
  echo "  FAIL: TEST-001b: z_harness_base returned path under repo (old behavior) — flip not in effect"
  echo "        result: $RESULT_001b"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: TEST-001b: z_harness_base did NOT return repo-local path (external default active)"
  PASS=$((PASS + 1))
fi

# The result must contain the XDG base path (tier 2 is first writable external tier)
REPOID_001b="$(cd "$REPO_001b" && bash "$PLAN_PATH" z_harness_repo_id 2>/dev/null)"
assert_contains "TEST-001b: z_harness_base resolves to external XDG tier (new default)" \
  "z-harness/$REPOID_001b" "$RESULT_001b"

rm -rf "$REPO_001b" "$XDG_001b"
rm -f "$REPO_001b/.git/.z-harness-base" 2>/dev/null || true

# ---------------------------------------------------------------------------
# TEST-002: Z_HARNESS_BASE_DIR set → events and metrics under override dir
# ---------------------------------------------------------------------------
#
# Invariant: When Z_HARNESS_BASE_DIR=/tmp/zh, ALL z-harness artifacts write
#   under /tmp/zh; nothing is written under the repo's z-harness/ directory.
#
# Failure class: artifacts land inside task repo, corrupting model.patch
# ---------------------------------------------------------------------------

echo ""
echo "TEST-002: Z_HARNESS_BASE_DIR set → artifacts under override dir, nothing under repo"

BASE_002="$(_tmpdir)"
RUN_002="test-base-dir-002"
SLUG_002="test-slug-002"

EXIT_002=0
(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BASE_002" \
  Z_HARNESS_SLUG="$SLUG_002" \
    bash "$LOG_EVENT" "$RUN_002" "test_event" '{"msg":"override"}' 2>/dev/null
) || EXIT_002=$?

EXPECTED_EVENTS_002="$BASE_002/plans/$SLUG_002/archive/$RUN_002/events.jsonl"
EXPECTED_METRICS_002="$BASE_002/metrics.jsonl"

assert_file_exists "TEST-002: events.jsonl under BASE_DIR/plans/<slug>/archive/<run>/" "$EXPECTED_EVENTS_002"
assert_file_exists "TEST-002: metrics.jsonl under BASE_DIR" "$EXPECTED_METRICS_002"

# Critical: nothing written under repo's z-harness/
assert_dir_not_exists "TEST-002: repo z-harness/ dir not created" "$REPO/z-harness"

# Events content sanity
EVENTS_002="$(cat "$EXPECTED_EVENTS_002")"
assert_contains "TEST-002: events.jsonl contains test_event" '"kind":"test_event"' "$EVENTS_002"

METRICS_002="$(cat "$EXPECTED_METRICS_002")"
assert_contains "TEST-002: metrics.jsonl contains test_event" '"kind":"test_event"' "$METRICS_002"

rm -rf "$BASE_002"

# ---------------------------------------------------------------------------
# TEST-002b: Z_HARNESS_BASE_DIR set, no slug → archive under BASE_DIR/archive/
# ---------------------------------------------------------------------------
#
# Invariant: legacy no-slug mode also respects Z_HARNESS_BASE_DIR.
#
# Failure class: no-slug mode still writes under repo
# ---------------------------------------------------------------------------

echo ""
echo "TEST-002b: Z_HARNESS_BASE_DIR set, no slug → archive under BASE_DIR/archive/"

BASE_002b="$(_tmpdir)"
RUN_002b="test-base-dir-002b"

EXIT_002b=0
(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BASE_002b" \
    bash "$LOG_EVENT" "$RUN_002b" "test_event_noslug" '{"msg":"noslug"}' 2>/dev/null
) || EXIT_002b=$?

EXPECTED_EVENTS_002b="$BASE_002b/archive/$RUN_002b/events.jsonl"
EXPECTED_METRICS_002b="$BASE_002b/metrics.jsonl"

assert_file_exists "TEST-002b: events.jsonl under BASE_DIR/archive/<run>/" "$EXPECTED_EVENTS_002b"
assert_file_exists "TEST-002b: metrics.jsonl under BASE_DIR" "$EXPECTED_METRICS_002b"
assert_dir_not_exists "TEST-002b: repo z-harness/ dir not created" "$REPO/z-harness"

rm -rf "$BASE_002b"

# ---------------------------------------------------------------------------
# TEST-003: Z_HARNESS_BASE_DIR with a relative path → exits 1 with error
# ---------------------------------------------------------------------------
#
# Invariant: plan-path.sh rejects non-absolute Z_HARNESS_BASE_DIR.
#
# Failure class: relative path silently resolves from wrong CWD, scatters artifacts
# ---------------------------------------------------------------------------

echo ""
echo "TEST-003: Z_HARNESS_BASE_DIR=relative-path → exit 1"

EXIT_003=0
Z_HARNESS_BASE_DIR="relative/path" bash "$PLAN_PATH" z_harness_base_override 2>/dev/null || EXIT_003=$?

assert_exit_nonzero "TEST-003: non-absolute Z_HARNESS_BASE_DIR causes exit 1" "$EXIT_003"

# Also check the error message
ERR_003="$(Z_HARNESS_BASE_DIR="relative/path" bash "$PLAN_PATH" z_harness_base_override 2>&1 || true)"
assert_contains "TEST-003: error message mentions absolute path" "absolute" "$ERR_003"

# ---------------------------------------------------------------------------
# TEST-004: plan_dir() uses Z_HARNESS_BASE_DIR/plans when Z_HARNESS_PLANS_DIR unset
# ---------------------------------------------------------------------------
#
# Invariant: plan_dir uses BASE_DIR/plans as the default root when BASE_DIR is set.
#
# Failure class: plan dirs resolve under repo even when BASE_DIR is set
# ---------------------------------------------------------------------------

echo ""
echo "TEST-004: plan_dir() uses Z_HARNESS_BASE_DIR/plans when Z_HARNESS_PLANS_DIR is unset"

BASE_004="/tmp/zh-test-004"
RESULT_004="$(Z_HARNESS_BASE_DIR="$BASE_004" bash "$PLAN_PATH" plan_dir "my-slug")"
EXPECTED_004="$BASE_004/plans/my-slug"

assert_eq "TEST-004: plan_dir returns BASE_DIR/plans/slug" "$EXPECTED_004" "$RESULT_004"

# ---------------------------------------------------------------------------
# TEST-005: Z_HARNESS_PLANS_DIR takes precedence over Z_HARNESS_BASE_DIR
# ---------------------------------------------------------------------------
#
# Invariant: when both Z_HARNESS_PLANS_DIR and Z_HARNESS_BASE_DIR are set,
#   Z_HARNESS_PLANS_DIR wins for the plan path.
#
# Failure class: explicit plans override silently ignored when BASE_DIR is also set
# ---------------------------------------------------------------------------

echo ""
echo "TEST-005: Z_HARNESS_PLANS_DIR takes precedence over Z_HARNESS_BASE_DIR"

PLANS_005="/tmp/explicit-plans"
BASE_005="/tmp/zh-test-005"
RESULT_005="$(Z_HARNESS_PLANS_DIR="$PLANS_005" Z_HARNESS_BASE_DIR="$BASE_005" bash "$PLAN_PATH" plan_dir "my-slug")"
EXPECTED_005="$PLANS_005/my-slug"

assert_eq "TEST-005: Z_HARNESS_PLANS_DIR wins over BASE_DIR" "$EXPECTED_005" "$RESULT_005"

# ---------------------------------------------------------------------------
# TEST-006: B1 — legacy slug fallback disabled when Z_HARNESS_BASE_DIR is set
# ---------------------------------------------------------------------------
#
# Invariant: when Z_HARNESS_BASE_DIR is set, a pre-existing legacy run dir
#   under <repo>/z-harness/<slug>/archive/<run> must NOT redirect writes there.
#   All writes must go to <BASE_DIR>/.
#
# Failure class: legacy fallback writes inside the repo, corrupting model.patch
# ---------------------------------------------------------------------------

echo ""
echo "TEST-006: legacy fallback disabled when Z_HARNESS_BASE_DIR is set"

BASE_006="$(_tmpdir)"
RUN_006="test-base-dir-006"
SLUG_006="test-slug-006"

# Pre-create the legacy run dir so the old code would have fallen back to it.
LEGACY_006="$REPO/z-harness/$SLUG_006/archive/$RUN_006"
mkdir -p "$LEGACY_006"

(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BASE_006" \
  Z_HARNESS_SLUG="$SLUG_006" \
    bash "$LOG_EVENT" "$RUN_006" "test_event_b1" '{"msg":"no-legacy"}' 2>/dev/null
)

EXPECTED_EVENTS_006="$BASE_006/plans/$SLUG_006/archive/$RUN_006/events.jsonl"

assert_file_exists "TEST-006: events.jsonl written under BASE_DIR despite legacy dir existing" "$EXPECTED_EVENTS_006"

# The legacy dir should NOT have gotten events.jsonl
LEGACY_EVENTS_006="$LEGACY_006/events.jsonl"
assert_file_not_exists "TEST-006: events.jsonl NOT written to legacy repo dir" "$LEGACY_EVENTS_006"

# No new z-harness artifacts (only the manually created dir exists)
EVENTS_006="$(cat "$EXPECTED_EVENTS_006")"
assert_contains "TEST-006: events.jsonl contains test_event_b1" '"kind":"test_event_b1"' "$EVENTS_006"

rm -rf "$BASE_006" "$REPO/z-harness"

# ---------------------------------------------------------------------------
# TEST-007: M2 — relative Z_HARNESS_PLANS_DIR with Z_HARNESS_BASE_DIR set → exit 1
# ---------------------------------------------------------------------------
#
# Invariant: when Z_HARNESS_BASE_DIR is set, Z_HARNESS_PLANS_DIR must be
#   absolute; a relative path would resolve repo-locally and escape the base.
#
# Failure class: relative PLANS_DIR silently bypasses BASE_DIR, writing into repo
# ---------------------------------------------------------------------------

echo ""
echo "TEST-007: relative Z_HARNESS_PLANS_DIR + Z_HARNESS_BASE_DIR → exit 1"

EXIT_007=0
Z_HARNESS_BASE_DIR="/tmp/zh-007" Z_HARNESS_PLANS_DIR="relative/plans" bash "$PLAN_PATH" plan_dir "my-slug" 2>/dev/null || EXIT_007=$?

assert_exit_nonzero "TEST-007: relative PLANS_DIR + BASE_DIR causes exit 1" "$EXIT_007"

ERR_007="$(Z_HARNESS_BASE_DIR="/tmp/zh-007" Z_HARNESS_PLANS_DIR="relative/plans" bash "$PLAN_PATH" plan_dir "my-slug" 2>&1 || true)"
assert_contains "TEST-007: error message mentions absolute path" "absolute" "$ERR_007"

# ---------------------------------------------------------------------------
# TEST-007b: M2 — actual writers (log-event.sh and check-timeout.sh) reject
#   relative Z_HARNESS_PLANS_DIR when Z_HARNESS_BASE_DIR is set, and write
#   NOTHING under the repo.
# ---------------------------------------------------------------------------
#
# Invariant: the subshell-isolation guard must be in the PARENT shell of each
#   writer, not just in plan_dir (whose exit 1 inside $(...) only kills the
#   subshell and cannot stop the parent from falling through to repo-local
#   resolution).
#
# Failure class: plan_dir's exit 1 swallowed by command substitution, parent
#   continues with empty string and writes artifacts under repo z-harness/.
# ---------------------------------------------------------------------------

echo ""
echo "TEST-007b: actual writers reject relative PLANS_DIR + BASE_DIR, write nothing under repo"

BASE_007b="/tmp/zh-007b-$$"
SLUG_007b="test-slug-007b"
RUN_007b="test-run-007b"

# --- log-event.sh ---
EXIT_007b_LE=0
(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BASE_007b" \
  Z_HARNESS_PLANS_DIR="relative/plans" \
  Z_HARNESS_SLUG="$SLUG_007b" \
    bash "$LOG_EVENT" "$RUN_007b" "test_event_007b" '{"msg":"should-fail"}' 2>/dev/null
) || EXIT_007b_LE=$?

assert_exit_nonzero "TEST-007b: log-event.sh exits non-zero with relative PLANS_DIR + BASE_DIR" "$EXIT_007b_LE"

# Nothing written under the repo z-harness/ or any relative path under repo
assert_dir_not_exists "TEST-007b: log-event.sh writes nothing under repo relative/plans" "$REPO/relative"
assert_dir_not_exists "TEST-007b: log-event.sh writes nothing under repo archive/" "$REPO/archive"
assert_dir_not_exists "TEST-007b: log-event.sh writes nothing under repo z-harness/" "$REPO/z-harness"

# --- check-timeout.sh (sourced in a subprocess so return 1 propagates as exit 1) ---
EXIT_007b_CT=0
(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BASE_007b" \
  Z_HARNESS_PLANS_DIR="relative/plans" \
  Z_HARNESS_SLUG="$SLUG_007b" \
    bash -c 'source '"$SCRIPTS_DIR/check-timeout.sh"' "'"$RUN_007b"'"' 2>/dev/null
) || EXIT_007b_CT=$?

assert_exit_nonzero "TEST-007b: check-timeout.sh exits non-zero with relative PLANS_DIR + BASE_DIR" "$EXIT_007b_CT"

assert_dir_not_exists "TEST-007b: check-timeout.sh writes nothing under repo relative/plans" "$REPO/relative"
assert_dir_not_exists "TEST-007b: check-timeout.sh writes nothing under repo z-harness/" "$REPO/z-harness"

rm -rf "$BASE_007b"

# ---------------------------------------------------------------------------
# TEST-008: M3 — z-overnight Phase-1 path resolution under BASE_DIR override
# ---------------------------------------------------------------------------
#
# Invariant: resolve_plan_path (used by z-overnight Phase-1 to locate BASE and
#   write .overnight.lock, .overnight.flock, overnight-state.json) returns a
#   path under Z_HARNESS_BASE_DIR when it is set; the repo's z-harness/ dir
#   is NOT created.
#
# Failure class: overnight state/lock files land inside the task repo,
#   corrupting model.patch (the same invariant as regular events)
# ---------------------------------------------------------------------------

echo ""
echo "TEST-008: z-overnight Phase-1 path resolution under BASE_DIR override"

BASE_008="$(_tmpdir)"
SLUG_008="test-overnight-slug"

# Simulate z-overnight Phase-1: pre-create the directory at the new canonical path
# (resolve_plan_path returns new path when it exists; falls back to new path for creation)
EXPECTED_PLAN_DIR_008="$BASE_008/plans/$SLUG_008"
mkdir -p "$EXPECTED_PLAN_DIR_008"
mkdir -p "$EXPECTED_PLAN_DIR_008/archive/run-008"

RESOLVED_008="$(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$BASE_008" Z_HARNESS_SLUG="$SLUG_008" \
    bash "$PLAN_PATH" resolve_plan_path "$SLUG_008"
)"

assert_eq "TEST-008: resolve_plan_path returns BASE_DIR/plans/slug" \
  "$EXPECTED_PLAN_DIR_008" "$RESOLVED_008"

# Simulate writing overnight state files under the resolved BASE.
OVERNIGHT_LOCK_008="$RESOLVED_008/.overnight.lock"
OVERNIGHT_FLOCK_008="$RESOLVED_008/.overnight.flock"
OVERNIGHT_STATE_008="$RESOLVED_008/archive/run-008/overnight-state.json"

printf '{"pid":1234}' > "$OVERNIGHT_LOCK_008"
touch "$OVERNIGHT_FLOCK_008"
printf '{"status":"running"}' > "$OVERNIGHT_STATE_008"

assert_file_exists "TEST-008: .overnight.lock under BASE_DIR" "$OVERNIGHT_LOCK_008"
assert_file_exists "TEST-008: .overnight.flock under BASE_DIR" "$OVERNIGHT_FLOCK_008"
assert_file_exists "TEST-008: overnight-state.json under BASE_DIR" "$OVERNIGHT_STATE_008"

# Repo z-harness/ must not have been created by resolve_plan_path
assert_dir_not_exists "TEST-008: repo z-harness/ not created by resolve_plan_path" "$REPO/z-harness"

rm -rf "$BASE_008"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
