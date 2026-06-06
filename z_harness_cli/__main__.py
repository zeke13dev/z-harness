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
    in_place: bool = typer.Option(
        False, "--in-place", help="Write into project (committed)."
    ),
    out: Optional[str] = typer.Option(
        None,
        "--out",
        help=(
            "Override destination directory.  Must resolve within the project repo root "
            "(git toplevel of cwd); paths that escape the repo are rejected.  "
            "Non-empty dirs are rejected unless --force is also passed."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow overwriting a non-empty existing --out directory.",
    ),
) -> None:
    """Export z-harness commands/agents/skills to a host (Model A)."""
    try:
        from z_harness_cli.commands import export as _export_mod  # type: ignore[import]
    except ImportError:
        typer.echo("'export' command not yet implemented.", err=True)
        raise typer.Exit(code=1)

    _export_mod.run(
        ctx,
        host=host,
        all_hosts=all_hosts,
        in_place=in_place,
        out=out,
        force=force,
    )


@app.command("launch")
def launch_cmd(
    ctx: typer.Context,
    host: Optional[str] = typer.Option(None, "--host", "-H", help="Host to launch."),
    quiet: bool = typer.Option(
        False, "--quiet", help="Suppress the fidelity banner before handover."
    ),
    project: Optional[str] = typer.Argument(None, help="Project directory (default: cwd)."),
) -> None:
    """Inject + PTY-launch a host in the target project (Model B)."""
    try:
        from z_harness_cli.commands import launch as _launch_mod  # type: ignore[import]
    except ImportError:
        typer.echo("'launch' command not yet implemented.", err=True)
        raise typer.Exit(code=1)

    # NOTE: run() is intentionally OUTSIDE the except so a typer.Exit (or any
    # error) it raises is NOT swallowed by the import fallback.  Narrowing the
    # except to wrap only the import avoids the broad-except blocker T014 hit.
    #
    # run() returns the host's exit code; a nonzero host exit MUST propagate as
    # the CLI's exit code (else `z-harness launch` would report success for a
    # host that crashed).  Zero stays an implicit clean exit.
    rc = _launch_mod.run(ctx, host=host, project=project, quiet=quiet)
    if rc:
        raise typer.Exit(code=rc)


@app.command("doctor")
def doctor_cmd(
    ctx: typer.Context,
    clear_mcp: bool = typer.Option(
        False,
        "--clear-mcp",
        help=(
            "De-register z-harness MCP entries from the global host config "
            "(e.g. ~/.codex/config.toml). Prompts for confirmation. "
            "Per SPEC F4: MCP entries are global/persistent; this is the "
            "only explicit removal path."
        ),
    ),
) -> None:
    """Show host capabilities, fidelity tiers, and telemetry path."""
    try:
        from z_harness_cli.commands import doctor as _doctor_mod  # type: ignore[import]
    except ImportError:
        typer.echo("'doctor' command not yet implemented.", err=True)
        raise typer.Exit(code=1)

    # NOTE: run() is intentionally OUTSIDE the except so a typer.Exit (or any
    # error) it raises is NOT swallowed by the import fallback.  Narrowing the
    # except to wrap only the import avoids the broad-except blocker (T014/T015
    # pattern).
    _doctor_mod.run(ctx, clear_mcp=clear_mcp)


# Alias: `z-harness status` mirrors `z-harness doctor`.
@app.command("status", hidden=True)
def status_cmd(ctx: typer.Context) -> None:
    """Alias for 'doctor'."""
    doctor_cmd(ctx, clear_mcp=False)


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
