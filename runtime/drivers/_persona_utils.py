"""
runtime/drivers/_persona_utils.py

Shared utilities for persona export adapters.

Provides a minimal YAML frontmatter parser and portability header builder
used by all four per-target persona_export.py modules.

These are internal helpers — not part of the public driver surface.
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Minimal frontmatter parser (stdlib-only — no PyYAML dependency)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---\r?\n(.*?)---\r?\n(.*)",
    re.DOTALL,
)


def parse_persona_file(path: Path) -> tuple[str, str, str]:
    """
    Parse a persona markdown file.

    Returns
    -------
    (name, frontmatter_text, body)
        ``name`` is the value of the ``name:`` key in the frontmatter.
        ``frontmatter_text`` is the raw text between the ``---`` delimiters
        (trailing newline included).
        ``body`` is everything after the closing ``---`` delimiter (leading
        blank line stripped).

    Raises
    ------
    ValueError
        If the file has no frontmatter or the ``name`` key is missing.
    """
    raw = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        raise ValueError(
            f"Persona file {path} has no YAML frontmatter block (expected "
            "opening and closing '---' delimiters)."
        )

    frontmatter_text = m.group(1)
    body = m.group(2).lstrip("\n")

    # Extract the ``name`` key from frontmatter lines.
    name: str | None = None
    for line in frontmatter_text.splitlines():
        if line.startswith("name:"):
            name = line[len("name:"):].strip().strip('"').strip("'")
            break

    if not name:
        raise ValueError(
            f"Persona file {path} frontmatter is missing required 'name:' key."
        )

    return name, frontmatter_text, body


# ---------------------------------------------------------------------------
# Portability header builder
# ---------------------------------------------------------------------------

def build_portability_header(target: str, native: bool, description: str) -> str:
    """
    Return a comment block describing the persona export portability for
    the given target.

    Parameters
    ----------
    target:
        Short target identifier (e.g. ``"antigravity"``, ``"cursor"``).
    native:
        Whether the target consumes persona files natively.
    description:
        One-sentence description of how the target uses the file.
    """
    native_label = "yes" if native else "no"
    lines = [
        "<!-- persona-export: portability header -->",
        f"<!-- target:  {target} -->",
        f"<!-- native:  {native_label} -->",
        f"<!-- note:    {description} -->",
        "",
    ]
    return "\n".join(lines) + "\n"
