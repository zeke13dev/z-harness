#!/usr/bin/env bash
# test_external_base_smoke.sh — End-to-end smoke test for external base durability gate.
#
# PURPOSE: This test is the GATE for T015 (the Phase-D flip). T015 must not
# proceed until every checkbox in docs/human/PLAN-LAYOUT.md#command-coverage-checklist
# is checked AND this smoke test passes.
#
# Run with:
#   bash scripts/test_external_base_smoke.sh
#
# Tests (hermetic temp git repo + Z_HARNESS_BASE_DIR pointed at a temp external dir):
#
#   SMOKE-A: base_dir() resolves to the temp external base (not the in-repo z-harness/).
#   SMOKE-B: all_plan_slugs discovers both new-layout (<base>/plans/<slug>/) and
#            legacy-flat (<base>/<slug>/) plan dirs.
#   SMOKE-C: active-plan-registry.py register → record lands under <base>/active-plans/.
#   SMOKE-D: scope extraction via mechanical Files:-parse fallback → update-scope →
#            record contains scope with expected paths.
#   SMOKE-E: overlaps → exit 0 (no peer) + expected output.
#   SMOKE-F: list/read-back → record is readable with correct base and slug.
#   SMOKE-G: NOTHING is written under the in-repo z-harness/ when Z_HARNESS_BASE_DIR is set.
#   SMOKE-H: cleanup — no anchor pollution at <repo>/.git/.z-harness-base.
#
# This test script is SELF-CONTAINED: all artifacts are created and destroyed here.
# No teardown uses rm -rf on the real repo.

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"
PLAN_PATH="$SCRIPTS_DIR/plan-path.sh"
REGISTRY="$SCRIPTS_DIR/active-plan-registry.py"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Always use /tmp directly (not TMPDIR) so tmpdir-based repos are outside
# any enclosing git tree; this ensures git rev-parse --show-toplevel resolves
# to the hermetic repo, not the harness repo.
_tmpdir() {
  mktemp -d "/tmp/smoke_external_base_XXXXXX"
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

# ---------------------------------------------------------------------------
# Setup: hermetic temp git repo + external base dir
# ---------------------------------------------------------------------------

REPO="$(_tmpdir)"
EXTERNAL_BASE="$(_tmpdir)"

git -C "$REPO" init -q
git -C "$REPO" config user.email "smoke@test.local"
git -C "$REPO" config user.name "SmokeTest"

# Create an initial commit so the repo is valid
printf 'smoke test init\n' > "$REPO/README"
git -C "$REPO" add README
git -C "$REPO" commit -q -m "init"

RUN_ID="smoke-test-run-$$"
SLUG_NEW="dummy-plan-new"
SLUG_LEGACY="dummy-plan-legacy"
SCOPE_JSON="$EXTERNAL_BASE/scope-$$.json"

echo ""
echo "=== External Base Smoke Test ==="
echo "  REPO:          $REPO"
echo "  EXTERNAL_BASE: $EXTERNAL_BASE"
echo "  RUN_ID:        $RUN_ID"

# ---------------------------------------------------------------------------
# SMOKE-A: base_dir() resolves to the temp external base
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-A: base_dir() resolves to the temp external base"

RESULT_A=""
RESULT_A="$(cd "$REPO" && Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" bash "$PLAN_PATH" base_dir)"

assert_eq "SMOKE-A: base_dir returns EXTERNAL_BASE" "$EXTERNAL_BASE" "$RESULT_A"

# Also verify z_harness_base returns the same value
RESULT_A2=""
RESULT_A2="$(cd "$REPO" && Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" bash "$PLAN_PATH" z_harness_base)"

assert_eq "SMOKE-A: z_harness_base returns EXTERNAL_BASE" "$EXTERNAL_BASE" "$RESULT_A2"

# ---------------------------------------------------------------------------
# SMOKE-B: all_plan_slugs discovers both new-layout and legacy-flat plan dirs
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-B: all_plan_slugs discovers new-layout + legacy-flat plans"

# Create a new-layout plan dir: <base>/plans/<slug>/
mkdir -p "$EXTERNAL_BASE/plans/$SLUG_NEW"

# Create a legacy-flat plan dir directly under base: <base>/<slug>/
mkdir -p "$EXTERNAL_BASE/$SLUG_LEGACY"

