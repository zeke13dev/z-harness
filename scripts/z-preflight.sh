#!/usr/bin/env bash
# z-preflight.sh — one-call setup ceremony for a /z-* skill run.
#
# Wraps the ~7 scripts every skill's Setup phase currently duplicates inline
# (plan-path.sh, plan-claim.sh, active-plan-registry.py, run-brief.sh,
# log-event.sh, version.sh, resolve-kernel.sh) behind a single call. NO logic
# is reimplemented here — every step below shells out to the existing script
# that already owns that behavior.
#
# NON-INTERACTIVE CONTRACT: this script never reads stdin and never calls
# AskUserQuestion. All contention/resolution DECISIONS (proceed-anyway,
# abort, use-a-new-slug, etc.) belong to the CALLING skill, which inspects
# this script's exit code / exported vars and branches accordingly. This
# script only performs the mechanical, always-safe sequence and surfaces
# outcomes — it never guesses on the caller's behalf beyond the documented
# defaults below.
#
# Usage:
#   eval "$(bash scripts/z-preflight.sh --command /z-plan --slug my-slug \
#             [--phase plan] [--intent "task text"] [--profile full|lite] \
#             [--ttl 2700] [--session SID] [--no-claim])"
#
# --no-claim: for READ-ONLY commands only (SKILL-STYLE.md §2). Skips step 4
#   (claim slug lock) ENTIRELY — plan-claim.sh acquire is never invoked, so a
#   read-only run never contends with a writer holding the same slug. Steps
#   1/2/3/5/6/7/8 (resolve, session-id, RUN stamp, register, run-brief init,
#   run_start, kernel) still run, so the command remains visible to managed
#   sessions/watchers via the registry. CLAIM_HELD is unconditionally "0".
#
# Output contract (STDOUT ONLY — must stay eval-clean):
#   On success (exit 0), stdout is EXCLUSIVELY a sequence of
#   `export NAME=VALUE` lines (values are `printf %q`-escaped), safe to
#   `eval` directly in the caller's shell. ALL diagnostics, warnings, and
#   holder-contention detail go to STDERR — never stdout — so a caller doing
#   `eval "$(...)"` never has diagnostic text injected into its shell.
#
#   Exported variables (minimum contract):
#     RUN                    — the freshly minted run id (<UTC-stamp>-<slug>)
#     Z_HARNESS_RUN           — alias of RUN (matches existing skill convention)
#     Z_HARNESS_SLUG          — the slug passed via --slug
#     Z_HARNESS_PLAN_DIR      — resolved plan directory (plan-path.sh resolve_plan_path)
#     CURRENT_ARCHIVE_DIR     — $Z_HARNESS_PLAN_DIR/archive/$RUN
#     Z_HARNESS_SESSION_ID    — stable session id (persisted to
#                               $CURRENT_ARCHIVE_DIR/session-id for resume)
#     CLAIM_HELD              — "1" if this run now holds the slug claim lock,
#                               "0" otherwise (see CLAIM_HELD table below)
#     REG_RC                  — active-plan-registry.py register's raw exit
#                               code (0 = registered; 3 = register FAILED —
#                               see graduated-failure policy below). The
#                               CALLER decides what REG_RC!=0 means; this
#                               script never hard-fails on it.
#     KERNEL_PATH             — resolved KERNEL.md path, or "" if none exists
#                               (resolve-kernel.sh's own no-kernel case is
#                               NOT an error)
#
# Sequence (fixed order — matches the frozen design contract for this
# wrapper; does not have to match any one skill's legacy inline order):
#   1. resolve paths            (plan-path.sh resolve_plan_path)
#   2. session-id                (active-plan-registry.py session-id)
#   3. RUN id stamp               (date -u ...)
#   4. claim slug lock            (plan-claim.sh acquire)
#   5. register                   (active-plan-registry.py register)
#   6. run-brief init              (run-brief.sh init)
#   7. run_start log-event          (log-event.sh, payload = version.sh blob)
#   8. resolve kernel                (resolve-kernel.sh)
#
# CLAIM_HELD decision table (mirrors plan-claim.sh's documented exit codes;
# this script makes ONE fixed non-interactive choice per branch since it
# cannot ask the user — the calling skill remains free to re-implement its
# own interactive branching around plan-claim.sh directly instead of this
# wrapper if it needs AskUserQuestion-driven contention handling):
#   acquire rc==0, output=="acquired"|"self-reentry"  -> CLAIM_HELD=1, proceed
#   acquire rc==0, output=="disabled" (CLAIM_DISABLE)  -> CLAIM_HELD=0, proceed
#   acquire rc==2 (stale-takeover — WE now hold it)     -> CLAIM_HELD=1, proceed
#                                                           (the takeover already
#                                                           happened at the OS
#                                                           level; refusing to
#                                                           use it would just
#                                                           mean releasing it
#                                                           again for no benefit)
#   acquire rc==1 (live peer contention)                 -> HARD STOP (exit 10)
#   acquire rc==3 (corrupt lock / invalid holder fields)  -> HARD STOP (exit 11)
#
# Exit codes:
#   0  — success; stdout holds the export lines described above
#   2  — usage error (missing --command/--slug, or invalid --profile)
#   1  — fatal path/base resolution failure (plan-path.sh itself failed) —
#        nothing was created, no lock was ever attempted
#   10 — claim contention: a live peer holds the slug lock (HARD STOP; no
#        lock held; holder JSON from plan-claim.sh is echoed to stderr)
#   11 — claim corrupt / invalid holder fields (HARD STOP; no lock held)
#
# Register failure (active-plan-registry.py register exit 3) is
# graduated-failure, NOT a hard stop: it is loud (emits a registry_error
# event) but proceed-able. REG_RC is exported so the calling skill decides
# whether to proceed uncoordinated or abort — this script never aborts on a
# register failure by itself.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN_PATH_SH="$SCRIPT_DIR/plan-path.sh"
PLAN_CLAIM_SH="$SCRIPT_DIR/plan-claim.sh"
REGISTRY_PY="$SCRIPT_DIR/active-plan-registry.py"
RUN_BRIEF_SH="$SCRIPT_DIR/run-brief.sh"
LOG_EVENT_SH="$SCRIPT_DIR/log-event.sh"
VERSION_SH="$SCRIPT_DIR/version.sh"
RESOLVE_KERNEL_SH="$SCRIPT_DIR/resolve-kernel.sh"

