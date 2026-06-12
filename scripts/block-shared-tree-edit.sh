#!/usr/bin/env bash
# block-shared-tree-edit.sh — PreToolUse hook for Edit | Write | MultiEdit |
# NotebookEdit. Concurrency-aware worktree-isolation guard.
#
# Purpose: stop two Claude sessions from editing the SAME git working tree at
# once. On 2026-06-12 two sessions ran in the primary z-harness checkout on
# `main` simultaneously; one committed under the other, `main` diverged, and a
# merge nearly clobbered the other session's uncommitted work. This hook makes
# that impossible: the first session to edit a tree owns it; a second concurrent
# session is blocked until it moves to its own worktree.
#
# Decision:
#   ALLOW : exit 0. Solo editing of ANY tree (including primary/main) is fine.
#   BLOCK : exit 2, reason on STDERR, when a different LIVE session owns this
#           working tree.
#
# Mechanism (lockless, mirrors the active-plan-registry philosophy): each
# session keeps a marker under the worktree's OWN per-tree git dir
# (`git rev-parse --absolute-git-dir`/z-harness-active-editors/<session_id>).
# That dir is distinct per worktree (`.git` for the primary checkout,
# `.git/worktrees/<n>` for a linked worktree), so sessions in DIFFERENT
# worktrees never see each other. The marker's CONTENT is a stable claim epoch
# (written once); its MTIME is a heartbeat (refreshed every edit). Owner = the
# live marker with the earliest claim epoch (tie-break: smallest session id).
# Markers idle longer than TTL are pruned, so a crashed/parked session releases
# its claim automatically.
#
# Fail-open: any malformed payload, missing tool, or git error ALLOWS the edit.
# A guardrail must never wedge all editing on its own bug.
#
# Override: export Z_HARNESS_ALLOW_SHARED_TREE=1 to bypass (intentional solo
# work on a shared tree). Tune idle expiry via Z_HARNESS_EDIT_CLAIM_TTL (secs).
set -u

TTL="${Z_HARNESS_EDIT_CLAIM_TTL:-1200}"   # idle-claim expiry, default 20 min

PAYLOAD="$(cat 2>/dev/null || true)"
[ -n "$PAYLOAD" ] || exit 0                # empty stdin -> allow

# --- parse session_id, edited path, cwd (jq preferred, python3 fallback) ---
parse() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$PAYLOAD" | jq -r \
      '[(.session_id // ""), (.tool_input.file_path // .tool_input.notebook_path // ""), (.cwd // "")] | @tsv' \
      2>/dev/null && return 0
  fi
  printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    o = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
ti = o.get("tool_input") or {}
p = ti.get("file_path") or ti.get("notebook_path") or ""
print("\t".join([o.get("session_id") or "", p, o.get("cwd") or ""]))
' 2>/dev/null
}
FIELDS="$(parse)" || exit 0
SESSION="$(printf '%s' "$FIELDS" | cut -f1)"
FILEPATH="$(printf '%s' "$FIELDS" | cut -f2)"
CWD="$(printf '%s' "$FIELDS" | cut -f3)"

[ -n "$FILEPATH" ] || exit 0               # no target -> nothing to guard
[ -n "$SESSION" ] || exit 0                # no session id -> can't attribute
[ "${Z_HARNESS_ALLOW_SHARED_TREE:-0}" = "1" ] && exit 0

# --- resolve the worktree's per-tree git dir from the edited file's location ---
DIR="$(dirname -- "$FILEPATH" 2>/dev/null || echo "")"
[ -d "$DIR" ] || DIR="$CWD"
[ -d "$DIR" ] || exit 0
GITDIR="$(git -C "$DIR" rev-parse --absolute-git-dir 2>/dev/null)" || exit 0   # not a repo -> allow
[ -n "$GITDIR" ] || exit 0

MARKDIR="$GITDIR/z-harness-active-editors"
mkdir -p "$MARKDIR" 2>/dev/null || exit 0
NOW="$(date +%s 2>/dev/null)" || exit 0

mtime_of() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }

# --- stamp/refresh OUR marker: claim epoch in content (once), mtime = heartbeat ---
MINE="$MARKDIR/$SESSION"
if [ ! -e "$MINE" ]; then
  printf '%s\n' "$NOW" > "$MINE" 2>/dev/null || exit 0
else
  touch "$MINE" 2>/dev/null || true        # heartbeat; preserve claim epoch
fi

# --- find the owner: earliest live claim epoch, tie-break by session id ---
OWNER=""; OWNER_CLAIM=""; OWNER_AGE=0
for m in "$MARKDIR"/*; do
  [ -e "$m" ] || continue
  age=$(( NOW - $(mtime_of "$m") ))
  if [ "$age" -gt "$TTL" ]; then
    rm -f -- "$m" 2>/dev/null               # idle -> release claim
    continue
  fi
  claim="$(head -n1 "$m" 2>/dev/null)"
  case "$claim" in (*[!0-9]*|'') claim="$(mtime_of "$m")";; esac   # fallback if content unusable
  base="$(basename -- "$m")"
  if [ -z "$OWNER" ] || [ "$claim" -lt "$OWNER_CLAIM" ] \
     || { [ "$claim" -eq "$OWNER_CLAIM" ] && [ "$base" \< "$OWNER" ]; }; then
    OWNER="$base"; OWNER_CLAIM="$claim"; OWNER_AGE="$age"
  fi
done

# --- owner edits freely; anyone else is blocked until they isolate ---
[ "$OWNER" = "$SESSION" ] && exit 0
[ -z "$OWNER" ] && exit 0                    # race: nothing live -> allow

WT="$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || echo "$DIR")"
{
  echo "BLOCKED: another Claude session is already editing this working tree."
  echo "  worktree : $WT"
  echo "  owned by : session $OWNER (heartbeat ${OWNER_AGE}s ago)"
  echo "  you      : session $SESSION"
  echo
  echo "Two sessions sharing one working tree is what diverged main on 2026-06-12."
  echo "Isolate into your own worktree, then relaunch this session there:"
  echo "    git worktree add ../$(basename "$WT")-<topic> -b <branch> origin/main"
  echo
  echo "Deliberate solo override: export Z_HARNESS_ALLOW_SHARED_TREE=1"
} >&2
exit 2
