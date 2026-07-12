#!/usr/bin/env bash
# z-teardown.sh — one-call finish ceremony for a /z-* skill run.
#
# Counterpart to z-preflight.sh. Wraps the run-ending sequence every skill's
# finalize/halt path currently duplicates inline (run-brief.sh finalize,
# plan-claim.sh release, active-plan-registry.py deregister, log-event.sh)
# behind a single call. NO logic is reimplemented here — every step below
# shells out to the existing script that already owns that behavior.
#
# Usage:
#   bash scripts/z-teardown.sh --run "$RUN" --slug "$SLUG" --command /z-plan \
#     [--status complete|aborted] [--session SID]
#
# Env vars / outputs:
#   Does NOT export anything for eval (there is nothing left to hand back to
#   the caller's shell once the run is torn down). On completion it prints a
#   single JSON summary line to stdout:
#     {"run":"<RUN>","status":"<complete|aborted>","warnings":["<step>", ...]}
#   `warnings` lists any step that failed non-fatally (best-effort cleanup —
#   see exit-code contract below). All step-level diagnostics also go to
#   stderr as they happen.
#
# Idempotent: safe to call twice for the same --run. Every step it wraps
# (run-brief.sh finalize, plan-claim.sh release, active-plan-registry.py
# deregister) is itself idempotent/best-effort and returns success on a
# second call against an already-torn-down run (finalize re-validates and
# rewrites; release on an already-free/foreign-held lock is a documented
# true no-op; deregister on an already-absent record is a benign no-op).
# The only non-idempotent side effect is a second run_end event line being
# appended to telemetry — harmless, not a correctness issue.
#
# Sequence:
#   1. run-brief finalize        (run-brief.sh finalize)
#   2. claim release              (plan-claim.sh release — ALWAYS attempted;
#                                  see note below on why CLAIM_HELD isn't
#                                  required as a precondition)
#   3. deregister                  (active-plan-registry.py deregister)
#   4. run_end log-event            (log-event.sh)
#
#   NOTE on ordering (release BEFORE deregister): this mirrors the existing
#   documented invariant used across the skill corpus's inline finalize
#   blocks ("Release BEFORE deregister so the lock frees first, minimizing
#   the window where the registry shows the run gone but the lock is still
#   held"). No production caller of this wrapper should depend on the
#   opposite order.
#
#   NOTE on release without a CLAIM_HELD precondition: plan-claim.sh release
#   is itself best-effort and keys on `--expected-holder`; releasing a lock
#   this run never held (or already released) is a documented true no-op
#   (TC09 in test_plan_claim.sh) — it never touches a peer's record. So this
#   script always attempts release rather than requiring the caller to pass
#   a CLAIM_HELD flag; the caller only needs to supply the SAME --session
#   and --command it used at z-preflight.sh acquire time (or omit --session
#   and let this script read the session id z-preflight.sh persisted to
#   <plan_dir>/archive/<run>/session-id).
#
# Exit codes:
#   0 — always, EXCEPT usage errors below (best-effort cleanup: an
#       individual step warning never changes the exit code — see
#       `warnings` in the stdout summary for what, if anything, was skipped
#       or failed)
#   2 — usage error (missing --run, --slug, or --command; invalid --status)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN_PATH_SH="$SCRIPT_DIR/plan-path.sh"
PLAN_CLAIM_SH="$SCRIPT_DIR/plan-claim.sh"
REGISTRY_PY="$SCRIPT_DIR/active-plan-registry.py"
RUN_BRIEF_SH="$SCRIPT_DIR/run-brief.sh"
LOG_EVENT_SH="$SCRIPT_DIR/log-event.sh"

usage() {
  cat >&2 <<'EOF'
usage:
  z-teardown.sh --run RUN --slug SLUG --command CMD [--status complete|aborted] [--session SID]
EOF
  exit 2
}

RUN=""
SLUG=""
COMMAND=""
STATUS="complete"
SESSION_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)      RUN="${2:?}"; shift 2 ;;
    --run=*)    RUN="${1#*=}"; shift ;;
    --slug)     SLUG="${2:?}"; shift 2 ;;
    --slug=*)   SLUG="${1#*=}"; shift ;;
    --command)  COMMAND="${2:?}"; shift 2 ;;
    --command=*) COMMAND="${1#*=}"; shift ;;
    --status)   STATUS="${2:?}"; shift 2 ;;
    --status=*) STATUS="${1#*=}"; shift ;;
    --session)  SESSION_ARG="${2:?}"; shift 2 ;;
    --session=*) SESSION_ARG="${1#*=}"; shift ;;
    *) printf 'z-teardown.sh: unknown argument: %s\n' "$1" >&2; usage ;;
  esac
