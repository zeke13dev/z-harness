#!/usr/bin/env bash
# audit-scope-probe.sh — mechanical helpers for z-audit's Phase 0 scope probe.
#
# Extracted from skills/z-audit/SKILL.md (SKILL-STYLE.md size tripwire,
# extraction-first remedy; T114, LEDGER T108/T110 note). Owns the two
# ENTIRELY MECHANICAL pieces of Phase 0 — neither is a decision, so neither
# belongs in skill prose (SKILL-STYLE.md's generating rule):
#
#   fast-path-check  — Step 0a: classify whether a target auto-qualifies for
#                       LIGHT mode (single existing file, no glob metachars,
#                       short argument) and, on qualify, emit the
#                       scope_probe_skipped_fast_path event.
#   write-scope      — Step 0.3: assemble and atomically write SCOPE.json,
#                       archive copy first, then the live copy (same order;
#                       prevents partial-overwrite on parallel runs).
#
# NOT owned here — stays inline in SKILL.md as judgment prose:
#   - Step 0.1/0.2's scope-probe Agent() dispatch and hybrid-return
#     (line-prefix + fenced-JSON) interpretation.
#   - Step 0.3's LIGHT-mode dimensions_hint derivation — reading the topic
#     and seam evidence to decide which audit dimensions apply is a model
#     judgment call; the derived list is simply passed in here as a flag.
#   - Step 0.4's MODE branching (what the host does next).
#
# Usage:
#   bash audit-scope-probe.sh fast-path-check --arg ARG --run RUN
#   bash audit-scope-probe.sh write-scope --plan-dir DIR --run RUN --slug SLUG \
#       --mode MODE --axis AXIS --confidence CONF --reason-codes CSV \
#       --chunks JSON_ARRAY --seams-counted N --candidates-walked N \
#       [--dimensions-hint JSON_ARRAY]
#
# fast-path-check output contract (STDOUT ONLY — eval-clean, mirrors
# z-preflight.sh's convention: `eval "$(bash ... fast-path-check ...)"`):
#   Qualifies:         export SCOPE_FAST_PATH=1
#                      export MODE=LIGHT
#                      export AXIS=none
#                      export CONFIDENCE=high
#                      export REASON_CODES=fast_path_single_file
#                      export REASON='single-file target auto-classified as LIGHT'
#                      export chunks='[]'
#                      export seams_counted=0
#                      export candidates_walked=0
#   Does not qualify:  export SCOPE_FAST_PATH=0   (nothing else — no event)
#   All diagnostics (including the scope_probe_skipped_fast_path log-event
#   call's own stderr) go to stderr, never stdout.
#
# write-scope exit codes:
#   0 — both the archive and live SCOPE.json copies were written.
#   1 — the write failed (archive assembly, archive write, or live write).
#       The caller's documented Phase-0 fallback is to abort Phase 0
#       entirely, log a scope_probe_classified event with
#       status "archive_write_failed", and proceed as MEDIUM — this script
#       never logs that event itself; the caller (SKILL.md) owns that
#       decision and its wording.
#   2 — usage error (missing a required flag).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_EVENT_SH="$SCRIPT_DIR/log-event.sh"

usage() {
  cat >&2 <<'EOF'
usage:
  audit-scope-probe.sh fast-path-check --arg ARG --run RUN
  audit-scope-probe.sh write-scope --plan-dir DIR --run RUN --slug SLUG \
      --mode MODE --axis AXIS --confidence CONF --reason-codes CSV \
      --chunks JSON_ARRAY --seams-counted N --candidates-walked N \
      [--dimensions-hint JSON_ARRAY]
EOF
  exit 2
}

