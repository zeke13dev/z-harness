#!/usr/bin/env bash
# plan-claim.sh — Thin wrapper over sink-lock.sh for slug-level claim locks.
#
# Manages a per-slug hard lock so a second Claude session cannot silently
# double-work (and clobber SPEC/PLAN/TASKS) a slug already claimed by a live
# peer. Computes the canonical lock-path for a slug, manages holder identity +
# TTL, emits structured events, and maps sink-lock's exit codes to a stable
# contract.
#
# BUSINESS LOGIC (AskUser branches) LIVES IN THE CALLER, NOT HERE. This script
# is NON-INTERACTIVE: it reads/writes/emits-events only, NEVER reads stdin or
# calls AskUserQuestion. All decision-making (proceed/abort/use-new-slug) is the
# caller's. Exit codes + printed holder JSON are the only interface.
#
# HOLDER IDENTITY MODEL (SPEC invariant 6):
#   The sink-lock `holder` string is the only carrier of identity. We encode
#   HOLDER = "<session>::<run>::<command>" and parse it back for contention
#   display and the self-reentry guard. acquire rejects any of the three fields
#   containing a ':' (exit 2) so the '::' delimiter stays unambiguous.
#
# SESSION ID (SPEC invariant 7):
#   --session is REQUIRED input. This script NEVER calls `session-id` itself —
#   active-plan-registry.py session-id is not stable across invocations. The
#   caller is responsible for exporting + persisting + restoring the session id
#   and passing it via --session to every call.
#
# Usage:
#   plan-claim.sh acquire    --slug S --run-id R --session SID --command C [--ttl N]
#   plan-claim.sh heartbeat  --slug S --run-id R --session SID --command C [--ttl N]
#   plan-claim.sh release    --slug S --run-id R --session SID --command C [--ttl N]
#   plan-claim.sh status     --slug S [--ttl N]
#   plan-claim.sh reap-stale --slug S [--ttl N]
#
# Exit codes — acquire:
#   0 — acquired / self-reentry / disabled
#   1 — live-peer contention (holder JSON printed to stdout; display-only/TOCTOU)
#   2 — stale-takeover succeeded — WE now hold the lock (caller confirms first)
#   3 — corrupt lock OR invalid-holder/invalid-args — we do NOT hold the lock
# Exit codes — heartbeat:
#   0 — refreshed / disabled / transient read error (heartbeat_error, non-fatal)
#   9 — confirmed lost claim (holder present-and-different, or free)
#   (plan-claim.sh-specific; 9 is NOT a sink-lock code)
# Exit codes — release:
#   0 — confirmed released / already free / disabled
#   4 — ownership mismatch (peer preserved; no retry)
#   5 — release timed out after three total attempts
#   other nonzero — unexpected sink-lock failure
# Exit codes — status:
#   0 — printed holder JSON or {"state":"free"}
#   3 — corrupt lock content
# Exit codes — reap-stale (read-only; delegates to sink-lock check-stale):
#   0 — held  (lock is live and held by a live process)
#   1 — free  (no lock file or empty)
#   2 — stale (lock held by a dead PID or expired heartbeat)
#   3 — corrupt (non-empty but unparseable JSON)
# Exit codes — usage / invalid args (any subcommand): 2

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAN_PATH_SH="$SCRIPT_DIR/plan-path.sh"
SINK_LOCK_SH="$SCRIPT_DIR/sink-lock.sh"
LOG_EVENT_SH="$SCRIPT_DIR/log-event.sh"

DEFAULT_TTL_SECONDS=2700

# ---------------------------------------------------------------------------
# usage / fatal
# ---------------------------------------------------------------------------
_usage() {
  cat >&2 <<'EOF'
Usage:
  plan-claim.sh acquire    --slug S --run-id R --session SID --command C [--ttl N]
  plan-claim.sh heartbeat  --slug S --run-id R --session SID --command C [--ttl N]
  plan-claim.sh release    --slug S --run-id R --session SID --command C [--ttl N]
  plan-claim.sh status     --slug S [--ttl N]
  plan-claim.sh reap-stale --slug S [--ttl N]
EOF
  exit 2
}

