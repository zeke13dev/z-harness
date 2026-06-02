#!/usr/bin/env bash
# run-status.sh — classify the terminal state of a z-harness run.
#
# Subcommands:
#   classify <run-id-or-path> [--command <name>]
#       Prints exactly one of: clean | halted | errored | unknown
#       Exits 0.
#   last-event <run-id-or-path>
#       Prints the last valid JSON event from events.jsonl.
#       Exits 0.
#
# Layout resolution uses scripts/plan-path.sh.  Both canonical
# (z-harness/plans/<slug>/archive/<run>/) and legacy
# (z-harness/<slug>/archive/<run>/) layouts are supported.
#
# Classification rules (per SPEC C6 REWRITTEN):
#   CLEAN events (explicit allowlist):
#     run_end, amend_run_end, audit_run_end, brainstorm_run_end,
#     debug_run_end, light_run_end, plan_audit_end, plan_split_run_end,
#     research_run_end, review_all_end, review_end, test_plan_end,
#     init_docs_end, maintain_docs_end, doc_update_end, cluster_planner_end
#   HALT events (explicit allowlist):
#     task_halt, docs_freshness_halt, docs_staleness_halt,
#     askuser_halted, unknown_ask_blocked, plan_halt, review_halt,
#     implement_all_halt, slug_collision_halt, overnight_lock_corrupt
#   ERROR events (pattern): *_error or "fatal"
#
# /z-implement-all special case (--command implement-all):
#   Clean only when BOTH:
#     (a) last event kind ∈ {implement_end, compaction_pause}
#     (b) every task in $BASE/TASKS.md is [x] or [~]
#   Last event ∈ halt events → halted
#   Otherwise → unknown

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Source plan-path helpers
# shellcheck source=scripts/plan-path.sh
source "$SCRIPTS_DIR/plan-path.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Resolve the events.jsonl path for a run-id-or-path argument.
# Accepts:
#   - absolute path to the run dir or to events.jsonl directly
#   - <run-id> (looks for it under any known layout root)
resolve_events_file() {
  local arg="$1"

  # If the arg is an absolute path to events.jsonl itself
  if [[ "$arg" == *.jsonl && -f "$arg" ]]; then
    echo "$arg"
    return 0
  fi

  # If the arg is an absolute path to a directory
  if [[ "$arg" == /* && -d "$arg" ]]; then
    echo "$arg/events.jsonl"
    return 0
  fi

  # If the arg is a relative path that exists as a directory from repo root
  if [[ -d "$REPO_ROOT/$arg" ]]; then
    echo "$REPO_ROOT/$arg/events.jsonl"
    return 0
  fi

  # Try to find the run-id under known archive locations.
  # Use plan-path.sh helpers so Z_HARNESS_PLANS_DIR overrides are respected.
  #
  # plan_dir <slug> returns either a relative or absolute path (absolute when
  # Z_HARNESS_PLANS_DIR is an absolute path).  We derive the plans root by
  # calling plan_dir with a sentinel slug and stripping the slug suffix.
  local _sentinel_canonical_raw
  _sentinel_canonical_raw="$(plan_dir "__sentinel__")"
  # Make absolute: if it's already absolute, leave it; otherwise prepend REPO_ROOT.
  local _sentinel_canonical
  if [[ "$_sentinel_canonical_raw" == /* ]]; then
    _sentinel_canonical="$_sentinel_canonical_raw"
  else
    _sentinel_canonical="$REPO_ROOT/$_sentinel_canonical_raw"
  fi
  local canonical_plans_root
  canonical_plans_root="$(dirname "$_sentinel_canonical")"

  local _sentinel_legacy_raw
  _sentinel_legacy_raw="$(legacy_plan_dir "__sentinel__")"
  local _sentinel_legacy
  if [[ "$_sentinel_legacy_raw" == /* ]]; then
    _sentinel_legacy="$_sentinel_legacy_raw"
  else
    _sentinel_legacy="$REPO_ROOT/$_sentinel_legacy_raw"
  fi
  local legacy_plans_root
  legacy_plans_root="$(dirname "$_sentinel_legacy")"

  # Canonical layout: <plans-root>/<slug>/archive/<run>/
  local found
  found="$(find "$canonical_plans_root" -maxdepth 3 -type d -name "$arg" 2>/dev/null | head -1)"
  if [[ -n "$found" ]]; then
    echo "$found/events.jsonl"
    return 0
  fi

  # Legacy layout: z-harness/<slug>/archive/<run>/
  found="$(find "$legacy_plans_root" -maxdepth 3 -type d -name "$arg" 2>/dev/null | head -1)"
  if [[ -n "$found" ]]; then
    echo "$found/events.jsonl"
    return 0
  fi

  # Fall back: global archive <base>/archive/<run>/
  local _zh_base
  _zh_base="$(z_harness_base 2>/dev/null || echo "$REPO_ROOT/z-harness")"
  if [[ -d "$_zh_base/archive/$arg" ]]; then
    echo "$_zh_base/archive/$arg/events.jsonl"
    return 0
  fi

  # Return the best-guess path even if it doesn't exist (caller handles missing)
  echo "$_zh_base/archive/$arg/events.jsonl"
}

# Resolve the $BASE directory for a run-id-or-path argument (for TASKS.md lookup).
resolve_base_dir() {
  local events_file="$1"
  # events_file is <base>/archive/<run>/events.jsonl
  # base is three levels up from events.jsonl
  local run_dir
  run_dir="$(dirname "$events_file")"
  local archive_dir
  archive_dir="$(dirname "$run_dir")"
  dirname "$archive_dir"
}

# Read the last N=20 lines of events.jsonl, find the last valid JSON line,
# and print it. Returns empty string if none found.
last_valid_event() {
  local events_file="$1"

  if [[ ! -f "$events_file" ]]; then
    echo ""
    return 0
  fi

  # Read last 20 lines; iterate in reverse to find the latest valid JSON
  local last_valid=""
  while IFS= read -r line; do
    # Skip empty lines
    [[ -z "$line" ]] && continue
    # Try to parse as JSON
    if printf '%s' "$line" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
      last_valid="$line"
    fi
  done < <(tail -n 20 "$events_file")

  echo "$last_valid"
}

# Extract the "kind" field from a JSON event string.
event_kind() {
  local event="$1"
  printf '%s' "$event" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("kind",""))' 2>/dev/null || echo ""
}

# Check whether every task in TASKS.md is [x] or [~] (done or skipped).
# Returns 0 if all done/skipped (or no tasks), 1 if any are pending/in-progress.
all_tasks_done() {
  local tasks_file="$1"

  if [[ ! -f "$tasks_file" ]]; then
    # No TASKS.md — cannot confirm done; treat as incomplete
    return 1
  fi

  # Require at least one task checkbox; a file with zero checkboxes is treated
  # as incomplete (guards against malformed or wrong TASKS.md).
  local total
  total="$(grep -E '^\s*-\s*\[' "$tasks_file" | wc -l | tr -d ' ')"
  if [[ "$total" -eq 0 ]]; then
    return 1
  fi

  # Find any task checkbox that is NOT [x] or [~]
  # Matches lines like "- [ ] ..." or "- [?] ..." etc.
  local pending
  pending="$(grep -E '^\s*-\s*\[' "$tasks_file" | grep -vE '^\s*-\s*\[[x~]\]' | wc -l | tr -d ' ')"
  if [[ "$pending" -eq 0 ]]; then
    return 0
  fi
  return 1
}

# Classify based on event kind using the allowlists.
classify_by_kind() {
  local kind="$1"

  # Clean terminal event kinds (explicit allowlist)
  case "$kind" in
    run_end|amend_run_end|audit_run_end|brainstorm_run_end|\
    debug_run_end|light_run_end|plan_audit_end|plan_split_run_end|\
    research_run_end|review_all_end|review_end|test_plan_end|\
    init_docs_end|maintain_docs_end|doc_update_end|cluster_planner_end)
      echo "clean"
      return 0
      ;;
  esac

  # Halt terminal event kinds (explicit allowlist)
  case "$kind" in
    task_halt|docs_freshness_halt|docs_staleness_halt|\
    askuser_halted|unknown_ask_blocked|plan_halt|review_halt|\
    implement_all_halt|slug_collision_halt|overnight_lock_corrupt)
      echo "halted"
      return 0
      ;;
  esac

  # Error terminal: "fatal" exact match or *_error suffix
  if [[ "$kind" == "fatal" || "$kind" == *_error ]]; then
    echo "errored"
    return 0
  fi

  echo "unknown"
}

# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

cmd_last_event() {
  local arg="$1"
  local events_file
  events_file="$(resolve_events_file "$arg")"

  local event
  event="$(last_valid_event "$events_file")"

  if [[ -z "$event" ]]; then
    echo "null"
  else
    echo "$event"
  fi
}

cmd_classify() {
  local arg="$1"
  local command_name="${2:-}"

  local events_file
  events_file="$(resolve_events_file "$arg")"

  # Handle missing file
  if [[ ! -f "$events_file" ]]; then
    echo "unknown"
    return 0
  fi

  # Handle empty file
  if [[ ! -s "$events_file" ]]; then
    echo "unknown"
    return 0
  fi

  local last_event
  last_event="$(last_valid_event "$events_file")"

  # No valid JSON events found
  if [[ -z "$last_event" ]]; then
    echo "unknown"
    return 0
  fi

  local kind
  kind="$(event_kind "$last_event")"

  # /z-implement-all special case
  if [[ "$command_name" == "implement-all" ]]; then
    # First check for halt events (takes priority)
    case "$kind" in
      task_halt|docs_freshness_halt|docs_staleness_halt|\
      askuser_halted|unknown_ask_blocked|plan_halt|review_halt|\
      implement_all_halt|slug_collision_halt|overnight_lock_corrupt)
        echo "halted"
        return 0
        ;;
    esac
    if [[ "$kind" == "fatal" || "$kind" == *_error ]]; then
      echo "errored"
      return 0
    fi
    # Clean requires both conditions: last event is implement_end or compaction_pause
    # AND all tasks are done
    if [[ "$kind" == "implement_end" || "$kind" == "compaction_pause" ]]; then
      local base_dir tasks_file
      base_dir="$(resolve_base_dir "$events_file")"
      tasks_file="$base_dir/TASKS.md"
      if all_tasks_done "$tasks_file"; then
        echo "clean"
        return 0
      fi
    fi
    echo "unknown"
    return 0
  fi

  # Standard classification
  classify_by_kind "$kind"
}

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  if [[ $# -lt 2 ]]; then
    echo "Usage: $0 {classify|last-event} <run-id-or-path> [--command <name>]" >&2
    exit 2
  fi

  subcmd="$1"
  shift

  case "$subcmd" in
    classify)
      run_arg="$1"
      shift
      command_name=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --command)
            shift
            command_name="${1:-}"
            shift
            ;;
          *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
        esac
      done
      cmd_classify "$run_arg" "$command_name"
      ;;
    last-event)
      cmd_last_event "$1"
      ;;
    *)
      echo "Unknown subcommand: $subcmd" >&2
      echo "Usage: $0 {classify|last-event} <run-id-or-path> [--command <name>]" >&2
      exit 2
      ;;
  esac
fi
