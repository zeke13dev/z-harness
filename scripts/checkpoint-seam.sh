#!/usr/bin/env bash
# checkpoint-seam.sh — one-call checkpoint seam over check-compaction.sh +
# write-clear-checkpoint.sh (SKILL-STYLE.md §2).
#
# Absorbs the ~40-line inline env-var block every durable-boundary checkpoint
# seam used to duplicate (fast-forward-guard hashing, Z_HARNESS_CHECKPOINT_*
# exports, the check-compaction.sh + write-clear-checkpoint.sh sequencing and
# its 3-way branch) behind a single call. NO logic is reimplemented here —
# both wrapped scripts still own their behavior; this only wires them.
#
# Authored at Level 2 by the /z-stats canary rewrite (z-stats itself has no
# checkpoint seam) for the remaining five SKILL-STYLE.md rewrites to consume.
#
# Usage:
#   bash scripts/checkpoint-seam.sh <seam-id> <artifact> <resume-cmd> \
#     [--producer NAME] [--next-step TEXT] [--hash PATH ...]
#
#   <seam-id>     stable phase id — drives the state file
#                 ($Z_HARNESS_PLAN_DIR/.clear-checkpoint-<seam-id>.json) and
#                 the fast-forward comparison.
#   <artifact>    the durable artifact that must exist for this seam to be
#                 complete/fast-forwardable (folded into the guard hash).
#   <resume-cmd>  the exact command a human/watcher should run to resume
#                 (becomes Z_HARNESS_CHECKPOINT_RESUME_COMMAND).
#   --producer    logical producer name (default: an already-exported
#                 Z_HARNESS_CHECKPOINT_PRODUCER, else "checkpoint-seam").
#   --next-step   human-readable next-step text for the handoff
#                 (default: "Resume via: <resume-cmd>").
#   --hash PATH   additional file(s) folded into the fast-forward guard hash
#                 alongside <artifact> (repeatable). A missing file hashes as
#                 a "missing" sentinel — same convention every existing
#                 inline seam block used.
#
# Env vars (read): Z_HARNESS_PLAN_DIR (required), Z_HARNESS_SLUG (optional,
# passed through to write-clear-checkpoint.sh's resume-command default).
#
# Exit codes:
#   0 — no pause needed (below threshold), OR the durable state already
#       matches (fast-forward, printed as STATUS: clear_checkpoint_fast_forward)
#       — caller continues normally, nothing paused.
#   1 — a NEW checkpoint was just written (STATUS: clear_checkpoint ...) —
#       caller should surface the printed output and yield; this phase
#       pauses here (NOT an error).
#   2 — strict context-pressure estimate failure (check-compaction.sh's own
#       documented exit 2) — caller halts without checkpoint handling.
#
# All check-compaction.sh / write-clear-checkpoint.sh stdout/stderr is
# printed verbatim so the caller's transcript shows the same diagnostics
# either script would have produced inline.

set -euo pipefail

_PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}}"

usage() {
  cat >&2 <<'EOF'
usage:
  checkpoint-seam.sh <seam-id> <artifact> <resume-cmd> [--producer NAME]
                      [--next-step TEXT] [--hash PATH ...]
EOF
  exit 2
}

[[ $# -ge 3 ]] || usage
SEAM_ID="$1"
ARTIFACT="$2"
RESUME_CMD="$3"
shift 3

[[ -n "$SEAM_ID" && -n "$ARTIFACT" && -n "$RESUME_CMD" ]] || usage

PRODUCER="${Z_HARNESS_CHECKPOINT_PRODUCER:-checkpoint-seam}"
NEXT_STEP=""
HASH_PATHS=("$ARTIFACT")

while [[ $# -gt 0 ]]; do
  case "$1" in
    --producer)    PRODUCER="${2:?}"; shift 2 ;;
    --producer=*)  PRODUCER="${1#*=}"; shift ;;
    --next-step)   NEXT_STEP="${2:?}"; shift 2 ;;
    --next-step=*) NEXT_STEP="${1#*=}"; shift ;;
    --hash)        HASH_PATHS+=("${2:?}"); shift 2 ;;
    --hash=*)      HASH_PATHS+=("${1#*=}"); shift ;;
    *) printf 'checkpoint-seam.sh: unknown argument: %s\n' "$1" >&2; usage ;;
  esac
done

if [[ -z "${Z_HARNESS_PLAN_DIR:-}" ]]; then
  echo "checkpoint-seam.sh: Z_HARNESS_PLAN_DIR is not set" >&2
  exit 2
fi

[[ -n "$NEXT_STEP" ]] || NEXT_STEP="Resume via: $RESUME_CMD"

FAST_FORWARD_GUARD="$(python3 - "${HASH_PATHS[@]}" <<'PY'
import hashlib
import sys

h = hashlib.sha256()
for path in sys.argv[1:]:
    try:
        with open(path, "rb") as fh:
            h.update(path.encode("utf-8") + b"\0" + fh.read() + b"\0")
    except FileNotFoundError:
        h.update(path.encode("utf-8") + b"\0missing\0")
print(h.hexdigest())
PY
)"

PRODUCER_META_JSON="$(python3 - "$SEAM_ID" "${RUN:-}" "$ARTIFACT" "$PRODUCER" <<'PY'
import json
import sys

seam, run, artifact, producer = sys.argv[1:5]
print(json.dumps({"command": producer, "seam": seam, "run": run, "completed_artifact": artifact}))
PY
)"

export Z_HARNESS_CHECKPOINT_STATUS="context_pressure"
export Z_HARNESS_CHECKPOINT_PRODUCER="$PRODUCER"
export Z_HARNESS_CHECKPOINT_PHASE_ID="$SEAM_ID"
export Z_HARNESS_CHECKPOINT_PHASE_NAME="$SEAM_ID"
export Z_HARNESS_CHECKPOINT_COMPLETED_ARTIFACT="$ARTIFACT"
export Z_HARNESS_CHECKPOINT_FAST_FORWARD_GUARD="$FAST_FORWARD_GUARD"
export Z_HARNESS_CHECKPOINT_STALE_MODE="reject"
export Z_HARNESS_CHECKPOINT_RESUME_COMMAND="$RESUME_CMD"
export Z_HARNESS_CHECKPOINT_NEXT_STEP="$NEXT_STEP"
export Z_HARNESS_CHECKPOINT_PRODUCER_META_JSON="$PRODUCER_META_JSON"

COMPACTION_TRIGGERED=0
bash "$_PLUGIN_ROOT/scripts/check-compaction.sh" || COMPACTION_TRIGGERED=$?

case "$COMPACTION_TRIGGERED" in
  0)
    exit 0
    ;;
  1)
    CHECKPOINT_RC=0
    CHECKPOINT_OUT="$(bash "$_PLUGIN_ROOT/scripts/write-clear-checkpoint.sh")" || CHECKPOINT_RC=$?
    printf '%s\n' "$CHECKPOINT_OUT"
    case "$CHECKPOINT_OUT" in
      STATUS:\ clear_checkpoint_fast_forward*) exit 0 ;;
      STATUS:\ clear_checkpoint*) exit 1 ;;
      *)
        # Includes write-clear-checkpoint.sh's own stale-rejected exit (3):
        # no checkpoint was written and the caller still needs to pause and
        # decide (e.g. re-run with --stale-mode refresh upstream).
        exit 1
        ;;
    esac
    ;;
  2)
    exit 2
    ;;
  *)
    printf 'checkpoint-seam.sh: unexpected check-compaction.sh exit code: %s\n' "$COMPACTION_TRIGGERED" >&2
    exit 1
    ;;
esac