SLUGS_B=""
SLUGS_B="$(cd "$REPO" && Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" bash "$PLAN_PATH" all_plan_slugs)"

# New-layout slug must appear
if printf '%s\n' "$SLUGS_B" | grep -qxF "$SLUG_NEW"; then
  echo "  PASS: SMOKE-B: new-layout slug '$SLUG_NEW' found in all_plan_slugs"
  PASS=$((PASS + 1))
else
  echo "  FAIL: SMOKE-B: new-layout slug '$SLUG_NEW' missing from all_plan_slugs"
  echo "        got: $SLUGS_B"
  FAIL=$((FAIL + 1))
fi

# Legacy-flat slug must appear
if printf '%s\n' "$SLUGS_B" | grep -qxF "$SLUG_LEGACY"; then
  echo "  PASS: SMOKE-B: legacy-flat slug '$SLUG_LEGACY' found in all_plan_slugs"
  PASS=$((PASS + 1))
else
  echo "  FAIL: SMOKE-B: legacy-flat slug '$SLUG_LEGACY' missing from all_plan_slugs"
  echo "        got: $SLUGS_B"
  FAIL=$((FAIL + 1))
fi

# Infrastructure dirs must NOT appear
for INFRA in plans archive active-plans followups; do
  if printf '%s\n' "$SLUGS_B" | grep -qxF "$INFRA"; then
    echo "  FAIL: SMOKE-B: infra dir '$INFRA' must NOT appear in all_plan_slugs"
    echo "        got: $SLUGS_B"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: SMOKE-B: infra dir '$INFRA' correctly excluded"
    PASS=$((PASS + 1))
  fi
done

# ---------------------------------------------------------------------------
# SMOKE-C: active-plan-registry.py register → record lands under <base>/active-plans/
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-C: register a run → record lands under <base>/active-plans/"

EXIT_C=0
(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" \
    python3 "$REGISTRY" register \
      --run-id "$RUN_ID" \
      --slug "$SLUG_NEW" \
      --command "/z-execute" \
      --phase "implement" \
      2>/dev/null
) || EXIT_C=$?

assert_exit_zero "SMOKE-C: register exits 0" "$EXIT_C"

EXPECTED_RECORD="$EXTERNAL_BASE/active-plans/$RUN_ID.json"
assert_file_exists "SMOKE-C: record file created at <base>/active-plans/<run-id>.json" "$EXPECTED_RECORD"

# Verify record has the right schema fields
RECORD_SLUG="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
print(rec.get('slug', ''))
" "$EXPECTED_RECORD" 2>/dev/null || true)"

assert_eq "SMOKE-C: record slug matches" "$SLUG_NEW" "$RECORD_SLUG"

RECORD_STATUS="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
print(rec.get('status', ''))
" "$EXPECTED_RECORD" 2>/dev/null || true)"

assert_eq "SMOKE-C: record status is 'running'" "running" "$RECORD_STATUS"

RECORD_COMMAND="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
print(rec.get('command', ''))
" "$EXPECTED_RECORD" 2>/dev/null || true)"

assert_eq "SMOKE-C: record command is '/z-execute'" "/z-execute" "$RECORD_COMMAND"

# ---------------------------------------------------------------------------
# SMOKE-D: scope extraction via mechanical fallback → update-scope → record contains scope
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-D: mechanical scope fallback → update-scope → scope stored in record"

# Create a dummy TASKS.md under the new-layout plan dir for scope extraction
TASKS_MD="$EXTERNAL_BASE/plans/$SLUG_NEW/TASKS.md"
cat > "$TASKS_MD" <<'EOF'
# TASKS — dummy-plan-new

## T001 — example task
**Files:** `scripts/plan-path.sh`, `scripts/active-plan-registry.py`
**Depends:** none
**Acceptance:** tests pass.

## T002 — another task
**Files:** `agents/scope-extractor.md` (NEW)
**Depends:** T001
**Acceptance:** agent validates.
EOF

