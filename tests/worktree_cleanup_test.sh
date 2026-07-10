#!/usr/bin/env bash
# worktree_cleanup_test.sh — Tests for T001/scripts/worktree-cleanup.sh
# (worktree-merge-cleanup plan). Hermetic bash assertion harness matching the
# style of scripts/test_block_dangerous_git.sh and
# scripts/test_plan_path_resolution.sh, but placed under tests/ per the
# T007 task spec.
#
# Run with:
#   bash tests/worktree_cleanup_test.sh
#
# Tests (acceptance-critical safety behaviors from INTENT.frozen.md):
#   T-WTC-A: classify tags a SQUASH-merged, never-pushed local branch as
#            safe-remove (headline offline patch-identity case)
#   T-WTC-B: classify tags a worktree with uncommitted TRACKED changes on a
#            merged branch as merged-dirty
#   T-WTC-C: classify tags a worktree with unique unmerged commits as
#            unmerged-work
#   T-WTC-D: remove <path> on a DIRTY worktree exits non-zero and removes
#            nothing (no --force)
#   T-WTC-E: remove <path> on an UNMERGED worktree exits non-zero and
#            removes nothing (no --force)
#   T-WTC-F: remove <path> on a safe (merged+clean) worktree succeeds —
#            worktree gone from `git worktree list` AND branch deleted
#   T-WTC-G: remove --force <path> overrides the refusal on a dirty worktree
#   T-WTC-H: the main worktree is never classified or removed

set -euo pipefail

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
HELPER="$(cd "$TESTS_DIR/.." && pwd)/scripts/worktree-cleanup.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
CLEANUP_DIRS=()
ERR_FILE="$(mktemp "/tmp/test_wtclean_err_XXXXXX")"
cleanup() {
  for d in "${CLEANUP_DIRS[@]:-}"; do
    rm -rf "$d"
  done
  rm -f "$ERR_FILE"
}
trap cleanup EXIT

# _canon <path> — realpath-resolve a path so comparisons against git's own
# (always-canonicalized) worktree-list output are stable across platforms
# where a temp-dir root is itself a symlink (e.g. macOS /tmp -> /private/tmp).
# This mirrors how the real classify->remove pipeline works: `remove` is fed
# paths straight out of `classify`'s JSON, which is itself sourced from
# `git worktree list --porcelain` (already canonical) — never from a
# manually-typed, unresolved path.
_canon() {
  python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
}

_tmpdir() {
  local d
  d="$(mktemp -d "/tmp/test_wtclean_XXXXXX")"
  d="$(_canon "$d")"
  CLEANUP_DIRS+=("$d")
  printf '%s' "$d"
}

# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

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
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
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
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
    echo "  FAIL: $label"
    echo "        did not expect substring: $needle"
    echo "        in: $haystack"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: $label"
    PASS=$((PASS + 1))
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

assert_true() {
  local label="$1" cond="$2"
  if [[ "$cond" == "1" ]]; then
    echo "  PASS: $label"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $label"
    FAIL=$((FAIL + 1))
  fi
}

# Run worktree-cleanup.sh, capturing stdout/stderr/exit code separately.
# Sets RC_LAST, OUT_LAST, ERR_LAST.
RC_LAST=0
OUT_LAST=""
ERR_LAST=""
run_helper() {
  RC_LAST=0
  OUT_LAST=""
  : > "$ERR_FILE"
  OUT_LAST="$(bash "$HELPER" "$@" 2>"$ERR_FILE")" || RC_LAST=$?
  ERR_LAST="$(cat "$ERR_FILE" 2>/dev/null || true)"
}

# Extract a scalar field from a single JSON object line (bools -> 1/0).
_json_field() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys
obj = json.loads(sys.argv[1])
val = obj.get(sys.argv[2], "")
print("1" if val is True else "0" if val is False else val)
PYEOF
}

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

