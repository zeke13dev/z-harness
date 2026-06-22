#!/usr/bin/env bash
# audit-preview-misses.sh — Flash false-negative audit harness
#
# Samples low-tier tasks where Flash gated codex out (review_gated_down events),
# re-runs the codex reviewer on the same diff, and records whether codex would
# have found blockers/majors that Flash missed (Flash miss rate).
#
# Usage:
#   audit-preview-misses.sh [--slug <slug>] [--metrics <path>] [--sample N]
#                            [--report <path>] [--demo]
#
# Options:
#   --slug <slug>     Plan slug to scope the diff archive lookup (default: auto-detect
#                     from Z_HARNESS_PLAN_DIR or the plan the gated event belongs to)
#   --metrics <path>  Explicit path to metrics.jsonl (default: auto-resolved via
#                     plan-path.sh base_dir, same pattern as estimate-tokens.py)
#   --sample N        Max number of gated-out tasks to re-review (default: all)
#   --report <path>   Write the report to this file in addition to stdout
#                     (default: stdout only)
#   --demo            Inject a synthetic review_gated_down event so the script
#                     exercises its full flow even before the knob has been enabled.
#                     Reads the most recent archived diff.patch it can find.
#
# Exit codes:
#   0  completed successfully (zero or more gated tasks found)
#   1  fatal error (metrics unreadable, no codex available, etc.)
#
# READ-ONLY invariant:
#   This script never mutates TASKS.md, plan state, or production event streams.
#   The optional --report file is the only write. A timestamped notice is appended
#   to the report noting it is an offline analysis artifact.
#
# Evidence gate context:
#   Z_HARNESS_IMPL_PRE_REVIEW (default 0) must be enabled and some low-tier tasks
#   run before real review_gated_down events appear. Until then, --demo mode or a
#   graceful "no events found" message is the expected output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

SLUG=""
METRICS_PATH=""
SAMPLE_N=""
REPORT_PATH=""
DEMO_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug)
      SLUG="$2"; shift 2 ;;
    --metrics)
      METRICS_PATH="$2"; shift 2 ;;
    --sample)
      SAMPLE_N="$2"; shift 2 ;;
    --report)
      REPORT_PATH="$2"; shift 2 ;;
    --demo)
      DEMO_MODE=1; shift ;;
    -h|--help)
      sed -n '3,30p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
      exit 0 ;;
    *)
      printf 'audit-preview-misses: unknown argument: %s\n' "$1" >&2
      exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Metrics path resolution (mirrors estimate-tokens.py _default_metrics_path)
# ---------------------------------------------------------------------------

if [[ -z "$METRICS_PATH" ]]; then
  if [[ -n "${Z_HARNESS_BASE_DIR:-}" ]]; then
    METRICS_PATH="${Z_HARNESS_BASE_DIR}/metrics.jsonl"
  else
    RESOLVED_BASE="$(bash "$SCRIPT_DIR/plan-path.sh" base_dir 2>/dev/null)" || RESOLVED_BASE=""
    if [[ -n "$RESOLVED_BASE" ]]; then
      METRICS_PATH="${RESOLVED_BASE}/metrics.jsonl"
    else
      METRICS_PATH="${REPO_ROOT}/z-harness/metrics.jsonl"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Resolve codex command via providers (reviewer role)
# ---------------------------------------------------------------------------

_resolve_reviewer_command() {
  local descriptor
  descriptor="$(python3 "$SCRIPT_DIR/resolve-provider.py" reviewer 2>/dev/null)" || {
    printf 'audit-preview-misses: resolve-provider.py reviewer failed — is reviewer configured in .z-harness/providers.json?\n' >&2
    return 1
  }
  printf '%s' "$descriptor"
}

_json_field() {
  local json="$1" field="$2"
  printf '%s' "$json" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d.get('$field',''))"
}

_json_list_field() {
  local json="$1" field="$2"
  printf '%s' "$json" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(' '.join(str(x) for x in d.get('$field',[])))"
}

# ---------------------------------------------------------------------------
# Load review_gated_down events from metrics
# ---------------------------------------------------------------------------