# ---------------------------------------------------------------------------
# emit_event <kind> <json-payload>
# Non-fatal: claim correctness must NEVER depend on telemetry. A failure to log
# (missing run-id, log-event.sh error, etc.) is swallowed.
# ---------------------------------------------------------------------------
emit_event() {
  local kind="$1" payload="$2"
  [[ -x "$LOG_EVENT_SH" ]] || return 0
  [[ -n "${RUN_ID:-}" ]] || return 0
  Z_HARNESS_SLUG="${SLUG:-}" bash "$LOG_EVENT_SH" "$RUN_ID" "$kind" "$payload" >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# json_str <value>  — emit a JSON-escaped string literal for the given value.
# Used to build event payloads + holder JSON safely (handles quotes/backslashes).
# ---------------------------------------------------------------------------
json_str() {
  python3 -c 'import json,sys; sys.stdout.write(json.dumps(sys.argv[1]))' "$1" 2>/dev/null || printf '""'
}

# ---------------------------------------------------------------------------
# Argument parsing — shared across subcommands.
#   SLUG RUN_ID SESSION_ID COMMAND TTL
# ---------------------------------------------------------------------------
SLUG=""
RUN_ID=""
SESSION_ID=""
COMMAND=""
TTL=""

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --slug)     SLUG="${2:-}"; shift 2 ;;
      --slug=*)   SLUG="${1#*=}"; shift ;;
      --run-id)   RUN_ID="${2:-}"; shift 2 ;;
      --run-id=*) RUN_ID="${1#*=}"; shift ;;
      --session)  SESSION_ID="${2:-}"; shift 2 ;;
      --session=*) SESSION_ID="${1#*=}"; shift ;;
      --command)  COMMAND="${2:-}"; shift 2 ;;
      --command=*) COMMAND="${1#*=}"; shift ;;
      --ttl)      TTL="${2:-}"; shift 2 ;;
      --ttl=*)    TTL="${1#*=}"; shift ;;
      *)
        printf 'plan-claim.sh: unknown option: %s\n' "$1" >&2
        _usage
        ;;
    esac
  done
}

# resolve_ttl — --ttl arg, else $Z_HARNESS_CLAIM_TTL_SECS, else default 2700.
resolve_ttl() {
  if [[ -n "$TTL" ]]; then
    printf '%s' "$TTL"
  elif [[ -n "${Z_HARNESS_CLAIM_TTL_SECS:-}" ]]; then
    printf '%s' "$Z_HARNESS_CLAIM_TTL_SECS"
  else
    printf '%s' "$DEFAULT_TTL_SECONDS"
  fi
}

# validate_slug_path — reject a slug containing '/' or '..' (defense-in-depth).
validate_slug_path() {
  if [[ "$SLUG" == *"/"* || "$SLUG" == *".."* ]]; then
    printf 'plan-claim.sh: invalid slug (contains / or ..): %s\n' "$SLUG" >&2
    exit 2
  fi
}

# validate_holder_fields — reject a ':' in session, run, or command (invariant 6)
# so the '::' delimiter in the holder string is unambiguous. exit 2.
validate_holder_fields() {
  local f
  for f in "$SESSION_ID" "$RUN_ID" "$COMMAND"; do
    if [[ "$f" == *":"* ]]; then
      printf 'plan-claim.sh: holder field may not contain ":" (got %s)\n' "$f" >&2
      exit 2
    fi
  done
}

# lockpath — compute "$(claims_dir)/<slug>.lock"; mkdir -p the dir first.
lockpath() {
  local claims
  claims="$(bash "$PLAN_PATH_SH" claims_dir)" || {
    printf 'plan-claim.sh: failed to resolve claims_dir\n' >&2
    exit 3
  }
  [[ -n "$claims" ]] || {
    printf 'plan-claim.sh: empty claims_dir\n' >&2
    exit 3
  }
  mkdir -p "$claims" 2>/dev/null || true
  printf '%s/%s.lock' "$claims" "$SLUG"
}

# read_holder_json <lockpath> <ttl>
# Echoes sink-lock read-holder JSON to stdout; returns sink-lock's rc
# (0 = printed held/free JSON, 3 = corrupt).
read_holder_json() {
  local lp="$1" ttl="$2"
  bash "$SINK_LOCK_SH" read-holder "$lp" "--ttl-seconds=$ttl"
}

# parse_holder_field <holder-string> <index>
# Splits the holder string on the FIRST and SECOND '::' only (trailing '::'
# belong to command, per invariant 6). index: session|run|command.
# Echoes the requested field.
parse_holder_field() {
  python3 - "$1" "$2" <<'PYEOF'
import sys
holder = sys.argv[1]
which = sys.argv[2]
# Split on the first and second "::" only; the remainder (which may itself
# contain "::") is the command field.
parts = holder.split("::", 2)
session = parts[0] if len(parts) > 0 else ""
run = parts[1] if len(parts) > 1 else ""
command = parts[2] if len(parts) > 2 else ""
print({"session": session, "run": run, "command": command}.get(which, ""))
PYEOF
}

