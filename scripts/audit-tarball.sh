#!/usr/bin/env bash
# audit-tarball.sh — verify that an export tarball does not contain sensitive
# or internal paths that must never leave the repo.
#
# Usage: audit-tarball.sh <tarball-path>
#
# Exits 0 if the tarball is clean.
# Exits 1 on the first forbidden entry found, printing the offending path to
# stderr and a summary message to stdout.
#
# ALLOWLIST:
#   runtime/        — host-neutral runtime tree (binary + templates + config)
#                     Note: drivers live under runtime/drivers/; there is no
#                     separate top-level drivers/ directory in this repo.
#   personas/       — persona preset files (.md) for builtin and user layers.
#                     Per-target persona exports land under exports/<target>/personas/
#                     (Cursor), exports/<target>/.agent/personas/ (agy), etc.
#
# LEGACY-ALLOWLIST (remove at v<next-minor>):
#   exports/codex/  — legacy per-host Codex exporter output       # REMOVE-AT: v<next-minor>
#   exports/agy/    — legacy per-host AGY exporter output          # REMOVE-AT: v<next-minor>
#   exports/cursor/ — legacy per-host Cursor exporter output       # REMOVE-AT: v<next-minor>
#   exports/pi/     — pi exporter output (agents/prompts/extension) # REMOVE-AT: v<next-minor>
#
# Forbidden patterns (any match is a violation):
#   providers.json          — provider registry (credentials/config)
#   .z-harness/             — repo-local harness config dir
#   z-harness/plans/        — plan artifacts
#   z-harness/archive/      — run archives
#   z-harness/improvements/ — improvement artifacts
#   exports/<other>/        — re-packaging exports (non-legacy paths); see
#                             LEGACY-ALLOWLIST above for the three permitted
#                             exports/ subdirs during the transition window
#   /Users/<anything>       — macOS absolute user paths
#   /home/<anything>        — Linux absolute home paths
#   paths containing ~/     — tilde-expanded home paths
#   z-harness/<slug>/(SPEC|PLAN|TASKS).md — legacy plan content outside plans/

set -euo pipefail

# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s <tarball-path>\n' "$(basename "$0")" >&2
    exit 1
fi

TARBALL="$1"

if [[ ! -f "$TARBALL" ]]; then
    printf 'audit-tarball: file not found: %s\n' "$TARBALL" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Listing the tarball
# ---------------------------------------------------------------------------

# Support both .tar.gz/.tgz and plain .tar archives.
case "$TARBALL" in
    *.tar.gz|*.tgz)
        TAR_FLAGS="-tzf"
        ;;
    *.tar)
        TAR_FLAGS="-tf"
        ;;
    *.tar.bz2|*.tbz2)
        TAR_FLAGS="-tjf"
        ;;
    *.tar.xz|*.txz)
        TAR_FLAGS="-tJf"
        ;;
    *)
        # Try gzip first; fall back to plain tar.
        if tar -tzf "$TARBALL" >/dev/null 2>&1; then
            TAR_FLAGS="-tzf"
        else
            TAR_FLAGS="-tf"
        fi
        ;;
esac

LISTING="$(tar $TAR_FLAGS "$TARBALL" 2>/dev/null)"

# ---------------------------------------------------------------------------
# Audit checks
# ---------------------------------------------------------------------------

_audit_fail() {
    local pattern="$1"
    local entry="$2"
    printf '[audit-tarball] FAIL: forbidden pattern %s matched by: %s\n' "$pattern" "$entry"
    printf '[audit-tarball] tarball: %s\n' "$TARBALL"
    exit 1
}

_check_pattern() {
    local label="$1"
    local grep_args=("${@:2}")
    local hit
    hit="$(printf '%s\n' "$LISTING" | grep "${grep_args[@]}" | head -n1 || true)"
    if [[ -n "$hit" ]]; then
        _audit_fail "$label" "$hit"
    fi
}

# Fixed-string patterns (literal substring matches)
# Note: personas/ (top-level persona preset files) is NOT forbidden — it is explicitly
# allowlisted (see ALLOWLIST header comment above).  Per-target persona exports under
# exports/<target>/personas/ are also allowed via the exports/ filter below.
_check_pattern "providers.json"         -F  "providers.json"
_check_pattern ".z-harness/"            -F  ".z-harness/"
_check_pattern "z-harness/plans/"       -F  "z-harness/plans/"
_check_pattern "z-harness/archive/"     -F  "z-harness/archive/"
_check_pattern "z-harness/improvements/" -F "z-harness/improvements/"
_check_pattern "~/"                     -F  "~/"

# exports/ is forbidden except for the three legacy subdirs that are permitted
# during the one-minor-version transition window (see LEGACY-ALLOWLIST above).
# REMOVE-AT: v<next-minor> — once the legacy window closes, replace this block
# with: _check_pattern "exports/" -F "exports/"
#
# Per-target persona exports (e.g. exports/cursor/personas/, exports/agy/.agent/personas/,
# exports/codex/personas/) are implicitly allowed because they fall under the permitted
# exports/<target>/ prefix checked by the regex below.
_exports_hit="$(printf '%s\n' "$LISTING" \
    | grep -F "exports/" \
    | grep -Ev "^\.?/?exports/(codex|agy|cursor|pi)(/|$)" \
    | head -n1 || true)"
if [[ -n "$_exports_hit" ]]; then
    _audit_fail "exports/ (non-legacy path)" "$_exports_hit"
fi

# Regex patterns for absolute home paths
_check_pattern "/Users/<path>"          -E  "^/?Users/"
_check_pattern "/home/<path>"           -E  "^/?home/"

# Legacy plan content — z-harness/<slug>/(SPEC|PLAN|TASKS).md outside the
# canonical z-harness/plans/ directory.
_legacy_hit="$(printf '%s\n' "$LISTING" \
    | grep -E '^\./z-harness/[^/]+/(SPEC|PLAN|TASKS)\.md$' \
    | grep -v '^\./z-harness/plans/' \
    | head -n1 || true)"
if [[ -n "$_legacy_hit" ]]; then
    _audit_fail "legacy plan content (z-harness/<slug>/(SPEC|PLAN|TASKS).md)" "$_legacy_hit"
fi

printf '[audit-tarball] PASS: %s\n' "$TARBALL"
exit 0
