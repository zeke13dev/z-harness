#!/usr/bin/env bash
# block-shared-tree-edit.sh — PreToolUse hook for Edit | Write | MultiEdit |
# NotebookEdit | Bash. Concurrency-aware worktree-isolation guard.
#
# Bash coverage (added 2026-06-20): an implementer that hit the Edit block once
# routed around it with `python3 -c "open(path,'w')"` — a Bash file-write the
# hook never saw. We now also scan Bash commands for writer patterns
# (> / >> / tee / sed -i / cp / mv / python open(...,'w'|'a'|'x')) whose target
# resolves into a guarded tree, and apply the SAME ownership check. Fail-open:
# any command we cannot confidently parse as a write into a contended tree is
# allowed, so normal Bash usage is never wedged.
#
# Purpose: stop two agent sessions from editing the SAME git working tree at
# once. On 2026-06-12 two sessions ran in the primary z-harness checkout on
# `main` simultaneously; one committed under the other, `main` diverged, and a
# merge nearly clobbered the other session's uncommitted work. This hook makes
# that impossible: the first session to edit a tree owns it; a second concurrent
# session is blocked until it moves to its own worktree. The block message is
# entrypoint-agnostic: use the host's in-place worktree switch when available
# (Claude Code: EnterWorktree; OMP/pi: move the current session cwd), otherwise
# relaunch/root a new session in a linked worktree.
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

# --- parse session_id, tool_name, edited path, bash command, cwd ---
parse() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$PAYLOAD" | jq -r \
      '[(.session_id // ""), (.tool_name // ""), (.tool_input.file_path // .tool_input.notebook_path // ""), (.tool_input.command // ""), (.cwd // "")] | @tsv' \
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
cmd = ti.get("command") or ""
# tabs/newlines in the command would corrupt the TSV; strip to single-line.
cmd = cmd.replace("\t", " ").replace("\n", " ")
print("\t".join([o.get("session_id") or "", o.get("tool_name") or "", p, cmd, o.get("cwd") or ""]))
' 2>/dev/null
}
FIELDS="$(parse)" || exit 0
SESSION="$(printf '%s' "$FIELDS" | cut -f1)"
TOOL="$(printf '%s' "$FIELDS" | cut -f2)"
FILEPATH="$(printf '%s' "$FIELDS" | cut -f3)"
COMMAND="$(printf '%s' "$FIELDS" | cut -f4)"
CWD="$(printf '%s' "$FIELDS" | cut -f5)"

[ -n "$SESSION" ] || exit 0                # no session id -> can't attribute
[ "${Z_HARNESS_ALLOW_SHARED_TREE:-0}" = "1" ] && exit 0

# --- build the list of write-target paths to guard ---------------------------
# Edit family: exactly the one file_path. Bash: heuristically-extracted write
# targets from the command (fail-open — emit nothing we cannot parse).
CANDIDATES=""
if [ -n "$FILEPATH" ]; then
  CANDIDATES="$FILEPATH"
elif [ "$TOOL" = "Bash" ] && [ -n "$COMMAND" ]; then
  CANDIDATES="$(printf '%s' "$COMMAND" | python3 -c '
import os, re, sys
cmd = sys.stdin.read()
out = []
def add(p):
    p = p.strip().strip("\x27\x22")
    # ignore obvious non-file targets and process substitutions / fds
    if not p or p.startswith("&") or p.startswith("/dev/") or p == "-":
        return
    out.append(p)
def pathlike(p):
    # A real write target looks like a filename, not a bare identifier from a
    # comparison (1>2, a>b) or a quoted ">". Require a path separator, a dotted
    # basename, a ~/ home ref, or an already-existing path.
    p = p.strip().strip("\x27\x22")
    if not p:
        return False
    base = os.path.basename(p)
    return ("/" in p) or p.startswith("~") or ("." in base) or os.path.exists(p)
# redirects:  > file   >> file   (not >&2 etc — those start with & after >).
# Bare `>` is highly ambiguous (comparison operators, quoted text, awk/python),
# so only treat the target as a write when it actually looks like a file path.
for m in re.finditer(r">>?\s*([^\s|;&>()]+)", cmd):
    if pathlike(m.group(1)):
        add(m.group(1))
# tee [-a] file ...
for m in re.finditer(r"\btee\b(?:\s+-\S+)*\s+([^\s|;&>()]+)", cmd):
    add(m.group(1))
# sed -i ... file  (last whitespace-delimited token is the file in common usage)
for m in re.finditer(r"\bsed\b[^|;&]*\s-\S*i\S*[^|;&]*?\s([^\s|;&>()]+)\s*(?:$|[|;&])", cmd):
    add(m.group(1))
# cp/mv SRC DST -> DST is the write target (last token before a delimiter)
for m in re.finditer(r"\b(?:cp|mv)\b[^|;&]*\s([^\s|;&>()]+)\s*(?:$|[|;&])", cmd):
    add(m.group(1))
