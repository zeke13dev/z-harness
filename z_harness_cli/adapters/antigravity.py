"""Antigravity (agy) host adapter — fidelity: high.

agy is a single-agent host that supports native skill and persona loading via
the ``.agent/`` directory convention.  All /z-* commands run in high-fidelity
mode: single-agent orchestration works natively; multi-agent commands
(/z-implement-all, /z-panel, /z-consult, /z-gate) are degraded (no subagent
dispatch) rather than fully blocked.

Injection modes
---------------
ephemeral:  A gitignored ``.agent/z-harness-session.md`` instruction file is
    written carrying the MAGIC_MARKER.  The ANTIGRAVITY_PLUGIN_ROOT env var is
    injected so the spawned agy process can locate the harness runtime.
    cleanup() removes the file.

in_place:  The session file is written as a committed project file (the caller
    manages its lifecycle; cleanup is a no-op for files the caller committed).

Export layout (agy native skills/personas)
------------------------------------------
Delegates to ``runtime/drivers/antigravity/persona_export.py::export_persona()``
for persona files, which writes::

    <dest>/.agent/personas/<name>.md

Skills and agents are exported under::

    <dest>/.agent/skills/<name>.md
    <dest>/.agent/agents/<name>.md

Capabilities
------------
agy reads personas natively from ``.agent/personas/`` — no context-injection
workaround needed.  agy supports project-scoped config via ``.agent/config.toml``.
There is no documented user-scoped MCP path; trust prompts are suppressed in
non-interactive mode.  ``agy`` does not expose a ``--cwd`` flag; working directory
is set via cwd of the spawned process.

Command-capability matrix
--------------------------
All /z-* commands run in high-fidelity mode.  Multi-agent commands run in
degraded mode (single-agent transliteration) rather than blocked — agy supports
the underlying skills natively, but subagent dispatch is absent.

Attribution / decision record
------------------------------
- binary probed: agy (on PATH; version via ``agy --version``)
- fidelity=high: native skill/persona loading via .agent/; single-agent only
- supports_project_mcp=False: agy uses .agent/config.toml (not MCP protocol)
- supports_user_mcp=False: no documented user-scoped MCP path
- needs_trust_prompt=False: agy does not present interactive trust prompts
- supports_cwd_override=False: agy has no --cwd / --project flag
- cleanup_strategy="ephemeral": session file gitignored + deleted on cleanup
- ANTIGRAVITY_PLUGIN_ROOT injected for ephemeral launches (D14)
- decision source: runtime/drivers/antigravity/; probe date 2026-06-03
  decided by: T011 implementer (Claude Sonnet 4.6) under T011 task block
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

_HOST_NAME = "antigravity"
_FIDELITY_TIER: Literal["high"] = "high"

# The agy binary name.
_AGY_BINARY = "agy"

# Gitignored session instruction file written for ephemeral injection.
# Placed under .agent/ so agy picks it up automatically.
_EPHEMERAL_SESSION_DIRNAME = ".agent"
_EPHEMERAL_SESSION_FILENAME = "z-harness-session.md"

# Magic marker reference — imported from inject_safety to stay in sync.
_MAGIC_MARKER = inject_safety.MAGIC_MARKER

# Template for the ephemeral session instruction file.  Embeds the magic
# marker so inject_safety recognises it as z-harness-authored on re-runs.
_SESSION_MD_TEMPLATE = """\
<!-- {marker} (ephemeral z-harness injection — delete to stop injection) -->
<!-- This file was written by `z-harness launch` and is gitignored. -->
<!-- It informs agy that z-harness is loaded from: {plugin_root} -->

# z-harness (ephemeral session)

This file was injected by `z-harness launch` for this session.
It will be removed automatically on exit.  Do not commit this file.

