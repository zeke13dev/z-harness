#!/usr/bin/env bash
# Print a JSON blob describing the current z-harness plugin version.
#
# Output (single line):
#   {"z_harness_version":"<git short-sha>","z_harness_dirty":<true|false>,"z_harness_branch":"<branch>"}
#
# Used by /z-plan, /z-implement-all, /z-implement-next, /z-review-all at
# their `run_start` events so post-run analysis can correlate behavior
# with the exact plugin commit.
#
# Resolves the plugin dir via $ANTIGRAVITY_PLUGIN_ROOT or $CLAUDE_PLUGIN_ROOT
# or by walking up from this script's own location.

set -euo pipefail

PLUGIN_ROOT="${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}}"

cd "$PLUGIN_ROOT" 2>/dev/null || {
  printf '{"z_harness_version":"unknown","z_harness_dirty":false,"z_harness_branch":"unknown","error":"plugin_root_missing"}'
  exit 0
}

# If plugin dir isn't a git repo, fall back to a deterministic marker.
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  printf '{"z_harness_version":"non-git","z_harness_dirty":false,"z_harness_branch":"none"}'
  exit 0
fi

SHA="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
TAG="$(git describe --tags --abbrev=0 2>/dev/null || echo "")"
if git diff --quiet --ignore-submodules HEAD 2>/dev/null; then
  DIRTY="false"
else
  DIRTY="true"
fi

if [[ -n "$TAG" ]]; then
  printf '{"z_harness_version":"%s","z_harness_dirty":%s,"z_harness_branch":"%s","z_harness_tag":"%s"}' \
    "$SHA" "$DIRTY" "$BRANCH" "$TAG"
else
  printf '{"z_harness_version":"%s","z_harness_dirty":%s,"z_harness_branch":"%s"}' \
    "$SHA" "$DIRTY" "$BRANCH"
fi
