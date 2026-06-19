#!/usr/bin/env bash
#
# changelog-from-commit.sh — drive a CHANGELOG.md bullet from the just-made commit.
#
# Intended to be called from a git `post-commit` hook (see
# scripts/install-changelog-hook.sh). On a conventional-commit of an allowlisted
# type, it appends a human-readable `_(auto)_` bullet under today's date heading
# in CHANGELOG.md and leaves it UNSTAGED — it never amends or creates a commit,
# so there is no loop and no history rewrite (this repo's git-safety doctrine).
#
# Gated entirely by config (scripts/config.py), so it can be disabled per-repo
# without uninstalling the hook:
#   changelog.auto   (bool)  master switch
#   changelog.types  (list)  conventional-commit types that earn a bullet
#   changelog.repos  (list)  repo-id allowlist; "*" = all
#   changelog.file   (str)   changelog path, relative to repo root
#
# Always exits 0 — a changelog hiccup must never make a commit look failed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -n "$repo_root" ] || exit 0

# --- Skip merge commits (a merge's subject isn't a real change line) ----------
if git rev-parse -q --verify HEAD^2 >/dev/null 2>&1; then
  exit 0
fi

subject="$(git log -1 --pretty=%s 2>/dev/null)" || exit 0
[ -n "$subject" ] || exit 0

# --- Parse conventional commit: type(scope)!: description ----------------------
if [[ ! "$subject" =~ ^([a-zA-Z]+)(\(([^\)]*)\))?(!)?:[[:space:]]*(.+)$ ]]; then
  exit 0
fi
ctype="${BASH_REMATCH[1]}"
cscope="${BASH_REMATCH[3]}"
cdesc="${BASH_REMATCH[5]}"

# --- Read config (stdout is clean; warnings go to stderr) ----------------------
cfg() { python3 "$SCRIPT_DIR/config.py" get "$1" 2>/dev/null; }

auto="$(cfg changelog.auto)"
[ "$auto" = "true" ] || exit 0

types_json="$(cfg changelog.types)"
repos_json="$(cfg changelog.repos)"
changelog_file="$(cfg changelog.file)"
[ -n "$changelog_file" ] || changelog_file="CHANGELOG.md"

# Type allowlist (case-insensitive)
ctype_lc="$(printf '%s' "$ctype" | tr '[:upper:]' '[:lower:]')"
if ! printf '%s' "$types_json" | python3 -c '
import json,sys
want=sys.argv[1]
try: types=[str(t).lower() for t in json.load(sys.stdin)]
except Exception: sys.exit(1)
sys.exit(0 if want in types else 1)
' "$ctype_lc"; then
  exit 0
fi

# Repo-id allowlist ("*" = all)
repo_id="$(bash "$SCRIPT_DIR/plan-path.sh" z_harness_repo_id 2>/dev/null)" || repo_id=""
if ! printf '%s' "$repos_json" | python3 -c '
import json,sys
rid=sys.argv[1]
try: repos=[str(r) for r in json.load(sys.stdin)]
except Exception: sys.exit(1)
sys.exit(0 if ("*" in repos or rid in repos) else 1)
' "$repo_id"; then
  exit 0
fi

changelog_path="$repo_root/$changelog_file"
[ -f "$changelog_path" ] || exit 0   # don't create one uninvited

today="$(date +%Y-%m-%d)"

# --- Insert the bullet (idempotent within today's section) ---------------------
CL_TODAY="$today" CL_DESC="$cdesc" CL_SCOPE="$cscope" python3 - "$changelog_path" <<'PY'
import os, re, sys

path  = sys.argv[1]
today = os.environ["CL_TODAY"]
desc  = os.environ["CL_DESC"].strip().rstrip()
scope = os.environ.get("CL_SCOPE", "").strip()

# Human-shaped bullet: capitalize, tag as auto, keep scope as a hint.
human = desc[:1].upper() + desc[1:] if desc else desc
suffix = f" _({scope})_" if scope else ""
bullet = f"- _(auto)_ {human}{suffix}\n"

with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

heading = f"## {today}\n"

# Find today's heading and the start of the next date section after it.
try:
    hi = lines.index(heading)
except ValueError:
    hi = None

if hi is not None:
    # End of today's section = next "## " heading, else EOF.
    end = len(lines)
    for j in range(hi + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    section = "".join(lines[hi:end])
    # Idempotency: skip if this exact description is already in today's section.
    if human and human in section:
        sys.exit(0)
    # Insert after the last non-blank line of the section.
    ins = end
    while ins > hi + 1 and lines[ins - 1].strip() == "":
        ins -= 1
    lines.insert(ins, bullet)
else:
    # Create a new date section above the newest existing one (first "## ").
    block = [heading, "\n", bullet, "\n"]
    target = None
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            target = i
            break
    if target is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        if lines and lines[-1].strip() != "":
            lines.append("\n")
        lines.extend(block)
    else:
        lines[target:target] = block

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)

print(f"[z-harness] CHANGELOG.md: drafted a bullet under {today} (unstaged — edit/stage as you like).")
PY

exit 0