_load_gated_events() {
  local metrics="$1"
  if [[ ! -f "$metrics" ]]; then
    printf ''
    return 0
  fi
  grep '"review_gated_down"' "$metrics" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Parse a gated event JSON line → fields
# ---------------------------------------------------------------------------

_event_field() {
  local line="$1" field="$2"
  printf '%s' "$line" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d.get('$field',''))" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Find the diff.patch for a given task id + slug context
# ---------------------------------------------------------------------------

_find_diff() {
  local task_id="$1"
  local hint_slug="$2"  # may be empty

  # Strategy 1: use the hint slug directly
  if [[ -n "$hint_slug" ]]; then
    local candidate
    candidate="$(bash "$SCRIPT_DIR/plan-path.sh" plan_dir "$hint_slug" 2>/dev/null)" || candidate=""
    if [[ -n "$candidate" && -f "$candidate/archive/tasks/${task_id}/diff.patch" ]]; then
      printf '%s' "$candidate/archive/tasks/${task_id}/diff.patch"
      return 0
    fi
  fi

  # Strategy 2: scan all known plans for this task archive
  local base_dir
  base_dir="$(bash "$SCRIPT_DIR/plan-path.sh" base_dir 2>/dev/null)" || base_dir=""
  if [[ -n "$base_dir" ]]; then
    # New layout: <base>/plans/<slug>/archive/tasks/<id>/diff.patch
    local found
    found="$(find "$base_dir/plans" -path "*/archive/tasks/${task_id}/diff.patch" 2>/dev/null | head -1)" || true
    if [[ -n "$found" ]]; then
      printf '%s' "$found"
      return 0
    fi
  fi

  return 1
}

# ---------------------------------------------------------------------------
# Run the codex reviewer on a diff.patch and return the response
# ---------------------------------------------------------------------------

_run_codex_review() {
  local task_id="$1"
  local diff_path="$2"
  local descriptor="$3"

  local provider command args use_stdin timeout_s
  provider="$(_json_field "$descriptor" provider)"
  command="$(_json_field "$descriptor" command)"
  args="$(_json_list_field "$descriptor" args_template)"
  use_stdin="$(_json_field "$descriptor" stdin)"
  timeout_s="$(_json_field "$descriptor" timeout_s)"
  timeout_s="${timeout_s:-120}"

  local diff_content
  diff_content="$(cat "$diff_path" 2>/dev/null)" || diff_content="(diff.patch unreadable)"

  local prompt
  prompt="$(cat <<EOF
You are performing a code review on task ${task_id}.

This is a Flash false-negative audit: Flash previously reviewed this task and found no blockers or majors. You are being asked to review the same diff independently to check whether Flash missed anything significant.

Diff:

${diff_content}

Scrutinize this code rigorously. Focus on:
1. Bugs or correctness issues
2. Spec violations or missed acceptance criteria
3. Missed edge cases / error handling gaps
4. DRY / KISS / SOLID violations
5. Security concerns

OUTPUT FORMAT — respect strictly:
- Report blockers and majors only. Skip minors and nits.
- For each finding: severity (blocker/major), location, and a suggested fix.
- If no blockers or majors: respond with exactly: VERDICT: CLEAN
- If findings exist: start with VERDICT: ISSUES_FOUND then list findings.
- Total response under 4000 characters.
EOF
)"

  # Codex capability probe for --output-last-message
  local probe_sentinel="/tmp/z-harness-codex-outfile-probe.${PPID:-$$}"
  local codex_supports_outfile=0
  if [[ ! -f "$probe_sentinel" ]]; then
    if "$command" exec --help 2>&1 | grep -q 'output-last-message' 2>/dev/null; then
      printf '1' > "$probe_sentinel"
    else
      printf '0' > "$probe_sentinel"
    fi
  fi
  codex_supports_outfile="$(cat "$probe_sentinel" 2>/dev/null || printf '0')"

  local response=""
  local exit_code=0

  # Timeout wrapper
  local timeout_cmd=""
  if command -v timeout &>/dev/null; then
    timeout_cmd="timeout"
  elif command -v gtimeout &>/dev/null; then
    timeout_cmd="gtimeout"
  fi

  if [[ "$provider" = "codex" && "$codex_supports_outfile" = "1" ]]; then
    local outfile
    outfile="$(mktemp /tmp/audit-preview-misses-review.XXXXXX)"
    if [[ "$use_stdin" = "True" ]]; then
      if [[ -n "$timeout_cmd" ]]; then
        printf '%s' "$prompt" | "$timeout_cmd" "$timeout_s" $command $args -o "$outfile" 2>/dev/null || exit_code=$?
      else
        printf '%s' "$prompt" | $command $args -o "$outfile" 2>/dev/null || exit_code=$?
      fi
    else
      if [[ -n "$timeout_cmd" ]]; then
        "$timeout_cmd" "$timeout_s" $command $args -o "$outfile" "$prompt" 2>/dev/null || exit_code=$?
      else
        $command $args -o "$outfile" "$prompt" 2>/dev/null || exit_code=$?
      fi
    fi
    if [[ -s "$outfile" ]]; then
      response="$(cat "$outfile")"
    fi
    rm -f "$outfile"
  else
    if [[ "$use_stdin" = "True" ]]; then
      if [[ -n "$timeout_cmd" ]]; then
        response="$(printf '%s' "$prompt" | "$timeout_cmd" "$timeout_s" $command $args 2>/dev/null)" || exit_code=$?
      else
        response="$(printf '%s' "$prompt" | $command $args 2>/dev/null)" || exit_code=$?
      fi
    else
      if [[ -n "$timeout_cmd" ]]; then
        response="$("$timeout_cmd" "$timeout_s" $command $args "$prompt" 2>/dev/null)" || exit_code=$?
      else
        response="$($command $args "$prompt" 2>/dev/null)" || exit_code=$?
      fi
    fi
  fi

  if [[ $exit_code -ne 0 && -z "$response" ]]; then
    printf 'REVIEW_ERROR: codex exited %d with no output\n' "$exit_code"
    return 0
  fi

  printf '%s' "$response"
}

