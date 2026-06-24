"""commands/doctor.py — `z-harness doctor` / `z-harness status` command.

Spec reference: SPEC.md "Commands (behavior)" + MINOR doctor ACs + F4 + D13.

Behavior:
  - Rich table: per-host installed/version/reachable/fidelity/capabilities.
  - Command-capability matrix: shows native/degraded/blocked tier per command.
  - Resolved telemetry (Z_HARNESS_PLAN_DIR) + config paths.
  - Orphaned-injection detection + clean offer (uses inject_safety.detect_orphans).
  - Update notice (reuses release.py + update.py version-compare logic; no auto-update).
  - ``--clear-mcp``: de-registers z-harness MCP entries from GLOBAL host config
    (e.g. ~/.codex/config.toml) with confirmation prompt (F4).
  - Host-detection precedence: CLAUDECODE → agy → cursor → codex → omp → error.
  - Exit code: 0 healthy; 1 if any installed host is unreachable.

Read-only except for --clear-mcp and the orphan-clean prompt.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Lazy top-level imports that are stable at module scope (patchable in tests).
# Heavy libraries (Rich, adapters) are still imported inside functions to keep
# cold-start cost low, but the adapter registry is small and always needed.
# ---------------------------------------------------------------------------

# Import detect_all at module scope so tests can patch
# ``z_harness_cli.commands.doctor.detect_all`` directly.
from z_harness_cli.adapters.registry import detect_all  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The MCP server name z-harness registers with Codex.
_ZH_MCP_SERVER_NAME = "z-harness"

#: Host-detection precedence order (CLAUDECODE → agy → cursor → codex → omp).
_HOST_PRECEDENCE = ("claude", "antigravity", "cursor", "codex", "omp")

# Fidelity tier display style (Rich markup color).
_FIDELITY_STYLE = {
    "native":      "bold green",
    "high":        "green",
    "flattened":   "yellow",
    "partial":     "bold yellow",
    "unsupported": "red",
}

# Command tier display characters.
_TIER_CHAR = {
    "native":   "[green]N[/green]",
    "degraded": "[yellow]D[/yellow]",
    "blocked":  "[red]B[/red]",
}


# ---------------------------------------------------------------------------
# MCP de-registration (--clear-mcp)
# ---------------------------------------------------------------------------


def _codex_config_toml_path() -> Path:
    """Return the canonical ~/.codex/config.toml path."""
    return Path.home() / ".codex" / "config.toml"


def _has_zh_mcp_entry(config_toml: Path) -> bool:
    """Return True if ~/.codex/config.toml contains [mcp_servers.z-harness]."""
    if not config_toml.exists():
        return False
    try:
        with config_toml.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError:
        return False
    return _ZH_MCP_SERVER_NAME in data.get("mcp_servers", {})


def _remove_zh_mcp_entry(config_toml: Path) -> bool:
    """Remove the [mcp_servers.z-harness] section from config_toml in place.

    Uses line-based removal so we don't require a TOML *write* library
    (only ``tomllib`` for reading/validation is in stdlib Python 3.11+).

    Returns True if an entry was found and removed, False if nothing was present.
    Raises RuntimeError on write failure.
    """
    if not config_toml.exists():
        return False

    try:
        raw = config_toml.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Could not read {config_toml}: {exc}") from exc

    # Parse first to confirm the key actually exists (authoritative).
    try:
        with config_toml.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Could not parse {config_toml}: {exc}") from exc

    if _ZH_MCP_SERVER_NAME not in data.get("mcp_servers", {}):
        return False

    # Remove the [mcp_servers.z-harness] section using line-based filtering.
    # TOML section headers look like: [mcp_servers.z-harness]  or
    # [mcp_servers."z-harness"] — match both.
    # We remove the section header line AND all lines up to (not including)
    # the next section header or end-of-file.
    new_lines: list[str] = []
    in_zh_section = False
    section_target_variants = (
        f"[mcp_servers.{_ZH_MCP_SERVER_NAME}]",
        f'[mcp_servers."{_ZH_MCP_SERVER_NAME}"]',
    )
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped in section_target_variants:
            in_zh_section = True
            continue  # drop this header line
        if in_zh_section:
            # A new section header terminates the removed section.
            if stripped.startswith("[") and not stripped.startswith("[["):
                in_zh_section = False
                new_lines.append(line)
            elif stripped.startswith("[["):
                in_zh_section = False
                new_lines.append(line)
            else:
                continue  # drop keys/values belonging to [mcp_servers.z-harness]
        else:
            new_lines.append(line)

    new_content = "".join(new_lines)

    # Post-write re-validation: parse the new content BEFORE replacing the
    # original file.  If the line-based removal produced invalid TOML (e.g. a
    # mid-section comment or inline table with a dangling comma), we abort and
    # leave the original file intact rather than clobber a global shared config
    # with a corrupt result.
    try:
        tomllib.loads(new_content)
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(
            f"Post-edit TOML re-validation failed for {config_toml}; "
            f"aborting write to preserve the original file intact. "
            f"Parser error: {exc}"
        ) from exc

    # Atomic write: write to a temp file alongside the original, then rename.
    tmp_path = config_toml.with_suffix(config_toml.suffix + ".zh-tmp")
    try:
        tmp_path.write_text(new_content, encoding="utf-8")
        os.replace(tmp_path, config_toml)
    except OSError as exc:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise RuntimeError(f"Could not write {config_toml}: {exc}") from exc

    return True


def _clear_mcp(*, _config_toml: Path | None = None) -> None:
    """Interactive --clear-mcp flow: confirm then remove z-harness MCP entries.

    Args:
        _config_toml: Override the config path (for testing).
    """
    config_toml = _config_toml or _codex_config_toml_path()

    if not config_toml.exists():
        typer.echo("No ~/.codex/config.toml found — nothing to clear.")
        return

    if not _has_zh_mcp_entry(config_toml):
        typer.echo(
            f"No z-harness MCP entry found in {config_toml}. Nothing to remove."
        )
        return

    typer.echo(
        f"Found [mcp_servers.{_ZH_MCP_SERVER_NAME}] entry in {config_toml}.\n"
        "This entry was written globally by `z-harness launch` and is shared\n"
        "across ALL your Codex projects in this config file."
    )
    confirmed = typer.confirm(
        "Remove the z-harness MCP entry from the global Codex config?",
        default=False,
    )
    if not confirmed:
        typer.echo("Aborted — no changes made.")
        raise typer.Exit(code=0)

    try:
        removed = _remove_zh_mcp_entry(config_toml)
    except RuntimeError as exc:
        typer.echo(f"Error removing MCP entry: {exc}", err=True)
        raise typer.Exit(code=1)

    if removed:
        typer.echo(
            f"Removed [mcp_servers.{_ZH_MCP_SERVER_NAME}] from {config_toml}."
        )
    else:
        typer.echo("No entry found to remove (already absent).")


# ---------------------------------------------------------------------------
# Telemetry + config path resolution (best-effort; doctor is read-only)
# ---------------------------------------------------------------------------


def _resolve_paths_display(cwd: str) -> tuple[str, str]:
    """Return (plan_dir, config_path) strings for display.

    Both are best-effort: if the underlying scripts fail (e.g. not in a git
    repo), returns a human-friendly error string rather than crashing.

    Returns:
        (plan_dir_display, config_path_display)
    """
    from z_harness_cli.env_bundle import resolve_plan_dir, resolve_config_env

    # Plan dir
    try:
        plan_dir = resolve_plan_dir(cwd)
    except RuntimeError as exc:
        plan_dir = f"(unavailable: {exc})"

    # Config path: config.py export-env gives us the env vars; the config file
    # itself is the layered TOML.  We show the git-root .z-harness/config.toml
    # when it exists, else the global XDG path.
    config_path = _resolve_config_path(cwd)

    return plan_dir, config_path


def _resolve_config_path(cwd: str) -> str:
    """Best-effort: return the most specific config file path that exists."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            repo_cfg = Path(result.stdout.strip()) / ".z-harness" / "config.toml"
            if repo_cfg.exists():
                return str(repo_cfg)
    except FileNotFoundError:
        pass

    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    global_cfg = Path(xdg) / "z-harness" / "config.toml"
    if global_cfg.exists():
        return str(global_cfg)

    return str(global_cfg) + " (not yet created)"


