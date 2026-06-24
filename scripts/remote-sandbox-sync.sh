#!/usr/bin/env bash
# Sync the local working tree to a per-(slug, task-id) sandbox on the
# remote host, honoring an excludes list. Invoked by the remote-runner
# subagent before running cargo/qtctl on remote.
#
# Usage:
#   remote-sandbox-sync.sh <remote-host> <slug> <task-id> [--no-delete] [--allow-no-exclude]
#
# Examples:
#   remote-sandbox-sync.sh zeke-pc expand-sports-ml T030
#   remote-sandbox-sync.sh zeke-pc data-overhaul C-001 --no-delete
#
# Remote path layout:
#   <host>:~/dev/qt-bot-sandbox/                     ← CONTAINER (may hold helpers/README)
#   <host>:~/dev/qt-bot-sandbox/sandbox/             ← all ephemeral slug trees live here
#   <host>:~/dev/qt-bot-sandbox/sandbox/<slug>/base/        ← shared warm base (seeded once per slug)
#   <host>:~/dev/qt-bot-sandbox/sandbox/<slug>/<task-id>/   ← per-task overlay via --link-dest
#
# Everything ephemeral is nested under .../sandbox/ so the container root stays
# clean: anything that lands directly in qt-bot-sandbox/ (and is not `sandbox/`)
# is unambiguously stray and safe for the GC reaper to remove. A misdirected
# rsync can no longer pollute alongside real slug dirs.
#
# Exclude file lookup order:
#   1. $(pwd)/.z-harness-rsync-exclude         (per-project override)
#   2. $ANTIGRAVITY_PLUGIN_ROOT / $CLAUDE_PLUGIN_ROOT/.z-harness-rsync-exclude  (plugin default)
#
# Output: writes rsync's stats summary to stdout. Exits non-zero on rsync error.

set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: remote-sandbox-sync.sh <remote-host> <slug> <task-id> [--no-delete]" >&2
  exit 2
fi

REMOTE_HOST="$1"
SLUG="$2"
TASK_ID="$3"
shift 3

# --- Input validation: reject path-traversal or ambiguous values ---------------
case "$TASK_ID" in
  base|*/*|*..*|""|*\'*) echo "remote-sandbox-sync.sh: invalid TASK_ID '$TASK_ID'" >&2; exit 2;;
esac
case "$SLUG" in
  */*|*..*|""|*\'*) echo "remote-sandbox-sync.sh: invalid SLUG '$SLUG'" >&2; exit 2;;
esac
# -------------------------------------------------------------------------------

DELETE_FLAG="--delete"
ALLOW_NO_EXCLUDE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-delete) DELETE_FLAG="" ;;
    --allow-no-exclude) ALLOW_NO_EXCLUDE=1 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

# Resolve the local tree to ship. Default: the git work tree of the current cwd,
# which for a linked worktree is the WORKTREE root (verified: `git rev-parse
# --show-toplevel` returns the worktree path, not the common dir). This is correct
# ONLY when cwd is the worktree. When the orchestrator's cwd is the main checkout but
# edits land in a worktree via absolute paths, set Z_HARNESS_WORKTREE_ROOT to the
# worktree abs path so we rsync the right tree instead of silently shipping stale main.
if [[ -n "${Z_HARNESS_WORKTREE_ROOT:-}" ]]; then
  LOCAL_ROOT="$Z_HARNESS_WORKTREE_ROOT"
  if [[ ! -d "$LOCAL_ROOT" ]]; then
    echo "remote-sandbox-sync.sh: Z_HARNESS_WORKTREE_ROOT='$LOCAL_ROOT' is not a directory" >&2
    exit 2
  fi
else
  LOCAL_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
# Surface the resolved root so a wrong-tree sync is visible in logs, not silent.
echo "remote-sandbox-sync.sh: syncing local root: $LOCAL_ROOT" >&2
PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}}"

EXCLUDE_FILE=""
if [[ -f "$LOCAL_ROOT/.z-harness-rsync-exclude" ]]; then
  EXCLUDE_FILE="$LOCAL_ROOT/.z-harness-rsync-exclude"
elif [[ -f "$PLUGIN_ROOT/.z-harness-rsync-exclude" ]]; then
  EXCLUDE_FILE="$PLUGIN_ROOT/.z-harness-rsync-exclude"
else
  if [[ "$ALLOW_NO_EXCLUDE" -ne 1 ]]; then
    echo "remote-sandbox-sync.sh: no .z-harness-rsync-exclude found; refusing to rsync without explicit --allow-no-exclude" >&2
    exit 2
  fi
  echo "warning: no .z-harness-rsync-exclude found; --allow-no-exclude set, rsync will ship everything" >&2
fi