# ---------------------------------------------------------------------------
# Extract verdict from codex response
# ---------------------------------------------------------------------------

_extract_verdict() {
  local response="$1"
  # Check CLEAN signals FIRST — before any loose keyword matches.
  # Codex may emit "No blockers or majors found" which contains the substring
  # "blockers"; checking the loose regex first would misclassify those as
  # ISSUES_FOUND (false inflation of the miss rate).
  if printf '%s' "$response" | grep -q 'VERDICT:[[:space:]]*CLEAN'; then
    printf 'CLEAN'
  elif printf '%s' "$response" | grep -qiE 'no blockers (or majors found|found)|no majors'; then
    printf 'CLEAN'
  elif printf '%s' "$response" | grep -q 'VERDICT:[[:space:]]*ISSUES_FOUND'; then
    printf 'ISSUES_FOUND'
  elif printf '%s' "$response" | grep -qiE '(blocker|major)'; then
    printf 'ISSUES_FOUND'
  elif printf '%s' "$response" | grep -q 'REVIEW_ERROR'; then
    printf 'ERROR'
  else
    printf 'UNKNOWN'
  fi
}

# ---------------------------------------------------------------------------
# Demo mode: inject a synthetic gated event
# ---------------------------------------------------------------------------

_synthetic_gated_events() {
  # Find the most recent diff.patch we can locate across all plans
  local base_dir
  base_dir="$(bash "$SCRIPT_DIR/plan-path.sh" base_dir 2>/dev/null)" || base_dir=""
  local demo_diff="" demo_task="" demo_slug=""

  if [[ -n "$base_dir" ]]; then
    local found_diff
    # Only consider the canonical structure: plans/<slug>/archive/tasks/<id>/diff.patch
    # (4 path components from diff.patch up to plans/<slug>)
    found_diff="$(find "$base_dir/plans" -path '*/archive/tasks/*/diff.patch' 2>/dev/null | sort | tail -1)" || found_diff=""
    if [[ -n "$found_diff" ]]; then
      demo_diff="$found_diff"
      # tasks/<id>/diff.patch → id is parent dir
      demo_task="$(basename "$(dirname "$found_diff")")"
      # archive/tasks/<id>/diff.patch → slug is 4 levels up from diff.patch
      demo_slug="$(basename "$(dirname "$(dirname "$(dirname "$(dirname "$found_diff")")")")")"
    fi
  fi

  if [[ -z "$demo_diff" ]]; then
    printf '' # nothing found — graceful empty
    return 0
  fi

  # Emit a synthetic review_gated_down JSON line
  python3 -c "
import json, sys
print(json.dumps({
  'ts': '2026-01-01T00:00:00Z',
  'run': 'demo-run',
  'kind': 'review_gated_down',
  'id': sys.argv[1],
  'tier': 'low',
  'provider': 'flash',
  'cycle': 1,
  '_demo': True,
  '_slug': sys.argv[2]
}))" "$demo_task" "$demo_slug"
}

# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

