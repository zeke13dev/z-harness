#!/usr/bin/env bash
# bundle-plugin.sh — build a distributable z-harness tarball
#
# Usage: bash scripts/bundle-plugin.sh
#
# Output: dist/z-harness-<version>.tar.gz
#
# Exclusions (never included in the tarball):
#   .git/
#   exports/
#   temp/
#   z-harness/ runtime state
#   archive/, improvements/, research/
#   .agent/, .pi/, .local/, .pytest_cache/, .claude/worktrees/, .antigravitycli/
#   dist/
#   .z-harness/
#   __pycache__/
#   providers.json (any location)
#   z-harness/<slug>/ dirs containing PLAN.md/SPEC.md/TASKS.md (legacy plans)
#
# After building, runs scripts/audit-tarball.sh on the output.
# Fails (non-zero) and deletes the tarball on any audit violation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

# Resolve version
VERSION_JSON="$(bash "$SCRIPT_DIR/version.sh")"
VERSION="$(printf '%s' "$VERSION_JSON" | python3 -c 'import json,sys; d=json.loads(sys.stdin.read()); print(d.get("z_harness_tag") or d["z_harness_version"])')"

if [[ -z "$VERSION" ]]; then
  printf 'bundle-plugin.sh: ERROR: could not determine version\n' >&2
  exit 1
fi

DIST_DIR="$REPO_ROOT/dist"
mkdir -p "$DIST_DIR"

OUTPUT="$DIST_DIR/z-harness-${VERSION}.tar.gz"

printf 'bundle-plugin.sh: building %s\n' "$OUTPUT"

# Build exclusion list for tar
# Note: tar --exclude patterns match relative to the source dir
EXCLUDES=(
  "--exclude=./.git"
  "--exclude=./exports"
  "--exclude=./prompts"
  "--exclude=./temp"
  "--exclude=./z-harness"
  "--exclude=./archive"
  "--exclude=./improvements"
  "--exclude=./research"
  "--exclude=./.agent"
  "--exclude=./.pi"
  "--exclude=./.local"
  "--exclude=./.pytest_cache"
  "--exclude=./.claude/worktrees"
  "--exclude=./.antigravitycli"
  "--exclude=./.venv"
  "--exclude=./dist"
  "--exclude=./.z-harness"
  "--exclude=./__pycache__"
  "--exclude=*/__pycache__"
  "--exclude=*/providers.json"
  "--exclude=./providers.json"
)

# Enumerate legacy plan dirs — any z-harness/<slug>/ that contains PLAN.md,
# SPEC.md, or TASKS.md — and exclude them from the tarball.
# Skip the canonical directories that are either already excluded above or
# are intentionally included.
_SKIP_SLUGS=("plans" "archive" "improvements")
if [[ -d "$REPO_ROOT/z-harness" ]]; then
  while IFS= read -r -d '' dir; do
    slug="$(basename "$dir")"
    # Skip already-excluded canonical dirs
    skip=0
    for s in "${_SKIP_SLUGS[@]}"; do
      [[ "$slug" == "$s" ]] && skip=1 && break
    done
    [[ "$skip" -eq 1 ]] && continue
    # Exclude if the dir contains any of the plan marker files
    if [[ -f "$dir/PLAN.md" || -f "$dir/SPEC.md" || -f "$dir/TASKS.md" ]]; then
      EXCLUDES+=("--exclude=./z-harness/${slug}")
    fi
  done < <(find "$REPO_ROOT/z-harness" -maxdepth 1 -mindepth 1 -type d -print0)
fi

tar -czf "$OUTPUT" "${EXCLUDES[@]}" -C "$REPO_ROOT" .

printf 'bundle-plugin.sh: tarball created at %s\n' "$OUTPUT"
printf 'bundle-plugin.sh: running audit...\n'

if ! bash "$SCRIPT_DIR/audit-tarball.sh" "$OUTPUT"; then
  printf 'bundle-plugin.sh: FAIL — audit violation; deleting tarball\n' >&2
  rm -f "$OUTPUT"
  exit 1
fi

printf 'bundle-plugin.sh: build complete — %s\n' "$OUTPUT"
