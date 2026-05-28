"""
runtime/drivers/cursor/persona_export.py

Persona export adapter for the Cursor target.

Output path: <export_root>/.cursor/personas/<name>.mdc

Portability: NOT NATIVE — Cursor has no built-in persona mechanism.
The exported .mdc file is structured as a Cursor context-injection rule
with ``attach: glob: "**/*"`` so it is attached to every file context.
The persona body becomes the rule content, acting as a system-prompt
prefix during Cursor AI interactions.

Public surface
--------------
export_persona(persona_file_path, target_export_root) -> Path
    Write the persona to <target_export_root>/.cursor/personas/<name>.mdc.
    Returns the absolute Path of the written file.
    Raises ValueError if the persona frontmatter is missing or malformed.
    Raises OSError if the destination cannot be written.
"""

from __future__ import annotations

from pathlib import Path

from runtime.drivers._persona_utils import parse_persona_file, build_portability_header


_TARGET_NATIVE = False
_TARGET_NAME = "cursor"
_TARGET_DESCRIPTION = (
    "Cursor has no native persona mechanism; this file is a context-injection "
    "rule (glob: '**/*') that prepends the persona body as a system-prompt prefix."
)

# Cursor MDC rule frontmatter for glob-based context injection.
_MDC_RULE_HEADER = """\
---
description: Persona context injection — {name}
globs:
  - "**/*"
alwaysApply: true
---
"""


def export_persona(persona_file_path: str | Path, target_export_root: str | Path) -> Path:
    """
    Export a persona file to the Cursor target as a .mdc context-injection rule.

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
        ``<target_export_root>/.cursor/personas/<name>.mdc``

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

    out_dir = target_export_root / ".cursor" / "personas"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.mdc"

    portability_header = build_portability_header(
        target=_TARGET_NAME,
        native=_TARGET_NATIVE,
        description=_TARGET_DESCRIPTION,
    )

    mdc_rule_header = _MDC_RULE_HEADER.format(name=name)

    out_path.write_text(
        portability_header + mdc_rule_header + "\n" + body,
        encoding="utf-8",
    )
    return out_path.resolve()
