# DEPRECATED: frozen at v0.1.0. Remove after v0.2.0. See C6-D1.
"""
export-codex.py — Build Codex CLI prompt files from z-harness commands, agents, and skills.

Usage:
    python3 scripts/export-codex.py [--out exports/codex]

Emits one prompt .md file per command / skill into:
    exports/codex/prompts/<id>.md

Agents are consolidated into:
    exports/codex/AGENTS.md   (one ## <agent-id> section per agent)

Body rewriting:
    Lines invoking Agent(...), Skill(...), AskUserQuestion(...) are replaced
    with an HTML comment directing the reader to CAPABILITIES.md.
"""

# ---------------------------------------------------------------------------
# Format research note
#
# Codex CLI (OpenAI) reads task prompts via stdin:
#     cat prompts/<id>.md | codex exec -
#
# The recommended pattern for batch/template usage is to maintain a directory
# of prompt files and pipe them on demand.  There is no native "prompt
# library" concept built into the Codex CLI binary itself — the per-file
# convention is an empirical best-practice observed in the community.  From
# `codex --help` and the openai-codex README:
#
#     codex exec -          # reads the task prompt from stdin
#     codex exec <task>     # inline string task
#
# So each z-harness command/skill maps to one prompt file:
#     exports/codex/prompts/<id>.md
# Users either pipe it:
#     cat exports/codex/prompts/z-plan.md | codex exec -
# Or reference it from a wrapper script.
#
# Agents are consolidated into AGENTS.md because Codex CLI has no native
# subagent dispatch — the file documents the agent roles so users can manually
# invoke the right prompt.
#
# Anthropic-specific constructs (Agent(), Skill(), AskUserQuestion()) are
# replaced with HTML comments referencing CAPABILITIES.md.
# ---------------------------------------------------------------------------

from __future__ import annotations

import argparse
import importlib.util as _ilu
import re
import sys
from pathlib import Path

# Allow running from repo root: python3 scripts/export-codex.py
_REPO_ROOT = Path(__file__).resolve().parent.parent

# export-common.py uses a hyphen so it is not directly importable; load it
# via importlib instead.
_COMMON_SPEC = _ilu.spec_from_file_location(
    "export_common",
    _REPO_ROOT / "scripts" / "export-common.py",
)
_COMMON_MOD = _ilu.module_from_spec(_COMMON_SPEC)
_COMMON_SPEC.loader.exec_module(_COMMON_MOD)

enumerate_sources = _COMMON_MOD.enumerate_sources
output_path_for = _COMMON_MOD.output_path_for
validate_capabilities = _COMMON_MOD.validate_capabilities


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

def _render_prompt(entry: dict) -> str:
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

def _render_agents_md(agents: list[dict]) -> str:
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
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export z-harness commands/agents/skills to Codex CLI prompt files."
    )
    p.add_argument(
        "--out",
        default="exports/codex",
        help="Output root directory (default: exports/codex)",
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

    emitted: list[Path] = []
    validation_errors: list[str] = []

    # Build a set of command IDs to detect skill/command name collisions.
    command_ids = {entry["id"] for entry in sources["commands"]}

    # --- Emit prompt files for commands and skills ---
    for kind in ("commands", "skills"):
        for entry in sources[kind]:
            eid = entry["id"]
            # Skills that share a name with a command get a "-skill" suffix
            # to avoid overwriting the command export.
            export_id = f"{eid}-skill" if kind == "skills" and eid in command_ids else eid
            out_path = output_path_for(repo_root, "codex", kind, export_id)
            default_base = repo_root / "exports" / "codex"
            if out_root != default_base:
                relative = out_path.relative_to(default_base)
                out_path = out_root / relative

            out_path.parent.mkdir(parents=True, exist_ok=True)
            content = _render_prompt(entry)
            out_path.write_text(content, encoding="utf-8")
            emitted.append(out_path)

    # --- Emit consolidated AGENTS.md ---
    agents_path = out_root / "AGENTS.md"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_md = _render_agents_md(sources["agents"])
    agents_path.write_text(agents_md, encoding="utf-8")

    # --- Validate prompt files ---
    for path in emitted:
        validation_errors.extend(_validate_prompt(path))

    # --- Validate CAPABILITIES.md if it exists ---
    caps_path = out_root / "CAPABILITIES.md"
    if caps_path.exists():
        cap_errors = validate_capabilities(caps_path)
        if cap_errors:
            validation_errors.extend(
                [f"CAPABILITIES.md: {e}" for e in cap_errors]
            )

    # --- Print summary ---
    total = len(emitted)
    prompts_dir = out_root / "prompts"
    print(f"export-codex: emitted {total} prompt files to {prompts_dir}")
    print(f"  AGENTS.md written to {agents_path}")

    if validation_errors:
        print(f"\nValidation errors ({len(validation_errors)}):")
        for err in validation_errors:
            print(f"  ERROR: {err}")
        return 1

    print(f"  all {total} prompt files passed validation.")
    return 0


if __name__ == "__main__":
    print(
        "[z-harness] WARNING: export-codex.py is deprecated and will be removed"
        " in the next minor release. Use the runtime driver instead.",
        file=sys.stderr,
    )
    sys.exit(main())
