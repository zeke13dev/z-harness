#!/usr/bin/env bash
# test_block_dangerous_git.sh — Tests for block-dangerous-git.sh PreToolUse hook.
#
# Run with:
#   bash scripts/test_block_dangerous_git.sh
#
# Tests:
#   T005-A: Working-tree-destructive commands are blanket-blocked (exit 2)
#   T005-B: Non-git and safe git commands pass through (exit 0)
#   T005-C: History-rewrite with upstream-reachable HEAD is blocked (exit 2)
#   T005-D: History-rewrite with non-upstream HEAD is allowed (exit 0)
#   T005-E: Fail-closed: unborn/detached HEAD or rev errors are blocked (exit 2)
#   T005-F: Override path: Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1 allows + logs
#   T005-G: Global-option / chaining EVASION class is still caught (regression)

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPTS_DIR/block-dangerous-git.sh"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
CLEANUP_DIRS=()
cleanup() {
  for d in "${CLEANUP_DIRS[@]:-}"; do
    rm -rf "$d"
  done
}
trap cleanup EXIT

_tmpdir() {
  local d
  d="$(mktemp -d "/tmp/test_blk_git_XXXXXX")"
  CLEANUP_DIRS+=("$d")
  printf '%s' "$d"
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

assert_rc() {
  local expected="$1"
  local description="$2"
  local actual="$3"
  if [[ "$actual" -eq "$expected" ]]; then
    printf '  PASS: %s (exit %s)\n' "$description" "$actual"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s — expected exit %s, got %s\n' "$description" "$expected" "$actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_contains() {
  local label="$1"
  local needle="$2"
  local haystack="$3"
  if printf '%s' "$haystack" | grep -qF "$needle"; then
    printf '  PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: %s\n' "$label"
    printf '        expected substring: %s\n' "$needle"
    printf '        in: %s\n' "$haystack"
    FAIL=$((FAIL + 1))
  fi
}

# Pipe a JSON payload into the hook and capture exit code + stderr.
# Usage: run_hook <json> [env_var=value ...]
#   Sets RC_LAST and STDERR_LAST.
RC_LAST=0
STDERR_LAST=""
run_hook() {
  local json="$1"
  shift
  RC_LAST=0
  STDERR_LAST=""
  STDERR_LAST="$(printf '%s' "$json" | env "$@" bash "$HOOK" 2>&1)" || RC_LAST=$?
}

# Run hook from inside a git repo directory.
# Usage: run_hook_in_repo <repo_dir> <json> [env_var=value ...]
run_hook_in_repo() {
  local repo_dir="$1"
  local json="$2"
  shift 2
  RC_LAST=0
  STDERR_LAST=""
  STDERR_LAST="$(cd "$repo_dir" && printf '%s' "$json" | env "$@" bash "$HOOK" 2>&1)" || RC_LAST=$?
}

# ---------------------------------------------------------------------------
# TEST T005-A: Working-tree-destructive commands are blanket-blocked (exit 2)
# ---------------------------------------------------------------------------
printf '\nT005-A: Working-tree-destructive commands blocked (rc=2)\n'

DESTRUCTIVE_CMDS=(
  "git clean -fdx"
  "git clean -fd"
  "git clean -f ."
  "git checkout ."
  "git restore ."
  "git branch -D somebranch"
)

for CMD in "${DESTRUCTIVE_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook "$JSON"
  assert_rc 2 "T005-A: '$CMD' is blocked" "$RC_LAST"
done

# ---------------------------------------------------------------------------
# TEST T005-B: Non-git and safe git commands pass through (exit 0)
# ---------------------------------------------------------------------------
printf '\nT005-B: Non-git and safe git commands pass through (rc=0)\n'

PASS_THROUGH_CMDS=(
  "ls -la"
  "echo hi"
  "git status"
  "git log"
  "git diff"
  "git add ."
)

for CMD in "${PASS_THROUGH_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook "$JSON"
  assert_rc 0 "T005-B: '$CMD' passes through" "$RC_LAST"
done

# Non-Bash tool with dangerous git command passes through (not a Bash tool call)
JSON='{"tool_name":"Write","tool_input":{"command":"git reset --hard HEAD~1"}}'
run_hook "$JSON"
assert_rc 0 "T005-B: non-Bash tool with dangerous cmd passes through" "$RC_LAST"

# Empty stdin passes through
RC_LAST=0
STDERR_LAST=""
STDERR_LAST="$(printf '' | bash "$HOOK" 2>&1)" || RC_LAST=$?
assert_rc 0 "T005-B: empty stdin passes through" "$RC_LAST"

# ---------------------------------------------------------------------------
# TEST T005-C: History-rewrite with upstream-reachable HEAD is blocked (exit 2)
# ---------------------------------------------------------------------------
printf '\nT005-C: History-rewrite + upstream-reachable HEAD is blocked (rc=2)\n'

# Set up a temp repo with a local bare "remote" where HEAD is pushed.
REPO_C="$(_tmpdir)"
REMOTE_C="$(_tmpdir)"

# Init the bare remote
git -C "$REMOTE_C" init -q --bare

# Init the local repo and push a commit to the remote
git -C "$REPO_C" init -q
git -C "$REPO_C" config user.email "test@test.local"
git -C "$REPO_C" config user.name "Test"
git -C "$REPO_C" remote add origin "$REMOTE_C"
printf 'init\n' > "$REPO_C/README"
git -C "$REPO_C" add README
git -C "$REPO_C" commit -q -m "init"
git -C "$REPO_C" push -q origin HEAD:refs/heads/main

# Now HEAD is upstream-reachable: git branch -r --contains HEAD should list origin/main
REWRITE_CMDS=(
  "git reset --hard HEAD~1"
  "git commit --amend --no-edit"
  "git push --force"
  "git push --force-with-lease"
  "git push -f"
)

for CMD in "${REWRITE_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook_in_repo "$REPO_C" "$JSON"
  assert_rc 2 "T005-C: '$CMD' blocked (HEAD upstream-reachable)" "$RC_LAST"
done

# Verify the block message mentions upstream/inspect
for CMD in "git reset --hard HEAD~1" "git push --force"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook_in_repo "$REPO_C" "$JSON"
  assert_contains "T005-C: block message mentions upstream recovery for '$CMD'" \
    "inspect" "$STDERR_LAST"
done

# +-refspec force pushes are semantically equivalent to --force for that ref and
# must flow through the SAME upstream-reachability check (block when reachable).
PLUS_REFSPEC_BLOCK_CMDS=(
  "git push origin +main"
  "git push origin +refs/heads/main:refs/heads/main"
  "git push origin +src:main"
)

for CMD in "${PLUS_REFSPEC_BLOCK_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook_in_repo "$REPO_C" "$JSON"
  assert_rc 2 "T005-C: '$CMD' blocked (+refspec is a force push, upstream-reachable)" "$RC_LAST"
done

# Sanity: a normal (non-force) push of the same ref must NOT be treated as a
# rewrite verb — it passes through (rc=0) even on the upstream-reachable repo.
JSON_NORMAL_PUSH='{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'
run_hook_in_repo "$REPO_C" "$JSON_NORMAL_PUSH"
assert_rc 0 "T005-C: 'git push origin main' (no +) passes through (not a force push)" "$RC_LAST"

# ---------------------------------------------------------------------------
# TEST T005-D: History-rewrite with non-upstream HEAD is allowed (exit 0)
# ---------------------------------------------------------------------------
printf '\nT005-D: History-rewrite + HEAD NOT upstream-reachable is allowed (rc=0)\n'

# Set up a temp repo where there is a remote but the latest local commit is NOT pushed.
REPO_D="$(_tmpdir)"
REMOTE_D="$(_tmpdir)"

git -C "$REMOTE_D" init -q --bare

git -C "$REPO_D" init -q
git -C "$REPO_D" config user.email "test@test.local"
git -C "$REPO_D" config user.name "Test"
git -C "$REPO_D" remote add origin "$REMOTE_D"

# Push an initial commit
printf 'base\n' > "$REPO_D/README"
git -C "$REPO_D" add README
git -C "$REPO_D" commit -q -m "base"
git -C "$REPO_D" push -q origin HEAD:refs/heads/main

# Add a LOCAL-ONLY commit that has not been pushed
printf 'local-only\n' >> "$REPO_D/README"
git -C "$REPO_D" add README
git -C "$REPO_D" commit -q -m "local-only commit"

# HEAD (local-only commit) is NOT upstream-reachable
LOCAL_REWRITE_CMDS=(
  "git reset --hard HEAD~1"
  "git commit --amend --no-edit"
  "git push --force"
)

for CMD in "${LOCAL_REWRITE_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook_in_repo "$REPO_D" "$JSON"
  assert_rc 0 "T005-D: '$CMD' allowed (HEAD not upstream-reachable)" "$RC_LAST"
done

# ---------------------------------------------------------------------------
# TEST T005-E: Fail-closed on unborn/detached HEAD or rev/contains errors (exit 2)
# ---------------------------------------------------------------------------
printf '\nT005-E: Fail-closed (unborn/detached HEAD or git errors) -> blocked (rc=2)\n'

# Sub-case E1: Repo with unborn HEAD (no commits yet)
REPO_E1="$(_tmpdir)"
git -C "$REPO_E1" init -q
git -C "$REPO_E1" config user.email "test@test.local"
git -C "$REPO_E1" config user.name "Test"
# No commits — HEAD is unborn; git rev-parse --verify HEAD fails

JSON_RESET='{"tool_name":"Bash","tool_input":{"command":"git reset --hard HEAD~1"}}'
run_hook_in_repo "$REPO_E1" "$JSON_RESET"
assert_rc 2 "T005-E1: unborn HEAD + reset --hard is blocked fail-closed" "$RC_LAST"
assert_contains "T005-E1: fail-closed message shown" "fail-closed" "$STDERR_LAST"

JSON_AMEND='{"tool_name":"Bash","tool_input":{"command":"git commit --amend --no-edit"}}'
run_hook_in_repo "$REPO_E1" "$JSON_AMEND"
assert_rc 2 "T005-E1: unborn HEAD + commit --amend is blocked fail-closed" "$RC_LAST"

# Sub-case E2: Repo with a commit but NO remote configured
# git branch -r --contains <sha> exits non-zero when there are no remotes
REPO_E2="$(_tmpdir)"
git -C "$REPO_E2" init -q
git -C "$REPO_E2" config user.email "test@test.local"
git -C "$REPO_E2" config user.name "Test"
printf 'init\n' > "$REPO_E2/README"
git -C "$REPO_E2" add README
git -C "$REPO_E2" commit -q -m "init"
# No remote added — git branch -r --contains may fail or return empty.
# The hook fails-closed on any git error from the contains check.
# Actually: git branch -r --contains with no remote returns empty stdout + exit 0,
# which is "not upstream-reachable" → allow. We test a stronger fail-closed case
# by detaching HEAD instead.

# Sub-case E2: Detached HEAD
REPO_E2B="$(_tmpdir)"
REMOTE_E2B="$(_tmpdir)"
git -C "$REMOTE_E2B" init -q --bare
git -C "$REPO_E2B" init -q
git -C "$REPO_E2B" config user.email "test@test.local"
git -C "$REPO_E2B" config user.name "Test"
git -C "$REPO_E2B" remote add origin "$REMOTE_E2B"
printf 'init\n' > "$REPO_E2B/README"
git -C "$REPO_E2B" add README
git -C "$REPO_E2B" commit -q -m "init"
git -C "$REPO_E2B" push -q origin HEAD:refs/heads/main
# Detach HEAD: now HEAD points at the same sha but is not a branch tip,
# git branch -r --contains <sha> will still return origin/main → blocked.
# For the true fail-closed test: a repo where rev-parse --verify HEAD fails.
# The E1 (unborn) already covers that. Detached HEAD that IS upstream-reachable
# also ends up blocked (which is also the fail-safe path).
SHA_E2B="$(git -C "$REPO_E2B" rev-parse HEAD)"
git -C "$REPO_E2B" checkout -q --detach "$SHA_E2B"
run_hook_in_repo "$REPO_E2B" "$JSON_RESET"
assert_rc 2 "T005-E2: detached HEAD (reachable sha) + reset --hard is blocked" "$RC_LAST"

# ---------------------------------------------------------------------------
# TEST T005-F: Override path — allowed + audit log entry (exit 0)
# ---------------------------------------------------------------------------
printf '\nT005-F: Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1 allows + writes audit log (rc=0)\n'

# Set up a repo with upstream-reachable HEAD (would normally be blocked)
REPO_F="$(_tmpdir)"
REMOTE_F="$(_tmpdir)"
AUDIT_BASE_F="$(_tmpdir)"

git -C "$REMOTE_F" init -q --bare
git -C "$REPO_F" init -q
git -C "$REPO_F" config user.email "test@test.local"
git -C "$REPO_F" config user.name "Test"
git -C "$REPO_F" remote add origin "$REMOTE_F"
printf 'init\n' > "$REPO_F/README"
git -C "$REPO_F" add README
git -C "$REPO_F" commit -q -m "init"
git -C "$REPO_F" push -q origin HEAD:refs/heads/main

# Verify this command IS blocked without override
JSON_FORCE='{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}}'
run_hook_in_repo "$REPO_F" "$JSON_FORCE"
assert_rc 2 "T005-F: without override, push --force is blocked (sanity check)" "$RC_LAST"

# Now run with override
RC_LAST=0
STDERR_LAST=""
STDERR_LAST="$(cd "$REPO_F" && printf '%s' "$JSON_FORCE" | \
  Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1 \
  Z_HARNESS_BASE_DIR="$AUDIT_BASE_F" \
  bash "$HOOK" 2>&1)" || RC_LAST=$?

assert_rc 0 "T005-F: with override, push --force is allowed (rc=0)" "$RC_LAST"

# Audit log must have been written
AUDIT_LOG_F="$AUDIT_BASE_F/git-guardrails-audit.log"
if [[ -f "$AUDIT_LOG_F" ]]; then
  printf '  PASS: T005-F: audit log file created at %s\n' "$AUDIT_LOG_F"
  PASS=$((PASS + 1))
else
  printf '  FAIL: T005-F: audit log file NOT found at %s\n' "$AUDIT_LOG_F"
  FAIL=$((FAIL + 1))
fi

AUDIT_CONTENT_F=""
if [[ -f "$AUDIT_LOG_F" ]]; then
  AUDIT_CONTENT_F="$(cat "$AUDIT_LOG_F")"
fi
assert_contains "T005-F: audit log contains 'override'" "override" "$AUDIT_CONTENT_F"
assert_contains "T005-F: audit log contains the command" "push --force" "$AUDIT_CONTENT_F"

# Also test override with a destructive command (blanket-block normally)
JSON_CLEAN='{"tool_name":"Bash","tool_input":{"command":"git clean -fdx"}}'
RC_LAST=0
STDERR_LAST="$(cd "$REPO_F" && printf '%s' "$JSON_CLEAN" | \
  Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1 \
  Z_HARNESS_BASE_DIR="$AUDIT_BASE_F" \
  bash "$HOOK" 2>&1)" || RC_LAST=$?
assert_rc 0 "T005-F: with override, git clean -fdx is allowed (rc=0)" "$RC_LAST"

# Audit log should now have two entries (one per override call)
if [[ -f "$AUDIT_LOG_F" ]]; then
  ENTRY_COUNT="$(wc -l < "$AUDIT_LOG_F" | tr -d ' ')"
  if [[ "$ENTRY_COUNT" -ge 2 ]]; then
    printf '  PASS: T005-F: audit log has %s entries (>=2)\n' "$ENTRY_COUNT"
    PASS=$((PASS + 1))
  else
    printf '  FAIL: T005-F: audit log has only %s entries (expected >=2)\n' "$ENTRY_COUNT"
    FAIL=$((FAIL + 1))
  fi
fi

# ---------------------------------------------------------------------------
# TEST T005-G: Global-option / chaining EVASION class is still caught
# ---------------------------------------------------------------------------
# Regression coverage for the BLOCKER where intervening git global options
# (-C <path>, -c k=v, --git-dir=, --work-tree=) or command chaining let a
# dangerous verb slip past the substring matcher. Verb detection must survive
# normalization of global options, env-var prefixes, and chained segments.
printf '\nT005-G: Global-option / chaining evasion is caught (rc=2; benign rc=0)\n'

# Repo with upstream-reachable HEAD (rewrite verbs would normally be blocked).
REPO_G="$(_tmpdir)"
REMOTE_G="$(_tmpdir)"

git -C "$REMOTE_G" init -q --bare
git -C "$REPO_G" init -q
git -C "$REPO_G" config user.email "test@test.local"
git -C "$REPO_G" config user.name "Test"
git -C "$REPO_G" remote add origin "$REMOTE_G"
printf 'init\n' > "$REPO_G/README"
git -C "$REPO_G" add README
git -C "$REPO_G" commit -q -m "init"
git -C "$REPO_G" push -q origin HEAD:refs/heads/main

# Rewrite verbs hidden behind global options (run inside REPO_G so the
# upstream-reachable HEAD resolves and the verb is what's under test).
EVASION_BLOCK_CMDS=(
  "git -C /tmp reset --hard HEAD~1"
  "git --work-tree=$REPO_G --git-dir=$REPO_G/.git reset --hard"
  "git -c foo=bar reset --hard"
  "git -c foo=bar -p reset --hard HEAD~1"
  "GIT_DIR=x git reset --hard HEAD~1"
  "cd /tmp && git reset --hard HEAD~1"
)

for CMD in "${EVASION_BLOCK_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook_in_repo "$REPO_G" "$JSON"
  assert_rc 2 "T005-G: '$CMD' blocked (verb survives normalization)" "$RC_LAST"
done

# Working-tree-destructive verbs hidden behind global options (blanket-block,
# no upstream check needed — any cwd is fine).
EVASION_DESTRUCTIVE_CMDS=(
  "git -C /tmp clean -fdx"
  "git -c foo=bar clean -fd"
  "git --work-tree=/x --git-dir=/x/.git clean -f ."
  "git -p -c k=v clean -fdx"
  "cd /tmp && git clean -fdx"
  "GIT_DIR=x git checkout ."
  "git -C /tmp branch -D somebranch"
)

for CMD in "${EVASION_DESTRUCTIVE_CMDS[@]}"; do
  JSON="$(printf '{"tool_name":"Bash","tool_input":{"command":"%s"}}' "$CMD")"
  run_hook "$JSON"
  assert_rc 2 "T005-G: '$CMD' blocked (destructive verb survives normalization)" "$RC_LAST"
done

# Sanity: benign commands with global options must still pass through.
JSON_GC="$(printf '{"tool_name":"Bash","tool_input":{"command":"git -C %s status"}}' "$REPO_G")"
run_hook_in_repo "$REPO_G" "$JSON_GC"
assert_rc 0 "T005-G: 'git -C <tmp> status' still allowed" "$RC_LAST"

JSON_GC2='{"tool_name":"Bash","tool_input":{"command":"git -c color.ui=always log --oneline"}}'
run_hook_in_repo "$REPO_G" "$JSON_GC2"
assert_rc 0 "T005-G: 'git -c color.ui=always log' still allowed" "$RC_LAST"

# A chained command whose git segment is benign must still pass through.
JSON_GC3="$(printf '{"tool_name":"Bash","tool_input":{"command":"cd %s && git -C %s status"}}' "$REPO_G" "$REPO_G")"
run_hook_in_repo "$REPO_G" "$JSON_GC3"
assert_rc 0 "T005-G: 'cd <tmp> && git -C <tmp> status' still allowed" "$RC_LAST"

# A local-only (not upstream-reachable) reset behind -C must still be allowed
# (normalization must not change the upstream-reachability semantics).
REPO_G2="$(_tmpdir)"
REMOTE_G2="$(_tmpdir)"
git -C "$REMOTE_G2" init -q --bare
git -C "$REPO_G2" init -q
git -C "$REPO_G2" config user.email "test@test.local"
git -C "$REPO_G2" config user.name "Test"
git -C "$REPO_G2" remote add origin "$REMOTE_G2"
printf 'base\n' > "$REPO_G2/README"
git -C "$REPO_G2" add README
git -C "$REPO_G2" commit -q -m "base"
git -C "$REPO_G2" push -q origin HEAD:refs/heads/main
printf 'local\n' >> "$REPO_G2/README"
git -C "$REPO_G2" add README
git -C "$REPO_G2" commit -q -m "local-only"

JSON_GLOCAL='{"tool_name":"Bash","tool_input":{"command":"git -c foo=bar reset --hard HEAD~1"}}'
run_hook_in_repo "$REPO_G2" "$JSON_GLOCAL"
assert_rc 0 "T005-G: local-only reset behind -c is allowed (semantics preserved)" "$RC_LAST"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