# ---------------------------------------------------------------------------
# Update notice (read-only; no auto-update)
# ---------------------------------------------------------------------------


def _update_notice() -> str | None:
    """Return a one-line update notice string, or None if up to date / unreachable."""
    try:
        from z_harness_cli import __version__
        from z_harness_cli.release import (
            FetchError,
            ManifestParseError,
            ManifestSchemaError,
            VersionComparisonResult,
            compare_versions,
            fetch_manifest,
        )
        manifest = fetch_manifest()
        result = compare_versions(__version__, manifest)
        if result == VersionComparisonResult.STALE:
            return (
                f"Update available: {manifest.version} "
                f"(installed: {__version__}). Run `z-harness update`."
            )
    except (ManifestSchemaError, FetchError, ManifestParseError, OSError):
        pass
    return None


# ---------------------------------------------------------------------------
# Reachability probe
# ---------------------------------------------------------------------------


def _probe_reachable(binary: str | None) -> bool:
    """Return True if the binary can be exec'd without error.

    Uses the same ``--version`` probe as detect() (side-effect-free).
    The binary argument comes from DetectResult.binary (already resolved).
    """
    if not binary:
        return False
    import subprocess
    try:
        r = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ---------------------------------------------------------------------------
# Orphan detection + clean
# ---------------------------------------------------------------------------


