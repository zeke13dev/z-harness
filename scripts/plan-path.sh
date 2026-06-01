#!/bin/bash

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

# plan_dir <slug>
# Returns the canonical path for a plan, respecting Z_HARNESS_BASE_DIR and
# Z_HARNESS_PLANS_DIR overrides.
#
# Precedence for the plans directory root:
#   1. Z_HARNESS_PLANS_DIR (explicit; must be absolute when Z_HARNESS_BASE_DIR is also set,
#      to prevent repo-local writes from defeating the base-dir override guarantee)
#   2. Z_HARNESS_BASE_DIR/plans (when Z_HARNESS_BASE_DIR is set)
#   3. z-harness/plans (built-in default, relative to repo root)
#
# When both Z_HARNESS_BASE_DIR and Z_HARNESS_PLANS_DIR are set:
#   - If Z_HARNESS_PLANS_DIR is absolute → it wins (explicit absolute override).
#   - If Z_HARNESS_PLANS_DIR is relative → exit 1 (would escape the base, violating
#     the model.patch invariant). Resolve to an absolute path before setting both.
plan_dir() {
  local slug="$1"
  local base_dir
  if [[ -n "${Z_HARNESS_PLANS_DIR:-}" ]]; then
    # If BASE_DIR is also set, PLANS_DIR must be absolute to guarantee no repo writes.
    if [[ -n "${Z_HARNESS_BASE_DIR:-}" && "${Z_HARNESS_PLANS_DIR}" != /* ]]; then
      echo "[z-harness] Z_HARNESS_PLANS_DIR must be absolute when Z_HARNESS_BASE_DIR is set, got: $Z_HARNESS_PLANS_DIR" >&2
      exit 1
    fi
    base_dir="$Z_HARNESS_PLANS_DIR"
  else
    local base_override
    base_override="$(z_harness_base_override)"
    if [[ -n "$base_override" ]]; then
      base_dir="$base_override/plans"
    else
      base_dir="z-harness/plans"
    fi
  fi
  if [ -z "$slug" ]; then
    # Legacy flat layout: no slug → return the base dir itself (not the plans subdir).
    # When Z_HARNESS_BASE_DIR is set this lands outside the repo;
    # when unset we default to the repo-relative "z-harness" folder.
    if [[ -n "${Z_HARNESS_PLANS_DIR:-}" ]]; then
      echo "${Z_HARNESS_PLANS_DIR}"
    else
      local noslug_base
      noslug_base="$(z_harness_base_override)"
      if [[ -n "$noslug_base" ]]; then
        echo "$noslug_base"
      else
        echo "z-harness"
      fi
    fi
  else
    echo "${base_dir}/${slug}"
  fi
}

# legacy_plan_dir <slug>
# Returns the legacy path for a plan.
legacy_plan_dir() {
  local slug="$1"
  if [ -z "$slug" ]; then
    echo "z-harness"
  else
    echo "z-harness/${slug}"
  fi
}

# resolve_plan_path <slug>
# Tries new path first, then legacy.
# If legacy is used, echoes warning to stderr (once per parent process via stamp file).
resolve_plan_path() {
  local slug="$1"
  local new_path
  local old_path
  new_path=$(plan_dir "$slug")
  old_path=$(legacy_plan_dir "$slug")

  if [ -d "$new_path" ]; then
    echo "$new_path"
    return 0
  fi

  if [ -d "$old_path" ]; then
    local STAMP="${TMPDIR:-/tmp}/z-harness-legacy-warned-$PPID"
    if [ ! -f "$STAMP" ]; then
      echo "Warning: Plan found at legacy path '$old_path'. Please run 'scripts/migrate-plan-layout.sh $slug' to migrate." >&2
      touch "$STAMP"
    fi
    echo "$old_path"
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
    plan_dir|legacy_plan_dir|resolve_plan_path|z_harness_base_override)
      "$cmd" "$@"
      ;;
    *)
      echo "Usage: $0 {plan_dir|legacy_plan_dir|resolve_plan_path|z_harness_base_override} <slug>" >&2
      exit 1
      ;;
  esac
fi
