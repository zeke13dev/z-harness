#!/usr/bin/env bash
# block-dangerous-git.sh — Claude Code PreToolUse hook that blocks dangerous
# git commands (history rewrites that would clobber upstream, and blanket
# working-tree-destructive operations).
#
# Usage: block-dangerous-git.sh
#   Reads a Claude Code PreToolUse hook JSON payload on STDIN. No positional
#   arguments are accepted. Install it as a PreToolUse hook with matcher "Bash"
#   (see commands/z-git-guardrails.md).
#
# Stdin contract (Claude Code PreToolUse):
#   {"tool_name": "Bash", "tool_input": {"command": "git push --force ..."}}
#   Only "Bash" tool calls are inspected; any other tool_name passes through.
#
# Stdout/exit contract (block via exit-code-2 + stderr, audit R7 — the simplest,
# most stable PreToolUse block path across Claude Code versions):
#   - ALLOW : exit 0, no output.
#   - BLOCK : exit 2, human-readable reason written to STDERR.
#   The JSON-stdout permissionDecision:"deny" form is an acceptable alternative
#   but exit-2+stderr is preferred per SPEC F4.
#
# Classification (semi-smart):
#   - History-rewrite verbs (reset --hard, commit --amend, push --force,
#     push --force-with-lease, push with a +-prefixed refspec): resolve the
#     relevant ref and run
#     `git branch -r --contains <sha>`. BLOCK iff upstream-reachable. If the
#     check errors (detached HEAD, no remote, git error) → BLOCK (fail-closed).
#   - Working-tree-destructive verbs (clean -f/-fd/-fdx, checkout ., restore .,
#     branch -D): blanket-BLOCK.
#   - Everything else (including all non-git commands): ALLOW instantly. Only
#     rewrite verbs shell out to git; the rest is string matching.
#
# Override (one-shot escape hatch): Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1 → ALLOW
#   the command AND append an audit entry to the guardrails audit log under the
#   resolved z-harness base dir (<base>/git-guardrails-audit.log).
#
# Example:
#   echo '{"tool_name":"Bash","tool_input":{"command":"git push --force"}}' \
#     | block-dangerous-git.sh   # exit 2 if HEAD is upstream-reachable

set -euo pipefail

