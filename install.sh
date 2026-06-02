#!/usr/bin/env bash
# install.sh — install z-harness for Claude Code and/or Codex
#
# Usage:
#   bash install.sh                    # Claude Code install, auto-detect mode
#   bash install.sh --target=codex     # Codex plugin install
#   bash install.sh --target=all       # Claude Code + Codex install
#   bash install.sh --tarball=<url>    # force tarball download from URL
#   bash install.sh --force            # overwrite a non-symlink plugin dir
#   bash install.sh --legacy           # also install frozen scripts/export-*.py exporters (deprecated)
#   bash install.sh --help             # show this help
#
# Claude symlink mode (repo clone detected):
#   Requires: cwd contains .git AND commands/ AND agents/ AND runtime/
#   Creates: ~/.claude/plugins/z-harness@zeke-tools -> <cwd>
#   Installs: commands/, agents/, runtime/ (includes runtime/drivers/)
#
# Codex symlink mode (repo clone detected):
#   Requires: cwd contains .git AND .codex-plugin/plugin.json AND skills/
#   Creates: ~/plugins/z-harness -> <cwd>
#   Creates/updates: ~/.agents/plugins/marketplace.json
#   Runs: codex plugin add z-harness@personal when codex is on PATH
#
# Tarball mode:
#   Downloads tarball from Z_HARNESS_RELEASE_URL or --tarball=<url>
#   Extracts under the selected host's plugin location.
#   Tarball must include runtime/ tree (drivers live under runtime/drivers/).
#
# Legacy mode (--legacy):
#   In addition to the standard install, copies frozen scripts/export-*.py
#   exporters to the install target. This flag is deprecated and will be
#   removed in the next minor release.

set -euo pipefail

CLAUDE_PLUGIN_LINK_NAME="z-harness@zeke-tools"
CLAUDE_PLUGIN_PARENT_DIR="${HOME}/.claude/plugins"
CLAUDE_PLUGIN_LINK_PATH="${CLAUDE_PLUGIN_PARENT_DIR}/${CLAUDE_PLUGIN_LINK_NAME}"

CODEX_MARKETPLACE_NAME="personal"
CODEX_MARKETPLACE_ROOT="${HOME}/.agents/plugins"
CODEX_PLUGIN_PARENT_DIR="${HOME}/plugins"
CODEX_PLUGIN_NAME="z-harness"
CODEX_PLUGIN_LINK_PATH="${CODEX_PLUGIN_PARENT_DIR}/${CODEX_PLUGIN_NAME}"
CODEX_MARKETPLACE_PATH="${CODEX_MARKETPLACE_ROOT}/marketplace.json"

TARBALL_URL=""
FORCE=false
TARGET="claude"
LEGACY=false

# Parse args
for arg in "$@"; do
  case "$arg" in
    --tarball=*)
      TARBALL_URL="${arg#--tarball=}"
      ;;
    --force)
      FORCE=true
      ;;
    --target=claude|--host=claude)
      TARGET="claude"
      ;;
    --target=codex|--host=codex)
      TARGET="codex"
      ;;
    --target=all|--host=all)
      TARGET="all"
      ;;
    --legacy)
      LEGACY=true
      ;;
    --help|-h)
      # Print the header comment block (lines 2+, starting with #) up to the first non-comment line
      awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} /^[^#]/{exit}' "$0"
      exit 0
      ;;
    *)
      printf 'install.sh: unknown argument: %s\n' "$arg" >&2
      exit 1
      ;;
  esac
done

# Detect mode
is_repo_clone() {
  # runtime/ includes drivers/ (runtime/drivers/); no separate top-level drivers/ needed.
  [[ -d ".git" && -d "commands" && -d "agents" && -d "runtime" ]]
}

is_codex_plugin_source() {
  [[ -d ".git" && -f ".codex-plugin/plugin.json" && -d "skills" ]]
}

ensure_can_replace() {
  local path="$1"
  local label="$2"
  if [[ -e "$path" && ! -L "$path" ]]; then
    if [[ "$FORCE" == "true" ]]; then
      printf 'install.sh: removing existing non-symlink at %s (--force)\n' "$path"
      rm -rf "$path"
    else
      printf 'install.sh: ERROR: %s exists and is not a symlink.\n' "$path" >&2
      printf '  Use --force to overwrite the existing %s install.\n' "$label" >&2
      exit 1
    fi
  fi

  if [[ -L "$path" ]]; then
    rm "$path"
  fi
}

