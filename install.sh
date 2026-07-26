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
#   bash install.sh --tarball=<path>        # install a local archive
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
#   Requires: cwd contains .git + skills/. A missing generated Codex manifest
#             is bootstrapped from the tracked Claude version stamp.
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

INSTALL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT_PATH="${INSTALL_SCRIPT_DIR}/$(basename "${BASH_SOURCE[0]}")"
INSTALL_SCRIPT_IMAGE_FD=9
if ! exec 9<"$INSTALL_SCRIPT_PATH"; then
  printf 'install.sh: ERROR: could not open the running installer image.\n' >&2
  exit 1
fi
INSTALL_SCRIPT_IMAGE_SHA256="$(python3 -c '
import hashlib
import os
import sys

with os.fdopen(os.dup(int(sys.argv[1])), "rb") as image:
    image.seek(0)
    print(hashlib.sha256(image.read()).hexdigest())
' "$INSTALL_SCRIPT_IMAGE_FD")" || {
  printf 'install.sh: ERROR: could not fingerprint the running installer image.\n' >&2
  exit 1
}
readonly INSTALL_SCRIPT_IMAGE_FD INSTALL_SCRIPT_IMAGE_SHA256

run_embedded_python() {
  local marker="$1"
  shift
  python3 -c '
import hashlib
import os
import sys

image_fd, expected_digest, marker = sys.argv[1:4]
with os.fdopen(os.dup(int(image_fd)), "rb") as image:
    image.seek(0)
    source_bytes = image.read()
actual_digest = hashlib.sha256(source_bytes).hexdigest()
if actual_digest != expected_digest:
    raise SystemExit("install.sh: ERROR: running installer image changed after startup")
try:
    source = source_bytes.decode("utf-8")
except UnicodeDecodeError:
    raise SystemExit("install.sh: ERROR: running installer image is not valid UTF-8")
begin = f"# Z_HARNESS_{marker}_PYTHON_BEGIN\n"
end = f"# Z_HARNESS_{marker}_PYTHON_END\n"
try:
    program = source.split(begin, 1)[1].split(end, 1)[0]
except IndexError:
    raise SystemExit(f"install.sh: ERROR: embedded Python program {marker} is unavailable")
sys.argv = [sys.argv[0], *sys.argv[4:]]
exec(compile(program, "<running-install.sh>:" + marker.lower(), "exec"))
' "$INSTALL_SCRIPT_IMAGE_FD" "$INSTALL_SCRIPT_IMAGE_SHA256" "$marker" "$@"
}

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
LIFECYCLE_FAULT_STEPS="payload.claude payload.codex marketplace.codex registration.codex exports.claude exports.codex cli.tool cli.launcher coherence"

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
  [[ -e ".git" && -d "skills" && -d "agents" && -d "runtime" ]]
}

is_codex_plugin_source() {
  [[ -e ".git" && -f ".codex-plugin/plugin.json" && -d "skills" ]]
}

bootstrap_codex_source_manifest() {
  [[ -f ".codex-plugin/plugin.json" ]] && return 0
  [[ -e ".git" && -d "skills" && -f ".claude-plugin/plugin.json" ]] || return 1
  python3 -c '
import json
import os
import sys
from pathlib import Path

source = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = source.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit("tracked Claude plugin manifest has no version")
manifest = {
    "name": "z-harness",
    "version": version,
    "description": "z-harness planning and implementation workflow for Codex CLI",
    "skills": "./skills/",
}
target = Path(sys.argv[2])
target.parent.mkdir(parents=True, exist_ok=True)
temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, target)
' ".claude-plugin/plugin.json" ".codex-plugin/plugin.json"
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

_write_codex_marketplace_source() {
  mkdir -p "$CODEX_MARKETPLACE_ROOT"
  python3 - "$CODEX_MARKETPLACE_PATH" <<'PY'
# Z_HARNESS_MARKETPLACE_PYTHON_BEGIN
import json
import os
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
temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
with temporary.open("rb") as handle:
    os.fsync(handle.fileno())
os.replace(temporary, path)
directory_fd = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
# Z_HARNESS_MARKETPLACE_PYTHON_END
PY
}