# --- arg validation ---
# This hook takes no positional arguments; the payload arrives on stdin.
if [[ $# -gt 0 ]]; then
  echo "usage: block-dangerous-git.sh   (reads PreToolUse hook JSON on stdin)" >&2
  exit 2
fi

# --- constants ---
REWRITE_MSG="Upstream reachable — recover via inspect+merge, not force-push (see git-rewrite-check-upstream)."
DESTRUCTIVE_MSG="Working-tree-destructive git command blocked. To override, re-run with Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1."
FAILCLOSED_MSG="Could not verify upstream reachability for this history-rewrite (detached HEAD, no remote, or git error). Blocked fail-closed; recover via inspect+merge or override with Z_HARNESS_GIT_GUARDRAILS_OVERRIDE=1."

# Block by writing the reason to stderr and exiting 2 (preferred PreToolUse path).
block() {
  printf '%s\n' "$1" >&2
  exit 2
}

# --- stdin payload parse (robust; never crash) ---
# Read the whole payload. Empty / non-JSON stdin must fail safe (allow), never
# raise. We only need tool_name and tool_input.command.
PAYLOAD="$(cat || true)"
if [[ -z "${PAYLOAD//[[:space:]]/}" ]]; then
  # Empty stdin — nothing to inspect; allow.
  exit 0
fi

# Extract fields with jq (repo-preferred); fall back cleanly if the payload is
# not valid JSON. jq's // "" yields an empty string for missing keys.
TOOL_NAME=""
COMMAND=""
if command -v jq >/dev/null 2>&1; then
  if PARSED="$(printf '%s' "$PAYLOAD" | jq -r '[(.tool_name // ""), (.tool_input.command // "")] | @tsv' 2>/dev/null)"; then
    TOOL_NAME="${PARSED%%$'\t'*}"
    COMMAND="${PARSED#*$'\t'}"
  else
    # Not valid JSON — fail safe (allow). Never crash on malformed stdin.
    exit 0
  fi
else
  # No jq: fall back to python3 (also repo-present). Same fail-safe semantics.
  if PARSED="$(printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    obj = json.loads(sys.stdin.read())
except (ValueError, TypeError):
    sys.exit(3)
tn = obj.get("tool_name", "") or ""
cmd = (obj.get("tool_input", {}) or {}).get("command", "") or ""
sys.stdout.write(tn + "\t" + cmd)
' 2>/dev/null)"; then
    TOOL_NAME="${PARSED%%$'\t'*}"
    COMMAND="${PARSED#*$'\t'}"
  else
    exit 0
  fi
fi

# --- gate on Bash + git ---
# Only Bash tool calls are inspected; only commands that mention git matter.
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi
if [[ "$COMMAND" != *git* ]]; then
  # Non-git commands pass through instantly (no git shell-out).
  exit 0
fi

# --- override escape hatch ---
# Append an audit entry and allow. Resolution of the base dir reuses
# plan-path.sh's z_harness_base() (DRY) so the audit log lands beside other
# z-harness state.
audit_override() {
  local base
  # shellcheck source=scripts/plan-path.sh
  if source "$(dirname "$0")/plan-path.sh" 2>/dev/null \
     && base="$(_Z_HARNESS_RESOLVING_BASE=1 z_harness_base 2>/dev/null)" \
     && [[ -n "$base" ]]; then
    mkdir -p "$base" 2>/dev/null || true
    local ts
    ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '%s\toverride\t%s\n' "$ts" "$COMMAND" >> "$base/git-guardrails-audit.log" 2>/dev/null || true
  fi
}

if [[ "${Z_HARNESS_GIT_GUARDRAILS_OVERRIDE:-}" == "1" ]]; then
  audit_override
  exit 0
fi

# --- normalization: extract canonical "git <subcommand> <rest>" forms ---
# git's global options can appear between `git` and the subcommand
# (e.g. `git -C /tmp reset --hard`), and the whole invocation may be preceded
# by an env-var assignment prefix (`GIT_DIR=x git ...`) or buried inside a
# command chain (`cd /tmp && git reset --hard`). Substring matching on the raw
# string is therefore unsound: an attacker (or a careless agent) evades the hook
# simply by inserting `-C <path>` after `git`. We defend by tokenizing each
# chained segment, dropping git's leading global options, and re-emitting a
# canonical `git <subcommand> <remaining args>` string. The existing verb
# matchers then run against these canonical forms.

# Global options that take a SEPARATE value argument (the next token is consumed).
# e.g. `-C <path>`, `-c <name=value>`, `--git-dir <path>`.
_git_global_opts_with_arg=" -C -c --git-dir --work-tree --exec-path --namespace --super-prefix --config-env "

# Split the raw command into segments on chaining/compounding operators so a
# dangerous verb anywhere in a chain is evaluated. Operators: && || | ; & and
# newlines. We translate each into a newline and read segments line by line.
# This is intentionally coarse (it does not parse quotes/subshells), which is
# safe for a *blocklist*: over-segmenting can only ever surface MORE git
# invocations to classify, never hide one.
_split_segments() {
  local cmd="$1"
  cmd="${cmd//&&/$'\n'}"
  cmd="${cmd//||/$'\n'}"
  cmd="${cmd//|/$'\n'}"
  cmd="${cmd//;/$'\n'}"
  cmd="${cmd//&/$'\n'}"
  # Trailing newline so `while read` processes the final segment even when the
  # raw command has no chaining operators (single-segment case).
  printf '%s\n' "$cmd"
}

# Given one segment, locate a `git` invocation and emit a canonical
# `git <subcommand> <rest...>` line with global options stripped. Emits nothing
# if the segment contains no git subcommand invocation. Robust to:
#   - a leading run of `VAR=value` env assignments before `git`
#   - git global options (value-taking and boolean) before the subcommand
#   - the `=`-attached forms (`--git-dir=/x`, `-c key=val` is value-taking)
_canonicalize_segment() {
  local seg="$1"
  # Tokenize on whitespace (read -a). Glob is disabled to avoid expansion.
  local -a toks=()
  # shellcheck disable=SC2206
  IFS=$' \t' read -r -a toks <<< "$seg"

  local i=0 n=${#toks[@]}
  # Skip a leading run of NAME=VALUE env-var assignments.
  while (( i < n )); do
    case "${toks[$i]}" in
      [A-Za-z_]*=*) i=$((i + 1)); continue ;;
      *) break ;;
    esac
  done

  # Require the next token to be exactly `git` (allow a path like /usr/bin/git).
  (( i < n )) || return 0
  case "${toks[$i]}" in
    git|*/git) ;;
    *) return 0 ;;
  esac
  i=$((i + 1))  # advance past `git`

  # Strip git global options until we reach the subcommand token.
  while (( i < n )); do
    local t="${toks[$i]}"
    case "$t" in
      # `--opt=value` attached forms — single token, drop it.
      --git-dir=*|--work-tree=*|--exec-path=*|--namespace=*|--super-prefix=*|--config-env=*)
        i=$((i + 1)); continue ;;
      # value-taking options where the value is a SEPARATE next token.
      -C|-c|--git-dir|--work-tree|--exec-path|--namespace|--super-prefix|--config-env)
        i=$((i + 2)); continue ;;
      # boolean / no-arg global options — drop the single token.
      -p|--paginate|-P|--no-pager|--bare|--no-replace-objects|--literal-pathspecs|--glob-pathspecs|--noglob-pathspecs|--icase-pathspecs|--no-optional-locks|--html-path|--man-path|--info-path|--version|--help|-h)
        i=$((i + 1)); continue ;;
      # any other leading `-`/`--` global flag we do not specifically model:
      # drop it conservatively so it cannot shield the subcommand. A flag of the
      # form `--foo=bar` is self-contained; a bare `--foo` we also drop. We do
      # NOT consume a following value for unknown flags (we cannot know the
      # arity), which at worst leaves a stray value token in `rest` — harmless.
      -*)
        i=$((i + 1)); continue ;;
      # first non-option token = the subcommand. Stop stripping.
      *)
        break ;;
    esac
  done

  (( i < n )) || return 0  # no subcommand present (e.g. bare `git -C x`)
  # Emit canonical: git <subcommand> <remaining tokens...>
  local out="git"
  while (( i < n )); do
    out+=" ${toks[$i]}"
    i=$((i + 1))
  done
  printf '%s\n' "$out"
}

