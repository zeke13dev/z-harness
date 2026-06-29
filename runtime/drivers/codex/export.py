"""
runtime/drivers/codex/export.py

Codex CLI export driver — strict port of ``scripts/export-codex.py`` wrapped
in the runtime-owned ``export()`` signature.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Render all z-harness skills and agents as Codex CLI files under
    ``export_root``.

    Codex output format:
    - ``skills/<id>/SKILL.md``    — one file per skill, copied VERBATIM from
                                    the source SKILL.md (frontmatter + body
                                    preserved; no transliteration).
    - ``AGENTS.md``               — consolidated agent reference document.
    - ``.codex-plugin/plugin.json``— generated manifest declaring skills path
                                    so Codex CLI discovers the skills directory.

ExportResult is imported from runtime.drivers._export_utils (BLOCKER-1).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from runtime.drivers._export_utils import (
    ExportResult,
    _parse_frontmatter,
    enumerate_sources,
    output_path_for,
    validate_capabilities,
    rewrite_unsupported_call_blocks,
    export_resume_runtime_scripts,
)


# ---------------------------------------------------------------------------
# Body rewriting (for agents/commands only)
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
    """Rewrite whole unsupported runtime call blocks with a Codex hint."""
    return rewrite_unsupported_call_blocks(
        body,
        lambda _block: _REPLACEMENT_COMMENT,
    )


def _render_native_skill(entry: dict[str, Any]) -> str:
    """Render a native SKILL.md with expanded includes and original frontmatter."""
    source_text = entry["source_path"].read_text(encoding="utf-8")
    _, source_body = _parse_frontmatter(source_text)
    return source_text[: len(source_text) - len(source_body)] + entry["body"]


# ---------------------------------------------------------------------------
# Prompt file rendering (commands only — retained for any future use)
# ---------------------------------------------------------------------------


def _render_prompt(entry: dict[str, Any]) -> str:
    """Render a single command/skill *entry* as a Codex prompt file.

    Format:
        # /<id>
        <rewritten body>

    Note: This renderer is no longer used for skills (which are now written
    verbatim as ``skills/<id>/SKILL.md``). It is retained for commands if
    ever emitted, and for backward-compatibility with tests that exercise
    the rendering logic directly on arbitrary entries.
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
# .codex-plugin/plugin.json manifest generation
# ---------------------------------------------------------------------------

_CODEX_PLUGIN_MANIFEST: dict[str, Any] = {
    "name": "z-harness",
    "description": "z-harness planning and implementation workflow for Codex CLI",
    "skills": "./skills/",
}


def _resolve_version(repo_root: Path) -> str | None:
    """Read the stamped version from the committed Claude plugin manifest.

    Single source of truth: scripts/sync-version.sh stamps the version
    (MAJOR.MINOR.<commit-count>) into .claude-plugin/plugin.json at commit time.
    The codex manifest mirrors that value so Codex busts its cache on every
    commit too. Returns None if the manifest or field is absent (older trees).
    """
    manifest = repo_root / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def _render_plugin_manifest(repo_root: Path) -> str:
    """Return the JSON content for .codex-plugin/plugin.json."""
    manifest = dict(_CODEX_PLUGIN_MANIFEST)
    version = _resolve_version(repo_root)
    if version:
        # Insert version right after name for readability.
        manifest = {"name": manifest["name"], "version": version,
                    **{k: v for k, v in manifest.items() if k != "name"}}
    return json.dumps(manifest, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Public export function
# ---------------------------------------------------------------------------


def export(
    repo_root: Path,
    export_root: Path,
    *,
    options: dict[str, Any] | None = None,
) -> ExportResult:
    """Export z-harness skills and agents as Codex CLI files.

    Parameters
    ----------
    repo_root:
        Absolute path to the z-harness repository root.  Used to discover
        source files (``agents/``, ``skills/``).
    export_root:
        Destination directory for exported files.  Skills are written verbatim
        to ``<export_root>/skills/<id>/SKILL.md`` (frontmatter preserved, no
        transliteration).  The consolidated agent reference is written to
        ``<export_root>/AGENTS.md``.  A Codex CLI discovery manifest is written
        to ``<export_root>/.codex-plugin/plugin.json``.
    options:
        Reserved for future use.  Currently unused; pass ``None`` or omit.

    Returns
    -------
    ExportResult
        ``dest`` is *export_root* (resolved).
        ``files`` lists every file written.
        ``fidelity`` is ``"flattened"`` because skills are copied verbatim but
        Codex still lacks native z-harness subagent orchestration.
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

    # --- Emit native SKILL.md files for skills (verbatim copy) ---
    for entry in sources["skills"]:
        eid = entry["id"]
        out_path = output_path_for(repo_root, "codex", "skills", eid)
        if export_root != default_base:
            relative = out_path.relative_to(default_base)
            out_path = export_root / relative

        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve source frontmatter, but write the enumerated body so includes expand.
        skill_text = _render_native_skill(entry)
        out_path.write_text(skill_text, encoding="utf-8")
        emitted.append(out_path)

    # --- Emit consolidated AGENTS.md ---
    agents_path = export_root / "AGENTS.md"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_md = _render_agents_md(sources["agents"])
    agents_path.write_text(agents_md, encoding="utf-8")

    # --- Emit .codex-plugin/plugin.json manifest ---
    plugin_dir = export_root / ".codex-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin_manifest_path = plugin_dir / "plugin.json"
    plugin_manifest_path.write_text(_render_plugin_manifest(repo_root), encoding="utf-8")

    emitted.extend(export_resume_runtime_scripts(repo_root, export_root))

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
        files=emitted + [agents_path, plugin_manifest_path],
        fidelity="flattened",
        warnings=warnings,
    )
