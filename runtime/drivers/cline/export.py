"""
runtime/drivers/cline/export.py

Cline export driver — emits ``.clinerules/`` markdown rule files consumed by
the `Cline <https://github.com/cline/cline>`_ VS Code extension.

Export-only asymmetry
---------------------
Cline is an EXPORT-ONLY target.  There is no HostAdapter, HostDriver, or
adapter-registry entry for this driver.  This module reads from the z-harness
source tree and writes ``.clinerules/`` files to *export_root*.  The generated
files are consumed by Cline's native rule-file loader; the z-harness runtime
cannot launch Cline or inject sessions into it.

Default strategy: ``pointer``
-----------------------------
Cline loads **every** ``.clinerules/`` file into context on every prompt.
Dumping the full z-harness rule set (100+ files) would bloat each prompt
unacceptably.  The default strategy is therefore ``pointer``: a **single**
capabilities doc is emitted that describes z-harness and explains how to
invoke slash commands via the Cline chat interface.

Users who want more rules loaded automatically may set::

    # config.toml
    [export]
    strategy = "curated"   # always-on agents only (5–10 files)
    strategy = "full"      # all commands + agents + skills (100+ files)

Body rewriting
--------------
Lines containing ``Agent(...)``, ``Skill(...)``, ``AskUserQuestion(...)``,
``TaskCreate(...)``, or ``SubagentCreate(...)`` are replaced with an HTML
comment directing the user to invoke z-harness manually.  Cline cannot
dispatch subagents or run skills natively — all fan-out must happen through
the Cline chat / slash-command interface.

Output layout (pointer — default)
----------------------------------
<export_root>/
    .clinerules/
        z-harness.md   — single pointer + capabilities doc

Output layout (curated or full)
---------------------------------
<export_root>/
    .clinerules/
        <id>.md        — one file per selected command / agent / skill

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import (
    ExportResult,
    enumerate_sources,
    resolve_strategy,
    select_sources,
)


# ---------------------------------------------------------------------------
# Pointer-strategy capabilities doc
# ---------------------------------------------------------------------------

_POINTER_DOC_ID = "z-harness"

_POINTER_DOC_BODY = """\
# z-harness — Capabilities Overview

z-harness is an AI-assisted software-development workflow harness built on
Anthropic's Claude Code SDK.  It ships slash commands, subagent definitions,
and skills that orchestrate common dev tasks (planning, implementing,
reviewing, auditing, exporting).

## This is a *pointer* export

Only this single rule file has been written to `.clinerules/`.  Cline loads
every rule file in `.clinerules/` on every prompt, so the z-harness default
strategy avoids bloating your context with 100+ files.

## How to invoke z-harness

z-harness commands are invoked as slash commands in the Cline chat interface.
Type `/z-<command>` to trigger a command, e.g.:

- `/z-plan`              — plan a feature or refactor
- `/z-implement-all`     — implement all tasks in a TASKS.md plan
- `/z-audit-plan`        — audit an existing TASKS.md plan
- `/z-review`            — run a post-implementation review pass
- `/z-export`            — export z-harness to IDE rule files
- `/z-debt`              — harvest z: debt markers from the codebase
- `/z-debug`             — iterative debug ladder

## Subagent / skill dispatch

Cline does not support native subagent fan-out or skill invocation.  Lines in
z-harness commands that contain `Agent(...)`, `Skill(...)`, or
`AskUserQuestion(...)` have been replaced with inline comments directing you
to handle those actions manually within the Cline chat.

<!-- agent dispatch / skill invocation not supported in Cline; see this file -->

## Expanding to more rules

Set `strategy = "curated"` or `strategy = "full"` in `config.toml` under
`[export]` and re-run `/z-export` (or `python3 scripts/export.py --target cline`)
to populate `.clinerules/` with the always-on agent subset or the full rule
set respectively.

## More information