# Produce all canonical git invocations found in the raw command (one per line).
_canonical_invocations() {
  local raw="$1" seg
  while IFS= read -r seg; do
    [[ -z "${seg//[[:space:]]/}" ]] && continue
    _canonicalize_segment "$seg"
  done < <(_split_segments "$raw")
}

# Compute the canonical forms once; all classification runs against them.
CANON="$(_canonical_invocations "$COMMAND")"

# --- working-tree-destructive verbs (blanket block) ---
# Matched against canonical `git <subcommand> ...` lines so leading global
# options (e.g. `git -C /tmp clean -fdx`) cannot evade detection. These never
# shell out to git.
is_destructive() {
  local cmd="$1"
  # git clean -f / -fd / -fdx (any -f* force flag)
  if [[ "$cmd" == "git clean "*"-f"* ]]; then
    return 0
  fi
  # git checkout .  /  git restore .  (discard all working-tree changes)
  if [[ "$cmd" == "git checkout ."* || "$cmd" == "git restore ."* ]]; then
    return 0
  fi
  # git branch -D  (force-delete a branch)
  if [[ "$cmd" == "git branch -D"* ]]; then
    return 0
  fi
  return 1
}

while IFS= read -r _inv; do
  [[ -z "$_inv" ]] && continue
  if is_destructive "$_inv"; then
    block "$DESTRUCTIVE_MSG"
  fi
done <<< "$CANON"