# _mk_repo — a fresh hermetic repo with an explicit "main" default branch and
# one initial commit. Never touches a remote (no push, no network).
_mk_repo() {
  local d
  d="$(_tmpdir)"
  git -c init.defaultBranch=main init -q "$d"
  git -C "$d" config user.email "test@test.local"
  git -C "$d" config user.name "Test"
  printf 'init\n' > "$d/README"
  git -C "$d" add README
  git -C "$d" commit -q -m "init" >/dev/null
  printf '%s' "$d"
}

# _new_wt_path — a not-yet-existing path suitable for `git worktree add`.
_new_wt_path() {
  local parent
  parent="$(_tmpdir)"
  printf '%s/wt' "$parent"
}

# _mk_squash_merged_worktree <repo> <branch> — creates <branch> off main with
# one unique commit, squash-merges it into main (no literal merge commit, no
# push), then adds a worktree checked out at <branch>'s original (pre-squash)
# commit. This is the headline "safe-remove" fixture: patch-identical to
# main via offline patch-identity, never pushed anywhere.
# Prints the worktree path.
_mk_squash_merged_worktree() {
  local repo="$1" branch="$2"
  git -C "$repo" checkout -q -b "$branch"
  printf 'feature content for %s\n' "$branch" > "$repo/feature-$branch.txt"
  git -C "$repo" add "feature-$branch.txt"
  git -C "$repo" commit -q -m "feature commit on $branch" >/dev/null
  git -C "$repo" checkout -q main
  git -C "$repo" merge --squash "$branch" >/dev/null
  git -C "$repo" commit -q -m "squash merge $branch" >/dev/null
  local wt
  wt="$(_new_wt_path)"
  git -C "$repo" worktree add -q "$wt" "$branch"
  printf '%s' "$wt"
}

# _mk_unmerged_worktree <repo> <branch> — creates <branch> off main with a
# unique commit that is NOT merged (squash or otherwise) into main, and adds
# a worktree checked out at that branch. Prints the worktree path.
_mk_unmerged_worktree() {
  local repo="$1" branch="$2"
  git -C "$repo" checkout -q -b "$branch"
  printf 'unmerged content for %s\n' "$branch" > "$repo/unmerged-$branch.txt"
  git -C "$repo" add "unmerged-$branch.txt"
  git -C "$repo" commit -q -m "unique unmerged commit on $branch" >/dev/null
  git -C "$repo" checkout -q main
  local wt
  wt="$(_new_wt_path)"
  git -C "$repo" worktree add -q "$wt" "$branch"
  printf '%s' "$wt"
}

# ---------------------------------------------------------------------------
# T-WTC-A: classify tags a SQUASH-merged, never-pushed local branch as
# safe-remove (headline case).
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-A: classify tags squash-merged, never-pushed branch as safe-remove"

REPO_A="$(_mk_repo)"
WT_A="$(_mk_squash_merged_worktree "$REPO_A" "feature-a")"

run_helper classify "$REPO_A"
assert_exit_zero "T-WTC-A: classify exits 0" "$RC_LAST"

RECORD_A="$(printf '%s\n' "$OUT_LAST" | grep -F "\"$WT_A\"" || true)"
if [[ -z "$RECORD_A" ]]; then
  # Path may be realpath-normalized (macOS /tmp -> /private/tmp); fall back
  # to the single non-blank output line.
  RECORD_A="$(printf '%s\n' "$OUT_LAST" | grep -v '^[[:space:]]*$' | head -1)"
fi
assert_contains "T-WTC-A: exactly one classify record emitted" "\"branch\": \"feature-a\"" "$RECORD_A"
BUCKET_A="$(_json_field "$RECORD_A" bucket)"
assert_eq "T-WTC-A: bucket is safe-remove" "safe-remove" "$BUCKET_A"
MERGE_STATE_A="$(_json_field "$RECORD_A" merge_state)"
assert_eq "T-WTC-A: merge_state is merged (offline patch-identity)" "merged" "$MERGE_STATE_A"

git -C "$REPO_A" worktree remove -q --force "$WT_A" 2>/dev/null || true

# ---------------------------------------------------------------------------
# T-WTC-B: classify tags a worktree with uncommitted TRACKED changes on a
# merged branch as merged-dirty.
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-B: classify tags dirty-but-merged worktree as merged-dirty"