install_claude_symlink() {
  local repo_path
  repo_path="$(pwd)"

  ensure_can_replace "$CLAUDE_PLUGIN_LINK_PATH" "Claude Code"

  mkdir -p "$CLAUDE_PLUGIN_PARENT_DIR"
  ln -s "$repo_path" "$CLAUDE_PLUGIN_LINK_PATH"

  printf 'install.sh: symlink created\n'
  printf '  %s -> %s\n' "$CLAUDE_PLUGIN_LINK_PATH" "$repo_path"
  # In symlink mode the symlink resolves to the whole repo, so runtime/ and
  # runtime/drivers/ (the drivers tree) are available automatically.
  if [[ "$LEGACY" == "true" ]]; then
    # Symlink already exposes scripts/export-*.py via the repo; --legacy is a no-op
    # but we still print the deprecation notice so callers are aware.
    printf '\nNOTE: --legacy mode is available for one minor release only and will be removed in the next release.\n'
    printf 'install.sh: legacy exporters are available via the repo symlink (no copy needed in symlink mode)\n'
  fi
  printf '\nz-harness installed for Claude Code (symlink mode). Edits in the repo go live immediately.\n'
}

write_codex_marketplace() {
  mkdir -p "$CODEX_MARKETPLACE_ROOT"
  python3 - "$CODEX_MARKETPLACE_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if path.exists():
    data = json.loads(path.read_text(encoding="utf-8"))
else:
    data = {
        "name": "personal",
        "interface": {"displayName": "Personal"},
        "plugins": [],
    }

if data.get("name") != "personal":
    raise SystemExit(f"install.sh: ERROR: {path} exists but its marketplace name is not 'personal'")

data.setdefault("interface", {}).setdefault("displayName", "Personal")
plugins = data.setdefault("plugins", [])
entry = {
    "name": "z-harness",
    "source": {"source": "local", "path": "./plugins/z-harness"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity",
}
for idx, existing in enumerate(plugins):
    if existing.get("name") == "z-harness":
        plugins[idx] = entry
        break
else:
    plugins.append(entry)

path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

install_codex_symlink() {
  local repo_path
  repo_path="$(pwd)"

  ensure_can_replace "$CODEX_PLUGIN_LINK_PATH" "Codex"

  mkdir -p "$CODEX_PLUGIN_PARENT_DIR"
  ln -s "$repo_path" "$CODEX_PLUGIN_LINK_PATH"
  write_codex_marketplace

  printf 'install.sh: symlink created\n'
  printf '  %s -> %s\n' "$CODEX_PLUGIN_LINK_PATH" "$repo_path"
  printf 'install.sh: marketplace updated\n'
  printf '  %s\n' "$CODEX_MARKETPLACE_PATH"

  if command -v codex >/dev/null 2>&1; then
    codex plugin add "${CODEX_PLUGIN_NAME}@${CODEX_MARKETPLACE_NAME}"
  else
    printf 'install.sh: codex not found on PATH; run this after installing Codex:\n'
    printf '  codex plugin add %s@%s\n' "$CODEX_PLUGIN_NAME" "$CODEX_MARKETPLACE_NAME"
  fi

  # In symlink mode the symlink resolves to the whole repo; runtime/drivers/ available automatically.
  if [[ "$LEGACY" == "true" ]]; then
    printf '\nNOTE: --legacy mode is available for one minor release only and will be removed in the next release.\n'
    printf 'install.sh: legacy exporters are available via the repo symlink (no copy needed in symlink mode)\n'
  fi
  printf '\nz-harness installed for Codex (symlink mode). Start a new Codex thread to load new skills.\n'
}

# REMOVE-AT: v<next-minor>. See C6-D1.
install_legacy_exporters() {
  local destination="$1"
  local repo_path
  repo_path="$(pwd)"

  printf '\nNOTE: --legacy mode is available for one minor release only and will be removed in the next release.\n'

  local src_dir="${repo_path}/scripts"
  local dst_dir="${destination}/scripts"
  mkdir -p "$dst_dir"

  local count=0
  for exporter in "${src_dir}"/export-*.py; do
    [[ -f "$exporter" ]] || continue
    cp "$exporter" "${dst_dir}/$(basename "$exporter")"
    count=$((count + 1))
  done

  if [[ "$count" -gt 0 ]]; then
    printf 'install.sh: legacy exporters installed (%d files -> %s)\n' "$count" "$dst_dir"
  else
    printf 'install.sh: WARNING: --legacy specified but no scripts/export-*.py files found in %s\n' "$src_dir" >&2
  fi
}

extract_tarball_to() {
  local url="$1"
  local destination="$2"
  local label="$3"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  local tmp_tarball="${tmp_dir}/z-harness.tar.gz"

  printf 'install.sh: downloading tarball from %s\n' "$url"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$tmp_tarball"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$tmp_tarball"
  else
    printf 'install.sh: ERROR: neither curl nor wget found.\n' >&2
    rm -rf "$tmp_dir"
    exit 1
  fi

  ensure_can_replace "$destination" "$label"

  mkdir -p "$(dirname "$destination")"
  local extract_dir="${tmp_dir}/extracted"
  mkdir -p "$extract_dir"
  tar -xzf "$tmp_tarball" -C "$extract_dir"

  # Move extracted contents to plugin location
  # Support both bare tarballs and tarballs with a single top-level directory
  local top_entries
  top_entries="$(ls "$extract_dir" | wc -l | tr -d ' ')"
  if [[ "$top_entries" -eq 1 ]]; then
    local top_dir
    top_dir="$(ls "$extract_dir")"
    mv "${extract_dir}/${top_dir}" "$destination"
  else
    mv "$extract_dir" "$destination"
  fi

  rm -rf "$tmp_dir"
}

install_claude_tarball() {
  extract_tarball_to "$1" "$CLAUDE_PLUGIN_LINK_PATH" "Claude Code"
  printf 'install.sh: tarball extracted to %s\n' "$CLAUDE_PLUGIN_LINK_PATH"
  # runtime/ (including runtime/drivers/) is expected to be present in the tarball.
  if [[ "$LEGACY" == "true" ]]; then
    install_legacy_exporters "$CLAUDE_PLUGIN_LINK_PATH"
  fi
  printf '\nz-harness installed for Claude Code (tarball mode).\n'
  printf 'Run /z-update inside Claude Code to update in the future.\n'
}

install_codex_tarball() {
  extract_tarball_to "$1" "$CODEX_PLUGIN_LINK_PATH" "Codex"
  write_codex_marketplace
  printf 'install.sh: tarball extracted to %s\n' "$CODEX_PLUGIN_LINK_PATH"
  printf 'install.sh: marketplace updated\n'
  printf '  %s\n' "$CODEX_MARKETPLACE_PATH"
  if command -v codex >/dev/null 2>&1; then
    codex plugin add "${CODEX_PLUGIN_NAME}@${CODEX_MARKETPLACE_NAME}"
  else
    printf 'install.sh: codex not found on PATH; run this after installing Codex:\n'
    printf '  codex plugin add %s@%s\n' "$CODEX_PLUGIN_NAME" "$CODEX_MARKETPLACE_NAME"
  fi
  # runtime/ (including runtime/drivers/) is expected to be present in the tarball.
  if [[ "$LEGACY" == "true" ]]; then
    install_legacy_exporters "$CODEX_PLUGIN_LINK_PATH"
  fi
  printf '\nz-harness installed for Codex (tarball mode). Start a new Codex thread to load new skills.\n'
}

install_target_from_repo() {
  case "$TARGET" in
    claude)
      if ! is_repo_clone; then
        printf 'install.sh: ERROR: not a Claude plugin repo clone (need .git + commands/ + agents/ + runtime/).\n' >&2
        exit 1
      fi
      install_claude_symlink
      ;;
    codex)
      if ! is_codex_plugin_source; then
        printf 'install.sh: ERROR: not a Codex plugin source (need .git + .codex-plugin/plugin.json + skills/).\n' >&2
        exit 1
      fi
      install_codex_symlink
      ;;
    all)
      if ! is_repo_clone || ! is_codex_plugin_source; then
        printf 'install.sh: ERROR: repo is missing required Claude or Codex plugin files.\n' >&2
        exit 1
      fi
      install_claude_symlink
      install_codex_symlink
      ;;
  esac
}

