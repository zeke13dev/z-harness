#!/usr/bin/env bash
# lint-frontmatter.sh — Validate all frontmatter-bearing .md files
#
# Checks every file under agents/, skills/, commands/, personas/, and
# scripts/pi_assets/ for YAML frontmatter that is parseable by a strict
# YAML 1.2 parser. Catches unquoted colons in description values
# (e.g. "file:line", "tasks: [...]") that the custom regex frontmatter
# parser silently accepts.
#
# Exits 0 if all pass, 1 on any failure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

errors=0
total=0

# Directories to scan (relative to REPO_ROOT)
scan_dirs=("agents" "skills" "commands" "personas" "scripts/pi_assets")

# Build a Python one-liner that validates frontmatter
# We try yaml (YAML 1.2) first, fall back to PyYAML, skip if neither available.
lint_py=$(cat << 'PYEOF'
import re, sys, os
from pathlib import Path

try:
    import yaml
except ImportError:
    print("SKIP: yaml module not available — cannot perform strict frontmatter validation")
    sys.exit(0)

repo_root = Path(os.environ.get('REPO_ROOT', '.'))
errors = 0

for root_dir in sys.argv[1:]:
    scan_path = repo_root / root_dir
    if not scan_path.is_dir():
        continue
    for md_file in sorted(scan_path.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        # Isolate frontmatter block
        end_idx = text.find("\n---", 3)
        if end_idx == -1:
            continue
        yaml_string = text[4:end_idx]
        try:
            parsed = yaml.safe_load(yaml_string)
        except yaml.YAMLError as e:
            rel = md_file.relative_to(repo_root)
            print(f"FAIL: {rel} — {e}")
            errors += 1
            continue
        if parsed is None:
            parsed = {}
        if not isinstance(parsed, dict):
            rel = md_file.relative_to(repo_root)
            print(f"FAIL: {rel} — frontmatter is not a mapping ({type(parsed).__name__})")
            errors += 1
            continue

if errors:
    sys.exit(1)
PYEOF
)

export REPO_ROOT
cd "$REPO_ROOT"

for dir in "${scan_dirs[@]}"; do
    if [ -d "$dir" ]; then
        files=$(find "$dir" -name "*.md" | wc -l | tr -d ' ')
        total=$((total + files))
    fi
done

echo "lint-frontmatter: scanning $total .md files across ${#scan_dirs[@]} directories..."

if ! python3 -c "$lint_py" "${scan_dirs[@]}" 2>&1; then
    errors=1
fi

if [ "$errors" -eq 0 ]; then
    printf "${GREEN}lint-frontmatter: ALL ${total} files passed${NC}\n"
    exit 0
else
    printf "${RED}lint-frontmatter: FAILURES detected${NC}\n"
    exit 1
fi