# json_get <json> <key> — extract a top-level key from a JSON object as text.
json_get() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys
try:
    obj = json.loads(sys.argv[1])
except Exception:
    print("")
    sys.exit(0)
val = obj.get(sys.argv[2], "") if isinstance(obj, dict) else ""
if val is None:
    val = ""
print(val)
PYEOF
}

# ---------------------------------------------------------------------------
# cmd_acquire
# ---------------------------------------------------------------------------
cmd_acquire() {
  validate_slug_path
  validate_holder_fields

  if [[ "${Z_HARNESS_CLAIM_DISABLE:-}" == "1" ]]; then
    printf 'disabled\n'
    exit 0
  fi

  local ttl lp holder rc
  ttl="$(resolve_ttl)"
  lp="$(lockpath)"
  holder="${SESSION_ID}::${RUN_ID}::${COMMAND}"

  rc=0
  bash "$SINK_LOCK_SH" acquire "$lp" "$holder" "--ttl-seconds=$ttl" || rc=$?

  case "$rc" in
    0)
      emit_event plan_claim_acquired \
        "$(printf '{"slug":%s,"run_id":%s,"session":%s}' \
          "$(json_str "$SLUG")" "$(json_str "$RUN_ID")" "$(json_str "$SESSION_ID")")"
      printf 'acquired\n'
      exit 0
      ;;
    1)
      # Live peer. Re-read holder (best-effort, TOCTOU — display-only; the gate
      # keys on rc==1, not on the JSON). The holder may have changed/freed since
      # sink-lock returned 1.
      local hj h_holder h_session h_run h_cmd hb_age
      hj="$(read_holder_json "$lp" "$ttl" 2>/dev/null)" || hj=""
      h_holder="$(json_get "$hj" holder)"
      hb_age="$(json_get "$hj" heartbeat_age_s)"
      h_session="$(parse_holder_field "$h_holder" session)"
      h_run="$(parse_holder_field "$h_holder" run)"
      h_cmd="$(parse_holder_field "$h_holder" command)"

      # Self-reentry guard: same session, different run → proceed (do not contend).
      if [[ -n "$h_session" && "$h_session" == "$SESSION_ID" && "$h_run" != "$RUN_ID" ]]; then
        emit_event plan_claim_self_reentry \
          "$(printf '{"slug":%s,"prior_run":%s}' \
            "$(json_str "$SLUG")" "$(json_str "$h_run")")"
        printf 'self-reentry\n'
        exit 0
      fi

      emit_event plan_claim_contended \
        "$(printf '{"slug":%s,"holder_session":%s,"holder_run":%s,"holder_command":%s,"heartbeat_age_s":%s}' \
          "$(json_str "$SLUG")" "$(json_str "$h_session")" "$(json_str "$h_run")" \
          "$(json_str "$h_cmd")" "$(json_str "${hb_age:-}")")"
      # Print holder JSON (session, run, command, heartbeat_age_s) for caller display.
      printf '{"session":%s,"run":%s,"command":%s,"heartbeat_age_s":%s}\n' \
        "$(json_str "$h_session")" "$(json_str "$h_run")" "$(json_str "$h_cmd")" \
        "$(json_str "${hb_age:-}")"
      exit 1
      ;;
    2)
      # sink-lock already performed a stale-takeover — WE now hold the lock.
      local hj prior_holder prior_age
      hj="$(read_holder_json "$lp" "$ttl" 2>/dev/null)" || hj=""
      # After takeover the JSON now reflects OUR record; the "prior" holder is no
      # longer recoverable from the lock. Best-effort: report what is there.
      prior_holder="$(json_get "$hj" holder)"
      prior_age="$(json_get "$hj" heartbeat_age_s)"
      emit_event plan_claim_stale_takeover \
        "$(printf '{"slug":%s,"prior_holder":%s,"prior_heartbeat_age_s":%s}' \
          "$(json_str "$SLUG")" "$(json_str "$prior_holder")" "$(json_str "${prior_age:-}")")"
      printf '{"prior_holder":%s,"prior_heartbeat_age_s":%s}\n' \
        "$(json_str "$prior_holder")" "$(json_str "${prior_age:-}")"
      exit 2
      ;;
    *)
      # rc==3 (corrupt) or any unexpected sink-lock error → we do NOT hold the lock.
      emit_event registry_error \
        "$(printf '{"op":"claim_acquire","slug":%s,"rc":%s}' \
          "$(json_str "$SLUG")" "$(json_str "$rc")")"
      printf 'corrupt\n'
      exit 3
      ;;
  esac
}

