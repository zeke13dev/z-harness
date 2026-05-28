"""
runtime/drivers/antigravity/persona_export.py

Persona export adapter for the Antigravity (agy) target.

Output path: <export_root>/.agent/personas/<name>.md

Portability: NATIVE — agy reads persona files from .agent/personas/ directly
via its persona-aware extension point.  No context-injection workaround needed.

Public surface
--------------
export_persona(persona_file_path, target_export_root) -> Path
    Write the persona to <target_export_root>/.agent/personas/<name>.md.
    Returns the absolute Path of the written file.
    Raises ValueError if the persona frontmatter is missing or malformed.
    Raises OSError if the destination cannot be written.
"""

from __future__ import annotations

from pathlib import Path

from runtime.drivers._persona_utils import parse_persona_file, build_portability_header


# This target consumes persona files natively.
_TARGET_NATIVE = True
_TARGET_NAME = "antigravity"
_TARGET_DESCRIPTION = (
    "agy reads persona files from .agent/personas/ natively via its "
    "persona-aware extension point."
)


def export_persona(persona_file_path: str | Path, target_export_root: str | Path) -> Path:
    """
    Export a persona file to the Antigravity (agy) target.

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
        ``<target_export_root>/.agent/personas/<name>.md``

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

    out_dir = target_export_root / ".agent" / "personas"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.md"

    header = build_portability_header(
        target=_TARGET_NAME,
        native=_TARGET_NATIVE,
        description=_TARGET_DESCRIPTION,
    )

    out_path.write_text(
        header + "---\n" + frontmatter_text + "---\n\n" + body,
        encoding="utf-8",
    )
    return out_path.resolve()
