#!/usr/bin/env bash
# install.sh — install z-harness plugin for Claude Code
#
# Usage:
#   bash install.sh              # auto-detect mode (repo clone or tarball)
#   bash install.sh --tarball=<url>   # force tarball download from URL
#   bash install.sh --force      # overwrite a non-symlink plugin dir
#
# Symlink mode (repo clone detected):
#   Requires: cwd contains .git AND commands/ AND agents/
#   Creates: ~/.claude/plugins/z-harness@zeke-tools -> <cwd>
#
# Tarball mode:
#   Downloads tarball from Z_HARNESS_RELEASE_URL or --tarball=<url>
#   Extracts under ~/.claude/plugins/z-harness@zeke-tools/

set -euo pipefail

PLUGIN_LINK_NAME="z-harness@zeke-tools"
PLUGIN_PARENT_DIR="${HOME}/.claude/plugins"
PLUGIN_LINK_PATH="${PLUGIN_PARENT_DIR}/${PLUGIN_LINK_NAME}"

TARBALL_URL=""
FORCE=false

# Parse args
for arg in "$@"; do
  case "$arg" in
    --tarball=*)
      TARBALL_URL="${arg#--tarball=}"
      ;;
    --force)
      FORCE=true
      ;;
    *)
      printf 'install.sh: unknown argument: %s\n' "$arg" >&2
      exit 1
      ;;
  esac
done

# Detect mode
is_repo_clone() {
  [[ -d ".git" && -d "commands" && -d "agents" ]]
}

install_symlink() {
  local repo_path
  repo_path="$(pwd)"

  # Safety: refuse to overwrite a non-symlink unless --force
  if [[ -e "$PLUGIN_LINK_PATH" && ! -L "$PLUGIN_LINK_PATH" ]]; then
    if [[ "$FORCE" == "true" ]]; then
      printf 'install.sh: removing existing non-symlink at %s (--force)\n' "$PLUGIN_LINK_PATH"
      rm -rf "$PLUGIN_LINK_PATH"
    else
      printf 'install.sh: ERROR: %s exists and is not a symlink.\n' "$PLUGIN_LINK_PATH" >&2
      printf '  Use --force to overwrite it.\n' >&2
      exit 1
    fi
  fi

  # Remove stale symlink if present
  if [[ -L "$PLUGIN_LINK_PATH" ]]; then
    rm "$PLUGIN_LINK_PATH"
  fi

  mkdir -p "$PLUGIN_PARENT_DIR"
  ln -s "$repo_path" "$PLUGIN_LINK_PATH"

  printf 'install.sh: symlink created\n'
  printf '  %s -> %s\n' "$PLUGIN_LINK_PATH" "$repo_path"
  printf '\nz-harness installed (symlink mode). Edits in the repo go live immediately.\n'
}

install_tarball() {
  local url="$1"
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

  # Safety: refuse to overwrite a non-symlink unless --force
  if [[ -e "$PLUGIN_LINK_PATH" && ! -L "$PLUGIN_LINK_PATH" ]]; then
    if [[ "$FORCE" == "true" ]]; then
      printf 'install.sh: removing existing non-symlink at %s (--force)\n' "$PLUGIN_LINK_PATH"
      rm -rf "$PLUGIN_LINK_PATH"
    else
      printf 'install.sh: ERROR: %s exists and is not a symlink.\n' "$PLUGIN_LINK_PATH" >&2
      printf '  Use --force to overwrite it.\n' >&2
      rm -rf "$tmp_dir"
      exit 1
    fi
  fi

  # Remove stale symlink if present
  if [[ -L "$PLUGIN_LINK_PATH" ]]; then
    rm "$PLUGIN_LINK_PATH"
  fi

  mkdir -p "$PLUGIN_PARENT_DIR"
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
    mv "${extract_dir}/${top_dir}" "$PLUGIN_LINK_PATH"
  else
    mv "$extract_dir" "$PLUGIN_LINK_PATH"
  fi

  rm -rf "$tmp_dir"

  printf 'install.sh: tarball extracted to %s\n' "$PLUGIN_LINK_PATH"
  printf '\nz-harness installed (tarball mode).\n'
  printf 'Run /z-update inside Claude Code to update in the future.\n'
}

# Main dispatch
if [[ -n "$TARBALL_URL" ]]; then
  install_tarball "$TARBALL_URL"
elif is_repo_clone; then
  printf 'install.sh: detected repo clone at %s\n' "$(pwd)"
  install_symlink
elif [[ -n "${Z_HARNESS_RELEASE_URL:-}" ]]; then
  printf 'install.sh: no repo clone detected; using Z_HARNESS_RELEASE_URL\n'
  install_tarball "$Z_HARNESS_RELEASE_URL"
else
  printf 'install.sh: ERROR: not a repo clone (need .git + commands/ + agents/).\n' >&2
  printf '  To install from tarball: bash install.sh --tarball=<url>\n' >&2
  printf '  Or set Z_HARNESS_RELEASE_URL and re-run.\n' >&2
  exit 1
fi