- **Repository:** https://github.com/anthropics/z-harness
- **Commands:** `commands/` directory in the repository root
- **Agents:** `agents/` directory
- **Skills:** `skills/` directory
- **Config:** `config.toml` (see `scripts/config.py ensure-defaults`)
"""

_CLINE_POINTER_ENTRY: dict[str, Any] = {
    "id": _POINTER_DOC_ID,
    "source_path": None,
    "frontmatter": {
        "description": "z-harness capabilities pointer for Cline",
    },
    "body": _POINTER_DOC_BODY,
}


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Cline; "
    "invoke z-harness slash commands manually in the Cline chat -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to remove Anthropic-specific constructs.

    Lines containing ``Agent(...)``, ``Skill(...)``, ``AskUserQuestion(...)``,
    ``TaskCreate(...)``, or ``SubagentCreate(...)`` are replaced with the
    replacement comment, preserving leading whitespace.
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
# Cline rule file rendering
# ---------------------------------------------------------------------------

def _render_clinerule(entry: dict[str, Any]) -> str:
    """Render a single source *entry* as a Cline ``.clinerules/`` markdown file.

    Cline rule files are plain markdown — no YAML frontmatter is required.
    The id is used as the H1 heading, followed by the (rewritten) body.
    """
    eid = entry["id"]
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", "").strip()
    rewritten_body = _rewrite_body(body)

    # Ensure body starts clean after the heading.
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    # For the pointer entry the body is already a full document (has its own
    # H1 heading) — emit as-is without a synthetic heading.
    if eid == _POINTER_DOC_ID:
        return rewritten_body.lstrip("\n")

    # For regular entries: emit a synthetic heading and optional description.
    parts: list[str] = [f"# /{eid}\n"]
    if description:
        parts.append(f"\n> {description}\n")
    parts.append(rewritten_body)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_clinerule(path: Path) -> list[str]:
    """Basic validation: file must be non-empty markdown.

    Cline rule files have no required frontmatter — only non-empty content
    is enforced.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        errors.append(f"{path}: rule file is empty")
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
    """Export z-harness commands, agents, and skills to Cline ``.clinerules/`` files.

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.  Source directories
        ``commands/``, ``agents/``, and ``skills/`` are resolved relative to
        this path.
    export_root:
        Absolute path to the export output root directory.  Files are written
        under ``<export_root>/.clinerules/``.
    options:
        Reserved for future use.  Currently unused; any keys are silently
        ignored.

    Returns
    -------
    ExportResult
        ``dest`` is set to ``<export_root>/.clinerules/``.
        ``files`` lists every ``.md`` file written.
        ``fidelity`` is ``"pointer"`` when the pointer strategy is active
        (default), ``"flattened"`` otherwise (Agent/Skill calls replaced with
        limitation comments).
        ``warnings`` contains any validation errors encountered.

    Notes
    -----
    Default strategy is ``pointer`` — only a single capabilities doc is emitted.
    Cline loads ALL ``.clinerules/`` files on every prompt, so dumping 100+
    files would unacceptably bloat every prompt.
    """
    repo_root = Path(repo_root).resolve()
    out_root = Path(export_root).resolve()

    strategy = resolve_strategy("pointer", repo_root)

    sources = enumerate_sources(repo_root)
    selected = select_sources(
        strategy,
        sources,
        pointer_doc=_CLINE_POINTER_ENTRY,
    )

    rules_dir = out_root / ".clinerules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    emitted: list[Path] = []
    validation_errors: list[str] = []

    # Build a set of command IDs to detect skill/command name collisions.
    command_ids = {entry["id"] for entry in selected.get("commands", [])}

    for kind in ("commands", "agents", "skills"):
        for entry in selected.get(kind, []):
            eid = entry["id"]
            # Skills that share a name with a command get a "-skill" suffix
            # to avoid overwriting the command export.
            export_id = (
                f"{eid}-skill" if kind == "skills" and eid in command_ids else eid
            )
            out_path = rules_dir / f"{export_id}.md"
            out_path.write_text(_render_clinerule(entry), encoding="utf-8")
            emitted.append(out_path)

    # Validate all emitted files.
    for path in emitted:
        validation_errors.extend(_validate_clinerule(path))

    # Fidelity reflects the effective strategy.
    fidelity = "pointer" if strategy == "pointer" else "flattened"

    dest = rules_dir
    return ExportResult(
        dest=dest,
        files=emitted,
        fidelity=fidelity,
        warnings=validation_errors,
    )
