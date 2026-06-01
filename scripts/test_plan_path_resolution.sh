#!/usr/bin/env bash
# test_plan_path_resolution.sh — Tests for T001: z_harness_base fallback chain,
#   z_harness_repo_id, anchor invariant, EXTERNAL_DEFAULT gating, dual-read,
#   and PLANS_DIR-absolute guard.
#
# Run with:
#   bash scripts/test_plan_path_resolution.sh
#
# Tests:
#   T001-A: z_harness_repo_id stable across two worktrees of one repo
#   T001-B: fallback tier 2 (XDG_STATE_HOME) chosen when writable + EXTERNAL_DEFAULT=1
#   T001-C: fallback tier 3 (HOME/.local/state) chosen when XDG absent + EXTERNAL_DEFAULT=1
#   T001-D: fallback tier 4 (git-common-dir/z-harness) chosen when HOME absent + EXTERNAL_DEFAULT=1
#   T001-E: fallback tier 5 (pwd/z-harness) is effective base in stage 1 (EXTERNAL_DEFAULT unset)
#   T001-F: EXTERNAL_DEFAULT=0 → effective base = pwd/z-harness regardless of XDG/HOME
#   T001-G: anchor written on first call; second call with same path → no mismatch
#   T001-H: anchor mismatch (two paths disagree) → hard-fail (non-zero exit)
#   T001-I: dual-read: resolve_plan_path finds z-harness/plans/<slug> (secondary legacy)
#   T001-J: dual-read: resolve_plan_path finds z-harness/<slug> (primary legacy flat)
#   T001-K: dual-read: new path (under z_harness_base) takes priority over legacy paths
#   T001-L: PLANS_DIR relative + BASE_DIR set → exit 1 (guard preserved)
#   T001-M: active_plans_dir() returns <base>/active-plans
#   T001-N: followups_dir() returns <base>/followups
#   T001-O: base_dir() returns same as z_harness_base
#   T001-P: all tiers unwritable → FATAL exit (EXTERNAL_DEFAULT=1 forced)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAN_PATH="$SCRIPTS_DIR/plan-path.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
  mktemp -d "/tmp/test_plan_path_XXXXXX"
}

