"""commands/export.py — `z-harness export` command (Model A).

Spec reference: SPEC.md "Commands (behavior)", D13, D7/AMENDED, T014.

Behavior:
  * z-harness export [--host H | --all] [--in-place] [--out PATH] [--force]

  --host H      Export for a specific host only.
  --all         Export for all registered hosts.
  --in-place    Write into the project (committed layout); default writes under
                the resolved state root (plan-path.sh z_harness_base).
  --out PATH    Override the destination directory.  Path must resolve within
                the project repo root (git toplevel of cwd).  Paths that escape
                the repo root are rejected with exit 1.  A non-empty existing
                directory is rejected unless --force is also passed.
  --force       Allow overwriting a non-empty existing destination directory.

Per-host fidelity is printed after each export.

Output model:
  * Default: dest = resolved state root from env_bundle.resolve_plan_dir().
  * --in-place: dest = cwd (the user's project directory).
  * --out PATH: dest = PATH (with within-repo guard + non-empty dir guard).
"""

from __future__ import annotations
import importlib

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import typer
from z_harness_cli import release_surface

_EXPORT_ONLY_HOSTS = release_surface.runtime_driver_export_hosts()
_RUNTIME_DRIVER_HOSTS = _EXPORT_ONLY_HOSTS


def _remove_generated_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _cleanup_prod_surface(dest: Path) -> None:
    """Remove stale manifest-excluded files before writing a prod-surface export."""
    if release_surface.default_surface() != "prod":
        return

    skill_ids = set(release_surface.dev_only_skill_ids())
    for skills_dir in (
        dest / "skills",
        dest / ".cursor" / "skills",
        dest / ".agent" / "skills",
        dest / ".omp" / "z-harness" / "skills",
    ):
        if skills_dir.is_dir():
            for pattern in release_surface.dev_only_skill_patterns():
                skill_ids.update(path.name for path in skills_dir.glob(pattern))

    for skill_id in skill_ids:
        for relative in release_surface.cleanup_relative_paths_for_id("skills", skill_id):
            _remove_generated_path(dest / relative)

    for agent_id in release_surface.dev_only_agent_ids():
        for relative in release_surface.cleanup_relative_paths_for_id("agents", agent_id):
            _remove_generated_path(dest / relative)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    """Return the project repo root: git toplevel of cwd, falling back to cwd.

    This is the *user's project* repo root, not the z_harness_cli package
    installation directory.  Using the package location would cause the
    within-repo guard to validate against the wrong tree for installed CLIs.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip()).resolve()
    except subprocess.CalledProcessError:
        return Path.cwd().resolve()


def _resolve_default_dest(repo_root: Path) -> Path:
    """Resolve the default export destination via env_bundle.resolve_plan_dir().

    Raises SystemExit(1) if the script cannot be called — silent fallback
    violates the no-silent-degradation contract of the injected-env resolver.
    """
    from z_harness_cli import env_bundle

    try:
        plan_dir = env_bundle.resolve_plan_dir(repo_root)
        return Path(plan_dir)
    except RuntimeError as exc:
        typer.echo(
            f"Error: could not resolve state root via plan-path.sh: {exc}",
            err=True,
        )
        raise typer.Exit(code=1)


def _validate_out_path(out: str, repo_root: Path, force: bool) -> Path:
    """Validate and resolve the --out PATH value.

    Rules (spec T014 — within-repo guard):
    1. Resolve the path.
    2. If the resolved path is NOT within the repo root, reject with exit 1.
    3. If the resolved path is an existing non-empty directory and --force is
       not passed, exit 1.

    Returns the resolved Path.
    """
    dest = Path(out).resolve()

    # Within-repo guard: reject any path that escapes the project repo root.
    try:
        dest.relative_to(repo_root)
    except ValueError:
        typer.echo(
            f"Error: --out path {out!r} escapes the repo root ({repo_root}).\n"
            "The destination must be within the project repository.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Check non-empty-dir guard. With --force, allow the export to proceed
    # without deleting the caller-chosen root. Exporters may overwrite their
    # own files, but the CLI must not remove sibling exports or the repo root.
    if dest.is_dir() and any(dest.iterdir()) and not force:
        typer.echo(
            f"Error: destination directory {dest} already exists and is non-empty.\n"
            "Pass --force to overwrite.",
            err=True,
        )
        raise typer.Exit(code=1)
    return dest


def _export_for_host(
    adapter,
    dest: Path,
    namespace_by_host: bool,
) -> None:
    """Call adapter.export_payload(dest) and print per-host fidelity.

    Args:
        adapter: The host adapter.
        dest: The base destination directory.
        namespace_by_host: When True, write to dest/<host_name>/ (used when
            exporting multiple hosts to a shared root so they don't collide).
            When False, write directly to dest.
    """
    host_dest = dest / adapter.name if namespace_by_host else dest
    host_dest.mkdir(parents=True, exist_ok=True)
    _cleanup_prod_surface(host_dest)

    result = adapter.export_payload(host_dest)

    # Print fidelity summary.
    typer.echo(
        f"[{adapter.name}] fidelity={result.fidelity}  "
        f"files={len(result.files)}  dest={host_dest}"
    )

    if result.warnings:
        for warn in result.warnings:
            typer.echo(f"  warning: {warn}", err=True)
        raise typer.Exit(code=1)

    if result.files:
        for f in result.files:
            typer.echo(f"  wrote: {f}")



def _export_runtime_driver(host_name: str, repo_root: Path, dest: Path) -> None:
    """Export a runtime driver target that has no interactive host adapter."""
    if host_name == "antigravity":
        module_name = "runtime.drivers.antigravity.export"
    else:
        module_name = f"runtime.drivers.{host_name}.export"

    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        typer.echo(f"Error: cannot import exporter for host {host_name!r}: {exc}", err=True)
        raise typer.Exit(code=1)

    _cleanup_prod_surface(dest)
    result = mod.export(repo_root, dest)
    typer.echo(
        f"[{host_name}] fidelity={result.fidelity}  "
        f"files={len(result.files)}  dest={dest}"
    )
    if result.warnings:
        for warn in result.warnings:
            typer.echo(f"  warning: {warn}", err=True)
        raise typer.Exit(code=1)
    for f in result.files:
        typer.echo(f"  wrote: {f}")

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    ctx: "typer.Context",
    *,
    host: Optional[str],
    all_hosts: bool,
    in_place: bool,
    out: Optional[str],
    force: bool,
    surface: Optional[str] = None,
) -> None:
    """Entry point called from __main__.export_cmd."""
    from z_harness_cli.adapters.registry import (
        select,
        detect_all,
        UnknownHostError,
        NoHostInstalledError,
    )

    repo_root = _repo_root()
    try:
        resolved_surface = release_surface.default_surface(surface)
    except ValueError:
        typer.echo("Error: --surface must be one of: dev, prod", err=True)
        raise typer.Exit(code=2)

    previous_surface = os.environ.get("Z_HARNESS_RELEASE_SURFACE")

    # -----------------------------------------------------------------------
    # Validate mutual exclusions before any I/O (fail fast).
    # -----------------------------------------------------------------------
    if out is not None and in_place:
        typer.echo(
            "Error: --out and --in-place are mutually exclusive.",
            err=True,
        )
        raise typer.Exit(code=1)

    if host is not None and all_hosts:
        typer.echo(
            "Error: --host and --all are mutually exclusive.",
            err=True,
        )
        raise typer.Exit(code=1)

    # -----------------------------------------------------------------------
    # Determine destination directory.
    # -----------------------------------------------------------------------
    if out is not None:
        dest = _validate_out_path(out, repo_root, force)
    elif in_place:
        dest = Path.cwd().resolve()
    else:
        dest = _resolve_default_dest(repo_root)

    # -----------------------------------------------------------------------
    # Determine which adapters to export.
    # -----------------------------------------------------------------------

    runtime_hosts: list[str] = []
    if all_hosts:
        default_hosts = set(release_surface.public_release_hosts()) if resolved_surface == "prod" else None
        adapters = [
            adapter
            for adapter, result in detect_all()
            if result.installed and (default_hosts is None or adapter.name in default_hosts)
        ]
        runtime_hosts = []
        if not adapters:
            if default_hosts is None:
                typer.echo("Error: no installed hosts found.", err=True)
            else:
                typer.echo(
                    "Error: no installed release-supported hosts found (Claude or OMP). "
                    "Use --host with an explicit dev/advanced target if needed.",
                    err=True,
                )
            raise typer.Exit(code=1)
        # Multiple hosts sharing one destination root — namespace per host to
        # prevent collisions.
        namespace_by_host = True
    elif host is not None:
        if host in _RUNTIME_DRIVER_HOSTS:
            runtime_hosts = [host]
            adapters = []
        else:
            try:
                adapter, _result = select(host=host, interactive=False)
            except UnknownHostError as exc:
                typer.echo(
                    f"Error: {exc} Runtime export targets also supported: {sorted(_RUNTIME_DRIVER_HOSTS)}.",
                    err=True,
                )
                raise typer.Exit(code=1)
            adapters = [adapter]
            runtime_hosts = []
        if resolved_surface == "prod" and host not in release_surface.public_release_hosts():
            typer.echo(
                f"warning: {host} is an explicit dev/advanced or export-only target; "
                "prod defaults are Claude and OMP.",
                err=True,
            )
        # Single explicit host — write directly to dest, no sub-directory.
        namespace_by_host = False
    else:
        # Default: auto-select best installed host (or first if multiple).
        try:
            adapter, _result = select(host=None, interactive=False)
        except NoHostInstalledError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1)
        adapters = [adapter]
        # Single auto-selected host — write directly to dest, no sub-directory.
        namespace_by_host = False

    # -----------------------------------------------------------------------
    # Run exports.
    # -----------------------------------------------------------------------
    dest.mkdir(parents=True, exist_ok=True)
    os.environ["Z_HARNESS_RELEASE_SURFACE"] = resolved_surface

    try:
        for adapter in adapters:
            _export_for_host(adapter, dest, namespace_by_host)
        for host_name in runtime_hosts:
            host_dest = dest / host_name if namespace_by_host else dest
            host_dest.mkdir(parents=True, exist_ok=True)
            _export_runtime_driver(host_name, repo_root, host_dest)
    finally:
        if previous_surface is None:
            os.environ.pop("Z_HARNESS_RELEASE_SURFACE", None)
        else:
            os.environ["Z_HARNESS_RELEASE_SURFACE"] = previous_surface
