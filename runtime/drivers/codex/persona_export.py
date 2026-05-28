"""
runtime/drivers/codex/persona_export.py

Persona export adapter for the Codex CLI target.

Output path: <export_root>/prompts/personas/<name>.md

Portability: NOT NATIVE — Codex CLI has no built-in persona mechanism.
The Codex orchestrator is expected to concatenate this file as the system
prompt prefix at consultant-dispatch time.  The flat ``# Persona: <name>``
header makes the file self-describing when read standalone.

Public surface
--------------
export_persona(persona_file_path, target_export_root) -> Path
    Write the persona to <target_export_root>/prompts/personas/<name>.md.
    Returns the absolute Path of the written file.
    Raises ValueError if the persona frontmatter is missing or malformed.
    Raises OSError if the destination cannot be written.
"""

from __future__ import annotations

from pathlib import Path

from runtime.drivers._persona_utils import parse_persona_file, build_portability_header


_TARGET_NATIVE = False
_TARGET_NAME = "codex"
_TARGET_DESCRIPTION = (
    "Codex CLI has no native persona mechanism; the orchestrator concatenates "
    "this file as a system-prompt prefix at consultant-dispatch time."
)


def export_persona(persona_file_path: str | Path, target_export_root: str | Path) -> Path:
    """
    Export a persona file to the Codex CLI target.

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
        ``<target_export_root>/prompts/personas/<name>.md``

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

    out_dir = target_export_root / "prompts" / "personas"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.md"

    portability_header = build_portability_header(
        target=_TARGET_NAME,
        native=_TARGET_NATIVE,
        description=_TARGET_DESCRIPTION,
    )

    flat_header = f"# Persona: {name}\n\n"

    out_path.write_text(
        portability_header + flat_header + body,
        encoding="utf-8",
    )
    return out_path.resolve()