# ---------------------------------------------------------------------------
# cmd_heartbeat — lost-claim aware.
# ---------------------------------------------------------------------------
cmd_heartbeat() {
  validate_slug_path
  validate_holder_fields

  if [[ "${Z_HARNESS_CLAIM_DISABLE:-}" == "1" ]]; then
    exit 0
  fi

  local ttl lp holder hj rc h_holder
  ttl="$(resolve_ttl)"
  lp="$(lockpath)"
  holder="${SESSION_ID}::${RUN_ID}::${COMMAND}"

  # Read current holder FIRST. Distinguish ownership-change from a read error.
  rc=0
  hj="$(read_holder_json "$lp" "$ttl" 2>/dev/null)" || rc=$?

  if [[ "$rc" -ne 0 ]]; then
    # Transient read/corrupt error (read-holder exit 3, I/O glitch). NOT a
    # takeover — emit heartbeat_error and return non-fatal (exit 0). The caller
    # continues and retries at the next heartbeat point.
    emit_event heartbeat_error \
      "$(printf '{"slug":%s,"run_id":%s,"reason":%s}' \
        "$(json_str "$SLUG")" "$(json_str "$RUN_ID")" "$(json_str "read_holder_rc=$rc")")"
    exit 0
  fi

  local state
  state="$(json_get "$hj" state)"

  if [[ "$state" == "free" ]]; then
    # Lock legitimately released — treat as lost.
    emit_event plan_claim_lost \
      "$(printf '{"slug":%s,"current_holder":%s}' \
        "$(json_str "$SLUG")" "$(json_str "")")"
    exit 9
  fi

  h_holder="$(json_get "$hj" holder)"
  if [[ "$h_holder" != "$holder" ]]; then
    # Confirmed ownership change — a peer holds the lock now.
    emit_event plan_claim_lost \
      "$(printf '{"slug":%s,"current_holder":%s}' \
        "$(json_str "$SLUG")" "$(json_str "$h_holder")")"
    exit 9
  fi

  # holder == HOLDER → refresh. The holder-identity check MUST precede this call:
  # sink-lock heartbeat refreshes whatever holder currently owns the lock (it
  # only verifies the recorded daemon pid is alive), so calling it after a peer
  # takeover would extend the PEER's lease.
  local hb_rc=0
  bash "$SINK_LOCK_SH" heartbeat "$lp" || hb_rc=$?
  if [[ "$hb_rc" -ne 0 ]]; then
    # sink-lock heartbeat failed AFTER we confirmed we are the holder. This is a
    # transient failure (e.g. the daemon pid races to death between the read and
    # the refresh); treat as non-fatal heartbeat_error, not a confirmed takeover.
    emit_event heartbeat_error \
      "$(printf '{"slug":%s,"run_id":%s,"reason":%s}' \
        "$(json_str "$SLUG")" "$(json_str "$RUN_ID")" "$(json_str "sink_heartbeat_rc=$hb_rc")")"
    exit 0
  fi
  exit 0
}

