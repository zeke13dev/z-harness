"""
build-skill-index.py — Crawl skills/*/SKILL.md frontmatter
and emit a compact one-line-per-skill dispatch table (markdown) to stdout.

Output format (one line per entry):
  `/command` — <one-clause description>

Entries are sorted alphabetically by command name (casefold, then original for
total-order stability — no case-tie ordering regressions).

Deduplication: skills/ is the sole source tier. After normalizing each name
to have a leading `/`, duplicates (two skill directories whose frontmatter name
resolves to the same normalized string) are collapsed to a single row: the
first entry encountered (alphabetical by directory name) wins; if its
description is empty, the next non-empty description is used as a fallback.

Multi-line YAML descriptions (folded `>` or literal `|` blocks): the parser
detects these indicators and fails fast with a clear error naming the file,
rather than silently emitting a useless row.

CLI usage:
  python3 scripts/build-skill-index.py [--repo-root <path>]

Defaults:
  --repo-root  directory containing skills/  (default: script's
               two-levels-up parent, i.e. the repo root when invoked from any
               working directory)

Stdlib only — no external deps (mirrors config.py / export-common.py
conventions).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Frontmatter parsing (mirrors export-common.py idioms)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str, source_path: Path | None = None) -> dict[str, str]:
    """Parse flat YAML-fenced frontmatter at the top of *text*.

    Only simple ``key: value`` pairs on a single line are handled — no nested
    structures or sequences.  Multi-line folded (``>``) or literal (``|``)
    block values are detected and cause a ValueError naming the source file.

    Returns a dict of key→value strings (values are stripped of surrounding
    whitespace).  Returns an empty dict if no valid frontmatter fence found.
    """
    frontmatter: dict[str, str] = {}
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return frontmatter

    end_fence = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            end_fence = i
            break

    if end_fence == -1:
        return frontmatter

    for line in lines[1:end_fence]:
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*:\s*(.*)', stripped)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            # Detect multi-line YAML block indicators
            if value in (">", "|", ">-", "|-", ">+", "|+"):
                loc = str(source_path) if source_path else "<unknown>"
                raise ValueError(
                    f"Multi-line YAML block value for key '{key}' in {loc!r}. "
                    "Flatten to a single-line string in frontmatter."
                )
            frontmatter[key] = value

    return frontmatter


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Ensure *name* has exactly one leading `/`.

    Examples:
        ``z-plan``   → ``/z-plan``
        ``/z-plan``  → ``/z-plan``
        ``//z-plan`` → ``/z-plan``  (degenerate; strip extras)
    """
    stripped = name.lstrip("/")
    return f"/{stripped}"


# ---------------------------------------------------------------------------
# Crawl helpers
# ---------------------------------------------------------------------------

def _crawl_skills(skills_dir: Path) -> list[dict[str, str]]:
    """Return one entry per skill directory containing a SKILL.md file."""
    if not skills_dir.is_dir():
        return []

    entries: list[dict[str, str]] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        fm = _parse_frontmatter(text, source_path=skill_file)
        raw_name = fm.get("name") or skill_dir.name
        name = _normalize_name(raw_name)
        entries.append({
            "name": name,
            "description": fm.get("description", ""),
            "source": "skill",
        })
    return entries


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _dedup(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse duplicate normalized skill names to a single entry.

    Merge rule (skills-only): first-seen entry wins; if its description is
    empty, the next non-empty description from a later entry is used as a
    fallback.  Entries arrive in alphabetical directory order from
    _crawl_skills, so "first-seen" means "alphabetically first skill dir".
    """
    seen: dict[str, dict[str, str]] = {}  # normalized name → merged entry
    for entry in entries:
        name = entry["name"]
        if name not in seen:
            seen[name] = dict(entry)
        else:
            existing = seen[name]
            # Fall back to this entry's description if the earlier one is empty
            if not existing["description"] and entry["description"]:
                existing["description"] = entry["description"]
    return list(seen.values())


# ---------------------------------------------------------------------------
# Dispatch table rendering
# ---------------------------------------------------------------------------

def _render_dispatch_table(entries: list[dict[str, str]]) -> str:
    """Render *entries* as a compact one-line-per-skill dispatch table.

    Format: ``/command` — <one-clause description>``
    Sorted by (name.casefold(), name) for deterministic total order with no
    case-tie ambiguity.
    """
    # Deduplicate before sorting
    deduped = _dedup(entries)
    # Total-order sort: casefold primary, original secondary (stable tie-break)
    sorted_entries = sorted(deduped, key=lambda e: (e["name"].casefold(), e["name"]))
    lines = [f"`{e['name']}` — {e['description']}" for e in sorted_entries]
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------------------
# Public API (importable by build-kernel.py)
# ---------------------------------------------------------------------------

def build_skill_index(repo_root: Path) -> str:
    """Crawl skills/ under *repo_root* and return a compact
    one-line-per-entry markdown dispatch table.

    Each line: ``/command` — <one-clause description>``

    Entries are sorted alphabetically (casefold + original for stable total order).

    This function is the canonical entry point reused by build-kernel.py.
    """
    repo_root = Path(repo_root).resolve()
    skills_entries = _crawl_skills(repo_root / "skills")
    return _render_dispatch_table(skills_entries)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _default_repo_root() -> Path:
    """Resolve the repo root as the parent of the scripts/ directory."""
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Emit a compact one-line-per-skill markdown dispatch table to stdout.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Path to the repository root (default: auto-detected from script location).",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root if args.repo_root is not None else _default_repo_root()
    table = build_skill_index(repo_root)
    sys.stdout.write(table)


if __name__ == "__main__":
    main()
