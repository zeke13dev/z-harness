"""
runtime/drivers/antigravity/export.py

Antigravity (agy) export driver — commands, agents, and skills.

Strict no-behavior-change port of ``scripts/export-agy.py`` wrapped in the
``export()`` entry point that the runtime expects.  All rendering logic is
preserved verbatim from the legacy script.  Any quirk from the legacy script
is noted with a ``# preserved quirk:`` comment.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Write Antigravity workflow / rule / skill / prompt files under
    *export_root* and return an ``ExportResult``.

    Parameters
    ----------
    repo_root:
        Absolute (or relative) path to the z-harness repository root.
    export_root:
        Destination directory.  Created if absent.
    options:
        Reserved for future use; ignored.

    Returns
    -------
    ExportResult
        ``dest``    — resolved *export_root*
        ``files``   — every file written
        ``fidelity``— ``"high"`` (antigravity supports native workflows/rules/skills)
        ``warnings``— validation warnings (non-fatal; details echoed to stderr)

Output layout
-------------
<export_root>/
    agy-plugin.yaml
    CAPABILITIES.md
    README.md
    .agent/
        workflows/<id>.md        — one per command
        rules/z-harness-<id>.md  — one per agent
        skills/<id>/SKILL.md     — one per skill
    prompts/
        <id>.md                  — flat prompt (commands, role=workflow)
        <id>.md                  — flat prompt (agents,   role=rule)
        skill-<id>.md            — flat prompt (skills,   role=skill)

Agent trigger assignment
------------------------
Agents in ``_ALWAYS_ON_AGENTS`` get ``trigger: always_on``; all others get
``trigger: model_decision``.  This set is preserved exactly from the legacy
script.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import (
    ExportResult,
    _ALWAYS_ON_AGENTS,
    enumerate_sources,
    validate_capabilities,
)


# ---------------------------------------------------------------------------
# Always-on agent set (imported from _export_utils — single source of truth)
# ---------------------------------------------------------------------------

# _ALWAYS_ON_AGENTS is defined in runtime/drivers/_export_utils.py (T010).
# It is imported above so antigravity/export.py and any helper that calls
# select_sources(..., strategy="curated") always use the same set.


# ---------------------------------------------------------------------------
# YAML scalar quoting (ported verbatim from legacy)
# ---------------------------------------------------------------------------

def _yaml_str(value: str) -> str:
    """Emit a YAML scalar, quoting if the value contains special characters."""
    needs_quotes = any(c in value for c in (':', '#', '"', "'", '{', '}', '[', ']', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '\n'))
    if needs_quotes:
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        return f'"{escaped}"'
    return value


# ---------------------------------------------------------------------------
# Body rewriting (ported verbatim from legacy)
# ---------------------------------------------------------------------------

_AGENT_CALL_RE = re.compile(r"Agent\s*\(", re.MULTILINE)
_SKILL_CALL_RE = re.compile(r"Skill\s*\(", re.MULTILINE)
_TOOL_SCHEMA_RE = re.compile(
    r"AskUserQuestion\s*\(|TaskCreate\s*\(|SubagentCreate\s*\(", re.MULTILINE
)

_REPLACEMENT_COMMENT = (
    "<!-- agent dispatch / skill invocation not supported in Antigravity; "
    "see CAPABILITIES.md -->"
)


def _rewrite_body(body: str) -> str:
    """Replace Anthropic-specific construct call-sites with an HTML comment."""
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
# Workflow rendering (.agent/workflows/<id>.md)
# ---------------------------------------------------------------------------

def _render_workflow(entry: dict[str, Any]) -> str:
    """Render a command entry as an Antigravity workflow .md file."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", f"z-harness {entry['id']} workflow")
    # Strip any embedded '---' from description to avoid YAML delimiter conflict.
    description = description.replace("---", "—")
    # Truncate to 250-char limit.
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return f"---\ndescription: {_yaml_str(description)}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# Rule rendering (.agent/rules/<id>.md)
# ---------------------------------------------------------------------------

def _agent_trigger(agent_id: str) -> str:
    return "always_on" if agent_id in _ALWAYS_ON_AGENTS else "model_decision"


def _render_rule(entry: dict[str, Any]) -> str:
    """Render an agent entry as an Antigravity rule .md file."""
    fm = entry["frontmatter"]
    body = entry["body"]

    agent_id = entry["id"]
    trigger = _agent_trigger(agent_id)

    description = fm.get("description", f"z-harness {agent_id} agent context")
    description = description.replace("---", "—")
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    frontmatter_lines = [f"trigger: {trigger}"]
    if trigger == "model_decision":
        frontmatter_lines.append(f"description: {_yaml_str(description)}")

    fm_block = "---\n" + "\n".join(frontmatter_lines) + "\n---\n"
    return fm_block + rewritten_body


