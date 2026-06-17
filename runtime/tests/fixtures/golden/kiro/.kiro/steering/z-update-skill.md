---
inclusion: manual
description: Update the local z-harness install for Codex, Claude Code, or Antigravity. Detects symlink vs extracted installs and refreshes safely without force-resetting local changes.
---

# z-update

Update the z-harness plugin to the latest version.

## What It Does

Detects whether z-harness is installed as a symlink (dev/clone mode) or an extracted tarball, then runs the appropriate update path.

Emits a `harness_updated` event with old and new version stamps.

## Steps

### 1. Locate plugin root

Use this detection block. It supports Codex, Claude Code, Antigravity, and a direct repo checkout:

```bash
Z_HARNESS_PLUGIN_ROOT="${Z_HARNESS_PLUGIN_ROOT:-${ANTIGRAVITY_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}}"
if [ -z "$Z_HARNESS_PLUGIN_ROOT" ]; then
  for candidate in \
    "${HOME}/plugins/z-harness" \
    "${HOME}/.claude/plugins/z-harness@zeke-tools" \
    "$(pwd)"
  do
    if [ -f "${candidate}/scripts/version.sh" ] && [ -f "${candidate}/install.sh" ]; then
      Z_HARNESS_PLUGIN_ROOT="$candidate"
      break
    fi
  done
fi

if [ -z "$Z_HARNESS_PLUGIN_ROOT" ] || [ ! -f "${Z_HARNESS_PLUGIN_ROOT}/scripts/version.sh" ]; then
  echo "[z-update] ERROR: z-harness plugin root not found."
  echo "Run install.sh --target=codex from the repo, or set Z_HARNESS_PLUGIN_ROOT."
  exit 1
fi
```

### 2. Detect install mode

```bash
PLUGIN_DIR="$Z_HARNESS_PLUGIN_ROOT"
MODE="tarball"
if [ -L "$PLUGIN_DIR" ]; then
  MODE="symlink"
  PLUGIN_DIR="$(readlink "$PLUGIN_DIR")"
elif git -C "$PLUGIN_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  MODE="symlink"
fi
```

### 3. Capture old version

```bash
OLD_VERSION="$(Z_HARNESS_PLUGIN_ROOT="$PLUGIN_DIR" bash "${PLUGIN_DIR}/scripts/version.sh")"
```

### 4. Symlink mode - git pull

Pre-flight: abort on dirty tree.

```bash
DIRTY="$(git -C "$PLUGIN_DIR" status --porcelain 2>/dev/null)"
if [ -n "$DIRTY" ]; then
  echo "[z-update] Aborting: plugin repo has uncommitted changes:"
  git -C "$PLUGIN_DIR" status
  echo ""
  echo "Commit or stash your changes, then re-run z-update."
  exit 1
fi
```

Pull:

```bash
git -C "$PLUGIN_DIR" pull --ff-only
```

If `git pull --ff-only` fails, print the error and advise the user to resolve manually. Do not force-merge or reset.

### 5. Tarball mode - atomic swap

```bash
RELEASE_URL="${Z_HARNESS_RELEASE_URL:-}"
RELEASE_URL="${RELEASE_URL:-https://example.com/z-harness/releases/latest/z-harness.tar.gz}"
```

If `RELEASE_URL` still points at `example.com`, halt and ask the user to set `Z_HARNESS_RELEASE_URL`; there is no real public release URL yet.

Steps:

1. Download new tarball to a temp directory.
2. Extract to a temp location.
3. If the extracted tarball has a single top-level directory, use that directory as the new plugin root.
4. Atomically swap: `mv "$PLUGIN_DIR" "${PLUGIN_DIR}.old" && mv "$TMP_EXTRACT" "$PLUGIN_DIR"`.
5. Remove the old dir: `rm -rf "${PLUGIN_DIR}.old"`.
6. On any failure during swap, restore: `mv "${PLUGIN_DIR}.old" "$PLUGIN_DIR"`.

### 6. Capture new version and emit event

```bash
NEW_VERSION="$(Z_HARNESS_PLUGIN_ROOT="$PLUGIN_DIR" bash "${PLUGIN_DIR}/scripts/version.sh")"

echo "[z-update] Updated successfully."
echo "  old: ${OLD_VERSION}"
echo "  new: ${NEW_VERSION}"

bash "${PLUGIN_DIR}/scripts/log-event.sh" \
  "z-update-$(date -u +%Y%m%dT%H%M%SZ)" \
  harness_updated \
  "$(printf '{"mode":"%s","old_version":%s,"new_version":%s}' \
     "$MODE" "$OLD_VERSION" "$NEW_VERSION")"
```

For Codex marketplace installs, reinstall the plugin cache after a successful symlink update:

```bash
if command -v codex >/dev/null 2>&1 && [ -f "${HOME}/.agents/plugins/marketplace.json" ]; then
  codex plugin add z-harness@personal
fi
```

Start a new Codex thread after reinstalling so the updated skills are loaded.

## Notes

- In symlink mode, the plugin dir is the live repo. Never reset it automatically.
- In tarball mode, `--ff-only` is not applicable; the atomic swap is the equivalent safety guarantee.
- To switch from tarball to symlink mode, clone the repo and re-run `bash install.sh --target=codex` or `bash install.sh --target=claude`.