z-harness plugin root: `{plugin_root}`
""".format


# ---------------------------------------------------------------------------
# Command-capability matrix registration
# ---------------------------------------------------------------------------

#: Commands that require multi-agent orchestration — degraded on high-fidelity
#: hosts (single-agent transliteration present, subagent dispatch absent).
_MULTI_AGENT_COMMANDS = frozenset(
    {
        "z-implement-all",
        "z-panel",
        "z-consult",
        "z-gate",
    }
)

register_command_tiers(
    _HOST_NAME,
    {
        cmd: ("degraded" if cmd in _MULTI_AGENT_COMMANDS else "native")
        for cmd in KNOWN_COMMANDS
    },
)


# ---------------------------------------------------------------------------
# Capabilities declaration
# ---------------------------------------------------------------------------

_CAPABILITIES = Capabilities(
    supports_project_mcp=False,   # agy uses .agent/config.toml, not MCP protocol
    supports_user_mcp=False,      # no documented user-scoped MCP path
    needs_trust_prompt=False,     # agy does not present interactive trust prompts
    supports_cwd_override=False,  # no --cwd / --project flag in agy CLI
    cleanup_strategy="ephemeral",
)


# ---------------------------------------------------------------------------
# AntigravityAdapter
# ---------------------------------------------------------------------------


class AntigravityAdapter:
    """Host adapter for Antigravity/agy (fidelity: high).

    Instantiate once per process; safe to reuse across multiple inject/
    cleanup cycles (each inject() produces an independent Injection).
    """

    name: str = _HOST_NAME
    fidelity_tier: Literal["high"] = _FIDELITY_TIER
    capabilities: Capabilities = _CAPABILITIES

    # ------------------------------------------------------------------
    # detect
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        """Probe for the ``agy`` binary on PATH and read its version.

        Runs ``agy --version`` (non-interactive; safe to call without
        side-effects).  The version string is whatever the binary prints on
        a single line to stdout.

        Returns
        -------
        DetectResult
            installed=True when the binary is on PATH and exits zero.
            version=None when the binary is present but ``--version`` fails.
        """
        binary = shutil.which(_AGY_BINARY)
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
        """Export commands, agents, skills, and personas to the agy native layout.

        Delegates to ``runtime/drivers/antigravity/export.py::export()`` for
        commands, agents, and skills (producing ``.agent/workflows/``,
        ``.agent/rules/``, ``.agent/skills/``, and ``prompts/`` files), then
        runs the existing persona loop via
        ``runtime/drivers/antigravity/persona_export.py::export_persona()``
        for each persona file found in the ``personas/`` directory.

        Both results are merged into a single ExportResult.  Fidelity is
        always ``"high"`` for Antigravity.

        Non-empty warnings from the runtime export (validation errors) are
        preserved and re-raised as ``RuntimeError`` so callers that expect the
        legacy hard-gate behaviour see a failure signal rather than a silent
        downgrade.

        Collision assert (MINOR-6): persona names must not overlap with
        command/agent/skill ids in the agy layout.  A collision raises
        ``RuntimeError`` with a descriptive message.

        The written layout is::

            <dest>/.agent/workflows/<id>.md          — commands
            <dest>/.agent/rules/z-harness-<id>.md   — agents
            <dest>/.agent/skills/<id>/SKILL.md       — skills
            <dest>/prompts/<id>.md                   — flat prompts
            <dest>/.agent/personas/<name>.md         — personas

        Returns
        -------
        ExportResult
            fidelity="high"; files lists all written files under dest;
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
        personas_dir = harness_root / "personas"

        all_files: list[Path] = []
        all_warnings: list[str] = []

        # ------------------------------------------------------------------
        # Stage 1: runtime export — commands, agents, skills
        # ------------------------------------------------------------------
        try:
            from runtime.drivers.antigravity.export import export as agy_export
        except ImportError as exc:
            all_warnings.append(
                f"runtime.drivers.antigravity.export not importable: {exc}"
            )
            agy_export = None  # type: ignore[assignment]

        runtime_ids: set[str] = set()
        if agy_export is not None:
            rt_result = agy_export(harness_root, dest)
            all_files.extend(rt_result.files)
            if rt_result.warnings:
                # Surface validation warnings as a hard failure — preserving
                # the legacy export-agy.py validation gate behaviour.
                raise RuntimeError(
                    f"antigravity runtime export produced validation errors:\n"
                    + "\n".join(f"  {w}" for w in rt_result.warnings)
                )
            # Collect ids from workflows/rules/skills to check for persona
            # collisions.  Use file stems from .agent/workflows/ as
            # the representative set of command/agent/skill ids.
            for f in rt_result.files:
                p = Path(f)
                # Workflows: .agent/workflows/<id>.md
                # Rules: .agent/rules/z-harness-<id>.md  → strip prefix
                # Skills: .agent/skills/<id>/SKILL.md
                if p.parent.name == "workflows":
                    runtime_ids.add(p.stem)
                elif p.parent.name == "rules" and p.stem.startswith("z-harness-"):
                    runtime_ids.add(p.stem[len("z-harness-"):])
                elif p.name == "SKILL.md":
                    runtime_ids.add(p.parent.name)

        # ------------------------------------------------------------------
        # Stage 2: persona export loop
        # ------------------------------------------------------------------
        if not personas_dir.is_dir():
            all_warnings.append("personas/ directory not found; persona export skipped")
        else:
            # Lazy import so the adapter can load without the full runtime
            # package in environments where only z_harness_cli is installed.
            try:
                from runtime.drivers.antigravity.persona_export import export_persona
            except ImportError as exc:
                all_warnings.append(
                    f"runtime.drivers.antigravity.persona_export not importable: {exc}"
                )
                export_persona = None  # type: ignore[assignment]

            if export_persona is not None:
                for persona_file in sorted(personas_dir.glob("*.md")):
                    persona_name = persona_file.stem
                    # Collision check: persona names must not overlap with
                    # command/agent/skill ids in the agy layout.
                    if persona_name in runtime_ids:
                        raise RuntimeError(
                            f"antigravity export collision: persona name "
                            f"{persona_name!r} conflicts with an existing "
                            f"command/agent/skill id. Rename the persona or "
                            f"the conflicting source file."
                        )
                    try:
                        out_path = export_persona(persona_file, dest)
                        all_files.append(out_path)
                    except (ValueError, OSError) as exc:
                        all_warnings.append(f"Skipped {persona_file.name}: {exc}")

        return ExportResult(
            dest=dest,
            files=all_files,
            fidelity="high",
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
        """Write a host-native .agent session file and return an Injection handle.

        For ``mode="ephemeral"``:
          * Runs inject_safety.preflight_targets() on the target session file
            before writing (clobber guard).
          * Writes a gitignored ``.agent/z-harness-session.md``
            carrying the magic marker.
          * Calls inject_safety.ensure_gitignored() so the file is never
            accidentally committed.
          * Injects ANTIGRAVITY_PLUGIN_ROOT into the child env (D14: agy reads
            this var when the harness is injected).

        For ``mode="in_place"``:
          * Writes ``.agent/z-harness-session.md`` into the project
            without gitignoring (caller manages lifecycle; cleanup is no-op).

        The returned Injection's ``_cleanup_fn`` is set to
        ``AntigravityAdapter.cleanup`` so the context-manager protocol works.

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

        Returns
        -------
        Injection
            env merges *state_env* + ANTIGRAVITY_PLUGIN_ROOT into a copy of
            os.environ.  injected_files lists any written paths.
        """
        project = Path(project).resolve()
        env: dict[str, str] = dict(os.environ)
        env.update(state_env)
        injected_files: list[Path] = []
        backup_manifest: dict[str, Path] | None = None

        # Determine the harness root to inject as ANTIGRAVITY_PLUGIN_ROOT (D14).
        harness_root = str(Path(__file__).parent.parent.parent.resolve())
        env["ANTIGRAVITY_PLUGIN_ROOT"] = harness_root

        # Target path for the session file.
        agent_dir = project / _EPHEMERAL_SESSION_DIRNAME
        target = agent_dir / _EPHEMERAL_SESSION_FILENAME

        if mode == "ephemeral":
            # Clobber-safe pre-flight (raises ClobberRefused if the file
            # exists and is not z-harness-authored, and force=False).
            backup_manifest = inject_safety.preflight_targets(
                [target],
                project,
                force=False,
            )

            # Write the session instruction file.
            agent_dir.mkdir(parents=True, exist_ok=True)
            content = _SESSION_MD_TEMPLATE(
                marker=_MAGIC_MARKER,
                plugin_root=harness_root,
            )
            target.write_text(content, encoding="utf-8")
            injected_files.append(target)

            # Ensure the written file is gitignored.
            inject_safety.ensure_gitignored([target], project)

        else:
            # in_place: write but do not gitignore; caller manages lifecycle.
            agent_dir.mkdir(parents=True, exist_ok=True)
            content = _SESSION_MD_TEMPLATE(
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
        """PTY-passthrough exec of ``agy`` in *project*.

        Blocks until agy exits and returns its exit code.

        The caller is responsible for calling cleanup() afterwards (or
        using the Injection context manager so cleanup always runs).

        Parameters
        ----------
        project:
            Working directory for the ``agy`` process.
        env:
            Full environment mapping (typically the Injection.env dict
            merged over os.environ via env_bundle.apply_env_bundle()).

        Returns
        -------
        int
            agy's exit code (0 = clean exit).

        Raises
        ------
        FileNotFoundError
            If the ``agy`` binary is not on PATH.
        PTYUnsupportedError
            On Windows or any platform without the ``pty`` stdlib module.
        """
        from z_harness_cli.pty_launch import pty_launch

        binary = shutil.which(_AGY_BINARY) or _AGY_BINARY
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

        For ephemeral mode this removes ``.agent/z-harness-session.md``
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

        # Derive project from the first injected file: the session file is at
        # <project>/.agent/z-harness-session.md, so parent.parent is the project root.
        session_path = injection.injected_files[0]
        project = session_path.parent.parent
        inject_safety.cleanup(project)
