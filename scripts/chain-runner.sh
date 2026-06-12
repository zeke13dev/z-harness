#!/usr/bin/env bash
# chain-runner.sh — Mechanics-only chain sequencing/state primitive for the
# /z-overnight and /z-attend orchestrators.
#
# POLICY STAYS OUT OF THIS SCRIPT (SPEC Invariant 2). This file sequences a
# command chain and persists/reads the run state file. It NEVER spawns a Skill,
# resolves a gate, or applies AUTODECIDE/category/NO_ASK policy. Those live in
# the per-command orchestrator (commands/z-overnight.md, commands/z-attend.md).
#
# It is a narrow extraction of the sequencing/state/resume logic currently
# inline in commands/z-overnight.md (Phase 0 presets, Phase 1.9 state init,
# Phase 1.10/3.10 flock-guarded state write, Phase 2.4 cursor, Phase 3.5/3.8
# C14 new-run-id set-difference). Behavior MUST be byte-identical to that inline
# logic on the same inputs — pinned by tests/test_chain_runner_characterization.*
# (SPEC Invariant 3 — runner parity).
#
# STATE-FILE PATH IS A PARAMETER (m3 / SPEC). Every state subcommand takes the
# state-file path as an explicit argument: overnight passes
# "$BASE/archive/$RUN_ID/overnight-state.json" (Invariant 3 parity) while attend
# passes its own run-scoped file. There is NO hardcoded state-file constant.
#
# PORTABLE FLOCK. macOS has no `flock(1)` util, so state-write serialization is
# done with Python 3 fcntl.flock (same portability convention as sink-lock.sh)
# using the documented tmp+rename atomic-replace pattern.
#
# Subcommands:
#   steps <preset>
#       Emit "name:yield_after" per line for the preset's ordered steps.
#       yield_after defaults false; true for `plan` and `implement-all` (m1).
#       Exit 2 on unknown preset (no output).
#
#   state-init <state-file> <chain-csv> <preset> <started-at> <head-sha> <version>
#       Build the initial run-state JSON (status=running, all step_runs queued)
#       and write it flock-guarded via tmp+rename. <preset> of "null" / "" → null.
#       The lock file is "<state-file>.lock" unless CHAIN_RUNNER_LOCK_FILE is set.
#
#   state-read <state-file>
#       Print the state JSON to stdout. Exit 3 if the file is missing/unreadable.
#
#   state-write <state-file> <json|->
#       Replace the entire state file with the JSON payload (validated as JSON)
#       flock-guarded via tmp+rename. The lock file is "<state-file>.lock" unless
#       CHAIN_RUNNER_LOCK_FILE is set. The payload source is:
#         - a literal JSON string passed as <json> (the original argv form), OR
#         - stdin, when <json> is "-" or omitted (the unbounded form — use this
#           for large overnight states that could exceed the OS argv/env ceiling).
#       Both forms share identical flock + tmp+rename + JSON-validation semantics.
#
#   cursor <state-file>
#       Print the index of the first step_run whose status != "complete"
#       (Phase 2.4). Prints len(step_runs) when all complete. Exit 3 if missing.
#
#   new-run-id <state-file-unused> <before-set-file-or-->  <archive-dir>
#       (kept signature-compatible with the task's "new-run-id <run> <before-set>")
#       Compute the C14 set-difference of archive-dir basenames that appeared
#       since the <before-set> snapshot, EXCLUDING any basename matching
#       *-overnight-* from BOTH sides. <before-set> is a file of newline-separated
#       basenames, or "-" to read the before-set from stdin. Prints the sorted
#       NEW basenames, one per line (0 lines = ambiguous/no-new; >1 = ambiguous).
#
# Exit codes: 0 ok · 2 unknown preset · 3 missing/unreadable state file ·
#             64 usage error.

set -euo pipefail

_die_usage() {
  printf 'chain-runner.sh: %s\n' "$1" >&2
  printf 'usage: chain-runner.sh <steps|state-init|state-read|state-write|cursor|new-run-id> ...\n' >&2
  exit 64
}

# ---------------------------------------------------------------------------
# Presets (lifted verbatim from commands/z-overnight.md Phase 0 + attend-full B3)
# ---------------------------------------------------------------------------
# attend-full = full-build + an `audit` step inserted after `plan` (SPEC B3 / PLAN D7).
_expand_preset() {
  case "$1" in
    full-build)     printf '%s\n' "plan,test,implement-all,review-all" ;;
    research-build) printf '%s\n' "research,plan,test,implement-all,review-all" ;;
    quick-build)    printf '%s\n' "plan,implement-all" ;;
    attend-full)    printf '%s\n' "plan,audit,test,implement-all,review-all" ;;
    *)              return 1 ;;
  esac
}

# yield_after flag per step name (m1): true only for plan and implement-all.
_yield_after() {
  case "$1" in
    plan|implement-all) printf 'true' ;;
    *)                  printf 'false' ;;
  esac
}