write_codex_marketplace() {
  mkdir -p "$CODEX_MARKETPLACE_ROOT"
  run_embedded_python MARKETPLACE "$CODEX_MARKETPLACE_PATH"
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
    printf 'install.sh: ERROR: --generate-exports: %s not found.\n' "$gen_script" >&2
    return 1
  fi
  printf '\nGenerating host exports to temp/exports/ via runtime drivers...\n'
  if ! python3 "$gen_script"; then
    printf 'install.sh: ERROR: export generation failed (see above).\n' >&2
    return 1
  fi
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

is_remote_tarball_url() {
  local location="$1"
  [[ "$location" =~ ^[A-Za-z][A-Za-z0-9+.-]*:// && "$location" != file://* ]]
}

validate_tarball_archive() {
  local tarball="$1"
  python3 - "$tarball" <<'PY'
import posixpath
import re
import sys
import tarfile
from pathlib import PurePosixPath

tarball_path = sys.argv[1]


def invalid_member_path(value: str) -> bool:
    if not value or "\\" in value or "\x00" in value:
        return True
    path = PurePosixPath(value)
    return (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:", value) is not None
        or any(part in {"", ".", ".."} for part in path.parts)
        or posixpath.normpath(value) != value
    )


def unsafe_link_destination(member: tarfile.TarInfo) -> bool:
    target = member.linkname
    if (
        not target
        or "\\" in target
        or "\x00" in target
        or PurePosixPath(target).is_absolute()
        or re.match(r"^[A-Za-z]:", target) is not None
    ):
        return True
    base = posixpath.dirname(member.name) if member.issym() else ""
    resolved = posixpath.normpath(posixpath.join(base, target))
    return resolved == ".." or resolved.startswith("../") or resolved.startswith("/")


try:
    with tarfile.open(tarball_path, mode="r:gz") as archive:
        for member in archive:
            if invalid_member_path(member.name):
                raise SystemExit(
                    f"install.sh: ERROR: unsafe archive member path: {member.name!r}"
                )
            if member.isdev():
                raise SystemExit(
                    f"install.sh: ERROR: unsafe archive member type: {member.name!r}"
                )
            if (member.issym() or member.islnk()) and unsafe_link_destination(member):
                raise SystemExit(
                    "install.sh: ERROR: unsafe archive link destination: "
                    f"{member.name!r} -> {member.linkname!r}"
                )
except (tarfile.TarError, OSError) as exc:
    raise SystemExit(
        "install.sh: ERROR: tarball extraction failed during pre-extraction "
        f"validation: {exc}"
    ) from None
PY
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
  local location="$1"
  local label="$2"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  local tmp_tarball="${tmp_dir}/z-harness.tar.gz"

  STAGED_TARBALL_TMP_DIR=""
  STAGED_TARBALL_SOURCE=""

  if is_remote_tarball_url "$location" && [[ -z "$TARBALL_SHA256" ]]; then
    printf 'install.sh: ERROR: --tarball-sha256 is required for a remote --tarball URL.\n' >&2
    rm -rf "$tmp_dir"
    return 1
  fi
  if [[ -n "$TARBALL_SHA256" && ! "$TARBALL_SHA256" =~ ^[0-9a-fA-F]{64}$ ]]; then
    printf 'install.sh: ERROR: --tarball-sha256 must be a 64-character hexadecimal SHA-256 digest.\n' >&2
    rm -rf "$tmp_dir"
    return 1
  fi

  if [[ "$location" != *://* ]]; then
    printf 'install.sh: reading local tarball from %s\n' "$location"
    if ! cp "$location" "$tmp_tarball"; then
      printf 'install.sh: ERROR: failed to read local tarball from %s\n' "$location" >&2
      rm -rf "$tmp_dir"
      return 1
    fi
  else
    printf 'install.sh: downloading tarball from %s\n' "$location"
    if command -v curl >/dev/null 2>&1; then
      if ! curl -fsSL "$location" -o "$tmp_tarball"; then
        printf 'install.sh: ERROR: failed to download tarball from %s\n' "$location" >&2
        rm -rf "$tmp_dir"
        return 1
      fi
    elif command -v wget >/dev/null 2>&1; then
      if ! wget -q "$location" -O "$tmp_tarball"; then
        printf 'install.sh: ERROR: failed to download tarball from %s\n' "$location" >&2
        rm -rf "$tmp_dir"
        return 1
      fi
    else
      printf 'install.sh: ERROR: neither curl nor wget found.\n' >&2
      rm -rf "$tmp_dir"
      return 1
    fi
  fi

  if [[ -n "$TARBALL_SHA256" ]]; then
    if ! verify_tarball_sha256 "$tmp_tarball" "$TARBALL_SHA256"; then
      rm -rf "$tmp_dir"
      return 1
    fi
  fi

  if ! validate_tarball_archive "$tmp_tarball"; then
    rm -rf "$tmp_dir"
    return 1
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
  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    transaction_path_is_safe claude_payload "$CLAUDE_PLUGIN_LINK_PATH" || {
      printf 'install.sh: ERROR: Claude destination escapes HOME.\n' >&2
      return 1
    }
    if [[ "$GENERATE_EXPORTS" == "true" ]]; then
      transaction_path_is_safe claude_exports "${CLAUDE_PLUGIN_LINK_PATH}/temp/exports" || return 1
    fi
  fi
  if [[ "$TARGET" == "codex" || "$TARGET" == "all" ]]; then
    transaction_path_is_safe codex_payload "$CODEX_PLUGIN_LINK_PATH" || {
      printf 'install.sh: ERROR: Codex destination escapes HOME.\n' >&2
      return 1
    }
    transaction_path_is_safe marketplace "$CODEX_MARKETPLACE_PATH" || return 1
    if [[ "$GENERATE_EXPORTS" == "true" ]]; then
      transaction_path_is_safe codex_exports "${CODEX_PLUGIN_LINK_PATH}/temp/exports" || return 1
    fi
  fi
}

install_target_from_tarball() {
  case "$TARGET" in
    claude) install_claude_tarball "$1" ;;
    codex) install_codex_tarball "$1" ;;
    all) install_all_tarball "$1" ;;
  esac
}

# --- durable lifecycle transaction ---

TRANSACTION_ROOT="${XDG_STATE_HOME:-${HOME}/.local/state}/z-harness/lifecycle"
TRANSACTION_DIR="${TRANSACTION_ROOT}/current"
TRANSACTION_STATE="${TRANSACTION_DIR}/state"
TRANSACTION_LOCK="${TRANSACTION_ROOT}/lock"
TRANSACTION_LOCK_HELD=false
TRANSACTION_LOCK_TOKEN=""
TRANSACTION_RETAIN_LOCK=false

_transaction_lock_protocol_source() {
  python3 - "$@" <<'PY'
# Z_HARNESS_LOCK_PROTOCOL_PYTHON_BEGIN
import fcntl
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

action, lock_raw, pid_raw, token = sys.argv[1:]
lock = Path(lock_raw)
pid = int(pid_raw)


def process_start_identity(owner_pid):
    process = subprocess.Popen(
        ["/bin/ps", "-o", "lstart=", "-p", str(owner_pid)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    stdout, _ = process.communicate()
    value = stdout.strip()
    return value if process.returncode == 0 and value else None


def read_owner(root):
    try:
        value = json.loads((root / "owner.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        try:
            legacy_pid = int((root / "pid").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        return {
            "pid": legacy_pid,
            "started": process_start_identity(legacy_pid),
            "token": "legacy",
        }
    return value if isinstance(value, dict) else None


def owner_is_live(owner):
    return (
        isinstance(owner, dict)
        and isinstance(owner.get("pid"), int)
        and isinstance(owner.get("started"), str)
        and process_start_identity(owner["pid"]) == owner["started"]
    )


def atomic_write(path, value):
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def with_guard(callback):
    lock.parent.mkdir(parents=True, exist_ok=True)
    guard = lock.parent / ".lock.guard"
    with guard.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return callback()


if action == "accept":
    for _ in range(100):
        owner = read_owner(lock)
        if (
            owner is not None
            and owner.get("token") == token
            and owner.get("pid") == pid
            and owner_is_live(owner)
        ):
            raise SystemExit(0)
        time.sleep(0.05)
    raise SystemExit(1)

if action == "release":
    def release():
        owner = read_owner(lock)
        if (
            owner is not None
            and owner.get("token") == token
            and owner.get("pid") == pid
        ):
            quarantine = lock.parent / f".lock.release.{token}"
            os.rename(lock, quarantine)
            shutil.rmtree(quarantine)

    with_guard(release)
    raise SystemExit(0)

if action != "acquire":
    raise SystemExit("unknown lifecycle lock action")

started = process_start_identity(pid)
if started is None:
    raise SystemExit(f"install.sh: ERROR: cannot identify lifecycle owner pid {pid}")
new_token = token or secrets.token_hex(32)


def acquire():
    if lock.exists():
        observed = read_owner(lock)
        if observed is not None and owner_is_live(observed):
            raise RuntimeError(f"lifecycle transaction is owned by active pid {observed['pid']}")
        quarantine = lock.parent / f".lock.stale.{secrets.token_hex(16)}"
        os.rename(lock, quarantine)
        if read_owner(quarantine) != observed:
            if not lock.exists():
                os.rename(quarantine, lock)
            raise RuntimeError("lifecycle lock changed during stale reclaim")
        shutil.rmtree(quarantine)
    candidate = lock.parent / f".lock.candidate.{new_token}"
    candidate.mkdir()
    atomic_write(
        candidate / "owner.json",
        json.dumps({"pid": pid, "started": started, "token": new_token}),
    )
    try:
        os.rename(candidate, lock)
    except BaseException:
        shutil.rmtree(candidate, ignore_errors=True)
        raise


try:
    with_guard(acquire)
except (OSError, RuntimeError) as exc:
    raise SystemExit(f"install.sh: ERROR: {exc}")
# Z_HARNESS_LOCK_PROTOCOL_PYTHON_END
PY
}

transaction_lock_protocol() {
  run_embedded_python LOCK_PROTOCOL "$@"
}

release_transaction_lock() {
  if [[ "$TRANSACTION_RETAIN_LOCK" != "true" && "$TRANSACTION_LOCK_HELD" == "true" && -n "$TRANSACTION_LOCK_TOKEN" ]]; then
    transaction_lock_protocol release "$TRANSACTION_LOCK" "$$" "$TRANSACTION_LOCK_TOKEN" || true
    TRANSACTION_LOCK_HELD=false
  fi
}

acquire_transaction_lock() {
  if [[ -n "${Z_HARNESS_HANDOFF_TOKEN:-}" ]]; then
    if ! transaction_lock_protocol accept "$TRANSACTION_LOCK" "$$" "$Z_HARNESS_HANDOFF_TOKEN"; then
      printf 'install.sh: ERROR: lifecycle ownership handoff was not completed.\n' >&2
      return 1
    fi
    TRANSACTION_LOCK_TOKEN="$Z_HARNESS_HANDOFF_TOKEN"
    TRANSACTION_LOCK_HELD=true
    return 0
  fi
  TRANSACTION_LOCK_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" || return $?
  transaction_lock_protocol acquire "$TRANSACTION_LOCK" "$$" "$TRANSACTION_LOCK_TOKEN" || return $?
  TRANSACTION_LOCK_HELD=true
}

transaction_path_is_safe() {
  local key="$1"
  local path="$2"
  python3 -c '
import os
import sys
from pathlib import Path

key, raw, home_raw, claude_raw, codex_raw, marketplace_raw, data_raw, bin_raw = sys.argv[1:]
if not raw.startswith("/") or "\n" in raw or "\x00" in raw or ".." in Path(raw).parts:
    raise SystemExit(1)
path = Path(raw)
home_path = Path(home_raw)
home = home_path.resolve()


def lexically_beneath(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def safe_parent(parent: Path, root: Path) -> bool:
    if not lexically_beneath(parent, root):
        return False
    cursor = parent
    while cursor != root:
        if cursor.is_symlink():
            return False
        cursor = cursor.parent
    try:
        parent.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def safe_allowed_root(root: Path) -> bool:
    if root.is_symlink():
        return False
    if lexically_beneath(root, home_path):
        return safe_parent(root, home_path)
    return True


def resolved_within(candidate: Path, roots: tuple[Path, ...]) -> bool:
    if not (candidate.exists() or candidate.is_symlink()):
        return True
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        return True
    return False


expected = {
    "claude_payload": Path(claude_raw),
    "codex_payload": Path(codex_raw),
    "marketplace": Path(marketplace_raw),
    "claude_exports": Path(claude_raw) / "temp" / "exports",
    "codex_exports": Path(codex_raw) / "temp" / "exports",
}
if key in {"claude_payload", "codex_payload", "marketplace"}:
    safe = path == expected[key] and safe_parent(path.parent, home_path)
    raise SystemExit(0 if safe else 1)
if key in {"claude_exports", "codex_exports"}:
    payload = expected[key].parents[1]
    temp_dir = payload / "temp"
    safe = (
        path == expected[key]
        and safe_parent(payload.parent, home_path)
        and not temp_dir.is_symlink()
    )
    if safe:
        try:
            path.parent.resolve().relative_to(home)
        except (OSError, ValueError):
            safe = False
    raise SystemExit(0 if safe else 1)
if key == "cli_tool":
    data_home = Path(data_raw)
    safe = (
        path in {data_home / "uv" / "tools" / "z-harness", data_home / "uv" / "tools" / "z_harness"}
        and safe_allowed_root(data_home)
        and safe_parent(path.parent, data_home)
        and resolved_within(path, (data_home,))
    )
    raise SystemExit(0 if safe else 1)
if key in {"cli_launcher_main", "cli_launcher_zh"}:
    bin_home = Path(bin_raw)
    safe = (
        path in {bin_home / "z-harness", bin_home / "zh"}
        and safe_allowed_root(bin_home)
        and safe_parent(path.parent, bin_home)
        and resolved_within(path, (home_path, Path(data_raw)))
    )
    raise SystemExit(0 if safe else 1)
raise SystemExit(1)
' "$key" "$path" "$HOME" "$CLAUDE_PLUGIN_LINK_PATH" "$CODEX_PLUGIN_LINK_PATH" "$CODEX_MARKETPLACE_PATH" "${XDG_DATA_HOME:-${HOME}/.local/share}" "${XDG_BIN_HOME:-${HOME}/.local/bin}"
}

_atomic_text_write_source() {
  local path="$1"
  local value="$2"
  python3 - "$path" "$value" <<'PY'
# Z_HARNESS_ATOMIC_TEXT_WRITE_PYTHON_BEGIN
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
with temporary.open("w", encoding="utf-8") as handle:
    handle.write(sys.argv[2] + "\n")
    handle.flush()
    os.fsync(handle.fileno())
os.replace(temporary, path)
directory_fd = os.open(path.parent, os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
# Z_HARNESS_ATOMIC_TEXT_WRITE_PYTHON_END
PY
}

atomic_text_write() {
  run_embedded_python ATOMIC_TEXT_WRITE "$1" "$2"
}

transaction_record_path() {
  local key="$1"
  local value="$2"
  atomic_text_write "${TRANSACTION_DIR}/${key}.path" "$value"
}

fsync_tree() {
  local root="$1"
  python3 - "$root" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
paths = [root]
if root.is_dir() and not root.is_symlink():
    paths.extend(root.rglob("*"))
for path in paths:
    if path.is_file() and not path.is_symlink():
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
for path in reversed(paths):
    if path.is_dir() and not path.is_symlink():
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
parent = os.open(root.parent, os.O_RDONLY)
try:
    os.fsync(parent)
finally:
    os.close(parent)
PY
}

transaction_backup_path() {
  local key="$1"
  local path="$2"
  transaction_record_path "$key" "$path" || return $?
  if [[ -e "$path" || -L "$path" ]]; then
    cp -a "$path" "${TRANSACTION_DIR}/${key}.backup.tmp" || return $?
    mv "${TRANSACTION_DIR}/${key}.backup.tmp" "${TRANSACTION_DIR}/${key}.backup" || return $?
    fsync_tree "${TRANSACTION_DIR}/${key}.backup" || return $?
    atomic_text_write "${TRANSACTION_DIR}/${key}.present" "true" || return $?
  fi
}

transaction_restore_path() {
  local key="$1"
  local path_file="${TRANSACTION_DIR}/${key}.path"
  local destination
  [[ -f "$path_file" ]] || return 0
  [[ -f "${TRANSACTION_DIR}/${key}.mutation" ]] || return 0
  destination="$(cat "$path_file")"
  if ! transaction_path_is_safe "$key" "$destination"; then
    printf 'install.sh: ERROR: refusing corrupt or unconfined recovery path for %s.\n' "$key" >&2
    return 1
  fi
  rm -rf "$destination" || return $?
  if [[ -f "${TRANSACTION_DIR}/${key}.present" ]]; then
    mkdir -p "$(dirname "$destination")" || return $?
    cp -a "${TRANSACTION_DIR}/${key}.backup" "$destination" || return $?
  fi
}

transaction_fault_after() {
  local step="$1"
  case " ${LIFECYCLE_FAULT_STEPS} " in
    *" ${step} "*) ;;
    *)
      printf 'install.sh: ERROR: undefined lifecycle fault step: %s\n' "$step" >&2
      return 2
      ;;
  esac
  atomic_text_write "${TRANSACTION_DIR}/completed.${step}" "true" || return $?
  if [[ "${Z_HARNESS_TEST_FAIL_AFTER:-}" == "$step" ]]; then
    printf 'install.sh: injected failure after %s\n' "$step" >&2
    return 97
  fi
}

transaction_registration_present() {
  command -v codex >/dev/null 2>&1 || return 1
  local listing=""
  listing="$(codex plugin list 2>/dev/null)" || return 2
  printf '%s\n' "$listing" | grep -Fq "${CODEX_PLUGIN_NAME}@${CODEX_MARKETPLACE_NAME}"
}

rollback_lifecycle_transaction() {
  [[ -d "$TRANSACTION_DIR" ]] || return 0
  atomic_text_write "$TRANSACTION_STATE" "rolling_back" || return $?

  local restore_failed=0
  if [[ -f "${TRANSACTION_DIR}/registration.attempted" ]] \
    && [[ -f "${TRANSACTION_DIR}/registration.absent" ]]; then
    local compensation_status=0
    if command -v codex >/dev/null 2>&1; then
      # Confirmed-absent pre-state authorizes compensation even when add's
      # post-state could not be observed. The final inventory, not add/remove's
      # exit status alone, decides whether pre-state has been restored.
      codex plugin remove "${CODEX_PLUGIN_NAME}@${CODEX_MARKETPLACE_NAME}" >/dev/null 2>&1 || true
      transaction_registration_present || compensation_status=$?
    else
      compensation_status=2
    fi
    if [[ "$compensation_status" -ne 1 ]]; then
      printf 'install.sh: ERROR: Codex registration compensation failed or could not be verified; recovery state retained.\n' >&2
      restore_failed=1
    else
      rm -f "${TRANSACTION_DIR}/registration.uncertain"
    fi
  elif [[ -f "${TRANSACTION_DIR}/registration.uncertain" ]] \
    && [[ -f "${TRANSACTION_DIR}/registration.present" ]]; then
    local preserved_status=0
    transaction_registration_present || preserved_status=$?
    if [[ "$preserved_status" -ne 0 ]]; then
      printf 'install.sh: ERROR: pre-existing Codex registration could not be revalidated; recovery state retained.\n' >&2
      restore_failed=1
    fi
  elif [[ -f "${TRANSACTION_DIR}/registration.uncertain" ]]; then
    printf 'install.sh: ERROR: Codex registration state lacks authoritative pre-state; recovery state retained.\n' >&2
    restore_failed=1
  fi

  # Reverse mutation order. Each restore is derived from durable pre-state, so
  # replay after an interrupted rollback is safe.
  transaction_restore_path cli_launcher_zh || restore_failed=$?
  transaction_restore_path cli_launcher_main || restore_failed=$?
  transaction_restore_path cli_tool || restore_failed=$?
  transaction_restore_path codex_exports || restore_failed=$?
  transaction_restore_path claude_exports || restore_failed=$?
  transaction_restore_path marketplace || restore_failed=$?
  transaction_restore_path codex_payload || restore_failed=$?
  transaction_restore_path claude_payload || restore_failed=$?

  if [[ "$restore_failed" -ne 0 ]]; then
    TRANSACTION_RETAIN_LOCK=true
    printf 'install.sh: ERROR: rollback is incomplete; durable recovery state was retained.\n' >&2
    return "$restore_failed"
  fi

  atomic_text_write "$TRANSACTION_STATE" "rolled_back" || return $?
  rm -rf "$TRANSACTION_DIR"
}

recover_lifecycle_transaction() {
  [[ -d "$TRANSACTION_DIR" ]] || return 0
  local state="unknown"
  if [[ -f "$TRANSACTION_STATE" ]]; then
    state="$(cat "$TRANSACTION_STATE")"
  fi
  if [[ "$state" == "committed" ]]; then
    rm -rf "$TRANSACTION_DIR"
    return 0
  fi
  printf 'install.sh: recovering interrupted lifecycle transaction (%s)\n' "$state" >&2
  rollback_lifecycle_transaction
}

inventory_payload() {
  local label="$1"
  local path="$2"
  local mode="missing"
  local version="missing"
  local location="$path"
  if [[ -L "$path" ]]; then
    mode="symlink"
    location="$(cd "$(dirname "$path")" && cd "$(readlink "$path")" 2>/dev/null && pwd -P || true)"
  elif [[ -d "$path" ]]; then
    mode="packaged"
  fi
  if [[ "$mode" != "missing" ]]; then
    if [[ -f "$path/VERSION" ]]; then
      version="$(tr -d '[:space:]' < "$path/VERSION")"
      [[ -n "$version" ]] || version="unknown"
    else
      version="unknown"
    fi
  fi
  printf 'install.sh: inventory %s mode=%s location=%s version=%s\n' "$label" "$mode" "$location" "$version"
}

inventory_cli() {
  local location="missing"
  local version="missing"
  local mode="missing"
  if command -v z-harness >/dev/null 2>&1; then
    location="$(command -v z-harness)"
    mode="executable"
    version="$(z-harness --version 2>/dev/null | awk '{print $NF}' | tail -1 || true)"
    [[ -n "$version" ]] || version="unknown"
  fi
  printf 'install.sh: inventory cli mode=%s location=%s version=%s\n' "$mode" "$location" "$version"
}

validate_candidate_version() {
  local root="$1"
  local candidate_mode="${2:-release}"
  if [[ ! -f "$root/VERSION" ]]; then
    printf 'install.sh: ERROR: verified candidate payload is missing VERSION.\n' >&2
    return 1
  fi
  if [[ "$candidate_mode" == "development" ]]; then
    [[ -n "$(tr -d '[:space:]' < "$root/VERSION")" ]] || {
      printf 'install.sh: ERROR: development checkout VERSION is empty.\n' >&2
      return 1
    }
    return 0
  fi
  if release_python_available; then
    release_python - "$root/VERSION" <<'PY'
import sys
from pathlib import Path
from z_harness_cli.release import parse_release_candidate

value = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
try:
    candidate = parse_release_candidate(value)
except ValueError as exc:
    raise SystemExit(f"install.sh: ERROR: candidate VERSION is not canonical: {exc}")
if value != candidate.plugin_version:
    raise SystemExit(
        f"install.sh: ERROR: payload VERSION must use canonical plugin spelling {candidate.plugin_version!r}"
    )
PY
    return $?
  fi
  standalone_release_version validate "$root/VERSION"
}

release_python_available() {
  if [[ -n "${Z_HARNESS_PYTHON:-}" ]]; then
    # An explicit interpreter is authoritative; release_python reports any
    # invalid path or missing release module instead of silently bypassing it.
    return 0
  fi
  if python3 -c 'from z_harness_cli.release import parse_release_candidate' >/dev/null 2>&1; then
    return 0
  fi
  [[ -x "${INSTALL_SCRIPT_DIR}/.venv/bin/python" ]] \
    && "${INSTALL_SCRIPT_DIR}/.venv/bin/python" -c 'from z_harness_cli.release import parse_release_candidate' >/dev/null 2>&1
}

release_python() {
  local configured="${Z_HARNESS_PYTHON:-}"
  if [[ -n "$configured" ]]; then
    if [[ "$configured" != /* || ! -x "$configured" ]]; then
      printf 'install.sh: ERROR: Z_HARNESS_PYTHON must be an absolute executable path.\n' >&2
      return 1
    fi
    "$configured" "$@"
    return $?
  fi
  if python3 -c 'from z_harness_cli.release import parse_release_candidate' >/dev/null 2>&1; then
    python3 "$@"
    return $?
  fi
  if [[ -x "${INSTALL_SCRIPT_DIR}/.venv/bin/python" ]]; then
    "${INSTALL_SCRIPT_DIR}/.venv/bin/python" "$@"
    return $?
  fi
  printf 'install.sh: ERROR: release validation requires the z-harness Python environment.\n' >&2
  return 1
}

standalone_release_version() {
  python3 - "$@" <<'PY'
import re
import sys
from pathlib import Path

CANONICAL_PLUGIN_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-beta\.(0|[1-9][0-9]*))?$"
)

action = sys.argv[1]
if action == "validate":
    value = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
    if not CANONICAL_PLUGIN_VERSION.fullmatch(value):
        raise SystemExit(
            f"install.sh: ERROR: candidate VERSION is not canonical: {value!r}"
        )
elif action == "payload":
    actual = Path(sys.argv[2]).read_text(encoding="utf-8").strip()
    expected, label, mode = sys.argv[3:]
    if mode == "development":
        valid = bool(actual) and actual == expected
    else:
        valid = (
            CANONICAL_PLUGIN_VERSION.fullmatch(actual) is not None
            and CANONICAL_PLUGIN_VERSION.fullmatch(expected) is not None
            and actual == expected
        )
    if not valid:
        raise SystemExit(
            f"install.sh: ERROR: {label} payload version {actual!r} "
            f"does not match candidate {expected!r}."
        )
elif action == "compatible":
    expected, actual = sys.argv[2:]
    if not (
        CANONICAL_PLUGIN_VERSION.fullmatch(expected)
        and CANONICAL_PLUGIN_VERSION.fullmatch(actual)
        and expected == actual
    ):
        raise SystemExit(
            f"install.sh: ERROR: CLI version {actual!r} is not compatible with candidate {expected!r}."
        )
else:
    raise SystemExit("unknown release-version validation action")
PY
}

transaction_replace_payload() {
  local key="$1"
  local source="$2"
  local destination="$3"
  local label="$4"
  local display_label="$label"
  if [[ "$label" == "claude" ]]; then display_label="Claude Code"; fi
  if [[ "$label" == "codex" ]]; then display_label="Codex"; fi
  atomic_text_write "${TRANSACTION_DIR}/${key}.mutation" "started" || return $?
  rm -rf "$destination" || return $?
  mkdir -p "$(dirname "$destination")" || return $?
  if [[ "$label" == "codex" ]]; then
    # Codex discovers ./skills directly.  Materialize a Codex-specific
    # payload for every source and tarball route so the source-only
    # multi-agent /z-execute skill cannot bypass the exported filter.
    local staged_copy="${TRANSACTION_DIR}/${key}.candidate"
    cp -a "$source" "$staged_copy" || return $?
    rm -rf "$staged_copy/skills" || return $?
    mkdir -p "$staged_copy/skills" || return $?
    local skill_dir
    for skill_dir in "$source"/skills/*; do
      [[ -d "$skill_dir" ]] || continue
      [[ "$(basename "$skill_dir")" == "z-execute" ]] && continue
      cp -a "$skill_dir" "$staged_copy/skills/" || return $?
    done
    if ! mv "$staged_copy" "$destination"; then
      printf 'install.sh: ERROR: could not move staged %s install into place: %s\n' "$display_label" "$destination" >&2
      return 1
    fi
  elif [[ -e "$source/.git" ]]; then
    ln -s "$source" "$destination" || return $?
  elif [[ -d "$source" && ! -L "$source" ]]; then
    local staged_copy="${TRANSACTION_DIR}/${key}.candidate"
    cp -a "$source" "$staged_copy" || return $?
    if ! mv "$staged_copy" "$destination"; then
      printf 'install.sh: ERROR: could not move staged %s install into place: %s\n' "$display_label" "$destination" >&2
      return 1
    fi
  else
    ln -s "$source" "$destination" || return $?
  fi
  transaction_fault_after "payload.${label}"
}

transaction_generate_exports() {
  local key="$1"
  local root="$2"
  local label="$3"
  atomic_text_write "${TRANSACTION_DIR}/${key}.mutation" "started" || return $?
  generate_exports_on_demand "$root" || return $?
  transaction_fault_after "exports.${label}"
}

transaction_replace_cli() {
  local wheel="${Z_HARNESS_TRANSACTION_CLI_WHEEL:-}"
  [[ -n "$wheel" ]] || return 0
  [[ -f "$wheel" ]] || {
    printf 'install.sh: ERROR: staged CLI wheel does not exist: %s\n' "$wheel" >&2
    return 1
  }
  local tool_root="${Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT:-}"
  local launcher="${Z_HARNESS_TRANSACTION_CLI_LAUNCHER:-}"
  local launcher_zh="${Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH:-}"
  [[ -n "$tool_root" ]] || {
    printf 'install.sh: ERROR: CLI transaction requires its tool root.\n' >&2
    return 1
  }
  atomic_text_write "${TRANSACTION_DIR}/cli_tool.mutation" "started" || return $?
  if [[ -n "$launcher" ]]; then
    atomic_text_write "${TRANSACTION_DIR}/cli_launcher_main.mutation" "started" || return $?
  fi
  if [[ -n "$launcher_zh" && "$launcher_zh" != "$launcher" ]]; then
    atomic_text_write "${TRANSACTION_DIR}/cli_launcher_zh.mutation" "started" || return $?
  fi
  uv tool install --upgrade "$wheel" || return $?
  transaction_fault_after "cli.tool" || return $?
  transaction_fault_after "cli.launcher" || return $?
}

transaction_prepare_cli_backup() {
  local wheel="${Z_HARNESS_TRANSACTION_CLI_WHEEL:-}"
  [[ -n "$wheel" ]] || return 0
  local tool_root="${Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT}"
  local launcher="${Z_HARNESS_TRANSACTION_CLI_LAUNCHER:-}"
  local launcher_zh="${Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH:-}"
  transaction_backup_path cli_tool "$tool_root" || return $?
  if [[ -n "$launcher" ]]; then transaction_backup_path cli_launcher_main "$launcher" || return $?; fi
  if [[ -n "$launcher_zh" && "$launcher_zh" != "$launcher" ]]; then
    transaction_backup_path cli_launcher_zh "$launcher_zh" || return $?
  fi
}

transaction_verify_payload_version() {
  local path="$1"
  local expected="$2"
  local label="$3"
  local candidate_mode="${4:-release}"
  if [[ "$candidate_mode" == "development" ]]; then
    local actual
    actual="$(tr -d '[:space:]' < "$path/VERSION")"
    if [[ -z "$actual" || "$actual" != "$expected" ]]; then
      printf 'install.sh: ERROR: %s development payload version %s does not match checkout version %s.\n' \
        "$label" "$actual" "$expected" >&2
      return 1
    fi
    return 0
  fi
  if ! release_python_available; then
    standalone_release_version payload "$path/VERSION" "$expected" "$label" "$candidate_mode"
    return $?
  fi
  release_python - "$path/VERSION" "$expected" "$label" "$candidate_mode" <<'PY'
import sys
from pathlib import Path

actual = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
if sys.argv[4] == "development":
    if not actual or actual != sys.argv[2]:
        raise SystemExit(
            f"install.sh: ERROR: {sys.argv[3]} development payload version {actual!r} "
            f"does not match checkout version {sys.argv[2]!r}."
        )
    raise SystemExit(0)
from z_harness_cli.release import parse_release_candidate
try:
    actual_candidate = parse_release_candidate(actual)
    expected_candidate = parse_release_candidate(sys.argv[2])
except ValueError as exc:
    raise SystemExit(f"install.sh: ERROR: {sys.argv[3]} version is invalid: {exc}")
if actual_candidate != expected_candidate or actual != actual_candidate.plugin_version:
    raise SystemExit(
        f"install.sh: ERROR: {sys.argv[3]} payload version {actual!r} "
        f"does not match candidate {expected_candidate.plugin_version!r}."
    )
PY
}

transaction_verify_cli_version() {
  local expected="$1"
  local launcher="${Z_HARNESS_TRANSACTION_CLI_LAUNCHER:-}"
  [[ -n "${Z_HARNESS_TRANSACTION_CLI_WHEEL:-}" ]] || return 0
  [[ -n "$launcher" && -x "$launcher" ]] || {
    printf 'install.sh: ERROR: updated CLI launcher is unavailable for coherence verification.\n' >&2
    return 1
  }
  local actual
  actual="$("$launcher" --version 2>/dev/null | awk '{print $NF}' | tail -1)"
  if ! release_python_available; then
    standalone_release_version compatible "$expected" "$actual"
    return $?
  fi
  release_python - "$expected" "$actual" <<'PY'
import sys
from z_harness_cli.release import parse_release_candidate
try:
    compatible = parse_release_candidate(sys.argv[1]) == parse_release_candidate(sys.argv[2])
except ValueError:
    compatible = False
if not compatible:
    raise SystemExit(
        f"install.sh: ERROR: CLI version {sys.argv[2]!r} is not compatible with candidate {sys.argv[1]!r}."
    )
PY
}

run_lifecycle_transaction() {
  local candidate_root="$1"
  local candidate_mode="${2:-release}"
  local candidate_version
  validate_candidate_version "$candidate_root" "$candidate_mode" || return $?
  candidate_version="$(tr -d '[:space:]' < "$candidate_root/VERSION")"
  if [[ "$GENERATE_EXPORTS" == "true" && ! -f "$candidate_root/scripts/generate-exports.py" ]]; then
    printf 'install.sh: ERROR: requested export generator is missing from the verified candidate.\n' >&2
    return 1
  fi

  # Validate every selected destination before inventory, backup creation, or
  # any host-visible mutation. Recovery repeats these checks from the journal.
  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    transaction_path_is_safe claude_payload "$CLAUDE_PLUGIN_LINK_PATH" || {
      printf 'install.sh: ERROR: Claude destination escapes its exact HOME root or has a symlinked parent.\n' >&2
      return 1
    }
    if [[ "$GENERATE_EXPORTS" == "true" ]]; then
      transaction_path_is_safe claude_exports "${CLAUDE_PLUGIN_LINK_PATH}/temp/exports" || {
        printf 'install.sh: ERROR: Claude export destination is unconfined.\n' >&2
        return 1
      }
    fi
  fi
  if [[ "$TARGET" == "codex" || "$TARGET" == "all" ]]; then
    transaction_path_is_safe codex_payload "$CODEX_PLUGIN_LINK_PATH" || {
      printf 'install.sh: ERROR: Codex destination escapes its exact HOME root or has a symlinked parent.\n' >&2
      return 1
    }
    transaction_path_is_safe marketplace "$CODEX_MARKETPLACE_PATH" || {
      printf 'install.sh: ERROR: Codex marketplace destination is unconfined.\n' >&2
      return 1
    }
    if [[ "$GENERATE_EXPORTS" == "true" ]]; then
      transaction_path_is_safe codex_exports "${CODEX_PLUGIN_LINK_PATH}/temp/exports" || {
        printf 'install.sh: ERROR: Codex export destination is unconfined.\n' >&2
        return 1
      }
    fi
  fi

  inventory_cli
  inventory_payload claude "$CLAUDE_PLUGIN_LINK_PATH"
  inventory_payload codex "$CODEX_PLUGIN_LINK_PATH"

  # All candidate and destination checks precede the durable journal and the
  # first host-visible mutation.
  case "$TARGET" in
    claude) check_can_replace_install_destination "$CLAUDE_PLUGIN_LINK_PATH" "Claude Code" ;;
    codex) check_can_replace_install_destination "$CODEX_PLUGIN_LINK_PATH" "Codex" ;;
    all)
      check_can_replace_install_destination "$CLAUDE_PLUGIN_LINK_PATH" "Claude Code"
      check_can_replace_install_destination "$CODEX_PLUGIN_LINK_PATH" "Codex"
      ;;
  esac
  if [[ -n "${Z_HARNESS_TRANSACTION_CLI_WHEEL:-}" ]]; then
    [[ -f "$Z_HARNESS_TRANSACTION_CLI_WHEEL" ]] || {
      printf 'install.sh: ERROR: staged CLI wheel does not exist: %s\n' "$Z_HARNESS_TRANSACTION_CLI_WHEEL" >&2
      return 1
    }
    [[ -n "${Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT:-}" ]] || {
      printf 'install.sh: ERROR: CLI transaction requires its tool root.\n' >&2
      return 1
    }
    transaction_path_is_safe cli_tool "$Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT" || {
      printf 'install.sh: ERROR: CLI tool root is outside the supported HOME uv tool location.\n' >&2
      return 1
    }
    if [[ -n "${Z_HARNESS_TRANSACTION_CLI_LAUNCHER:-}" ]]; then
      transaction_path_is_safe cli_launcher_main "$Z_HARNESS_TRANSACTION_CLI_LAUNCHER" || {
        printf 'install.sh: ERROR: CLI launcher path is outside HOME.\n' >&2
        return 1
      }
    fi
    if [[ -n "${Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH:-}" ]]; then
      transaction_path_is_safe cli_launcher_zh "$Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH" || {
        printf 'install.sh: ERROR: zh launcher path is outside HOME.\n' >&2
        return 1
      }
    fi
    command -v uv >/dev/null 2>&1 || {
      printf 'install.sh: ERROR: uv is required for a CLI transaction.\n' >&2
      return 1
    }
  fi
  if [[ "$TARGET" == "codex" || "$TARGET" == "all" ]]; then
    if [[ -f "$CODEX_MARKETPLACE_PATH" ]]; then
      python3 - "$CODEX_MARKETPLACE_PATH" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(data, dict) or data.get("name") != "personal":
    raise SystemExit(
        f"install.sh: ERROR: {path} must be a personal marketplace JSON object"
    )
if "plugins" in data and not isinstance(data["plugins"], list):
    raise SystemExit(f"install.sh: ERROR: {path} plugins must be an array")
PY
    fi
  fi

  acquire_transaction_lock || return $?
  recover_lifecycle_transaction || return $?
  mkdir "$TRANSACTION_DIR" || return $?
  atomic_text_write "$TRANSACTION_STATE" "prepared" || return $?
  atomic_text_write "${TRANSACTION_DIR}/candidate.version" "$candidate_version" || return $?
  atomic_text_write "${TRANSACTION_DIR}/selected" "$TARGET" || return $?

  # Persist every selected component's reversible pre-state before mutation
  # zero. Backups remain transaction-owned until coherence commits.
  local preparation_failed=0
  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    transaction_backup_path claude_payload "$CLAUDE_PLUGIN_LINK_PATH" || preparation_failed=$?
    if [[ "$GENERATE_EXPORTS" == "true" ]]; then
      if [[ "$preparation_failed" -eq 0 ]]; then
        transaction_backup_path claude_exports "${CLAUDE_PLUGIN_LINK_PATH}/temp/exports" || preparation_failed=$?
      fi
    fi
  fi
  if [[ "$preparation_failed" -eq 0 && ( "$TARGET" == "codex" || "$TARGET" == "all" ) ]]; then
    transaction_backup_path codex_payload "$CODEX_PLUGIN_LINK_PATH" || preparation_failed=$?
    if [[ "$preparation_failed" -eq 0 ]]; then
      transaction_backup_path marketplace "$CODEX_MARKETPLACE_PATH" || preparation_failed=$?
    fi
    if [[ "$GENERATE_EXPORTS" == "true" ]]; then
      if [[ "$preparation_failed" -eq 0 ]]; then
        transaction_backup_path codex_exports "${CODEX_PLUGIN_LINK_PATH}/temp/exports" || preparation_failed=$?
      fi
    fi
    if [[ "$preparation_failed" -eq 0 ]]; then
      local registration_status=0
      transaction_registration_present || registration_status=$?
      if [[ "$registration_status" -eq 0 ]]; then
        atomic_text_write "${TRANSACTION_DIR}/registration.present" "true" || preparation_failed=$?
      elif [[ "$registration_status" -eq 1 ]]; then
        atomic_text_write "${TRANSACTION_DIR}/registration.absent" "true" || preparation_failed=$?
      else
        printf 'install.sh: ERROR: could not inventory Codex registration state.\n' >&2
        preparation_failed=1
      fi
    fi
  fi
  if [[ "$preparation_failed" -eq 0 ]]; then
    transaction_prepare_cli_backup || preparation_failed=$?
  fi
  if [[ "$preparation_failed" -ne 0 ]]; then
    printf 'install.sh: ERROR: could not persist complete transaction pre-state.\n' >&2
    rollback_lifecycle_transaction
    return "$preparation_failed"
  fi
  atomic_text_write "$TRANSACTION_STATE" "applying" || return $?

  local failed=0
  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    transaction_replace_payload claude_payload "$candidate_root" "$CLAUDE_PLUGIN_LINK_PATH" claude || failed=$?
  fi
  if [[ "$failed" -eq 0 && ( "$TARGET" == "codex" || "$TARGET" == "all" ) ]]; then
    transaction_replace_payload codex_payload "$candidate_root" "$CODEX_PLUGIN_LINK_PATH" codex || failed=$?
  fi
  if [[ "$failed" -eq 0 && ( "$TARGET" == "codex" || "$TARGET" == "all" ) ]]; then
    atomic_text_write "${TRANSACTION_DIR}/marketplace.mutation" "started" || failed=$?
    if [[ "$failed" -eq 0 ]]; then write_codex_marketplace || failed=$?; fi
    if [[ "$failed" -eq 0 ]]; then transaction_fault_after marketplace.codex || failed=$?; fi
  fi
  if [[ "$failed" -eq 0 && ( "$TARGET" == "codex" || "$TARGET" == "all" ) ]] \
    && command -v codex >/dev/null 2>&1; then
    atomic_text_write "${TRANSACTION_DIR}/registration.attempted" "true" || failed=$?
    if [[ "$failed" -eq 0 ]]; then
      codex plugin add "${CODEX_PLUGIN_NAME}@${CODEX_MARKETPLACE_NAME}" || failed=$?
    fi
    if [[ "$failed" -eq 0 ]]; then
      local registration_status=0
      transaction_registration_present || registration_status=$?
      if [[ "$registration_status" -eq 0 ]]; then
        if [[ -f "${TRANSACTION_DIR}/registration.absent" ]]; then
          atomic_text_write "${TRANSACTION_DIR}/registration.added" "true" || failed=$?
        fi
      elif [[ "$registration_status" -eq 1 ]]; then
        printf 'install.sh: ERROR: Codex registration command returned success but registration is absent.\n' >&2
        failed=1
      else
        printf 'install.sh: ERROR: Codex registration verification failed.\n' >&2
        atomic_text_write "${TRANSACTION_DIR}/registration.uncertain" "true" || true
        failed=1
      fi
    fi
    if [[ "$failed" -eq 0 ]]; then transaction_fault_after registration.codex || failed=$?; fi
  fi
  if [[ "$failed" -eq 0 && "$GENERATE_EXPORTS" == "true" ]]; then
    if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
      transaction_generate_exports claude_exports "$CLAUDE_PLUGIN_LINK_PATH" claude || failed=$?
    fi
    if [[ "$failed" -eq 0 && ( "$TARGET" == "codex" || "$TARGET" == "all" ) ]]; then
      transaction_generate_exports codex_exports "$CODEX_PLUGIN_LINK_PATH" codex || failed=$?
    fi
  fi
  if [[ "$failed" -eq 0 ]]; then transaction_replace_cli || failed=$?; fi

  if [[ "$failed" -eq 0 && ( "$TARGET" == "claude" || "$TARGET" == "all" ) ]]; then
    transaction_verify_payload_version "$CLAUDE_PLUGIN_LINK_PATH" "$candidate_version" claude "$candidate_mode" || failed=$?
  fi
  if [[ "$failed" -eq 0 && ( "$TARGET" == "codex" || "$TARGET" == "all" ) ]]; then
    transaction_verify_payload_version "$CODEX_PLUGIN_LINK_PATH" "$candidate_version" codex "$candidate_mode" || failed=$?
  fi
  if [[ "$failed" -eq 0 ]]; then transaction_verify_cli_version "$candidate_version" || failed=$?; fi
  if [[ "$failed" -eq 0 ]]; then transaction_fault_after coherence || failed=$?; fi

  if [[ "$failed" -ne 0 ]]; then
    rollback_lifecycle_transaction
    return "$failed"
  fi
  if ! atomic_text_write "$TRANSACTION_STATE" "committed"; then
    rollback_lifecycle_transaction
    return 1
  fi
  rm -rf "$TRANSACTION_DIR" || return $?
  printf 'install.sh: lifecycle transaction committed at version %s\n' "$candidate_version"
  if [[ "$TARGET" == "claude" || "$TARGET" == "all" ]]; then
    printf 'z-harness installed for Claude Code.\n'
  fi
  if [[ "$TARGET" == "codex" || "$TARGET" == "all" ]]; then
    printf 'z-harness installed for Codex.\n'
  fi
  printf 'To update later, reinstall from the audited release manifest/tarball (for example: z-harness install --target=%s --force).\n' "$TARGET"
}

install_transaction_from_tarball() {
  local location="$1"
  if ! stage_tarball_payload "$location" "selected host"; then
    return 1
  fi
  local tmp_dir="$STAGED_TARBALL_TMP_DIR"
  local staged_source="$STAGED_TARBALL_SOURCE"
  local second_tmp_dir=""
  if [[ "$TARGET" == "all" ]]; then
    if ! stage_tarball_payload "$location" "Codex"; then
      rm -rf "$tmp_dir"
      return 1
    fi
    second_tmp_dir="$STAGED_TARBALL_TMP_DIR"
  fi
  local result=0
  run_lifecycle_transaction "$staged_source" || result=$?
  rm -rf "$tmp_dir"
  if [[ -n "$second_tmp_dir" ]]; then rm -rf "$second_tmp_dir"; fi
  return "$result"
}

# Main dispatch
main_result=0
if [[ -z "$TARBALL_URL" ]] \
  && [[ "$TARGET" == "codex" || "$TARGET" == "all" ]] \
  && [[ ! -f ".codex-plugin/plugin.json" ]] \
  && is_repo_clone; then
  if ! bootstrap_codex_source_manifest; then
    printf 'install.sh: ERROR: failed to bootstrap the Codex source manifest.\n' >&2
    release_transaction_lock
    exit 1
  fi
fi
if [[ -n "$TARBALL_URL" ]]; then
  install_transaction_from_tarball "$TARBALL_URL" || main_result=$?
elif { [[ "$TARGET" == "claude" ]] && is_repo_clone; } \
  || { [[ "$TARGET" == "codex" ]] && is_codex_plugin_source; } \
  || { [[ "$TARGET" == "all" ]] && is_repo_clone && is_codex_plugin_source; }; then
  printf 'install.sh: detected repo clone at %s\n' "$(pwd)"
  run_lifecycle_transaction "$(pwd)" development || main_result=$?
elif [[ -n "${Z_HARNESS_RELEASE_URL:-}" ]]; then
  printf 'install.sh: no repo clone detected; using Z_HARNESS_RELEASE_URL\n'
  install_transaction_from_tarball "$Z_HARNESS_RELEASE_URL" || main_result=$?
else
  printf 'install.sh: ERROR: not a compatible repo clone for --target=%s.\n' "$TARGET" >&2
  printf '  Claude needs .git + skills/ + agents/ + runtime/.\n' >&2
  printf '  Codex needs .git + skills/ and a tracked Claude version stamp (the Codex manifest is generated).\n' >&2
  printf '  To install from tarball: bash install.sh --target=%s --tarball=<url>\n' "$TARGET" >&2
  printf '  Or set Z_HARNESS_RELEASE_URL and re-run.\n' >&2
  main_result=1
fi

release_transaction_lock
exit "$main_result"