def _handle_orphans(cwd: str) -> None:
    """Detect orphaned injections and offer to clean them up.

    Prints a warning and prompts the user if orphans are found.  Passes
    silently if no manifest exists or all injections were cleaned up.
    """
    from z_harness_cli import inject_safety

    try:
        orphans = inject_safety.detect_orphans(Path(cwd))
    except (RuntimeError, OSError):
        # RuntimeError: not in a git repo or git absent.
        # OSError: manifest unreadable.
        # In both cases doctor proceeds without orphan info.
        return

    if not orphans:
        return

    typer.echo(
        f"\n[WARNING] Found {len(orphans)} orphaned injection file(s) from a "
        "previous `z-harness launch` that was not cleaned up:"
    )
    for p in orphans:
        typer.echo(f"  {p}")

    confirmed = typer.confirm(
        "Clean up orphaned injection files now?",
        default=True,
    )
    if confirmed:
        try:
            inject_safety.cleanup(Path(cwd))
            typer.echo("Orphaned injection files cleaned up.")
        except inject_safety.RestoreError as exc:
            typer.echo(f"[ERROR] Restore failed: {exc}", err=True)
        except (RuntimeError, OSError) as exc:
            # RuntimeError: git/path resolution failures.
            # OSError: file I/O failures during cleanup.
            typer.echo(f"[ERROR] Cleanup error: {exc}", err=True)


# ---------------------------------------------------------------------------
# Rich host table + command matrix
# ---------------------------------------------------------------------------


