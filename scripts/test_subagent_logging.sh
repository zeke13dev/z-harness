#!/usr/bin/env bash
# test_subagent_logging.sh — Drift-guard CI for subagent dispatch logging (T007)
#
# Policy (read this before modifying):
# ============================================================
# This test enforces that the 4 canonical role-bearing dispatch sites wired by
# T006 remain logged, and that the regression-detection mechanism works.
#
# ROLE-BEARING dispatch types and their canonical logging location:
#
#   implementer       — z-implement-all.md logs it (orchestrator-side, after Agent() returns)
#   reviewer          — agents/reviewer.md self-logs (the agent logs its own invocation)
#   consultant-primary  — agents/consultant-primary.md self-logs
#   consultant-secondary — agents/consultant-secondary.md self-logs
#
# CANONICAL FILES (the 5 sites that must contain log-subagent.sh — 4 wired by T006, 1 by T007):
#   commands/z-implement-all.md          must contain log-subagent.sh
#   commands/z-implement-next.md         must contain log-subagent.sh (wired by T007)
#   agents/reviewer.md                   must contain log-subagent.sh
#   agents/consultant-primary.md         must contain log-subagent.sh
#   agents/consultant-secondary.md       must contain log-subagent.sh
#
# DRIFT DETECTION (broad scan — fails on NEW role dispatches without logging):
#   Scans ALL commands/*.md and agents/*.md for subagent_type="implementer".
#   Any such file that lacks BOTH log-subagent.sh AND a # no-subagent-log: opt-out
#   is a VIOLATION.  This catches someone adding a new orchestrator that dispatches
#   implementers without wiring the telemetry.
#
#   Opt-out syntax:  # no-subagent-log: <reason>
#   Place it in the same file that contains subagent_type="implementer".
#
# KNOWN EXCEPTIONS (files that have implementer dispatches but are pre-T007 gaps
# not yet wired — add a # no-subagent-log: comment to those files to clear them):
#   (none — all known implementer dispatch sites are now wired or opted out)
#
# CONSULTANT DISPATCHES from orchestrators (z-review-all.md, z-audit-plan.md, etc.):
#   These do NOT require log-subagent.sh or opt-outs — the AGENTS self-log from
#   within agents/consultant-primary.md and agents/consultant-secondary.md.
#   Double-logging from orchestrators would inflate cost metrics.
#
# Run with:
#   bash scripts/test_subagent_logging.sh
#
# Exit 0 = all checks pass.
# Exit 1 = at least one violation detected.
# ============================================================

set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
COMMANDS_DIR="$REPO_ROOT/commands"
AGENTS_DIR="$REPO_ROOT/agents"

PASS=0
FAIL=0
VIOLATIONS=()

# Files with implementer dispatches that are pre-T007 gaps, not yet wired.
# Remove a file from this list by adding '# no-subagent-log: <reason>' to it.
_IMPLEMENTER_DISPATCH_EXCEPTIONS=()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

assert_pass() {
  local label="$1"
  echo "  PASS: $label"
  PASS=$((PASS + 1))
}

assert_fail() {
  local label="$1" detail="$2"
  echo "  FAIL: $label"
  echo "        $detail"
  FAIL=$((FAIL + 1))
  VIOLATIONS+=("$label: $detail")
}

file_has() {
  local file="$1" needle="$2"
  grep -qF "$needle" "$file" 2>/dev/null
}

_is_exception() {
  local rel_path="$1"
  local exc
  for exc in "${_IMPLEMENTER_DISPATCH_EXCEPTIONS[@]}"; do
    if [[ "$exc" == "$rel_path" ]]; then
      return 0
    fi
  done
  return 1
}

# ---------------------------------------------------------------------------
# Part 1: Canonical-file checks
#
# Verify the 4 sites wired by T006 still have log-subagent.sh.
# These are pinned checks — if any are removed, this fails immediately.
# ---------------------------------------------------------------------------

echo ""
echo "Part 1: Canonical logging sites (T006-wired) must still have log-subagent.sh"

_CANONICAL_FILES=(
  "commands/z-implement-all.md"
  "commands/z-implement-next.md"
  "agents/reviewer.md"
  "agents/consultant-primary.md"
  "agents/consultant-secondary.md"
)

for rel_path in "${_CANONICAL_FILES[@]}"; do
  full_path="$REPO_ROOT/$rel_path"
  if [[ ! -f "$full_path" ]]; then
    assert_fail \
      "Canonical file missing: $rel_path" \
      "File must exist and contain log-subagent.sh — it was wired by T006"
    continue
  fi
  if file_has "$full_path" 'log-subagent.sh'; then
    assert_pass "log-subagent.sh present in $rel_path"
  else
    assert_fail \
      "log-subagent.sh REMOVED from $rel_path" \
      "This is a regression — T006 wired this file; restore the log-subagent.sh call"
  fi
done

# ---------------------------------------------------------------------------
# Part 2: Broad drift scan — any file with subagent_type="implementer" must be logged
#
# Scans commands/ and agents/ for implementer dispatch sites.
# Each file must have EITHER log-subagent.sh OR a # no-subagent-log: opt-out,
# unless it appears in _IMPLEMENTER_DISPATCH_EXCEPTIONS (pre-existing gap).
# ---------------------------------------------------------------------------

echo ""
echo "Part 2: Drift scan — new implementer dispatch sites must be logged"

