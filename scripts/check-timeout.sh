#!/usr/bin/env bash
# Detect timeout(1)/gtimeout(1) on PATH and emit a structured
# `timeout_availability` event once per run.
#
# Designed to be SOURCED, not executed:
#   source "$PLUGIN_ROOT/scripts/check-timeout.sh" "$RUN"
#
# On return, the caller's environment has `TIMEOUT_CMD` set:
#   - absolute path to `timeout` or `gtimeout` if found
#   - empty string if neither is on PATH (caller must check)
#
# The event is emitted at most once per (run, shell-session) tuple via a
# marker file under the run dir, mirroring the `.providers-logged` pattern
# in commands/z-plan.md. Subsequent sources within the same run are no-ops
# beyond exporting TIMEOUT_CMD.

# Resolve plugin root the same way log-phase.sh does.
_CT_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"

# Argument: run id (relative or absolute path under archive/). May be empty;
# if empty, we still set TIMEOUT_CMD but skip the event emission.
_CT_RUN="${1:-}"

TIMEOUT_CMD="$(command -v timeout || command -v gtimeout || true)"
export TIMEOUT_CMD

# Stderr warning runs before any marker check so parallel shell sessions
# (where the env-var guard doesn't carry across processes) still see it once
# per shell. Idempotency of the *event* is enforced separately below via a
# filesystem marker.
if [ -z "$TIMEOUT_CMD" ] && [ -z "${Z_HARNESS_TIMEOUT_WARNED:-}" ]; then
  echo "[providers] timeout(1) not on PATH — provider timeout disabled. brew install coreutils to restore." >&2
  export Z_HARNESS_TIMEOUT_WARNED=1
fi

if [ -z "$_CT_RUN" ]; then
  return 0 2>/dev/null || exit 0
fi

# Locate the run dir to drop the marker file. Delegate base resolution to
# plan-path.sh so the full 5-tier fallback chain and anchor invariant are
# honoured — identical to log-event.sh.
_CT_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/plan-path.sh
source "$_CT_SCRIPT_DIR/plan-path.sh"

# Resolve base via z_harness_base(); set sentinel to suppress base_resolved
# event emission that would re-invoke this script via log-event.sh.
_CT_ZH_BASE="$(_Z_HARNESS_RESOLVING_BASE=1 z_harness_base)"

if [ -n "${Z_HARNESS_SLUG:-}" ]; then
  # Validate PLANS_DIR in parent shell: relative path + BASE_DIR set → fail loudly.
  # (Must be checked here in the parent shell because any exit 1 inside $(...)
  # command substitution only kills the subshell.)
  if [ -n "${Z_HARNESS_BASE_DIR:-}" ] && [ -n "${Z_HARNESS_PLANS_DIR:-}" ]; then
    case "${Z_HARNESS_PLANS_DIR}" in
      /*) : ;;  # absolute — OK
      *)
        echo "[z-harness] Z_HARNESS_PLANS_DIR must be absolute when Z_HARNESS_BASE_DIR is set, got: $Z_HARNESS_PLANS_DIR" >&2
        return 1 2>/dev/null || exit 1
        ;;
    esac
  fi
  if [ -n "${Z_HARNESS_PLANS_DIR:-}" ]; then
    _CT_PLANS_DIR="$Z_HARNESS_PLANS_DIR"
  else
    _CT_PLANS_DIR="$_CT_ZH_BASE/plans"
  fi
  _CT_RUN_DIR="$_CT_PLANS_DIR/$Z_HARNESS_SLUG/archive/$_CT_RUN"
  # Legacy mid-flight fallback: only when Z_HARNESS_BASE_DIR is NOT set
  # (setting it disables repo-local writes to preserve the model.patch invariant).
  if [ -z "${Z_HARNESS_BASE_DIR:-}" ]; then
    _CT_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    _CT_LEGACY_RUN_DIR="$_CT_REPO_ROOT/$(legacy_plan_dir "$Z_HARNESS_SLUG")/archive/$_CT_RUN"
    if [ -d "$_CT_LEGACY_RUN_DIR" ] && [ ! -d "$_CT_RUN_DIR" ]; then
      _CT_RUN_DIR="$_CT_LEGACY_RUN_DIR"
    fi
  fi
else
  _CT_RUN_DIR="$_CT_ZH_BASE/archive/$_CT_RUN"
fi

mkdir -p "$_CT_RUN_DIR"

# Atomic lock via mkdir — `mkdir` of an existing directory is a non-zero exit,
# so only the first parallel source-caller proceeds to emit the event. This
# is the cheap POSIX-portable replacement for flock here (log-event.sh itself
# uses flock; we only need to gate the one-shot emission).
_CT_MARKER_DIR="$_CT_RUN_DIR/.timeout-logged"
if ! mkdir "$_CT_MARKER_DIR" 2>/dev/null; then
  return 0 2>/dev/null || exit 0
fi

# Build payload via python3 so a path with quotes/backslashes/newlines round-trips
# as valid JSON instead of being wrapped as `{"raw": ...}` by log-event.sh.
_CT_PAYLOAD="$(python3 -c '
import json, sys
cmd = sys.argv[1] or None
out = {"available": bool(cmd), "command": cmd}
if not cmd:
    out["hint"] = "brew install coreutils to restore timeout(1)"
print(json.dumps(out))
' "$TIMEOUT_CMD")"

# Write the event BEFORE confirming the marker survives. If log-event.sh
# fails, remove the marker so a subsequent caller can retry the emission
# instead of being silently locked out for the rest of the run.
if ! bash "$_CT_PLUGIN_ROOT/scripts/log-event.sh" "$_CT_RUN" timeout_availability "$_CT_PAYLOAD" >/dev/null 2>&1; then
  rmdir "$_CT_MARKER_DIR" 2>/dev/null || true
fi