# ---------------------------------------------------------------------------
# Skill rendering (.agent/skills/<id>/SKILL.md)
# ---------------------------------------------------------------------------

def _render_skill(entry: dict[str, Any]) -> str:
    """Render a skill entry as an Antigravity skill SKILL.md file."""
    fm = entry["frontmatter"]
    body = entry["body"]

    skill_id = entry["id"]
    description = fm.get("description", f"z-harness {skill_id} skill")
    description = description.replace("---", "—")
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return f"---\nname: {skill_id}\ndescription: {_yaml_str(description)}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# Prompt rendering (prompts/<id>.md)
# ---------------------------------------------------------------------------

def _render_prompt(entry: dict[str, Any], role: str) -> str:
    """Render a flat prompt file with YAML frontmatter (description, role)."""
    fm = entry["frontmatter"]
    body = entry["body"]

    description = fm.get("description", f"z-harness {entry['id']}")
    description = description.replace("---", "—")
    if len(description) > 250:
        description = description[:247] + "..."

    rewritten_body = _rewrite_body(body)
    if rewritten_body and not rewritten_body.startswith("\n"):
        rewritten_body = "\n" + rewritten_body

    return f"---\ndescription: {_yaml_str(description)}\nrole: {role}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# agy-plugin.yaml generation (ported verbatim from legacy)
# ---------------------------------------------------------------------------

def _build_manifest(sources: dict[str, list[dict[str, Any]]], repo_name: str = "z-harness") -> str:
    """Build the agy-plugin.yaml manifest content."""
    lines: list[str] = []

    lines.append("# agy-plugin.yaml")
    lines.append("# z-harness agy export manifest — read by runtime/drivers/antigravity/export.py")
    lines.append("# NOT a native Antigravity file format (agy does not read this)")
    lines.append("schema_version: 1")
    lines.append("")
    lines.append("metadata:")
    lines.append(f"  name: {repo_name}")
    lines.append("  description: z-harness planning and implementation workflow for Antigravity IDE")
    lines.append("  source_repo: https://github.com/zeke-tools/z-harness")
    lines.append("")

    # Commands → workflows
    lines.append("# Commands → .agent/workflows/*.md")
    lines.append("# Each command becomes a custom chat mode (agy chat --mode <id>)")
    lines.append("workflows:")
    for entry in sources["commands"]:
        eid = entry["id"]
        fm = entry["frontmatter"]
        description = fm.get("description", f"z-harness {eid} workflow")
        description = description.replace("---", "—")
        if len(description) > 250:
            description = description[:247] + "..."
        source_rel = f"commands/{entry['source_path'].name}"
        lines.append(f"  - id: {eid}")
        lines.append(f"    source: {source_rel}")
        lines.append(f"    output: .agent/workflows/{eid}.md")
        lines.append(f"    description: {_yaml_str(description)}")
    lines.append("")

    # Agents → rules
    lines.append("# Agents → .agent/rules/*.md")
    lines.append("# No subagent dispatch in agy; agents become role-specific rule files")
    lines.append("rules:")
    for entry in sources["agents"]:
        eid = entry["id"]
        fm = entry["frontmatter"]
        description = fm.get("description", f"z-harness {eid} agent context")
        description = description.replace("---", "—")
        if len(description) > 250:
            description = description[:247] + "..."
        trigger = _agent_trigger(eid)
        source_rel = f"agents/{entry['source_path'].name}"
        lines.append(f"  - id: {eid}")
        lines.append(f"    source: {source_rel}")
        lines.append(f"    output: .agent/rules/z-harness-{eid}.md")
        lines.append(f"    trigger: {trigger}")
        lines.append(f"    description: {_yaml_str(description)}")
    lines.append("")

    # Skills → .agent/skills/<id>/SKILL.md (only when skill sources exist;
    # the skills/ source dir was removed in favor of commands/-only exports).
    if sources["skills"]:
        lines.append("# Skills → .agent/skills/<id>/SKILL.md")
        lines.append("# Native workspace skills in Antigravity")
        lines.append("skills:")
        for entry in sources["skills"]:
            eid = entry["id"]
            source_rel = f"skills/{eid}/SKILL.md"
            lines.append(f"  - id: {eid}")
            lines.append(f"    source: {source_rel}")
            lines.append(f"    output: .agent/skills/{eid}/SKILL.md")
            fm = entry["frontmatter"]
            description = fm.get("description", f"z-harness {eid} skill")
            description = description.replace("---", "—")
            if len(description) > 250:
                description = description[:247] + "..."
            lines.append(f"    description: {_yaml_str(description)}")
    else:
        lines.append("skills: []")
    lines.append("")

    # MCP hint
    lines.append("# MCP tools — optional; registered separately by the user")
    lines.append("# Listed here for documentation only; the runtime driver does not write mcp_config.json")
    lines.append("mcp_hint:")
    lines.append("  - tool: z-harness-log")
    lines.append('    description: "Would be implemented as MCP server for metrics/event logging"')
    lines.append("    status: not_implemented")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CAPABILITIES.md (ported verbatim from legacy)
