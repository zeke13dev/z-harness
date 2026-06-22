"""
runtime/drivers/copilot/export.py

GitHub Copilot export driver — emits a single ``.github/copilot-instructions.md``.

GitHub Copilot reads exactly one file at the repository level:
``.github/copilot-instructions.md``.  This driver consolidates the full
z-harness capabilities into that single file regardless of the configured
export strategy — the strategy is effectively ``pointer`` for this target.

Export-only asymmetry
---------------------
GitHub Copilot is an EXPORT-ONLY target.  There is no HostAdapter, HostDriver,
or adapter-registry entry for this module.  This module owns only the export
pipeline: it reads from the z-harness source tree and writes
``.github/copilot-instructions.md`` to *export_root*.

Copilot's pointer strategy
--------------------------
Because Copilot reads a single instructions file (not raw source bodies), this
driver exports only the truncated/consolidated descriptions from each source
file's frontmatter.  No source body rewriting occurs — Agent(...), Skill(...),
or AskUserQuestion(...) call sites in source bodies are never included in the
output, so no rewriting is needed or performed.

Single-file consolidation
-------------------------
Even when the configured export strategy is ``curated`` or ``full``, Copilot's
single-file constraint means all relevant content must be consolidated.
The output file contains:

1. A short what-is-z-harness preamble.
2. A "Capabilities" section describing how to invoke commands and skills.
3. A command catalog (one line per command).
4. An agent catalog (one line per agent).
5. A skill catalog (one line per skill).
6. Invocation guidance and limitations (no subagent dispatch in Copilot).

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import (
    ExportResult,
    enumerate_sources,
    resolve_strategy,
)


# ---------------------------------------------------------------------------
# Catalog rendering
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 100) -> str:
    """Truncate *text* to at most *max_len* characters, appending ``…`` if cut."""
    text = text.strip().replace("\n", " ")
    if len(text) > max_len:
        return text[:max_len - 1] + "…"
    return text


def _render_catalog_section(title: str, entries: list[dict[str, Any]], id_prefix: str = "") -> str:
    """Render a markdown section listing *entries* as a bullet catalog.

    Parameters
    ----------
    title:
        The ``##``-level section heading.
    entries:
        List of source entry dicts (``id``, ``frontmatter``).
    id_prefix:
        Optional prefix to prepend to the displayed ID (e.g. ``/`` for
        commands and skills).
    """
    lines = [f"\n## {title}\n\n"]
    for entry in entries:
        eid = entry["id"]
        desc = _truncate(entry["frontmatter"].get("description", ""), 120)
        display_id = f"{id_prefix}{eid}" if id_prefix else eid
        lines.append(f"- **{display_id}** — {desc}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Document rendering
# ---------------------------------------------------------------------------

_PREAMBLE = """\
# z-harness Copilot Instructions

z-harness is a structured software-development harness for Claude Code that
adds planning discipline, multi-LLM review, and a reusable skill/agent
ecosystem on top of raw LLM sessions.

## What z-harness provides

- **Slash commands** — invoked as `/z-<name>` in Claude Code.  Each command
  runs a focused pipeline (planning, implementing, reviewing, auditing, …).
- **Agents** — specialist subagents dispatched internally by commands.  They
  are not directly invocable in GitHub Copilot; use the slash commands instead.
- **Skills** — reusable skill files that mirror commands but are loaded on
  demand by Claude Code; invoke them as `/z-<name>` in a Claude Code session.

## Invocation guidance (GitHub Copilot)

GitHub Copilot does not support native subagent dispatch or tool calls from
instructions files.  This file is a consolidated catalog of z-harness
commands, agents, and skills as capability descriptions — there are no
`Agent(...)` or `Skill(...)` call sites here, and no source-body rewriting
has occurred.

To use z-harness from GitHub Copilot:

