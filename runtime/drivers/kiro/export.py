"""
runtime/drivers/kiro/export.py

Kiro (https://kiro.dev) export driver — export-only pattern.

Kiro uses a "steering" document system: markdown files placed under
``.kiro/steering/`` are loaded into context with an ``inclusion:`` frontmatter
key that controls when the doc is active:

    inclusion: always       — loaded on every task
    inclusion: manual       — loaded only when explicitly referenced
    inclusion: fileMatch    — loaded when files matching ``fileMatchPattern:``
                              are in context

This driver emits one ``.kiro/steering/<id>.md`` file per source entry,
assigning ``inclusion:`` based on the export strategy and whether the agent
is in the always-on subset:

    - always-on agents (``_ALWAYS_ON_AGENTS``) → ``inclusion: always``
    - all other sources                         → ``inclusion: manual``

No HostAdapter, no adapter registry entry for kiro.  This module is
export-only: it reads from the z-harness source tree and writes to
``<export_root>/.kiro/steering/``.

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
    _ALWAYS_ON_AGENTS,
    enumerate_sources,
    resolve_strategy,
    select_sources,
)


# ---------------------------------------------------------------------------
# Body rewriting — Agent()/Skill() call sites → kiro hint comments
# ---------------------------------------------------------------------------

_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Kiro; see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite *body* to replace Anthropic-specific constructs with Kiro hints.

    Lines containing ``Agent(...)``, ``Skill(...)``, ``AskUserQuestion(...)``,
    ``TaskCreate(...)``, or ``SubagentCreate(...)`` are replaced with a
    one-line HTML comment directing the reader to CAPABILITIES.md.  Leading
    whitespace is preserved for readability.
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
# Kiro steering frontmatter rendering
# ---------------------------------------------------------------------------

def _yaml_quote(value: str) -> str:
    """Quote a scalar for the flat YAML frontmatter the Kiro loader parses."""
    if re.search(r'[:\[\]{}#"\']', value) or value != value.strip():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_steering_doc(
    entry: dict[str, Any],
    *,
    inclusion: str,
    file_match_pattern: str | None = None,
) -> str:
    """Render a single source *entry* as a Kiro steering document string.

    Parameters
    ----------
    entry:
        Source entry dict from :func:`enumerate_sources`.
    inclusion:
        Kiro ``inclusion:`` value — one of ``always``, ``manual``, or
        ``fileMatch``.
    file_match_pattern:
        When *inclusion* is ``"fileMatch"``, the glob pattern to attach as
        ``fileMatchPattern:``.  Ignored for other inclusion modes.
    """
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", "")
    description_escaped = _yaml_quote(description)

    lines = [
        "---\n",
        f"inclusion: {inclusion}\n",
    ]
    if description:
        lines.append(f"description: {description_escaped}\n")
    if inclusion == "fileMatch" and file_match_pattern:
        lines.append(f"fileMatchPattern: {file_match_pattern}\n")
    lines.append("---\n")

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return "".join(lines) + rewritten_body


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

_VALID_INCLUSION_VALUES = frozenset({"always", "manual", "fileMatch"})


def _validate_steering_doc(path: Path) -> list[str]:
    """Validate a Kiro steering document.

    Checks:
    - Frontmatter fences present and parseable.
    - ``inclusion:`` key present with a valid value.
    - Body is non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors

    fm_text = m.group(1)

    # Check inclusion: key
    inclusion_match = re.search(r"^inclusion\s*:\s*(\S+)", fm_text, re.MULTILINE)
    if not inclusion_match:
        errors.append(f"{path}: frontmatter missing required key 'inclusion'")
    else:
        val = inclusion_match.group(1).strip()
        if val not in _VALID_INCLUSION_VALUES:
            errors.append(
                f"{path}: invalid inclusion value {val!r}; "
                f"expected one of {sorted(_VALID_INCLUSION_VALUES)}"
            )

    # Check non-empty body
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
    """Export z-harness commands, agents, and skills to Kiro steering documents.

    Parameters
    ----------
    repo_root:
        Absolute (or relative) path to the z-harness repository root.
        Source directories ``commands/``, ``agents/``, and ``skills/`` are
        resolved relative to this path.
    export_root:
        Destination directory.  Steering documents are written to
        ``<export_root>/.kiro/steering/``.  Created if absent.
    options:
        Reserved for future use; ignored.

    Returns
    -------
    ExportResult
        ``dest``    — resolved ``<export_root>/.kiro/steering/``
        ``files``   — every file written
        ``fidelity``— ``"flattened"`` (Agent/Skill calls replaced with hint comments)
        ``warnings``— validation errors encountered (non-fatal)

    Strategy
    --------
    Default strategy is ``curated`` (reads ``config.py get export.strategy``).
    In ``curated`` mode:

    - Agents in ``_ALWAYS_ON_AGENTS`` → ``inclusion: always``
    - All other sources               → ``inclusion: manual``

    In ``full`` mode:

    - Same inclusion rules as curated but ALL agents/commands/skills are emitted.

    In ``pointer`` mode:

    - Single pointer document → ``inclusion: always``

    Export-only asymmetry
    ---------------------
    Kiro is an EXPORT-ONLY target.  There is no HostAdapter or adapter registry
    entry for kiro.  This module owns only the export pipeline.
    """
    repo_root = Path(repo_root).resolve()
    out_root = Path(export_root).resolve()
    steering_dir = out_root / ".kiro" / "steering"
    steering_dir.mkdir(parents=True, exist_ok=True)

    strategy = resolve_strategy("curated", repo_root)
    all_sources = enumerate_sources(repo_root)
    sources = select_sources(strategy, all_sources)

    # Build set of always-on agent IDs for inclusion assignment.
    # In pointer mode, the single pointer entry gets always; otherwise
    # members of _ALWAYS_ON_AGENTS get always and everything else gets manual.
    always_on_ids: frozenset[str]
    if strategy == "pointer":
        # The pointer doc itself should be always
        always_on_ids = frozenset({"z-harness-pointer"})
    else:
        always_on_ids = _ALWAYS_ON_AGENTS

    emitted: list[Path] = []
    validation_errors: list[str] = []

    # Build set of command IDs to detect skill/command name collisions.
    all_command_ids = {entry["id"] for entry in all_sources["commands"]}

    for kind in ("commands", "agents", "skills"):
        for entry in sources.get(kind, []):
            eid = entry["id"]
            # Skills that share a name with a command get a "-skill" suffix.
            export_id = (
                f"{eid}-skill" if kind == "skills" and eid in all_command_ids else eid
            )

            # Determine inclusion: always-on agents → always; everything else → manual.
            if kind == "agents" and eid in always_on_ids:
                inclusion = "always"
            else:
                inclusion = "manual"

            content = _render_steering_doc(entry, inclusion=inclusion)
            out_path = steering_dir / f"{export_id}.md"
            out_path.write_text(content, encoding="utf-8")
            emitted.append(out_path)

    # Validate all emitted files.
    for path in emitted:
        validation_errors.extend(_validate_steering_doc(path))

    dest = steering_dir
    return ExportResult(
        dest=dest,
        files=emitted,
        fidelity="flattened",
        warnings=validation_errors,
    )