cmd_steps() {
  local preset="${1:-}"
  [[ -n "$preset" ]] || _die_usage "steps: missing <preset>"
  local csv
  if ! csv="$(_expand_preset "$preset")"; then
    exit 2
  fi
  local IFS=','
  local step
  for step in $csv; do
    [[ -n "$step" ]] || continue
    printf '%s:%s\n' "$step" "$(_yield_after "$step")"
  done
}

# ---------------------------------------------------------------------------
# Flock-guarded atomic write (Python fcntl.flock + tmp+rename).
# Mirrors commands/z-overnight.md Phase 1.10 / 3.10 exactly.
# ---------------------------------------------------------------------------
_lock_file_for() {
  # $1 = state-file path. Lock file is "<state-file>.lock" unless overridden.
  printf '%s' "${CHAIN_RUNNER_LOCK_FILE:-$1.lock}"
}

# _atomic_write <state-file> <json-source>
# Validates the JSON payload, then writes it under an exclusive flock on the lock
# file via tmp+rename. Creates parent dir + lock file if absent.
#
# <json-source> selects where the payload comes from:
#   "-"  → read the payload from this function's stdin (the unbounded path; the
#          bytes never transit argv or an env var, so there is no OS size ceiling)
#   else → the literal JSON string itself (the original argv path)
# In BOTH cases the payload is handed to Python on the child's stdin, so even the
# argv form does not re-expose the value through an env var.
_atomic_write() {
  local state_file="$1" json_source="$2"
  local lock_file
  lock_file="$(_lock_file_for "$state_file")"
  mkdir -p "$(dirname "$state_file")"
  # Ensure the lock file exists for fcntl to open in r+ mode.
  [[ -e "$lock_file" ]] || : >"$lock_file"

  if [[ "$json_source" == "-" ]]; then
    STATE_FILE="$state_file" LOCK_FILE="$lock_file" _atomic_write_py
  else
    # Original argv form: feed the literal string to the same stdin-reading body.
    printf '%s' "$json_source" \
      | STATE_FILE="$state_file" LOCK_FILE="$lock_file" _atomic_write_py
  fi
}

# The atomic-write Python program. Held in a variable (not a stdin heredoc) so
# that the child's stdin stays free for the JSON payload — the payload is read
# from sys.stdin, which is how the unbounded path avoids the OS argv/env ceiling.
_ATOMIC_WRITE_PY='
import json, os, sys

state_file = os.environ["STATE_FILE"]
lock_file = os.environ["LOCK_FILE"]
# Read the payload from stdin — unbounded, never via argv/env (no size ceiling).
raw = sys.stdin.read()

# Validate as JSON before touching the lock — a malformed write must not
# clobber a good state file.
try:
    obj = json.loads(raw)
except json.JSONDecodeError as exc:
    sys.stderr.write(f"chain-runner.sh: state-write: invalid JSON: {exc}\n")
    sys.exit(64)

import fcntl
with open(lock_file, "r+") as lf:
    fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
    try:
        tmp = state_file + ".tmp." + str(os.getpid())
        with open(tmp, "w") as tf:
            json.dump(obj, tf, indent=2)
        os.rename(tmp, state_file)
    finally:
        fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
'

# _atomic_write_py — reads the JSON payload from stdin, validates it, and writes
# it flock-guarded via tmp+rename. STATE_FILE / LOCK_FILE come from the env.
_atomic_write_py() {
  python3 -c "$_ATOMIC_WRITE_PY"
}

cmd_state_init() {
  # state-init <state-file> <chain-csv> <preset> <started-at> <head-sha> <version>
  local state_file="${1:-}" chain_csv="${2:-}" preset="${3:-}" \
        started_at="${4:-}" head_sha="${5:-}" version="${6:-}"
  [[ -n "$state_file" ]] || _die_usage "state-init: missing <state-file>"
  [[ -n "$chain_csv" ]]  || _die_usage "state-init: missing <chain-csv>"

  local json
  json="$(STATE_CHAIN_CSV="$chain_csv" STATE_PRESET="$preset" \
          STATE_STARTED_AT="$started_at" STATE_HEAD_SHA="$head_sha" \
          STATE_VERSION="$version" python3 - <<'PY'
import json, os

chain = [s.strip() for s in os.environ["STATE_CHAIN_CSV"].split(",") if s.strip()]
preset = os.environ.get("STATE_PRESET", "")
preset_used = None if preset in ("", "null") else preset

state = {
    "chain": chain,
    "preset_used": preset_used,
    "started_at": os.environ.get("STATE_STARTED_AT", ""),
    "ended_at": None,
    "status": "running",
    "head_sha_at_start": os.environ.get("STATE_HEAD_SHA", ""),
    "z_harness_version": os.environ.get("STATE_VERSION") or "unknown",
    "git_diff_stat_at_end": None,
    "step_runs": [
        {
            "step": step,
            "position": i,
            "run_id": None,
            "status": "queued",
            "head_sha_before": None,
            "head_sha_after": None,
            "started_at": None,
            "ended_at": None,
            "wall_ms": None,
            "terminal_event_kind": None,
            "artifact_paths": [],
            "exit_event": None,
            "error_event": None,
        }
        for i, step in enumerate(chain)
    ],
}
print(json.dumps(state))
PY
)"
  _atomic_write "$state_file" "$json"
}