1. Describe what you want to do in natural language (e.g., "plan a feature
   to add dark mode using z-harness").
2. Copilot will suggest the appropriate z-harness workflow based on this file.
3. Copy the suggested command into a Claude Code session to execute it with
   full harness support.

## Key workflows

| Goal | Command |
|---|---|
| Plan a change | `/z-plan <description>` |
| Execute all tasks | `/z-execute` |
| Review a PR/branch | `/z-mr-review` |
| Audit a component | `/z-audit <component>` |
| Debug an issue | `/z-debug <issue>` |
| Export to IDEs | `/z-export` |
"""


def _render_doc(sources: dict[str, list[dict[str, Any]]]) -> str:
    """Render the full ``copilot-instructions.md`` content from *sources*."""
    parts = [_PREAMBLE]

    if sources.get("commands"):
        parts.append(_render_catalog_section(
            "Command catalog",
            sources["commands"],
            id_prefix="/",
        ))

    if sources.get("agents"):
        parts.append(_render_catalog_section(
            "Agent catalog",
            sources["agents"],
        ))

    if sources.get("skills"):
        parts.append(_render_catalog_section(
            "Skill catalog",
            sources["skills"],
            id_prefix="/",
        ))

    parts.append(
        "\n## Limitations\n\n"
        "- GitHub Copilot cannot dispatch `Agent(...)` calls or invoke "
        "`Skill(...)` programmatically.\n"
        "- Cross-LLM consultation (Gemini, Codex CLI) is not available within Copilot.\n"
        "- Subagent fan-out (used by `/z-execute`, `/z-review-all`, etc.) requires "
        "Claude Code to execute — Copilot can only suggest the command.\n"
        "- For full harness capability use Claude Code (claude.ai/code) with the "
        "z-harness plugin installed.\n"
    )

    return "".join(parts)


# ---------------------------------------------------------------------------
# Public export function
# ---------------------------------------------------------------------------

def export(
    repo_root: Path | str,
    export_root: Path | str,
    *,
    options: dict[str, Any] | None = None,
) -> ExportResult:
    """Export z-harness capabilities to ``.github/copilot-instructions.md``.

    GitHub Copilot reads a single repository-level instructions file.  This
    driver consolidates the full z-harness command/agent/skill catalog into
    that one file.  The strategy configured in ``export.strategy`` is read
    but its effect is collapsed: even ``curated`` or ``full`` strategies
    produce the same single-file output (Copilot's file constraint is the
    binding constraint).

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.  Source directories
        ``commands/``, ``agents/``, and ``skills/`` are resolved relative to
        this path.
    export_root:
        Absolute path to the export output root directory.  The file is
        written as ``<export_root>/.github/copilot-instructions.md``.
    options:
        Reserved for future use.  Currently unused.

    Returns
    -------
    ExportResult
        ``dest``     — ``<export_root>/.github/``
        ``files``    — the single ``copilot-instructions.md`` file written
        ``fidelity`` — ``"pointer"`` (single consolidated file regardless of strategy)
        ``warnings`` — validation errors encountered (non-fatal)
    """
    repo_root = Path(repo_root).resolve()
    out_root = Path(export_root).resolve()

    # Strategy is read for informational purposes; copilot is always single-file.
    # resolve_strategy falls back to "pointer" when config is absent or invalid.
    _strategy = resolve_strategy("pointer", repo_root)

    sources = enumerate_sources(repo_root)

    warnings: list[str] = []

    # Validate that we have sources to describe.
    if not sources.get("commands") and not sources.get("agents") and not sources.get("skills"):
        warnings.append(
            "copilot: no commands, agents, or skills found under repo_root "
            f"({repo_root}); copilot-instructions.md will be sparse"
        )

    # Render the document.
    doc_content = _render_doc(sources)

    # Write to .github/copilot-instructions.md
    github_dir = out_root / ".github"
    github_dir.mkdir(parents=True, exist_ok=True)
    out_file = github_dir / "copilot-instructions.md"
    out_file.write_text(doc_content, encoding="utf-8")

    return ExportResult(
        dest=github_dir,
        files=[out_file],
        fidelity="pointer",
        warnings=warnings,
    )
