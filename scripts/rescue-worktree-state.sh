#!/bin/bash
# rescue-worktree-state.sh — evacuate in-repo z-harness state to the external base
# BEFORE a git worktree is archived/deleted, so a LIVE run's logs are not lost.
#
# This is the INVERSE of migrate-plan-layout.sh:
#   - COPY, never move. The worktree is about to be deleted; we never rm a live
#     run's source, and we never need the worktree copy afterwards.
#   - NO live-run barrier. Rescuing a LIVE run (the case migrate refuses under
#     invariant 8) is the entire point.
#   - Source-wins MERGE into the resolved external base, with any displaced
#     destination file preserved as `<name>.pre-rescue` (rsync --backup), so a
#     newer external file is never silently clobbered.
#   - metrics.jsonl is dedup-appended (keep existing target lines, append only
#     source lines not already present) — mirrors migrate's merge_metrics.
#
# What is copied (allowlist): plans/ archive/ improvements/ adhoc/ metrics.jsonl
# What is NEVER copied: active-plans/ (copying a status:running record would create
#   a zombie), *.lock (transient), followups/ (in-flight locks; migrate skips these
#   by default too).
#
# Usage:
#   rescue-worktree-state.sh [--dry-run] [<repo-root>]
#     <repo-root>  Worktree root to rescue FROM. Defaults to the current directory.
#     --dry-run    Show exactly what would be copied; change nothing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/plan-path.sh
source "$SCRIPT_DIR/plan-path.sh"

DRY_RUN=0
REPO_ROOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] [<repo-root>]"
      echo "  Copy in-repo z-harness state (plans/, archive/, improvements/, adhoc/,"
      echo "  metrics.jsonl) to the resolved external base before a worktree is archived."
      exit 0
      ;;
    -*) echo "Unknown flag: $1" >&2; echo "Usage: $0 [--dry-run] [<repo-root>]" >&2; exit 2 ;;
    *)
      if [[ -n "$REPO_ROOT" ]]; then
        echo "Unexpected extra argument: $1" >&2; exit 2
      fi
      REPO_ROOT="$1"; shift ;;
  esac
done

REPO_ROOT="${REPO_ROOT:-$(pwd)}"
if [[ ! -d "$REPO_ROOT" ]]; then
  echo "FATAL: repo-root is not a directory: $REPO_ROOT" >&2
  exit 2
fi
# Canonicalize to an absolute, symlink-resolved path BEFORE we cd, so that a
# relative <repo-root> argument does not turn "$REPO_ROOT/z-harness" into a
# doubly-nested (and falsely absent) path after the cd below.
REPO_ROOT="$(cd "$REPO_ROOT" && pwd -P)"
# Resolve base relative to the target worktree's git context.
cd "$REPO_ROOT"

if ! command -v rsync >/dev/null 2>&1; then
  echo "FATAL: rsync is required but not found on PATH." >&2
  exit 2
fi

# --- Resolve source (in-repo legacy base) and destination (external base) -----
SRC="$REPO_ROOT/z-harness"

if [[ ! -e "$SRC" ]]; then
  echo "Nothing to rescue: no in-repo z-harness/ directory at $SRC (state is already external)."
  exit 0
fi
if [[ -L "$SRC" ]]; then
  echo "Nothing to rescue: $SRC is a symlink (state already lives outside the worktree)."
  exit 0
fi

DST="$(base_dir)"
if [[ -z "$DST" ]]; then
  echo "FATAL: could not resolve the external base directory." >&2
  exit 1
fi

# realpath helper (portable). An existing dir resolves directly; a not-yet-created
# leaf resolves via its existing parent (reattaching the basename) so the
# inside-repo guard below cannot be bypassed when the base sits under a symlinked
# parent and does not exist yet.
_real() {
  local p="$1" parent leaf
  if [[ -d "$p" ]]; then ( cd "$p" && pwd -P ); return; fi
  parent="$(dirname "$p")"; leaf="$(basename "$p")"
  if [[ -d "$parent" ]]; then
    printf '%s/%s' "$( cd "$parent" && pwd -P )" "$leaf"
  else
    printf '%s' "$p"
  fi
}
SRC_REAL="$(_real "$SRC")"
DST_REAL="$(_real "$DST")"
REPO_REAL="$(_real "$REPO_ROOT")"

if [[ "$SRC_REAL" == "$DST_REAL" ]]; then
  echo "Nothing to rescue: in-repo path IS the external base ($SRC_REAL)."
  exit 0
