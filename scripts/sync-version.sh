#!/usr/bin/env bash
#
# sync-version.sh — single-source-of-truth version propagation.
#
# The human-controlled MAJOR.MINOR lives in ./VERSION (e.g. "1.0"). The PATCH is
# auto-derived from the git commit count, so the version string changes on every
# commit and the plugin cache can never silently go stale (the failure mode that
# bit us with the pinned "0.1.0"). Combined with marketplace auto-update, every
# new session re-fetches the latest.
#
#     full version = "<VERSION>.<commit-count>"
#
# Modes:
#   sync        write the computed version into every manifest (default)
#   --check     verify manifests already match; exit 1 on drift (CI gate)
#   --print     print the computed version and exit
#
#   --pending   count the in-progress commit too (used by the pre-commit hook,
#               where `git rev-list --count HEAD` is one behind the commit that
#               is about to be created)
#
# Manifests kept in sync (the version-resolution surfaces each host reads):
#   .claude-plugin/marketplace.json   Claude marketplace entry (first in chain)
#   .claude-plugin/plugin.json        Claude Code plugin manifest
#   plugin.json                       root manifest (legacy/discovery)
#   .codex-plugin/plugin.json         Codex plugin manifest

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "[z-harness] not inside a git repository" >&2; exit 1; }
cd "$REPO_ROOT"

VERSION_FILE="$REPO_ROOT/VERSION"
[ -f "$VERSION_FILE" ] || { echo "[z-harness] missing VERSION file at $VERSION_FILE" >&2; exit 1; }

BASE="$(tr -d '[:space:]' < "$VERSION_FILE")"
if ! printf '%s' "$BASE" | grep -Eq '^[0-9]+\.[0-9]+$'; then
  echo "[z-harness] VERSION must be MAJOR.MINOR (e.g. 1.0); got '$BASE'" >&2; exit 1
fi

mode="sync"; pending=0
for a in "$@"; do
  case "$a" in
    sync)          mode="sync" ;;
    --check|check) mode="check" ;;
    --print|print) mode="print" ;;
    --pending)     pending=1 ;;
    *) echo "Usage: $0 [sync|--check|--print] [--pending]" >&2; exit 1 ;;
  esac
done

COUNT="$(git rev-list --count HEAD 2>/dev/null || echo 0)"
[ "$pending" -eq 1 ] && COUNT=$((COUNT + 1))
FULL="${BASE}.${COUNT}"

if [ "$mode" = "print" ]; then echo "$FULL"; exit 0; fi

MANIFESTS=(
  ".claude-plugin/marketplace.json"
  ".claude-plugin/plugin.json"
  "plugin.json"
  ".codex-plugin/plugin.json"
)

python3 - "$mode" "$FULL" "${MANIFESTS[@]}" <<'PY'
import json, re, sys

mode, full, *manifests = sys.argv[1:]
# Anchor on the z-harness entry's name line (NOT the marketplace's own name).
ANCHOR = re.compile(r'^(\s*)"name"\s*:\s*"z-harness"\s*,?\s*$', re.M)
VERSUB = re.compile(r'("version"\s*:\s*")[^"]*(")')

def current(text):
    m = VERSUB.search(text)
    return m.group(0).split('"')[3] if m else None

drift = []
for path in manifests:
    try:
        text = open(path).read()
    except FileNotFoundError:
        # Generated manifests (e.g. .codex-plugin/, gitignored) may be absent in
        # a fresh checkout. Absent != drift; export regenerates + stamps them.
        continue

    if mode == "check":
        cur = current(text)
        if cur != full:
            drift.append(f"{path}: has {cur!r}, expected {full!r}")
        continue

    # sync: replace an existing version field, else insert after the name line.
    if VERSUB.search(text):
        new = VERSUB.sub(lambda m: f"{m.group(1)}{full}{m.group(2)}", text, count=1)
    else:
        m = ANCHOR.search(text)
        if not m:
            print(f"[z-harness] no z-harness name anchor in {path}", file=sys.stderr)
            sys.exit(2)
        indent = m.group(1)
        new = text[:m.end()] + f'\n{indent}"version": "{full}",' + text[m.end():]
    if new != text:
        json.loads(new)          # never write invalid JSON
        open(path, "w").write(new)

if mode == "check" and drift:
    print("[z-harness] version drift (run `make version-sync`):", file=sys.stderr)
    for d in drift:
        print("  " + d, file=sys.stderr)
    sys.exit(1)
PY

[ "$mode" = "sync" ] && echo "[z-harness] synced version $FULL into ${#MANIFESTS[@]} manifests"
exit 0