usage() {
  cat >&2 <<'EOF'
usage:
  z-preflight.sh --command CMD --slug SLUG [--phase PHASE] [--intent TEXT]
                  [--profile full|lite] [--ttl SECS] [--session SID] [--no-claim]
EOF
  exit 2
}

COMMAND=""
SLUG=""
PHASE=""
INTENT=""
PROFILE="full"
TTL=""
SESSION_ARG=""
NO_CLAIM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --command)  COMMAND="${2:?}"; shift 2 ;;
    --command=*) COMMAND="${1#*=}"; shift ;;
    --slug)     SLUG="${2:?}"; shift 2 ;;
    --slug=*)   SLUG="${1#*=}"; shift ;;
    --phase)    PHASE="${2:?}"; shift 2 ;;
    --phase=*)  PHASE="${1#*=}"; shift ;;
    --intent)   INTENT="${2:?}"; shift 2 ;;
    --intent=*) INTENT="${1#*=}"; shift ;;
    --profile)  PROFILE="${2:?}"; shift 2 ;;
    --profile=*) PROFILE="${1#*=}"; shift ;;
    --ttl)      TTL="${2:?}"; shift 2 ;;
    --ttl=*)    TTL="${1#*=}"; shift ;;
    --session)  SESSION_ARG="${2:?}"; shift 2 ;;
    --session=*) SESSION_ARG="${1#*=}"; shift ;;
    --no-claim) NO_CLAIM=1; shift ;;
    *) printf 'z-preflight.sh: unknown argument: %s\n' "$1" >&2; usage ;;
  esac
done

[[ -n "$COMMAND" && -n "$SLUG" ]] || usage
case "$PROFILE" in
  full|lite) ;;
  *) printf 'z-preflight.sh: --profile must be full or lite, got: %s\n' "$PROFILE" >&2; usage ;;
esac

[[ -n "$PHASE" ]] || PHASE="${COMMAND#/}"
[[ -n "$INTENT" ]] || INTENT="$COMMAND invocation"

# Export Z_HARNESS_SLUG for the remainder of this process so every wrapped
# script that is slug-aware via that env var (run-brief.sh -> log-event.sh
# resolve-run-dir, active-plan-registry.py's own event emissions, etc.)
# namespaces its output under this slug instead of the legacy global
# archive path.
export Z_HARNESS_SLUG="$SLUG"

# ---------------------------------------------------------------------------
# 1. Resolve paths
# ---------------------------------------------------------------------------
Z_HARNESS_PLAN_DIR="$(bash "$PLAN_PATH_SH" resolve_plan_path "$SLUG")" || {
  printf 'z-preflight.sh: FATAL: plan-path.sh resolve_plan_path failed for slug %s\n' "$SLUG" >&2
  exit 1
}
[[ -n "$Z_HARNESS_PLAN_DIR" ]] || {
  printf 'z-preflight.sh: FATAL: plan-path.sh returned an empty plan dir\n' >&2
  exit 1
}

# ---------------------------------------------------------------------------
# 2. Session id (respect an already-exported Z_HARNESS_SESSION_ID / --session)
# ---------------------------------------------------------------------------
if [[ -n "$SESSION_ARG" ]]; then
  Z_HARNESS_SESSION_ID="$SESSION_ARG"
elif [[ -n "${Z_HARNESS_SESSION_ID:-}" ]]; then
  : # inherit from caller's environment
else
  Z_HARNESS_SESSION_ID="$(python3 "$REGISTRY_PY" session-id)"
fi

