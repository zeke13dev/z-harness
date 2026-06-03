"""Claude Code host adapter — fidelity: native.

This is the reference (native-fidelity) adapter.  All /z-* commands run
identically to how they behave when users launch Claude Code directly.

Injection modes
---------------
installed-plugin:  The z-harness Claude plugin is installed in the user's
    Claude Code instance (the normal production path).  No config file needs
    to be written; Claude Code resolves CLAUDE_PLUGIN_ROOT from its own
    environment.  inject() returns an Injection with mode="in_place" and an
    empty injected_files list.

ephemeral:  A gitignored CLAUDE.md is written to the project root with the
    z-harness magic marker so inject_safety can track it.  The CLAUDE_PLUGIN_ROOT
    env var is injected so the spawned Claude Code process can locate the
    harness runtime.  inject() returns an Injection with mode="ephemeral" and
    the written file listed for cleanup.

Export layout (claude plugin)
-----------------------------
Delegates to runtime/drivers/claude/persona_export.py::export_persona().
The output is <dest>/personas/<name>.md — a flat Markdown file injected as a
system-prompt prefix by the Claude subagent dispatcher.

Command-capability matrix
--------------------------
All /z-* commands run natively on Claude Code.
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
from z_harness_cli.pty_launch import pty_launch


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HOST_NAME = "claude"
_FIDELITY_TIER = "native"

# The gitignored config file written for ephemeral injection.  It carries the
# z-harness magic marker so inject_safety can recognise it as our file and
# not treat it as a foreign clobber on repeat runs.
_EPHEMERAL_CONFIG_FILENAME = "CLAUDE.md"

# Template for the ephemeral CLAUDE.md.  Embeds the magic marker + the
# CLAUDE_PLUGIN_ROOT so the spawned process resolves the harness runtime.
_CLAUDE_MD_TEMPLATE = """\
<!-- {marker} (ephemeral z-harness injection — delete to stop injection) -->
<!-- This file was written by `z-harness launch` and is gitignored. -->
<!-- It informs Claude Code that z-harness is loaded from: {plugin_root} -->

# z-harness (ephemeral)