install_target_from_tarball() {
  case "$TARGET" in
    claude) install_claude_tarball "$1" ;;
    codex) install_codex_tarball "$1" ;;
    all)
      install_claude_tarball "$1"
      install_codex_tarball "$1"
      ;;
  esac
}

# Main dispatch
if [[ -n "$TARBALL_URL" ]]; then
  install_target_from_tarball "$TARBALL_URL"
elif { [[ "$TARGET" == "claude" ]] && is_repo_clone; } \
  || { [[ "$TARGET" == "codex" ]] && is_codex_plugin_source; } \
  || { [[ "$TARGET" == "all" ]] && is_repo_clone && is_codex_plugin_source; }; then
  printf 'install.sh: detected repo clone at %s\n' "$(pwd)"
  install_target_from_repo
elif [[ -n "${Z_HARNESS_RELEASE_URL:-}" ]]; then
  printf 'install.sh: no repo clone detected; using Z_HARNESS_RELEASE_URL\n'
  install_target_from_tarball "$Z_HARNESS_RELEASE_URL"
else
  printf 'install.sh: ERROR: not a compatible repo clone for --target=%s.\n' "$TARGET" >&2
  printf '  Claude needs .git + commands/ + agents/ + runtime/.\n' >&2
  printf '  Codex needs .git + .codex-plugin/plugin.json + skills/.\n' >&2
  printf '  To install from tarball: bash install.sh --target=%s --tarball=<url>\n' "$TARGET" >&2
  printf '  Or set Z_HARNESS_RELEASE_URL and re-run.\n' >&2
  exit 1
fi
