#!/bin/bash

# z_harness_repo_id
# Returns a stable identifier for the repo: <basename>-<8hex>
# where 8hex = first 8 hex chars of the SHA-256 of the realpath of
# `git rev-parse --git-common-dir`.  Using git-common-dir means all
# worktrees of the same repo get the same id.
# Falls back to a sha of realpath($PWD) when not in a git repo.
z_harness_repo_id() {
  local common_dir
  common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || true
  local abs_path
  if [[ -n "$common_dir" ]]; then
    abs_path="$(realpath "$common_dir" 2>/dev/null || (cd "$common_dir" && pwd))"
    # Derive basename from the repo root (dirname of common-dir), not show-toplevel,
    # so all worktrees of one repo get the same basename.
    local repo_root
    repo_root="$(dirname "$abs_path")"
    local basename_top
    basename_top="$(basename "$repo_root")"
    local hex8
    # Portable hash: try sha256sum (Linux/CI) then fall back to shasum -a 256 (macOS).
    hex8="$( (printf '%s' "$abs_path" | sha256sum 2>/dev/null || printf '%s' "$abs_path" | shasum -a 256) | cut -c1-8)"
    if [[ -z "$hex8" ]]; then
      printf '[z-harness] FATAL: no sha256 utility (sha256sum/shasum) available — cannot compute a stable repo-id\n' >&2
      exit 1
    fi
    printf '%s-%s' "$basename_top" "$hex8"
  else
    abs_path="$(realpath "$PWD" 2>/dev/null || pwd)"
    local basename_top
    basename_top="$(basename "$abs_path")"
    local hex8
    # Portable hash: try sha256sum (Linux/CI) then fall back to shasum -a 256 (macOS).
    hex8="$( (printf '%s' "$abs_path" | sha256sum 2>/dev/null || printf '%s' "$abs_path" | shasum -a 256) | cut -c1-8)"
    if [[ -z "$hex8" ]]; then
      printf '[z-harness] FATAL: no sha256 utility (sha256sum/shasum) available — cannot compute a stable repo-id\n' >&2
      exit 1
    fi
    printf '%s-%s' "$basename_top" "$hex8"
  fi
}

# _z_harness_probe_writable <dir>
# Returns 0 if <dir> is (or can be created as) a writable directory.
# Returns 1 if not writable.
# Non-littering: if <dir> does not already exist, this function probes writability
# by creating the directory tree, touching a temp file, then removing all newly
# created components immediately (from leaf up to the first pre-existing ancestor).
# The caller is responsible for creating the directory again when the tier is
# actually selected; this function leaves the filesystem unchanged on probe.
_z_harness_probe_writable() {
  local dir="$1"
  if [[ -d "$dir" ]]; then
    # Already exists — check writability
    if [[ -w "$dir" ]]; then
      return 0
    else
      return 1
    fi
  fi
  # Dir does not exist — find the topmost component we will need to create,
  # so we can clean up exactly that subtree after probing.
  local create_root=""
  local candidate="$dir"
  while [[ -n "$candidate" && "$candidate" != "/" ]]; do
    local parent
    parent="$(dirname "$candidate")"
    if [[ -d "$parent" ]]; then
      create_root="$candidate"
      break
    fi
    candidate="$parent"
  done
  # Probe writability without leaving stray dirs.
  local probe_ok=1
  if mkdir -p "$dir" 2>/dev/null; then
    if touch "$dir/.z-harness-probe-$$" 2>/dev/null; then
      rm -f "$dir/.z-harness-probe-$$" 2>/dev/null || true
      probe_ok=0
    fi
    # Remove the subtree we created (from leaf up to create_root).
    if [[ -n "$create_root" ]]; then
      rm -rf "$create_root" 2>/dev/null || true
    else
      # Fallback: try just rmdir of the dir itself.
      rmdir "$dir" 2>/dev/null || true
    fi
  fi
  return $probe_ok
}

# _z_harness_anchor_path
# Echoes the path of the anchor file (<git-common-dir>/.z-harness-base).
# Falls back to empty string if not in a git repo.
_z_harness_anchor_path() {
  local common_dir
  common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || true
  if [[ -z "$common_dir" ]]; then
    printf ''
    return 0
  fi
  local abs_dir
  abs_dir="$(realpath "$common_dir" 2>/dev/null || (cd "$common_dir" && pwd))"
  printf '%s/.z-harness-base' "$abs_dir"
}