[[ $# -ge 1 ]] || usage
SUBCOMMAND="$1"; shift

case "$SUBCOMMAND" in
  fast-path-check)
    ARG=""
    RUN=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --arg)    ARG="${2:?}"; shift 2 ;;
        --arg=*)  ARG="${1#*=}"; shift ;;
        --run)    RUN="${2:?}"; shift 2 ;;
        --run=*)  RUN="${1#*=}"; shift ;;
        *) printf 'audit-scope-probe.sh fast-path-check: unknown argument: %s\n' "$1" >&2; usage ;;
      esac
    done
    [[ -n "$RUN" ]] || usage
    # ARG may legitimately be empty (never file-exists) — do not require it.

    ARG_LEN=${#ARG}
    case "$ARG" in
      *"*"*|*"?"*|*"["*|*"{"*|*"}"*) IS_GLOB=1 ;;
      *) IS_GLOB=0 ;;
    esac
    EXPANDED_ARG="${ARG/#\~/$HOME}"

    if [[ "$IS_GLOB" -eq 0 && "$ARG_LEN" -lt 200 && -f "$EXPANDED_ARG" ]]; then
      PAYLOAD="$(python3 -c 'import json,sys; print(json.dumps({"command":sys.argv[1],"target":sys.argv[2],"arg_len":int(sys.argv[3])}))' "z-audit" "$EXPANDED_ARG" "$ARG_LEN")"
      bash "$LOG_EVENT_SH" "$RUN" scope_probe_skipped_fast_path "$PAYLOAD" >&2
      printf 'export SCOPE_FAST_PATH=1\n'
      printf 'export MODE=%q\n' "LIGHT"
      printf 'export AXIS=%q\n' "none"
      printf 'export CONFIDENCE=%q\n' "high"
      printf 'export REASON_CODES=%q\n' "fast_path_single_file"
      printf 'export REASON=%q\n' "single-file target auto-classified as LIGHT"
      printf 'export chunks=%q\n' "[]"
      printf 'export seams_counted=%q\n' "0"
      printf 'export candidates_walked=%q\n' "0"
    else
      printf 'export SCOPE_FAST_PATH=0\n'
    fi
    ;;

  write-scope)
    PLAN_DIR=""
    RUN=""
    SLUG=""
    MODE=""
    AXIS=""
    CONFIDENCE=""
    REASON_CODES=""
    CHUNKS="[]"
    SEAMS_COUNTED="0"
    CANDIDATES_WALKED="0"
    DIMENSIONS_HINT=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --plan-dir) PLAN_DIR="${2:?}"; shift 2 ;;
        --plan-dir=*) PLAN_DIR="${1#*=}"; shift ;;
        --run) RUN="${2:?}"; shift 2 ;;
        --run=*) RUN="${1#*=}"; shift ;;
        --slug) SLUG="${2:?}"; shift 2 ;;
        --slug=*) SLUG="${1#*=}"; shift ;;
        --mode) MODE="${2:?}"; shift 2 ;;
        --mode=*) MODE="${1#*=}"; shift ;;
        --axis) AXIS="${2:?}"; shift 2 ;;
        --axis=*) AXIS="${1#*=}"; shift ;;
        --confidence) CONFIDENCE="${2:?}"; shift 2 ;;
        --confidence=*) CONFIDENCE="${1#*=}"; shift ;;
        --reason-codes) REASON_CODES="${2:-}"; shift 2 ;;
        --reason-codes=*) REASON_CODES="${1#*=}"; shift ;;
        --chunks) CHUNKS="${2:-[]}"; shift 2 ;;
        --chunks=*) CHUNKS="${1#*=}"; shift ;;
        --seams-counted) SEAMS_COUNTED="${2:-0}"; shift 2 ;;
        --seams-counted=*) SEAMS_COUNTED="${1#*=}"; shift ;;
        --candidates-walked) CANDIDATES_WALKED="${2:-0}"; shift 2 ;;
        --candidates-walked=*) CANDIDATES_WALKED="${1#*=}"; shift ;;
        --dimensions-hint) DIMENSIONS_HINT="${2:-}"; shift 2 ;;
        --dimensions-hint=*) DIMENSIONS_HINT="${1#*=}"; shift ;;
        *) printf 'audit-scope-probe.sh write-scope: unknown argument: %s\n' "$1" >&2; usage ;;
      esac
    done
    [[ -n "$PLAN_DIR" && -n "$RUN" && -n "$SLUG" && -n "$MODE" ]] || usage

    SCOPE_JSON_STR="$(python3 - "$SLUG" "$RUN" "$MODE" "$AXIS" "$CONFIDENCE" "$REASON_CODES" "$CHUNKS" "$SEAMS_COUNTED" "$CANDIDATES_WALKED" "$DIMENSIONS_HINT" <<'PY'
import json
import sys
from datetime import datetime, timezone

slug, run, mode, axis, confidence, reason_codes_csv, chunks_json, seams_counted, candidates_walked, dimensions_hint_json = sys.argv[1:11]

reason_codes = [c for c in reason_codes_csv.split(",") if c] if reason_codes_csv else []
chunks = json.loads(chunks_json) if chunks_json.strip() else []

scope = {
    "host_command": "z-audit",
    "slug": slug,
    "last_run_id": run,
    "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mode": mode,
    "axis": axis,
    "confidence": confidence,
    "reason_codes": reason_codes,
    "chunks": chunks,
    "seams_counted": int(seams_counted or 0),
    "candidates_walked": int(candidates_walked or 0),
    "scope_probe_version": "1",
}
if dimensions_hint_json.strip():
    scope["dimensions_hint"] = json.loads(dimensions_hint_json)

print(json.dumps(scope, indent=2))
PY
)" || { echo "audit-scope-probe.sh write-scope: FATAL: SCOPE.json assembly failed" >&2; exit 1; }

    ARCHIVE_DIR="$PLAN_DIR/archive/$RUN"
    mkdir -p "$ARCHIVE_DIR"
    ARCHIVE_SCOPE="$ARCHIVE_DIR/SCOPE.json"
    ARCHIVE_TMP="${ARCHIVE_SCOPE}.tmp"
    if ! printf '%s\n' "$SCOPE_JSON_STR" > "$ARCHIVE_TMP" || ! mv "$ARCHIVE_TMP" "$ARCHIVE_SCOPE"; then
      rm -f "$ARCHIVE_TMP"
      echo "audit-scope-probe.sh write-scope: FATAL: archive SCOPE.json write failed" >&2
      exit 1
    fi

    LIVE_SCOPE="$PLAN_DIR/SCOPE-audit.json"
    LIVE_TMP="${LIVE_SCOPE}.tmp.$$"
    if ! printf '%s\n' "$SCOPE_JSON_STR" > "$LIVE_TMP" || ! mv "$LIVE_TMP" "$LIVE_SCOPE"; then
      rm -f "$LIVE_TMP"
      echo "audit-scope-probe.sh write-scope: FATAL: live SCOPE-audit.json write failed" >&2
      exit 1
    fi
    ;;

  *)
    printf 'audit-scope-probe.sh: unknown subcommand: %s\n' "$SUBCOMMAND" >&2
    usage
    ;;
esac
