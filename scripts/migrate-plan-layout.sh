#!/bin/bash
set -e

# Load plan-path helper
# shellcheck source=scripts/plan-path.sh
source "$(dirname "$0")/plan-path.sh"

DRY_RUN=0

migrate_one() {
  local slug="$1"
  local old_dir
  local new_dir
  old_dir=$(legacy_plan_dir "$slug")
  new_dir=$(plan_dir "$slug")

  # Idempotent: if old doesn't exist and new does, already migrated — exit silently.
  if [ ! -d "$old_dir" ] && [ -d "$new_dir" ]; then
    return 0
  fi

  if [ ! -d "$old_dir" ]; then
    echo "Error: Legacy directory '$old_dir' not found." >&2
    exit 1
  fi

  if [ -d "$new_dir" ]; then
    echo "Error: Target directory '$new_dir' already exists. Manual resolution required." >&2
    echo "Diff between old and new:" >&2
    diff -rq "$old_dir" "$new_dir" >&2 || true
    exit 1
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] Would migrate '$slug': '$old_dir' → '$new_dir'"
    return 0
  fi

  echo "Migrating '$slug' from '$old_dir' to '$new_dir'..."
  mkdir -p "$(dirname "$new_dir")"
  mv "$old_dir" "$new_dir"

  # Log event
  if [ -f "$(dirname "$0")/log-event.sh" ]; then
    Z_HARNESS_SLUG="$slug" "$(dirname "$0")/log-event.sh" "migration" "migration_done" "{\"slug\": \"$slug\", \"from\": \"$old_dir\", \"to\": \"$new_dir\"}"
  fi

  echo "Migration complete for '$slug'."
}

migrate_all() {
  echo "Searching for legacy plans to migrate in z-harness/..."
  # A legacy plan dir contains PLAN.md, SPEC.md, or TASKS.md at its root.
  # Exclude infra dirs: plans, archive, improvements; also skip metrics.jsonl (it's a file, not a dir).
  for d in z-harness/*/; do
    [ -d "$d" ] || continue   # defensive: skip if not a directory
    d="${d%/}"                 # strip trailing slash
    slug="${d#z-harness/}"

    case "$slug" in
      plans|archive|improvements) continue ;;
    esac

    # Skip if d is metrics.jsonl (belt-and-suspenders; glob won't match it, but be defensive)
    [ "$slug" = "metrics.jsonl" ] && continue

    if [ -f "$d/PLAN.md" ] || [ -f "$d/SPEC.md" ] || [ -f "$d/TASKS.md" ]; then
      migrate_one "$slug"
    fi
  done
}

# Parse arguments
POSITIONAL=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) POSITIONAL+=("$arg") ;;
  esac
done

set -- "${POSITIONAL[@]+"${POSITIONAL[@]}"}"

if [ "${1:-}" = "--all" ]; then
  migrate_all
elif [ -n "${1:-}" ]; then
  migrate_one "$1"
else
  echo "Usage: $0 [--dry-run] <slug> | [--dry-run] --all" >&2
  exit 1
fi
