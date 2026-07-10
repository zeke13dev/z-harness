#!/usr/bin/env bash
# worktree-cleanup.sh — shared, safe git-worktree classify/remove helper.
#
# Pure bash + git (no network calls). Classifies worktrees by TRUE merge
# status (patch-identity, catching squash merges and unpushed local
# branches) and only ever removes provably-safe ones. This is the reusable
# primitive other worktree-cleanup call sites build on.
#
# Usage:
#   worktree-cleanup.sh classify <repo-root>
#   worktree-cleanup.sh remove <path> [--force]
#   worktree-cleanup.sh after-merge <path> <branch>
#
# classify emits one JSON object per line (JSONL) per non-main worktree:
#   {"path":..., "branch":..., "detached":bool, "tracked_dirty":int,
#    "untracked":int, "merge_state":"merged"|"unmerged",
#    "bucket":"dead-pointer"|"safe-remove"|"merged-dirty"|"unmerged-work"}
#
# remove refuses (exit 1, nothing removed) when the worktree has
# uncommitted tracked changes OR unmerged commits, unless --force is given.
#
# after-merge is a thin post-merge wrapper: asserts merged, then delegates
# to remove. Best-effort — never fails a caller's merge if the worktree is
# already gone.

set -euo pipefail

# Internal field separator for the path/head/branch/detached tuples passed
# between _parse_worktree_list and its readers. A plain tab (or space)
# CANNOT be used here: when IFS consists solely of "IFS whitespace"
# characters (space/tab/newline), bash's `read` collapses consecutive
# delimiters instead of producing an empty field — silently misaligning
# columns whenever branch is empty (the detached-HEAD case). Unit separator
# (0x1F) is not in that whitespace class, so empty fields survive intact.
_WT_FS=$'\x1f'

usage() {
  cat >&2 <<'EOF'
Usage:
  worktree-cleanup.sh classify <repo-root>
  worktree-cleanup.sh remove <path> [--force]
  worktree-cleanup.sh after-merge <path> <branch>
EOF
  exit 2
}

# ---------------------------------------------------------------------------
# default_branch <repo>
# Resolves the repo's default branch: origin/HEAD symref, else local main,
# else master. Existence-checked so downstream rev-list calls have a real ref.
# ---------------------------------------------------------------------------
default_branch() {
  local repo="$1"
  local ref
  ref="$(git -C "$repo" symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null)" || ref=""
  if [[ -n "$ref" ]]; then
    printf '%s' "${ref#refs/remotes/origin/}"
    return 0
  fi
  if git -C "$repo" show-ref --verify --quiet refs/heads/main 2>/dev/null; then
    printf 'main'
    return 0
  fi
  printf 'master'
}

# ---------------------------------------------------------------------------
# _merge_state <repo> <default-branch> <head-sha>
# "merged" iff the commit is already contained in <default-branch> by patch
# identity: rev-list --cherry-pick --right-only --count == 0. Works offline
# against the LOCAL default branch (unpushed branches count), catches squash
# merges, and subsumes the literal-ancestor case (detached HEAD included).
# ---------------------------------------------------------------------------
_merge_state() {
  local repo="$1" default="$2" head_sha="$3"
  if [[ -z "$head_sha" ]]; then
    printf 'unmerged'
    return 0
  fi
  if ! git -C "$repo" rev-parse --quiet --verify "refs/heads/$default" >/dev/null 2>&1; then
    printf 'unmerged'
    return 0
  fi
  local count
  count="$(git -C "$repo" rev-list --cherry-pick --right-only --count "${default}...${head_sha}" 2>/dev/null)" || count=""
  if [[ "$count" == "0" ]]; then
    printf 'merged'
  else
    printf 'unmerged'
  fi
}

