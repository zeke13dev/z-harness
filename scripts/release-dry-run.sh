#!/usr/bin/env bash
# release-dry-run.sh — non-publishing release-candidate smoke.
# Builds one verified output and executes its exact public bootstrap without
# creating GitHub tags or releases. Cross-host dependency closure is gated later.
#
# Usage: bash scripts/release-dry-run.sh CANDIDATE
# Example: bash scripts/release-dry-run.sh v0.9.0-beta.2

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RAW_CANDIDATE="${Z_HARNESS_RELEASE_CANDIDATE:-${1:-}}"
if [[ -z "$RAW_CANDIDATE" ]]; then
  printf 'usage: %s CANDIDATE\n' "$0" >&2
  exit 2
fi
CANDIDATE_IDENTITIES="$(python3 - "$RAW_CANDIDATE" <<'PY'
import sys
from z_harness_cli.release import parse_release_candidate

try:
    candidate = parse_release_candidate(sys.argv[1])
except ValueError as exc:
    raise SystemExit(f"release-dry-run: ERROR invalid release candidate: {exc}") from exc
print(f"{candidate.git_tag}\t{candidate.plugin_version}")
PY
)"
IFS=$'\t' read -r TAG VERSION <<< "$CANDIDATE_IDENTITIES"
CANDIDATE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
WORK_DIR="${TMPDIR:-/tmp}/z-harness-release-dry-run"
DIST_DIR="${Z_HARNESS_RELEASE_OUTPUT:-$WORK_DIR/dist}"
HOME_DIR="$WORK_DIR/home"
VENV_DIR="$WORK_DIR/venv"
FAKE_BIN="$WORK_DIR/fake-bin"
MANIFEST="$WORK_DIR/latest.json"

rm -rf "$WORK_DIR"
mkdir -p "$DIST_DIR" "$HOME_DIR" "$FAKE_BIN"

cd "$REPO_ROOT"

printf 'release-dry-run: assembling verified release output for %s\n' "$TAG"
if [[ -z "${Z_HARNESS_RELEASE_OUTPUT:-}" ]]; then
  python3 scripts/assemble-release.py \
    --repo-root "$REPO_ROOT" \
    --out "$DIST_DIR" \
    --candidate-version "$VERSION" \
    --candidate-commit "$CANDIDATE_COMMIT" \
    --artifact-base-url "https://release-smoke.invalid/$TAG"
else
  printf 'release-dry-run: consuming preassembled output at %s\n' "$DIST_DIR"
fi

WHEEL_COUNT="$(find "$DIST_DIR" -maxdepth 1 -name '*.whl' | wc -l | tr -d ' ')"
if [[ "$WHEEL_COUNT" -ne 1 ]]; then
  printf 'release-dry-run: ERROR expected one wheel, found %s\n' "$WHEEL_COUNT" >&2
  exit 1
fi
WHEEL_PATH="$(find "$DIST_DIR" -maxdepth 1 -name '*.whl' -print -quit)"
TARBALL_COUNT="$(find "$DIST_DIR" -maxdepth 1 -name 'z-harness-*.tar.gz' | wc -l | tr -d ' ')"
if [[ "$TARBALL_COUNT" -ne 1 ]]; then
  printf 'release-dry-run: ERROR expected one tarball, found %s\n' "$TARBALL_COUNT" >&2
  exit 1
fi
TARBALL_PATH="$(find "$DIST_DIR" -maxdepth 1 -name 'z-harness-*.tar.gz' -print -quit)"
MANIFEST="$DIST_DIR/latest.json"
python3 - "$DIST_DIR" "$VERSION" <<'PY'
import sys
from z_harness_cli.release import verify_release_artifacts

verify_release_artifacts(sys.argv[1], sys.argv[2])
print('release-dry-run: candidate artifacts verified')
PY

printf 'release-dry-run: executing staged public install.sh from local manifest fixture\n'
cat >"$FAKE_BIN/curl" <<EOF
#!/usr/bin/env bash
set -euo pipefail
dest=""
url=""
while [[ \$# -gt 0 ]]; do
  case "\$1" in
    -o) dest="\$2"; shift 2 ;;
    -*) shift ;;
    *) url="\$1"; shift ;;
  esac
done
case "\$url" in
  *latest.json) cp "$MANIFEST" "\$dest" ;;
  *.whl) cp "$WHEEL_PATH" "\$dest" ;;
  *) exit 1 ;;
esac
EOF
cat >"$FAKE_BIN/uv" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${1:-}" == "--version" ]]; then printf 'uv release-smoke\n'; exit 0; fi
test "\${1:-}" = tool
test "\${2:-}" = install
test -f "\${4:-}"
printf 'public bootstrap invoked\n' >"$WORK_DIR/public-bootstrap.ok"
EOF
chmod +x "$FAKE_BIN/curl" "$FAKE_BIN/uv"
HOME="$HOME_DIR" PATH="$FAKE_BIN:$PATH" Z_HARNESS_RELEASE_URL="https://release-smoke.invalid/$TAG/latest.json" \
  sh "$DIST_DIR/install.sh"
test -f "$WORK_DIR/public-bootstrap.ok"

printf 'release-dry-run: installing wheel in isolated venv\n'
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install "$WHEEL_PATH" >/tmp/z-harness-release-dry-run-pip.log
"$VENV_DIR/bin/z-harness" --help >/tmp/z-harness-release-dry-run-help.txt
"$VENV_DIR/bin/z-harness" --version

printf 'release-dry-run: OK\n'
printf '  work_dir=%s\n' "$WORK_DIR"
printf '  wheel=%s\n' "$WHEEL_PATH"
printf '  tarball=%s\n' "$TARBALL_PATH"
printf '  manifest=%s\n' "$MANIFEST"
