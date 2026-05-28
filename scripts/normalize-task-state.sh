#!/usr/bin/env bash
# normalize-task-state.sh — Reset in-progress task markers to pending.
#
# Usage:
#   bash scripts/normalize-task-state.sh <plan-dir>
#   bash scripts/normalize-task-state.sh --self-test
#
# Reads <plan-dir>/TASKS.md and atomically replaces every "- [~]" line prefix
# with "- [ ]" (in-progress → pending). All other markers ([ ], [x]) are left
# unchanged.  Exits 0 always (best-effort).  Logs no events.
#
# Atomicity: writes to a sibling .tmp file and renames over the target so that
# a concurrent reader never sees a partial write.

set -uo pipefail

# ---------------------------------------------------------------------------
# Self-test mode
# ---------------------------------------------------------------------------

if [ "${1:-}" = "--self-test" ]; then
  PASS=0
  FAIL=0

  _assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [ "$actual" = "$expected" ]; then
      echo "  PASS: $label"
      PASS=$((PASS + 1))
    else
      echo "  FAIL: $label"
      printf "        expected: %s\n" "$expected"
      printf "        actual:   %s\n" "$actual"
      FAIL=$((FAIL + 1))
    fi
  }

  TMPDIR_ROOT="${TMPDIR:-/tmp}"

  # ---- Test 1: [~] reverted, [ ] and [x] unchanged -----------------------

  TD1="$(mktemp -d "${TMPDIR_ROOT}/normalize_task_state_t1_XXXXXX")"
  cat >"$TD1/TASKS.md" <<'EOF'
## T001
- [ ] pending task
- [x] completed task
- [~] in-progress task
- [ ] another pending
- [~] second in-progress
EOF

  bash "$0" "$TD1"
  RESULT1="$(cat "$TD1/TASKS.md")"

  EXPECTED1="## T001
- [ ] pending task
- [x] completed task
- [ ] in-progress task
- [ ] another pending
- [ ] second in-progress"

  _assert_eq "mixed markers: only [~] reverted to [ ]" "$EXPECTED1" "$RESULT1"
  rm -rf "$TD1"

  # ---- Test 2: idempotent — no [~] present means file is unchanged --------

  TD2="$(mktemp -d "${TMPDIR_ROOT}/normalize_task_state_t2_XXXXXX")"
  CLEAN_CONTENT="## T001
- [ ] pending
- [x] done"
  printf '%s\n' "$CLEAN_CONTENT" >"$TD2/TASKS.md"
  MTIME_BEFORE="$(stat -f '%m' "$TD2/TASKS.md" 2>/dev/null || stat -c '%Y' "$TD2/TASKS.md" 2>/dev/null)"

  bash "$0" "$TD2"
  RESULT2="$(cat "$TD2/TASKS.md")"

  _assert_eq "idempotent: already-clean file content unchanged" "$CLEAN_CONTENT" "$RESULT2"
  rm -rf "$TD2"

  # ---- Test 3: missing TASKS.md — exits 0 ---------------------------------

  TD3="$(mktemp -d "${TMPDIR_ROOT}/normalize_task_state_t3_XXXXXX")"
  EXIT3=0
  bash "$0" "$TD3" || EXIT3=$?
  _assert_eq "missing TASKS.md: exits 0" "0" "$EXIT3"
  rm -rf "$TD3"

  # ---- Test 4: [x] markers are never touched ------------------------------

  TD4="$(mktemp -d "${TMPDIR_ROOT}/normalize_task_state_t4_XXXXXX")"
  cat >"$TD4/TASKS.md" <<'EOF'
- [x] done
- [x] also done
EOF
  bash "$0" "$TD4"
  RESULT4="$(cat "$TD4/TASKS.md")"
  EXPECTED4="- [x] done
- [x] also done"
  _assert_eq "[x] markers untouched" "$EXPECTED4" "$RESULT4"
  rm -rf "$TD4"

  # ---- Summary -------------------------------------------------------------

  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  if [ "$FAIL" -gt 0 ]; then
    exit 1
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# Main: normalize a plan directory
# ---------------------------------------------------------------------------

PLAN_DIR="${1:-}"

if [ -z "$PLAN_DIR" ]; then
  echo "Usage: $0 <plan-dir> | --self-test" >&2
  exit 0
fi

TASKS_FILE="$PLAN_DIR/TASKS.md"

if [ ! -f "$TASKS_FILE" ]; then
  # Best-effort: nothing to normalize; exit cleanly.
  exit 0
fi

TMP_FILE="${TASKS_FILE}.tmp.$$"

# Replace "- [~]" at the start of any line with "- [ ]".
# The sed expression is intentionally narrow: only the exact prefix "- [~] "
# or "- [~]" at end of line is targeted, to avoid touching embedded text.
if sed 's/^- \[~\]/- [ ]/g' "$TASKS_FILE" >"$TMP_FILE" 2>/dev/null; then
  mv -f "$TMP_FILE" "$TASKS_FILE" || rm -f "$TMP_FILE"
else
  rm -f "$TMP_FILE"
fi

exit 0
