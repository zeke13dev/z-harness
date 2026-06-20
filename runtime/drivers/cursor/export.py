"""
runtime/drivers/cursor/export.py

Port of ``scripts/export-cursor.py`` as a runtime driver.

Renders z-harness agents as Cursor ``.mdc`` rule files under
``<export_root>/.cursor/rules/`` and skills as native ``SKILL.md`` files
under ``<export_root>/.cursor/skills/<id>/SKILL.md``.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult

Skill layout
------------
Each skill is copied verbatim (frontmatter preserved) to
``.cursor/skills/<id>/SKILL.md``.  No transliteration is performed —
Cursor 2.4+ supports native SKILL.md invocation.

Exactly one generated always-apply index ``.mdc`` is written at
``.cursor/rules/z-harness-skills.mdc`` pointing users to the skills
directory.

Limitations (agents only)
--------------------------
- Agent dispatch / Skill invocation are not supported in Cursor rules. Lines
  containing ``Agent(...)``, ``Skill(...)``, ``AskUserQuestion(...)``,
  ``TaskCreate(...)``, or ``SubagentCreate(...)`` are replaced with a
  one-line HTML comment directing the reader to CAPABILITIES.md.
  See: <!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import (
    ExportResult,
    enumerate_sources,
    output_path_for,
    validate_capabilities,
)


# ---------------------------------------------------------------------------
# Body rewriting — preserved verbatim from export-cursor.py
# ---------------------------------------------------------------------------

# Patterns that indicate Anthropic-specific / Claude Code constructs.
_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Cursor; see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to remove Anthropic-specific constructs.

    Strategy: scan for Agent(...)/Skill(...)/AskUserQuestion(...) call sites.
    When found on a line, replace that entire line with the replacement comment
    (preserving leading whitespace for readability).  Code blocks that contain
    these constructs are handled line-by-line as well since cursor rules are
    read as plain markdown.
    """
    lines = body.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.rstrip("\n\r")
        if (
            _AGENT_CALL_RE.search(stripped)
            or _SKILL_CALL_RE.search(stripped)
            or _TOOL_SCHEMA_RE.search(stripped)
        ):
            # Preserve leading whitespace, replace the rest.
            leading = len(stripped) - len(stripped.lstrip())
            result.append(" " * leading + _REPLACEMENT_COMMENT + "\n")
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# MDC rendering — preserved verbatim from export-cursor.py
# ---------------------------------------------------------------------------

def _render_mdc(entry: dict[str, Any]) -> str:
    """Render a single source *entry* as a Cursor .mdc string."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", "")
    # Escape any double-quotes in description for YAML safety.
    description_escaped = description.replace('"', '\\"')

    globs_line = ""
    if "globs" in fm:
        globs_escaped = fm["globs"].replace('"', '\\"')
        globs_line = f'\nglobs: "{globs_escaped}"'

    frontmatter_block = (
        f'---\n'
        f'description: "{description_escaped}"{globs_line}\n'
        f'alwaysApply: false\n'
        f'---\n'
    )

    rewritten_body = _rewrite_body(body)
    # Ensure body starts with a newline for readability.
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return frontmatter_block + rewritten_body


# ---------------------------------------------------------------------------
# Skills index MDC — single always-apply pointer to .cursor/skills/
# ---------------------------------------------------------------------------

_SKILLS_INDEX_NAME = "z-harness-skills.mdc"

_SKILLS_INDEX_TEMPLATE = (
    "---\n"
    'description: "z-harness skills index — invoke skills from .cursor/skills/"\n'
    "alwaysApply: true\n"
    "---\n"
    "\n"
    "# z-harness Skills\n"
    "\n"
    "z-harness skills live under `.cursor/skills/<name>/SKILL.md`.\n"
    "Open any `SKILL.md` in that directory and invoke it directly in Cursor.\n"
    "\n"
    "Available skills are listed in `.cursor/skills/` — one subdirectory per skill.\n"
)


# ---------------------------------------------------------------------------
# MDC validation — preserved verbatim from export-cursor.py
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _validate_mdc(path: Path) -> list[str]:
    """Basic MDC validation: frontmatter present + parseable, body non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors

    fm_text = m.group(1)
    # Verify required keys are present in frontmatter.
    for required_key in ("description", "alwaysApply"):
        if not re.search(rf"^{required_key}\s*:", fm_text, re.MULTILINE):
            errors.append(f"{path}: frontmatter missing required key '{required_key}'")

    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")

    return errors