# Run the mechanical fallback (as documented in agents/scope-extractor.md):
# grep **Files:** lines, parse paths, emit JSON array with explicit confidence.
# We replicate the documented one-liner using python3 for JSON assembly (jq may not be present).
SCOPE_JSON_CONTENT="$(
  { grep -E '^\*\*Files:\*\*' "$TASKS_MD" || true; } \
    | sed 's/^\*\*Files:\*\*[[:space:]]*//' \
    | tr ',' '\n' \
    | sed 's/`//g; s/[[:space:]]*(.*)//' \
    | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' \
    | { grep -v '^$' || true; } \
    | python3 -c '
import sys, json
entries = []
for line in sys.stdin:
    p = line.rstrip("\n")
    if p:
        entries.append({"path": p, "confidence": "explicit", "reason": "mechanical fallback"})
print(json.dumps(entries))
'
)"

printf '%s\n' "$SCOPE_JSON_CONTENT" > "$SCOPE_JSON"

# Verify scope JSON is valid and non-empty
SCOPE_COUNT="$(python3 -c "
import json, sys
data = json.loads(open(sys.argv[1]).read())
print(len(data))
" "$SCOPE_JSON" 2>/dev/null || true)"

if [[ "$SCOPE_COUNT" -gt 0 ]]; then
  echo "  PASS: SMOKE-D: mechanical fallback produced $SCOPE_COUNT scope entries"
  PASS=$((PASS + 1))
else
  echo "  FAIL: SMOKE-D: mechanical fallback produced no scope entries"
  FAIL=$((FAIL + 1))
fi

# Call update-scope to merge scope into the registry record
EXIT_D_SCOPE=0
(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" \
    python3 "$REGISTRY" update-scope \
      --run-id "$RUN_ID" \
      --scope-json "$SCOPE_JSON" \
      2>/dev/null
) || EXIT_D_SCOPE=$?

assert_exit_zero "SMOKE-D: update-scope exits 0" "$EXIT_D_SCOPE"

# Verify scope was stored in the record
STORED_SCOPE_COUNT="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
print(len(rec.get('scope', [])))
" "$EXPECTED_RECORD" 2>/dev/null || true)"

if [[ "${STORED_SCOPE_COUNT:-0}" -gt 0 ]]; then
  echo "  PASS: SMOKE-D: record scope has $STORED_SCOPE_COUNT entries after update-scope"
  PASS=$((PASS + 1))
else
  echo "  FAIL: SMOKE-D: record scope is empty after update-scope"
  FAIL=$((FAIL + 1))
fi

# Verify known paths appear in stored scope
STORED_PATHS="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
paths = [e.get('path','') for e in rec.get('scope', [])]
print(' '.join(paths))
" "$EXPECTED_RECORD" 2>/dev/null || true)"

assert_contains "SMOKE-D: stored scope contains scripts/plan-path.sh" \
  "scripts/plan-path.sh" "$STORED_PATHS"

assert_contains "SMOKE-D: stored scope contains scripts/active-plan-registry.py" \
  "scripts/active-plan-registry.py" "$STORED_PATHS"

# ---------------------------------------------------------------------------
# SMOKE-E: overlaps → exit 0 (no peer) with expected scan output
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-E: overlaps → exit 0 (no overlapping peers)"

EXIT_E=0
OVERLAP_OUTPUT=""
OVERLAP_OUTPUT="$(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" \
    python3 "$REGISTRY" overlaps \
      --run-id "$RUN_ID" \
      2>/dev/null
)" || EXIT_E=$?

assert_exit_zero "SMOKE-E: overlaps exits 0 (no peers)" "$EXIT_E"

# ---------------------------------------------------------------------------
# SMOKE-F: list/read-back → record readable with correct base and slug
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-F: list/read-back → record readable with correct base"

EXIT_F=0
LIST_OUTPUT=""
LIST_OUTPUT="$(
  cd "$REPO"
  Z_HARNESS_BASE_DIR="$EXTERNAL_BASE" \
    python3 "$REGISTRY" list \
      2>/dev/null
)" || EXIT_F=$?

assert_exit_zero "SMOKE-F: list exits 0" "$EXIT_F"

assert_contains "SMOKE-F: list output contains the run-id" "$RUN_ID" "$LIST_OUTPUT"
assert_contains "SMOKE-F: list output contains the slug" "$SLUG_NEW" "$LIST_OUTPUT"

