"""Cursor host adapter — fidelity: flattened.

Cursor agent (``cursor-agent``) runs z-harness commands as a single-agent
transliteration.  Multi-agent orchestration (/z-execute, /z-panel,
/z-consult, /z-gate) is absent at this fidelity tier.

Injection modes
---------------
ephemeral:  A gitignored ``.cursor/rules/z-harness-session.mdc`` rule file is
    written carrying the MAGIC_MARKER.  The CLAUDE_PLUGIN_ROOT env var is
    injected so the spawned cursor-agent process can locate the harness runtime.
    cleanup() removes the file and its parent directory if it was created.

in_place:  The .mdc rule is written as a committed project file (the caller
    manages its lifecycle; cleanup is a no-op for files the caller committed).

Export layout (cursor .mdc rules)
----------------------------------
Delegates to ``runtime/drivers/cursor/persona_export.py::export_persona()``
for persona files, which writes::

    <dest>/.cursor/personas/<name>.mdc

For full command/agent/skill export the caller should use the
``scripts/export-cursor.py`` pipeline (now frozen/deprecated) or the
runtime driver equivalent.

Capabilities
------------
cursor-agent supports project-scoped MCP via ``.cursor/mcp.json`` and
user-scoped MCP via ``~/.cursor/mcp.json``.  It presents a trust/permission
prompt for each new tool action (``--approve-mcps`` bypasses this for MCP
servers, but general tool trust is interactive).  ``cursor-agent`` does not
expose a ``--cwd`` / ``--project`` flag; the working directory is set via
cwd of the spawned process.

Command-capability matrix
--------------------------
All single-agent /z-* commands run in degraded mode (transliterated rules,
no subagent dispatch).  Multi-agent commands are blocked.

Attribution / decision record
------------------------------
- binary probed: cursor-agent (on PATH; version via ``cursor-agent --version``)
- fidelity=flattened: single-agent transliteration, per SPEC D13 + PLAN Phase B
- supports_project_mcp=True: .cursor/mcp.json probed from cursor-agent help
- supports_user_mcp=True: ~/.cursor/mcp.json is a documented config path
- needs_trust_prompt=True: cursor-agent surfaces per-tool approval interactively
- supports_cwd_override=False: cursor-agent does not expose a --cwd flag
- cleanup_strategy="ephemeral": session .mdc rule gitignored + deleted on cleanup
- CLAUDE_PLUGIN_ROOT injected for ephemeral launches (D14): cursor reads this
  var when the harness is injected (same var as Claude Code, per env_bundle.py)
- decision source: cursor-agent --help 2026-05-28-a70ca7c; probe date 2026-06-03
  decided by: T009 implementer (Claude Sonnet 4.6) under T009 task block
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from z_harness_cli.adapters.base import (
    KNOWN_COMMANDS,
    Capabilities,
    DetectResult,
    ExportResult,
    Injection,
    register_command_tiers,
)
from z_harness_cli import inject_safety


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HOST_NAME = "cursor"
_FIDELITY_TIER: Literal["flattened"] = "flattened"

# The cursor-agent binary name.
_CURSOR_BINARY = "cursor-agent"

# Gitignored session rule file written for ephemeral injection.
# Placed under .cursor/rules/ so cursor-agent picks it up automatically.
_EPHEMERAL_RULE_DIRNAME = ".cursor"
_EPHEMERAL_RULE_SUBDIR = "rules"
_EPHEMERAL_RULE_FILENAME = "z-harness-session.mdc"

# Magic marker reference — imported from inject_safety to stay in sync.
_MAGIC_MARKER = inject_safety.MAGIC_MARKER

# Template for the ephemeral session rule.  Embeds the magic marker so
# inject_safety recognises it as z-harness-authored on re-runs.
_SESSION_MDC_TEMPLATE = """\
---
description: "z-harness session injection ({marker})"
alwaysApply: true
---

<!-- {marker} (ephemeral z-harness injection — delete to stop injection) -->
<!-- This file was written by `z-harness launch` and is gitignored. -->
<!-- It informs cursor-agent that z-harness is loaded from: {plugin_root} -->

# z-harness (ephemeral session)

This rule was injected by `z-harness launch` for this session.
It will be removed automatically on exit.  Do not commit this file.