def _render_host_table(
    all_results: list,
    console: "rich.console.Console",  # type: ignore[name-defined]
) -> bool:
    """Render the per-host status table.  Returns True if any host is unreachable."""
    from rich.table import Table

    table = Table(
        title="z-harness host status",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Host", style="bold")
    table.add_column("Installed")
    table.add_column("Version")
    table.add_column("Reachable")
    table.add_column("Fidelity")
    table.add_column("MCP")
    table.add_column("Trust prompt")
    table.add_column("CWD override")
    table.add_column("Cleanup")

    any_unreachable = False

    for adapter, result in all_results:
        installed_str = "[green]yes[/green]" if result.installed else "[dim]no[/dim]"
        version_str = result.version or "[dim]-[/dim]"
        binary = result.binary

        if result.installed:
            reachable = _probe_reachable(binary)
            if reachable:
                reach_str = "[green]yes[/green]"
            else:
                reach_str = "[red]no[/red]"
                any_unreachable = True
        else:
            reach_str = "[dim]-[/dim]"

        fid = adapter.fidelity_tier
        fid_style = _FIDELITY_STYLE.get(fid, "")
        fid_str = f"[{fid_style}]{fid}[/{fid_style}]" if fid_style else fid

        caps = adapter.capabilities
        mcp_parts = []
        if caps.supports_project_mcp:
            mcp_parts.append("project")
        if caps.supports_user_mcp:
            mcp_parts.append("user")
        mcp_str = "/".join(mcp_parts) if mcp_parts else "[dim]none[/dim]"

        trust_str = "[yellow]yes[/yellow]" if caps.needs_trust_prompt else "no"
        cwd_str = "[green]yes[/green]" if caps.supports_cwd_override else "no"
        cleanup_str = caps.cleanup_strategy

        table.add_row(
            adapter.name,
            installed_str,
            version_str,
            reach_str,
            fid_str,
            mcp_str,
            trust_str,
            cwd_str,
            cleanup_str,
        )

    console.print(table)
    return any_unreachable


def _render_command_matrix(
    all_results: list,
    console: "rich.console.Console",  # type: ignore[name-defined]
) -> None:
    """Render the command-capability matrix for all hosts."""
    from rich.table import Table
    from z_harness_cli.adapters.base import KNOWN_COMMANDS, command_tier

    table = Table(
        title="Command-capability matrix  [green]N[/green]=native  [yellow]D[/yellow]=degraded  [red]B[/red]=blocked",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Command", style="bold", min_width=20)
    for adapter, _ in all_results:
        table.add_column(adapter.name, justify="center")

    for cmd in KNOWN_COMMANDS:
        row = [cmd]
        for adapter, _ in all_results:
            tier = command_tier(adapter.name, cmd)
            row.append(_TIER_CHAR.get(tier, tier))
        table.add_row(*row)

    console.print(table)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(ctx: "typer.Context", *, clear_mcp: bool = False) -> None:  # noqa: F821
    """Entry point called from __main__.doctor_cmd.

    Args:
        ctx: Typer context (not used currently; present for forward-compat).
        clear_mcp: When True, run the --clear-mcp flow instead of the
                   normal doctor output.
    """
    if clear_mcp:
        _clear_mcp()
        return

    from rich.console import Console

    console = Console()

    # --- Detect all hosts ---------------------------------------------------
    all_results = detect_all()

    # --- Per-host table + command matrix ------------------------------------
    any_unreachable = _render_host_table(all_results, console)
    console.print()
    _render_command_matrix(all_results, console)

    # --- Telemetry + config paths -------------------------------------------
    cwd = os.getcwd()
    plan_dir, config_path = _resolve_paths_display(cwd)
    console.print()
    console.print(f"[bold]Telemetry path:[/bold]  {plan_dir}")
    console.print(f"[bold]Config path:  [/bold]  {config_path}")

    # --- Host-detection precedence note -------------------------------------
    console.print()
    precedence = " → ".join(
        "CLAUDECODE" if host == "claude" else ("agy" if host == "antigravity" else host)
        for host in _HOST_PRECEDENCE
    )
    console.print(f"[dim]Host-detection precedence: {precedence} → error[/dim]")

    # --- Orphan detection + clean -------------------------------------------
    _handle_orphans(cwd)

    # --- Update notice (read-only) ------------------------------------------
    notice = _update_notice()
    if notice:
        console.print()
        console.print(f"[bold yellow]Update:[/bold yellow] {notice}")

    # --- Exit code: 1 if any installed host is unreachable ------------------
    if any_unreachable:
        raise typer.Exit(code=1)
