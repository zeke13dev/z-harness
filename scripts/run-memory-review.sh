#!/usr/bin/env bash
# Helper called by /z-implement-all, /z-review-all, and /z-debug.
# Encapsulates the review-agent lifecycle skip-conditions and artifact prep.
#
# Usage: bash scripts/run-memory-review.sh <RUN> <parent_command>
#   parent_command: implement-all | review-all | debug
#
# Exit 0 always (skip is success).
# Stdout line 1 is always: STATUS: ready | STATUS: skipped <reason>
# If ready, lines 2-4 are absolute paths to: cumulative.diff, SPEC.md (or empty if missing), TAGS.txt
# Line 5 (debug parent only): absolute path to DEBUG.md

set -euo pipefail

# Resolve REPO_ROOT, PLUGIN_ROOT, LOG_EVENT, and SLUG first so the missing_args
# early-exit path can use them before RUN/PARENT_COMMAND are parsed.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$REPO_ROOT}}"
LOG_EVENT="$PLUGIN_ROOT/scripts/log-event.sh"
SLUG="${Z_HARNESS_SLUG:-}"

# _build_terminal_payload <state> <skip_reason_raw> <parent_command_raw> <slug_raw>
# Builds a JSON payload string. Uses python3 when available; falls back to pure bash.
_build_terminal_payload() {
  local state="$1" skip_reason_raw="$2" parent_command_raw="$3" slug_raw="$4"
  if python3 -c '' 2>/dev/null; then
    python3 -c '
import json, sys
state, skip_reason_raw, parent_command_raw, slug_raw = sys.argv[1:5]
skip_reason = None if skip_reason_raw == "null" else skip_reason_raw
parent_command = None if not parent_command_raw else parent_command_raw
slug = None if not slug_raw else slug_raw
print(json.dumps({
  "state": state,
  "skip_reason": skip_reason,
  "parent_command": parent_command,
  "candidates": 0,
  "accepted": 0,
  "slug": slug
}))
' "$state" "$skip_reason_raw" "$parent_command_raw" "$slug_raw"
  else
    # Pure-bash fallback — no special characters in these values so no escaping needed.
    local skip_json parent_json slug_json
    [[ "$skip_reason_raw" == "null" ]] && skip_json="null" || skip_json="\"$skip_reason_raw\""
    [[ -z "$parent_command_raw" ]] && parent_json="null" || parent_json="\"$parent_command_raw\""
    [[ -z "$slug_raw" ]] && slug_json="null" || slug_json="\"$slug_raw\""
    printf '{"state":"%s","skip_reason":%s,"parent_command":%s,"candidates":0,"accepted":0,"slug":%s}' \
      "$state" "$skip_json" "$parent_json" "$slug_json"
  fi
}

if [[ $# -lt 2 ]]; then
  echo "STATUS: skipped missing_args"
  # Attempt to emit terminal event; degrade gracefully if log-event.sh is unavailable.
  if [[ -x "$LOG_EVENT" ]]; then
    _PAYLOAD="$(_build_terminal_payload "skipped_broken_context" "missing_args" "" "$SLUG")" || true
    [[ -n "${_PAYLOAD:-}" ]] && bash "$LOG_EVENT" "unknown" "memory_review_terminal" "$_PAYLOAD" || true
  fi
  exit 0
fi

RUN="$1"
PARENT_COMMAND="$2"

# emit_terminal <state> <skip_reason>
# Emits a single memory_review_terminal event. skip_reason may be "null" for the null literal.
emit_terminal() {
  local state="$1"
  local skip_reason="$2"
  if [[ -x "$LOG_EVENT" ]]; then
    local payload
    payload="$(_build_terminal_payload "$state" "$skip_reason" "$PARENT_COMMAND" "$SLUG")" || true
    [[ -n "${payload:-}" ]] && bash "$LOG_EVENT" "$RUN" "memory_review_terminal" "$payload" || true
  fi
}

# Resolve plan base dir — must be absolute
BASE="${Z_HARNESS_PLAN_DIR:-}"
if [[ -z "$BASE" ]]; then
  echo "STATUS: skipped no_plan_dir"
  emit_terminal "skipped_broken_context" "no_plan_dir"
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
  emit_terminal "not_applicable" "empty_diff"
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
    emit_terminal "not_applicable" "all_tasks_skipped"
    exit 0
  fi
fi

# --- Skip-condition 3: debug parent requires DEBUG.md to exist and be readable ---
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  DEBUG_MD="$BASE/DEBUG.md"
  if [[ ! -r "$DEBUG_MD" ]]; then
    echo "STATUS: skipped debug_md_missing"
    emit_terminal "not_applicable" "debug_md_missing"
    exit 0
  fi
fi

# --- Verify TAGS.txt exists ---
TAGS_FILE="$REPO_ROOT/docs/llm/TAGS.txt"
if [[ ! -f "$TAGS_FILE" ]]; then
  echo "STATUS: skipped tags_missing"
  emit_terminal "skipped_broken_context" "tags_missing"
  exit 0
fi

# --- Write cumulative diff (truncated to 5000 lines, streamed to avoid loading into memory) ---
DIFF_FILE="$RUN_DIR/cumulative.diff"
# Disable pipefail to tolerate SIGPIPE when diff output is shorter than 5000 lines.
set +o pipefail
git diff "${BASE_REF}..HEAD" | head -n 5000 > "$DIFF_FILE"
set -o pipefail

# --- Print ready + artifact paths (all absolute) ---
# On STATUS: ready, no terminal event is emitted — orchestrator owns it after dispatch.
echo "STATUS: ready"
echo "$DIFF_FILE"
if [[ -f "$BASE/SPEC.md" ]]; then
  echo "$BASE/SPEC.md"
else
  echo ""
fi
echo "$TAGS_FILE"
if [[ "$PARENT_COMMAND" == "debug" ]]; then
  echo "$BASE/DEBUG.md"
fi

# --- Emit AXIOM_READY when axioms.auto_extract_post_run is enabled (default on) ---
# Gating: "false" suppresses; "true" (or config unavailable) = emit.
_AXIOM_EXTRACT="$(python3 "$PLUGIN_ROOT/scripts/config.py" get axioms.auto_extract_post_run 2>/dev/null || echo "true")"
if [[ "$_AXIOM_EXTRACT" != "false" ]]; then
  echo "AXIOM_READY $DIFF_FILE"
fi

exit 0
