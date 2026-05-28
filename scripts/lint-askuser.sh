#!/usr/bin/env bash
# lint-askuser.sh — audit AskUserQuestion callsites in commands/ and skills/
#
# Usage:
#   scripts/lint-askuser.sh [--strict]
#
# Emits a table of every AskUserQuestion invocation found in commands/ and skills/,
# tagged REGISTERED if the same file also contains a resolve-question or check-no-ask
# call (indicating the callsite participates in halt-from-ask), or UNREGISTERED
# otherwise.
#
# Exit codes:
#   0  — success (or success with unregistered callsites, unless --strict)
#   1  — unregistered callsites found AND --strict flag was passed
#
# This is documentation/audit tooling, NOT runtime enforcement.
# Unregistered AskUserQuestion callsites under Z_HARNESS_NO_ASK=halt still block
# the conversation until the user responds. See docs/human/overnight-run.md for details.

set -euo pipefail

STRICT=0
for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# Resolve repo root from script location
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMANDS_DIR="$REPO_ROOT/commands"
SKILLS_DIR="$REPO_ROOT/skills"

# Verify directories exist
if [[ ! -d "$COMMANDS_DIR" ]]; then
  echo "ERROR: commands/ directory not found at $COMMANDS_DIR" >&2
  exit 1
fi
if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "ERROR: skills/ directory not found at $SKILLS_DIR" >&2
  exit 1
fi

# Collect all files containing AskUserQuestion
FILES=()
while IFS= read -r f; do
  FILES+=("$f")
done < <(grep -rln "AskUserQuestion" "$COMMANDS_DIR" "$SKILLS_DIR" 2>/dev/null | sort)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No AskUserQuestion callsites found in commands/ or skills/."
  exit 0
fi

# Classify each file: REGISTERED = has both AskUserQuestion + (resolve-question or check-no-ask)
REGISTERED_FILES=()
UNREGISTERED_FILES=()

for f in "${FILES[@]}"; do
  if grep -q "resolve-question\|check-no-ask" "$f" 2>/dev/null; then
    REGISTERED_FILES+=("$f")
  else
    UNREGISTERED_FILES+=("$f")
  fi
done

# Helper: print the table for a given file list and status tag
_print_rows() {
  local status="$1"
  shift
  local files=("$@")

  for f in "${files[@]}"; do
    rel="${f#$REPO_ROOT/}"
    # Extract question_id from resolve-question or check-no-ask call (if any)
    qid=""
    if [[ "$status" == "REGISTERED" ]]; then
      qid=$(grep -oE 'workflow\.[a-z_]+' "$f" | head -1 || true)
    fi

    # Emit one row per AskUserQuestion occurrence
    while IFS=: read -r lineno _rest; do
      if [[ -n "$qid" ]]; then
        printf "%-60s %-12s %s\n" "$rel:$lineno" "[$status]" "$qid"
      else
        printf "%-60s %-12s\n" "$rel:$lineno" "[$status]"
      fi
    done < <(grep -n "AskUserQuestion" "$f" 2>/dev/null)
  done
}

# Print header
printf "\n"
printf "AskUserQuestion callsite audit — %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf "Repo: %s\n" "$REPO_ROOT"
printf "\n"
printf "A callsite is REGISTERED if its file contains BOTH an AskUserQuestion call AND\n"
printf "a resolve-question or check-no-ask call (the halt-from-ask gate).\n"
printf "UNREGISTERED callsites will block under Z_HARNESS_NO_ASK=halt.\n"
printf "\n"
printf "%-60s %-12s %s\n" "FILE:LINE" "STATUS" "QUESTION_ID"
printf "%s\n" "$(printf '%.0s-' {1..90})"

# Print registered callsites first
if [[ ${#REGISTERED_FILES[@]} -gt 0 ]]; then
  printf "\n# Registered (%d files, 9 expected)\n" "${#REGISTERED_FILES[@]}"
  _print_rows "REGISTERED" "${REGISTERED_FILES[@]}"
fi

# Print unregistered callsites
if [[ ${#UNREGISTERED_FILES[@]} -gt 0 ]]; then
  printf "\n# Unregistered (%d files)\n" "${#UNREGISTERED_FILES[@]}"
  _print_rows "UNREGISTERED" "${UNREGISTERED_FILES[@]}"
fi

printf "\n"
printf "Summary: %d REGISTERED file(s), %d UNREGISTERED file(s).\n" \
  "${#REGISTERED_FILES[@]}" "${#UNREGISTERED_FILES[@]}"

if [[ ${#UNREGISTERED_FILES[@]} -gt 0 ]]; then
  printf "NOTE: Unregistered callsites are a known v1 limitation (fail-OPEN).\n"
  printf "      CI (make lint) surfaces these as advisory warnings, not hard failures.\n"
  printf "      Run 'make lint-strict' or 'scripts/lint-askuser.sh --strict' for exit-1 mode.\n"
  if [[ "$STRICT" -eq 1 ]]; then
    printf "\n--strict mode: exiting 1 due to %d unregistered callsite(s).\n" \
      "${#UNREGISTERED_FILES[@]}"
    exit 1
  fi
fi

exit 0
