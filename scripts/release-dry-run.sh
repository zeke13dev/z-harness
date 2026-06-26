#!/usr/bin/env bash
# release-dry-run.sh — non-publishing beta release smoke.
# Builds local artifacts, renders a manifest, installs from that manifest, and
# verifies plugin install/export paths without creating GitHub tags or releases.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TAG="${1:-v0.1.0-beta.1}"
VERSION="${TAG#v}"
WORK_DIR="${TMPDIR:-/tmp}/z-harness-release-dry-run"
DIST_DIR="$WORK_DIR/dist"
HOME_DIR="$WORK_DIR/home"
VENV_DIR="$WORK_DIR/venv"
EXPORT_DIR="$REPO_ROOT/temp/release-dry-run-export-codex"
MANIFEST="$WORK_DIR/latest.json"

rm -rf "$WORK_DIR" "$EXPORT_DIR"
cleanup() {
  rm -rf "$EXPORT_DIR"
}
trap cleanup EXIT
mkdir -p "$DIST_DIR" "$HOME_DIR"

cd "$REPO_ROOT"

printf 'release-dry-run: building wheel for %s\n' "$TAG"
if command -v uv >/dev/null 2>&1; then
  uv run --with build python -m build --wheel --outdir "$DIST_DIR"
else
  python3 -m build --wheel --outdir "$DIST_DIR"
fi

WHEEL_COUNT="$(find "$DIST_DIR" -maxdepth 1 -name '*.whl' | wc -l | tr -d ' ')"
if [[ "$WHEEL_COUNT" -ne 1 ]]; then
  printf 'release-dry-run: ERROR expected one wheel, found %s\n' "$WHEEL_COUNT" >&2
  exit 1
fi
WHEEL_PATH="$(find "$DIST_DIR" -maxdepth 1 -name '*.whl' -print -quit)"
WHEEL_SHA="$(python3 - "$WHEEL_PATH" <<'PY'
import hashlib, sys
h=hashlib.sha256()
with open(sys.argv[1], 'rb') as f:
    for chunk in iter(lambda: f.read(65536), b''):
        h.update(chunk)
print(h.hexdigest())
PY
)"

printf 'release-dry-run: building audited plugin tarball\n'
rm -rf dist
Z_HARNESS_RELEASE_SURFACE=prod bash scripts/bundle-plugin.sh
TARBALL_COUNT="$(find dist -maxdepth 1 -name 'z-harness-*.tar.gz' | wc -l | tr -d ' ')"
if [[ "$TARBALL_COUNT" -ne 1 ]]; then
  printf 'release-dry-run: ERROR expected one tarball, found %s\n' "$TARBALL_COUNT" >&2
  exit 1
fi
TARBALL_SRC="$(find dist -maxdepth 1 -name 'z-harness-*.tar.gz' -print -quit)"
TARBALL_PATH="$DIST_DIR/$(basename "$TARBALL_SRC")"
cp "$TARBALL_SRC" "$TARBALL_PATH"
TARBALL_SHA="$(python3 - "$TARBALL_PATH" <<'PY'
import hashlib, sys
h=hashlib.sha256()
with open(sys.argv[1], 'rb') as f:
    for chunk in iter(lambda: f.read(65536), b''):
        h.update(chunk)
print(h.hexdigest())
PY
)"

printf 'release-dry-run: rendering manifest\n'
python3 - "$MANIFEST" "$VERSION" "$WHEEL_PATH" "$WHEEL_SHA" "$TARBALL_PATH" "$TARBALL_SHA" <<'PY'
import json, pathlib, sys
manifest, version, wheel, wheel_sha, tarball, tarball_sha = sys.argv[1:]
data = {
    "schema_version": 1,
    "version": version,
    "wheel_url": pathlib.Path(wheel).resolve().as_uri(),
    "sha256": wheel_sha,
    "plugin_tarball_url": pathlib.Path(tarball).resolve().as_uri(),
    "plugin_tarball_sha256": tarball_sha,
    "cli_schema_version": 1,
    "telemetry_schema_version": 1,
    "min_supported_version": "0.1.0",
}
pathlib.Path(manifest).write_text(json.dumps(data, indent=2) + "\n")
PY
python3 - "$MANIFEST" <<'PY'
import sys
from z_harness_cli.release import parse_manifest
raw=open(sys.argv[1]).read()
parsed=parse_manifest(raw, allow_file_urls=True)
assert parsed.plugin_tarball_url, 'plugin_tarball_url missing'
print('release-dry-run: manifest validated')
PY

printf 'release-dry-run: installing wheel in isolated venv\n'
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install "$WHEEL_PATH" >/tmp/z-harness-release-dry-run-pip.log
"$VENV_DIR/bin/z-harness" --help >/tmp/z-harness-release-dry-run-help.txt
"$VENV_DIR/bin/z-harness" --version

printf 'release-dry-run: installing plugin from manifest-backed tarball\n'
HOME="$HOME_DIR" \
Z_HARNESS_RELEASE_URL="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve().as_uri())' "$MANIFEST")" \
Z_HARNESS_ALLOW_FILE_RELEASE_URLS=1 \
"$VENV_DIR/bin/z-harness" install --target=claude --force

test -f "$HOME_DIR/.claude/plugins/z-harness@zeke-tools/install.sh"

echo 'release-dry-run: running export smoke'
rm -rf "$EXPORT_DIR"
"$VENV_DIR/bin/z-harness" export --host codex --surface prod --out "$EXPORT_DIR" --force >/tmp/z-harness-release-dry-run-export.log
test -f "$EXPORT_DIR/.codex-plugin/plugin.json"
test ! -d "$EXPORT_DIR/skills/z-research"

printf 'release-dry-run: validating release workflow metadata for %s\n' "$TAG"
python3 - "$MANIFEST" "$VERSION" <<'PY'
import sys
from z_harness_cli.release import parse_manifest
parsed=parse_manifest(open(sys.argv[1]).read(), allow_file_urls=True)
assert parsed.version == sys.argv[2], (parsed.version, sys.argv[2])
assert parsed.sha256 and parsed.plugin_tarball_sha256
PY

printf 'release-dry-run: OK\n'
printf '  work_dir=%s\n' "$WORK_DIR"
printf '  wheel=%s\n' "$WHEEL_PATH"
printf '  tarball=%s\n' "$TARBALL_PATH"
printf '  manifest=%s\n' "$MANIFEST"
printf '  plugin=%s\n' "$HOME_DIR/.claude/plugins/z-harness@zeke-tools"
