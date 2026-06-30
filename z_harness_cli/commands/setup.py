"""Interactive-ish first-run setup for z-harness.

This is the small public CLI surface: detect the user's existing harnesses,
show provider/auth status, optionally install supported plugin targets, and
then hand off to the in-harness `/z-setup` wizard for deeper configuration.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import typer
from z_harness_cli import release_surface

_SUPPORTED_TARGETS = release_surface.explicit_setup_target_ids()
_PROVIDER_BINS = (
    ("claude", "Claude Code / Anthropic"),
    ("codex", "Codex / OpenAI"),
    ("gemini", "Gemini"),
    ("ollama", "Ollama local models"),
    ("agy", "Antigravity"),
)


@dataclass(frozen=True)
class HostSummary:
    name: str
    installed: bool
    version: str | None
    fidelity: str
    note: str


def _harness_root() -> Path:
    return Path(__file__).parent.parent.parent.resolve()


def _normalize_targets(target: str, *, surface: str | None = None) -> list[str]:
    if target == "all":
        return list(release_surface.setup_target_ids(surface))
    requested = [part.strip() for part in target.split(",") if part.strip()]
    invalid = [part for part in requested if part not in _SUPPORTED_TARGETS]
    if invalid:
        valid = ", ".join((*_SUPPORTED_TARGETS, "all"))
        typer.echo(f"Error: unknown setup target(s): {', '.join(invalid)}. Valid: {valid}", err=True)
        raise typer.Exit(code=2)
    return requested or list(release_surface.setup_target_ids(surface))


def _detect_hosts(selected: set[str], *, surface: str | None = None) -> list[HostSummary]:
    from z_harness_cli.adapters.registry import detect_all

    public_hosts = set(release_surface.public_release_hosts())
    prod_surface = release_surface.default_surface(surface) == "prod"
    summaries: list[HostSummary] = []
    for adapter, result in detect_all():
        if adapter.name not in _SUPPORTED_TARGETS:
            continue
        if prod_surface and adapter.name not in public_hosts and adapter.name not in selected:
            continue
        note = result.notes or ""
        if prod_surface and adapter.name not in public_hosts:
            note = f"{note}; dev/advanced explicit target".strip("; ")
        summaries.append(
            HostSummary(
                name=adapter.name,
                installed=result.installed,
                version=result.version,
                fidelity=adapter.fidelity_tier,
                note=note,
            )
        )
    if not prod_surface or "pi" in selected:
        summaries.append(
            HostSummary(
                name="pi",
                installed=True,
                version=None,
                fidelity="export-only",
                note="dev/advanced compatibility export target; no local binary probe"
                if prod_surface
                else "compatibility export target; no local binary probe",
            )
        )
    return summaries


def _provider_rows() -> list[tuple[str, str, bool, str | None]]:
    rows: list[tuple[str, str, bool, str | None]] = []
    for binary, label in _PROVIDER_BINS:
        path = shutil.which(binary)
        rows.append((binary, label, path is not None, path))
    return rows


def _echo_section(title: str) -> None:
    typer.echo(f"\n== {title} ==")


def _print_host_summary(hosts: Iterable[HostSummary], selected: set[str]) -> None:
    _echo_section("Harnesses")
    for host in hosts:
        marker = "*" if host.name in selected else " "
        status = "found" if host.installed else "missing"
        version = f" ({host.version})" if host.version else ""
        note = f" — {host.note}" if host.note else ""
        typer.echo(f"{marker} {host.name:<7} {status:<7} fidelity={host.fidelity}{version}{note}")


def _print_provider_summary() -> None:
    _echo_section("Provider/auth CLIs")
    for binary, label, installed, path in _provider_rows():
        status = "found" if installed else "missing"
        suffix = f" at {path}" if path else ""
        typer.echo(f"- {binary:<7} {status:<7} {label}{suffix}")


def _run_plugin_install(target: str, *, force: bool) -> None:
    from z_harness_cli.commands import install as install_cmd

    install_cmd.run(
        typer.Context(typer.Typer()),
        target=target,
        tarball=None,
        force=force,
        generate_exports=False,
    )


def _run_setup_py(args: list[str]) -> int:
    setup_py = _harness_root() / "scripts" / "setup.py"
    if not setup_py.is_file():
        typer.echo("setup.py is not available in this z-harness installation.", err=True)
        return 1
    return subprocess.run([sys.executable, str(setup_py), *args], check=False).returncode


def _next_steps(targets: list[str]) -> None:
    _echo_section("Next steps")
    if "claude" in targets:
        typer.echo("- Claude: restart/open Claude Code, then run `/z-setup status` or `/z-plan <task>`.")
    if "omp" in targets:
        typer.echo("- OMP: export or inject the OMP package, then launch OMP with `OMP_PLUGIN_ROOT` set.")
    if "pi" in targets:
        typer.echo("- pi (dev/advanced export-only): generate the compatibility export and copy it into the pi/Oh My Pi project as documented.")
    if "cursor" in targets:
        typer.echo("- Cursor (dev/advanced export-only): export `.cursor/skills`/rules into a project, then open Cursor Agent there.")
    if "codex" in targets:
        typer.echo("- Codex (dev/source plugin): restart Codex after plugin install; MCP registration is global and removable with `doctor --clear-mcp`.")
    typer.echo("- Deep config remains in-harness: run `/z-setup wizard` from your chosen harness.")


def run(
    *,
    target: str,
    install: bool,
    force: bool,
    posture: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Run first-time setup/onboarding."""
    surface = release_surface.default_surface()
    targets = _normalize_targets(target, surface=surface)
    selected = set(targets)

    typer.echo("z-harness setup — release defaults: Claude Code plugin + OMP package/export")
    _print_host_summary(_detect_hosts(selected, surface=surface), selected)

    _echo_section("Plan")
    typer.echo(f"selected harnesses: {', '.join(targets)}")
    if posture:
        typer.echo(f"posture preset: {posture}")
    else:
        typer.echo("posture preset: unchanged (use --posture interactive|ci-batch|overnight)")

    plugin_install_targets = release_surface.plugin_install_target_ids(surface)
    installable = [name for name in targets if name in plugin_install_targets]
    export_only = [name for name in targets if name not in plugin_install_targets]
    if installable:
        typer.echo(f"plugin install targets: {', '.join(installable)}")
    if export_only:
        typer.echo(f"package/export or dev/advanced targets: {', '.join(export_only)}")

    if dry_run:
        typer.echo("dry run: no changes made")
        _next_steps(targets)
        return

    if posture:
        args = ["apply", "--posture", posture]
        if yes:
            args.append("--yes")
        rc = _run_setup_py(args)
        if rc:
            raise typer.Exit(code=rc)

    if install and installable:
        install_target = "all" if set(installable) == plugin_install_targets else installable[0]
        if len(installable) == 1:
            install_target = installable[0]
        typer.echo(f"\nInstalling plugin target: {install_target}")
        _run_plugin_install(install_target, force=force)
    elif install and not installable:
        typer.echo("No selected harness has a direct plugin installer in this surface; use export/inject next steps.")
    else:
        typer.echo("\nNo plugin install run. Pass --install to install direct plugin targets for this surface.")

    _next_steps(targets)
