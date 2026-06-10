#!/usr/bin/env bash
# invariant-check.sh — CI-friendly invariant validation gate.
#
# Reads INVARIANTS.json + TESTS.md, runs the test suite, and exits non-zero
# on mandatory-invariant violations.
#
# Usage:
#   ./scripts/invariant-check.sh [--test-cmd <cmd>] [--repo-root <path>] [--full-chain]
#
# --full-chain: Also run full-chain tests (tests covering end-to-end composed paths).
#   When set, the script discovers full-chain test entries from TESTS.md (v2 only)
#   and runs them. Missing full-chain test files are skipped gracefully.
#
# Exit codes:
#   0 — all mandatory tests pass
#   1 — one or more mandatory tests failed (includes full-chain failures when --full-chain)
#   3 — coverage gap (uncovered blocker invariants in TESTS.md)
#   4 — I/O error (missing files, unparseable)
#
# Works standalone — does not require z-harness installed.
# Only needs: INVARIANTS.json, TESTS.md, and a test command.

set -euo pipefail

REPO_ROOT="${2:-$(cd "$(dirname "$0")/.." && pwd)}"
TEST_CMD="${TEST_CMD:-}"
FULL_CHAIN=0
INVARIANTS_FILE="${REPO_ROOT}/docs/INVARIANTS.json"
TESTS_FILE=""
TEST_RUNNER_JSON=""

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --test-cmd)
            TEST_CMD="$2"
            shift 2
            ;;
        --repo-root)
            REPO_ROOT="$2"
            INVARIANTS_FILE="${REPO_ROOT}/docs/INVARIANTS.json"
            shift 2
            ;;
        --tests-file)
            TESTS_FILE="$2"
            shift 2
            ;;
        --full-chain)
            FULL_CHAIN=1
            shift
            ;;
        *)
            # Assume it's a positional TESTS.md path
            if [[ -z "$TESTS_FILE" ]]; then
                TESTS_FILE="$1"
            fi
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Discover TESTS.md and test-runner.json
# ---------------------------------------------------------------------------
if [[ -z "$TESTS_FILE" ]]; then
    # Auto-discover: look in z-harness/plans/*/ for the most recent TESTS.md
    TESTS_FILE="$(find "${REPO_ROOT}/z-harness/plans" "${REPO_ROOT}/plans" -name TESTS.md -type f 2>/dev/null | head -1)"
fi

if [[ -z "$TESTS_FILE" || ! -f "$TESTS_FILE" ]]; then
    echo "[invariant-check] No TESTS.md found. Nothing to check."
    exit 0
fi

TESTS_DIR="$(dirname "$TESTS_FILE")"
TEST_RUNNER_JSON="${TESTS_DIR}/test-runner.json"

# ---------------------------------------------------------------------------
# Resolve test command
# ---------------------------------------------------------------------------
if [[ -z "$TEST_CMD" ]]; then
    if [[ -f "$TEST_RUNNER_JSON" ]]; then
        TEST_CMD="$(python3 -c "
import json, sys
try:
    data = json.load(open('$TEST_RUNNER_JSON'))
    tmpl = data.get('cmd_template', '')
    if tmpl:
        # Replace placeholders with wildcards for suite run
        tmpl = tmpl.replace('{TARGET_FILE}', 'tests/').replace('{TEST_NAME}', '')
        print(tmpl.strip())
except Exception as e:
    print('', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || true)"
    fi

    if [[ -z "$TEST_CMD" ]]; then
        # Guess: look for common test frameworks
        if [[ -f "${REPO_ROOT}/Cargo.toml" ]]; then
            TEST_CMD="cargo test"
        elif [[ -f "${REPO_ROOT}/pyproject.toml" ]] || [[ -f "${REPO_ROOT}/setup.py" ]]; then
            TEST_CMD="pytest tests/"
        elif [[ -f "${REPO_ROOT}/package.json" ]]; then
            TEST_CMD="pnpm test"
        else
            echo "[invariant-check] WARNING: could not determine test command. Set --test-cmd or create test-runner.json."
            exit 0
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Parse TESTS.md frontmatter
# ---------------------------------------------------------------------------
echo "[invariant-check] Reading ${TESTS_FILE}..."

# Extract version
VERSION="$(grep -m1 '^\*\*Version:\*\*' "$TESTS_FILE" 2>/dev/null | sed 's/.*Version:\*\* *//' | tr -d '[:space:]' || echo "1")"

# Extract covered and uncovered lists
COVERED_INVARIANTS="$(grep -m1 '^\*\*Covered invariants:\*\*' "$TESTS_FILE" 2>/dev/null | sed 's/.*Covered invariants:\*\* *//' | tr -d '[:space:]' || echo "")"
UNCOVERED_BLOCKERS="$(grep -m1 '^\*\*Uncovered invariants (blocker):\*\*' "$TESTS_FILE" 2>/dev/null | sed 's/.*Uncovered invariants (blocker):\*\* *//' | tr -d '[:space:]' || echo "")"
UNCOVERED_MAJORS="$(grep -m1 '^\*\*Uncovered invariants (major):\*\*' "$TESTS_FILE" 2>/dev/null | sed 's/.*Uncovered invariants (major):\*\* *//' | tr -d '[:space:]' || echo "")"

# ---------------------------------------------------------------------------
# Coverage gate — uncovered blockers
# ---------------------------------------------------------------------------
if [[ -n "$UNCOVERED_BLOCKERS" && "$UNCOVERED_BLOCKERS" != "none" ]]; then
    echo "[invariant-check] COVERAGE GAP: uncovered blocker invariants: $UNCOVERED_BLOCKERS"
    echo "[invariant-check] These invariants have no test coverage and are blockers. Add tests before proceeding."
    exit 3
