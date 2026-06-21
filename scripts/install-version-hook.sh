#!/usr/bin/env bash
#
# install-version-hook.sh — manage the version-stamping pre-commit hook.
#
# Usage:
#   scripts/install-version-hook.sh install   # wire .git/hooks/pre-commit
#   scripts/install-version-hook.sh remove    # unwire it
#   scripts/install-version-hook.sh status    # report
#
# The installed hook is a thin shim that runs scripts/sync-version.sh --pending
# and stages the manifests, so every commit carries a unique version string
# (PATCH = commit count). It is non-blocking: a sync failure never aborts the
# commit — drift is caught later by `make version-check` in CI.
#
# If a pre-commit hook already exists, the shim is chained (appended) rather than
# overwriting it; `remove` strips only our block. Mirrors install-changelog-hook.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[z-harness] not inside a git repository" >&2; exit 1; }

HOOK_DIR="$(git rev-parse --git-path hooks 2>/dev/null)"
[ -n "$HOOK_DIR" ] || HOOK_DIR="$REPO_ROOT/.git/hooks"
HOOK="$HOOK_DIR/pre-commit"

MARK_BEGIN="# >>> z-harness version hook >>>"
MARK_END="# <<< z-harness version hook <<<"

block() {
  cat <<EOF
$MARK_BEGIN
# Stamps the computed version into plugin manifests and stages them, so every
# commit carries a unique version (cache can't go stale). Non-blocking by design.
# Managed by scripts/install-version-hook.sh — edit there, not here.
if "$SCRIPT_DIR/sync-version.sh" --pending sync >/dev/null 2>&1; then
  git add .claude-plugin/marketplace.json .claude-plugin/plugin.json plugin.json .codex-plugin/plugin.json 2>/dev/null || true
fi
$MARK_END
EOF
}

has_block() { [ -f "$HOOK" ] && grep -qF "$MARK_BEGIN" "$HOOK"; }

cmd="${1:-status}"
case "$cmd" in
  install)
    mkdir -p "$HOOK_DIR"
    if has_block; then
      echo "[z-harness] version hook already installed: $HOOK"
      exit 0
    fi
    if [ ! -f "$HOOK" ]; then
      { echo "#!/usr/bin/env bash"; echo; block; } > "$HOOK"
    else
      head -n1 "$HOOK" | grep -q '^#!' || {
        tmp="$(mktemp)"; { echo "#!/usr/bin/env bash"; cat "$HOOK"; } > "$tmp"; mv "$tmp" "$HOOK"; }
      { echo; block; } >> "$HOOK"
    fi
    chmod +x "$HOOK"
    echo "[z-harness] installed version pre-commit hook: $HOOK"
    ;;
  remove)
    if ! has_block; then
      echo "[z-harness] no version hook present in $HOOK"
      exit 0
    fi
    tmp="$(mktemp)"
    awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
      $0==b {skip=1; next}
      $0==e {skip=0; next}
      !skip {print}
    ' "$HOOK" > "$tmp"
    if grep -qvE '^(#!.*|[[:space:]]*)$' "$tmp"; then
      mv "$tmp" "$HOOK"; chmod +x "$HOOK"
    else
      rm -f "$tmp" "$HOOK"
    fi
    echo "[z-harness] removed version hook from pre-commit"
    ;;
  status)
    if has_block; then
      echo "installed: $HOOK"
    else
      echo "not installed (repo: $REPO_ROOT)"
    fi
    echo "version: $(bash "$SCRIPT_DIR/sync-version.sh" --print 2>/dev/null || echo '?')"
    ;;
  *)
    echo "Usage: $0 {install|remove|status}" >&2; exit 1 ;;
esac
