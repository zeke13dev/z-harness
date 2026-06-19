"""
runtime/drivers/codex/export.py

Codex CLI export driver — strict port of ``scripts/export-codex.py`` wrapped
in the runtime-owned ``export()`` signature.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Render all z-harness commands, skills, and agents as Codex CLI prompt
    files under ``export_root``.

    Codex output format:
    - ``prompts/<id>.md``   — one file per skill, starting with
                              ``# /<id>``, body rewritten to replace
                              Anthropic-specific constructs with HTML comments.
    - ``AGENTS.md``         — consolidated agent reference document.
    - No YAML frontmatter is emitted in any output file.

ExportResult is imported from runtime.drivers._export_utils (BLOCKER-1).

No behaviour changes relative to the legacy script; quirks are preserved and
annotated.
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
# Body rewriting
# ---------------------------------------------------------------------------

# Patterns that indicate Anthropic-specific / Claude Code constructs.
_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(",
    re.MULTILINE,
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Codex CLI;"
    " see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to remove Anthropic-specific constructs.

    Lines containing Agent(...), Skill(...), AskUserQuestion(...) etc. are
    replaced line-by-line with a single HTML comment, preserving leading
    whitespace.
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
            leading = len(stripped) - len(stripped.lstrip())
            result.append(" " * leading + _REPLACEMENT_COMMENT + "\n")
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# Prompt file rendering (commands + skills)
# ---------------------------------------------------------------------------


def _render_prompt(entry: dict[str, Any]) -> str:
    """Render a single command/skill *entry* as a Codex prompt file.

    Format:
        # /<id>
        <rewritten body>
    """
    entry_id = entry["id"]
    body = entry["body"]

    header = f"# /{entry_id}\n"
    rewritten_body = _rewrite_body(body)

    # Strip leading blank lines from body (frontmatter separator artifacts).
    rewritten_body = rewritten_body.lstrip("\n")

    return header + "\n" + rewritten_body


# ---------------------------------------------------------------------------
# AGENTS.md rendering
# ---------------------------------------------------------------------------


def _render_agents_md(agents: list[dict[str, Any]]) -> str:
    """Render all agents as a single consolidated AGENTS.md."""
    lines: list[str] = [
        "# Agents\n",
        "\n",
        "This file documents all z-harness agents exported for Codex CLI use.\n",
        "\n",
        "Codex CLI has no native subagent dispatch.  These agent definitions\n",
        "describe the **role and behaviour** of each agent so you can manually\n",
        "compose prompts or invoke the appropriate prompt file.\n",
        "\n",
        "---\n",
        "\n",
    ]

    for entry in agents:
        agent_id = entry["id"]
        fm = entry["frontmatter"]
        body = entry["body"]

        description = fm.get("description", "")
        role_line = f"**Role:** {description}\n" if description else ""

        rewritten_body = _rewrite_body(body)
        rewritten_body = rewritten_body.lstrip("\n")

        lines.append(f"## {agent_id}\n")
        lines.append("\n")
        if role_line:
            lines.append(role_line)
            lines.append("\n")
        lines.append(rewritten_body)
        if not rewritten_body.endswith("\n"):
            lines.append("\n")
        lines.append("\n---\n\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# Prompt validation
# ---------------------------------------------------------------------------


def _validate_prompt(path: Path) -> list[str]:
    """Validate a prompt .md file: header line present, body non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    lines = text.splitlines()
    if not lines:
        errors.append(f"{path}: file is empty")
        return errors

    if not lines[0].startswith("# /"):
        errors.append(
            f"{path}: first line must be '# /<id>', got: {lines[0]!r}"
        )

    body_lines = [ln for ln in lines[1:] if ln.strip()]
    if not body_lines:
        errors.append(f"{path}: body is empty (no non-blank lines after header)")

    return errors


# ---------------------------------------------------------------------------
# Public export function
# ---------------------------------------------------------------------------


def export(
    repo_root: Path,
    export_root: Path,
    *,
    options: dict[str, Any] | None = None,
) -> ExportResult:
    """Export z-harness skills and agents as Codex CLI prompt files.

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.  Used to discover
        source files (``agents/``, ``skills/``).
    export_root:
        Destination directory for exported files.  Prompt files are written
        to ``<export_root>/prompts/<id>.md``; the consolidated agent reference
        is written to ``<export_root>/AGENTS.md``.
    options:
        Reserved for future use.  Currently unused; pass ``None`` or omit.

    Returns
    -------
    ExportResult
        ``dest`` is *export_root* (resolved).
        ``files`` lists every file written.
        ``fidelity`` is ``"flattened"`` (Codex has no native subagent dispatch;
        Anthropic-specific constructs are replaced with HTML comments).
        ``warnings`` carries any non-fatal validation errors discovered during
        export.
    """
    repo_root = Path(repo_root).resolve()
    export_root = Path(export_root).resolve()

    sources = enumerate_sources(repo_root)
    emitted: list[Path] = []
    warnings: list[str] = []
    validation_errors: list[str] = []

    # Default base according to output_path_for convention (used to remap
    # paths when export_root differs from the default).
    default_base = repo_root / "exports" / "codex"

    # --- Emit prompt files for skills only (commands/ no longer exists) ---
    for kind in ("skills",):
        for entry in sources[kind]:
            eid = entry["id"]
            out_path = output_path_for(repo_root, "codex", kind, eid)
            if export_root != default_base:
                relative = out_path.relative_to(default_base)
                out_path = export_root / relative

            out_path.parent.mkdir(parents=True, exist_ok=True)
            content = _render_prompt(entry)
            out_path.write_text(content, encoding="utf-8")
            emitted.append(out_path)

    # --- Emit consolidated AGENTS.md ---
    agents_path = export_root / "AGENTS.md"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_md = _render_agents_md(sources["agents"])
    agents_path.write_text(agents_md, encoding="utf-8")

    # --- Validate prompt files ---
    for path in emitted:
        validation_errors.extend(_validate_prompt(path))

    # --- Validate CAPABILITIES.md if it exists ---
    caps_path = export_root / "CAPABILITIES.md"
    if caps_path.exists():
        cap_errors = validate_capabilities(caps_path)
        if cap_errors:
            validation_errors.extend(
                [f"CAPABILITIES.md: {e}" for e in cap_errors]
            )

    if validation_errors:
        warnings.extend(validation_errors)

    return ExportResult(
        dest=export_root,
        files=emitted + [agents_path],
        fidelity="flattened",
        warnings=warnings,
    )
