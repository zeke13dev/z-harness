"""Entry point for `python -m z_harness_cli`, `z-harness`, and `zh` shims."""

from __future__ import annotations

from typing import Optional

import typer

app = typer.Typer(
    name="z-harness",
    help="z-harness packaging CLI — install, export, launch, doctor, and update.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        from z_harness_cli import __version__

        typer.echo(f"z-harness {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-V",
        help="Print version and exit.",
        callback=_version_callback,
        is_eager=True,
        is_flag=True,
    ),
) -> None:
    """z-harness packaging CLI."""
    # When invoked as `z-harness --help` (no sub-command), Typer shows help
    # automatically because no_args_is_help=True.
    if ctx.invoked_subcommand is None and not version:
        typer.echo(ctx.get_help())
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Lazy-registered sub-commands
# Each stub is a Typer sub-app or a plain command that imports the real module
# only when the command is actually invoked. This keeps cold-start low even
# before the command modules are written (they do not exist yet in T001).
# ---------------------------------------------------------------------------

@app.command("install")
def install_cmd(
    ctx: typer.Context,
) -> None:
    """Bootstrap / install z-harness (wraps install.sh)."""
    try:
        from z_harness_cli.commands import install as _install_mod  # type: ignore[import]

        _install_mod.run(ctx)
    except ImportError:
        typer.echo("'install' command not yet implemented.", err=True)
        raise typer.Exit(code=1)


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Target host."),
    all_hosts: bool = typer.Option(False, "--all", help="Export to all hosts."),
    in_place: bool = typer.Option(False, "--in-place", help="Write into project (committed)."),
) -> None:
    """Export z-harness commands/agents/skills to a host (Model A)."""
    try:
        from z_harness_cli.commands import export as _export_mod  # type: ignore[import]

        _export_mod.run(ctx, host=host, all_hosts=all_hosts, in_place=in_place)
    except ImportError:
        typer.echo("'export' command not yet implemented.", err=True)
        raise typer.Exit(code=1)


@app.command("launch")
def launch_cmd(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Host to launch."),
    project: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)."),
) -> None:
    """Inject + PTY-launch a host in the target project (Model B)."""
    try:
        from z_harness_cli.commands import launch as _launch_mod  # type: ignore[import]

        _launch_mod.run(ctx, host=host, project=project)
    except ImportError:
        typer.echo("'launch' command not yet implemented.", err=True)
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_cmd(
    ctx: typer.Context,
) -> None:
    """Show host capabilities, fidelity tiers, and telemetry path."""
    try:
        from z_harness_cli.commands import doctor as _doctor_mod  # type: ignore[import]

        _doctor_mod.run(ctx)
    except ImportError:
        typer.echo("'doctor' command not yet implemented.", err=True)
        raise typer.Exit(code=1)


# Alias: `z-harness status` mirrors `z-harness doctor`.
@app.command("status", hidden=True)
def status_cmd(ctx: typer.Context) -> None:
    """Alias for 'doctor'."""
    doctor_cmd(ctx)


@app.command("update")
def update_cmd(
    ctx: typer.Context,
) -> None:
    """Check for updates and apply them."""
    try:
        from z_harness_cli.commands import update as _update_mod  # type: ignore[import]

        _update_mod.run(ctx)
    except ImportError:
        typer.echo("'update' command not yet implemented.", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
