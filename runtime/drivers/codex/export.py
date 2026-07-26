"""
runtime/drivers/codex/export.py

Codex CLI export driver — strict port of ``scripts/export-codex.py`` wrapped
in the runtime-owned ``export()`` signature.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Render all z-harness skills and agents as Codex CLI export artifacts under
    ``export_root``.

    Codex output format:
    - ``skills/<id>/SKILL.md``    — one file per skill, copied VERBATIM from
                                    the source SKILL.md (frontmatter + body
                                    preserved; no transliteration).
    - ``.codex/agents/<id>.toml`` — one native Codex custom-agent TOML file
                                    per source agent.
    - ``AGENTS.md``               — consolidated agent reference document.
    - ``.codex-plugin/plugin.json``— generated manifest declaring skills path
                                    so Codex CLI discovers the skills directory.
    - ``mcp_config.json``         — installable MCP server config consumed by
                                    the Codex adapter registration path.

ExportResult is imported from runtime.drivers._export_utils (BLOCKER-1).
Fidelity is read from the Codex parity gate when available. Current evidence
can promote export fidelity independently of runtime command orchestration:
native skills/custom agents/MCP artifacts may be emitted while CLI subagent
dispatch remains unproven.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from runtime.capability_authority import (
    Capability,
    CapabilityAuthority,
    CapabilityKey,
    CapabilityResolution,
)
from runtime.drivers._export_utils import (
    ExportResult,
    _parse_frontmatter,
    enumerate_sources,
    output_path_for,
    validate_capabilities,
    rewrite_unsupported_call_blocks,
    export_resume_runtime_scripts,
)
from runtime.drivers.codex.agent_export import export_native_agents


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
    "<!-- Codex export emits skill/custom-agent artifacts, but this runtime"
    " dispatch primitive is unproven in Codex CLI; see CAPABILITIES.md -->"
)


def _current_fidelity() -> str:
    """Read Codex export fidelity from the parity gate."""
    try:
        from z_harness_cli.adapters.codex_parity_gate import codex_export_fidelity

        return codex_export_fidelity()
    except ImportError:
        return "flattened"


def _rewrite_body(body: str) -> str:
    """Rewrite unsupported runtime call blocks with a Codex dispatch hint."""
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


def _render_agents_md(agents: list[dict[str, Any]], *, fidelity: str) -> str:
    """Render all agents as a single consolidated AGENTS.md."""
    if fidelity == "native":
        dispatch_note = [
            "Codex parity evidence has authorized native orchestration for the\n",
            "covered z-harness command families.  These agent definitions remain\n",
            "a reference for the exported Codex package.\n",
        ]
    else:
        dispatch_note = [
            "Codex custom-agent definitions are exported under `.codex/agents/`,\n",
            "but Codex CLI native subagent dispatch has not been proven by the\n",
            "z-harness Codex parity gate.  This AGENTS.md remains a fallback\n",
            "reference for the exported package.\n",
        ]

    lines: list[str] = [
        "# Agents\n",
        "\n",
        "This file documents all z-harness agents exported for Codex CLI use.\n",
        "\n",
        *dispatch_note,
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

_MCP_SERVER_NAME = "z-harness"
_BLOCKED_PLUGIN_SKILLS = frozenset({"z-execute"})
_AUTHORITY_OPTION_FIELDS = (
    "authority_path",
    "host",
    "surface",
    "runtime_build",
    "command",
    "posture",
    "now",
)

_BLOCKED_WARNING = (
    "{reason}; restriction applies only to the z-execute workflow; "
    "global native collaboration/subagent tools remain available"
)


def _resolve_z_execute_authority(
    options: dict[str, Any] | None,
    *,
    installed_export_fingerprint: str,
) -> tuple[CapabilityResolution, dict[str, object] | None]:
    """Resolve the exact installed ``z-execute`` tuple for this export.

    An absent or incomplete authority context is the normal Release A state and
    fails closed.  ``now`` is supplied by the caller rather than read from the
    wall clock so identical inputs always produce the same export decision.

    Returns
    -------
    tuple[CapabilityResolution, dict[str, object] | None]
        The fail-closed authority result and the audit-safe binding to stamp
        into the installed plugin manifest when a complete context was given.
    """
    if options is None:
        return CapabilityResolution(Capability.BLOCKED, "release_a_static_block"), None
    if any(field not in options for field in _AUTHORITY_OPTION_FIELDS):
        return CapabilityResolution(Capability.BLOCKED, "incomplete_authority_context"), None

    string_fields = _AUTHORITY_OPTION_FIELDS[:-1]
    if any(not isinstance(options[field], str) or not options[field] for field in string_fields):
        return CapabilityResolution(Capability.BLOCKED, "invalid_authority_context"), None
    if type(options["now"]) is not int or options["command"] != "z-execute":
        return CapabilityResolution(Capability.BLOCKED, "invalid_authority_context"), None

    key = CapabilityKey(
        host=options["host"],
        surface=options["surface"],
        runtime_build=options["runtime_build"],
        command=options["command"],
        posture=options["posture"],
    )
    resolution = CapabilityAuthority(options["authority_path"]).resolve(
        key,
        installed_export_fingerprint=installed_export_fingerprint,
        now=options["now"],
    )
    binding: dict[str, object] = {
        "host": key.host,
        "surface": key.surface,
        "runtime_build": key.runtime_build,
        "command": key.command,
        "posture": key.posture,
        "installed_export_fingerprint": installed_export_fingerprint,
        "capability": resolution.capability.value,
        "reason": resolution.reason,
        "evidence_id": resolution.evidence_id,
        "z_execute_exported": resolution.capability is Capability.NATIVE_BOUNDED,
    }
    return resolution, binding


def _fingerprint_export_payload(
    export_root: Path,
    payload: dict[Path, bytes],
) -> str:
    """Return a deterministic SHA-256 fingerprint of the install payload.

    Paths are relative to the export root and both path and content are
    length-prefixed.  The plugin manifest is represented without its
    ``capability_authority`` field, avoiding a self-referential digest while
    still binding every independently generated byte of that manifest.
    """

    digest = hashlib.sha256()
    for path in sorted(
        payload,
        key=lambda candidate: candidate.relative_to(export_root).as_posix(),
    ):
        relative = path.relative_to(export_root).as_posix().encode("utf-8")
        content = payload[path]
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


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


def _render_plugin_manifest(
    repo_root: Path | None = None,
    *,
    candidate_version: str | None = None,
    candidate_commit: str | None = None,
    authority_binding: dict[str, object] | None = None,
) -> str:
    """Return deterministic JSON content for .codex-plugin/plugin.json."""
    manifest = dict(_CODEX_PLUGIN_MANIFEST)
    version = candidate_version or (_resolve_version(repo_root) if repo_root is not None else None)
    if version:
        # Insert version right after name for readability.
        manifest = {"name": manifest["name"], "version": version,
                    **{k: v for k, v in manifest.items() if k != "name"}}
    if candidate_commit:
        manifest["candidate_commit"] = candidate_commit
    if authority_binding is not None:
        manifest["capability_authority"] = authority_binding
    return json.dumps(manifest, indent=2) + "\n"


def _resolve_mcp_python(repo_root: Path) -> str:
    """Return the Python executable Codex should use for the MCP server."""
    for candidate in (
        repo_root / ".venv" / "bin" / "python",
        repo_root / "venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    return "python3"


def _render_mcp_config(repo_root: Path) -> str:
    """Return the MCP config JSON consumed by Codex adapter registration."""
    payload = {
        "mcpServers": {
            _MCP_SERVER_NAME: {
                "command": _resolve_mcp_python(repo_root),
                "default_tools_approval_mode": "approve",
                # Codex uses native plugin skills as the /z-* command surface.
                # Keep MCP available only for lightweight detection helpers so
                # a skill run cannot recursively invoke z-harness command tools.
                "enabled_tools": ["z_detect"],
                "args": [
                    "-m",
                    "z_harness_cli",
                    "serve",
                    "--transport",
                    "stdio",
                ],
                "env": {
                    "PYTHONPATH": str(repo_root),
                    "CLAUDE_PLUGIN_ROOT": str(repo_root),
                },
            },
        },
    }
    return json.dumps(payload, indent=2) + "\n"


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
        transliteration).  Native Codex custom agents are written under
        ``<export_root>/.codex/agents/``.  The consolidated
        fallback/reference document is written to ``<export_root>/AGENTS.md``.
        A Codex CLI discovery manifest is written to
        ``<export_root>/.codex-plugin/plugin.json``.  MCP registration config
        is written to ``<export_root>/mcp_config.json``.
    options:
        Optional exact capability-authority context for ``z-execute``.  A
        complete context contains ``authority_path``, ``host``, ``surface``,
        ``runtime_build``, ``command``, ``posture``, and integer ``now``.  The
        installed-export fingerprint is computed from the generated payload;
        missing or invalid context retains the Release A block.

    Returns
    -------
    ExportResult
        ``dest`` is *export_root* (resolved).
        ``files`` lists every file written.
        ``fidelity`` is read from ``codex_parity_gate``.
        ``warnings`` carries any non-fatal validation errors discovered during
        export.
    """
    repo_root = Path(repo_root).resolve()
    export_root = Path(export_root).resolve()

    sources = enumerate_sources(repo_root)
    emitted: list[Path] = []
    warnings: list[str] = []
    validation_errors: list[str] = []
    fidelity = _current_fidelity()

    # Default base according to output_path_for convention (used to remap
    # paths when export_root differs from the default).
    default_base = repo_root / "exports" / "codex"
    execute_candidate: tuple[Path, bytes] | None = None

    # --- Emit native SKILL.md files for skills (verbatim copy) ---
    for entry in sources["skills"]:
        eid = entry["id"]
        out_path = output_path_for(repo_root, "codex", "skills", eid)
        if export_root != default_base:
            relative = out_path.relative_to(default_base)
            out_path = export_root / relative

        # Preserve source frontmatter, but write the enumerated body so includes expand.
        skill_text = _render_native_skill(entry)
        if eid in _BLOCKED_PLUGIN_SKILLS:
            execute_candidate = (out_path, skill_text.encode("utf-8"))
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(skill_text, encoding="utf-8")
        emitted.append(out_path)

    # --- Emit native Codex custom-agent TOML files ---
    native_agent_result = export_native_agents(sources["agents"], export_root)
    emitted.extend(native_agent_result.files)
    warnings.extend(native_agent_result.warnings)

    # --- Emit consolidated AGENTS.md ---
    agents_path = export_root / "AGENTS.md"
    agents_path.parent.mkdir(parents=True, exist_ok=True)
    agents_md = _render_agents_md(sources["agents"], fidelity=fidelity)
    agents_path.write_text(agents_md, encoding="utf-8")

    # --- Emit MCP config consumed by CodexAdapter.inject default registration path ---
    mcp_config_path = export_root / "mcp_config.json"
    mcp_config_path.write_text(_render_mcp_config(repo_root), encoding="utf-8")

    emitted.extend(export_resume_runtime_scripts(repo_root, export_root))

    # Resolve authority against a digest computed from the exact candidate
    # payload.  The base manifest is included without the resulting binding so
    # evidence can be obtained from one blocked export and applied to the next.
    plugin_dir = export_root / ".codex-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin_manifest_path = plugin_dir / "plugin.json"
    payload = {path: path.read_bytes() for path in emitted}
    payload[agents_path] = agents_path.read_bytes()
    payload[mcp_config_path] = mcp_config_path.read_bytes()
    payload[plugin_manifest_path] = _render_plugin_manifest(repo_root).encode("utf-8")
    if execute_candidate is not None:
        payload[execute_candidate[0]] = execute_candidate[1]
    installed_export_fingerprint = _fingerprint_export_payload(export_root, payload)
    execute_resolution, authority_binding = _resolve_z_execute_authority(
        options,
        installed_export_fingerprint=installed_export_fingerprint,
    )
    execute_authorized = (
        execute_candidate is not None
        and execute_resolution.capability is Capability.NATIVE_BOUNDED
    )
    if authority_binding is not None:
        authority_binding["z_execute_exported"] = execute_authorized
    if execute_authorized:
        execute_path, execute_content = execute_candidate
        execute_path.parent.mkdir(parents=True, exist_ok=True)
        execute_path.write_bytes(execute_content)
        emitted.append(execute_path)
    else:
        if (
            execute_candidate is not None
            and os.environ.get("Z_HARNESS_RELEASE_SURFACE") != "prod"
        ):
            block_reason = (
                "degraded_single_agent_only"
                if execute_resolution.capability is Capability.DEGRADED_SINGLE_AGENT
                else execute_resolution.reason
            )
            warnings.append(
                f"z-execute blocked: {_BLOCKED_WARNING.format(reason=block_reason)}"
            )
        # A destination can outlive the source inventory.  Remove the one
        # forbidden generated directory so an older artifact cannot remain.
        execute_skill_dir = export_root / "skills" / "z-execute"
        if execute_skill_dir.is_dir():
            shutil.rmtree(execute_skill_dir)

    plugin_manifest_path.write_text(
        _render_plugin_manifest(repo_root, authority_binding=authority_binding),
        encoding="utf-8",
    )

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
        files=emitted + [agents_path, plugin_manifest_path, mcp_config_path],
        fidelity=fidelity,
        warnings=warnings,
    )