# ---------------------------------------------------------------------------

_CAPABILITIES_MD = """\
# Antigravity (agy) Export — CAPABILITIES.md

This document describes what the z-harness feature set can and cannot express
when exported to Antigravity IDE (Google's agy / Cascade agent platform).

---

## Supported

The following z-harness constructs have direct or near-direct equivalents in Antigravity:

| z-harness construct | Antigravity equivalent |
|---------------------|----------------------|
| `commands/*.md` (slash commands) | `.agent/workflows/<name>.md` — custom chat modes (`agy chat --mode <id>`) |
| `agents/*.md` (agent definitions) | `.agent/rules/<name>.md` — always_on or model_decision rules |
| `Bash`, `Read`, `Edit`, `Write` tools | Cascade native tools (exact names may differ; semantics are equivalent) |
| `AskUserQuestion` tool (clarification) | Cascade conversational turn (native; no special syntax needed) |
| `WebFetch`, `WebSearch` tools | Cascade native (if enabled in the workspace) |
| Markdown body / instruction content | Passed as system-level instructions to Cascade (Gemini-based) |
| `metrics.jsonl` shell writes | Shell commands in workflow bodies work; writes to workspace-relative paths |

---

## Unsupported

The following z-harness features have no native Antigravity equivalent:

1. **Subagent dispatch (`Agent(subagent_type=...)`)** — Cascade exposes no `Agent()` builtin
   and no `.agent/subagents/` directory.  Workaround: call `agy chat --mode <workflow-id>`
   from a shell command in the workflow body. This does not nest within a running Cascade
   session; it launches a new top-level session.

2. **Programmatic Skill Invocation (`Skill(name=...)`)** — Although Antigravity natively
   supports workspace skills under `.agent/skills/<name>/SKILL.md`, it does not support
   programmatic `Skill()` runtime API calls or dynamic inclusion. Downstream actions that rely
   on programmatic skill loading must be handled as instructions directing Cascade to load the
   appropriate workspace skill.

3. **Provider registry (`providers.json`, `resolve-provider.sh`)** — Cascade is bound to
   Gemini; there is no multi-provider routing mechanism.  All provider-routing logic in
   `scripts/resolve-provider.sh` is inapplicable.

4. **Multi-model review loop** — `/z-review-all` dispatches Codex + Gemini reviewers in
   parallel.  Single-provider Cascade cannot replicate this pattern; only one reviewer
   (the Cascade agent itself) is available.

5. **`Z_HARNESS_PLANS_DIR` + `plan-path.sh` env injection** — Cascade workflows cannot
   receive injected environment variables at load time.  Any path that z-harness resolves
   via `$Z_HARNESS_PLANS_DIR` must be hardcoded or assumed to be the workspace root in the
   exported workflow body.

6. **`metrics.jsonl` event stream (structured)** — `log-event.sh` and `log-phase.sh` write
   JSONL files.  These shell commands work inside workflow bodies but require the workspace
   to be writable at the expected paths.  The `TOKEN=` handshake pattern (start → end)
   may not survive across Cascade turns if the agent context is reset.

7. **`AskUserQuestion` structured return** — Claude Code's `AskUserQuestion` tool pauses
   execution and returns a typed answer object.  Cascade's equivalent is a conversational
   turn with no structured return value; downstream logic that branches on the answer type
   must be restructured as plain Markdown instructions.

8. **Workflow bodies > 12,000 characters** — Several z-harness commands (e.g., `z-plan`)
   exceed the Antigravity content limit for workflow files.  Mitigation: split into
   sub-workflows, or link to an external file if `@file` syntax is supported (unconfirmed
   as of agy 1.107.0).

---

## Notes

- **Gemini prompt norms:** Cascade is Gemini-based.  Anthropic-specific XML tags (e.g.,
  `<parameter name="thinking">`, `<result>`) are stripped during export and should not appear in
  workflow bodies.  Use clear imperative Markdown headings instead.

- **Workflow file placement:** Antigravity auto-discovers `.agent/workflows/**/*.md` by
  watching the workspace directory tree.  No install step is required after copying files.
  For global scope (available across all workspaces), place workflow files at:
  `~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/<name>.md`

- **Rule trigger values:** `always_on` (every session), `model_decision` (model chooses
  based on `description`), `glob` (applied when matching files are in context).

- **`agy-plugin.yaml`** is a z-harness convention manifest, not a native Antigravity
  format.  Antigravity does not read this file; it is generated by `runtime/drivers/antigravity/export.py`
  to document the mapping between source files and generated output.
"""


