#!/usr/bin/env bash
# install.sh — install z-harness for Claude Code and/or Codex
#
# NOTE: This script handles Claude Code and Codex direct plugin install paths.
# To install the z-harness Python CLI (z-harness / zh) via uv tool install,
# use scripts/curl-install.sh instead:
#   curl -fsSL https://github.com/zeke13dev/z-harness/releases/latest/download/install.sh | sh
# OMP is installed via `z-harness export --host omp`.
#
# Usage:
#   bash install.sh                         # Claude Code install, auto-detect mode
#   bash install.sh --target=codex          # Codex plugin install
#   bash install.sh --target=all            # Claude Code + Codex install
#   bash install.sh --tarball=<url>         # force tarball download from URL
#   bash install.sh --tarball=<url> --tarball-sha256=<sha256>
#   bash install.sh --force                 # overwrite a non-symlink plugin dir
#   bash install.sh --generate-exports      # also regenerate host exports to temp/exports/
#   bash install.sh --legacy                # also install frozen scripts/export-*.py exporters (deprecated)
#   bash install.sh --help                  # show this help
#
# Claude symlink mode (repo clone detected):
#   Requires: cwd contains .git AND skills/ AND agents/ AND runtime/
#   Creates: ~/.claude/plugins/z-harness@zeke-tools -> <cwd>
#   Installs: skills/, agents/, runtime/ (includes runtime/drivers/)
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
TARBALL_SHA256=""
FORCE=false
TARGET="claude"
LEGACY=false
GENERATE_EXPORTS=false

# Parse args
for arg in "$@"; do
  case "$arg" in
    --tarball=*)
      TARBALL_URL="${arg#--tarball=}"
      ;;
    --tarball-sha256=*)
      TARBALL_SHA256="${arg#--tarball-sha256=}"
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
    --generate-exports)
      GENERATE_EXPORTS=true
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
  [[ -d ".git" && -d "skills" && -d "agents" && -d "runtime" ]]
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
  if [[ "$GENERATE_EXPORTS" == "true" ]]; then
    generate_exports_on_demand "$repo_path"
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
  if [[ "$GENERATE_EXPORTS" == "true" ]]; then
    generate_exports_on_demand "$repo_path"
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

generate_exports_on_demand() {
  local repo_path="$1"
  local gen_script="${repo_path}/scripts/generate-exports.py"
  if [[ ! -f "$gen_script" ]]; then
    printf 'install.sh: WARNING: --generate-exports: %s not found; skipping.\n' "$gen_script" >&2
    return
  fi
  printf '\nGenerating host exports to temp/exports/ via runtime drivers...\n'
  python3 "$gen_script" || {
    printf 'install.sh: ERROR: export generation failed (see above).\n' >&2
    exit 1
  }
}

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    printf 'install.sh: ERROR: neither sha256sum nor shasum found for checksum verification.\n' >&2
    return 1
  fi
}

verify_tarball_sha256() {
  local tarball="$1"
  local expected="$2"
  local actual
  local expected_lower
  expected_lower="$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')"
  actual="$(sha256_file "$tarball")" || return 1
  if [[ "$actual" != "$expected_lower" ]]; then
    printf 'install.sh: ERROR: tarball SHA-256 mismatch.\n' >&2
    printf '  expected: %s\n' "$expected_lower" >&2
    printf '  actual:   %s\n' "$actual" >&2
    return 1
  fi
}

check_can_replace_install_destination() {
  local destination="$1"
  local label="$2"

  if [[ -e "$destination" && ! -L "$destination" ]]; then
    if [[ "$FORCE" != "true" ]]; then
      printf 'install.sh: ERROR: %s exists and is not a symlink.\n' "$destination" >&2
      printf '  Use --force to overwrite the existing %s install.\n' "$label" >&2
      return 1
    fi
    printf 'install.sh: replacing existing non-symlink at %s (--force)\n' "$destination"
  fi
  mkdir -p "$(dirname "$destination")"
}

STAGED_EXISTING_BACKUP=""
stage_existing_install_for_replacement() {
  local destination="$1"
  local label="$2"
  local backup_path=""

  STAGED_EXISTING_BACKUP=""
  if [[ -e "$destination" || -L "$destination" ]]; then
    backup_path="${destination}.backup.$$"
    while [[ -e "$backup_path" || -L "$backup_path" ]]; do
      backup_path="${destination}.backup.$$.${RANDOM}"
    done
    if ! mv "$destination" "$backup_path"; then
      printf 'install.sh: ERROR: could not stage existing %s install for replacement: %s\n' "$label" "$destination" >&2
      return 1
    fi
  fi
  STAGED_EXISTING_BACKUP="$backup_path"
}

