"""OMP host adapter — fidelity gated by native parity evidence (T009).

OMP is detected as a first-class host via the ``omp`` binary.  Command tiers
and adapter fidelity are not hardcoded: they are driven by the single parity
gate in ``z_harness_cli.adapters.omp_parity_gate``.  The gate reads T008
behavioral evidence and promotes only the command families that have proven
Claude-equivalent behavior.

Detection
---------
Runs ``omp --version`` and records the resolved binary path.

Injection / launch
------------------
OMP launch uses the shared ephemeral injection machinery: ``inject()`` writes
only a gitignored, session-scoped OMP state file plus ``OMP_PLUGIN_ROOT`` in
the child environment, and ``launch()`` PTY-hands over to ``omp`` in the
requested project directory.

Export
------
Delegates to ``runtime.drivers.omp.export::export`` for the OMP-native
``.omp/z-harness`` package layout.  Export fidelity is read from the parity
gate (``omp_export_fidelity()``) — it cannot diverge from adapter fidelity.

Parity gate
-----------
All three surfaces (adapter ``fidelity_tier``, export ``ExportResult.fidelity``,
and per-command COMMAND_CAPABILITY_MATRIX tiers) are driven by
``omp_parity_gate``.  Removing any T008 evidence entry immediately degrades the
corresponding family — no adapter change required.
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
from z_harness_cli.adapters.omp_parity_gate import (
    omp_adapter_fidelity,
    omp_command_tier,
    omp_export_fidelity,
)

from z_harness_cli import inject_safety
from z_harness_cli.inject_safety import MAGIC_MARKER as _MAGIC_MARKER


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HOST_NAME = "omp"
_OMP_BINARY = "omp"
_EPHEMERAL_SESSION_DIRNAME = ".omp"
_EPHEMERAL_SESSION_SUBDIR = "z-harness"
_EPHEMERAL_SESSION_FILENAME = "session.yml"


def _OMP_SESSION_TEMPLATE(*, marker: str, plugin_root: str) -> str:
    return (
        f"# {marker} (OMP ephemeral launch state)\n"
        "# Created by z-harness launch and removed on session cleanup.\n"
        "# Runtime discovery is process-scoped via OMP_PLUGIN_ROOT.\n"
        f"# OMP_PLUGIN_ROOT={plugin_root}\n"
    )


# ---------------------------------------------------------------------------
# Command-capability matrix registration
#
# Tiers are read from the parity gate — not hardcoded.  The gate drives
# promotion from its PARITY_EVIDENCE registry; removing any evidence entry
# immediately downgrades the corresponding family here.
# ---------------------------------------------------------------------------

register_command_tiers(
    _HOST_NAME,
    {cmd: omp_command_tier(cmd) for cmd in KNOWN_COMMANDS},
)


# ---------------------------------------------------------------------------
# Capabilities declaration
# ---------------------------------------------------------------------------

_CAPABILITIES = Capabilities(
    supports_project_mcp=False,
    supports_user_mcp=False,
    needs_trust_prompt=False,
    supports_cwd_override=False,
    cleanup_strategy="ephemeral",
)


# ---------------------------------------------------------------------------
# OmpAdapter
# ---------------------------------------------------------------------------


class OmpAdapter:
    """Host adapter for OMP.

    Fidelity tier and command tiers are driven by the parity gate
    (``omp_parity_gate``).  Do NOT cache or hardcode these values: reading them
    fresh from the gate on every attribute access ensures the three surfaces
    (adapter, export, matrix) stay synchronized.
    """

    name: str = _HOST_NAME
    capabilities: Capabilities = _CAPABILITIES

    @property
    def fidelity_tier(self) -> str:  # type: ignore[override]
        """Return the current parity-gate-driven fidelity tier."""
        return omp_adapter_fidelity()

    def detect(self) -> DetectResult:
        """Probe for the ``omp`` binary on PATH and read its version."""
        binary = shutil.which(_OMP_BINARY)
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
            return DetectResult(installed=True, binary=binary)

        if result.returncode != 0:
            return DetectResult(installed=True, binary=binary)

        version = result.stdout.strip() or result.stderr.strip() or None
        return DetectResult(installed=True, version=version, binary=binary)

    def export_payload(self, dest: Path) -> ExportResult:
        """Delegate OMP export to the runtime exporter.

        Export fidelity is read from the parity gate (``omp_export_fidelity()``)
        so that adapter fidelity and export fidelity cannot diverge.

        Missing exporter is surfaced as a warning on a gate-driven fidelity
        result; validation warnings from the runtime exporter remain hard
        failures.
        """
        dest = Path(dest)
        harness_root = Path(__file__).parent.parent.parent.resolve()
        fidelity = omp_export_fidelity()

        try:
            from runtime.drivers.omp.export import export as omp_export
        except ImportError as exc:
            return ExportResult(
                dest=dest,
                files=[],
                fidelity=fidelity,
                warnings=[f"runtime.drivers.omp.export not importable: {exc}"],
            )

        rt_result = omp_export(harness_root, dest)
        if rt_result.warnings:
            raise RuntimeError(
                "omp runtime export produced validation errors:\n"
                + "\n".join(f"  {w}" for w in rt_result.warnings)
            )

        return ExportResult(
            dest=dest,
            files=list(rt_result.files),
            fidelity=fidelity,
            warnings=[],
        )

    def inject(
        self,
        state_env: dict[str, str],
        mode: Literal["ephemeral", "in_place"],
        project: Path,
    ) -> Injection:
        """Write OMP session-scoped state and return an injection handle.

        OMP runtime discovery comes from ``OMP_PLUGIN_ROOT``, but launch-time
        ephemeral injection must point that env var at the session-scoped
        package root this adapter owns: ``<project>/.omp/z-harness``.  The only
        file write is ``.omp/z-harness/session.yml``: a gitignored file with the
        z-harness marker so the shared clobber/orphan cleanup machinery can
        distinguish it from user-authored OMP config.  The checked-in
        ``.omp/config.yml`` suppression file is never targeted or modified.
        """
        project = Path(project).resolve()

        env: dict[str, str] = dict(os.environ)
        env.update(state_env)

        # OMP should not inherit stale z-harness plugin-root vars for other
        # hosts; the runtime discovery surface for this adapter is OMP_PLUGIN_ROOT.
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        env.pop("ANTIGRAVITY_PLUGIN_ROOT", None)

        injected_files: list[Path] = []
        backup_manifest: dict[str, Path] | None = None

        if mode == "ephemeral":
            target = (
                project
                / _EPHEMERAL_SESSION_DIRNAME
                / _EPHEMERAL_SESSION_SUBDIR
                / _EPHEMERAL_SESSION_FILENAME
            )
            package_root = target.parent
            plugin_root = str(package_root)
            env["OMP_PLUGIN_ROOT"] = plugin_root

            backup_manifest = inject_safety.preflight_targets(
                [target],
                project,
                force=False,
            )

            package_root.mkdir(parents=True, exist_ok=True)
            target.write_text(
                _OMP_SESSION_TEMPLATE(
                    marker=_MAGIC_MARKER,
                    plugin_root=plugin_root,
                ),
                encoding="utf-8",
            )
            injected_files.append(target)
            inject_safety.ensure_gitignored([target], project)

        return Injection(
            env=env,
            injected_files=injected_files,
            mode=mode,
            host=_HOST_NAME,
            backup_manifest=backup_manifest if backup_manifest else None,
            _cleanup_fn=lambda inj: self.cleanup(inj),
        )

    def launch(self, project: Path, env: dict[str, str]) -> int:
        """PTY-passthrough exec of ``omp`` in *project* with the supplied env."""
        # Lazy import so launch.py can wrap the module-level pty_launch and own
        # signal-trapped cleanup, matching the other adapters' launch contract.
        from z_harness_cli.pty_launch import pty_launch

        binary = shutil.which(_OMP_BINARY) or _OMP_BINARY
        return pty_launch(
            argv=[binary],
            env=env,
            cwd=Path(project).resolve(),
        )

    def cleanup(self, injection: Injection) -> None:
        """Remove OMP session-scoped state via the shared safety manifest."""
        if not injection.injected_files:
            return

        if injection.mode == "in_place":
            return

        session_path = injection.injected_files[0]
        project = session_path.parent.parent.parent
        session_dir = session_path.parent
        inject_safety.cleanup(project)
        try:
            session_dir.rmdir()
        except OSError:
            pass