# ---------------------------------------------------------------------------
# README.md (ported verbatim from legacy)
# ---------------------------------------------------------------------------

_README_MD = """\
# z-harness → Antigravity (agy) Export

This directory contains z-harness commands, agents, and skills exported as Antigravity
(Google's agy IDE) workflow, rule, and skill files.

## What's included

| Path | Purpose |
|------|---------|
| `.agent/workflows/*.md` | Custom chat modes — one per z-harness command |
| `.agent/rules/*.md` | Always-on or model-decision rules — one per z-harness agent |
| `prompts/*.md` | Flat prompt files (description + role frontmatter) |
| `agy-plugin.yaml` | Export manifest (z-harness convention; not read by agy) |
| `CAPABILITIES.md` | What can and cannot be expressed in Antigravity |

## Install

### Per-project (recommended)

Copy the `.agent/` directory into your project workspace root:

```bash
cp -r exports/agy/.agent /path/to/your/project/
```

Antigravity auto-discovers `.agent/workflows/**/*.md` and `.agent/rules/**/*.md`
by watching the workspace directory tree.  No restart required — files become
available immediately in the IDE.

### Global (all workspaces)

To make workflows available across all projects, copy them to the global workflows path:

```bash
mkdir -p ~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/
cp exports/agy/.agent/workflows/*.md \\
  ~/.antigravity/antigravity/data/User/globalStorage/antigravity.antigravity/global_workflows/
```

## Usage

After installing, invoke a workflow from the command line:

```bash
agy chat --mode z-plan "Add user authentication feature"
agy chat --mode z-implement-next
agy chat --mode z-review-all
```

Or select the mode from the Antigravity IDE mode picker in the chat panel.

## Re-generating

Run the exporter from the repo root:

```bash
python3 -m z_harness_cli export --host antigravity
# or with a custom output directory:
python3 -m z_harness_cli export --host antigravity --out /path/to/output
```

## Known limitations

See `CAPABILITIES.md` for a full list of z-harness features that cannot be
expressed in Antigravity (subagent dispatch, skills, multi-model review, etc.).
"""


