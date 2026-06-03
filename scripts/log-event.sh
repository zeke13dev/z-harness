#!/usr/bin/env bash
# Append a structured event to the run's events.jsonl.
#
# Usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>
#
# Slug namespacing: if env var Z_HARNESS_SLUG is set (non-empty), all output
# paths are namespaced under ${Z_HARNESS_PLANS_DIR:-<base>/plans}/<slug>/
# so multiple plans can coexist in the same repo. If unset, the legacy flat
# layout (<base>/archive/...) is used for backward compat with old plans.
#
# <base> is resolved via scripts/plan-path.sh z_harness_base() (5-tier fallback):
#   tier 1: Z_HARNESS_BASE_DIR (must be absolute) — redirects ALL artifacts away from repo
#   tier 5 (default, stage-1): <repo>/z-harness  — unchanged from legacy behaviour
# Setting Z_HARNESS_BASE_DIR is required when running inside a benchmark task's working tree.
#
# Example:
#   Z_HARNESS_SLUG=add-rate-limit \
#   log-event.sh 20260517T144200Z-add-rate-limit consult \
#     '{"llm":"gemini","phase":3,"prompt_chars":4821,"wall_ms":18204,"transcript":"001-gemini.md"}'
#
# Writes to (with Z_HARNESS_SLUG set):
#   ${Z_HARNESS_PLANS_DIR:-<base>/plans}/<slug>/archive/<run>/events.jsonl  (new canonical)
#   z-harness/<slug>/archive/<run>/events.jsonl  (legacy mid-flight fallback — if run dir
#     already exists at legacy path, writes there to avoid splitting a run's events;
#     run 'scripts/migrate-plan-layout.sh <slug>' to move to the new layout)
#   <base>/metrics.jsonl  (aggregate; <base> = z_harness_base() resolved path)
#
# Writes to (legacy, no slug):
#   <base>/archive/<run>/events.jsonl
#   <base>/metrics.jsonl
#
# Both files are JSON Lines. Append-safe under concurrent calls via flock when available.

set -euo pipefail

# Read-only resolver subcommand: `log-event.sh resolve-run-dir <run-id>` prints
# the run's archive directory (using the same slug-aware, 5-tier logic the write
# path uses) and exits without creating or writing anything. Lets other tools
# (e.g. improve-nudge.sh) locate a run's events.jsonl without duplicating the
# resolution logic.
RESOLVE_ONLY=""
if [[ "${1:-}" == "resolve-run-dir" ]]; then
  RESOLVE_ONLY=1
  RUN="${2:-}"
  if [[ -z "$RUN" ]]; then
    echo "usage: log-event.sh resolve-run-dir <run-id>" >&2
    exit 2
  fi
else
  if [[ $# -lt 3 ]]; then
    echo "usage: log-event.sh <run-id-or-relpath> <kind> <json-payload>" >&2
    exit 2
  fi
  RUN="$1"
  KIND="$2"
  PAYLOAD="$3"
fi

# Resolve repo root (caller's cwd is assumed to be inside the target repo).
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Load plan-path helper
# shellcheck source=scripts/plan-path.sh
source "$(dirname "$0")/plan-path.sh"

# Resolve the artifact base dir via z_harness_base() so the full 5-tier fallback
# chain (and the anchor invariant) are honoured.  The _Z_HARNESS_RESOLVING_BASE
# sentinel prevents the recursive loop that would occur if z_harness_base() tried
# to emit a base_resolved event via this very script while we are sourcing it.
_Z_HARNESS_RESOLVING_BASE=1 ZH_BASE="$(z_harness_base)"

# Join a base dir (may be relative or absolute) with a suffix under REPO_ROOT.
# If the base is absolute it is used verbatim; if relative it is resolved
# relative to REPO_ROOT. This handles Z_HARNESS_PLANS_DIR=/tmp/p correctly.
abs_plan_dir() {
  local base="$1"
  case "$base" in
    /*) printf '%s' "$base" ;;
    *)  printf '%s/%s' "$REPO_ROOT" "$base" ;;
  esac
}

# Slug namespacing — global (also consumed later when constructing the event).
SLUG="${Z_HARNESS_SLUG:-}"

# Resolve the run's archive directory using slug namespacing (see header comment).
# Sets the global RUN_DIR; does NOT create it. Runs in the CURRENT shell (no
# command-substitution subshell) so the no-slug write path stays fork-free,
# matching the original inline behaviour — an extra fork here segfaults under
# macOS objc fork-safety. Shared by the resolver subcommand and the write path.
resolve_run_dir() {
  if [[ -n "$SLUG" ]]; then
    # Mid-flight legacy run detection: if the legacy archive dir for this run
    # already exists (run started before the plan-layout migration), write there
    # to avoid splitting a run's events across two locations. When
    # Z_HARNESS_BASE_DIR is set, skip the repo-local legacy fallback entirely —
    # writing to the repo would corrupt the model.patch invariant.
    if [[ -z "${Z_HARNESS_BASE_DIR:-}" ]]; then
      local LEGACY_RUN_DIR
      LEGACY_RUN_DIR="$(abs_plan_dir "$(legacy_plan_dir "$SLUG")")/archive/$RUN"
      if [[ -d "$LEGACY_RUN_DIR" ]]; then
        RUN_DIR="$LEGACY_RUN_DIR"
      else
        RUN_DIR="$(abs_plan_dir "$(plan_dir "$SLUG")")/archive/$RUN"
      fi
    else
      # Validate PLANS_DIR before the plan_dir command substitution so the
      # exit propagates from this (non-subshell) function context.
      if [[ -n "${Z_HARNESS_PLANS_DIR:-}" && "${Z_HARNESS_PLANS_DIR}" != /* ]]; then
        echo "[z-harness] Z_HARNESS_PLANS_DIR must be absolute when Z_HARNESS_BASE_DIR is set, got: $Z_HARNESS_PLANS_DIR" >&2
        exit 1
      fi
      local _PLAN_DIR_OUT
      _PLAN_DIR_OUT="$(plan_dir "$SLUG")" || exit 1
      RUN_DIR="$(abs_plan_dir "$_PLAN_DIR_OUT")/archive/$RUN"
    fi
  else
    # Global archive fallback (no slug) — respects Z_HARNESS_BASE_DIR.
    RUN_DIR="$ZH_BASE/archive/$RUN"
  fi
}

if [[ -n "$RESOLVE_ONLY" ]]; then
  resolve_run_dir
  printf '%s\n' "$RUN_DIR"
  exit 0
fi

resolve_run_dir
mkdir -p "$RUN_DIR"
mkdir -p "$ZH_BASE"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Validate payload is JSON; if not, wrap it as a string.
if ! printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; json.loads(sys.stdin.read())' 2>/dev/null; then
  PAYLOAD="$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys; print(json.dumps({"raw": sys.stdin.read()}))')"
fi

EVENT="$(python3 -c '
import json, sys
ts, run, kind, slug, payload = sys.argv[1:6]
obj = {"ts": ts, "run": run, "kind": kind}
if slug:
    obj["slug"] = slug
obj.update(json.loads(payload))
print(json.dumps(obj, separators=(",", ":")))
' "$TS" "$RUN" "$KIND" "$SLUG" "$PAYLOAD")"

append() {
  local target="$1"
  if command -v flock >/dev/null 2>&1; then
    ( flock 9; printf '%s\n' "$EVENT" >> "$target" ) 9>>"$target.lock"
  else
    printf '%s\n' "$EVENT" >> "$target"
  fi
}

append "$RUN_DIR/events.jsonl"
append "$ZH_BASE/metrics.jsonl"
