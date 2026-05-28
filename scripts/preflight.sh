#!/usr/bin/env bash
# preflight.sh — local checks to run before committing or opening a PR
#
# Usage:
#   bash scripts/preflight.sh
#
# Exits 0 if all checks pass or produce only advisory warnings.
# Exits non-zero only on hard failures.
#
# NOTE: The AskUserQuestion lint below is documentation/audit tooling, NOT
# runtime enforcement. Unregistered callsites under Z_HARNESS_NO_ASK=halt
# still block until the user responds. This lint makes the gap visible;
# it does not close it. See docs/human/overnight-run.md for v2 plans.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> preflight: AskUserQuestion callsite audit (advisory)"
# Non-strict: exits 0 even with unregistered callsites; surfaces them as warnings.
bash "$REPO_ROOT/scripts/lint-askuser.sh" || true
echo ""
echo "Preflight complete."