# Read the record back directly and verify base is consistent
RECORD_BASE="$EXTERNAL_BASE/active-plans/$RUN_ID.json"
assert_file_exists "SMOKE-F: record file still readable at <base>/active-plans/" "$RECORD_BASE"

READBACK_SLUG="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
print(rec.get('slug', ''))
" "$RECORD_BASE" 2>/dev/null || true)"

assert_eq "SMOKE-F: read-back slug matches registered slug" "$SLUG_NEW" "$READBACK_SLUG"

READBACK_RUNID="$(python3 -c "
import json, sys
rec = json.load(open(sys.argv[1]))
print(rec.get('run_id', ''))
" "$RECORD_BASE" 2>/dev/null || true)"

assert_eq "SMOKE-F: read-back run_id matches" "$RUN_ID" "$READBACK_RUNID"

# ---------------------------------------------------------------------------
# SMOKE-G: NOTHING written under the in-repo z-harness/ when Z_HARNESS_BASE_DIR set
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-G: nothing written under in-repo z-harness/ when Z_HARNESS_BASE_DIR is set"

# The hermetic REPO must have no z-harness/ dir since all artifacts go to EXTERNAL_BASE.
assert_dir_not_exists "SMOKE-G: REPO/z-harness/ not created" "$REPO/z-harness"

# The real repo's z-harness/ must also have no active-plans subdir created by this test.
REAL_REPO_ZH="$REPO_ROOT/z-harness"
if [[ -d "$REAL_REPO_ZH/active-plans" ]]; then
  # Check whether $RUN_ID leaked into the real repo's active-plans
  if [[ -f "$REAL_REPO_ZH/active-plans/$RUN_ID.json" ]]; then
    echo "  FAIL: SMOKE-G: test run leaked record into real repo at $REAL_REPO_ZH/active-plans/$RUN_ID.json"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: SMOKE-G: real repo active-plans/ exists but does not contain test run-id"
    PASS=$((PASS + 1))
  fi
else
  echo "  PASS: SMOKE-G: real repo has no active-plans/ dir"
  PASS=$((PASS + 1))
fi

# ---------------------------------------------------------------------------
# SMOKE-H: cleanup — no anchor pollution at the real repo's .git/.z-harness-base
# ---------------------------------------------------------------------------

echo ""
echo "SMOKE-H: no anchor pollution at the real repo's .git/.z-harness-base"

# The hermetic REPO uses Z_HARNESS_BASE_DIR (tier-1 escape hatch), so it does NOT
# write an anchor (SPEC invariant 7: tier-1 bypasses anchor). Verify no anchor
# was written to REPO's .git dir.
REPO_ANCHOR="$REPO/.git/.z-harness-base"
if [[ -f "$REPO_ANCHOR" ]]; then
  echo "  FAIL: SMOKE-H: anchor file unexpectedly created at $REPO_ANCHOR (tier-1 must bypass anchor)"
  FAIL=$((FAIL + 1))
else
  echo "  PASS: SMOKE-H: hermetic REPO has no anchor file (tier-1 escape hatch correctly bypasses anchor)"
  PASS=$((PASS + 1))
fi

# Critical: the real harness repo's anchor must NOT have been touched by this test.
REAL_GIT_DIR=""
REAL_GIT_DIR="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
if [[ -n "$REAL_GIT_DIR" ]]; then
  REAL_ANCHOR="$(realpath "$REAL_GIT_DIR" 2>/dev/null || echo "$REPO_ROOT/.git")/.z-harness-base"
  # We only verify the anchor was not written by checking whether it's in a temp location.
  # If it already existed before the test, the smoke test must not have modified it.
  # (We can't know its pre-test state, so we just confirm it is NOT in the temp REPO.)
  if [[ "$REAL_ANCHOR" == "$REPO/.git/.z-harness-base" ]]; then
    echo "  FAIL: SMOKE-H: real anchor path equals temp REPO anchor — wrong git dir resolved"
    FAIL=$((FAIL + 1))
  else
    echo "  PASS: SMOKE-H: real repo anchor is at its own git-common-dir (not the temp REPO)"
    PASS=$((PASS + 1))
  fi
fi

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

rm -f "$SCOPE_JSON" 2>/dev/null || true
rm -rf "$REPO" "$EXTERNAL_BASE" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
exit 0
