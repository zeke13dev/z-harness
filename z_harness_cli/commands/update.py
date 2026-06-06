"""commands/update.py — `z-harness update` command.

Spec reference: SPEC.md "Release + update (D4, D9)", F6, F9.

Behavior:
- Fetches the release manifest (latest.json) via release.fetch_manifest().
- Compares the installed version (from z_harness_cli.__version__) against
  the manifest using release.compare_versions().
- Stale install (uv tool install):
    1. Download the wheel to a temp file.
    2. Verify the sha256 against manifest.sha256 — abort with exit 1 on mismatch.
    3. Install the verified local wheel via `uv tool install`.
- Stale install (symlink/tarball):
    → Print a clear, actionable message and exit 1 so the user knows
      they must use /z-update or re-run the install script. Never silently no-op.
- Equal version  → no-op (idempotent).
- Dev SHA / PEP 440 dev install → prints a notice but never blocks or auto-updates.
- Newer manifest schema_version → clean exit 1 with "update z-harness" message.
- No auto-update without explicit `z-harness update` invocation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import typer

from z_harness_cli import __version__
from z_harness_cli.release import (
    FetchError,
    ManifestParseError,
    ManifestSchemaError,
    ReleaseManifest,
    VersionComparisonResult,
    compare_versions,
    fetch_manifest,
    is_dev_sha,
    verify_sha256,
)

if TYPE_CHECKING:
    pass


def _is_uv_tool_install() -> bool:
    """Best-effort: return True if z-harness was installed via `uv tool install`.

    Checks whether the running interpreter lives inside a uv-managed tool env
    (typically $HOME/.local/share/uv/tools/z-harness/...).
    """
    exe = sys.executable
    return "uv/tools/z-harness" in exe or "uv/tools/z_harness" in exe


def _apply_update(manifest: ReleaseManifest) -> None:
    """Apply the update using the appropriate mechanism."""
    if _is_uv_tool_install():
        _apply_uv_upgrade(manifest)
    else:
        _apply_symlink_hint(manifest)


def _apply_uv_upgrade(manifest: ReleaseManifest) -> None:
    """Download the wheel, verify sha256 (F9), then install the local file via uv."""
    typer.echo(f"Downloading z-harness {manifest.version}…")
    try:
        with urllib.request.urlopen(manifest.wheel_url, timeout=60) as resp:
            wheel_bytes = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        typer.echo(f"Download failed: {exc}", err=True)
        raise typer.Exit(code=1)

    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as tmp:
        tmp.write(wheel_bytes)
        tmp_path = tmp.name

    try:
        typer.echo("Verifying sha256…")
        if not verify_sha256(tmp_path, manifest.sha256):
            typer.echo(
                f"SHA-256 mismatch for downloaded wheel. "
                f"Expected {manifest.sha256}. "
                "Aborting install — the download may be corrupt or tampered with.",
                err=True,
            )
            raise typer.Exit(code=1)

        typer.echo(f"Installing z-harness {manifest.version} via uv…")
        result = subprocess.run(
            ["uv", "tool", "install", "--upgrade", tmp_path],
            check=False,
        )
        if result.returncode != 0:
            typer.echo(
                "uv install failed. You can retry manually with:\n"
                f"  uv tool install {manifest.wheel_url}",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(f"Successfully upgraded to z-harness {manifest.version}.")
    finally:
        os.unlink(tmp_path)


def _apply_symlink_hint(manifest: ReleaseManifest) -> None:
    """For non-uv installs (symlink/tarball), print actionable instructions and exit 1.

    This install type cannot be updated by the CLI — the user must use /z-update
    (symlink mode) or re-run the install script (tarball mode). We exit 1 so the
    caller knows the update did NOT complete, not just that a hint was printed.
    """
    typer.echo(
        f"z-harness {manifest.version} is available, but this install cannot be\n"
        "updated automatically by `z-harness update`.\n"
        "\n"
        "To update a symlink install: run /z-update inside Claude Code.\n"
        "To update a tarball install: re-run the install script:\n"
        "  curl -fsSL <install-url> | sh\n"
        "\n"
        "No changes have been made.",
        err=True,
    )
    raise typer.Exit(code=1)


def run(ctx: "typer.Context") -> None:  # noqa: F821
    """Entry point called from __main__.update_cmd."""
    try:
        manifest = fetch_manifest()
    except ManifestSchemaError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except (FetchError, ManifestParseError) as exc:
        typer.echo(f"Error fetching release manifest: {exc}", err=True)
        raise typer.Exit(code=1)

    result = compare_versions(__version__, manifest)

    if result == VersionComparisonResult.EQUAL:
        typer.echo(f"z-harness {__version__} is up to date.")
        return

    if result == VersionComparisonResult.NEWER:
        typer.echo(
            f"Installed version ({__version__}) is newer than the latest release "
            f"({manifest.version}). No update needed."
        )
        return

    if result == VersionComparisonResult.DEV_UNKNOWN:
        if is_dev_sha(__version__):
            typer.echo(
                f"Installed version is a dev build ({__version__}). "
                f"Latest release is {manifest.version}. "
                "No automatic update applied for dev builds."
            )
        else:
            typer.echo(
                f"Installed version ({__version__}) is newer than the latest release "
                f"({manifest.version}). No update needed."
            )
        return

    # result == VersionComparisonResult.STALE
    typer.echo(
        f"A newer version of z-harness is available: {manifest.version} "
        f"(installed: {__version__})."
    )
    _apply_update(manifest)