cmd_state_read() {
  local state_file="${1:-}"
  [[ -n "$state_file" ]] || _die_usage "state-read: missing <state-file>"
  if [[ ! -r "$state_file" ]]; then
    printf 'chain-runner.sh: state-read: cannot read %s\n' "$state_file" >&2
    exit 3
  fi
  cat "$state_file"
}

cmd_state_write() {
  local state_file="${1:-}"
  [[ -n "$state_file" ]] || _die_usage "state-write: missing <state-file>"
  # Payload source (backward-compatible):
  #   state-write <file> <json>   → literal JSON string via argv (original form)
  #   state-write <file> -        → read JSON from stdin (unbounded path)
  #   state-write <file>          → <json> omitted ⇒ also read from stdin
  # The stdin path exists so large overnight states never traverse the OS
  # argv/env size ceiling (SPEC Invariant 3 parity for large runs).
  local json_source
  if [[ $# -ge 2 ]]; then
    json_source="$2"
  else
    json_source="-"
  fi
  _atomic_write "$state_file" "$json_source"
}

cmd_cursor() {
  local state_file="${1:-}"
  [[ -n "$state_file" ]] || _die_usage "cursor: missing <state-file>"
  if [[ ! -r "$state_file" ]]; then
    printf 'chain-runner.sh: cursor: cannot read %s\n' "$state_file" >&2
    exit 3
  fi
  STATE_FILE="$state_file" python3 - <<'PY'
import json, os, sys

with open(os.environ["STATE_FILE"]) as f:
    state = json.load(f)
step_runs = state.get("step_runs", [])
# Phase 2.4: cursor = index of first step_run with status != "complete";
# len(step_runs) when all are complete (chain done).
cursor = next((i for i, sr in enumerate(step_runs)
               if sr.get("status") != "complete"),
              len(step_runs))
print(cursor)
PY
}

cmd_new_run_id() {
  # new-run-id <state-file-unused> <before-set-file-or-"-"> <archive-dir>
  # The first positional mirrors the task's "<run>" arg for signature
  # compatibility with overnight's callsite; it is intentionally unused here
  # (the run is implicit in the before-set snapshot + archive dir).
  local _run_unused="${1:-}" before_src="${2:-}" archive_dir="${3:-}"
  [[ -n "$before_src" ]]   || _die_usage "new-run-id: missing <before-set>"
  [[ -n "$archive_dir" ]]  || _die_usage "new-run-id: missing <archive-dir>"

  local before_set
  if [[ "$before_src" == "-" ]]; then
    before_set="$(cat)"
  elif [[ -r "$before_src" ]]; then
    before_set="$(cat "$before_src")"
  else
    printf 'chain-runner.sh: new-run-id: cannot read before-set %s\n' "$before_src" >&2
    exit 3
  fi

  # Snapshot archive dirs NOW (the "after" set), excluding *-overnight-*.
  # Mirrors commands/z-overnight.md Step 3.8 exactly.
  local after_set
  after_set="$(find "$archive_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
    | while IFS= read -r d; do
        b="$(basename "$d")"
        case "$b" in *-overnight-*) ;; *) printf '%s\n' "$b" ;; esac
      done \
    | sort || true)"

  # Set-difference (comm -13) of the *-overnight-*-filtered before/after sets.
  # The before-set is filtered too (matches the inline snapshot which already
  # excluded overnight dirs, and the characterization test which filters both).
  local before_filtered
  before_filtered="$(printf '%s\n' "$before_set" \
    | while IFS= read -r b; do
        [[ -n "$b" ]] || continue
        case "$b" in *-overnight-*) ;; *) printf '%s\n' "$b" ;; esac
      done \
    | sort || true)"

  comm -13 <(printf '%s\n' "$before_filtered" | sort) \
           <(printf '%s\n' "$after_set" | sort) \
    | sed '/^[[:space:]]*$/d'
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
main() {
  [[ $# -ge 1 ]] || _die_usage "missing subcommand"
  local sub="$1"; shift
  case "$sub" in
    steps)       cmd_steps "$@" ;;
    state-init)  cmd_state_init "$@" ;;
    state-read)  cmd_state_read "$@" ;;
    state-write) cmd_state_write "$@" ;;
    cursor)      cmd_cursor "$@" ;;
    new-run-id)  cmd_new_run_id "$@" ;;
    *)           _die_usage "unknown subcommand: $sub" ;;
  esac
}

main "$@"