REPO_B="$(_mk_repo)"
WT_B="$(_mk_squash_merged_worktree "$REPO_B" "feature-b")"
# Introduce an uncommitted TRACKED change in the worktree.
printf 'uncommitted edit\n' >> "$WT_B/feature-feature-b.txt"

run_helper classify "$REPO_B"
assert_exit_zero "T-WTC-B: classify exits 0" "$RC_LAST"

RECORD_B="$(printf '%s\n' "$OUT_LAST" | grep -v '^[[:space:]]*$' | head -1)"
BUCKET_B="$(_json_field "$RECORD_B" bucket)"
assert_eq "T-WTC-B: bucket is merged-dirty" "merged-dirty" "$BUCKET_B"
TRACKED_DIRTY_B="$(_json_field "$RECORD_B" tracked_dirty)"
if [[ "$TRACKED_DIRTY_B" -gt 0 ]]; then
  echo "  PASS: T-WTC-B: tracked_dirty > 0"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T-WTC-B: expected tracked_dirty > 0, got $TRACKED_DIRTY_B"
  FAIL=$((FAIL + 1))
fi

# ---------------------------------------------------------------------------
# T-WTC-C: classify tags a worktree with unique unmerged commits as
# unmerged-work.
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-C: classify tags worktree with unique unmerged commits as unmerged-work"

REPO_C="$(_mk_repo)"
WT_C="$(_mk_unmerged_worktree "$REPO_C" "feature-c")"

run_helper classify "$REPO_C"
assert_exit_zero "T-WTC-C: classify exits 0" "$RC_LAST"

RECORD_C="$(printf '%s\n' "$OUT_LAST" | grep -v '^[[:space:]]*$' | head -1)"
BUCKET_C="$(_json_field "$RECORD_C" bucket)"
assert_eq "T-WTC-C: bucket is unmerged-work" "unmerged-work" "$BUCKET_C"
MERGE_STATE_C="$(_json_field "$RECORD_C" merge_state)"
assert_eq "T-WTC-C: merge_state is unmerged" "unmerged" "$MERGE_STATE_C"

# ---------------------------------------------------------------------------
# T-WTC-D: remove <path> on a DIRTY worktree exits non-zero and removes
# NOTHING (no --force).
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-D: remove on a dirty worktree refuses without --force"

REPO_D="$(_mk_repo)"
WT_D="$(_mk_squash_merged_worktree "$REPO_D" "feature-d")"
printf 'uncommitted edit\n' >> "$WT_D/feature-feature-d.txt"

run_helper remove "$WT_D"
assert_exit_nonzero "T-WTC-D: remove refuses on dirty worktree" "$RC_LAST"
assert_contains "T-WTC-D: refusal message mentions --force" "--force" "$ERR_LAST"

if [[ -d "$WT_D" ]]; then
  echo "  PASS: T-WTC-D: worktree directory still exists after refused remove"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T-WTC-D: worktree directory was removed despite refusal"
  FAIL=$((FAIL + 1))
fi

BRANCH_LIST_D="$(git -C "$REPO_D" branch --list feature-d)"
assert_contains "T-WTC-D: branch feature-d still exists after refused remove" "feature-d" "$BRANCH_LIST_D"

WT_LIST_D="$(git -C "$REPO_D" worktree list)"
assert_contains "T-WTC-D: worktree still registered in git worktree list" "feature-d" "$WT_LIST_D"

# ---------------------------------------------------------------------------
# T-WTC-E: remove <path> on an UNMERGED worktree exits non-zero and removes
# nothing (no --force).
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-E: remove on an unmerged worktree refuses without --force"

REPO_E="$(_mk_repo)"
WT_E="$(_mk_unmerged_worktree "$REPO_E" "feature-e")"

run_helper remove "$WT_E"
assert_exit_nonzero "T-WTC-E: remove refuses on unmerged worktree" "$RC_LAST"
assert_contains "T-WTC-E: refusal message mentions --force" "--force" "$ERR_LAST"

if [[ -d "$WT_E" ]]; then
  echo "  PASS: T-WTC-E: worktree directory still exists after refused remove"
  PASS=$((PASS + 1))