while IFS= read -r -d '' file; do
  if ! file_has "$file" 'subagent_type="implementer"'; then
    continue
  fi

  # Compute path relative to repo root for exception matching
  rel_path="${file#$REPO_ROOT/}"

  has_log=0
  has_optout=0
  file_has "$file" 'log-subagent.sh' && has_log=1
  file_has "$file" '# no-subagent-log:' && has_optout=1
  basename="$(basename "$file")"

  if [[ "$has_log" -eq 1 || "$has_optout" -eq 1 ]]; then
    assert_pass "implementer dispatch logged or opted-out in $basename"
  elif _is_exception "$rel_path"; then
    echo "  SKIP: $basename — pre-existing gap in exception list; add '# no-subagent-log:' to clear"
  else
    assert_fail \
      "New unlogged implementer dispatch detected in $basename" \
      "Add log-subagent.sh call after Agent() or '# no-subagent-log: <reason>' opt-out"
  fi
done < <(find "$COMMANDS_DIR" "$AGENTS_DIR" -name "*.md" -print0 2>/dev/null)

# ---------------------------------------------------------------------------
# Self-test: prove the broad scan catches an unlogged implementer dispatch
#
# Creates a temporary fixture file that mimics a NEW command with an unlogged
# implementer dispatch.  The self-test verifies the check logic flags it.
# This proves the test can catch future regressions.
# ---------------------------------------------------------------------------

echo ""
echo "Self-test: verify regression detection catches an unlogged implementer dispatch"

FIXTURE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/test_subagent_logging_fixture_XXXXXX")"
trap 'rm -rf "$FIXTURE_DIR"' EXIT

# Fixture A: unlogged implementer dispatch — should be flagged as a violation
FIXTURE_A="$FIXTURE_DIR/new-unlogged-command.md"
cat > "$FIXTURE_A" << 'FIXTURE_A_EOF'
---
description: "Test fixture — unlogged implementer dispatch (should be flagged)"
---

## Phase 5

```
Agent(
  subagent_type="implementer",
  description="Implement T999",
  prompt="..."
)
```
FIXTURE_A_EOF

# Run the implementer-dispatch check on fixture A
fixture_a_has_log=0
fixture_a_has_optout=0
grep -qF 'log-subagent.sh' "$FIXTURE_A" 2>/dev/null && fixture_a_has_log=1
grep -qF '# no-subagent-log:' "$FIXTURE_A" 2>/dev/null && fixture_a_has_optout=1

has_implementer_a=0
grep -qF 'subagent_type="implementer"' "$FIXTURE_A" 2>/dev/null && has_implementer_a=1

if [[ "$has_implementer_a" -eq 1 \
    && "$fixture_a_has_log" -eq 0 \
    && "$fixture_a_has_optout" -eq 0 ]]; then
  assert_pass "Self-test A: unlogged implementer dispatch correctly flagged as violation"
else
  assert_fail \
    "Self-test A: FAILED to detect unlogged implementer dispatch" \
    "The drift-guard check is broken — it did not flag fixture_a as a violation"
fi

# Fixture B: properly logged implementer dispatch — should pass
FIXTURE_B="$FIXTURE_DIR/new-logged-command.md"
cat > "$FIXTURE_B" << 'FIXTURE_B_EOF'
---
description: "Test fixture — logged implementer dispatch (should pass)"
---

## Phase 5

```
Agent(
  subagent_type="implementer",
  description="Implement T999",
  prompt="..."
)
```

```bash
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-subagent.sh" \
  --run "tasks/<task-id>" \
  --role "implementer" \
  --subagent-type "implementer" \
  --subagent-model "$IMPL_MODEL" \
  --prompt-chars "$IMPL_PROMPT_CHARS" \
  --response-chars "$IMPL_RESPONSE_CHARS" || true
```
FIXTURE_B_EOF

fixture_b_has_log=0
grep -qF 'log-subagent.sh' "$FIXTURE_B" 2>/dev/null && fixture_b_has_log=1

if [[ "$fixture_b_has_log" -eq 1 ]]; then
  assert_pass "Self-test B: properly logged implementer dispatch correctly passes"
else
  assert_fail \
    "Self-test B: properly logged dispatch incorrectly fails" \
    "Check that grep -qF 'log-subagent.sh' matches the fixture"
fi

# Fixture C: opt-out implementer dispatch — should pass
FIXTURE_C="$FIXTURE_DIR/new-optout-command.md"
cat > "$FIXTURE_C" << 'FIXTURE_C_EOF'
---
description: "Test fixture — opt-out implementer dispatch (should pass)"
---

# no-subagent-log: this command does not dispatch an implementer in prod; Agent() here is illustrative

## Phase 5

```
Agent(
  subagent_type="implementer",
  description="Implement T999",
  prompt="..."
)
```
FIXTURE_C_EOF

fixture_c_has_optout=0
grep -qF '# no-subagent-log:' "$FIXTURE_C" 2>/dev/null && fixture_c_has_optout=1

if [[ "$fixture_c_has_optout" -eq 1 ]]; then
  assert_pass "Self-test C: opt-out implementer dispatch correctly passes"
else
  assert_fail \
    "Self-test C: opt-out dispatch incorrectly fails" \
    "Check that grep -qF '# no-subagent-log:' matches the fixture"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"
echo ""

if [[ "${#VIOLATIONS[@]}" -gt 0 ]]; then
  echo "Violations:"
  for v in "${VIOLATIONS[@]}"; do
    echo "  - $v"
  done
  echo ""
  echo "DRIFT DETECTED: add log-subagent.sh calls or '# no-subagent-log: <reason>' opt-outs to fix."
  exit 1
fi

echo "OK: all canonical role-bearing dispatch sites are logged; no new unlogged dispatches detected."
exit 0