# --- history-rewrite verbs (smart: block iff upstream-reachable) ---
# Detect the rewrite verb, then resolve the ref the rewrite would move and ask
# whether any remote-tracking branch contains it. fail-closed on any git error.
# Matched against canonical `git <subcommand> ...` lines (global options already
# stripped) so `git -C /tmp reset --hard` is classified like `git reset --hard`.
# A `push` whose refspec begins with `+` is a force push for that ref
# (`git push origin +main`, `+src:dst`, `+refs/heads/x:...`), semantically
# equivalent to `--force` for that ref. We must treat it like the other
# force-push forms so it flows through the SAME upstream-reachability check.
# Anchor on a token that STARTS with `+` (a bare `+` or a `+` mid-token, e.g.
# inside a URL, must not false-positive). The cmd is a canonical
# `git push <args...>` line (global options already stripped).
_push_has_plus_refspec() {
  local cmd="$1"
  local -a toks=()
  # shellcheck disable=SC2206
  IFS=$' \t' read -r -a toks <<< "$cmd"
  # toks: 0=git 1=push 2..=args. Inspect non-option tokens after `push`.
  local i=2 n=${#toks[@]}
  while (( i < n )); do
    local t="${toks[$i]}"
    case "$t" in
      # Skip option flags (e.g. -u, --set-upstream, --repo=x). A lone `+` is not
      # a refspec; require at least one char after the leading `+`.
      -*) i=$((i + 1)); continue ;;
      +?*) return 0 ;;
      *) i=$((i + 1)); continue ;;
    esac
  done
  return 1
}

is_rewrite() {
  local cmd="$1"
  if [[ "$cmd" == "git reset --hard"* || "$cmd" == "git reset "*"--hard"* ]]; then return 0; fi
  if [[ "$cmd" == "git commit "*"--amend"* || "$cmd" == "git commit --amend"* ]]; then return 0; fi
  if [[ "$cmd" == "git push "*"--force-with-lease"* ]]; then return 0; fi
  if [[ "$cmd" == "git push "*"--force"* ]]; then return 0; fi
  if [[ "$cmd" == "git push "*" -f"* || "$cmd" == "git push -f"* ]]; then return 0; fi
  # `+`-refspec force push: git push <remote> +<ref>[:<dst>]
  if [[ "$cmd" == "git push "* ]] && _push_has_plus_refspec "$cmd"; then return 0; fi
  return 1
}

# Resolve the sha whose disappearance from history we care about. For amend and
# reset --hard the at-risk commit is the current HEAD; for a force-push it is
# likewise the local tip that would overwrite the remote. HEAD is a sound,
# simple proxy in all four cases (KISS). Fail-closed if HEAD cannot resolve.
resolve_target_sha() {
  git rev-parse --verify HEAD 2>/dev/null
}

# Does ANY canonical invocation match a rewrite verb?
_FOUND_REWRITE=0
while IFS= read -r _inv; do
  [[ -z "$_inv" ]] && continue
  if is_rewrite "$_inv"; then
    _FOUND_REWRITE=1
    break
  fi
done <<< "$CANON"

if [[ "$_FOUND_REWRITE" -eq 1 ]]; then
  SHA=""
  if ! SHA="$(resolve_target_sha)" || [[ -z "$SHA" ]]; then
    # Detached/unborn HEAD or git error → cannot verify → fail-closed.
    block "$FAILCLOSED_MSG"
  fi

  CONTAINS=""
  if ! CONTAINS="$(git branch -r --contains "$SHA" 2>/dev/null)"; then
    # git error (e.g. no remote configured) → cannot verify → fail-closed.
    block "$FAILCLOSED_MSG"
  fi

  if [[ -n "${CONTAINS//[[:space:]]/}" ]]; then
    # A remote-tracking branch contains this commit → upstream-reachable → block.
    block "$REWRITE_MSG"
  fi
  # Not upstream-reachable → the rewrite is local-only → allow.
  exit 0
fi

# --- default: allow ---
# git command that matched no dangerous verb.
exit 0