# Always use realpath-resolved paths for comparison so macOS /tmp→/private/tmp
# symlink doesn't cause false failures.
_realpath() {
  realpath "$1" 2>/dev/null || (cd "$1" 2>/dev/null && pwd) || printf '%s' "$1"
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

# Run plan-path.sh subcommand inside a hermetic git repo
run_in_repo() {
  local repo_root="$1"; shift
  (cd "$repo_root"; bash "$PLAN_PATH" "$@")
}

# ---------------------------------------------------------------------------
# TEST T001-A: z_harness_repo_id stable across two worktrees of one repo
# ---------------------------------------------------------------------------
echo ""
echo "T001-A: z_harness_repo_id stable across two worktrees of one repo"

REPO_A="$(_tmpdir)"
git -C "$REPO_A" init -q
git -C "$REPO_A" config user.email "test@test.local"
git -C "$REPO_A" config user.name "Test"
# Create an initial commit so we can add a worktree
printf 'init\n' > "$REPO_A/README"
git -C "$REPO_A" add README
git -C "$REPO_A" commit -q -m "init"

# Add a worktree
WT_A="$(_tmpdir)"
git -C "$REPO_A" worktree add -q "$WT_A" HEAD

# Get repo-id from main checkout and worktree
REPOID_MAIN="$(run_in_repo "$REPO_A" z_harness_repo_id)"
REPOID_WT="$(run_in_repo "$WT_A" z_harness_repo_id)"

assert_eq "T001-A: repo-id identical from main checkout and worktree" "$REPOID_MAIN" "$REPOID_WT"
assert_contains "T001-A: repo-id contains a dash (basename-hex format)" "-" "$REPOID_MAIN"

# repo-id must not contain a slash (safe basename)
if printf '%s' "$REPOID_MAIN" | grep -qF "/"; then
  echo "  FAIL: T001-A: repo-id must not contain a slash, got: $REPOID_MAIN"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-A: repo-id has no slash"
  PASS=$((PASS + 1))
fi

rm -rf "$REPO_A" "$WT_A"

# ---------------------------------------------------------------------------
# TEST T001-B: Tier 2 (XDG_STATE_HOME) chosen when writable + EXTERNAL_DEFAULT=1
# ---------------------------------------------------------------------------
echo ""
echo "T001-B: fallback tier 2 (XDG_STATE_HOME) chosen when writable + EXTERNAL_DEFAULT=1"

REPO_B="$(_tmpdir)"
git -C "$REPO_B" init -q
git -C "$REPO_B" config user.email "test@test.local"
git -C "$REPO_B" config user.name "Test"

XDG_B="$(_tmpdir)"
ANCHOR_B="$REPO_B/.git/.z-harness-base"

RESULT_B="$(cd "$REPO_B" && \
  XDG_STATE_HOME="$XDG_B" \
  HOME="/nonexistent-home-$$" \
  Z_HARNESS_EXTERNAL_DEFAULT=1 \
  bash "$PLAN_PATH" z_harness_base)"

REPOID_B="$(cd "$REPO_B" && bash "$PLAN_PATH" z_harness_repo_id)"

# Use realpath for XDG_B since z_harness_base uses _z_harness_probe_writable which
# creates the dir and the result reflects the path as-given (not realpath-expanded).
# The result should contain the XDG_B path prefix.
assert_contains "T001-B: z_harness_base returns path under XDG_STATE_HOME" \
  "z-harness/$REPOID_B" "$RESULT_B"

# Anchor should have been written
if [[ -f "$ANCHOR_B" ]]; then
  ANCHOR_TIER_B="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("tier",""))' "$ANCHOR_B" 2>/dev/null || true)"
  assert_eq "T001-B: anchor records tier=XDG_STATE_HOME" "XDG_STATE_HOME" "$ANCHOR_TIER_B"
else
  # macOS: /tmp is symlinked to /private/tmp; check canonical path
  ANCHOR_B_REAL="$(_realpath "$REPO_B")/.git/.z-harness-base"
  if [[ -f "$ANCHOR_B_REAL" ]]; then
    ANCHOR_TIER_B="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("tier",""))' "$ANCHOR_B_REAL" 2>/dev/null || true)"
    assert_eq "T001-B: anchor records tier=XDG_STATE_HOME (realpath)" "XDG_STATE_HOME" "$ANCHOR_TIER_B"
  else
    echo "  FAIL: T001-B: anchor file not created at $ANCHOR_B (or $ANCHOR_B_REAL)"
    FAIL=$((FAIL + 1))
  fi
fi

rm -rf "$REPO_B" "$XDG_B"

# ---------------------------------------------------------------------------
# TEST T001-C: Tier 3 (HOME/.local/state) chosen when XDG absent + EXTERNAL_DEFAULT=1
# ---------------------------------------------------------------------------
echo ""
echo "T001-C: fallback tier 3 (HOME/.local/state) chosen when XDG absent + EXTERNAL_DEFAULT=1"

REPO_C="$(_tmpdir)"
git -C "$REPO_C" init -q
git -C "$REPO_C" config user.email "test@test.local"
git -C "$REPO_C" config user.name "Test"

HOME_C="$(_tmpdir)"
REPOID_C="$(cd "$REPO_C" && bash "$PLAN_PATH" z_harness_repo_id)"

RESULT_C="$(cd "$REPO_C" && \
  HOME="$HOME_C" \
  Z_HARNESS_EXTERNAL_DEFAULT=1 \
  bash "$PLAN_PATH" z_harness_base)"

assert_contains "T001-C: z_harness_base returns path under HOME/.local/state/z-harness" \
  ".local/state/z-harness/$REPOID_C" "$RESULT_C"

rm -rf "$REPO_C" "$HOME_C"

# ---------------------------------------------------------------------------
# TEST T001-D: Tier 4 (git-common-dir/z-harness) chosen when HOME absent + EXTERNAL_DEFAULT=1
# ---------------------------------------------------------------------------
echo ""
echo "T001-D: fallback tier 4 (git-common-dir/z-harness) when HOME unwritable + EXTERNAL_DEFAULT=1"

REPO_D="$(_tmpdir)"
git -C "$REPO_D" init -q
git -C "$REPO_D" config user.email "test@test.local"
git -C "$REPO_D" config user.name "Test"

RESULT_D="$(cd "$REPO_D" && \
  HOME="/nonexistent-home-$$" \
  Z_HARNESS_EXTERNAL_DEFAULT=1 \
  bash "$PLAN_PATH" z_harness_base)"

# The result should end with .git/z-harness (using the git-common-dir)
assert_contains "T001-D: z_harness_base returns path ending in .git/z-harness" \
  ".git/z-harness" "$RESULT_D"

rm -rf "$REPO_D"

# ---------------------------------------------------------------------------
# TEST T001-E: Stage 1 (EXTERNAL_DEFAULT unset): effective base = pwd/z-harness
# ---------------------------------------------------------------------------
echo ""
echo "T001-E: stage 1 (EXTERNAL_DEFAULT unset) → effective base = pwd/z-harness"

REPO_E="$(_tmpdir)"
git -C "$REPO_E" init -q
git -C "$REPO_E" config user.email "test@test.local"
git -C "$REPO_E" config user.name "Test"

XDG_E="$(_tmpdir)"
HOME_E="$(_tmpdir)"

RESULT_E="$(cd "$REPO_E" && \
  XDG_STATE_HOME="$XDG_E" \
  HOME="$HOME_E" \
  bash "$PLAN_PATH" z_harness_base)"

# In stage 1, result should be pwd/z-harness.
# Use realpath on both sides to handle macOS /tmp→/private/tmp symlink.
REPO_E_REAL="$(_realpath "$REPO_E")"
EXPECTED_E="$REPO_E_REAL/z-harness"
RESULT_E_REAL="$(_realpath "$(dirname "$RESULT_E")")/$(basename "$RESULT_E")"

assert_eq "T001-E: z_harness_base returns pwd/z-harness in stage 1 (EXTERNAL_DEFAULT unset)" \
  "$EXPECTED_E" "$RESULT_E_REAL"

rm -rf "$REPO_E" "$XDG_E" "$HOME_E"

# ---------------------------------------------------------------------------
# TEST T001-F: EXTERNAL_DEFAULT=0 → effective base = pwd/z-harness regardless of XDG/HOME
# ---------------------------------------------------------------------------
echo ""
echo "T001-F: EXTERNAL_DEFAULT=0 → effective base = pwd/z-harness"

REPO_F="$(_tmpdir)"
git -C "$REPO_F" init -q
git -C "$REPO_F" config user.email "test@test.local"
git -C "$REPO_F" config user.name "Test"

XDG_F="$(_tmpdir)"
HOME_F="$(_tmpdir)"

RESULT_F="$(cd "$REPO_F" && \
  XDG_STATE_HOME="$XDG_F" \
  HOME="$HOME_F" \
  Z_HARNESS_EXTERNAL_DEFAULT=0 \
  bash "$PLAN_PATH" z_harness_base)"

# Should NOT be under XDG (tier 2 or 3), but should end in z-harness
assert_contains "T001-F: EXTERNAL_DEFAULT=0 gives z-harness suffix" "z-harness" "$RESULT_F"

# Verify it does NOT contain XDG path
if printf '%s' "$RESULT_F" | grep -qF "$XDG_F"; then
  echo "  FAIL: T001-F: result should not be under XDG path when EXTERNAL_DEFAULT=0"
  echo "        result: $RESULT_F"
  echo "        XDG:    $XDG_F"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-F: result is not under XDG when EXTERNAL_DEFAULT=0"
  PASS=$((PASS + 1))
fi

rm -rf "$REPO_F" "$XDG_F" "$HOME_F"

# ---------------------------------------------------------------------------
# TEST T001-G: Anchor written on first call; second call same path → no mismatch
# ---------------------------------------------------------------------------
echo ""
echo "T001-G: anchor written on first call; second call same path → no mismatch"

REPO_G="$(_tmpdir)"
git -C "$REPO_G" init -q
git -C "$REPO_G" config user.email "test@test.local"
git -C "$REPO_G" config user.name "Test"

# First call
RESULT_G1="$(cd "$REPO_G" && bash "$PLAN_PATH" z_harness_base)"

# Check anchor was written (handle macOS /tmp→/private/tmp)
ANCHOR_G="$(_realpath "$REPO_G")/.git/.z-harness-base"
if [[ -f "$ANCHOR_G" ]]; then
  echo "  PASS: T001-G: anchor file created on first call"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-G: anchor file NOT created at $ANCHOR_G"
  FAIL=$((FAIL + 1))
fi

# Second call — must succeed (same path)
EXIT_G2=0
RESULT_G2="$(cd "$REPO_G" && bash "$PLAN_PATH" z_harness_base)" || EXIT_G2=$?
assert_eq "T001-G: second call returns same base path" "$RESULT_G1" "$RESULT_G2"
assert_eq "T001-G: second call succeeds (exit 0)" "0" "$EXIT_G2"

rm -rf "$REPO_G"

# ---------------------------------------------------------------------------
# TEST T001-H: Anchor mismatch → hard-fail (non-zero exit)
# ---------------------------------------------------------------------------
echo ""
echo "T001-H: anchor mismatch → hard-fail"

REPO_H="$(_tmpdir)"
git -C "$REPO_H" init -q
git -C "$REPO_H" config user.email "test@test.local"
git -C "$REPO_H" config user.name "Test"

ANCHOR_H="$(_realpath "$REPO_H")/.git/.z-harness-base"

# Write anchor manually with a different path
python3 -c '
import json, sys
anchor = sys.argv[1]
json.dump({"tier":"pwd","path":"/some/totally/different/path","repo_id":"fake-id"}, open(anchor,"w"))
' "$ANCHOR_H"

# Now call z_harness_base — should fail because anchor path != resolved path
EXIT_H=0
ERR_H="$(cd "$REPO_H" && bash "$PLAN_PATH" z_harness_base 2>&1)" || EXIT_H=$?

assert_exit_nonzero "T001-H: anchor mismatch causes non-zero exit" "$EXIT_H"
assert_contains "T001-H: stderr mentions mismatch" "mismatch" "$ERR_H"

rm -rf "$REPO_H"

# ---------------------------------------------------------------------------
# TEST T001-I: dual-read: resolve_plan_path finds z-harness/plans/<slug> (secondary legacy)
# Purpose: when a plan exists at the in-repo z-harness/plans/<slug> path but NOT
# at the external base, resolve_plan_path falls back to the secondary legacy path.
# ---------------------------------------------------------------------------
echo ""
echo "T001-I: dual-read finds z-harness/plans/<slug> (secondary legacy)"

REPO_I="$(_tmpdir)"
git -C "$REPO_I" init -q
git -C "$REPO_I" config user.email "test@test.local"
git -C "$REPO_I" config user.name "Test"

SLUG_I="my-slug-i"
# Create ONLY the in-repo secondary legacy path (not the external new path)
mkdir -p "$REPO_I/z-harness/plans/$SLUG_I"

EXTERNAL_I="$(_tmpdir)"

# Use external base so plan_dir → external (not found), then falls back to in-repo
RESULT_I="$(cd "$REPO_I" && Z_HARNESS_BASE_DIR="$EXTERNAL_I" bash "$PLAN_PATH" resolve_plan_path "$SLUG_I" 2>/dev/null)"
EXPECTED_I="z-harness/plans/$SLUG_I"

assert_eq "T001-I: resolve_plan_path returns secondary legacy z-harness/plans/<slug>" "$EXPECTED_I" "$RESULT_I"

rm -rf "$REPO_I" "$EXTERNAL_I"

# ---------------------------------------------------------------------------
# TEST T001-J: dual-read: resolve_plan_path finds z-harness/<slug> (primary legacy flat)
# ---------------------------------------------------------------------------
echo ""
echo "T001-J: dual-read finds z-harness/<slug> (primary legacy flat)"

REPO_J="$(_tmpdir)"
git -C "$REPO_J" init -q
git -C "$REPO_J" config user.email "test@test.local"
git -C "$REPO_J" config user.name "Test"

SLUG_J="my-slug-j"
# Create only the flat legacy path (no in-repo plans/ and no external new path)
mkdir -p "$REPO_J/z-harness/$SLUG_J"

EXTERNAL_J="$(_tmpdir)"

# Use external base so plan_dir → external (not found), then no secondary legacy,
# then falls back to primary legacy flat.
RESULT_J="$(cd "$REPO_J" && Z_HARNESS_BASE_DIR="$EXTERNAL_J" bash "$PLAN_PATH" resolve_plan_path "$SLUG_J" 2>/dev/null)"
EXPECTED_J="z-harness/$SLUG_J"

assert_eq "T001-J: resolve_plan_path returns z-harness/<slug> (flat legacy)" "$EXPECTED_J" "$RESULT_J"

rm -rf "$REPO_J" "$EXTERNAL_J"

# ---------------------------------------------------------------------------
# TEST T001-K: dual-read: new path (under z_harness_base) takes priority over legacy
# ---------------------------------------------------------------------------
echo ""
echo "T001-K: new path (under z_harness_base) takes priority over both legacy paths"

REPO_K="$(_tmpdir)"
git -C "$REPO_K" init -q
git -C "$REPO_K" config user.email "test@test.local"
git -C "$REPO_K" config user.name "Test"

SLUG_K="my-slug-k"
BASE_K="$(_tmpdir)"

# Create BOTH legacy paths and the new external path
mkdir -p "$REPO_K/z-harness/$SLUG_K"
mkdir -p "$REPO_K/z-harness/plans/$SLUG_K"
EXPECTED_K="$BASE_K/plans/$SLUG_K"
mkdir -p "$EXPECTED_K"

RESULT_K="$(cd "$REPO_K" && Z_HARNESS_BASE_DIR="$BASE_K" bash "$PLAN_PATH" resolve_plan_path "$SLUG_K")"

assert_eq "T001-K: new external path wins over legacy" "$EXPECTED_K" "$RESULT_K"

rm -rf "$REPO_K" "$BASE_K"

# ---------------------------------------------------------------------------
# TEST T001-L: PLANS_DIR relative + BASE_DIR set → exit 1 (guard preserved)
# ---------------------------------------------------------------------------
echo ""
echo "T001-L: PLANS_DIR relative + BASE_DIR set → exit 1"

EXIT_L=0
Z_HARNESS_BASE_DIR="/tmp/zh-l-$$" Z_HARNESS_PLANS_DIR="relative/plans" \
  bash "$PLAN_PATH" plan_dir "my-slug" 2>/dev/null || EXIT_L=$?

assert_exit_nonzero "T001-L: relative PLANS_DIR + BASE_DIR causes exit 1" "$EXIT_L"

ERR_L="$(Z_HARNESS_BASE_DIR="/tmp/zh-l-$$" Z_HARNESS_PLANS_DIR="relative/plans" \
  bash "$PLAN_PATH" plan_dir "my-slug" 2>&1 || true)"
assert_contains "T001-L: error message mentions absolute path" "absolute" "$ERR_L"

# ---------------------------------------------------------------------------
# TEST T001-M: active_plans_dir() returns <base>/active-plans
# Use a hermetic repo to avoid anchor conflicts between tests.
# ---------------------------------------------------------------------------
echo ""
echo "T001-M: active_plans_dir() returns <base>/active-plans"

REPO_M="$(_tmpdir)"
git -C "$REPO_M" init -q
git -C "$REPO_M" config user.email "test@test.local"
git -C "$REPO_M" config user.name "Test"
BASE_M="$(_tmpdir)"

RESULT_M="$(cd "$REPO_M" && Z_HARNESS_BASE_DIR="$BASE_M" bash "$PLAN_PATH" active_plans_dir)"
EXPECTED_M="$BASE_M/active-plans"

assert_eq "T001-M: active_plans_dir returns <base>/active-plans" "$EXPECTED_M" "$RESULT_M"

rm -rf "$REPO_M" "$BASE_M"

# ---------------------------------------------------------------------------
# TEST T001-N: followups_dir() returns <base>/followups
# ---------------------------------------------------------------------------
echo ""
echo "T001-N: followups_dir() returns <base>/followups"

REPO_N="$(_tmpdir)"
git -C "$REPO_N" init -q
git -C "$REPO_N" config user.email "test@test.local"
git -C "$REPO_N" config user.name "Test"
BASE_N="$(_tmpdir)"

RESULT_N="$(cd "$REPO_N" && Z_HARNESS_BASE_DIR="$BASE_N" bash "$PLAN_PATH" followups_dir)"
EXPECTED_N="$BASE_N/followups"

assert_eq "T001-N: followups_dir returns <base>/followups" "$EXPECTED_N" "$RESULT_N"

rm -rf "$REPO_N" "$BASE_N"

# ---------------------------------------------------------------------------
# TEST T001-O: base_dir() returns same result as z_harness_base
# ---------------------------------------------------------------------------
echo ""
echo "T001-O: base_dir() returns same result as z_harness_base"

REPO_O="$(_tmpdir)"
git -C "$REPO_O" init -q
git -C "$REPO_O" config user.email "test@test.local"
git -C "$REPO_O" config user.name "Test"
BASE_O="$(_tmpdir)"

RESULT_O_BASE="$(cd "$REPO_O" && Z_HARNESS_BASE_DIR="$BASE_O" bash "$PLAN_PATH" z_harness_base)"
RESULT_O_DIR="$(cd "$REPO_O" && Z_HARNESS_BASE_DIR="$BASE_O" bash "$PLAN_PATH" base_dir)"

assert_eq "T001-O: base_dir() == z_harness_base()" "$RESULT_O_BASE" "$RESULT_O_DIR"

rm -rf "$REPO_O" "$BASE_O"

# ---------------------------------------------------------------------------
# TEST T001-P: all external tiers unwritable → FATAL exit (EXTERNAL_DEFAULT=1 forced)
# We cannot make the git-common-dir unwritable on macOS without root, so we test
# the XDG/HOME tiers are skipped when unwritable, leaving git-common-dir writable.
# The FATAL case is best verified by pointing XDG/HOME to unwritable paths —
# if git-common-dir is also unwritable, we get FATAL; if writable, tier 4 is used.
# ---------------------------------------------------------------------------
echo ""
echo "T001-P: unwritable tiers fall through gracefully to first writable tier"

REPO_P="$(_tmpdir)"
git -C "$REPO_P" init -q
git -C "$REPO_P" config user.email "test@test.local"
git -C "$REPO_P" config user.name "Test"

NOWRITE_P="$(_tmpdir)"
chmod 555 "$NOWRITE_P"

EXIT_P=0
RESULT_P="$(cd "$REPO_P" && \
  XDG_STATE_HOME="$NOWRITE_P/xdg" \
  HOME="$NOWRITE_P/home" \
  Z_HARNESS_EXTERNAL_DEFAULT=1 \
  bash "$PLAN_PATH" z_harness_base 2>/dev/null)" || EXIT_P=$?

if [[ $EXIT_P -eq 0 ]]; then
  # Tier 4 (git-common-dir) was writable — result should end in .git/z-harness
  assert_contains "T001-P: falls through to git-common-dir tier when XDG/HOME unwritable" \
    ".git/z-harness" "$RESULT_P"
else
  # All tiers unwritable — expected FATAL
  echo "  PASS: T001-P: FATAL exit when all tiers unwritable (exit $EXIT_P)"
  PASS=$((PASS + 1))
fi

chmod 755 "$NOWRITE_P"
rm -rf "$REPO_P" "$NOWRITE_P"

# ---------------------------------------------------------------------------
# TEST T001-Q: portable-hash repo-id yields an 8-hex suffix (stable on this platform)
# The sha256sum/shasum fallback must produce a consistent hex string regardless of
# which tool is available. We verify the suffix is exactly 8 hex characters.
# ---------------------------------------------------------------------------
echo ""
echo "T001-Q: portable hash produces stable 8-hex suffix"

REPO_Q="$(_tmpdir)"
git -C "$REPO_Q" init -q
git -C "$REPO_Q" config user.email "test@test.local"
git -C "$REPO_Q" config user.name "Test"

REPOID_Q="$(run_in_repo "$REPO_Q" z_harness_repo_id)"

# Must match: <word>-<8hex> where 8hex is exactly [0-9a-f]{8}
if printf '%s' "$REPOID_Q" | grep -qE '^[^-]+-[0-9a-f]{8}$'; then
  echo "  PASS: T001-Q: repo-id matches <basename>-<8hex> format: $REPOID_Q"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-Q: repo-id does not match expected format: $REPOID_Q"
  FAIL=$((FAIL + 1))
fi

# Call twice — must be identical (stability)
REPOID_Q2="$(run_in_repo "$REPO_Q" z_harness_repo_id)"
assert_eq "T001-Q: repo-id is stable across two calls" "$REPOID_Q" "$REPOID_Q2"

rm -rf "$REPO_Q"

# ---------------------------------------------------------------------------
# TEST T001-R: tier-1 (Z_HARNESS_BASE_DIR set) is a TRUE ESCAPE HATCH — it
# bypasses the anchor entirely. A conflicting pre-existing anchor must NOT
# cause a hard-fail; tier-1 must succeed and return Z_HARNESS_BASE_DIR
# verbatim without modifying the anchor.
# ---------------------------------------------------------------------------
echo ""
echo "T001-R: tier-1 with conflicting anchor succeeds (escape hatch — anchor ignored)"

REPO_R="$(_tmpdir)"
git -C "$REPO_R" init -q
git -C "$REPO_R" config user.email "test@test.local"
git -C "$REPO_R" config user.name "Test"

ANCHOR_R="$(_realpath "$REPO_R")/.git/.z-harness-base"
ANCHOR_ORIGINAL_PATH="/some/other/path/from/anchor"

# Write an anchor whose path differs from our tier-1 BASE_DIR
python3 -c '
import json, sys
anchor = sys.argv[1]
json.dump({"tier":"pwd","path":"/some/other/path/from/anchor","repo_id":"fake-id"}, open(anchor,"w"))
' "$ANCHOR_R"

BASE_R="/tmp/zh-tier1-test-$$"
EXIT_R=0
RESULT_R="$(cd "$REPO_R" && Z_HARNESS_BASE_DIR="$BASE_R" bash "$PLAN_PATH" z_harness_base 2>&1)" || EXIT_R=$?

assert_eq "T001-R: tier-1 with conflicting anchor exits zero (escape hatch)" "0" "$EXIT_R"
assert_eq "T001-R: tier-1 returns Z_HARNESS_BASE_DIR verbatim" "$BASE_R" "$RESULT_R"

# Anchor must NOT have been modified (original path still stored)
STORED_R="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("path",""))' "$ANCHOR_R" 2>/dev/null || true)"
assert_eq "T001-R: anchor not modified by tier-1 (escape hatch does not write anchor)" \
  "$ANCHOR_ORIGINAL_PATH" "$STORED_R"

rm -rf "$REPO_R"

# ---------------------------------------------------------------------------
# TEST T001-S: tier-1 with no existing anchor does NOT create an anchor file.
# The validate-but-don't-write behavior must hold.
# ---------------------------------------------------------------------------
echo ""
echo "T001-S: tier-1 with no existing anchor does not create one"

REPO_S="$(_tmpdir)"
git -C "$REPO_S" init -q
git -C "$REPO_S" config user.email "test@test.local"
git -C "$REPO_S" config user.name "Test"

ANCHOR_S="$(_realpath "$REPO_S")/.git/.z-harness-base"
BASE_S="/tmp/zh-tier1-noanchor-$$"

# Confirm anchor does not exist before the call
if [[ -f "$ANCHOR_S" ]]; then
  echo "  FAIL: T001-S: anchor unexpectedly pre-exists at $ANCHOR_S"
  FAIL=$((FAIL + 1))
fi

# Call tier-1
RESULT_S="$(cd "$REPO_S" && Z_HARNESS_BASE_DIR="$BASE_S" bash "$PLAN_PATH" z_harness_base)"

assert_eq "T001-S: tier-1 returns Z_HARNESS_BASE_DIR verbatim" "$BASE_S" "$RESULT_S"

# Anchor must NOT have been written
if [[ -f "$ANCHOR_S" ]]; then
  echo "  FAIL: T001-S: anchor was written by tier-1 but should not be"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-S: tier-1 did not create an anchor file"
  PASS=$((PASS + 1))
fi

rm -rf "$REPO_S"

# ---------------------------------------------------------------------------
# TEST T001-T: stage-1 shadow probe (EXTERNAL_DEFAULT unset) leaves no stray
# directories under XDG_STATE_HOME or HOME when those tiers are not selected.
# ---------------------------------------------------------------------------
echo ""
echo "T001-T: stage-1 probe leaves no stray tier dirs under XDG/HOME"

REPO_T="$(_tmpdir)"
git -C "$REPO_T" init -q
git -C "$REPO_T" config user.email "test@test.local"
git -C "$REPO_T" config user.name "Test"

XDG_T="$(_tmpdir)"
HOME_T="$(_tmpdir)"

# Run in stage 1 (EXTERNAL_DEFAULT not set) with XDG and HOME pointing at
# writable temp dirs. The shadow probe runs tiers 2-3 for diagnostics but
# the effective tier is 5 (pwd). No stray dirs must be left behind.
RESULT_T="$(cd "$REPO_T" && \
  XDG_STATE_HOME="$XDG_T" \
  HOME="$HOME_T" \
  bash "$PLAN_PATH" z_harness_base)"

# Tier 2 (XDG) path would be: $XDG_T/z-harness/
XDG_STRAY="$XDG_T/z-harness"
# Tier 3 (HOME) path would be: $HOME_T/.local/state/z-harness/
HOME_STRAY="$HOME_T/.local"

if [[ -d "$XDG_STRAY" ]]; then
  echo "  FAIL: T001-T: stray directory left behind under XDG: $XDG_STRAY"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-T: no stray dir under XDG after stage-1 probe"
  PASS=$((PASS + 1))
fi

if [[ -d "$HOME_STRAY" ]]; then
  echo "  FAIL: T001-T: stray directory left behind under HOME: $HOME_STRAY"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-T: no stray dir under HOME after stage-1 probe"
  PASS=$((PASS + 1))
fi

# The result must be pwd/z-harness (tier 5)
REPO_T_REAL="$(_realpath "$REPO_T")"
EXPECTED_T="$REPO_T_REAL/z-harness"
RESULT_T_REAL="$(_realpath "$(dirname "$RESULT_T")")/$(basename "$RESULT_T")"
assert_eq "T001-T: effective base is pwd/z-harness (tier 5) in stage 1" "$EXPECTED_T" "$RESULT_T_REAL"

rm -rf "$REPO_T" "$XDG_T" "$HOME_T"

# ---------------------------------------------------------------------------
# TEST T001-U: z_harness_repo_id fails hard when neither sha256sum nor shasum
# is available (both hashers missing → empty hex8 → FATAL, non-zero exit).
#
# Technique: run z_harness_repo_id with PATH overridden to an empty sentinel
# directory so neither sha256sum nor shasum can be found. We must preserve
# enough of PATH for git and bash to work, so we put only those two binaries
# in the fake PATH directory via symlinks.
# ---------------------------------------------------------------------------
echo ""
echo "T001-U: z_harness_repo_id fails hard when no sha256 utility is available"

REPO_U="$(_tmpdir)"
git -C "$REPO_U" init -q
git -C "$REPO_U" config user.email "test@test.local"
git -C "$REPO_U" config user.name "Test"

# Build a fake PATH bin dir that has git and bash but NOT sha256sum or shasum.
FAKE_BIN_U="$(_tmpdir)"
# Symlink only git and bash (needed for the subshell to function).
GIT_BIN="$(command -v git 2>/dev/null || true)"
BASH_BIN="$(command -v bash 2>/dev/null || true)"
if [[ -n "$GIT_BIN" ]]; then
  ln -s "$GIT_BIN" "$FAKE_BIN_U/git"
fi
if [[ -n "$BASH_BIN" ]]; then
  ln -s "$BASH_BIN" "$FAKE_BIN_U/bash"
fi
# Also symlink realpath and dirname/basename/pwd so the function can resolve paths.
for BIN in realpath dirname basename pwd mktemp; do
  BIN_PATH="$(command -v "$BIN" 2>/dev/null || true)"
  if [[ -n "$BIN_PATH" ]]; then
    ln -s "$BIN_PATH" "$FAKE_BIN_U/$BIN" 2>/dev/null || true
  fi
done

EXIT_U=0
ERR_U="$(cd "$REPO_U" && PATH="$FAKE_BIN_U" bash "$PLAN_PATH" z_harness_repo_id 2>&1)" || EXIT_U=$?

assert_exit_nonzero "T001-U: z_harness_repo_id exits non-zero when no sha256 utility" "$EXIT_U"
assert_contains "T001-U: stderr mentions missing sha256 utility" "sha256" "$ERR_U"

rm -rf "$REPO_U" "$FAKE_BIN_U"

# ---------------------------------------------------------------------------
# TEST T001-V: all_plan_slugs() returns slugs from BOTH layouts and excludes infra dirs
# Creates a hermetic temp repo with:
#   - New layout:    <base>/plans/new-slug/
#   - Legacy flat:   <base>/legacy-slug/
#   - Infra dirs:    <base>/plans/, <base>/archive/, <base>/adhoc/, <base>/followups/
#   - Infra file:    <base>/metrics.jsonl
# Asserts:
#   - Output includes "new-slug" (new layout)
#   - Output includes "legacy-slug" (legacy flat layout)
#   - Output does NOT include any infra name: plans, archive, adhoc, followups, metrics.jsonl
# ---------------------------------------------------------------------------
echo ""
echo "T001-V: all_plan_slugs() includes both layouts and excludes infra dirs"

REPO_V="$(_tmpdir)"
git -C "$REPO_V" init -q
git -C "$REPO_V" config user.email "test@test.local"
git -C "$REPO_V" config user.name "Test"

BASE_V="$(_tmpdir)"

# New layout: <base>/plans/new-slug/
mkdir -p "$BASE_V/plans/new-slug"

# Legacy flat: <base>/legacy-slug/
mkdir -p "$BASE_V/legacy-slug"

# Infrastructure directories (must be excluded)
mkdir -p "$BASE_V/archive"
mkdir -p "$BASE_V/adhoc"
mkdir -p "$BASE_V/followups"
mkdir -p "$BASE_V/improvements"
mkdir -p "$BASE_V/active-plans"
mkdir -p "$BASE_V/bench"

# Infrastructure file (must be excluded)
touch "$BASE_V/metrics.jsonl"

SLUGS_V="$(cd "$REPO_V" && Z_HARNESS_BASE_DIR="$BASE_V" bash "$PLAN_PATH" all_plan_slugs)"

# Must include new-slug
if printf '%s\n' "$SLUGS_V" | grep -qxF "new-slug"; then
  echo "  PASS: T001-V: new-slug (new layout) appears in all_plan_slugs output"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-V: new-slug missing from all_plan_slugs output"
  echo "        got: $SLUGS_V"
  FAIL=$((FAIL + 1))
fi

# Must include legacy-slug
if printf '%s\n' "$SLUGS_V" | grep -qxF "legacy-slug"; then
  echo "  PASS: T001-V: legacy-slug (legacy flat layout) appears in all_plan_slugs output"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-V: legacy-slug missing from all_plan_slugs output"
  echo "        got: $SLUGS_V"
  FAIL=$((FAIL + 1))
fi

# Must NOT include infra dirs/files
for INFRA_NAME in plans archive adhoc followups improvements active-plans metrics.jsonl bench; do
  if printf '%s\n' "$SLUGS_V" | grep -qxF "$INFRA_NAME"; then
    echo "  FAIL: T001-V: infra name '$INFRA_NAME' must not appear in all_plan_slugs output"
    echo "        got: $SLUGS_V"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: T001-V: infra name '$INFRA_NAME' correctly excluded"
    PASS=$((PASS + 1))
  fi
done

# No duplicates: each slug appears exactly once
NEW_SLUG_COUNT="$(printf '%s\n' "$SLUGS_V" | grep -cxF "new-slug" || true)"
LEGACY_SLUG_COUNT="$(printf '%s\n' "$SLUGS_V" | grep -cxF "legacy-slug" || true)"
assert_eq "T001-V: new-slug appears exactly once (deduplication)" "1" "$NEW_SLUG_COUNT"
assert_eq "T001-V: legacy-slug appears exactly once (deduplication)" "1" "$LEGACY_SLUG_COUNT"

rm -rf "$REPO_V" "$BASE_V"

# ---------------------------------------------------------------------------
# TEST T001-W: mismatch-anchor → all_plan_slugs exits non-zero with EMPTY stdout
# Regression for the fatal base-mismatch propagation bug:
#   When z_harness_base() detects a base_mismatch and exits 1 inside $(),
#   all_plan_slugs must NOT compose paths with an empty base (which would
#   glob "/" and list filesystem root like Applications, Library, System, Users).
# ---------------------------------------------------------------------------
echo ""
echo "T001-W: mismatch-anchor → all_plan_slugs exits non-zero with empty stdout (no root glob)"

REPO_W="$(_tmpdir)"
git -C "$REPO_W" init -q
git -C "$REPO_W" config user.email "test@test.local"
git -C "$REPO_W" config user.name "Test"

# Plant a conflicting anchor at the repo's .git dir
ANCHOR_W="$(_realpath "$REPO_W")/.git/.z-harness-base"
python3 -c '
import json, sys
json.dump({"tier":"pwd","path":"/some/totally/different/path","repo_id":"fake-id"}, open(sys.argv[1],"w"))
' "$ANCHOR_W"

SLUGS_W=""
EXIT_W=0
SLUGS_W="$(cd "$REPO_W" && bash "$PLAN_PATH" all_plan_slugs 2>/dev/null)" || EXIT_W=$?

assert_exit_nonzero "T001-W: mismatch-anchor all_plan_slugs exits non-zero" "$EXIT_W"

# Stdout must be completely empty
if [[ -z "$SLUGS_W" ]]; then
  echo "  PASS: T001-W: all_plan_slugs stdout is empty on mismatch"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-W: all_plan_slugs stdout must be empty on mismatch"
  echo "        got: $SLUGS_W"
  FAIL=$((FAIL + 1))
fi

# Must NOT contain any filesystem root entries
for ROOT_ENTRY in "Applications" "Library" "System" "Users" "Volumes" "bin" "usr" "etc"; do
  if printf '%s\n' "$SLUGS_W" | grep -qxF "$ROOT_ENTRY"; then
    echo "  FAIL: T001-W: stdout must not contain filesystem root entry '$ROOT_ENTRY'"
    echo "        got: $SLUGS_W"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: T001-W: stdout does not contain '$ROOT_ENTRY'"
    PASS=$((PASS + 1))
  fi
done

rm -rf "$REPO_W"

# ---------------------------------------------------------------------------
# TEST T001-X: mismatch-anchor → active_plans_dir / followups_dir / base_dir
# Each must exit non-zero and NOT print a bare path like "/active-plans" or "/followups"
# (i.e. empty-base composition must be blocked).
# ---------------------------------------------------------------------------
echo ""
echo "T001-X: mismatch-anchor → active_plans_dir / followups_dir / base_dir exit non-zero, no empty-base paths"

REPO_X="$(_tmpdir)"
git -C "$REPO_X" init -q
git -C "$REPO_X" config user.email "test@test.local"
git -C "$REPO_X" config user.name "Test"

ANCHOR_X="$(_realpath "$REPO_X")/.git/.z-harness-base"
python3 -c '
import json, sys
json.dump({"tier":"pwd","path":"/some/totally/different/path","repo_id":"fake-id"}, open(sys.argv[1],"w"))
' "$ANCHOR_X"

# active_plans_dir
EXIT_X_APD=0
OUT_X_APD=""
OUT_X_APD="$(cd "$REPO_X" && bash "$PLAN_PATH" active_plans_dir 2>/dev/null)" || EXIT_X_APD=$?
assert_exit_nonzero "T001-X: mismatch-anchor active_plans_dir exits non-zero" "$EXIT_X_APD"
if printf '%s' "$OUT_X_APD" | grep -qE '^/active-plans'; then
  echo "  FAIL: T001-X: active_plans_dir must not print bare /active-plans path"
  echo "        got: $OUT_X_APD"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-X: active_plans_dir does not print bare /active-plans path"
  PASS=$((PASS + 1))
fi

# followups_dir
EXIT_X_FD=0
OUT_X_FD=""
OUT_X_FD="$(cd "$REPO_X" && bash "$PLAN_PATH" followups_dir 2>/dev/null)" || EXIT_X_FD=$?
assert_exit_nonzero "T001-X: mismatch-anchor followups_dir exits non-zero" "$EXIT_X_FD"
if printf '%s' "$OUT_X_FD" | grep -qE '^/followups'; then
  echo "  FAIL: T001-X: followups_dir must not print bare /followups path"
  echo "        got: $OUT_X_FD"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T001-X: followups_dir does not print bare /followups path"
  PASS=$((PASS + 1))
fi

# base_dir
EXIT_X_BD=0
OUT_X_BD=""
OUT_X_BD="$(cd "$REPO_X" && bash "$PLAN_PATH" base_dir 2>/dev/null)" || EXIT_X_BD=$?
assert_exit_nonzero "T001-X: mismatch-anchor base_dir exits non-zero" "$EXIT_X_BD"

rm -rf "$REPO_X"

# ---------------------------------------------------------------------------
# TEST T001-Y: happy-path regression — all_plan_slugs returns correct slugs
# when there is no base mismatch (verifies the fix didn't break normal operation).
# ---------------------------------------------------------------------------
echo ""
echo "T001-Y: happy-path regression — all_plan_slugs returns correct slugs (no mismatch)"

REPO_Y="$(_tmpdir)"
git -C "$REPO_Y" init -q
git -C "$REPO_Y" config user.email "test@test.local"
git -C "$REPO_Y" config user.name "Test"

BASE_Y="$(_tmpdir)"

# Create both new-layout and legacy-flat slugs
mkdir -p "$BASE_Y/plans/new-happy-slug"
mkdir -p "$BASE_Y/old-happy-slug"

SLUGS_Y=""
EXIT_Y=0
SLUGS_Y="$(cd "$REPO_Y" && Z_HARNESS_BASE_DIR="$BASE_Y" bash "$PLAN_PATH" all_plan_slugs)" || EXIT_Y=0

assert_eq "T001-Y: happy-path all_plan_slugs exits zero" "0" "$EXIT_Y"

if printf '%s\n' "$SLUGS_Y" | grep -qxF "new-happy-slug"; then
  echo "  PASS: T001-Y: new-happy-slug (new layout) appears in all_plan_slugs"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-Y: new-happy-slug missing from all_plan_slugs"
  echo "        got: $SLUGS_Y"
  FAIL=$((FAIL + 1))
fi

if printf '%s\n' "$SLUGS_Y" | grep -qxF "old-happy-slug"; then
  echo "  PASS: T001-Y: old-happy-slug (legacy flat) appears in all_plan_slugs"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T001-Y: old-happy-slug missing from all_plan_slugs"
  echo "        got: $SLUGS_Y"
  FAIL=$((FAIL + 1))
fi

rm -rf "$REPO_Y" "$BASE_Y"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
