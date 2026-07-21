#!/usr/bin/env bash
# ci-grep-gates.sh — Scan for bare provider name identifiers (codex, gemini, claude)
# that are NOT followed by the -cli suffix in code files across the z-harness repo.
#
# Usage:
#   bash scripts/ci-grep-gates.sh
#
# Exit codes:
#   0  — clean (no violations found)
#   1  — violations found (per-match report emitted to stdout)
#   2  — usage/argument error
#   3  — hard error (missing directory, internal failure)
#
# Purpose:
#   After the provider-name rename (codex -> codex-cli, gemini -> gemini-cli,
#   claude -> claude-cli), new code must not hardcode the old bare provider names
#   as role/runtime identifiers. This lexical scan cannot yet distinguish those
#   provider IDs from legitimate host IDs; callers may treat exit 1 as advisory,
#   but missing inputs and internal failures remain hard errors.
#
# Exempt paths (not scanned):
#   - docs/llm/*.json           — descriptive index files
#   - z-harness/*/archive/      — archived run artifacts
#   - Any line containing "aliases" — the aliases mapping itself in providers.json
#
# Exempt files/directories (not scanned):
#   - All *.md files            — documentation/prompts; prose uses are legitimate
#   - runtime/drivers/          — driver implementations reference their own binary name
#   - runtime/contract/         — schema files use names in description strings
#   - runtime/tests/            — compat tests need old names as test input
#   - scripts/discover-providers.py — legacy v1 discovery script; generates v1 format
#   - scripts/config.py         — contains _PROVIDER_RENAME migration dict
#   - scripts/test_config.py    — migration tests; old names appear as test input
#   - scripts/extract-dismissals.py — only comment example text
#   - scripts/log-event.sh      — only comment example text
#   - scripts/log-phase.sh      — only comment example text
#   - scripts/ci-grep-gates.sh  — this file itself (comments reference old names)
#   - scripts/test_consult_off.sh — provider config fixtures use bare names as keys
#   - scripts/test_persona_stats.py — model fixtures use bare names as test input
#   - scripts/calibration-*.json — data/calibration files
#
# Exempt token:
#   - ".claude" path references (e.g. ~/.claude/CLAUDE.md) — the Claude Code config
#     directory, a filesystem path rather than a bare provider identifier.

set -euo pipefail

# Resolve repo root from script location
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Scan directories (relative to REPO_ROOT)
SCAN_DIRS=(
    "skills"
    "scripts"
    "agents"
    "runtime"
)

# Verify all scan directories exist
for d in "${SCAN_DIRS[@]}"; do
    if [[ ! -d "$REPO_ROOT/$d" ]]; then
        echo "ERROR: scan directory '$d' not found at $REPO_ROOT/$d" >&2
        exit 3
    fi
done

# ---------------------------------------------------------------------------
# Build the find command to locate candidate files.
# We use find to enumerate files, then grep each one.
# Exclusions are handled at the find stage where possible, and via post-filter.
# ---------------------------------------------------------------------------

# Files to fully exempt (relative to REPO_ROOT)
EXEMPT_PATHS=(
    # Driver implementations: reference their own binary names internally
    "runtime/drivers"
    # Schema files: use names in description strings
    "runtime/contract"
    # Compat/unit tests: need old names as test input
    "runtime/tests"
    # Legacy discovery script: generates v1 providers.json format
    "scripts/discover-providers.py"
    # Migration code: contains _PROVIDER_RENAME dict with old names
    "scripts/config.py"
    # Migration tests: old names appear as input strings being tested
    "scripts/test_config.py"
    # Only has old names in a comment example line
    "scripts/extract-dismissals.py"
    # Only has old names in comment examples
    "scripts/log-event.sh"
    "scripts/log-phase.sh"
    # This script itself (comments reference old names by necessity)
    "scripts/ci-grep-gates.sh"
    # Consult-off tests: provider config fixtures use bare names as JSON keys
    "scripts/test_consult_off.sh"
    # Persona-stats tests: model fixtures use bare names as test input
    "scripts/test_persona_stats.py"
)

# Build a sed-friendly file for post-filtering by path prefix
# We'll use awk to check if the file path starts with any exempt prefix
build_exempt_pattern() {
    local patterns=()
    for p in "${EXEMPT_PATHS[@]}"; do
        patterns+=("^$REPO_ROOT/$p")
    done
    printf '%s\n' "${patterns[@]}"
}

EXEMPT_PATTERN_FILE="$(mktemp)"
MATCH_FILE="$(mktemp)"
trap 'rm -f "$EXEMPT_PATTERN_FILE" "$MATCH_FILE"' EXIT
build_exempt_pattern > "$EXEMPT_PATTERN_FILE"

# ---------------------------------------------------------------------------
# Collect all candidate files via find (excluding .md, .pyc, __pycache__, archive/)
# ---------------------------------------------------------------------------
CANDIDATE_FILES=()
while IFS= read -r f; do
    CANDIDATE_FILES+=("$f")