# ---------------------------------------------------------------------------
# cmd_release — bounded release with an exact expected-holder guard.
# ---------------------------------------------------------------------------
cmd_release() {
  validate_slug_path
  validate_holder_fields

  if [[ "${Z_HARNESS_CLAIM_DISABLE:-}" == "1" ]]; then
    exit 0
  fi

  local lp holder
  lp="$(lockpath)"
  holder="${SESSION_ID}::${RUN_ID}::${COMMAND}"

  # --expected-holder is repeated verbatim on every attempt. Retry only rc=5:
  # the holder has already received SIGTERM but its flock was not observably
  # free within the primitive's bounded wait. rc=4 is a peer/identity mismatch
  # and must never be retried or touched.
  local attempt=1 max_attempts=3 release_rc=0 release_diag="" outcome=""
  while [[ "$attempt" -le "$max_attempts" ]]; do
    release_rc=0
    release_diag=""
    release_diag="$(bash "$SINK_LOCK_SH" release "$lp" "--expected-holder=$holder" 2>&1)" || release_rc=$?

    case "$release_rc" in
      0)
        outcome="released"
        ;;
      1)
        outcome="already_free"
        ;;
      5)
        if [[ "$attempt" -lt "$max_attempts" ]]; then
          attempt=$((attempt + 1))
          continue
        fi
        ;;
    esac

    if [[ "$release_rc" -eq 0 || "$release_rc" -eq 1 ]]; then
      emit_event plan_claim_released \
        "$(printf '{"slug":%s,"run_id":%s,"outcome":%s,"attempts":%s}' \
          "$(json_str "$SLUG")" "$(json_str "$RUN_ID")" \
          "$(json_str "$outcome")" "$attempt")"
      exit 0
    fi
    break
  done

  if [[ "$release_rc" -eq 4 ]]; then
    outcome="ownership_mismatch"
  elif [[ "$release_rc" -eq 5 ]]; then
    outcome="timeout_exhausted"
  else
    outcome="unexpected_failure"
  fi
  emit_event plan_claim_release_failed \
    "$(printf '{"slug":%s,"run_id":%s,"outcome":%s,"sink_rc":%s,"attempts":%s,"diagnostic":%s}' \
      "$(json_str "$SLUG")" "$(json_str "$RUN_ID")" \
      "$(json_str "$outcome")" "$release_rc" "$attempt" \
      "$(json_str "$release_diag")")"
  printf 'plan-claim.sh: release failed for slug %s (outcome=%s, sink_rc=%s, attempts=%s)' \
    "$SLUG" "$outcome" "$release_rc" "$attempt" >&2
  if [[ -n "$release_diag" ]]; then
    printf ': %s' "$release_diag" >&2
  fi
  printf '\n' >&2
  exit "$release_rc"
}

# ---------------------------------------------------------------------------
# cmd_status — read-only; delegates to sink-lock read-holder. No events.
# Passes the SAME TTL acquire uses so the `stale` flag is consistent.
# ---------------------------------------------------------------------------
cmd_status() {
  validate_slug_path
  local ttl lp rc
  ttl="$(resolve_ttl)"
  lp="$(lockpath)"
  rc=0
  bash "$SINK_LOCK_SH" read-holder "$lp" "--ttl-seconds=$ttl" || rc=$?
  exit "$rc"
}

# ---------------------------------------------------------------------------
# cmd_reap_stale — read-only stale check. Delegates to sink-lock check-stale.
# Prints exactly one lowercase word to stdout and exits with the matching code:
#   held    (exit 0) — lock is live and held by a live process
#   free    (exit 1) — no lock file or empty
#   stale   (exit 2) — dead PID or expired heartbeat
#   corrupt (exit 3) — non-empty but unparseable JSON
# NEVER acquires, releases, or kills anything. --slug is the only required arg.
# ---------------------------------------------------------------------------
cmd_reap_stale() {
  validate_slug_path
  local ttl lp rc
  ttl="$(resolve_ttl)"
  lp="$(lockpath)"
  rc=0
  bash "$SINK_LOCK_SH" check-stale "$lp" "--ttl-seconds=$ttl" || rc=$?
  case "$rc" in
    0) printf 'held\n'    ;;
    1) printf 'free\n'    ;;
    2) printf 'stale\n'   ;;
    *) printf 'corrupt\n' ;;
  esac
  exit "$rc"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
[[ $# -lt 1 ]] && _usage
SUBCOMMAND="$1"
shift
parse_args "$@"

# --slug is required for every subcommand.
[[ -n "$SLUG" ]] || { printf 'plan-claim.sh: --slug is required\n' >&2; _usage; }

case "$SUBCOMMAND" in
  acquire)
    # --run-id, --session, --command required.
    [[ -n "$RUN_ID" && -n "$SESSION_ID" && -n "$COMMAND" ]] || {
      printf 'plan-claim.sh acquire: --run-id, --session, --command are required\n' >&2; _usage; }
    cmd_acquire
    ;;
  heartbeat)
    [[ -n "$RUN_ID" && -n "$SESSION_ID" && -n "$COMMAND" ]] || {
      printf 'plan-claim.sh heartbeat: --run-id, --session, --command are required\n' >&2; _usage; }
    cmd_heartbeat
    ;;
  release)
    [[ -n "$RUN_ID" && -n "$SESSION_ID" && -n "$COMMAND" ]] || {
      printf 'plan-claim.sh release: --run-id, --session, --command are required\n' >&2; _usage; }
    cmd_release
    ;;
  status)
    cmd_status
    ;;
  reap-stale)
    cmd_reap_stale
    ;;
  *)
    printf 'plan-claim.sh: unknown subcommand: %s\n' "$SUBCOMMAND" >&2
    _usage
    ;;
esac