# ---------------------------------------------------------------------------
# _parse_worktree_list <repo>
# Emits one $_WT_FS-separated record per worktree (main worktree included,
# always first — git's own guarantee): <path><FS><head-sha><FS><branch><FS><detached 0|1>
# ---------------------------------------------------------------------------
_parse_worktree_list() {
  local repo="$1"
  local path="" head="" branch="" detached=0
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then
      if [[ -n "$path" ]]; then
        printf '%s%s%s%s%s%s%s\n' "$path" "$_WT_FS" "$head" "$_WT_FS" "$branch" "$_WT_FS" "$detached"
      fi
      path="" head="" branch="" detached=0
      continue
    fi
    case "$line" in
      worktree\ *) path="${line#worktree }" ;;
      HEAD\ *) head="${line#HEAD }" ;;
      branch\ *) branch="${line#branch refs/heads/}" ;;
      detached) detached=1 ;;
    esac
    # bare/locked/prunable lines are intentionally ignored — presence on disk
    # (checked separately) is what drives the dead-pointer bucket.
  done < <(git -C "$repo" worktree list --porcelain 2>/dev/null; printf '\n')
}

# _find_worktree_fields <repo> <abs-path> — echoes the matching record from
# _parse_worktree_list, or nothing if <abs-path> is not a registered worktree.
_find_worktree_fields() {
  local repo="$1" target="$2"
  # NOTE: awk deliberately drains to EOF (no early `exit`) rather than
  # stopping at the first match — an early awk exit would close its stdin
  # while _parse_worktree_list is still writing, killing it with SIGPIPE
  # (bash exit 141) and tripping `set -e` in the caller.
  _parse_worktree_list "$repo" | awk -F"$_WT_FS" -v t="$target" '$1 == t && !found { print; found=1 }'
}

# ---------------------------------------------------------------------------
# _json_record <path> <branch> <detached 0|1> <tracked_dirty> <untracked>
#              <merge_state> <bucket>
# Emits one JSON object line. JSON encoding is offloaded to python3 so
# paths/branch names with quotes or unicode are safely escaped; all git
# logic stays in bash above.
# ---------------------------------------------------------------------------
_json_record() {
  python3 - "$@" <<'PYEOF'
import json, sys
path, branch, detached, tracked_dirty, untracked, merge_state, bucket = sys.argv[1:8]
print(json.dumps({
    "path": path,
    "branch": branch,
    "detached": detached == "1",
    "tracked_dirty": int(tracked_dirty),
    "untracked": int(untracked),
    "merge_state": merge_state,
    "bucket": bucket,
}))
PYEOF
}

# _json_get <json-line> <key> — extracts a scalar field (bools print 0/1).
_json_get() {
  python3 - "$1" "$2" <<'PYEOF'
import json, sys
obj = json.loads(sys.argv[1])
val = obj.get(sys.argv[2], "")
print("1" if val is True else "0" if val is False else val)
PYEOF
}

# ---------------------------------------------------------------------------
# _classify_one <repo> <default-branch> <wt-path> <wt-head> <wt-branch> <wt-detached>
# Reuses the same logic for the full classify sweep and for a single-path
# lookup (remove / after-merge's safety gate).
# ---------------------------------------------------------------------------
_classify_one() {
  local repo="$1" default="$2" wt_path="$3" wt_head="$4" wt_branch="$5" wt_detached="$6"

  # merge_state is computable from the object database alone (head sha from
  # the porcelain listing), independent of whether the worktree dir exists —
  # so a dead pointer still gets a real merge_state, per "best-effort" fields.
  local merge_state
  merge_state="$(_merge_state "$repo" "$default" "$wt_head")"

  if [[ ! -d "$wt_path" ]]; then
    _json_record "$wt_path" "$wt_branch" "$wt_detached" "0" "0" "$merge_state" "dead-pointer"
    return 0
  fi

  local tracked_status tracked_dirty
  tracked_status="$(git -C "$wt_path" status --porcelain --untracked-files=no 2>/dev/null || true)"
  if [[ -z "$tracked_status" ]]; then
    tracked_dirty=0
  else
    tracked_dirty="$(printf '%s\n' "$tracked_status" | wc -l | tr -d ' ')"
  fi

  local full_status untracked
  full_status="$(git -C "$wt_path" status --porcelain 2>/dev/null || true)"
  untracked="$(printf '%s\n' "$full_status" | grep -c '^??' || true)"

  local bucket
  if [[ "$merge_state" == "merged" && "$tracked_dirty" -eq 0 ]]; then
    bucket="safe-remove"
  elif [[ "$merge_state" == "merged" ]]; then
    bucket="merged-dirty"
  else
    bucket="unmerged-work"
  fi

  _json_record "$wt_path" "$wt_branch" "$wt_detached" "$tracked_dirty" "$untracked" "$merge_state" "$bucket"
}

