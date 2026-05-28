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

echo "==> preflight: AskUserQuestion callsite audit (--strict; unregistered callsites are advisory)"
# Run --strict so CI exercises the strict path locally.
# Exit 1 (unregistered callsites) is advisory — surface as warning but do not fail.
# Exit 2 (usage error) or 3+ (hard error) propagate as failures.
# Use 'if' guard to prevent set -e from aborting on exit 1.
if bash "$REPO_ROOT/scripts/lint-askuser.sh" --strict; then
  _lint_ec=0
else
  _lint_ec=$?
fi
if [[ $_lint_ec -eq 1 ]]; then
  echo "WARNING: unregistered AskUserQuestion callsites found (known v1 limitation, fail-OPEN)." >&2
elif [[ $_lint_ec -ne 0 ]]; then
  echo "ERROR: lint-askuser.sh exited with code $_lint_ec (hard failure)." >&2
  exit $_lint_ec
fi
echo ""
echo "Preflight complete."