fi

if [[ -n "$UNCOVERED_MAJORS" && "$UNCOVERED_MAJORS" != "none" ]]; then
    echo "[invariant-check] WARNING: uncovered major invariants: $UNCOVERED_MAJORS"
fi

# ---------------------------------------------------------------------------
# Run tests
# ---------------------------------------------------------------------------
echo "[invariant-check] Running: $TEST_CMD"

cd "$REPO_ROOT"

# Run the test suite and capture output
TEST_OUTPUT="$(mktemp -t invariant-check-output.XXXXXX)"
trap "rm -f '$TEST_OUTPUT'" EXIT

set +e
eval "$TEST_CMD" > "$TEST_OUTPUT" 2>&1
TEST_RC=$?
set -e

# ---------------------------------------------------------------------------
# Parse test results for TEST-NNN entries
# ---------------------------------------------------------------------------
if [[ "$VERSION" == "2" ]]; then
    # v2: extract TEST-NNN entries and check their results
    TEST_IDS="$(grep '^## TEST-' "$TESTS_FILE" 2>/dev/null | sed 's/^## *//' | sed 's/ .*//' || true)"

    FAILED_TESTS=""
    PASSED_TESTS=""

    for tid in $TEST_IDS; do
        # Look for the test ID in output (pytest: "TEST-001", cargo: "test_001")
        if grep -q "$tid" "$TEST_OUTPUT" 2>/dev/null; then
            if echo "$tid" | grep -q "FAILED\|failures" 2>/dev/null || grep -q "FAILED.*$tid\|$tid.*FAILED" "$TEST_OUTPUT" 2>/dev/null; then
                FAILED_TESTS="$FAILED_TESTS $tid"
            else
                PASSED_TESTS="$PASSED_TESTS $tid"
            fi
        fi
    done

    # Also check overall test exit code
    if [[ $TEST_RC -ne 0 ]]; then
        echo "[invariant-check] Test suite failed (exit $TEST_RC)."
        echo "[invariant-check] Test output:"
        tail -50 "$TEST_OUTPUT"

        # Check which invariants are affected
        if [[ -n "$COVERED_INVARIANTS" ]]; then
            echo "[invariant-check] Covered invariants: $COVERED_INVARIANTS"
            echo "[invariant-check] One or more mandatory tests failed — invariant violation detected."
        fi
        exit 1
    fi

    echo "[invariant-check] All per-task tests passed."

    # ---------------------------------------------------------------------------
    # Full-chain tests (only if --full-chain flag and v2 TESTS.md)
    # ---------------------------------------------------------------------------
    if [[ "$FULL_CHAIN" -eq 1 ]]; then
        echo "[invariant-check] Running full-chain tests..."

        FULL_CHAIN_IDS="$(awk '/^## TEST-/ { cur=\$2; layer="" }
            /^\*\*Layer:\*\*/ && /full-chain/ { print cur }' "$TESTS_FILE")"

        if [[ -z "$FULL_CHAIN_IDS" ]]; then
            echo "[invariant-check] No full-chain tests defined in TESTS.md."
        else
            FC_PASSED=0
            FC_FAILED=0
            FC_SKIPPED=0
            FC_LOG="$(mktemp -t invariant-check-fc.XXXXXX)"

            for tid in $FULL_CHAIN_IDS; do
                TARGET="$(awk -v id="$tid" '/^## /{cur=\$0; found=0} cur ~ id {found=1} found && /^\*\*Target file:\*\*/{print \$3; exit}' "$TESTS_FILE")"
                INV_ID="$(awk -v id="$tid" '/^## /{cur=\$0; found=0} cur ~ id {found=1} found && /^\*\*Invariant ID:\*\*/{print \$3; exit}' "$TESTS_FILE")"

                if [[ -z "$TARGET" ]] || [[ ! -f "$TARGET" ]]; then
                    echo "[SKIP] $tid — target file $TARGET not found (full-chain test not yet written)" | tee -a "$FC_LOG"
                    FC_SKIPPED=$((FC_SKIPPED+1))
                    continue
                fi

                CMD="$(echo "$TEST_CMD" | sed "s|{TARGET_FILE}|$TARGET|g; s|{TEST_NAME}|$tid|g")"
                if eval "$CMD" >> "$FC_LOG" 2>&1; then
                    echo "[PASS] $tid (invariant $INV_ID)" | tee -a "$FC_LOG"
                    FC_PASSED=$((FC_PASSED+1))
                else
                    echo "[FAIL] $tid (invariant $INV_ID) — full-chain invariant violation" | tee -a "$FC_LOG"
                    FC_FAILED=$((FC_FAILED+1))
                fi
            done

            echo "[invariant-check] Full-chain: $FC_PASSED passed, $FC_FAILED failed, $FC_SKIPPED skipped"
            rm -f "$FC_LOG"

            if [[ $FC_FAILED -gt 0 ]]; then
                echo "[invariant-check] Full-chain invariant violations detected."
                exit 1
            fi
        fi
    fi

else
    # v1: just check exit code
    if [[ $TEST_RC -ne 0 ]]; then
        echo "[invariant-check] Test suite failed (exit $TEST_RC)."
        tail -50 "$TEST_OUTPUT"
        exit 1
    fi
    echo "[invariant-check] All tests passed (v1 TESTS.md — invariant linkage not available)."
fi

# ---------------------------------------------------------------------------
# Emit summary
# ---------------------------------------------------------------------------
echo "[invariant-check] Summary:"
echo "  TESTS.md version: $VERSION"
echo "  Covered invariants: ${COVERED_INVARIANTS:-none}"
echo "  Test command: $TEST_CMD"
echo "  Result: PASS"

exit 0
