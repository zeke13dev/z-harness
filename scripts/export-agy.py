"""
export-agy.py — Build Antigravity (agy) workflows and rules from z-harness sources.

Usage:
    python3 scripts/export-agy.py [--out exports/agy]

Emits:
  exports/agy/
    agy-plugin.yaml             -- z-harness export manifest (not read by agy natively)
    .agent/
      workflows/<id>.md         -- one per command (agy chat --mode <id>)
      rules/<id>.md             -- one per agent
    prompts/<id>.md             -- flat prompt files (commands + agents + skills)
    CAPABILITIES.md             -- unsupported-constructs documentation
    README.md                   -- install instructions

Frontmatter mapping:
    commands → workflow frontmatter:  description (from source or stem-based default)
    agents   → rule frontmatter:      trigger (always_on | model_decision), description

Body rewriting:
    Agent(...) / Skill(...) / AskUserQuestion(...) / TaskCreate(...) lines are replaced
    with an HTML comment directing the reader to CAPABILITIES.md.

Cascade (agy's AI) is Gemini-based; Anthropic-specific XML tags are also stripped.

After emission, basic validation is run on each generated file.
A summary count is printed at the end.
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import re
import sys
from pathlib import Path

# Allow running from repo root: python3 scripts/export-agy.py
_REPO_ROOT = Path(__file__).resolve().parent.parent

# export-common.py uses a hyphen so it is not directly importable; load via importlib.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common",
    _REPO_ROOT / "scripts" / "export-common.py",
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
validate_capabilities = _COMMON_MOD.validate_capabilities


# ---------------------------------------------------------------------------
# Body rewriting
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

def _render_workflow(entry: dict) -> str:
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

    return f"---\ndescription: {description}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# Rule rendering (.agent/rules/<id>.md)
# ---------------------------------------------------------------------------

# Agents whose names suggest they are always-on context providers.
_ALWAYS_ON_AGENTS = {
    "implementer",
    "reviewer",
    "auditor",
    "mr-reviewer",
    "remote-runner",
}


def _agent_trigger(agent_id: str) -> str:
    return "always_on" if agent_id in _ALWAYS_ON_AGENTS else "model_decision"


def _render_rule(entry: dict) -> str:
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
        frontmatter_lines.append(f"description: {description}")

    fm_block = "---\n" + "\n".join(frontmatter_lines) + "\n---\n"
    return fm_block + rewritten_body


# ---------------------------------------------------------------------------
# Prompt rendering (exports/agy/prompts/<id>.md)
# ---------------------------------------------------------------------------

def _render_prompt(entry: dict, role: str) -> str:
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

    return f"---\ndescription: {description}\nrole: {role}\n---\n{rewritten_body}"


# ---------------------------------------------------------------------------
# agy-plugin.yaml generation
# ---------------------------------------------------------------------------

def _yaml_str(value: str) -> str:
    """Emit a YAML scalar, quoting if the value contains special characters."""
    needs_quotes = any(c in value for c in (':', '#', '"', "'", '{', '}', '[', ']', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '\n'))
    if needs_quotes:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _build_manifest(sources: dict, repo_name: str = "z-harness") -> str:
    """Build the agy-plugin.yaml manifest content."""
    lines: list[str] = []

    lines.append("# agy-plugin.yaml")
    lines.append("# z-harness agy export manifest — read by scripts/export-agy.py")
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

    # Skills — inlined, not expressible natively
    lines.append("# Skills — inlined into invoking workflows; no native skill concept in agy")
    if sources["skills"]:
        lines.append("skills:")
        for entry in sources["skills"]:
            eid = entry["id"]
            source_rel = f"skills/{eid}/SKILL.md"
            lines.append(f"  - id: {eid}")
            lines.append(f"    source: {source_rel}")
            lines.append("    output: null  # inlined into parent workflow; see CAPABILITIES.md")
    else:
        lines.append("skills: []  # not expressible natively; see CAPABILITIES.md")
    lines.append("")

    # MCP hint
    lines.append("# MCP tools — optional; registered separately by the user")
    lines.append("# Listed here for documentation only; export-agy.py does not write mcp_config.json")
    lines.append("mcp_hint:")
    lines.append("  - tool: z-harness-log")
    lines.append('    description: "Would be implemented as MCP server for metrics/event logging"')
    lines.append("    status: not_implemented")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CAPABILITIES.md
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

2. **Skills / Skill inclusion** — Antigravity has no skill-loading mechanism.  Skills from
   `skills/*/SKILL.md` must be inlined into the invoking workflow's Markdown body.  Note the
   12,000-character content limit per workflow file.

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
  format.  Antigravity does not read this file; it is used only by `scripts/export-agy.py`
  to document the mapping between source files and generated output.
"""


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------

