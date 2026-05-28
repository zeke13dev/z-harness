# DEPRECATED: frozen at v0.1.0. Remove after v0.2.0. See C6-D1.
"""
export-common.py — shared helpers for the multi-IDE export pipeline.

Importable by export-cursor.py, export-codex.py, export-agy.py, and any
other per-target adapter. Stdlib only; no third-party deps.

Public surface:
  enumerate_sources(repo_root) -> dict
  validate_capabilities(path) -> list[str]
  output_path_for(repo_root, target, kind, id) -> Path
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Parse YAML-fenced frontmatter at the top of *text*.

    Returns (frontmatter_dict, body_text).  Only simple ``key: value`` pairs
    are handled — no nested structures, sequences, or multi-line values.  This
    is intentional: the source files in this repo only use flat frontmatter.
    """
    frontmatter: dict[str, str] = {}
    body = text

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return frontmatter, body

    end_fence = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            end_fence = i
            break

    if end_fence == -1:
        return frontmatter, body

    for line in lines[1:end_fence]:
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r'^([A-Za-z0-9_-]+)\s*:\s*(.*)', stripped)
        if match:
            frontmatter[match.group(1)] = match.group(2).strip()

    body = "".join(lines[end_fence + 1:])
    return frontmatter, body


# ---------------------------------------------------------------------------
# Source enumeration
# ---------------------------------------------------------------------------

def _collect_entries(directory: Path) -> list[dict[str, Any]]:
    """Return one entry dict per markdown file in *directory* (non-recursive)."""
    if not directory.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        entries.append(
            {
                "id": path.stem,
                "source_path": path,
                "frontmatter": frontmatter,
                "body": body,
            }
        )
    return entries


def _collect_skills(skills_dir: Path) -> list[dict[str, Any]]:
    """Return one entry per skill (each skill lives in its own sub-directory
    as ``skills/<name>/SKILL.md``)."""
    if not skills_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_file.exists():
            continue
        text = skill_file.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(text)
        entries.append(
            {
                "id": skill_dir.name,
                "source_path": skill_file,
                "frontmatter": frontmatter,
                "body": body,
            }
        )
    return entries


def enumerate_sources(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Return a dict with keys ``commands``, ``agents``, ``skills``.

    Each value is a list of entry dicts::

        {
            "id": str,                      # stem of the source file / skill dir name
            "source_path": pathlib.Path,    # absolute path to the source file
            "frontmatter": dict[str, str],  # parsed key/value pairs (flat)
            "body": str,                    # markdown body after the frontmatter fence
        }
    """
    repo_root = Path(repo_root).resolve()
    return {
        "commands": _collect_entries(repo_root / "commands"),
        "agents": _collect_entries(repo_root / "agents"),
        "skills": _collect_skills(repo_root / "skills"),
    }


# ---------------------------------------------------------------------------
# CAPABILITIES.md schema validation
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS = ("## Supported", "## Unsupported", "## Notes")


def validate_capabilities(path: Path) -> list[str]:
    """Validate that *path* is a CAPABILITIES.md file conforming to the
    minimal schema.

    Required sections: ``## Supported``, ``## Unsupported``, ``## Notes``.

    Returns a list of validation error strings.  An empty list means the file
    is valid.
    """
    errors: list[str] = []
    path = Path(path)

    if not path.exists():
        errors.append(f"File not found: {path}")
        return errors

    text = path.read_text(encoding="utf-8")
    for section in _REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"Missing required section: {section!r}")

    return errors


# ---------------------------------------------------------------------------
# Per-target output path computation
# ---------------------------------------------------------------------------

_TARGET_CONVENTIONS: dict[str, dict[str, str]] = {
    "cursor": {
        "commands": ".cursor/rules/{id}.mdc",
        "agents": ".cursor/rules/{id}.mdc",
        "skills": ".cursor/rules/{id}.mdc",
    },
    "codex": {
        "commands": "prompts/{id}.md",
        "agents": "prompts/{id}.md",
        "skills": "prompts/{id}.md",
    },
    "agy": {
        "commands": "prompts/{id}.md",
        "agents": "prompts/{id}.md",
        "skills": "prompts/{id}.md",
    },
}


def output_path_for(repo_root: Path, target: str, kind: str, id: str) -> Path:
    """Return the conventional output path for a given export target.

    Args:
        repo_root: Absolute path to the repository root.
        target: Export target name — one of ``cursor``, ``codex``, ``agy``.
        kind: Source kind — one of ``commands``, ``agents``, ``skills``.
        id: Source identifier (file stem / skill dir name).

    Returns:
        An absolute Path inside ``exports/<target>/`` following the per-target
        convention:

        - cursor → ``exports/cursor/.cursor/rules/<id>.mdc``
        - codex  → ``exports/codex/prompts/<id>.md``
        - agy    → ``exports/agy/prompts/<id>.md``

    Raises:
        ValueError: if *target* or *kind* is not recognised.
    """
    repo_root = Path(repo_root).resolve()

    if target not in _TARGET_CONVENTIONS:
        raise ValueError(
            f"Unknown target {target!r}. Valid targets: {sorted(_TARGET_CONVENTIONS)}"
        )
    kind_map = _TARGET_CONVENTIONS[target]
    if kind not in kind_map:
        raise ValueError(
            f"Unknown kind {kind!r}. Valid kinds: {sorted(kind_map)}"
        )

    relative = kind_map[kind].format(id=id)
    return repo_root / "exports" / target / relative


if __name__ == "__main__":
    import sys
    print(
        "[z-harness] WARNING: export-common.py is deprecated and will be removed"
        " in the next minor release. Use the runtime driver instead.",
        file=sys.stderr,
    )
