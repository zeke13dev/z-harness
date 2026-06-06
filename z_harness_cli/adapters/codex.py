"""Codex host adapter — fidelity: flattened.

Codex CLI (OpenAI ``codex``) runs z-harness commands as a single-agent
transliteration.  Multi-agent orchestration (/z-implement-all, /z-panel,
/z-consult, /z-gate) is absent at this fidelity tier.

Injection modes
---------------
ephemeral:  A gitignored ``AGENTS.md`` is written to the project root
    carrying the MAGIC_MARKER.  The CLAUDE_PLUGIN_ROOT env var is injected
    so the spawned codex process can locate the harness runtime.
    cleanup() removes the file.

in_place:  The AGENTS.md is written as a committed project file (the
    caller manages its lifecycle; cleanup is a no-op for files the caller
    committed).

MCP registration (global / persistent — F4)
-------------------------------------------
When ``supports_project_mcp`` is True (the default), inject() calls
``runtime.drivers.codex.mcp.ensure_mcp_registered()`` to register the
z-harness MCP server in ``~/.codex/config.toml``.  This write is:
  * **Global and persistent** — shared across all of the user's projects.
  * **Idempotent** — re-running launch does not duplicate or fail.
  * **NOT undone by ephemeral cleanup** — removing a shared MCP entry on
    every session exit would break the user's other Codex projects.
  * **Explicit removal only** — via ``z-harness doctor --clear-mcp``.

De-registration of stale z-harness MCP entries happens only when the
host's fidelity downgrades out of MCP support (i.e. codex loses MCP
capability on a future version bump) and is handled by the doctor command.

Export layout (AGENTS.md)
--------------------------
Delegates to ``runtime/drivers/codex/persona_export.py::export_persona()``
for persona files, which writes::

    <dest>/prompts/personas/<name>.md

The top-level AGENTS.md for an injected session is a lightweight stub
that points to the prompts/ layout.  For full command/agent/skill export
the caller should use ``scripts/export-codex.py`` (now frozen/deprecated)
or the runtime driver equivalent.

Capabilities
------------
The Codex CLI supports project-scoped MCP via ``codex mcp add``
(written globally to ``~/.codex/config.toml``).  It does not have a
user-scoped MCP store separate from the global config.  The ``codex``
binary does not expose a ``--cwd`` / ``--project`` flag; the working
directory is set via the cwd of the spawned process.

Command-capability matrix
--------------------------
All single-agent /z-* commands run in degraded mode (transliterated via
AGENTS.md, no subagent dispatch).  Multi-agent commands are blocked.

Attribution / decision record
------------------------------
- binary probed: codex (on PATH; version via ``codex --version``)
- fidelity=flattened: single-agent transliteration, per SPEC D13 + PLAN Phase B
- supports_project_mcp=True: codex mcp add writes ~/.codex/config.toml
- supports_user_mcp=False: codex has no separate user-scoped MCP store;
  global ~/.codex/config.toml is the only MCP config location
- needs_trust_prompt=False: codex runs non-interactively without a per-tool
  approval prompt (model is configured at init time, not per-tool)
- supports_cwd_override=False: codex does not expose a --cwd / --project flag;
  cwd is set via the spawned process working directory
- cleanup_strategy="ephemeral": session AGENTS.md gitignored + deleted on
  cleanup; MCP entry in ~/.codex/config.toml is NOT removed by cleanup (F4)
- CLAUDE_PLUGIN_ROOT injected for ephemeral launches (D14)
- decision source: codex --help 2026-06-03; probe date 2026-06-03
  decided by: T010 implementer (Claude Sonnet 4.6) under T010 task block
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

_HOST_NAME = "codex"
_FIDELITY_TIER: Literal["flattened"] = "flattened"

# The codex binary name.
_CODEX_BINARY = "codex"

# Gitignored session file written for ephemeral injection.
# AGENTS.md is the Codex CLI's native agent-rules config.
_EPHEMERAL_CONFIG_FILENAME = "AGENTS.md"

# The logical MCP server name z-harness registers with Codex.
# Must match the [mcp_servers.<name>] key that ``codex mcp add`` creates.
_MCP_SERVER_NAME = "z-harness"

# Magic marker reference — imported from inject_safety to stay in sync.
_MAGIC_MARKER = inject_safety.MAGIC_MARKER

# Template for the ephemeral AGENTS.md.  Embeds the magic marker so
# inject_safety recognises it as z-harness-authored on re-runs.
_AGENTS_MD_TEMPLATE = """\
<!-- {marker} (ephemeral z-harness injection — delete to stop injection) -->
<!-- This file was written by `z-harness launch` and is gitignored. -->
<!-- It informs Codex that z-harness is loaded from: {plugin_root} -->

# z-harness (ephemeral session)