done < <(
    find "${SCAN_DIRS[@]/#/$REPO_ROOT/}" \
        -type f \
        ! -name "*.md" \
        ! -name "*.pyc" \
        ! -path "*/__pycache__/*" \
        ! -path "*/archive/*" \
        ! -path "*/docs/llm/*.json" \
        2>/dev/null | sort
)

if [[ ${#CANDIDATE_FILES[@]} -eq 0 ]]; then
    echo "ci-grep-gates: OK — no candidate files found."
    exit 0
fi

# ---------------------------------------------------------------------------
# Filter out exempt files/directories
# ---------------------------------------------------------------------------
SCAN_FILES=()
for f in "${CANDIDATE_FILES[@]}"; do
    exempt=0
    for exempt_p in "${EXEMPT_PATHS[@]}"; do
        full_exempt="$REPO_ROOT/$exempt_p"
        # Check if file path starts with the exempt prefix (for directories)
        # or exactly matches it (for specific files)
        if [[ "$f" == "$full_exempt" || "$f" == "$full_exempt/"* ]]; then
            exempt=1
            break
        fi
    done
    [[ $exempt -eq 1 ]] && continue
    # Also skip calibration data files
    basename_f="$(basename "$f")"
    if [[ "$basename_f" == calibration-*.json ]]; then
        continue
    fi
    SCAN_FILES+=("$f")
done

if [[ ${#SCAN_FILES[@]} -eq 0 ]]; then
    echo "ci-grep-gates: OK — no files to scan after exemptions."
    exit 0
fi

# ---------------------------------------------------------------------------
# Pattern: match bare provider name NOT followed by -cli or word chars.
# grep -E does not support negative lookaheads, so we:
#   1. grep for the bare word boundary pattern
#   2. Post-filter: discard lines where every occurrence is part of a -cli form
# ---------------------------------------------------------------------------
PATTERN='\b(codex|gemini|claude)\b'

VIOLATIONS=()

for f in "${SCAN_FILES[@]}"; do
    [[ ! -f "$f" ]] && continue

    # grep the file; exit 1 = no match (fine), exit 0 = matches
    grep_ec=0
    : > "$MATCH_FILE"
    grep -En "$PATTERN" "$f" > "$MATCH_FILE" 2>/dev/null || grep_ec=$?
    if [[ $grep_ec -gt 1 ]]; then
        echo "ci-grep-gates: hard error reading $f (grep exit $grep_ec)" >&2
        exit 3
    fi
    [[ ! -s "$MATCH_FILE" ]] && continue

    # Relative path for output
    rel="$f"
    rel="${rel#$REPO_ROOT/}"

    # Process each matching line
    while IFS= read -r match_line; do
        [[ -z "$match_line" ]] && continue

        # Line-level exemptions
        # 1. Skip lines with the "aliases" key (the aliases mapping itself)
        if echo "$match_line" | grep -q '"aliases"'; then
            continue
        fi

        # 2. Check if ALL occurrences of the bare name on this line are
        #    actually part of a -cli form.  We strip all -cli suffixed forms
        #    and check if any bare form remains.
        #    Also strip ".claude" path references (the Claude Code config dir,
        #    e.g. ~/.claude/CLAUDE.md or ".claude/**/*.md") — these are filesystem
        #    paths, not bare provider identifiers.
        stripped="$(echo "$match_line" | sed -E -e 's/(codex|gemini|claude)-[a-z][a-z0-9-]*/EXEMPT/g' -e 's/\.claude/.EXEMPT/g')"
        if ! echo "$stripped" | grep -qE '\b(codex|gemini|claude)\b'; then
            continue
        fi

        # Real violation
        lineno="${match_line%%:*}"
        content="${match_line#*:}"
        VIOLATIONS+=("$rel:$lineno: $content")
    done < "$MATCH_FILE"
done

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
if [[ ${#VIOLATIONS[@]} -eq 0 ]]; then
    echo "ci-grep-gates: OK — no bare provider name violations found."
    exit 0
fi

printf "\n"
printf "ci-grep-gates: FAIL — bare provider name(s) found (should be '<name>-cli')\n"
printf "Repo: %s\n" "$REPO_ROOT"
printf "\n"
printf "These files reference 'codex', 'gemini', or 'claude' without the '-cli' suffix.\n"
printf "Use the new provider names: codex-cli, gemini-cli, claude-cli.\n"
printf "Run 'python3 scripts/config.py migrate' to rewrite TOML configs automatically.\n"
printf "\n"
printf "%-80s\n" "FILE:LINE  CONTENT"
printf "%s\n" "$(printf '%.0s-' {1..90})"

for v in "${VIOLATIONS[@]}"; do
    printf "  %s\n" "$v"
done

printf "\n"
printf "Total: %d violation(s) found.\n" "${#VIOLATIONS[@]}"
exit 1