# python open(PATH, MODE) where MODE contains a write flag (w/a/x/+)
for m in re.finditer(r"open\(\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]\s*,\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]", cmd):
    if re.search(r"[wax+]", m.group(2)):
        add(m.group(1))
# de-dup, preserve order
seen = set(); uniq = []
for p in out:
    if p not in seen:
        seen.add(p); uniq.append(p)
print("\n".join(uniq))
' 2>/dev/null)"
fi

[ -n "$CANDIDATES" ] || exit 0             # nothing to guard -> allow

NOW="$(date +%s 2>/dev/null)" || exit 0
mtime_of() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }

# --- guard one path: stamp our marker in its tree, block if a peer owns it ----
# Echoes "BLOCK <worktree> <owner> <owner_age>" to stdout and returns 2 when a
# different live session owns the tree; returns 0 (allow) otherwise. Fail-open.
guard_path() {
  gp_path="$1"
  gp_dir="$(dirname -- "$gp_path" 2>/dev/null || echo "")"
  # resolve the path relative to the tool's CWD when it is not absolute
  case "$gp_path" in
    /*) : ;;
    *)  [ -d "$gp_dir" ] || gp_dir="$CWD/$gp_dir" ;;
  esac
  [ -d "$gp_dir" ] || gp_dir="$CWD"
  [ -d "$gp_dir" ] || return 0
  gp_gitdir="$(git -C "$gp_dir" rev-parse --absolute-git-dir 2>/dev/null)" || return 0
  [ -n "$gp_gitdir" ] || return 0

  gp_markdir="$gp_gitdir/z-harness-active-editors"
  mkdir -p "$gp_markdir" 2>/dev/null || return 0

  gp_mine="$gp_markdir/$SESSION"
  if [ ! -e "$gp_mine" ]; then
    printf '%s\n' "$NOW" > "$gp_mine" 2>/dev/null || return 0
  else
    touch "$gp_mine" 2>/dev/null || true
  fi

  gp_owner=""; gp_claim=""; gp_age=0
  for m in "$gp_markdir"/*; do
    [ -e "$m" ] || continue
    age=$(( NOW - $(mtime_of "$m") ))
    if [ "$age" -gt "$TTL" ]; then rm -f -- "$m" 2>/dev/null; continue; fi
    claim="$(head -n1 "$m" 2>/dev/null)"
    case "$claim" in (*[!0-9]*|'') claim="$(mtime_of "$m")";; esac
    base="$(basename -- "$m")"
    if [ -z "$gp_owner" ] || [ "$claim" -lt "$gp_claim" ] \
       || { [ "$claim" -eq "$gp_claim" ] && [ "$base" \< "$gp_owner" ]; }; then
      gp_owner="$base"; gp_claim="$claim"; gp_age="$age"
    fi
  done

  [ "$gp_owner" = "$SESSION" ] && return 0
  [ -z "$gp_owner" ] && return 0
  gp_wt="$(git -C "$gp_dir" rev-parse --show-toplevel 2>/dev/null || echo "$gp_dir")"
  printf 'BLOCK\t%s\t%s\t%s\n' "$gp_wt" "$gp_owner" "$gp_age"
  return 2
}

# --- check every candidate; block on the first one a live peer owns ----------
while IFS= read -r cand; do
  [ -n "$cand" ] || continue
  RESULT="$(guard_path "$cand")"; RC=$?
  if [ "$RC" -eq 2 ]; then
    WT="$(printf '%s' "$RESULT" | cut -f2)"
    OWNER="$(printf '%s' "$RESULT" | cut -f3)"
    OWNER_AGE="$(printf '%s' "$RESULT" | cut -f4)"
    {
      echo "BLOCKED: another agent session is already editing this working tree."
      echo "  worktree : $WT"
      echo "  target   : $cand"
      echo "  owned by : session $OWNER (heartbeat ${OWNER_AGE}s ago)"
      echo "  you      : session $SESSION"
      echo
      echo "Two sessions sharing one working tree is what diverged main on 2026-06-12."
      [ "$TOOL" = "Bash" ] && echo "(This was a Bash file-write — do NOT route around the guard; isolate instead.)"
      echo "Isolate into your own linked worktree. Prefer an in-place switch for THIS"
      echo "session when your host supports it; no fresh session is needed in that case:"
      echo "  - Claude Code: EnterWorktree(name: \"<topic>\") or EnterWorktree(path: \"<existing-worktree>\")"
      echo "  - OMP/pi or any cwd-aware host: create/select a linked worktree, then move"
      echo "    this session's cwd there before retrying the edit"
      echo "  - Other hosts: start/relaunch the agent rooted in a linked worktree"
      echo "A linked worktree has its own per-tree marker dir, so this guard won't fire there."
      echo "If you need to create one manually:"
      echo "    git worktree add ../$(basename "$WT")-<topic> -b <branch> origin/main"
      echo
      echo "Deliberate solo override: export Z_HARNESS_ALLOW_SHARED_TREE=1"
    } >&2
    exit 2
  fi
done <<EOF
$CANDIDATES
EOF
exit 0