# ---------------------------------------------------------------------------
# 3. RUN id stamp
# ---------------------------------------------------------------------------
RUN="$(date -u +%Y%m%dT%H%M%SZ)-${SLUG}"
CURRENT_ARCHIVE_DIR="$Z_HARNESS_PLAN_DIR/archive/$RUN"
mkdir -p "$CURRENT_ARCHIVE_DIR/transcripts"
printf '%s\n' "$Z_HARNESS_SESSION_ID" > "$CURRENT_ARCHIVE_DIR/session-id"

# ---------------------------------------------------------------------------
# 4. Claim slug lock — SKIPPED ENTIRELY under --no-claim (read-only commands;
#    SKILL-STYLE.md §2). plan-claim.sh acquire is never invoked in that case.
# ---------------------------------------------------------------------------
if [[ "$NO_CLAIM" -eq 1 ]]; then
  CLAIM_HELD=0
else
  CLAIM_RC=0
  CLAIM_ARGS=(acquire --slug "$SLUG" --run-id "$RUN" --session "$Z_HARNESS_SESSION_ID" --command "$COMMAND")
  [[ -n "$TTL" ]] && CLAIM_ARGS+=(--ttl "$TTL")
  CLAIM_OUTPUT="$(bash "$PLAN_CLAIM_SH" "${CLAIM_ARGS[@]}" 2>&1)" || CLAIM_RC=$?

  case "$CLAIM_RC" in
    0)
      if [[ "$CLAIM_OUTPUT" == "disabled" ]]; then
        CLAIM_HELD=0
      else
        CLAIM_HELD=1
      fi
      ;;
    2)
      # Stale-takeover succeeded — we now hold the lock. Proceed (see header).
      printf 'z-preflight.sh: NOTE: stale-takeover on slug %s: %s\n' "$SLUG" "$CLAIM_OUTPUT" >&2
      CLAIM_HELD=1
      ;;
    1)
      printf 'z-preflight.sh: HARD STOP: slug %s is held by a live peer: %s\n' "$SLUG" "$CLAIM_OUTPUT" >&2
      exit 10
      ;;
    *)
      printf 'z-preflight.sh: HARD STOP: claim acquire failed (rc=%s) for slug %s: %s\n' "$CLAIM_RC" "$SLUG" "$CLAIM_OUTPUT" >&2
      exit 11
      ;;
  esac
fi

# ---------------------------------------------------------------------------
# 5. Register (graduated failure — never a hard stop from this script)
# ---------------------------------------------------------------------------
REG_RC=0
python3 "$REGISTRY_PY" register \
  --run-id "$RUN" --slug "$SLUG" --command "$COMMAND" --phase "$PHASE" \
  --session "$Z_HARNESS_SESSION_ID" >&2 || REG_RC=$?
if [[ "$REG_RC" -ne 0 ]]; then
  printf 'z-preflight.sh: WARNING: registry register failed (rc=%s) — REG_RC exported for caller to decide\n' "$REG_RC" >&2
fi

# ---------------------------------------------------------------------------
# 6. Run-brief init
# ---------------------------------------------------------------------------
bash "$RUN_BRIEF_SH" init \
  --run "$RUN" --command "$COMMAND" --slug "$SLUG" --profile "$PROFILE" \
  --intent "$INTENT" >&2

# ---------------------------------------------------------------------------
# 7. run_start log-event (payload = version.sh blob + task/session/command)
# ---------------------------------------------------------------------------
VERSION_BLOB="$(bash "$VERSION_SH")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1])
v["task"] = sys.argv[2]
v["session_id"] = sys.argv[3]
v["command"] = sys.argv[4]
print(json.dumps(v))
' "$VERSION_BLOB" "$INTENT" "$Z_HARNESS_SESSION_ID" "$COMMAND")"
Z_HARNESS_SLUG="$SLUG" bash "$LOG_EVENT_SH" "$RUN" run_start "$START_PAYLOAD" >&2

# ---------------------------------------------------------------------------
# 8. Resolve kernel (non-fatal: empty KERNEL_PATH means "no kernel found")
# ---------------------------------------------------------------------------
KERNEL_PATH="$(bash "$RESOLVE_KERNEL_SH" 2>/dev/null || true)"

# ---------------------------------------------------------------------------
# Emit eval-clean export lines on stdout
# ---------------------------------------------------------------------------
printf 'export RUN=%q\n' "$RUN"
printf 'export Z_HARNESS_RUN=%q\n' "$RUN"
printf 'export Z_HARNESS_SLUG=%q\n' "$SLUG"
printf 'export Z_HARNESS_PLAN_DIR=%q\n' "$Z_HARNESS_PLAN_DIR"
printf 'export CURRENT_ARCHIVE_DIR=%q\n' "$CURRENT_ARCHIVE_DIR"
printf 'export Z_HARNESS_SESSION_ID=%q\n' "$Z_HARNESS_SESSION_ID"
printf 'export CLAIM_HELD=%q\n' "$CLAIM_HELD"
printf 'export REG_RC=%q\n' "$REG_RC"
printf 'export KERNEL_PATH=%q\n' "$KERNEL_PATH"

exit 0