This AGENTS.md was injected by `z-harness launch` for this session.
It will be removed automatically on exit.  Do not commit this file.

z-harness plugin root: `{plugin_root}`

## Agent roles

Personas and prompt files are exported under `prompts/personas/`.
Run `z-harness export --host codex` to populate the full prompt library.
""".format


# ---------------------------------------------------------------------------
# Command-capability matrix registration
# ---------------------------------------------------------------------------

#: Commands that require multi-agent orchestration — blocked on flattened hosts.
_MULTI_AGENT_COMMANDS = frozenset(
    {
        "z-implement-all",
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
    supports_project_mcp=True,    # codex mcp add writes ~/.codex/config.toml (global)
    supports_user_mcp=False,      # no separate user-scoped MCP store in codex
    needs_trust_prompt=False,     # codex runs non-interactively, no per-tool approval
    supports_cwd_override=False,  # no --cwd / --project flag in codex CLI
    cleanup_strategy="ephemeral",
)


# ---------------------------------------------------------------------------
# CodexAdapter
# ---------------------------------------------------------------------------


class CodexAdapter:
    """Host adapter for Codex CLI (fidelity: flattened).

    Instantiate once per process; safe to reuse across multiple inject/
    cleanup cycles (each inject() produces an independent Injection).

    MCP note (F4)
    -------------
    inject() registers the z-harness MCP entry in ``~/.codex/config.toml``
    idempotently (only when ``capabilities.supports_project_mcp`` is True).
    cleanup() does NOT remove this entry — the global MCP config is shared
    across all of the user's Codex projects.  Explicit removal is performed
    only by ``z-harness doctor --clear-mcp``.
    """

    name: str = _HOST_NAME
    fidelity_tier: Literal["flattened"] = _FIDELITY_TIER
    capabilities: Capabilities = _CAPABILITIES

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        """Probe for the ``codex`` binary on PATH and read its version.

        Runs ``codex --version`` (non-interactive; safe to call without
        side-effects).  The version string is whatever the binary prints on
        a single line to stdout.

        Returns
        -------
        DetectResult
            installed=True when the binary is on PATH and exits zero.
            version=None when the binary is present but ``--version`` fails.
        """
        binary = shutil.which(_CODEX_BINARY)
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
        """Export personas to the Codex prompts layout under *dest*.

        Delegates to ``runtime/drivers/codex/persona_export.py::export_persona()``
        for each persona file found in the ``personas/`` directory at the
        harness repo root.

        The written layout is::

            <dest>/prompts/personas/<name>.md

        Returns
        -------
        ExportResult
            fidelity="flattened"; files lists relative paths under dest.
        """
        dest = Path(dest)

        # Locate the harness repo root (where personas/ lives).
        harness_root = Path(__file__).parent.parent.parent.resolve()
        personas_dir = harness_root / "personas"

        written: list[Path] = []
        warnings: list[str] = []

        if not personas_dir.is_dir():
            return ExportResult(
                dest=dest,
                files=[],
                fidelity="flattened",
                warnings=["personas/ directory not found; nothing exported"],
            )

        # Lazy import so the adapter can be imported without the runtime
        # package in sys.path in environments where only z_harness_cli is
        # installed.
        try:
            from runtime.drivers.codex.persona_export import export_persona
        except ImportError as exc:
            return ExportResult(
                dest=dest,
                files=[],
                fidelity="flattened",
                warnings=[
                    f"runtime.drivers.codex.persona_export not importable: {exc}"
                ],
            )

        for persona_file in sorted(personas_dir.glob("*.md")):
            try:
                out_path = export_persona(persona_file, dest)
                written.append(out_path.relative_to(dest))
            except (ValueError, OSError) as exc:
                warnings.append(f"Skipped {persona_file.name}: {exc}")

        return ExportResult(
            dest=dest,
            files=written,
            fidelity="flattened",
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # inject
    # ------------------------------------------------------------------

    def inject(
        self,
        state_env: dict[str, str],
        mode: Literal["ephemeral", "in_place"],
        project: Path,
        *,
        mcp_config_path: str | None = None,
    ) -> Injection:
        """Write a host-native AGENTS.md, optionally register MCP, return Injection.

        For ``mode="ephemeral"``:
          * Runs inject_safety.preflight_targets() on the target AGENTS.md
            before writing (clobber guard).
          * Writes a gitignored ``AGENTS.md`` carrying the magic marker.
          * Calls inject_safety.ensure_gitignored() so the file is never
            accidentally committed.
          * Injects CLAUDE_PLUGIN_ROOT into the child env (D14).
          * When ``capabilities.supports_project_mcp`` is True, registers the
            z-harness MCP server in ``~/.codex/config.toml`` idempotently
            using ``runtime.drivers.codex.mcp.ensure_mcp_registered()``.
            This registration is global/persistent (F4) — NOT undone by
            cleanup().

        For ``mode="in_place"``:
          * Writes ``AGENTS.md`` into the project without gitignoring
            (caller manages lifecycle; cleanup is a no-op).
          * MCP is still registered idempotently (global/persistent).

        The returned Injection's ``_cleanup_fn`` is set to
        ``CodexAdapter.cleanup`` so the context-manager protocol works.

        Parameters
        ----------
        state_env:
            z-harness env bundle (from env_bundle.resolve_env_bundle()).
            Merged into the child env as-is.
        mode:
            "ephemeral" — write gitignored config for this session only.
            "in_place"  — committed project file; caller manages lifecycle.
        project:
            Absolute path to the user's project repo root.
        mcp_config_path:
            Optional path to the MCP config file to pass to ``codex mcp add``.
            When None the adapter uses a built-in default path derived from
            the harness root (``<harness_root>/exports/codex/mcp_config.json``).
            Callers can override this for testing or custom layouts.

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

        # Target path for the session AGENTS.md.
        target = project / _EPHEMERAL_CONFIG_FILENAME

        if mode == "ephemeral":
            # Clobber-safe pre-flight (raises ClobberRefused if the file
            # exists and is not z-harness-authored, and force=False).
            backup_manifest = inject_safety.preflight_targets(
                [target],
                project,
                force=False,
            )

            # Write the session AGENTS.md.
            content = _AGENTS_MD_TEMPLATE(
                marker=_MAGIC_MARKER,
                plugin_root=harness_root,
            )
            target.write_text(content, encoding="utf-8")
            injected_files.append(target)

            # Ensure the written file is gitignored.
            inject_safety.ensure_gitignored([target], project)

        else:
            # in_place: write but do not gitignore; caller manages lifecycle.
            content = _AGENTS_MD_TEMPLATE(
                marker=_MAGIC_MARKER,
                plugin_root=harness_root,
            )
            target.write_text(content, encoding="utf-8")
            injected_files.append(target)

        # MCP registration — capability-gated, global/persistent (F4).
        # Runs in both ephemeral and in_place modes: the MCP config is
        # independent of the per-session AGENTS.md injection.
        if self.capabilities.supports_project_mcp:
            codex_binary = shutil.which(_CODEX_BINARY) or _CODEX_BINARY
            resolved_mcp_config = (
                mcp_config_path
                if mcp_config_path is not None
                else str(
                    Path(harness_root) / "exports" / "codex" / "mcp_config.json"
                )
            )
            try:
                from runtime.drivers.codex.mcp import (  # noqa: PLC0415
                    McpRegistrationError,
                    ensure_mcp_registered,
                )
                try:
                    ensure_mcp_registered(
                        mcp_config_path=resolved_mcp_config,
                        server_name=_MCP_SERVER_NAME,
                        codex_path=codex_binary,
                    )
                except McpRegistrationError:
                    # `codex mcp add` exited non-zero (e.g. codex binary absent
                    # or config dir unwritable).  Best-effort per F4: AGENTS.md
                    # is already written; continue the session without MCP.
                    pass
            except ImportError:
                # Runtime package not available (e.g. standalone CLI install).
                # MCP registration is a best-effort enhancement; skip silently.
                pass

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
        """PTY-passthrough exec of ``codex`` in *project*.

        Blocks until codex exits and returns its exit code.

        The caller is responsible for calling cleanup() afterwards (or
        using the Injection context manager so cleanup always runs).

        Parameters
        ----------
        project:
            Working directory for the ``codex`` process.
        env:
            Full environment mapping (typically the Injection.env dict
            merged over os.environ via env_bundle.apply_env_bundle()).

        Returns
        -------
        int
            codex's exit code (0 = clean exit).

        Raises
        ------
        FileNotFoundError
            If the ``codex`` binary is not on PATH.
        PTYUnsupportedError
            On Windows or any platform without the ``pty`` stdlib module.
        """
        from z_harness_cli.pty_launch import pty_launch

        binary = shutil.which(_CODEX_BINARY) or _CODEX_BINARY
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

        For ephemeral mode this removes ``AGENTS.md`` and restores any
        pre-existing file that was backed up.

        For in_place mode this is a no-op (caller manages lifecycle).

        IMPORTANT — MCP registration is NOT reversed here (F4).
        The ``~/.codex/config.toml`` MCP entry is global and persistent;
        removing it on every session exit would break the user's other
        Codex projects.  Explicit removal is performed only via
        ``z-harness doctor --clear-mcp``.

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

        # Derive project from the injected file: AGENTS.md is written at
        # <project>/AGENTS.md, so its parent is the project root.
        agents_path = injection.injected_files[0]
        project = agents_path.parent
        inject_safety.cleanup(project)
