"""HostAdapter contract — Protocol/ABC + supporting types.

All concrete adapters (claude.py, cursor.py, codex.py, antigravity.py)
must satisfy this contract.  The module is pure stdlib + typing; no
third-party deps.

Fidelity tiers (D13, SPEC):
  native      — Full orchestration; all /z-* commands work natively.
  high        — Most commands work; minor degradation in a few areas.
  flattened   — Single-agent transliteration; multi-agent orchestration absent.
  partial     — Significant capability gaps; only core subset works.
  unsupported — Host detected but z-harness cannot run on it.

Command tiers (command-capability matrix):
  native      — Command works identically to the claude/native host.
  degraded    — Command runs but with reduced fidelity or missing features.
  blocked     — Command is not available on this host.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

FidelityTier = Literal["native", "high", "flattened", "partial", "unsupported"]
CommandTier = Literal["native", "degraded", "blocked"]

# ---------------------------------------------------------------------------
# ExportResult — re-exported from runtime (BLOCKER-1)
#
# The canonical ExportResult is owned by runtime/drivers/_export_utils.py so
# that runtime drivers never import up into z_harness_cli (one-way layering).
# z_harness_cli code and tests must import ExportResult from here, not from
# runtime.drivers._export_utils directly.
# ---------------------------------------------------------------------------

from runtime.drivers._export_utils import ExportResult  # noqa: E402  # re-export

__all__ = ["ExportResult"]  # expose as part of this module's public surface

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capabilities:
    """Static capability flags for a host adapter.

    Attributes:
        supports_project_mcp:  Host can register project-scoped MCP servers.
        supports_user_mcp:     Host can register user-scoped MCP servers.
        needs_trust_prompt:    Host presents an interactive trust/permission
                               prompt before running; inject must not assume
                               fully non-interactive startup.
        supports_cwd_override: Host respects a working-directory override
                               passed at launch time.
        cleanup_strategy:      How injected state is removed after a session.
                               ``"ephemeral"``  — gitignored config written for
                                                  the session and deleted on
                                                  cleanup.
                               ``"in_place"``   — config committed into the
                                                  project; cleanup is a no-op
                                                  (caller manages lifecycle).
                               ``"none"``       — no injection; nothing to clean.
    """

    supports_project_mcp: bool = False
    supports_user_mcp: bool = False
    needs_trust_prompt: bool = False
    supports_cwd_override: bool = False
    cleanup_strategy: Literal["ephemeral", "in_place", "none"] = "none"


@dataclass
class DetectResult:
    """Return value of HostAdapter.detect().

    Attributes:
        installed:  True if the host binary/runtime is reachable.
        version:    Version string reported by the host, or None if not
                    installed / version could not be determined.
        binary:     Resolved binary path (if installed), or None.
        notes:      Optional human-readable notes (e.g. auth warnings).
    """

    installed: bool
    version: str | None = None
    binary: str | None = None
    notes: str | None = None


@dataclass
class Injection:
    """Return value of HostAdapter.inject().

    Instances are context managers: the with-block wraps PTY launch so
    cleanup always runs on normal exit, SIGINT, SIGTERM, and crashes.

    Attributes:
        env:             Environment variables to merge into the child env.
        injected_files:  Paths written during injection (for restore/cleanup).
        mode:            Injection mode used.
        host:            Name of the adapter that created this injection.
        backup_manifest: Maps original file path → backup path for files that
                         were overwritten during injection.  Populated by T021
                         pre-flight; consumed by cleanup to restore originals.
        _cleanup_fn:     Internal callable invoked by cleanup().  Adapters
                         set this; callers do not call it directly.
    """

    env: dict[str, str]
    injected_files: list[Path] = field(default_factory=list)
    mode: Literal["ephemeral", "in_place"] = "ephemeral"
    host: str = ""
    # Populated by T021 pre-flight before overwriting any existing file;
    # consumed by cleanup to restore originals.  Maps original path → backup path.
    backup_manifest: dict[str, Path] | None = None
    # Internal — set by the adapter; not part of the public surface.
    _cleanup_fn: Any = field(default=None, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Context-manager protocol so `with adapter.inject(...) as inj:` works
    # ------------------------------------------------------------------

    def __enter__(self) -> "Injection":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        # Return False so exceptions propagate; cleanup always runs.
        self._run_cleanup()
        return False

    def _run_cleanup(self) -> None:
        """Execute the registered cleanup function (idempotent)."""
        if self._cleanup_fn is not None:
            fn = self._cleanup_fn
            self._cleanup_fn = None  # prevent double-run
            fn(self)


# ---------------------------------------------------------------------------
# HostAdapter Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class HostAdapter(Protocol):
    """Protocol that all concrete host adapters must satisfy.

    Adapters are instantiated once per process; state is per-instance.
    Pure detection/query methods (detect, capabilities, fidelity_tier,
    name) must be safe to call without side-effects.
    """

    # ------------------------------------------------------------------
    # Static identity (class or instance attributes)
    # ------------------------------------------------------------------

    #: Short machine-readable name, e.g. ``"claude"``, ``"cursor"``.
    name: str

    #: Declared fidelity relative to the native (Claude Code) baseline.
    fidelity_tier: FidelityTier

    #: Static capability flags for this host.
    capabilities: Capabilities

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def detect(self) -> DetectResult:
        """Probe the host's availability and version.

        Must be side-effect-free (read-only PATH/filesystem probe).
        """
        ...

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_payload(self, dest: Path) -> ExportResult:
        """Delegate to the host's export pipeline.

        Must write host-native config/prompt files to *dest* and return
        an ExportResult describing what was written.  Must never duplicate
        the upstream exporter logic — delegates to:
          1. ``runtime/drivers/<host>/export.py::export()`` for commands,
             agents, and skills.
          2. ``runtime/drivers/<host>/persona_export.py::export_persona()``
             for each persona in ``personas/``.
        Both results are merged into a single ExportResult.  Non-empty
        warnings from the runtime export must be surfaced as RuntimeError
        (legacy validation hard-gate).
        """
        ...

    # ------------------------------------------------------------------
    # Injection
    # ------------------------------------------------------------------

    def inject(
        self,
        state_env: dict[str, str],
        mode: Literal["ephemeral", "in_place"],
        project: Path,
    ) -> Injection:
        """Write host-native config to a gitignored path (ephemeral) or
        into the project (in_place).

        For ephemeral mode the written files MUST be gitignored and MUST
        be removed by cleanup().

        The returned Injection carries the env dict to merge into the
        child process and a cleanup handle.  Adapters that register MCP
        servers set Injection._cleanup_fn accordingly.

        inject() MUST also set the host-appropriate plugin-root env var
        (``CLAUDE_PLUGIN_ROOT`` / ``ANTIGRAVITY_PLUGIN_ROOT``) for
        ephemeral launches so the child process can resolve the runtime.
        """
        ...

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def launch(self, project: Path, env: dict[str, str]) -> int:
        """PTY-passthrough exec of the host's interactive command.

        Blocks until the host exits and returns its exit code.
        The caller is responsible for calling cleanup() afterwards
        (or using the Injection context manager).
        """
        ...

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self, injection: Injection) -> None:
        """Remove injected state produced by a prior inject() call.

        Must be idempotent — calling it twice must not raise.
        For ephemeral mode: remove all injected files and deregister any
        ephemeral resources.  Must NOT remove persistent/global resources
        such as global MCP entries in ``~/.codex/config.toml`` (those are
        managed separately via ``doctor --clear-mcp``).
        """
        ...


# ---------------------------------------------------------------------------
# Command-capability matrix
# ---------------------------------------------------------------------------
#
# A nested dict mapping host_name -> command_id -> CommandTier.
# Concrete adapters REGISTER their own entries by updating this dict after
# their module is imported (see each adapter's module-level _register() call).
#
# The matrix intentionally ships as a skeleton; T002 owns the structure +
# query API.  Adapters (T008–T011) fill their own tier declarations.
#
# Known /z-* command families (seed list; adapters extend as needed):
#   z-plan, z-implement, z-execute, z-review, z-test, z-audit,
#   z-export, z-update, z-doctor, z-status, z-brainstorm, z-consult,
#   z-panel, z-gate, z-maintain-docs

COMMAND_CAPABILITY_MATRIX: dict[str, dict[str, CommandTier]] = {
    # Populated by concrete adapters at import time.
    # Shape: { host_name: { command_id: tier } }
}

#: The canonical /z-* command families.  Adapters must declare a tier for
#: every entry in this list or raise at registration time.
KNOWN_COMMANDS: tuple[str, ...] = (
    "z-plan",
    "z-implement",
    "z-execute",
    "z-review",
    "z-test",
    "z-audit",
    "z-export",
    "z-update",
    "z-doctor",
    "z-status",
    "z-brainstorm",
    "z-consult",
    "z-panel",
    "z-gate",
    "z-maintain-docs",
)


def register_command_tiers(host: str, tiers: dict[str, CommandTier]) -> None:
    """Register (or replace) command-capability tiers for *host*.

    Called by each adapter module at import time::

        from z_harness_cli.adapters.base import register_command_tiers
        register_command_tiers("claude", {"z-plan": "native", ...})

    Raises ``ValueError`` if *tiers* omits any entry in KNOWN_COMMANDS.
    """
    missing = set(KNOWN_COMMANDS) - set(tiers)
    if missing:
        raise ValueError(
            f"Adapter '{host}' did not declare tiers for: {sorted(missing)}"
        )
    COMMAND_CAPABILITY_MATRIX[host] = dict(tiers)


def command_tier(host: str, command: str) -> CommandTier:
    """Look up the capability tier for (*host*, *command*).

    Returns ``"blocked"`` when either the host or the command is not
    registered (fail-safe: unknown = blocked, not assumed native).

    Args:
        host:    Host name, e.g. ``"claude"``, ``"cursor"``.
        command: Command id, e.g. ``"z-plan"``.

    Returns:
        ``"native"``, ``"degraded"``, or ``"blocked"``.
    """
    host_tiers = COMMAND_CAPABILITY_MATRIX.get(host)
    if host_tiers is None:
        return "blocked"
    return host_tiers.get(command, "blocked")
