#!/bin/bash

# plan_dir <slug>
# Returns the canonical path for a plan, respecting Z_HARNESS_PLANS_DIR override.
plan_dir() {
  local slug="$1"
  local base_dir="${Z_HARNESS_PLANS_DIR:-z-harness/plans}"
  if [ -z "$slug" ]; then
    echo "z-harness" # Legacy flat
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
    plan_dir|legacy_plan_dir|resolve_plan_path)
      "$cmd" "$@"
      ;;
    *)
      echo "Usage: $0 {plan_dir|legacy_plan_dir|resolve_plan_path} <slug>" >&2
      exit 1
      ;;
  esac
fi