# _z_harness_anchor_write <tier> <path> <repo_id>
# Atomically writes the anchor file if absent (tmpfile+rename).
# Returns 0 on success (written or already existed with matching path).
# Returns 1 on mismatch (caller must hard-fail).
_z_harness_anchor_write() {
  local tier="$1"
  local resolved_path="$2"
  local repo_id="$3"

  local anchor_path
  anchor_path="$(_z_harness_anchor_path)"
  if [[ -z "$anchor_path" ]]; then
    # Not in a git repo — no anchor
    return 0
  fi

  if [[ -f "$anchor_path" ]]; then
    # Anchor exists — validate
    local stored_path
    stored_path="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("path",""))' "$anchor_path" 2>/dev/null || true)"
    if [[ -n "$stored_path" && "$stored_path" != "$resolved_path" ]]; then
      printf '[z-harness] plan-path.sh: base_mismatch_detected: anchor=%s resolved=%s\n' \
        "$stored_path" "$resolved_path" >&2
      return 1
    fi
    return 0
  fi

  # Anchor absent — write atomically
  local anchor_dir
  anchor_dir="$(dirname "$anchor_path")"
  local tmp
  tmp="$(mktemp "$anchor_dir/.z-harness-base.XXXXXX" 2>/dev/null)" || return 0
  python3 -c 'import json,sys; json.dump({"tier":sys.argv[1],"path":sys.argv[2],"repo_id":sys.argv[3]},open(sys.argv[4],"w"))' \
    "$tier" "$resolved_path" "$repo_id" "$tmp" 2>/dev/null || { rm -f "$tmp"; return 0; }
  mv -f "$tmp" "$anchor_path" 2>/dev/null || rm -f "$tmp"
  return 0
}

