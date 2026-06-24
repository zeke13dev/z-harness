"""
runtime/drivers/windsurf/export.py

Windsurf export driver — export z-harness commands, agents, and skills to
Windsurf ``.windsurf/rules/*.md`` rule files.

Export-only asymmetry
---------------------
Windsurf is an EXPORT-ONLY target.  There is no HostAdapter, HostDriver, or
adapter-registry entry for this driver.  This module owns only the export
pipeline: it reads from the z-harness source tree and writes to *export_root*.
DO NOT register a HostAdapter and DO NOT add to the adapter registry.

Output layout
-------------
<export_root>/
    .windsurf/
        rules/
            <id>.md     — one rule file per command, agent, or skill

Rule frontmatter format
-----------------------
Windsurf rule files use YAML frontmatter with:
  - ``trigger: always_on``        — for agents in _ALWAYS_ON_AGENTS (always active)
  - ``trigger: model_decision``   — for all other sources (model decides when to apply)
  - ``globs: "<pattern>"``        — optional glob pattern (emitted when source frontmatter
                                    has a ``globs`` key; also sets ``trigger: glob``)

Agent dispatch / Skill invocation are not supported in Windsurf rules. Lines
containing ``Agent(...)``, ``Skill(...)``, ``AskUserQuestion(...)``,
``TaskCreate(...)``, or ``SubagentCreate(...)`` are replaced with a one-line
HTML comment directing the reader to CAPABILITIES.md.

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
    rewrite_unsupported_call_blocks,
)


# ---------------------------------------------------------------------------
# Body rewriting — replace Anthropic-specific constructs with hint comments
# ---------------------------------------------------------------------------

_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Windsurf; see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Rewrite whole unsupported runtime call blocks with a Windsurf hint."""
    return rewrite_unsupported_call_blocks(
        body,
        lambda _block: _REPLACEMENT_COMMENT,
    )


# ---------------------------------------------------------------------------
# Rule rendering
# ---------------------------------------------------------------------------

def _entry_trigger(entry_id: str, globs: str | None) -> str:
    """Return the windsurf trigger value for an entry.

    - ``always_on``      — for agents in _ALWAYS_ON_AGENTS
    - ``glob``           — when source frontmatter supplies a ``globs`` field
    - ``model_decision`` — for everything else
    """
    if entry_id in _ALWAYS_ON_AGENTS:
        return "always_on"
    if globs:
        return "glob"
    return "model_decision"


def _render_rule(entry: dict[str, Any]) -> str:
    """Render a z-harness source entry as a Windsurf rule file.

    Format::

        ---
        trigger: <always_on|glob|model_decision>
        globs: "<pattern>"   (only when trigger == glob)
        description: "..."   (only when trigger == model_decision)
        ---

        <rewritten body>
    """
    fm = entry["frontmatter"]
    body = entry["body"]
    entry_id = entry["id"]

    description = fm.get("description", "")
    globs = fm.get("globs", None)
    trigger = _entry_trigger(entry_id, globs)

    # Build frontmatter lines.
    fm_lines: list[str] = [f"trigger: {trigger}"]

    if trigger == "glob" and globs:
        globs_escaped = globs.replace('"', '\\"')
        fm_lines.append(f'globs: "{globs_escaped}"')
    elif trigger == "model_decision" and description:
        description_escaped = description.replace('"', '\\"')
        fm_lines.append(f'description: "{description_escaped}"')

    fm_block = "---\n" + "\n".join(fm_lines) + "\n---\n"

    rewritten_body = _rewrite_body(body)
    # Ensure body starts with a newline for readability.
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return fm_block + rewritten_body


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_VALID_TRIGGERS = frozenset({"always_on", "glob", "model_decision"})


def _validate_rule_file(path: Path) -> list[str]:
    """Basic validation: frontmatter present + trigger valid, body non-empty.

    Returns a list of error strings; empty list means valid.
    """
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")

    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors

    fm_text = m.group(1)

    # Verify trigger key is present and valid.
    trigger_m = re.search(r"^trigger\s*:\s*(\S+)", fm_text, re.MULTILINE)
    if not trigger_m:
        errors.append(f"{path}: frontmatter missing required key 'trigger'")
    elif trigger_m.group(1) not in _VALID_TRIGGERS:
        errors.append(
            f"{path}: frontmatter 'trigger' has invalid value {trigger_m.group(1)!r}; "
            f"expected one of {sorted(_VALID_TRIGGERS)}"
        )

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
    """Export z-harness commands, agents, and skills to Windsurf rule files.

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.  Source directories
        ``commands/``, ``agents/``, and ``skills/`` are resolved relative to
        this path.
    export_root:
        Absolute path to the export output root directory.  Files are written
        under ``<export_root>/.windsurf/rules/``.
    options:
        Reserved for future use.  Currently unused; any keys are silently
        ignored.

    Returns
    -------
    ExportResult
        ``dest`` is set to ``<export_root>/.windsurf/rules/``.
        ``files`` lists every ``.md`` file written.
        ``fidelity`` is ``"flattened"`` (Agent/Skill calls replaced with
        hint comments; Windsurf has no native subagent dispatch).
        ``warnings`` contains any validation errors encountered.

    Notes
    -----
    Export-only: this driver has no HostAdapter and is NOT registered in the
    adapter registry.  T015 will add it to the z-export.md target list.

    Strategy is resolved via ``resolve_strategy(repo_root, default_strategy="curated")``:

    - ``curated``  — agents filtered to ``_ALWAYS_ON_AGENTS``; commands/skills
                     passed through as-is.  Default for Windsurf.
    - ``full``     — all sources.
    - ``pointer``  — single pointer doc.
    """
    repo_root = Path(repo_root).resolve()
    out_root = Path(export_root).resolve()

    # Resolve strategy: read from config.py, fall back to "curated".
    strategy = resolve_strategy("curated", repo_root=repo_root)

    # Enumerate all sources and apply strategy filter.
    all_sources = enumerate_sources(repo_root)
    sources = select_sources(strategy, all_sources)

    # Output directory: .windsurf/rules/
    rules_dir = out_root / ".windsurf" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    emitted: list[Path] = []
    validation_errors: list[str] = []

    # Build a set of command IDs to detect skill/command name collisions.
    command_ids = {entry["id"] for entry in sources["commands"]}

    for kind in ("commands", "agents", "skills"):
        for entry in sources[kind]:
            eid = entry["id"]
            # Skills that share a name with a command get a "-skill" suffix
            # to avoid overwriting the command export.
            export_id = (
                f"{eid}-skill" if kind == "skills" and eid in command_ids else eid
            )
            out_path = rules_dir / f"{export_id}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)

            rule_content = _render_rule(entry)
            out_path.write_text(rule_content, encoding="utf-8")
            emitted.append(out_path)

    # Validate all emitted files.
    for path in emitted:
        validation_errors.extend(_validate_rule_file(path))

    dest = out_root / ".windsurf" / "rules"
    return ExportResult(
        dest=dest,
        files=emitted,
        fidelity="flattened",
        warnings=validation_errors,
    )
