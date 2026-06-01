#!/usr/bin/env bash
# test_scope_extract_fallback.sh — Tests for the mechanical scope-extractor fallback
#
# Run with:
#   bash scripts/test_scope_extract_fallback.sh
#
# Tests:
#   1. Mechanical fallback extracts **Files:** paths from TASKS.md
#   2. Output is valid JSON (array of objects with path/confidence/reason)
#   3. Each entry has confidence "explicit" and non-empty path
#   4. Known file paths from TASKS.md appear in the output
#   5. Empty TASKS.md produces an empty JSON array []

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPTS_DIR/.." && pwd)"

PASS=0
FAIL=0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_tmpdir() {
    mktemp -d /tmp/scope_test_XXXXXX
}

pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

# The mechanical fallback one-liner (mirrors exactly what scope-extractor.md documents)
run_fallback() {
    local tasks_md="$1"
    local base
    base="$(dirname "$tasks_md")"
    # Replicate the documented shell one-liner; use python3 -c for JSON assembly
    # since jq may not be present everywhere.
    # grep exits 1 on no match; treat that as an empty result (not an error).
    { grep -E '^\*\*Files:\*\*' "$tasks_md" || true; } \
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
}

# ---------------------------------------------------------------------------
# Test 1: Mechanical fallback extracts Files: paths
# ---------------------------------------------------------------------------
T="mechanical fallback extracts Files: paths from a real TASKS.md"

# The plan artifact dir is co-located in z-harness/active-plan-coordination/ within the main repo.
# The worktree root is a checkout of the active-plan-coordination branch; the TASKS.md for this
# plan lives in z-harness/active-plan-coordination/TASKS.md within the MAIN repo.
# Try several candidate locations.
ACTUAL_TASKS=""
for candidate in \
    "$REPO_ROOT/z-harness/active-plan-coordination/TASKS.md" \
    "$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)/z-harness/active-plan-coordination/TASKS.md" \
    "/Users/zeke/dev/z-harness/z-harness/active-plan-coordination/TASKS.md"; do
    if [[ -f "$candidate" ]]; then
        ACTUAL_TASKS="$candidate"
        break
    fi
done
if [[ ! -f "$ACTUAL_TASKS" ]]; then
    echo "SKIP: $T (TASKS.md not found at $ACTUAL_TASKS)"
else
    output="$(run_fallback "$ACTUAL_TASKS")"
    # Verify it's non-empty JSON array
    count="$(python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(len(d))" <<< "$output")"
    if [[ "$count" -gt 0 ]]; then
        pass "$T — got $count entries"
    else
        fail "$T — expected >0 entries, got 0"
    fi
fi

# ---------------------------------------------------------------------------
# Test 2: Output is valid JSON with required fields
# ---------------------------------------------------------------------------
T="fallback output is valid JSON with path/confidence/reason fields"

TMPDIR_2="$(_tmpdir)"
TASKS_2="$TMPDIR_2/TASKS.md"
cat > "$TASKS_2" <<'EOF'
# TASKS

## T001 — example task
**Files:** `scripts/plan-path.sh`, `scripts/log-event.sh`
**Depends:** none
Some description.
**Acceptance:** tests pass.

## T002 — another task
**Files:** `agents/scope-extractor.md` (NEW)
**Depends:** none
Another description.
**Acceptance:** agent file validates.
EOF

output="$(run_fallback "$TASKS_2")"
valid="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
all_valid = True
for item in data:
    if 'path' not in item or 'confidence' not in item or 'reason' not in item:
        all_valid = False
        break
    if item['confidence'] != 'explicit':
        all_valid = False
        break
    if not item['path']:
        all_valid = False
        break
print('ok' if all_valid else 'fail')
" <<< "$output")"

if [[ "$valid" == "ok" ]]; then
    pass "$T"
else
    fail "$T — output: $output"
fi
rm -rf "$TMPDIR_2"

# ---------------------------------------------------------------------------
# Test 3: Known paths appear in output
# ---------------------------------------------------------------------------
T="fallback output contains known paths from Files: lines"

TMPDIR_3="$(_tmpdir)"
TASKS_3="$TMPDIR_3/TASKS.md"
cat > "$TASKS_3" <<'EOF'
# TASKS

## T001 — example task
**Files:** `scripts/plan-path.sh`, `agents/scope-extractor.md` (NEW)
**Depends:** none
**Acceptance:** tests pass.
EOF

output="$(run_fallback "$TASKS_3")"
paths="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(' '.join(item['path'] for item in data))
" <<< "$output")"

if echo "$paths" | grep -q "scripts/plan-path.sh"; then
    pass "$T — scripts/plan-path.sh present"
else
    fail "$T — scripts/plan-path.sh missing from: $paths"
fi

if echo "$paths" | grep -q "agents/scope-extractor.md"; then
    pass "$T — agents/scope-extractor.md present"
else
    fail "$T — agents/scope-extractor.md missing from: $paths"
fi
rm -rf "$TMPDIR_3"

# ---------------------------------------------------------------------------
# Test 4: Parenthesized annotations are stripped from path tokens
# ---------------------------------------------------------------------------
T="annotations like (NEW) and (MODIFY) stripped from path tokens"

TMPDIR_4="$(_tmpdir)"
TASKS_4="$TMPDIR_4/TASKS.md"
cat > "$TASKS_4" <<'EOF'
# TASKS

## T001 — with annotations
**Files:** `commands/z-stats.md` (MODIFY), `docs/human/config.md` (NEW)
**Accepts:** pass.
EOF

output="$(run_fallback "$TASKS_4")"
paths="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(repr([item['path'] for item in data]))
" <<< "$output")"

# Paths must not contain "(MODIFY)" or "(NEW)" — check with python
clean="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
bad = [item['path'] for item in data if '(' in item['path'] or ')' in item['path']]
print('ok' if not bad else 'fail:' + str(bad))
" <<< "$output")"

if [[ "$clean" == "ok" ]]; then
    pass "$T"
else
    fail "$T — $clean"
fi
rm -rf "$TMPDIR_4"

# ---------------------------------------------------------------------------
# Test 5: Empty TASKS.md produces empty JSON array
# ---------------------------------------------------------------------------
T="empty TASKS.md produces empty JSON array"

TMPDIR_5="$(_tmpdir)"
TASKS_5="$TMPDIR_5/TASKS.md"
cat > "$TASKS_5" <<'EOF'
# TASKS

## T001 — no files line
**Depends:** none
**Acceptance:** pass.
EOF

output="$(run_fallback "$TASKS_5")"
result="$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
print(len(data))
" <<< "$output")"

if [[ "$result" == "0" ]]; then
    pass "$T — correctly returns []"
else
    fail "$T — expected 0 entries, got $result: $output"
fi
rm -rf "$TMPDIR_5"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi
exit 0