# z_harness_base
# Returns the artifact base directory for the current repo.
#
# Fallback chain (first writable tier wins):
#   1. $Z_HARNESS_BASE_DIR             — explicit absolute override
#   2. $XDG_STATE_HOME/z-harness/<repo-id>  — if Z_HARNESS_EXTERNAL_DEFAULT=1
#   3. $HOME/.local/state/z-harness/<repo-id>   — if Z_HARNESS_EXTERNAL_DEFAULT=1
#   4. <git-common-dir>/z-harness      — if Z_HARNESS_EXTERNAL_DEFAULT=1
#   5. $(pwd)/z-harness                — last resort / current behavior (always effective in stage 1)
#
# EXTERNAL_DEFAULT gating (stage 1):
#   When Z_HARNESS_EXTERNAL_DEFAULT is unset or 0, tiers 2-4 are computed for a
#   shadow diagnostic only. The effective base remains tier 1 (if set) or tier 5.
#   Set Z_HARNESS_EXTERNAL_DEFAULT=1 to activate the full fallback chain.
#
# Anchor invariant (SPEC invariant 7):
#   After resolving the path, writes/validates <git-common-dir>/.z-harness-base.
#   Mismatch → emits base_mismatch_detected to stderr + hard-fails.
#   Exception: tier-1 (Z_HARNESS_BASE_DIR explicitly set) validates against an
#   existing anchor but does NOT write one.  This prevents split-brain without
#   breaking hermetic test repos that have no pre-existing anchor.
#
# Source-loop guard:
#   log-event.sh sources plan-path.sh. To avoid recursion when z_harness_base()
#   would call log-event.sh, the base_resolved event is only emitted when
#   _Z_HARNESS_RESOLVING_BASE is NOT set. Callers (CLI wrapper) set this sentinel
#   before invoking log-event.sh so recursive calls no-op on event emission.
z_harness_base() {
  # --- Tier 1: explicit override ---
  # When Z_HARNESS_BASE_DIR is set, validate against any existing anchor but do NOT
  # write a new anchor. The anchor prevents split-brain in *automatic* tier selection
  # (tiers 2-5); an explicit override is already deterministic. We validate-but-don't-
  # write so that a pre-existing anchor from an automatic tier can still detect
  # conflict (split-brain hole: process A uses explicit BASE_DIR, process B auto-
  # resolved a different path and wrote the anchor → mismatch → hard-fail).
  local base_dir_env="${Z_HARNESS_BASE_DIR:-}"
  if [[ -n "$base_dir_env" ]]; then
    if [[ "$base_dir_env" != /* ]]; then
      printf '[z-harness] Z_HARNESS_BASE_DIR must be an absolute path, got: %s\n' "$base_dir_env" >&2
      exit 1
    fi
    # Validate against existing anchor (do NOT write one).
    local tier1_anchor
    tier1_anchor="$(_z_harness_anchor_path)"
    if [[ -n "$tier1_anchor" && -f "$tier1_anchor" ]]; then
      local stored_path
      stored_path="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("path",""))' "$tier1_anchor" 2>/dev/null || true)"
      if [[ -n "$stored_path" && "$stored_path" != "$base_dir_env" ]]; then
        printf '[z-harness] plan-path.sh: base_mismatch_detected: anchor=%s resolved=%s\n' \
          "$stored_path" "$base_dir_env" >&2
        printf '[z-harness] plan-path.sh: FATAL base_mismatch_detected — anchor and resolved base disagree. Aborting.\n' >&2
        exit 1
      fi
    fi
    # No anchor written for tier-1 (validate-but-don't-write).
    printf '%s' "$base_dir_env"
    return 0
  fi

  local repo_id
  repo_id="$(z_harness_repo_id)" || exit 1

  local external_default="${Z_HARNESS_EXTERNAL_DEFAULT:-0}"

  # --- Shadow diagnostics (tiers 2-4): computed regardless of gating, for diagnostics ---
  local shadow_tier="" shadow_path=""

  # Tier 2: XDG_STATE_HOME
  local xdg_state="${XDG_STATE_HOME:-}"
  if [[ -n "$xdg_state" ]]; then
    local t2_path="$xdg_state/z-harness/$repo_id"
    if _z_harness_probe_writable "$t2_path"; then
      shadow_tier="XDG_STATE_HOME"
      shadow_path="$t2_path"
    fi
  fi

  # Tier 3: ~/.local/state
  if [[ -z "$shadow_tier" && -n "${HOME:-}" ]]; then
    local t3_path="$HOME/.local/state/z-harness/$repo_id"
    if _z_harness_probe_writable "$t3_path"; then
      shadow_tier="HOME_local_state"
      shadow_path="$t3_path"
    fi
  fi

  # Tier 4: <git-common-dir>/z-harness
  if [[ -z "$shadow_tier" ]]; then
    local common_dir
    common_dir="$(git rev-parse --git-common-dir 2>/dev/null)" || true
    if [[ -n "$common_dir" ]]; then
      local abs_common
      abs_common="$(realpath "$common_dir" 2>/dev/null || (cd "$common_dir" && pwd))"
      local t4_path="$abs_common/z-harness"
      if _z_harness_probe_writable "$t4_path"; then
        shadow_tier="git_common_dir"
        shadow_path="$t4_path"
      fi
    fi
  fi

  # --- Tier 5: $(pwd)/z-harness (last resort) ---
  local t5_path
  t5_path="$(pwd)/z-harness"

  # --- Determine effective base ---
  local effective_path="" effective_tier=""

  if [[ "$external_default" == "1" ]]; then
    # Full fallback chain active
    if [[ -n "$shadow_tier" ]]; then
      effective_tier="$shadow_tier"
      effective_path="$shadow_path"
    elif _z_harness_probe_writable "$t5_path"; then
      effective_tier="pwd"
      effective_path="$t5_path"
    else
      printf 'plan-path.sh: FATAL no writable base found (tried XDG_STATE_HOME, HOME/.local/state, git-common-dir, pwd)\n' >&2
      exit 1
    fi
  else
    # Stage 1: only tier 1 (handled above) or tier 5 is effective
    if _z_harness_probe_writable "$t5_path"; then
      effective_tier="pwd"
      effective_path="$t5_path"
    else
      printf 'plan-path.sh: FATAL no writable base found (Z_HARNESS_EXTERNAL_DEFAULT not set, tried pwd)\n' >&2
      exit 1
    fi
  fi

  # --- Anchor write/validate ---
  if ! _z_harness_anchor_write "$effective_tier" "$effective_path" "$repo_id"; then
    printf '[z-harness] plan-path.sh: FATAL base_mismatch_detected — anchor and resolved base disagree. Aborting.\n' >&2
    exit 1
  fi

  _z_harness_emit_base_resolved "$effective_tier" "$effective_path" "$repo_id"
  printf '%s' "$effective_path"
  return 0
}

# _z_harness_emit_base_resolved <tier> <path> <repo_id>
# Emits the base_resolved event via the sentinel-guarded path.
# No-ops if _Z_HARNESS_RESOLVING_BASE is set (source-loop guard).
_z_harness_emit_base_resolved() {
  local tier="$1" path="$2" repo_id="$3"
  # Guard: if we are already inside a log-event.sh invocation that sourced us,
  # do not recurse by calling log-event.sh again.
  [[ "${_Z_HARNESS_RESOLVING_BASE:-}" == "1" ]] && return 0
  # Guard: only emit once per process (uses a tmp sentinel file keyed by PID).
  local stamp="${TMPDIR:-/tmp}/.zh-base-resolved-$$"
  [[ -f "$stamp" ]] && return 0
  touch "$stamp" 2>/dev/null || return 0
  # Attempt to emit via log-event.sh if available and we have a run id.
  # In practice this is only reachable from the CLI wrapper path, not from
  # sourced use, because the Z_HARNESS_RESOLVING_BASE sentinel guards sourced use.
  local log_event_sh
  log_event_sh="$(dirname "${BASH_SOURCE[0]}")/log-event.sh"
  if [[ -n "${Z_HARNESS_RUN_ID:-}" && -x "$log_event_sh" ]]; then
    export _Z_HARNESS_RESOLVING_BASE=1
    bash "$log_event_sh" "${Z_HARNESS_RUN_ID}" "base_resolved" \
      "$(printf '{"tier":"%s","path":"%s","repo_id":"%s"}' "$tier" "$path" "$repo_id")" \
      2>/dev/null || true
    unset _Z_HARNESS_RESOLVING_BASE
  fi
}

# z_harness_base_override
# Returns the artifact base dir override from Z_HARNESS_BASE_DIR (must be absolute).
# Prints an empty string and returns 0 when the env var is unset or empty.
# Prints the path to stdout and returns 0 when valid.
# Prints an error to stderr and exits 1 when set to a non-absolute path.
z_harness_base_override() {
  local base="${Z_HARNESS_BASE_DIR:-}"
  if [[ -z "$base" ]]; then
    return 0  # unset — caller uses default
  fi
  if [[ "$base" != /* ]]; then
    echo "[z-harness] Z_HARNESS_BASE_DIR must be an absolute path, got: $base" >&2
    exit 1
  fi
  printf '%s' "$base"
}

# base_dir
# Echoes the resolved artifact base directory (for z-stats, banners, diagnostics).
base_dir() {
  z_harness_base
}

# active_plans_dir
# Returns the directory for the active-plan registry JSON files.
active_plans_dir() {
  local base
  base="$(z_harness_base)"
  printf '%s/active-plans' "$base"
}

# followups_dir
# Returns the directory for the follow-up queue.
followups_dir() {
  local base
  base="$(z_harness_base)"
  printf '%s/followups' "$base"
}

# plan_dir <slug>
# Returns the canonical path for a plan, respecting Z_HARNESS_BASE_DIR and
# Z_HARNESS_PLANS_DIR overrides.
#
# Precedence for the plans directory root:
#   1. Z_HARNESS_PLANS_DIR (explicit; must be absolute when Z_HARNESS_BASE_DIR is also set,
#      to prevent repo-local writes from defeating the base-dir override guarantee)
#   2. <z_harness_base>/plans (resolved via z_harness_base())
#
# When both Z_HARNESS_BASE_DIR and Z_HARNESS_PLANS_DIR are set:
#   - If Z_HARNESS_PLANS_DIR is absolute → it wins (explicit absolute override).
#   - If Z_HARNESS_PLANS_DIR is relative → exit 1 (would escape the base, violating
#     the model.patch invariant). Resolve to an absolute path before setting both.
plan_dir() {
  local slug="$1"
  local base_dir_path
  # Compute the base ONCE here so the empty-slug branch can reuse it without
  # triggering a second z_harness_base() call (which would re-probe all tiers).
  local zh_base=""
  if [[ -n "${Z_HARNESS_PLANS_DIR:-}" ]]; then
    # If BASE_DIR is also set, PLANS_DIR must be absolute to guarantee no repo writes.
    if [[ -n "${Z_HARNESS_BASE_DIR:-}" && "${Z_HARNESS_PLANS_DIR}" != /* ]]; then
      echo "[z-harness] Z_HARNESS_PLANS_DIR must be absolute when Z_HARNESS_BASE_DIR is set, got: $Z_HARNESS_PLANS_DIR" >&2
      exit 1
    fi
    base_dir_path="$Z_HARNESS_PLANS_DIR"
  else
    zh_base="$(z_harness_base)"
    base_dir_path="$zh_base/plans"
  fi
  if [ -z "$slug" ]; then
    # Legacy flat layout: no slug → return the base dir itself (not the plans subdir).
    # When Z_HARNESS_BASE_DIR is set this lands outside the repo;
    # when unset we default to the repo-relative "z-harness" folder.
    if [[ -n "${Z_HARNESS_PLANS_DIR:-}" ]]; then
      echo "${Z_HARNESS_PLANS_DIR}"
    else
      # Reuse the already-computed base; no second z_harness_base() call needed.
      echo "$zh_base"
    fi
  else
    echo "${base_dir_path}/${slug}"
  fi
}

# legacy_plan_dir <slug>
# Returns the legacy path(s) for a plan.
# Probes both z-harness/<slug> (old flat layout) and z-harness/plans/<slug> (new in-repo layout).
# When called for path resolution, the caller should check existence; this function just returns
# the primary legacy candidate.
# Extended dual-read: also exposes the secondary legacy path via legacy_plan_dir_secondary.
legacy_plan_dir() {
  local slug="$1"
  if [ -z "$slug" ]; then
    echo "z-harness"
  else
    echo "z-harness/${slug}"
  fi
}

# legacy_plan_dir_secondary <slug>
# Returns the secondary legacy path: z-harness/plans/<slug>
# (the in-repo plans/ path used before the external base was introduced).
legacy_plan_dir_secondary() {
  local slug="$1"
  if [ -z "$slug" ]; then
    echo "z-harness/plans"
  else
    echo "z-harness/plans/${slug}"
  fi
}

# resolve_plan_path <slug>
# Tries new path first (via z_harness_base()), then legacy paths.
# Legacy paths probed: z-harness/plans/<slug> (in-repo canonical), then z-harness/<slug> (flat).
# If legacy is used, echoes warning to stderr (once per parent process via stamp file).
resolve_plan_path() {
  local slug="$1"
  local new_path
  local old_path
  local old_path2
  new_path=$(plan_dir "$slug")
  old_path=$(legacy_plan_dir "$slug")
  old_path2=$(legacy_plan_dir_secondary "$slug")

  if [ -d "$new_path" ]; then
    echo "$new_path"
    return 0
  fi

  # Dual-read: probe both legacy paths
  local legacy_found=""
  if [ -d "$old_path2" ]; then
    legacy_found="$old_path2"
  elif [ -d "$old_path" ]; then
    legacy_found="$old_path"
  fi

  if [[ -n "$legacy_found" ]]; then
    local STAMP="${TMPDIR:-/tmp}/z-harness-legacy-warned-$PPID"
    if [ ! -f "$STAMP" ]; then
      echo "Warning: Plan found at legacy path '$legacy_found'. Please run 'scripts/migrate-plan-layout.sh $slug' to migrate." >&2
      touch "$STAMP"
    fi
    echo "$legacy_found"
    return 0
  fi

  # Default to new path even if it doesn't exist (for creation)
  echo "$new_path"
}

# CLI wrapper
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  cmd="$1"
  shift
  case "$cmd" in
    plan_dir|legacy_plan_dir|legacy_plan_dir_secondary|resolve_plan_path|z_harness_base_override)
      "$cmd" "$@"
      ;;
    z_harness_base|base_dir)
      z_harness_base "$@"
      ;;
    z_harness_repo_id)
      z_harness_repo_id "$@"
      ;;
    active_plans_dir)
      active_plans_dir "$@"
      ;;
    followups_dir)
      followups_dir "$@"
      ;;
    *)
      echo "Usage: $0 {plan_dir|legacy_plan_dir|legacy_plan_dir_secondary|resolve_plan_path|z_harness_base_override|z_harness_base|z_harness_repo_id|active_plans_dir|followups_dir|base_dir} [args...]" >&2
      exit 1
      ;;
  esac
fi