# ---------------------------------------------------------------------------
# _resolve_repo_root_from_worktree <wt-path>
# Common-dir owner (the main worktree root), per task spec: prefer
# git-common-dir, fall back to the first entry of `git worktree list`.
# ---------------------------------------------------------------------------
_resolve_repo_root_from_worktree() {
  local wt_path="$1"
  local common_dir
  common_dir="$(git -C "$wt_path" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || common_dir=""
  if [[ -n "$common_dir" ]]; then
    if [[ "$(basename "$common_dir")" == ".git" ]]; then
      dirname "$common_dir"
    else
      printf '%s' "$common_dir"
    fi
    return 0
  fi
  # awk drains to EOF rather than exiting early — see the note in
  # _find_worktree_fields for why an early exit here is unsafe (SIGPIPE).
  git -C "$wt_path" worktree list --porcelain 2>/dev/null | awk '/^worktree / && !found {print $2; found=1}'
}

# ---------------------------------------------------------------------------
# cmd_classify <repo-root>
# ---------------------------------------------------------------------------
cmd_classify() {
  local repo="${1:-}"
  [[ -n "$repo" ]] || usage
  [[ -d "$repo" ]] || { printf 'worktree-cleanup.sh classify: not a directory: %s\n' "$repo" >&2; exit 1; }
  repo="$(cd "$repo" && pwd -P)"
  git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || {
    printf 'worktree-cleanup.sh classify: not a git repo: %s\n' "$repo" >&2
    exit 1
  }

  local default
  default="$(default_branch "$repo")"

  local idx=0
  while IFS="$_WT_FS" read -r wt_path wt_head wt_branch wt_detached; do
    idx=$((idx + 1))
    [[ "$idx" -eq 1 ]] && continue # main worktree — always first, per git
    _classify_one "$repo" "$default" "$wt_path" "$wt_head" "$wt_branch" "$wt_detached"
  done < <(_parse_worktree_list "$repo")
}

# ---------------------------------------------------------------------------
# cmd_remove <path> [--force]
# ---------------------------------------------------------------------------
cmd_remove() {
  local wt_path="${1:-}"
  shift || true
  local force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) force=1; shift ;;
      *) printf 'worktree-cleanup.sh remove: unknown option: %s\n' "$1" >&2; usage ;;
    esac
  done
  [[ -n "$wt_path" ]] || usage
  [[ -d "$wt_path" ]] || {
    printf 'worktree-cleanup.sh remove: path does not exist on disk: %s (use "git worktree prune" from the repo instead)\n' "$wt_path" >&2
    exit 1
  }
  local abs_wt_path
  abs_wt_path="$(cd "$wt_path" && pwd -P)"

  local repo
  repo="$(_resolve_repo_root_from_worktree "$abs_wt_path")"
  [[ -n "$repo" ]] || {
    printf 'worktree-cleanup.sh remove: could not resolve repo root for %s\n' "$abs_wt_path" >&2
    exit 1
  }

  local main_wt
  main_wt="$(git -C "$repo" worktree list --porcelain 2>/dev/null | awk '/^worktree / && !found {print $2; found=1}')"
  if [[ -n "$main_wt" && "$abs_wt_path" == "$main_wt" ]]; then
    printf 'worktree-cleanup.sh remove: refusing to remove the main worktree: %s\n' "$abs_wt_path" >&2
    exit 1
  fi

  local default
  default="$(default_branch "$repo")"

  local fields
  fields="$(_find_worktree_fields "$repo" "$abs_wt_path")"
  [[ -n "$fields" ]] || {
    printf 'worktree-cleanup.sh remove: %s is not a registered worktree of %s\n' "$abs_wt_path" "$repo" >&2
    exit 1
  }
  local f_path f_head f_branch f_detached
  IFS="$_WT_FS" read -r f_path f_head f_branch f_detached <<<"$fields"

  # Safety gate: reuse the classify logic on just this one path.
  local record tracked_dirty merge_state branch
  record="$(_classify_one "$repo" "$default" "$f_path" "$f_head" "$f_branch" "$f_detached")"
  tracked_dirty="$(_json_get "$record" tracked_dirty)"
  merge_state="$(_json_get "$record" merge_state)"
  branch="$(_json_get "$record" branch)"

  if [[ "$force" -ne 1 ]]; then
    if [[ "$tracked_dirty" -gt 0 || "$merge_state" != "merged" ]]; then
      printf 'worktree-cleanup.sh remove: refusing to remove %s (tracked_dirty=%s merge_state=%s) — use --force to override\n' \
        "$abs_wt_path" "$tracked_dirty" "$merge_state" >&2
      exit 1
    fi
  fi

  if [[ "$force" -eq 1 ]]; then
    git -C "$repo" worktree remove --force "$abs_wt_path"
  else
    git -C "$repo" worktree remove "$abs_wt_path"
  fi
  printf 'removed worktree: %s\n' "$abs_wt_path"

  if [[ -n "$branch" ]]; then
    if [[ "$merge_state" == "merged" ]]; then
      if git -C "$repo" branch -d "$branch" 2>/dev/null; then
        printf 'deleted branch: %s\n' "$branch"
      else
        # git's own `-d` ancestry check can refuse a branch we have already
        # proven merged via patch-identity: a squash-merge commit is not a
        # literal descendant of the branch tip, so `-d` fails even though the
        # patch content is identical. Our merge_state check is a stronger,
        # patch-identity-based safety proof than git's own ancestry check, so
        # force-delete here rather than leave the branch stranded.
        git -C "$repo" branch -D "$branch"
        printf 'force-deleted branch (patch-identity proven merged): %s\n' "$branch"
      fi
    elif [[ "$force" -eq 1 ]]; then
      git -C "$repo" branch -D "$branch"
      printf 'force-deleted branch: %s\n' "$branch"
    fi
  fi

  git -C "$repo" worktree prune
  printf 'pruned worktree pointers\n'
}