fi
# If the resolved base is still inside the repo, the external base is disabled and
# there is nowhere durable to rescue to.
case "$DST_REAL/" in
  "$REPO_REAL"/*)
    echo "REFUSED: the resolved base is inside the repo ($DST_REAL) — the external" >&2
    echo "         base is disabled, so there is nowhere durable to rescue to." >&2
    echo "         Enable it and retry, e.g.:" >&2
    echo "           Z_HARNESS_EXTERNAL_DEFAULT=1 bash $0 ${DRY_RUN:+--dry-run }$REPO_ROOT" >&2
    echo "         or set an absolute Z_HARNESS_BASE_DIR outside the repo." >&2
    exit 1
    ;;
esac

# --- Copy allowlisted directories ----------------------------------------------
# Source-wins, but any displaced destination file is preserved under a per-run
# backup dir <base>/.pre-rescue/<stamp>/<dir>/ — a unique location per rescue, so a
# second rescue never clobbers an earlier run's backup.
STAMP="${Z_HARNESS_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
DIRS=(plans archive improvements adhoc)
copied_any=0

echo "Rescue source:      $SRC_REAL"
echo "Rescue destination: $DST_REAL"
[[ "$DRY_RUN" == "1" ]] && echo "(dry-run — no changes will be made)"

for d in "${DIRS[@]}"; do
  [[ -d "$SRC/$d" ]] || continue
  copied_any=1
  rsync_opts=(-a --backup --backup-dir="$DST_REAL/.pre-rescue/$STAMP/$d" --exclude '*.lock')
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "--- would copy: $d/ ---"
    rsync -ni "${rsync_opts[@]}" "$SRC/$d/" "$DST/$d/" || true
  else
    mkdir -p "$DST/$d"
    rsync "${rsync_opts[@]}" "$SRC/$d/" "$DST/$d/"
    echo "RESCUED ($d/): $SRC/$d -> $DST/$d"
  fi
done

# --- metrics.jsonl: dedup-append, never clobber --------------------------------
SRC_METRICS="$SRC/metrics.jsonl"
DST_METRICS="$DST/metrics.jsonl"
if [[ -f "$SRC_METRICS" ]]; then
  copied_any=1
  if [[ "$DRY_RUN" == "1" ]]; then
    if [[ -f "$DST_METRICS" ]]; then
      echo "--- would dedup-append metrics.jsonl into existing $DST_METRICS ---"
    else
      echo "--- would copy metrics.jsonl -> $DST_METRICS ---"
    fi
  elif [[ ! -f "$DST_METRICS" ]]; then
    mkdir -p "$DST"
    cp -p "$SRC_METRICS" "$DST_METRICS"
    echo "RESCUED (metrics.jsonl): $SRC_METRICS -> $DST_METRICS"
  else
    tmp="$(mktemp "$DST/.metrics-rescue.XXXXXX")"
    if python3 - "$DST_METRICS" "$SRC_METRICS" "$tmp" <<'PY'
import sys
dst_path, src_path, tmp_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(dst_path, "r", encoding="utf-8", errors="surrogateescape") as f:
    dst_lines = f.readlines()
present = set(dst_lines)
with open(src_path, "r", encoding="utf-8", errors="surrogateescape") as f:
    src_lines = f.readlines()
with open(tmp_path, "w", encoding="utf-8", errors="surrogateescape") as out:
    out.writelines(dst_lines)
    for line in src_lines:
        if line in present:
            continue  # already present in target — skip (idempotent re-run)
        out.write(line)
PY
    then
      mv -f "$tmp" "$DST_METRICS"
      echo "RESCUED (metrics.jsonl): dedup-appended into $DST_METRICS"
    else
      rm -f "$tmp"
      echo "WARN (metrics.jsonl): dedup-append failed — source left intact, target unchanged." >&2
    fi
  fi
fi

if [[ "$copied_any" == "0" ]]; then
  echo "Nothing to rescue: $SRC has no plans/, archive/, improvements/, adhoc/, or metrics.jsonl."
  exit 0
fi

# --- Record the rescue ---------------------------------------------------------
if [[ "$DRY_RUN" != "1" && -x "$SCRIPT_DIR/log-event.sh" ]]; then
  "$SCRIPT_DIR/log-event.sh" "${Z_HARNESS_RUN_ID:-rescue}" worktree_state_rescued \
    "$(printf '{"src":"%s","dst":"%s"}' "$SRC_REAL" "$DST_REAL")" >/dev/null 2>&1 || true
  echo
  echo "Done. Your z-harness state now lives at $DST_REAL and survives worktree archive."
  echo "The in-repo copy was left intact; you can safely archive this worktree now."
fi
