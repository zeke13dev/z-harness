#!/usr/bin/env bash
# bundle-plugin.sh — build a distributable z-harness tarball from a canonical stage
#
# Usage: bash scripts/bundle-plugin.sh --stage DIR --candidate-version VERSION --candidate-commit SHA
# Example: bash scripts/bundle-plugin.sh --stage /tmp/z-harness-release-stage --candidate-version 0.2.0-beta.1 --candidate-commit abc123
#
# Output: dist/z-harness-<version>.tar.gz
# The supplied stage must carry matching candidate metadata. After building,
# the script audits the output and deletes it on any violation.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ $# -ne 6 || "$1" != "--stage" || "$3" != "--candidate-version" || "$5" != "--candidate-commit" ]]; then
  printf 'usage: %s --stage DIR --candidate-version VERSION --candidate-commit SHA\n' "$0" >&2
  exit 2
fi

STAGE_DIR="$2"
VERSION="$4"
CANDIDATE_COMMIT="$6"
MANIFEST="$STAGE_DIR/.codex-plugin/plugin.json"

if [[ ! -d "$STAGE_DIR" || ! -f "$MANIFEST" ]]; then
  printf 'bundle-plugin.sh: ERROR: canonical stage or plugin metadata is missing\n' >&2
  exit 1
fi

python3 - "$MANIFEST" "$VERSION" "$CANDIDATE_COMMIT" <<'PY'
import json
import pathlib
import sys
from z_harness_cli.release import parse_release_candidate

manifest_path, version, commit = sys.argv[1:]
try:
    candidate = parse_release_candidate(version)
except ValueError as exc:
    raise SystemExit(f"bundle-plugin.sh: ERROR: invalid release candidate: {exc}") from exc
manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding="utf-8"))
try:
    manifest_candidate = parse_release_candidate(manifest.get("version", ""))
except ValueError as exc:
    raise SystemExit("bundle-plugin.sh: ERROR: canonical stage candidate identity mismatch") from exc
if manifest_candidate != candidate or manifest.get("candidate_commit") != commit:
    raise SystemExit("bundle-plugin.sh: ERROR: canonical stage candidate identity mismatch")
PY

DIST_DIR="$REPO_ROOT/dist"
mkdir -p "$DIST_DIR"

OUTPUT="$DIST_DIR/z-harness-${VERSION}.tar.gz"

printf 'bundle-plugin.sh: building %s\n' "$OUTPUT"

python3 - "$STAGE_DIR" "$OUTPUT" <<'PY'
import gzip
import pathlib
import sys
import tarfile

stage = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
paths = sorted(stage.rglob("*"), key=lambda path: path.relative_to(stage).as_posix())

with output.open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path in paths:
                relative = path.relative_to(stage).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                info.mode = 0o755 if path.is_dir() or info.mode & 0o111 else 0o644
                info.pax_headers = {}
                if path.is_file():
                    with path.open("rb") as source:
                        archive.addfile(info, source)
                else:
                    archive.addfile(info)
PY

printf 'bundle-plugin.sh: tarball created at %s\n' "$OUTPUT"
printf 'bundle-plugin.sh: running audit...\n'

SURFACE="${Z_HARNESS_RELEASE_SURFACE:-dev}"
if [[ "$SURFACE" == "prod" || "$SURFACE" == "production" ]]; then
  # The source ownership contract deliberately excludes generated files. Audit
  # every source entry against it, allowing only the stager-owned metadata.
  if ! tar -tzf "$OUTPUT" \
    | grep -Ev '^\.codex-plugin/?$|^\.codex-plugin/plugin\.json$|^\./\.codex-plugin/?$|^\./\.codex-plugin/plugin\.json$' \
    | python3 -m z_harness_cli.release_surface audit-listing --surface prod; then
    printf 'bundle-plugin.sh: FAIL — staged source is outside the prod ownership contract\n' >&2
    rm -f "$OUTPUT"
    exit 1
  fi
fi

if ! Z_HARNESS_RELEASE_SURFACE=dev bash "$SCRIPT_DIR/audit-tarball.sh" "$OUTPUT"; then
  printf 'bundle-plugin.sh: FAIL — audit violation; deleting tarball\n' >&2
  rm -f "$OUTPUT"
  exit 1
fi

printf 'bundle-plugin.sh: build complete — %s\n' "$OUTPUT"
