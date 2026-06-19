#!/usr/bin/env bash
#
# install-changelog-hook.sh — manage the CHANGELOG.md post-commit hook.
#
# Usage:
#   scripts/install-changelog-hook.sh install   # wire .git/hooks/post-commit
#   scripts/install-changelog-hook.sh remove     # unwire it
#   scripts/install-changelog-hook.sh status     # report
#
# The installed hook is a thin shim that calls scripts/changelog-from-commit.sh.
# If a post-commit hook already exists, the shim is appended (chained) rather
# than overwriting it; `remove` strips only our block.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[z-harness] not inside a git repository" >&2; exit 1; }

HOOK_DIR="$(git rev-parse --git-path hooks 2>/dev/null)"
[ -n "$HOOK_DIR" ] || HOOK_DIR="$REPO_ROOT/.git/hooks"
HOOK="$HOOK_DIR/post-commit"

MARK_BEGIN="# >>> z-harness changelog hook >>>"
MARK_END="# <<< z-harness changelog hook <<<"

block() {
  cat <<EOF
$MARK_BEGIN
# Drafts a CHANGELOG.md bullet from the commit. Managed by
# scripts/install-changelog-hook.sh — edit there, not here.
"$SCRIPT_DIR/changelog-from-commit.sh" || true
$MARK_END
EOF
}

has_block() { [ -f "$HOOK" ] && grep -qF "$MARK_BEGIN" "$HOOK"; }

cmd="${1:-status}"
case "$cmd" in
  install)
    mkdir -p "$HOOK_DIR"
    if has_block; then
      echo "[z-harness] changelog hook already installed: $HOOK"
      exit 0
    fi
    if [ ! -f "$HOOK" ]; then
      { echo "#!/usr/bin/env bash"; echo; block; } > "$HOOK"
    else
      # Chain onto the existing hook. Ensure it's executable & has a shebang.
      head -n1 "$HOOK" | grep -q '^#!' || {
        tmp="$(mktemp)"; { echo "#!/usr/bin/env bash"; cat "$HOOK"; } > "$tmp"; mv "$tmp" "$HOOK"; }
      { echo; block; } >> "$HOOK"
    fi
    chmod +x "$HOOK"
    echo "[z-harness] installed changelog post-commit hook: $HOOK"
    ;;
  remove)
    if ! has_block; then
      echo "[z-harness] no changelog hook present in $HOOK"
      exit 0
    fi
    tmp="$(mktemp)"
    awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
      $0==b {skip=1; next}
      $0==e {skip=0; next}
      !skip {print}
    ' "$HOOK" > "$tmp"
    # Drop a now-empty hook (only shebang/blanks left); else keep the rest.
    if grep -qvE '^(#!.*|[[:space:]]*)$' "$tmp"; then
      mv "$tmp" "$HOOK"; chmod +x "$HOOK"
    else
      rm -f "$tmp" "$HOOK"
    fi
    echo "[z-harness] removed changelog hook from post-commit"
    ;;
  status)
    if has_block; then
      echo "installed: $HOOK"
    else
      echo "not installed (repo: $REPO_ROOT)"
    fi
    echo "config: changelog.auto=$(python3 "$SCRIPT_DIR/config.py" get changelog.auto 2>/dev/null)" \
         "types=$(python3 "$SCRIPT_DIR/config.py" get changelog.types 2>/dev/null)"
    ;;
  *)
    echo "Usage: $0 {install|remove|status}" >&2; exit 1 ;;
esac