z-harness plugin root: `{plugin_root}`
""".format


# ---------------------------------------------------------------------------
# Command-capability matrix registration
# ---------------------------------------------------------------------------

#: Commands that require multi-agent orchestration — blocked on flattened hosts.
_MULTI_AGENT_COMMANDS = frozenset(
    {
        "z-execute",
        "z-panel",
        "z-consult",
        "z-gate",
    }
)

#: Commands that run in degraded mode (single-agent transliteration present,
#: but reduced fidelity vs the native Claude Code experience).
_DEGRADED_COMMANDS = frozenset(KNOWN_COMMANDS) - _MULTI_AGENT_COMMANDS

register_command_tiers(
    _HOST_NAME,
    {
        cmd: ("blocked" if cmd in _MULTI_AGENT_COMMANDS else "degraded")
        for cmd in KNOWN_COMMANDS
    },
)


# ---------------------------------------------------------------------------
# Capabilities declaration
# ---------------------------------------------------------------------------

_CAPABILITIES = Capabilities(
    supports_project_mcp=True,    # .cursor/mcp.json is a documented project MCP path
    supports_user_mcp=True,       # ~/.cursor/mcp.json is the user-scoped MCP path
    needs_trust_prompt=True,      # cursor-agent surfaces per-tool approval interactively
    supports_cwd_override=False,  # no --cwd / --project flag in cursor-agent CLI
    cleanup_strategy="ephemeral",
)


# ---------------------------------------------------------------------------
# CursorAdapter
# ---------------------------------------------------------------------------


class CursorAdapter:
    """Host adapter for Cursor agent (fidelity: flattened).

    Instantiate once per process; safe to reuse across multiple inject/
    cleanup cycles (each inject() produces an independent Injection).
    """

    name: str = _HOST_NAME
    fidelity_tier: Literal["flattened"] = _FIDELITY_TIER
    capabilities: Capabilities = _CAPABILITIES

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        """Probe for the ``cursor-agent`` binary on PATH and read its version.

        Runs ``cursor-agent --version`` (non-interactive; safe to call without
        side-effects).  The version string is whatever the binary prints on
        a single line to stdout.

        Returns
        -------
        DetectResult
            installed=True when the binary is on PATH and exits zero.
            version=None when the binary is present but ``--version`` fails.
        """
        binary = shutil.which(_CURSOR_BINARY)
        if binary is None:
            return DetectResult(installed=False)

        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            # Binary found but unresponsive or exec failed.
            return DetectResult(installed=True, binary=binary)

        if result.returncode != 0:
            return DetectResult(installed=True, binary=binary)

        version = result.stdout.strip() or result.stderr.strip() or None
        return DetectResult(installed=True, version=version, binary=binary)

    # ------------------------------------------------------------------
    # export_payload
    # ------------------------------------------------------------------

    def export_payload(self, dest: Path) -> ExportResult:
        """Export commands, agents, skills, and personas to the Cursor .mdc layout.

        Delegates to ``runtime/drivers/cursor/export.py::export()`` for
        commands, agents, and skills (producing ``.mdc`` rule files under
        ``<dest>/.cursor/rules/``), then runs the existing persona loop via
        ``runtime/drivers/cursor/persona_export.py::export_persona()`` for
        each persona file found in the ``personas/`` directory.

        Both results are merged into a single ExportResult.  Fidelity is
        always ``"flattened"`` for Cursor.

        Non-empty warnings from the runtime export (validation errors) are
        preserved and re-raised as ``RuntimeError`` so callers that expect the
        legacy hard-gate behaviour see a failure signal rather than a silent
        downgrade.

        Collision assert (MINOR-6): persona names must not overlap with
        command/agent/skill ids in the flat ``.cursor/rules/`` namespace.
        A collision raises ``RuntimeError`` with a descriptive message.

        The written layout is::

            <dest>/.cursor/rules/<id>.mdc       — commands, agents, skills
            <dest>/.cursor/personas/<name>.mdc  — personas

        Returns
        -------
        ExportResult
            fidelity="flattened"; files lists all written files under dest;
            warnings aggregated from both stages.

        Raises
        ------
        RuntimeError
            If the runtime export produces validation warnings (legacy hard-gate)
            or if persona names collide with command/agent/skill ids.
        """
        dest = Path(dest)

        # Locate the harness repo root.
        harness_root = Path(__file__).parent.parent.parent.resolve()
        # Shipped personas live in personas/builtin/ (the canonical builtin layer
        # per resolve-persona.py); personas/ itself holds only README.md. Globbing
        # personas/ directly matches zero persona files and exports no personas.
        personas_dir = harness_root / "personas" / "builtin"

        all_files: list[Path] = []
        all_warnings: list[str] = []

        # ------------------------------------------------------------------
        # Stage 1: runtime export — commands, agents, skills
        # ------------------------------------------------------------------
        try:
            from runtime.drivers.cursor.export import export as cursor_export
        except ImportError as exc:
            all_warnings.append(
                f"runtime.drivers.cursor.export not importable: {exc}"
            )
            cursor_export = None  # type: ignore[assignment]

        runtime_ids: set[str] = set()
        if cursor_export is not None:
            rt_result = cursor_export(harness_root, dest)
            all_files.extend(rt_result.files)
            if rt_result.warnings:
                # Surface validation warnings as a hard failure — preserving
                # the legacy export-cursor.py validation gate behaviour.
                raise RuntimeError(
                    f"cursor runtime export produced validation errors:\n"
                    + "\n".join(f"  {w}" for w in rt_result.warnings)
                )
            # Collect exported ids to check for persona-name collisions.
            # Files land under .cursor/rules/<id>.mdc; extract the stem.
            for f in rt_result.files:
                stem = Path(f).stem
                runtime_ids.add(stem)

        # ------------------------------------------------------------------
        # Stage 2: persona export loop
        # ------------------------------------------------------------------
        if not personas_dir.is_dir():
            all_warnings.append("personas/builtin/ directory not found; persona export skipped")
        else:
            # Lazy import so the adapter can load without the full runtime
            # package in environments where only z_harness_cli is installed.
            try:
                from runtime.drivers.cursor.persona_export import export_persona
            except ImportError as exc:
                all_warnings.append(
                    f"runtime.drivers.cursor.persona_export not importable: {exc}"
                )
                export_persona = None  # type: ignore[assignment]

            if export_persona is not None:
                for persona_file in sorted(personas_dir.glob("*.md")):
                    persona_name = persona_file.stem
                    # Collision check: persona names must not overlap with
                    # command/agent/skill ids in the flat .cursor/rules/ namespace.
                    if persona_name in runtime_ids:
                        raise RuntimeError(
                            f"cursor export collision: persona name {persona_name!r} "
                            f"conflicts with an existing command/agent/skill id. "
                            f"Rename the persona or the conflicting source file."
                        )
                    try:
                        out_path = export_persona(persona_file, dest)
                        all_files.append(out_path)
                    except (ValueError, OSError) as exc:
                        all_warnings.append(f"Skipped {persona_file.name}: {exc}")

        return ExportResult(
            dest=dest,
            files=all_files,
            fidelity="flattened",
            warnings=all_warnings,
        )

    # ------------------------------------------------------------------
    # inject
    # ------------------------------------------------------------------

    def inject(
        self,
        state_env: dict[str, str],
        mode: Literal["ephemeral", "in_place"],
        project: Path,
    ) -> Injection:
        """Write a host-native .mdc session rule and return an Injection handle.

        For ``mode="ephemeral"``:
          * Runs inject_safety.preflight_targets() on the target .mdc file
            before writing (clobber guard).
          * Writes a gitignored ``.cursor/rules/z-harness-session.mdc``
            carrying the magic marker.
          * Calls inject_safety.ensure_gitignored() so the file is never
            accidentally committed.
          * Injects CLAUDE_PLUGIN_ROOT into the child env (D14: cursor reads
            this var when the harness is injected).

        For ``mode="in_place"``:
          * Writes ``.cursor/rules/z-harness-session.mdc`` into the project
            without gitignoring (caller manages lifecycle; cleanup is no-op).

        The returned Injection's ``_cleanup_fn`` is set to
        ``CursorAdapter.cleanup`` so the context-manager protocol works.

        Parameters
        ----------
        state_env:
            z-harness env bundle (from env_bundle.resolve_env_bundle()).
            Merged into the child env as-is.
        mode:
            "ephemeral" — write gitignored config for this session only.
            "in_place"  — committed project rule; caller manages lifecycle.
        project:
            Absolute path to the user's project repo root.

        Returns
        -------
        Injection
            env merges *state_env* + CLAUDE_PLUGIN_ROOT into a copy of
            os.environ.  injected_files lists any written paths.
        """
        project = Path(project).resolve()
        env: dict[str, str] = dict(os.environ)
        env.update(state_env)
        injected_files: list[Path] = []
        backup_manifest: dict[str, Path] | None = None

        # Determine the harness root to inject as CLAUDE_PLUGIN_ROOT (D14).
        harness_root = str(Path(__file__).parent.parent.parent.resolve())
        env["CLAUDE_PLUGIN_ROOT"] = harness_root

        # Target path for the session rule.
        rule_dir = project / _EPHEMERAL_RULE_DIRNAME / _EPHEMERAL_RULE_SUBDIR
        target = rule_dir / _EPHEMERAL_RULE_FILENAME

        if mode == "ephemeral":
            # Clobber-safe pre-flight (raises ClobberRefused if the file
            # exists and is not z-harness-authored, and force=False).
            backup_manifest = inject_safety.preflight_targets(
                [target],
                project,
                force=False,
            )

            # Write the session .mdc rule.
            rule_dir.mkdir(parents=True, exist_ok=True)
            content = _SESSION_MDC_TEMPLATE(
                marker=_MAGIC_MARKER,
                plugin_root=harness_root,
            )
            target.write_text(content, encoding="utf-8")
            injected_files.append(target)

            # Ensure the written file is gitignored.
            inject_safety.ensure_gitignored([target], project)

        else:
            # in_place: write but do not gitignore; caller manages lifecycle.
            rule_dir.mkdir(parents=True, exist_ok=True)
            content = _SESSION_MDC_TEMPLATE(
                marker=_MAGIC_MARKER,
                plugin_root=harness_root,
            )
            target.write_text(content, encoding="utf-8")
            injected_files.append(target)

        return Injection(
            env=env,
            injected_files=injected_files,
            mode=mode,
            host=_HOST_NAME,
            backup_manifest=backup_manifest if backup_manifest else None,
            _cleanup_fn=lambda inj: self.cleanup(inj),
        )

    # ------------------------------------------------------------------
    # launch
    # ------------------------------------------------------------------

    def launch(self, project: Path, env: dict[str, str]) -> int:
        """PTY-passthrough exec of ``cursor-agent`` in *project*.

        Blocks until cursor-agent exits and returns its exit code.

        The caller is responsible for calling cleanup() afterwards (or
        using the Injection context manager so cleanup always runs).

        Parameters
        ----------
        project:
            Working directory for the ``cursor-agent`` process.
        env:
            Full environment mapping (typically the Injection.env dict
            merged over os.environ via env_bundle.apply_env_bundle()).

        Returns
        -------
        int
            cursor-agent's exit code (0 = clean exit).

        Raises
        ------
        FileNotFoundError
            If the ``cursor-agent`` binary is not on PATH.
        PTYUnsupportedError
            On Windows or any platform without the ``pty`` stdlib module.
        """
        from z_harness_cli.pty_launch import pty_launch

        binary = shutil.which(_CURSOR_BINARY) or _CURSOR_BINARY
        return pty_launch(
            argv=[binary],
            env=env,
            cwd=Path(project).resolve(),
        )

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------

    def cleanup(self, injection: Injection) -> None:
        """Remove injected state produced by a prior inject() call.

        Delegates to inject_safety.cleanup() for file restore/removal per
        the persisted manifest.  Idempotent: safe to call multiple times.

        For ephemeral mode this removes ``.cursor/rules/z-harness-session.mdc``
        and restores any pre-existing file that was backed up.

        For in_place mode this is a no-op (caller manages lifecycle).

        Parameters
        ----------
        injection:
            The Injection returned by a prior call to inject().
        """
        if not injection.injected_files:
            return

        if injection.mode == "in_place":
            # in_place: caller manages lifecycle; no automatic cleanup.
            return

        # Derive project from the first injected file: the rule is at
        # <project>/.cursor/rules/z-harness-session.mdc, so parent.parent.parent
        # is the project root.
        rule_path = injection.injected_files[0]
        project = rule_path.parent.parent.parent
        inject_safety.cleanup(project)