_README_MD = """\
# z-harness → Antigravity (agy) Export

This directory contains z-harness commands and agents exported as Antigravity
(Google's agy IDE) workflow and rule files.

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

Run the export script from the repo root:

```bash
python3 scripts/export-agy.py
# or with a custom output directory:
python3 scripts/export-agy.py --out /path/to/output
```

## Known limitations

See `CAPABILITIES.md` for a full list of z-harness features that cannot be
expressed in Antigravity (subagent dispatch, skills, multi-model review, etc.).
"""


# ---------------------------------------------------------------------------
# Validation helpers
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
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export z-harness commands/agents/skills to Antigravity (agy) format."
    )
    p.add_argument(
        "--out",
        default="exports/agy",
        help="Output root directory (default: exports/agy)",
    )
    p.add_argument(
        "--repo",
        default=str(_REPO_ROOT),
        help="Repository root (default: parent of this script's directory)",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    repo_root = Path(args.repo).resolve()
    out_root = (
        (repo_root / args.out)
        if not Path(args.out).is_absolute()
        else Path(args.out)
    )

    sources = enumerate_sources(repo_root)

    emitted_workflows: list[Path] = []
    emitted_rules: list[Path] = []
    emitted_prompts: list[Path] = []

    # --- Workflows (commands) ---
    workflows_dir = out_root / ".agent" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    for entry in sources["commands"]:
        eid = entry["id"]
        out_path = workflows_dir / f"{eid}.md"
        out_path.write_text(_render_workflow(entry), encoding="utf-8")
        emitted_workflows.append(out_path)

    # --- Rules (agents) ---
    rules_dir = out_root / ".agent" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    for entry in sources["agents"]:
        eid = entry["id"]
        out_path = rules_dir / f"z-harness-{eid}.md"
        out_path.write_text(_render_rule(entry), encoding="utf-8")
        emitted_rules.append(out_path)

    # --- Prompts (commands + agents + skills, flat) ---
    prompts_dir = out_root / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for entry in sources["commands"]:
        out_path = prompts_dir / f"{entry['id']}.md"
        out_path.write_text(_render_prompt(entry, "workflow"), encoding="utf-8")
        emitted_prompts.append(out_path)
    for entry in sources["agents"]:
        out_path = prompts_dir / f"{entry['id']}.md"
        out_path.write_text(_render_prompt(entry, "rule"), encoding="utf-8")
        emitted_prompts.append(out_path)
    for entry in sources["skills"]:
        # Prefix with "skill-" to avoid collision with same-named commands.
        out_path = prompts_dir / f"skill-{entry['id']}.md"
        out_path.write_text(_render_prompt(entry, "skill"), encoding="utf-8")
        emitted_prompts.append(out_path)

    # --- agy-plugin.yaml ---
    manifest_path = out_root / "agy-plugin.yaml"
    manifest_path.write_text(_build_manifest(sources), encoding="utf-8")

    # --- CAPABILITIES.md ---
    caps_path = out_root / "CAPABILITIES.md"
    caps_path.write_text(_CAPABILITIES_MD, encoding="utf-8")

    # --- README.md ---
    readme_path = out_root / "README.md"
    readme_path.write_text(_README_MD, encoding="utf-8")

    # --- Validation ---
    validation_errors: list[str] = []
    for path in emitted_workflows:
        validation_errors.extend(_validate_workflow(path))
    for path in emitted_rules:
        validation_errors.extend(_validate_rule(path))
    for path in emitted_prompts:
        validation_errors.extend(_validate_prompt(path))
    cap_errors = validate_capabilities(caps_path)
    for err in cap_errors:
        validation_errors.append(f"CAPABILITIES.md: {err}")

    # --- Summary ---
    total = len(emitted_workflows) + len(emitted_rules) + len(emitted_prompts)
    print(f"export-agy: emitted {len(emitted_workflows)} workflows, "
          f"{len(emitted_rules)} rules, {len(emitted_prompts)} prompts "
          f"to {out_root}")
    print(f"  agy-plugin.yaml: {manifest_path}")
    print(f"  CAPABILITIES.md: {caps_path}")
    print(f"  README.md:       {readme_path}")

    if validation_errors:
        print(f"\nValidation errors ({len(validation_errors)}):")
        for err in validation_errors:
            print(f"  ERROR: {err}")
        return 1

    print(f"  all {total} prompt/workflow/rule files passed validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