# Resolve the remote home directory once to build absolute paths.
# Tilde expansion is unreliable inside --link-dest on the remote side.
REMOTE_HOME="$(ssh "$REMOTE_HOST" 'printf %s "$HOME"')"
# All slug trees nest under <container>/sandbox/ (see layout note in header).
# Changing this one line cascades to base/overlay/lock/marker paths below.
REMOTE_SANDBOX_ROOT="$REMOTE_HOME/dev/qt-bot-sandbox/sandbox"
REMOTE_BASE_ABS="$REMOTE_SANDBOX_ROOT/$SLUG/base"
REMOTE_TASK_ABS="$REMOTE_SANDBOX_ROOT/$SLUG/$TASK_ID"
REMOTE_LOCK_DIR="$REMOTE_SANDBOX_ROOT/$SLUG/.base.lock"
REMOTE_READY_MARKER="$REMOTE_BASE_ABS/.base-ready"

# Ensure per-task remote dir exists (safe; single-quoted SLUG/TASK_ID are validated above).
ssh "$REMOTE_HOST" "mkdir -p -- '$REMOTE_TASK_ABS'" >/dev/null

RSYNC_ARGS_BASE=(
  -az
  --info=stats2
  --delete
)
if [[ -n "$EXCLUDE_FILE" ]]; then
  RSYNC_ARGS_BASE+=(--exclude-from="$EXCLUDE_FILE")
fi

RSYNC_ARGS_TASK=(
  -az
  --info=stats2
  --partial
  $DELETE_FLAG
)
if [[ -n "$EXCLUDE_FILE" ]]; then
  RSYNC_ARGS_TASK+=(--exclude-from="$EXCLUDE_FILE")
fi

# ---------------------------------------------------------------------------
# Shared-base seeding with atomic remote locking.
#
# Protocol:
#   1. Check for .base-ready marker. If present, base is usable — skip seed.
#   2. Attempt to acquire lock via `mkdir` (atomic on most filesystems).
#      - Winner: seed base, write marker, release lock.
#      - Losers: poll for .base-ready up to 600 s, then abort.
# ---------------------------------------------------------------------------
seed_base() {
  # Acquire lock atomically.
  if ssh "$REMOTE_HOST" "mkdir -- '$REMOTE_LOCK_DIR'" 2>/dev/null; then
    # We are the winner — seed the base.
    echo "remote-sandbox-sync: seeding shared base at $REMOTE_HOST:$REMOTE_BASE_ABS" >&2

    # Ensure base dir exists inside the lock.
    ssh "$REMOTE_HOST" "mkdir -p -- '$REMOTE_BASE_ABS'" >/dev/null

    if rsync "${RSYNC_ARGS_BASE[@]}" "$LOCAL_ROOT/" "$REMOTE_HOST:$REMOTE_BASE_ABS/"; then
      # Write readiness marker containing local HEAD sha.
      LOCAL_SHA="$(git -C "$LOCAL_ROOT" rev-parse HEAD 2>/dev/null || echo 'unknown')"
      ssh "$REMOTE_HOST" "printf '%s\n' '$LOCAL_SHA' > '$REMOTE_READY_MARKER'"
    else
      # Seed failed — clean up partial state before releasing lock.
      ssh "$REMOTE_HOST" "rm -rf -- '$REMOTE_BASE_ABS'" 2>/dev/null || true
      ssh "$REMOTE_HOST" "rmdir -- '$REMOTE_LOCK_DIR'" 2>/dev/null || true
      echo "remote-sandbox-sync: seed rsync failed; base not populated" >&2
      exit 1
    fi

    # Release lock.
    ssh "$REMOTE_HOST" "rmdir -- '$REMOTE_LOCK_DIR'" >/dev/null
  else
    # We are a loser — wait for the winner to finish (poll up to 600 s).
    echo "remote-sandbox-sync: waiting for another invocation to finish seeding base..." >&2
    local elapsed=0
    while ! ssh "$REMOTE_HOST" "[ -f '$REMOTE_READY_MARKER' ]" 2>/dev/null; do
      if [[ $elapsed -ge 600 ]]; then
        echo "remote-sandbox-sync: timed out (600s) waiting for base-ready marker at $REMOTE_HOST:$REMOTE_READY_MARKER" >&2
        exit 1
      fi
      sleep 5
      elapsed=$(( elapsed + 5 ))
    done
    echo "remote-sandbox-sync: base is ready (waited ${elapsed}s)" >&2
  fi
}

# Check if base is already seeded; if not, seed it.
if ! ssh "$REMOTE_HOST" "[ -f '$REMOTE_READY_MARKER' ]" 2>/dev/null; then
  seed_base
fi

# ---------------------------------------------------------------------------
# Per-task overlay rsync using --link-dest for hard-linked unchanged files.
# ---------------------------------------------------------------------------
# Trailing slash on source means "contents of dir", not the dir itself.
rsync "${RSYNC_ARGS_TASK[@]}" \
  --link-dest="$REMOTE_BASE_ABS" \
  "$LOCAL_ROOT/" "$REMOTE_HOST:$REMOTE_TASK_ABS/"