rollback_replaced_install() {
  local destination="$1"
  local backup_path="$2"
  local label="$3"

  rm -rf "$destination"
  if [[ -n "$backup_path" ]]; then
    if ! mv "$backup_path" "$destination"; then
      printf 'install.sh: ERROR: rollback failed for existing %s install at %s\n' "$label" "$destination" >&2
    fi
  fi
}

replace_with_staged_install() {
  local staged_source="$1"
  local destination="$2"
  local label="$3"
  local backup_path=""

  check_can_replace_install_destination "$destination" "$label" || return 1
  if ! stage_existing_install_for_replacement "$destination" "$label"; then
    return 1
  fi
  backup_path="$STAGED_EXISTING_BACKUP"

  if mv "$staged_source" "$destination"; then
    if [[ -n "$backup_path" ]]; then
      rm -rf "$backup_path"
    fi
    return 0
  fi

  printf 'install.sh: ERROR: could not move staged %s install into place: %s\n' "$label" "$destination" >&2
  rollback_replaced_install "$destination" "$backup_path" "$label"
  return 1
}

replace_two_staged_installs_atomically() {
  local first_staged_source="$1"
  local first_destination="$2"
  local first_label="$3"
  local second_staged_source="$4"
  local second_destination="$5"
  local second_label="$6"
  local first_backup_path=""
  local second_backup_path=""

  check_can_replace_install_destination "$first_destination" "$first_label" || return 1
  check_can_replace_install_destination "$second_destination" "$second_label" || return 1

  if ! stage_existing_install_for_replacement "$first_destination" "$first_label"; then
    return 1
  fi
  first_backup_path="$STAGED_EXISTING_BACKUP"

  if ! stage_existing_install_for_replacement "$second_destination" "$second_label"; then
    rollback_replaced_install "$first_destination" "$first_backup_path" "$first_label"
    return 1
  fi
  second_backup_path="$STAGED_EXISTING_BACKUP"

  if ! mv "$first_staged_source" "$first_destination"; then
    printf 'install.sh: ERROR: could not move staged %s install into place: %s\n' "$first_label" "$first_destination" >&2
    rollback_replaced_install "$second_destination" "$second_backup_path" "$second_label"
    rollback_replaced_install "$first_destination" "$first_backup_path" "$first_label"
    return 1
  fi

  if ! mv "$second_staged_source" "$second_destination"; then
    printf 'install.sh: ERROR: could not move staged %s install into place: %s\n' "$second_label" "$second_destination" >&2
    rollback_replaced_install "$second_destination" "$second_backup_path" "$second_label"
    rollback_replaced_install "$first_destination" "$first_backup_path" "$first_label"
    return 1
  fi

  if [[ -n "$first_backup_path" ]]; then
    rm -rf "$first_backup_path"
  fi
  if [[ -n "$second_backup_path" ]]; then
    rm -rf "$second_backup_path"
  fi
}

STAGED_TARBALL_TMP_DIR=""
STAGED_TARBALL_SOURCE=""
stage_tarball_payload() {
  local url="$1"
  local label="$2"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  local tmp_tarball="${tmp_dir}/z-harness.tar.gz"

  STAGED_TARBALL_TMP_DIR=""
  STAGED_TARBALL_SOURCE=""

  printf 'install.sh: downloading tarball from %s\n' "$url"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsSL "$url" -o "$tmp_tarball"; then
      printf 'install.sh: ERROR: failed to download tarball from %s\n' "$url" >&2
      rm -rf "$tmp_dir"
      return 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget -q "$url" -O "$tmp_tarball"; then
      printf 'install.sh: ERROR: failed to download tarball from %s\n' "$url" >&2
      rm -rf "$tmp_dir"
      return 1
    fi
  else
    printf 'install.sh: ERROR: neither curl nor wget found.\n' >&2
    rm -rf "$tmp_dir"
    return 1
  fi

  if [[ -n "$TARBALL_SHA256" ]]; then
    if [[ ! "$TARBALL_SHA256" =~ ^[0-9a-fA-F]{64}$ ]]; then
      printf 'install.sh: ERROR: --tarball-sha256 must be a 64-character hexadecimal SHA-256 digest.\n' >&2
      rm -rf "$tmp_dir"
      return 1
    fi
    if ! verify_tarball_sha256 "$tmp_tarball" "$TARBALL_SHA256"; then
      rm -rf "$tmp_dir"
      return 1
    fi
  fi

  local extract_dir="${tmp_dir}/extracted"
  mkdir -p "$extract_dir"
  if ! tar -xzf "$tmp_tarball" -C "$extract_dir"; then
    printf 'install.sh: ERROR: tarball extraction failed; existing %s install was left untouched.\n' "$label" >&2
    rm -rf "$tmp_dir"
    return 1
  fi

  # Move extracted contents to plugin location.
  # Support both bare tarballs and tarballs with a single top-level directory.
  local top_entries
  top_entries="$(find "$extract_dir" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
  local staged_source="$extract_dir"
  if [[ "$top_entries" -eq 1 ]]; then
    staged_source="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -print -quit)"
  fi

  STAGED_TARBALL_TMP_DIR="$tmp_dir"
  STAGED_TARBALL_SOURCE="$staged_source"
}