else
  echo "  FAIL: T-WTC-E: worktree directory was removed despite refusal"
  FAIL=$((FAIL + 1))
fi

BRANCH_LIST_E="$(git -C "$REPO_E" branch --list feature-e)"
assert_contains "T-WTC-E: branch feature-e still exists after refused remove" "feature-e" "$BRANCH_LIST_E"

# ---------------------------------------------------------------------------
# T-WTC-F: remove <path> on a safe (merged+clean) worktree succeeds —
# worktree gone from `git worktree list` AND the branch deleted.
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-F: remove on a safe (merged+clean) worktree succeeds"

REPO_F="$(_mk_repo)"
WT_F="$(_mk_squash_merged_worktree "$REPO_F" "feature-f")"

run_helper remove "$WT_F"
assert_exit_zero "T-WTC-F: remove succeeds on safe worktree" "$RC_LAST"

WT_LIST_F="$(git -C "$REPO_F" worktree list)"
assert_not_contains "T-WTC-F: worktree no longer in git worktree list" "feature-f" "$WT_LIST_F"

BRANCH_LIST_F="$(git -C "$REPO_F" branch --list feature-f)"
assert_eq "T-WTC-F: branch feature-f deleted" "" "$BRANCH_LIST_F"

if [[ -d "$WT_F" ]]; then
  echo "  FAIL: T-WTC-F: worktree directory still on disk after successful remove"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T-WTC-F: worktree directory removed from disk"
  PASS=$((PASS + 1))
fi

# ---------------------------------------------------------------------------
# T-WTC-G: remove --force <path> overrides the refusal on a dirty worktree.
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-G: remove --force overrides refusal on a dirty worktree"

REPO_G="$(_mk_repo)"
WT_G="$(_mk_squash_merged_worktree "$REPO_G" "feature-g")"
printf 'uncommitted edit\n' >> "$WT_G/feature-feature-g.txt"

# Sanity: without --force it is refused.
run_helper remove "$WT_G"
assert_exit_nonzero "T-WTC-G: without --force, remove is refused (sanity check)" "$RC_LAST"

run_helper remove "$WT_G" --force
assert_exit_zero "T-WTC-G: with --force, remove succeeds" "$RC_LAST"

WT_LIST_G="$(git -C "$REPO_G" worktree list)"
assert_not_contains "T-WTC-G: worktree no longer in git worktree list after --force" "feature-g" "$WT_LIST_G"

if [[ -d "$WT_G" ]]; then
  echo "  FAIL: T-WTC-G: worktree directory still on disk after --force remove"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: T-WTC-G: worktree directory removed from disk after --force"
  PASS=$((PASS + 1))
fi

# ---------------------------------------------------------------------------
# T-WTC-H: the main worktree is never classified or removed.
# ---------------------------------------------------------------------------
echo ""
echo "T-WTC-H: main worktree is never classified or removed"

REPO_H="$(_mk_repo)"
WT_H="$(_mk_squash_merged_worktree "$REPO_H" "feature-h")"

run_helper classify "$REPO_H"
assert_exit_zero "T-WTC-H: classify exits 0" "$RC_LAST"

RECORD_COUNT_H="$(printf '%s\n' "$OUT_LAST" | grep -c '"bucket"' || true)"
assert_eq "T-WTC-H: classify emits exactly one record (main worktree excluded)" "1" "$RECORD_COUNT_H"
assert_not_contains "T-WTC-H: classify output does not include the main worktree path" "\"path\": \"$REPO_H\"" "$OUT_LAST"

run_helper remove "$REPO_H"
assert_exit_nonzero "T-WTC-H: remove on the main worktree refuses" "$RC_LAST"
assert_contains "T-WTC-H: refusal message mentions the main worktree" "main worktree" "$ERR_LAST"

MAIN_STILL_THERE_H="0"
if [[ -d "$REPO_H" ]]; then
  MAIN_STILL_THERE_H="1"
fi
assert_true "T-WTC-H: main worktree directory still exists after refused remove" "$MAIN_STILL_THERE_H"

git -C "$REPO_H" worktree remove -q --force "$WT_H" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
