"""commands/update.py — `z-harness update` command.

Spec reference: SPEC.md "Release + update (D4, D9)", F6, F9.

Behavior:
- Fetches the release manifest (latest.json) via release.fetch_manifest().
- Compares the installed version (from z_harness_cli.__version__) against
  the manifest using release.compare_versions().
- Stale wheel install (uv tool install):
    1. Download the wheel to a temp file.
    2. Verify the sha256 against manifest.sha256 — abort with exit 1 on mismatch.
    3. Install the verified local wheel via `uv tool install`.
- Stale source/symlink plugin install:
    1. Abort on a dirty checkout.
    2. Run `git pull --ff-only`.
- Stale tarball/runtime plugin install:
    → Do not self-swap from host prose. Print manifest-backed reinstall
      instructions that route through `z-harness install` / install.sh checksum
      verification.
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
from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class PluginInstall:
    """Best-effort classification of the plugin payload this command can see."""

    mode: str
    root: Path | None = None
    target: str | None = None


def _harness_root() -> Path:
    """Return the installed/source payload root that contains z_harness_cli."""

    return Path(__file__).parent.parent.parent.resolve()


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    return Path(value).expanduser()


def _candidate_plugin_roots() -> list[tuple[Path, str | None]]:
    """Return plausible plugin roots, newest/specific first."""

    candidates: list[tuple[Path, str | None]] = []
    for env_name, target in (
        ("Z_HARNESS_PLUGIN_ROOT", None),
        ("CLAUDE_PLUGIN_ROOT", "claude"),
        ("ANTIGRAVITY_PLUGIN_ROOT", None),
        ("OMP_PLUGIN_ROOT", None),
    ):
        path = _path_from_env(env_name)
        if path is not None:
            candidates.append((path, target))

    home = Path.home()
    candidates.extend(
        [
            (home / ".claude" / "plugins" / "z-harness@zeke-tools", "claude"),
            (home / "plugins" / "z-harness", "codex"),
            (_harness_root(), None),
        ]
    )
    return candidates


def _looks_like_payload(root: Path) -> bool:
    return (root / "skills").is_dir() and (root / "agents").is_dir()


def _detect_plugin_install() -> PluginInstall:
    """Classify a source/symlink/tarball plugin install without network access."""

    for candidate, target in _candidate_plugin_roots():
        if not (candidate.exists() or candidate.is_symlink()):
            continue

        root = candidate.resolve()
        if candidate.is_symlink():
            return PluginInstall("symlink", root, target)
        if (root / ".git").exists() and _looks_like_payload(root):
            return PluginInstall("symlink", root, target)
        if (root / "runtime").is_dir() and _looks_like_payload(root):
            return PluginInstall("tarball", root, target)

    return PluginInstall("unknown", None, None)


def _default_reinstall_target(install: PluginInstall) -> str:
    return install.target or "claude"

def _is_uv_tool_install() -> bool:
    """Best-effort: return True if z-harness was installed via `uv tool install`.

    Checks whether the running interpreter lives inside a uv-managed tool env
    (typically $HOME/.local/share/uv/tools/z-harness/...).
    """
    exe = sys.executable
    return "uv/tools/z-harness" in exe or "uv/tools/z_harness" in exe


def _apply_update(manifest: ReleaseManifest) -> None:
    """Apply or route the update using deterministic install-mode handling."""
    if _is_uv_tool_install():
        _apply_uv_upgrade(manifest)
        return

    install = _detect_plugin_install()
    if install.mode == "symlink":
        _apply_symlink_update(install)
        return

    _apply_reinstall_hint(manifest, install)


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


def _apply_symlink_update(install: PluginInstall) -> None:
    """Fast-forward a source/symlink checkout, aborting on dirty/diverged state."""

    if install.root is None:
        typer.echo(
            "Could not locate the z-harness source checkout for this symlink install.",
            err=True,
        )
        raise typer.Exit(code=1)

    dirty = subprocess.run(
        ["git", "-C", str(install.root), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    if dirty.returncode != 0:
        typer.echo(
            f"Could not inspect git status for {install.root}. "
            "Resolve the checkout manually, then re-run /z-update.",
            err=True,
        )
        raise typer.Exit(code=1)
    if dirty.stdout.strip():
        typer.echo(
            "Aborting: z-harness source checkout has uncommitted changes.\n"
            f"  checkout: {install.root}\n"
            "Commit or stash your changes, then re-run /z-update.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo(f"Updating z-harness source checkout at {install.root}…")
    pull = subprocess.run(
        ["git", "-C", str(install.root), "pull", "--ff-only"],
        check=False,
    )
    if pull.returncode != 0:
        typer.echo(
            "git pull --ff-only failed. Resolve the checkout manually; "
            "z-update will not merge, reset, or force-update your source tree.",
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo("z-harness source checkout updated. Restart the host to load refreshed commands.")


def _apply_reinstall_hint(manifest: ReleaseManifest, install: PluginInstall) -> None:
    """Route non-symlink plugin payloads to manifest-backed reinstall code."""

    target = _default_reinstall_target(install)
    mode = install.mode if install.mode != "unknown" else "non-uv"
    command = f"z-harness install --target={target} --force"
    python_command = f"python3 -m z_harness_cli install --target={target} --force"
    typer.echo(
        f"z-harness {manifest.version} is available, but this {mode} install is not\n"
        "self-updated by /z-update. Safe tarball replacement must go through\n"
        "the deterministic installer, which fetches the release manifest and\n"
        "passes the audited tarball URL plus SHA-256 to install.sh.\n"
        "\n"
        "Run:\n"
        f"  {command}\n"
        "If the z-harness executable is not on PATH, run from the plugin payload:\n"
        f"  {python_command}\n"
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
                "No automatic update applied for dev builds. "
                "Update a clean source checkout with `git pull --ff-only`, "
                "or reinstall a tagged release with `z-harness install`."
            )
        else:
            typer.echo(
                f"Installed version ({__version__}) is not a tagged release "
                f"comparable to latest release {manifest.version}. "
                "No automatic update applied. Update a clean source checkout "
                "with `git pull --ff-only`, or reinstall a tagged release with "
                "`z-harness install`."
            )
        return

    # result == VersionComparisonResult.STALE
    typer.echo(
        f"A newer version of z-harness is available: {manifest.version} "
        f"(installed: {__version__})."
    )
    _apply_update(manifest)