# ---------------------------------------------------------------------------
# Public export function
# ---------------------------------------------------------------------------

def export(
    repo_root: Path | str,
    export_root: Path | str,
    *,
    options: dict[str, Any] | None = None,
) -> ExportResult:
    """Export z-harness agents and skills to Cursor.

    Agents are rendered as ``.mdc`` rule files under
    ``<export_root>/.cursor/rules/``.  Skills are written verbatim as
    ``<export_root>/.cursor/skills/<id>/SKILL.md`` (frontmatter preserved,
    no rewriting).  Exactly one generated always-apply index ``.mdc`` is
    written at ``<export_root>/.cursor/rules/z-harness-skills.mdc``.

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.  Source directories
        ``agents/`` and ``skills/`` are resolved relative to this path.
    export_root:
        Absolute path to the export output root directory.
    options:
        Reserved for future use.  Currently unused; any keys are silently
        ignored.

    Returns
    -------
    ExportResult
        ``dest`` is set to ``<export_root>/.cursor/rules/``.
        ``files`` lists every file written (agents as ``.mdc``, skills as
        ``SKILL.md``, plus the index ``.mdc``).
        ``fidelity`` is ``"flattened"`` (Agent/Skill calls in agent rules are
        replaced with limitation comments).
        ``warnings`` contains any MDC validation errors encountered.
    """
    repo_root = Path(repo_root).resolve()
    out_root = Path(export_root).resolve()

    sources = enumerate_sources(repo_root)

    emitted: list[Path] = []
    validation_errors: list[str] = []

    # Canonical output base for the cursor target (used for path rewriting
    # when out_root differs from the default exports/cursor/).
    default_base = repo_root / "exports" / "cursor"

    def _resolve_out(kind: str, eid: str) -> Path:
        """Resolve output path, honouring out_root override."""
        out_path = output_path_for(repo_root, "cursor", kind, eid)
        if out_root != default_base:
            relative = out_path.relative_to(default_base)
            return out_root / relative
        return out_path

    # --- Agents: render as .mdc rule files (with body rewriting). ---
    for entry in sources["agents"]:
        out_path = _resolve_out("agents", entry["id"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_render_mdc(entry), encoding="utf-8")
        emitted.append(out_path)

    # --- Skills: copy verbatim as native SKILL.md files. ---
    for entry in sources["skills"]:
        out_path = _resolve_out("skills", entry["id"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve the source SKILL.md verbatim (frontmatter intact, no rewriting).
        source_text = entry["source_path"].read_text(encoding="utf-8")
        out_path.write_text(source_text, encoding="utf-8")
        emitted.append(out_path)

    # --- Skills index: one generated always-apply .mdc pointer (only when skills present). ---
    # Gated: emitting a skills index when there are zero skills is misleading and
    # breaks tests that assert result.files == [] for persona-only or empty exports.
    if sources["skills"]:
        rules_dir = out_root / ".cursor" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        index_path = rules_dir / _SKILLS_INDEX_NAME
        index_path.write_text(_SKILLS_INDEX_TEMPLATE, encoding="utf-8")
        emitted.append(index_path)

    # Validate all emitted .mdc files (agents + index; SKILL.md are not .mdc).
    for path in emitted:
        if path.suffix == ".mdc":
            validation_errors.extend(_validate_mdc(path))

    # Validate CAPABILITIES.md if it exists.
    caps_path = out_root / "CAPABILITIES.md"
    if caps_path.exists():
        cap_errors = validate_capabilities(caps_path)
        for err in cap_errors:
            validation_errors.append(f"CAPABILITIES.md: {err}")

    dest = out_root / ".cursor" / "rules"
    return ExportResult(
        dest=dest,
        files=emitted,
        fidelity="flattened",
        warnings=validation_errors,
    )
