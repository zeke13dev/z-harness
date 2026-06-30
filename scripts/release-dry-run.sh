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
STAGE_DIR="$WORK_DIR/release-stage"
HOME_DIR="$WORK_DIR/home"
VENV_DIR="$WORK_DIR/venv"
CODEX_EXPORT_DIR="$REPO_ROOT/temp/release-dry-run-export-codex"
OMP_EXPORT_DIR="$REPO_ROOT/temp/release-dry-run-export-omp"
MANIFEST="$WORK_DIR/latest.json"

rm -rf "$WORK_DIR" "$CODEX_EXPORT_DIR" "$OMP_EXPORT_DIR"
cleanup() {
  rm -rf "$CODEX_EXPORT_DIR" "$OMP_EXPORT_DIR"
}
trap cleanup EXIT
mkdir -p "$DIST_DIR" "$HOME_DIR"

cd "$REPO_ROOT"

printf 'release-dry-run: staging prod release surface\n'
python3 scripts/stage-release-surface.py --repo-root "$REPO_ROOT" --out "$STAGE_DIR" --keep-git >/tmp/z-harness-release-dry-run-stage.txt

printf 'release-dry-run: building staged prod wheel for %s\n' "$TAG"
(
  cd "$STAGE_DIR"
  if command -v uv >/dev/null 2>&1; then
    uv run --with build python -m build --wheel --outdir "$DIST_DIR"
  else
    python3 -m build --wheel --outdir "$DIST_DIR"
  fi
)

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
bash scripts/audit-tarball.sh "$TARBALL_PATH"
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

echo 'release-dry-run: running degraded Codex export-only smoke'
rm -rf "$CODEX_EXPORT_DIR"
"$VENV_DIR/bin/z-harness" export --host codex --surface prod --out "$CODEX_EXPORT_DIR" --force >/tmp/z-harness-release-dry-run-export-codex.log
test -f "$CODEX_EXPORT_DIR/.codex-plugin/plugin.json"
test ! -d "$CODEX_EXPORT_DIR/skills/z-research"

echo 'release-dry-run: running blocking OMP prod export smoke'
"$VENV_DIR/bin/python" scripts/omp-prod-export-smoke.py \
  --cli "$VENV_DIR/bin/z-harness" \
  --out "$OMP_EXPORT_DIR"

echo 'release-dry-run: running MCP prod tool-list smoke'
(
  cd "$WORK_DIR"
  Z_HARNESS_RELEASE_SURFACE=prod "$VENV_DIR/bin/python" \
    -m z_harness_cli.mcp_prod_tool_list_smoke \
    --repo-root "$REPO_ROOT"
)

printf 'release-dry-run: validating release workflow metadata for %s\n' "$TAG"
python3 - "$MANIFEST" "$VERSION" <<'PY'
import pathlib
import sys

from z_harness_cli.release import parse_manifest

parsed = parse_manifest(open(sys.argv[1]).read(), allow_file_urls=True)
assert parsed.version == sys.argv[2], (parsed.version, sys.argv[2])
assert parsed.sha256 and parsed.plugin_tarball_sha256

workflow = pathlib.Path(".github/workflows/release.yml").read_text(encoding="utf-8")
makefile = pathlib.Path("Makefile").read_text(encoding="utf-8")
release_index = workflow.index("Create GitHub Release")
before_release = workflow[:release_index]
required_workflow_gates = {
    "make release-verify": "full unit/shell/dry-run/checksum gate target",
    "scripts/omp-prod-export-smoke.py": "blocking OMP prod export smoke",
    "Z_HARNESS_RELEASE_SURFACE=prod /tmp/z-harness-wheel-smoke/bin/python": "MCP prod tool-list smoke",
    "-m z_harness_cli.mcp_prod_tool_list_smoke": "installed-wheel MCP prod smoke module",
    "--repo-root \"$GITHUB_WORKSPACE\"": "MCP prod smoke checkout-import guard",
    "bash scripts/audit-tarball.sh": "tarball audit",
    "python3 -m venv /tmp/z-harness-wheel-smoke": "prod wheel smoke",
}
missing = [label for token, label in required_workflow_gates.items() if token not in before_release]
assert not missing, f"release workflow missing gates before publication: {missing}"
inline_mcp_import = "from z_harness_cli.mcp.server " "import"
assert inline_mcp_import not in before_release, "MCP prod smoke must not inline repo-root import"
assert "release-verify: test test-sh" in makefile, "release-verify must depend on unit and shell tests"
assert "tests/test_install_sh_integrity.py" in makefile, "release-verify must include checksum/atomic install regressions"
assert "bash scripts/release-dry-run.sh" in makefile, "release-verify must include release dry-run"
assert "action-gh-release" in workflow[release_index:], "release publication step missing after gates"
PY

printf 'release-dry-run: OK\n'
printf '  work_dir=%s\n' "$WORK_DIR"
printf '  wheel=%s\n' "$WHEEL_PATH"
printf '  tarball=%s\n' "$TARBALL_PATH"
printf '  manifest=%s\n' "$MANIFEST"
printf '  plugin=%s\n' "$HOME_DIR/.claude/plugins/z-harness@zeke-tools"