extract_tarball_to() {
  local url="$1"
  local destination="$2"
  local label="$3"
  local tmp_dir
  local staged_source

  if ! stage_tarball_payload "$url" "$label"; then
    exit 1
  fi
  tmp_dir="$STAGED_TARBALL_TMP_DIR"
  staged_source="$STAGED_TARBALL_SOURCE"

  if ! replace_with_staged_install "$staged_source" "$destination" "$label"; then
    rm -rf "$tmp_dir"
    exit 1
  fi

  rm -rf "$tmp_dir"
}

finish_claude_tarball_install() {
  printf 'install.sh: tarball extracted to %s\n' "$CLAUDE_PLUGIN_LINK_PATH"
  # runtime/ (including runtime/drivers/) is expected to be present in the tarball.
  if [[ "$LEGACY" == "true" ]]; then
    install_legacy_exporters "$CLAUDE_PLUGIN_LINK_PATH"
  fi
  if [[ "$GENERATE_EXPORTS" == "true" ]]; then
    generate_exports_on_demand "$CLAUDE_PLUGIN_LINK_PATH"
  fi
  printf '\nz-harness installed for Claude Code (tarball mode).\n'
  printf 'To update later, reinstall from the audited release manifest/tarball (for example: z-harness install --target=claude --force).\n'
}

install_claude_tarball() {
  extract_tarball_to "$1" "$CLAUDE_PLUGIN_LINK_PATH" "Claude Code"
  finish_claude_tarball_install
}

finish_codex_tarball_install() {
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
  if [[ "$GENERATE_EXPORTS" == "true" ]]; then
    generate_exports_on_demand "$CODEX_PLUGIN_LINK_PATH"
  fi
  printf '\nz-harness installed for Codex (tarball mode). To update later, reinstall from the audited release manifest/tarball (for example: z-harness install --target=codex --force), then start a new Codex thread.\n'
}

install_codex_tarball() {
  extract_tarball_to "$1" "$CODEX_PLUGIN_LINK_PATH" "Codex"
  finish_codex_tarball_install
}

install_all_tarball() {
  local url="$1"
  local claude_tmp_dir
  local claude_staged_source
  local codex_tmp_dir
  local codex_staged_source

  if ! stage_tarball_payload "$url" "Claude Code"; then
    exit 1
  fi
  claude_tmp_dir="$STAGED_TARBALL_TMP_DIR"
  claude_staged_source="$STAGED_TARBALL_SOURCE"

  if ! stage_tarball_payload "$url" "Codex"; then
    rm -rf "$claude_tmp_dir"
    exit 1
  fi
  codex_tmp_dir="$STAGED_TARBALL_TMP_DIR"
  codex_staged_source="$STAGED_TARBALL_SOURCE"

  if ! replace_two_staged_installs_atomically \
    "$claude_staged_source" "$CLAUDE_PLUGIN_LINK_PATH" "Claude Code" \
    "$codex_staged_source" "$CODEX_PLUGIN_LINK_PATH" "Codex"; then
    rm -rf "$claude_tmp_dir" "$codex_tmp_dir"
    exit 1
  fi

  rm -rf "$claude_tmp_dir" "$codex_tmp_dir"
  finish_claude_tarball_install
  finish_codex_tarball_install
}

install_target_from_repo() {
  case "$TARGET" in
    claude)
      if ! is_repo_clone; then
        printf 'install.sh: ERROR: not a Claude plugin repo clone (need .git + skills/ + agents/ + runtime/).\n' >&2
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
    all) install_all_tarball "$1" ;;
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
  printf '  Claude needs .git + skills/ + agents/ + runtime/.\n' >&2
  printf '  Codex needs .git + .codex-plugin/plugin.json + skills/.\n' >&2
  printf '  To install from tarball: bash install.sh --target=%s --tarball=<url>\n' "$TARGET" >&2
  printf '  Or set Z_HARNESS_RELEASE_URL and re-run.\n' >&2
  exit 1
fi