_emit() {
  printf '%s\n' "$1"
  if [[ -n "$REPORT_PATH" ]]; then
    printf '%s\n' "$1" >> "$REPORT_PATH"
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

NOW="$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%Y-%m-%dT%H:%M:%SZ')"

# Truncate report file if writing
if [[ -n "$REPORT_PATH" ]]; then
  : > "$REPORT_PATH"
fi

_emit "# Flash False-Negative Audit Report"
_emit "Generated: ${NOW}"
_emit "Metrics:   ${METRICS_PATH}"
if [[ $DEMO_MODE -eq 1 ]]; then
  _emit "Mode:      --demo (synthetic events; no real gated tasks)"
fi
_emit ""

# Load gated events
if [[ $DEMO_MODE -eq 1 ]]; then
  GATED_LINES="$(_synthetic_gated_events)"
else
  GATED_LINES="$(_load_gated_events "$METRICS_PATH")"
fi

# Count events
TOTAL_GATED=0
if [[ -n "$GATED_LINES" ]]; then
  TOTAL_GATED="$(printf '%s\n' "$GATED_LINES" | grep -c . 2>/dev/null || printf '0')"
fi

if [[ $TOTAL_GATED -eq 0 ]]; then
  _emit "## Result: No gated-out tasks found"
  _emit ""
  _emit "No \`review_gated_down\` events found in:"
  _emit "  ${METRICS_PATH}"
  _emit ""
  _emit "To populate this audit:"
  _emit "  1. Enable the pre-review gate:  export Z_HARNESS_IMPL_PRE_REVIEW=1"
  _emit "  2. Run some low-tier tasks:     /z-execute (tasks marked Complexity: low)"
  _emit "  3. Re-run this script to see Flash false-negative rate."
  _emit ""
  _emit "Use --demo to exercise the full audit flow with synthetic data."
  if [[ -n "$REPORT_PATH" ]]; then
    printf 'audit-preview-misses: report written to %s\n' "$REPORT_PATH" >&2
  fi
  exit 0
fi

_emit "## Gated-Out Tasks Found: ${TOTAL_GATED}"
_emit ""

# Apply sample limit
if [[ -n "$SAMPLE_N" ]] && [[ "$TOTAL_GATED" -gt "$SAMPLE_N" ]]; then
  GATED_LINES="$(printf '%s\n' "$GATED_LINES" | head -n "$SAMPLE_N")"
  _emit "(Sampled ${SAMPLE_N} of ${TOTAL_GATED} events — use --sample to adjust)"
  _emit ""
fi

# Resolve reviewer
REVIEWER_DESCRIPTOR=""
REVIEWER_AVAILABLE=0
if REVIEWER_DESCRIPTOR="$(_resolve_reviewer_command 2>/dev/null)"; then
  REVIEWER_AVAILABLE=1
fi

if [[ $REVIEWER_AVAILABLE -eq 0 ]]; then
  _emit "WARNING: Could not resolve reviewer provider (codex not configured?)."
  _emit "         Will list gated tasks without re-review."
  _emit "         Configure the reviewer role in .z-harness/providers.json to enable re-review."
  _emit ""
fi

# Process each gated event
MISS_COUNT=0
CLEAN_COUNT=0
ERROR_COUNT=0
UNKNOWN_COUNT=0
ROW=0

declare -a TASK_ROWS

while IFS= read -r event_line; do
  [[ -z "$event_line" ]] && continue
  ROW=$((ROW + 1))

  task_id="$(_event_field "$event_line" id)"
  tier="$(_event_field "$event_line" tier)"
  provider="$(_event_field "$event_line" provider)"
  ts="$(_event_field "$event_line" ts)"
  run="$(_event_field "$event_line" run)"
  is_demo="$(_event_field "$event_line" _demo)"
  event_slug="$(_event_field "$event_line" _slug)"

  label=""
  if [[ "$is_demo" = "True" ]]; then
    label=" [DEMO]"
  fi

  _emit "### Task ${task_id}${label}"
  _emit "  Gated at: ${ts}  (run: ${run}, tier: ${tier}, pre-reviewer: ${provider})"

  # Find diff
  hint="${SLUG:-${event_slug}}"
  diff_path=""
  if diff_path="$(_find_diff "$task_id" "$hint" 2>/dev/null)"; then
    _emit "  Diff:     ${diff_path}"
  else
    _emit "  Diff:     NOT FOUND (archive missing or task id mismatch)"
    _emit "  Result:   SKIP (no diff available for re-review)"
    ERROR_COUNT=$((ERROR_COUNT + 1))
    _emit ""
    continue
  fi

  if [[ $REVIEWER_AVAILABLE -eq 0 ]]; then
    _emit "  Result:   SKIP (reviewer not configured)"
    ERROR_COUNT=$((ERROR_COUNT + 1))
    _emit ""
    continue
  fi

  # Run codex re-review
  _emit "  Re-reviewing with codex..."
  CODEX_RESPONSE="$(_run_codex_review "$task_id" "$diff_path" "$REVIEWER_DESCRIPTOR" 2>/dev/null || printf 'REVIEW_ERROR: dispatch failed')"
  VERDICT="$(_extract_verdict "$CODEX_RESPONSE")"

  case "$VERDICT" in
    ISSUES_FOUND)
      MISS_COUNT=$((MISS_COUNT + 1))
      _emit "  Verdict:  ISSUES_FOUND — Flash missed blockers/majors (FALSE NEGATIVE)"
      _emit "  Codex findings (excerpt, first 800 chars):"
      excerpt="$(printf '%s' "$CODEX_RESPONSE" | head -c 800)"
      while IFS= read -r fline; do
        _emit "    ${fline}"
      done <<< "$excerpt"
      ;;
    CLEAN)
      CLEAN_COUNT=$((CLEAN_COUNT + 1))
      _emit "  Verdict:  CLEAN — Flash and codex agree (no miss)"
      ;;
    ERROR)
      ERROR_COUNT=$((ERROR_COUNT + 1))
      _emit "  Verdict:  ERROR — codex re-review failed"
      _emit "  Detail:   $(printf '%s' "$CODEX_RESPONSE" | head -c 200)"
      ;;
    *)
      UNKNOWN_COUNT=$((UNKNOWN_COUNT + 1))
      _emit "  Verdict:  UNKNOWN — could not parse codex response"
      _emit "  Detail:   $(printf '%s' "$CODEX_RESPONSE" | head -c 200)"
      ;;
  esac
  _emit ""