This CLAUDE.md was injected by `z-harness launch` for this session.
It will be removed automatically on exit.  Do not commit this file.
""".format

# Magic marker reference — import from inject_safety to stay in sync.
_MAGIC_MARKER = inject_safety.MAGIC_MARKER


# ---------------------------------------------------------------------------
# Command-capability matrix registration
# ---------------------------------------------------------------------------

register_command_tiers(
    _HOST_NAME,
    {cmd: "native" for cmd in KNOWN_COMMANDS},
)


# ---------------------------------------------------------------------------
# Capabilities declaration
# ---------------------------------------------------------------------------

_CAPABILITIES = Capabilities(
    supports_project_mcp=True,
    supports_user_mcp=True,
    needs_trust_prompt=False,
    supports_cwd_override=True,
    cleanup_strategy="ephemeral",
)


# ---------------------------------------------------------------------------
# ClaudeAdapter
# ---------------------------------------------------------------------------


class ClaudeAdapter:
    """Host adapter for Claude Code (fidelity: native).

    Instantiate once per process; safe to reuse across multiple inject/
    cleanup cycles (each inject() produces an independent Injection).
    """

    name: str = _HOST_NAME
    fidelity_tier: Literal["native"] = _FIDELITY_TIER
    capabilities: Capabilities = _CAPABILITIES

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        """Probe for the ``claude`` binary on PATH and read its version.

        Runs ``claude --version`` (non-interactive; safe to call without
        side-effects).  The version string is whatever the binary prints on
        a single line to stdout.

        Returns
        -------
        DetectResult
            installed=True when the binary is on PATH and exits zero.
            version=None when the binary is present but ``--version`` fails.
        """
        binary = shutil.which("claude")
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
        """Export personas to the Claude plugin layout under *dest*.

        Delegates to ``runtime/drivers/claude/persona_export.py::export_persona()``
        for each persona file found in the ``personas/`` directory at the
        harness repo root.

        The written layout is::

            <dest>/personas/<name>.md

        Returns
        -------
        ExportResult
            fidelity="native"; files lists relative paths under dest.
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
                fidelity="native",
                warnings=["personas/ directory not found; nothing exported"],
            )

        # Lazy import so the adapter can be imported without the runtime
        # package in sys.path in environments where only z_harness_cli is
        # installed.
        try:
            from runtime.drivers.claude.persona_export import export_persona
        except ImportError as exc:
            return ExportResult(
                dest=dest,
                files=[],
                fidelity="native",
                warnings=[
                    f"runtime.drivers.claude.persona_export not importable: {exc}"
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
            fidelity="native",
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
    ) -> Injection:
        """Write host-native config and return an Injection handle.

        For ``mode="ephemeral"``:
          * Runs inject_safety.preflight_targets() on the target CLAUDE.md
            before writing (clobber guard).
          * Writes a gitignored CLAUDE.md carrying the magic marker.
          * Calls inject_safety.ensure_gitignored() so the file is never
            accidentally committed.
          * Injects CLAUDE_PLUGIN_ROOT into the child env.

        For ``mode="in_place"``:
          * No config files are written (the plugin is assumed installed;
            Claude Code resolves CLAUDE_PLUGIN_ROOT from its own env).
          * Returns an Injection with empty injected_files.

        The returned Injection's ``_cleanup_fn`` is set to
        ``ClaudeAdapter.cleanup`` so the context-manager protocol works.

        Parameters
        ----------
        state_env:
            z-harness env bundle (from env_bundle.resolve_env_bundle()).
            Merged into the child env as-is.
        mode:
            "ephemeral" — write gitignored config for this session only.
            "in_place"  — installed-plugin mode; no files written.
        project:
            Absolute path to the user's project repo root.

        Returns
        -------
        Injection
            env merges *state_env* + CLAUDE_PLUGIN_ROOT (ephemeral) into a
            copy of os.environ.  injected_files lists any written paths.
        """
        project = Path(project).resolve()
        env: dict[str, str] = dict(os.environ)
        env.update(state_env)
        injected_files: list[Path] = []
        backup_manifest: dict[str, Path] | None = None

        if mode == "ephemeral":
            # Determine the harness root to inject as CLAUDE_PLUGIN_ROOT.
            harness_root = str(Path(__file__).parent.parent.parent.resolve())
            env["CLAUDE_PLUGIN_ROOT"] = harness_root

            target = project / _EPHEMERAL_CONFIG_FILENAME

            # Clobber-safe pre-flight (raises ClobberRefused if the file
            # exists and is not z-harness-authored, and force=False).
            backup_manifest = inject_safety.preflight_targets(
                [target],
                project,
                force=False,
            )

            # Write the gitignored CLAUDE.md.
            content = _CLAUDE_MD_TEMPLATE(
                marker=_MAGIC_MARKER,
                plugin_root=harness_root,
            )
            target.write_text(content, encoding="utf-8")
            injected_files.append(target)

            # Ensure the written file is gitignored.
            inject_safety.ensure_gitignored([target], project)

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
        """PTY-passthrough exec of ``claude`` in *project*.

        Blocks until Claude Code exits and returns its exit code.

        The caller is responsible for calling cleanup() afterwards (or
        using the Injection context manager so cleanup always runs).

        Parameters
        ----------
        project:
            Working directory for the ``claude`` process.
        env:
            Full environment mapping (typically the Injection.env dict
            merged over os.environ via env_bundle.apply_env_bundle()).

        Returns
        -------
        int
            Claude Code's exit code (0 = clean exit).

        Raises
        ------
        FileNotFoundError
            If the ``claude`` binary is not on PATH.
        PTYUnsupportedError
            On Windows or any platform without the ``pty`` stdlib module.
        """
        binary = shutil.which("claude") or "claude"
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

        Parameters
        ----------
        injection:
            The Injection returned by a prior call to inject().
            (The project path is reconstructed from injected_files.)
        """
        if not injection.injected_files:
            # in_place mode or already cleaned.
            return

        # Derive project from the first injected file's parent
        # (inject() always writes into project/).
        project = injection.injected_files[0].parent
        inject_safety.cleanup(project)
