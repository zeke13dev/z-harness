#!/usr/bin/env bash
# Verify the triggering release tag against the fetched public branch.
# Usage: verify-release-provenance.sh <locked-python>
# Example: verify-release-provenance.sh .venv/bin/python

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: verify-release-provenance.sh <locked-python>" >&2
  exit 2
fi
if [[ -z "${GITHUB_REF_NAME:-}" || -z "${GITHUB_SHA:-}" ]]; then
  echo "verify-release-provenance.sh: GITHUB_REF_NAME and GITHUB_SHA are required" >&2
  exit 2
fi

PYTHON_BIN="$1"
CANDIDATE_VERSION="${GITHUB_REF_NAME#v}"

git fetch --force --no-tags origin \
  "+refs/heads/prod:refs/remotes/origin/prod" \
  "+refs/tags/${GITHUB_REF_NAME}:refs/tags/${GITHUB_REF_NAME}"
TAG_COMMIT="$(git rev-parse --verify "refs/tags/${GITHUB_REF_NAME}^{commit}")"
PROD_TIP="$(git rev-parse --verify "refs/remotes/origin/prod^{commit}")"

"$PYTHON_BIN" - \
  "$CANDIDATE_VERSION" "$GITHUB_REF_NAME" \
  "$TAG_COMMIT" "$GITHUB_SHA" "$PROD_TIP" <<'PY'
import sys

from z_harness_cli.release import verify_publication_provenance

verify_publication_provenance(*sys.argv[1:])
PY