done <<< "$GATED_LINES"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

# UNKNOWN verdicts are excluded from the denominator — they are unclassifiable
# and including them would silently distort the miss rate.
REVIEWED=$((MISS_COUNT + CLEAN_COUNT))
if [[ $REVIEWED -gt 0 ]]; then
  MISS_RATE_PCT="$(python3 -c "print(f'{100*${MISS_COUNT}/${REVIEWED}:.1f}')" 2>/dev/null || printf '?')"
  MISS_RATE_DISPLAY="${MISS_RATE_PCT}%  (${MISS_COUNT}/${REVIEWED} classifiable re-reviews)"
else
  MISS_RATE_PCT="N/A"
  MISS_RATE_DISPLAY="n/a — no classifiable re-reviews"
fi

_emit "---"
_emit "## Summary"
_emit ""
_emit "  Gated-out tasks processed : ${ROW}"
_emit "  Classifiable re-reviews   : ${REVIEWED}  (MISS + CLEAN; basis for miss rate)"
_emit "  Flash false negatives     : ${MISS_COUNT}  (codex found issues Flash missed)"
_emit "  Agreement (both clean)    : ${CLEAN_COUNT}"
_emit "  Errors / skipped          : ${ERROR_COUNT}"
_emit "  Inconclusive (excluded)   : ${UNKNOWN_COUNT}  (unclassifiable; excluded from rate)"
_emit ""
_emit "  Flash miss rate           : ${MISS_RATE_DISPLAY}"
_emit ""

if [[ $REVIEWED -eq 0 ]]; then
  _emit "  Recommendation: not enough data to evaluate. Run more low-tier tasks with"
  _emit "  Z_HARNESS_IMPL_PRE_REVIEW=1 enabled, then re-run this audit."
elif python3 -c "import sys; sys.exit(0 if float('${MISS_RATE_PCT}') <= 10.0 else 1)" 2>/dev/null; then
  _emit "  Recommendation: miss rate <= 10% — consider enabling Z_HARNESS_IMPL_PRE_REVIEW=1"
  _emit "  as the default. Review individual false-negative cases above before deciding."
else
  _emit "  Recommendation: miss rate > 10% — do NOT enable Z_HARNESS_IMPL_PRE_REVIEW as"
  _emit "  default. Investigate false-negative cases above; consider tightening the Flash"
  _emit "  pre-reviewer prompt (agents/pre-reviewer.md) before re-evaluating."
fi

_emit ""
_emit "  [Offline analysis artifact — generated $(date -u 2>/dev/null || date). Read-only.]"

if [[ -n "$REPORT_PATH" ]]; then
  printf 'audit-preview-misses: report written to %s\n' "$REPORT_PATH" >&2
fi