# ---------------------------------------------------------------------------
# Validation helpers (ported verbatim from legacy)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _validate_workflow(path: Path) -> list[str]:
    """Validate an Antigravity workflow .md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    if not re.search(r"^description\s*:", fm_text, re.MULTILINE):
        errors.append(f"{path}: workflow frontmatter missing 'description'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


def _validate_rule(path: Path) -> list[str]:
    """Validate an Antigravity rule .md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    if not re.search(r"^trigger\s*:", fm_text, re.MULTILINE):
        errors.append(f"{path}: rule frontmatter missing 'trigger'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


def _validate_skill(path: Path) -> list[str]:
    """Validate an Antigravity skill SKILL.md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    for key in ("name", "description"):
        if not re.search(rf"^{key}\s*:", fm_text, re.MULTILINE):
            errors.append(f"{path}: skill frontmatter missing '{key}'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


def _validate_prompt(path: Path) -> list[str]:
    """Validate a flat prompt .md file."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"{path}: missing or malformed frontmatter (expected --- fences)")
        return errors
    fm_text = m.group(1)
    for key in ("description", "role"):
        if not re.search(rf"^{key}\s*:", fm_text, re.MULTILINE):
            errors.append(f"{path}: prompt frontmatter missing '{key}'")
    body = text[m.end():]
    if not body.strip():
        errors.append(f"{path}: body is empty")
    return errors


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def export(
    repo_root: str | Path,
    export_root: str | Path,
    *,
    options: object | None = None,
) -> ExportResult:
    """Export z-harness commands, agents, and skills to Antigravity (agy) format.

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.
    export_root:
        Destination directory.  Created (with parents) if absent.
    options:
        Reserved for future use; ignored.

    Returns
    -------
    ExportResult
        ``dest``    — resolved *export_root*
        ``files``   — every file written during this export
        ``fidelity``— ``"high"``
        ``warnings``— non-fatal validation warnings
    """
    repo_root = Path(repo_root).resolve()
    out_root = Path(export_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    sources = enumerate_sources(repo_root)

    emitted_files: list[Path] = []
    emitted_workflows: list[Path] = []
    emitted_rules: list[Path] = []
    emitted_skills: list[Path] = []
    emitted_prompts: list[Path] = []

    # --- Workflows (commands) ---
    workflows_dir = out_root / ".agent" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    for entry in sources["commands"]:
        eid = entry["id"]
        out_path = workflows_dir / f"{eid}.md"
        out_path.write_text(_render_workflow(entry), encoding="utf-8")
        emitted_workflows.append(out_path)
        emitted_files.append(out_path)

    # --- Rules (agents) ---
    rules_dir = out_root / ".agent" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    for entry in sources["agents"]:
        eid = entry["id"]
        out_path = rules_dir / f"z-harness-{eid}.md"
        out_path.write_text(_render_rule(entry), encoding="utf-8")
        emitted_rules.append(out_path)
        emitted_files.append(out_path)

    # --- Skills (skills) ---
    skills_dir = out_root / ".agent" / "skills"
    for entry in sources["skills"]:
        eid = entry["id"]
        skill_dir = skills_dir / eid
        skill_dir.mkdir(parents=True, exist_ok=True)
        out_path = skill_dir / "SKILL.md"
        out_path.write_text(_render_skill(entry), encoding="utf-8")
        emitted_skills.append(out_path)
        emitted_files.append(out_path)

    # --- Prompts (commands + agents + skills, flat) ---
    prompts_dir = out_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for entry in sources["commands"]:
        out_path = prompts_dir / f"{entry['id']}.md"
        out_path.write_text(_render_prompt(entry, "workflow"), encoding="utf-8")
        emitted_prompts.append(out_path)
        emitted_files.append(out_path)
    for entry in sources["agents"]:
        out_path = prompts_dir / f"{entry['id']}.md"
        out_path.write_text(_render_prompt(entry, "rule"), encoding="utf-8")
        emitted_prompts.append(out_path)
        emitted_files.append(out_path)
    for entry in sources["skills"]:
        # Prefix with "skill-" to avoid collision with same-named commands.
        # preserved quirk: skill- prefix for flat prompt to avoid name collisions
        out_path = prompts_dir / f"skill-{entry['id']}.md"
        out_path.write_text(_render_prompt(entry, "skill"), encoding="utf-8")
        emitted_prompts.append(out_path)
        emitted_files.append(out_path)

    # --- agy-plugin.yaml ---
    manifest_path = out_root / "agy-plugin.yaml"
    manifest_path.write_text(_build_manifest(sources), encoding="utf-8")
    emitted_files.append(manifest_path)

    # --- CAPABILITIES.md ---
    caps_path = out_root / "CAPABILITIES.md"
    caps_path.write_text(_CAPABILITIES_MD, encoding="utf-8")
    emitted_files.append(caps_path)

    # --- README.md ---
    readme_path = out_root / "README.md"
    readme_path.write_text(_README_MD, encoding="utf-8")
    emitted_files.append(readme_path)

    # --- Validation (collect warnings, do not raise) ---
    warnings: list[str] = []
    validation_errors: list[str] = []
    for path in emitted_workflows:
        validation_errors.extend(_validate_workflow(path))
    for path in emitted_rules:
        validation_errors.extend(_validate_rule(path))
    for path in emitted_skills:
        validation_errors.extend(_validate_skill(path))
    for path in emitted_prompts:
        validation_errors.extend(_validate_prompt(path))
    cap_errors = validate_capabilities(caps_path)
    for err in cap_errors:
        validation_errors.append(f"CAPABILITIES.md: {err}")

    for err in validation_errors:
        warnings.append(err)
        print(f"  WARNING: {err}", file=sys.stderr)

    return ExportResult(
        dest=out_root,
        files=emitted_files,
        fidelity="high",
        warnings=warnings,
    )