done

[[ -n "$RUN" && -n "$SLUG" && -n "$COMMAND" ]] || usage
case "$STATUS" in
  complete|aborted) ;;
  *) printf 'z-teardown.sh: --status must be complete or aborted, got: %s\n' "$STATUS" >&2; usage ;;
esac

# Export Z_HARNESS_SLUG so every wrapped script that is slug-aware via that
# env var (run-brief.sh -> log-event.sh resolve-run-dir, etc.) resolves the
# SAME namespaced run directory z-preflight.sh used to create it.
export Z_HARNESS_SLUG="$SLUG"

# Warnings are accumulated as a space-separated string (not a bash array) so
# this script stays correct under bash 3.2 (macOS system /bin/bash), where
# `"${arr[@]}"` on a zero-element array is an unbound-variable error under
# `set -u`.
WARNINGS=""
_warn() {
  WARNINGS="${WARNINGS:+$WARNINGS }$1"
}

# ---------------------------------------------------------------------------
# 1. Run-brief finalize (best-effort)
# ---------------------------------------------------------------------------
if ! bash "$RUN_BRIEF_SH" finalize --run "$RUN" >&2; then
  printf 'z-teardown.sh: WARNING: run-brief finalize failed for run %s\n' "$RUN" >&2
  _warn "run_brief_finalize"
fi

# ---------------------------------------------------------------------------
# Resolve the session id used at acquire time (best-effort — needed to build
# the exact holder string for release; a mismatch is a safe no-op per
# plan-claim.sh's documented --expected-holder contract, so a resolution
# failure here degrades gracefully rather than blocking teardown).
# ---------------------------------------------------------------------------
SESSION_ID="$SESSION_ARG"
if [[ -z "$SESSION_ID" ]]; then
  PLAN_DIR="$(bash "$PLAN_PATH_SH" resolve_plan_path "$SLUG" 2>/dev/null || true)"
  SESSION_FILE="$PLAN_DIR/archive/$RUN/session-id"
  if [[ -n "$PLAN_DIR" && -f "$SESSION_FILE" ]]; then
    SESSION_ID="$(cat "$SESSION_FILE")"
  else
    printf 'z-teardown.sh: WARNING: no --session given and no persisted session-id found for run %s; claim release will be attempted with an empty session (safe no-op if it does not match the holder)\n' "$RUN" >&2
    _warn "session_id_unresolved"
  fi
fi

# ---------------------------------------------------------------------------
# 2. Claim release (always attempted; best-effort no-op if not held by us —
#    see header note. Release BEFORE deregister — invariant preserved.)
# ---------------------------------------------------------------------------
if ! bash "$PLAN_CLAIM_SH" release \
  --slug "$SLUG" --run-id "$RUN" --session "$SESSION_ID" --command "$COMMAND" >&2; then
  printf 'z-teardown.sh: WARNING: claim release returned non-zero for slug %s\n' "$SLUG" >&2
  _warn "claim_release"
fi

# ---------------------------------------------------------------------------
# 3. Deregister (best-effort; always returns 0 by its own contract)
# ---------------------------------------------------------------------------
if ! python3 "$REGISTRY_PY" deregister --run-id "$RUN" --status "$STATUS" >&2; then
  printf 'z-teardown.sh: WARNING: deregister returned non-zero for run %s\n' "$RUN" >&2
  _warn "deregister"
fi

# ---------------------------------------------------------------------------
# 4. run_end log-event
# ---------------------------------------------------------------------------
END_PAYLOAD="$(python3 -c '
import json, sys
print(json.dumps({"status": sys.argv[1], "command": sys.argv[2]}))
' "$STATUS" "$COMMAND")"
if ! Z_HARNESS_SLUG="$SLUG" bash "$LOG_EVENT_SH" "$RUN" run_end "$END_PAYLOAD" >&2; then
  printf 'z-teardown.sh: WARNING: run_end log-event failed for run %s\n' "$RUN" >&2
  _warn "run_end_event"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
python3 -c '
import json, sys
run, status, warnings = sys.argv[1], sys.argv[2], sys.argv[3]
print(json.dumps({"run": run, "status": status, "warnings": warnings.split() if warnings else []}))
' "$RUN" "$STATUS" "$WARNINGS"

exit 0