# ---------------------------------------------------------------------------
# cmd_after_merge <path> <branch>
# Thin post-merge wrapper. Best-effort: never fails a caller's merge if the
# worktree is already gone.
# ---------------------------------------------------------------------------
cmd_after_merge() {
  local wt_path="${1:-}" branch="${2:-}"
  [[ -n "$wt_path" && -n "$branch" ]] || usage

  if [[ ! -d "$wt_path" ]]; then
    printf 'worktree-cleanup.sh after-merge: worktree already gone, nothing to do: %s\n' "$wt_path" >&2
    exit 0
  fi

  local repo
  repo="$(_resolve_repo_root_from_worktree "$wt_path")"
  if [[ -z "$repo" ]]; then
    printf 'worktree-cleanup.sh after-merge: warning: could not resolve repo root for %s — skipping\n' "$wt_path" >&2
    exit 0
  fi

  local abs_wt_path
  abs_wt_path="$(cd "$wt_path" && pwd -P)"

  local default
  default="$(default_branch "$repo")"

  local fields
  fields="$(_find_worktree_fields "$repo" "$abs_wt_path")"
  if [[ -z "$fields" ]]; then
    printf 'worktree-cleanup.sh after-merge: warning: %s is not a registered worktree — skipping\n' "$abs_wt_path" >&2
    exit 0
  fi
  local f_path f_head f_branch f_detached
  IFS="$_WT_FS" read -r f_path f_head f_branch f_detached <<<"$fields"

  local merge_state
  merge_state="$(_merge_state "$repo" "$default" "$f_head")"
  if [[ "$merge_state" != "merged" ]]; then
    printf 'worktree-cleanup.sh after-merge: refusing — %s (branch %s) is not proven merged into %s\n' \
      "$abs_wt_path" "$branch" "$default" >&2
    exit 1
  fi

  cmd_remove "$abs_wt_path"
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
[[ $# -ge 1 ]] || usage
SUBCOMMAND="$1"
shift

case "$SUBCOMMAND" in
  classify)    cmd_classify "$@" ;;
  remove)      cmd_remove "$@" ;;
  after-merge) cmd_after_merge "$@" ;;
  *)
    printf 'worktree-cleanup.sh: unknown subcommand: %s\n' "$SUBCOMMAND" >&2
    usage
    ;;
esac
