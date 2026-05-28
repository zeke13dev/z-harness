"""
runtime/drivers/claude/persona_export.py

Persona export adapter for the Claude subagent target.

Output path: <export_root>/personas/<name>.md

Portability: NOT NATIVE in the IDE-integration sense — this is the Claude
subagent dispatch target.  The exported flat .md file is injected as a
system-prompt prefix when spinning up Claude subagents.  The flat format
(no MDC wrapper, no Cursor-style rule) is the simplest representation for
programmatic consumption by the Claude subagent dispatcher.

Public surface
--------------
export_persona(persona_file_path, target_export_root) -> Path
    Write the persona to <target_export_root>/personas/<name>.md.
    Returns the absolute Path of the written file.
    Raises ValueError if the persona frontmatter is missing or malformed.
    Raises OSError if the destination cannot be written.
"""

from __future__ import annotations

from pathlib import Path

from runtime.drivers._persona_utils import parse_persona_file, build_portability_header


_TARGET_NATIVE = False
_TARGET_NAME = "claude"
_TARGET_DESCRIPTION = (
    "Claude subagent target; this flat .md is injected as a system-prompt "
    "prefix at subagent dispatch time by the Claude subagent dispatcher."
)


def export_persona(persona_file_path: str | Path, target_export_root: str | Path) -> Path:
    """
    Export a persona file to the Claude subagent target.

    Parameters
    ----------
    persona_file_path:
        Absolute or relative path to the source persona .md file.
    target_export_root:
        Root of the target project tree to export into.

    Returns
    -------
    Path
        Absolute path of the written file:
        ``<target_export_root>/personas/<name>.md``

    Raises
    ------
    ValueError
        If the persona frontmatter cannot be parsed or ``name`` is missing.
    OSError
        If the output file cannot be written.
    """
    persona_file_path = Path(persona_file_path)
    target_export_root = Path(target_export_root)

    name, frontmatter_text, body = parse_persona_file(persona_file_path)

    out_dir = target_export_root / "personas"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.md"

    portability_header = build_portability_header(
        target=_TARGET_NAME,
        native=_TARGET_NATIVE,
        description=_TARGET_DESCRIPTION,
    )

    out_path.write_text(
        portability_header + "---\n" + frontmatter_text + "---\n\n" + body,
        encoding="utf-8",
    )
    return out_path.resolve()
