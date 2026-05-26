#!/usr/bin/env bash
# Helper called by /z-implement-all and /z-review-all.
# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
#
# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
#   parent_command: implement-all | review-all
#
# Exit 0 always (skip is success).
# Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md, TAGS.txt

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "STATUS: skipped missing_args"
  exit 0
fi

RUN="$1"
PARENT_COMMAND="$2"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"

# Resolve plan base dir — must be absolute
BASE="${Z_HARNESS_PLAN_DIR:-}"
if [[ -z "$BASE" ]]; then
  echo "STATUS: skipped no_plan_dir"
  exit 0
fi

# Normalize BASE to an absolute path
if [[ -d "$BASE" ]]; then
  BASE="$(cd "$BASE" && pwd)"
else
  # Directory doesn't exist yet; prefix with REPO_ROOT if relative
  case "$BASE" in
    /*) ;;  # already absolute
    *) BASE="$REPO_ROOT/$BASE" ;;
  esac
fi

RUN_DIR="$BASE/archive/$RUN"
mkdir -p "$RUN_DIR"

# --- Skip-condition 1: empty diff ---
# Resolve a valid base ref: prefer origin/main merge-base, then HEAD~5, then empty-tree.
EMPTY_TREE="4b825dc642cb6eb9a060e54bf8d69288fbee4904"
BASE_REF=""

MERGE_BASE="$(git merge-base HEAD origin/main 2>/dev/null || true)"
if [[ -n "$MERGE_BASE" ]] && git rev-parse --verify "${MERGE_BASE}^{commit}" >/dev/null 2>&1; then
  BASE_REF="$MERGE_BASE"
elif git rev-parse --verify "HEAD~5^{commit}" >/dev/null 2>&1; then
  BASE_REF="HEAD~5"
else
  BASE_REF="$EMPTY_TREE"
fi

# Test emptiness without loading the diff into memory, then stream to file.
if git diff --quiet "${BASE_REF}..HEAD" 2>/dev/null; then
  echo "STATUS: skipped empty_diff"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "phase_end" \
      '{"name":"memory_review","skipped":true,"skip_reason":"empty_diff"}' || true
  fi
  exit 0
fi

# --- Skip-condition 2: zero completed tasks and parent is implement-all ---
TASKS_FILE="$BASE/TASKS.md"
if [[ -f "$TASKS_FILE" && "$PARENT_COMMAND" == "implement-all" ]]; then
  COMPLETED_COUNT="$(grep -c '\[x\]' "$TASKS_FILE" 2>/dev/null || true)"
  COMPLETED_COUNT="${COMPLETED_COUNT:-0}"
  COMPLETED_COUNT="$(printf '%s' "$COMPLETED_COUNT" | tr -d '[:space:]')"
  if [[ "${COMPLETED_COUNT:-0}" -eq 0 ]]; then
    echo "STATUS: skipped all_tasks_skipped"
    if [[ -x "$LOG_EVENT" ]]; then
      bash "$LOG_EVENT" "$RUN" "phase_end" \
        '{"name":"memory_review","skipped":true,"skip_reason":"all_tasks_skipped"}' || true
    fi
    exit 0
  fi
fi

# --- Verify TAGS.txt exists ---
TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
if [[ ! -f "$TAGS_FILE" ]]; then
  echo "STATUS: skipped tags_missing"
  if [[ -x "$LOG_EVENT" ]]; then
    bash "$LOG_EVENT" "$RUN" "review_agent_failed" \
      '{"reason":"tags_missing"}' || true
  fi
  exit 0
fi

# --- Write cumulative diff (truncated to 5000 lines, streamed to avoid loading into memory) ---
DIFF_FILE="$RUN_DIR/cumulative.diff"
# Disable pipefail to tolerate SIGPIPE when diff output is shorter than 5000 lines.
set +o pipefail
git diff "${BASE_REF}..HEAD" | head -n 5000 > "$DIFF_FILE"
set -o pipefail

# --- Print ready + artifact paths (all absolute) ---
echo "STATUS: ready"
echo "$DIFF_FILE"
echo "$BASE/SPEC.md"
echo "$TAGS_FILE"

exit 0
