"""commands/install.py — `z-harness install` plugin installer wrapper.

The Python CLI is the first-run entrypoint installed by the curl/uv flow.  The
actual plugin installation logic remains in install.sh so source clone, tarball,
and packaged-wheel paths share one implementation. Public prod installs support
the direct Claude Code and Codex plugin paths.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from z_harness_cli.release import (
    FetchError,
    ManifestParseError,
    ManifestSchemaError,
    fetch_manifest,
    require_plugin_tarball_metadata,
)
import typer


def _harness_root() -> Path:
    """Return the installed harness payload root.

    Wheels force-include install.sh, skills/, agents/, runtime/, and scripts/ as
    siblings of z_harness_cli in site-packages. Source checkouts have the same
    shape at the repo root.
    """
    return Path(__file__).parent.parent.parent.resolve()


def _is_source_checkout(root: Path) -> bool:
    return (
        (root / ".git").exists()
        and (root / "skills").is_dir()
        and (root / "agents").is_dir()
        and (root / "runtime").is_dir()
    )


def _manifest_tarball_metadata() -> tuple[str, str]:
    allow_file_urls = bool(os.environ.get("Z_HARNESS_ALLOW_FILE_RELEASE_URLS"))
    try:
        manifest = fetch_manifest(allow_file_urls=allow_file_urls)
        return require_plugin_tarball_metadata(manifest)
    except (FetchError, ManifestParseError, ManifestSchemaError) as exc:
        typer.echo(f"Error: could not resolve release manifest for tarball install: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def run(
    ctx: typer.Context,
    *,
    target: str,
    tarball: Optional[str],
    force: bool,
    generate_exports: bool,
) -> None:
    """Run install.sh with CLI-validated arguments."""
    if target not in {"claude", "codex", "all"}:
        typer.echo("Error: --target must be one of: claude, codex, all", err=True)
        raise typer.Exit(code=2)

    root = _harness_root()
    source_checkout = _is_source_checkout(root)
    resolved_target = target

    script = root / "install.sh"
    if not script.is_file():
        typer.echo(
            "Error: install.sh is missing from this z-harness installation. "
            "Reinstall z-harness or use a source checkout.",
            err=True,
        )
        raise typer.Exit(code=1)

    resolved_tarball = tarball
    resolved_tarball_sha256: Optional[str] = None
    if not resolved_tarball and not source_checkout:
        resolved_tarball, resolved_tarball_sha256 = _manifest_tarball_metadata()

    args = ["bash", str(script), f"--target={resolved_target}"]
    if resolved_tarball:
        args.append(f"--tarball={resolved_tarball}")
    if resolved_tarball_sha256:
        args.append(f"--tarball-sha256={resolved_tarball_sha256}")
    if force:
        args.append("--force")
    if generate_exports:
        args.append("--generate-exports")

    result = subprocess.run(args, cwd=str(root), check=False)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
