"""Inventory and transactionally update the public z-harness installation.

C4-D1 makes the CLI and independently detected Claude/Codex payloads one
candidate-alignment decision. Manifest-backed packaged components are replaced
through install.sh's durable journal; clean source aliases fast-forward one
deduplicated checkout. Standalone uv replacement keeps recoverable tool and
launcher backups outside the tool root. Development builds remain explicit and
are never auto-updated.
"""

from __future__ import annotations

import os
import fcntl
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from contextlib import contextmanager
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
    parse_release_candidate,
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


@dataclass(frozen=True)
class ComponentInventory:
    """One independently detected lifecycle component."""

    name: str
    mode: str
    location: Path | None
    version: str | None


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


def _payload_version(root: Path) -> str | None:
    """Read a payload's canonical VERSION, returning None when unknown."""

    try:
        value = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _inventory_host(target: str, path: Path) -> ComponentInventory:
    """Classify one host without allowing another component to mask it."""

    if not (path.exists() or path.is_symlink()):
        return ComponentInventory(target, "missing", path, None)
    try:
        root = path.resolve(strict=True)
    except OSError:
        return ComponentInventory(target, "unknown", path, None)
    if path.is_symlink() or (root / ".git").exists():
        mode = "symlink"
    elif _looks_like_payload(root):
        mode = "packaged"
    else:
        mode = "unknown"
    return ComponentInventory(target, mode, root, _payload_version(root))


def inventory_components() -> tuple[ComponentInventory, ComponentInventory, ComponentInventory]:
    """Return independent CLI, Claude, and Codex installation state."""

    executable = Path(sys.executable).resolve()
    source_root = _harness_root()
    if _is_uv_tool_install():
        cli_mode = "uv-tool"
        cli_location = executable
    elif (source_root / ".git").exists():
        cli_mode = "source"
        cli_location = source_root
    else:
        cli_mode = "executable"
        cli_location = executable
    cli = ComponentInventory("cli", cli_mode, cli_location, __version__)
    home = Path.home()
    claude_path = _path_from_env("CLAUDE_PLUGIN_ROOT") or (
        home / ".claude" / "plugins" / "z-harness@zeke-tools"
    )
    # Antigravity and OMP are export/provider roots, never the supported Codex
    # direct-install destination mutated by install.sh.
    codex_path = home / "plugins" / "z-harness"
    return cli, _inventory_host("claude", claude_path), _inventory_host("codex", codex_path)


def _component_is_stale(component: ComponentInventory, manifest: ReleaseManifest) -> bool:
    """Return whether a selected component needs candidate replacement."""

    if component.mode == "missing":
        return False
    if component.version is None:
        return True
    result = compare_versions(component.version, manifest)
    return result in {VersionComparisonResult.STALE, VersionComparisonResult.DEV_UNKNOWN}


def _echo_inventory(components: tuple[ComponentInventory, ...]) -> None:
    """Render the independently classified local inventory."""

    for component in components:
        typer.echo(
            f"inventory {component.name}: mode={component.mode} "
            f"location={component.location or 'missing'} "
            f"version={component.version or ('missing' if component.mode == 'missing' else 'unknown')}"
        )


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
        _apply_symlink_update(install, manifest)
        return

    _apply_reinstall_hint(manifest, install)


def _download_verified_wheel(manifest: ReleaseManifest) -> Path:
    """Download and verify the manifest-selected wheel before mutation."""

    typer.echo(f"Downloading z-harness {manifest.version}…")
    try:
        with urllib.request.urlopen(manifest.wheel_url, timeout=60) as response:
            wheel_bytes = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        typer.echo(f"Download failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as temporary:
        temporary.write(wheel_bytes)
        wheel = Path(temporary.name)
    typer.echo("Verifying sha256…")
    if not verify_sha256(str(wheel), manifest.sha256):
        wheel.unlink(missing_ok=True)
        typer.echo(
            "SHA-256 mismatch for downloaded wheel. "
            f"Expected {manifest.sha256}. "
            "Aborting install — the download may be corrupt or tampered with.",
            err=True,
        )
        raise typer.Exit(code=1)
    return wheel


def _cli_transaction_environment(wheel: Path) -> dict[str, str]:
    """Describe the exact uv tool and launcher pre-state to install.sh."""

    environment = os.environ.copy()
    environment["Z_HARNESS_TRANSACTION_CLI_WHEEL"] = str(wheel)
    environment["Z_HARNESS_TRANSACTION_CLI_TOOL_ROOT"] = str(Path(sys.prefix).resolve())
    launcher = shutil.which("z-harness")
    launcher_zh = shutil.which("zh")
    if launcher:
        environment["Z_HARNESS_TRANSACTION_CLI_LAUNCHER"] = launcher
    if launcher_zh:
        environment["Z_HARNESS_TRANSACTION_CLI_LAUNCHER_ZH"] = launcher_zh
    return environment


def _cli_transaction_path() -> Path:
    """Return the HOME-scoped recovery location outside the uv tool root."""

    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "z-harness" / "lifecycle" / "cli-current"


def _lifecycle_lock_path() -> Path:
    return _cli_transaction_path().parent / "lock"


_HELD_LOCK_TOKENS: dict[Path, str] = {}


def _process_start_identity(pid: int) -> str | None:
    process = subprocess.Popen(
        ["/bin/ps", "-o", "lstart=", "-p", str(pid)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    stdout, _ = process.communicate()
    value = stdout.strip()
    return value if process.returncode == 0 and value else None


def _read_lock_owner(lock: Path) -> dict[str, object] | None:
    try:
        value = json.loads((lock / "owner.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        try:
            legacy_pid = int((lock / "pid").read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        started = _process_start_identity(legacy_pid)
        return {"pid": legacy_pid, "started": started, "token": "legacy"}
    return value if isinstance(value, dict) else None


def _owner_is_live(owner: dict[str, object]) -> bool:
    pid = owner.get("pid")
    started = owner.get("started")
    return isinstance(pid, int) and isinstance(started, str) and _process_start_identity(pid) == started


def _acquire_lifecycle_lock_for_pid(owner_pid: int) -> tuple[Path, str]:
    """Atomically publish a complete token/PID/start owner record."""

    lock = _lifecycle_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    started = _process_start_identity(owner_pid)
    if started is None:
        raise RuntimeError(f"Cannot identify lifecycle owner pid {owner_pid}")
    token = secrets.token_hex(32)
    guard = lock.parent / ".lock.guard"
    with guard.open("a+", encoding="utf-8") as guard_handle:
        fcntl.flock(guard_handle.fileno(), fcntl.LOCK_EX)
        if lock.exists():
            observed = _read_lock_owner(lock)
            if observed is not None and _owner_is_live(observed):
                raise RuntimeError(f"Lifecycle transaction is owned by active pid {observed['pid']}")
            quarantine = lock.parent / f".lock.stale.{secrets.token_hex(16)}"
            os.rename(lock, quarantine)
            if _read_lock_owner(quarantine) != observed:
                if not lock.exists():
                    os.rename(quarantine, lock)
                raise RuntimeError("Lifecycle lock changed during stale reclaim")
            shutil.rmtree(quarantine)
        candidate = lock.parent / f".lock.candidate.{token}"
        candidate.mkdir()
        _atomic_write_text(
            candidate / "owner.json",
            json.dumps({"pid": owner_pid, "started": started, "token": token}),
        )
        try:
            os.rename(candidate, lock)
        except BaseException:
            shutil.rmtree(candidate, ignore_errors=True)
            raise
    return lock, token


def _acquire_lifecycle_lock() -> Path:
    lock, token = _acquire_lifecycle_lock_for_pid(os.getpid())
    _HELD_LOCK_TOKENS[lock] = token
    return lock


def _release_lifecycle_lock(lock: Path) -> None:
    """Release only the lock owned by this process."""

    token = _HELD_LOCK_TOKENS.pop(lock, None)
    owner = _read_lock_owner(lock)
    if token is not None and owner is not None and owner.get("pid") == os.getpid():
        _release_lifecycle_lock_token(lock, token)


def _handoff_lifecycle_lock(lock: Path, token: str, child_pid: int) -> None:
    started = _process_start_identity(child_pid)
    if started is None:
        raise RuntimeError("Cannot identify lifecycle handoff child")
    guard = lock.parent / ".lock.guard"
    with guard.open("a+", encoding="utf-8") as guard_handle:
        fcntl.flock(guard_handle.fileno(), fcntl.LOCK_EX)
        owner = _read_lock_owner(lock)
        if owner is None or owner.get("token") != token or owner.get("pid") != os.getpid():
            raise RuntimeError("Lifecycle ownership changed before child handoff")
        _atomic_write_text(
            lock / "owner.json",
            json.dumps({"pid": child_pid, "started": started, "token": token}),
        )


def _accept_lifecycle_handoff(lock: Path, token: str, child_pid: int) -> bool:
    for _ in range(100):
        owner = _read_lock_owner(lock)
        if (
            owner is not None
            and owner.get("token") == token
            and owner.get("pid") == child_pid
            and _owner_is_live(owner)
        ):
            return True
        time.sleep(0.05)
    return False


def _release_lifecycle_lock_token(lock: Path, token: str) -> None:
    guard = lock.parent / ".lock.guard"
    with guard.open("a+", encoding="utf-8") as guard_handle:
        fcntl.flock(guard_handle.fileno(), fcntl.LOCK_EX)
        owner = _read_lock_owner(lock)
        if owner is not None and owner.get("token") == token:
            quarantine = lock.parent / f".lock.release.{token}"
            os.rename(lock, quarantine)
            shutil.rmtree(quarantine)


@contextmanager
def _lifecycle_ownership():
    """Hold exclusive lifecycle ownership for one mutation/recovery section."""

    lock = _acquire_lifecycle_lock()
    try:
        yield
    finally:
        _release_lifecycle_lock(lock)


def _safe_uv_tool_root(path: Path) -> bool:
    """Accept only the named z-harness uv tool environment under HOME."""

    try:
        path.resolve().relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return False
    return "uv" in path.parts and "tools" in path.parts and path.name in {"z-harness", "z_harness"}


def _safe_launcher(path: Path) -> bool:
    """Accept only z-harness launchers stored beneath HOME."""

    try:
        path.parent.resolve().relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return False
    return path.name in {"z-harness", "zh"}


def _atomic_write_text(path: Path, value: str) -> None:
    """Durably replace one small transaction metadata file."""

    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree(root: Path) -> None:
    """Persist copied backup contents and directory entries before mutation."""

    paths = [root]
    if root.is_dir() and not root.is_symlink():
        paths.extend(root.rglob("*"))
    for path in paths:
        if path.is_file() and not path.is_symlink():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    for path in reversed(paths):
        if path.is_dir() and not path.is_symlink():
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    descriptor = os.open(root.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _cli_preparation_fault(step: str) -> None:
    if os.environ.get("Z_HARNESS_TEST_FAIL_AFTER") == step:
        raise RuntimeError(f"Injected failure after {step}")


def _restore_cli_transaction(transaction: Path) -> None:
    """Restore a complete CLI backup and remove it only after success."""

    tool_root = Path((transaction / "tool.path").read_text(encoding="utf-8").strip())
    if not _safe_uv_tool_root(tool_root):
        raise RuntimeError("Refusing corrupt or unconfined CLI tool recovery path")
    shutil.rmtree(tool_root, ignore_errors=True)
    shutil.copytree(transaction / "tool", tool_root, symlinks=True)
    for path_file in sorted(transaction.glob("launcher-*.path")):
        index = path_file.name.removesuffix(".path")
        launcher_path = Path(path_file.read_text(encoding="utf-8").strip())
        if not _safe_launcher(launcher_path):
            raise RuntimeError("Refusing corrupt or unconfined CLI launcher recovery path")
        launcher_path.unlink(missing_ok=True)
        shutil.copy2(transaction / index, launcher_path, follow_symlinks=False)
    shutil.rmtree(transaction)


def _recover_cli_transaction() -> None:
    """Idempotently restore an interrupted standalone CLI replacement."""

    transaction = _cli_transaction_path()
    phase_path = transaction / "phase"
    if phase_path.is_file():
        phase = phase_path.read_text(encoding="utf-8").strip()
        if phase in {"preparing", "prepared"}:
            shutil.rmtree(transaction)
            return
        if phase != "applying":
            raise RuntimeError("Unknown CLI recovery phase; state retained")
    metadata = transaction / "tool.path"
    backup = transaction / "tool"
    if not metadata.is_file() or not backup.is_dir():
        return
    _restore_cli_transaction(transaction)


def _recover_intervening_transactions() -> None:
    """Recover every durable lifecycle record while mutation ownership is held."""

    _recover_cli_transaction()
    _recover_source_transaction()
    if _cli_transaction_path().exists() or _source_transaction_path().exists():
        raise RuntimeError("Incomplete lifecycle recovery state is retained; refusing mutation")


def _apply_packaged_transaction(
    manifest: ReleaseManifest,
    targets: list[ComponentInventory],
    *,
    replace_cli: bool,
) -> None:
    """Run packaged payloads and an optional CLI swap as one shell transaction."""

    tarball_url = manifest.plugin_tarball_url
    tarball_sha256 = manifest.plugin_tarball_sha256
    if not tarball_url or not tarball_sha256:
        typer.echo("Release manifest is missing verified plugin tarball metadata.", err=True)
        raise typer.Exit(code=1)
    target_names = {component.name for component in targets}
    target = "all" if target_names == {"claude", "codex"} else next(iter(target_names))
    script = _harness_root() / "install.sh"
    args = [
        "bash",
        str(script),
        f"--target={target}",
        f"--tarball={tarball_url}",
        f"--tarball-sha256={tarball_sha256}",
        "--force",
    ]
    wheel: Path | None = None
    environment = os.environ.copy()
    try:
        if replace_cli:
            wheel = _download_verified_wheel(manifest)
            environment = _cli_transaction_environment(wheel)
        with _lifecycle_ownership():
            _recover_intervening_transactions()
            lock = _lifecycle_lock_path()
            token = _HELD_LOCK_TOKENS[lock]
            environment["Z_HARNESS_HANDOFF_TOKEN"] = token
            process = subprocess.Popen(args, cwd=str(_harness_root()), env=environment)
            try:
                _handoff_lifecycle_lock(lock, token, process.pid)
            except BaseException:
                process.terminate()
                process.wait()
                raise
            result_code = process.wait()
        if result_code != 0:
            raise typer.Exit(code=result_code)
    except RuntimeError as exc:
        typer.echo(f"Lifecycle recovery failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if wheel is not None:
            wheel.unlink(missing_ok=True)


def _apply_detected_transaction(
    manifest: ReleaseManifest,
    components: tuple[ComponentInventory, ComponentInventory, ComponentInventory],
) -> None:
    """Update every stale detected component without adding absent hosts."""

    cli, claude, codex = components
    cli_stale = _component_is_stale(cli, manifest)
    hosts = [component for component in (claude, codex) if component.mode != "missing"]
    stale_hosts = [component for component in hosts if _component_is_stale(component, manifest)]
    newer_hosts = [
        component
        for component in hosts
        if component.version is not None
        and compare_versions(component.version, manifest) == VersionComparisonResult.NEWER
    ]
    cli_comparison = compare_versions(cli.version or "unknown", manifest)
    if newer_hosts or (cli_comparison == VersionComparisonResult.NEWER and hosts):
        typer.echo(
            "Detected components cannot be aligned to the candidate without a downgrade; "
            "no changes were made.",
            err=True,
        )
        raise typer.Exit(code=1)
    if cli_comparison == VersionComparisonResult.NEWER and not hosts:
        typer.echo(
            f"Installed version ({cli.version}) is newer than the latest release "
            f"({manifest.version}). No update needed."
        )
        return
    if not cli_stale and not stale_hosts:
        typer.echo(f"z-harness {manifest.version} is up to date across all detected components.")
        return

    symlink_hosts = [component for component in stale_hosts if component.mode == "symlink"]
    packaged_hosts = [component for component in stale_hosts if component.mode in {"packaged", "unknown"}]
    if symlink_hosts and packaged_hosts:
        typer.echo(
            "Cannot atomically update mixed source-symlink and packaged host payloads. "
            "Align their install modes first.",
            err=True,
        )
        raise typer.Exit(code=1)

    if symlink_hosts:
        roots = {component.location for component in symlink_hosts if component.location is not None}
        if len(roots) != 1:
            typer.echo(
                "Cannot atomically fast-forward host symlinks backed by different checkouts.",
                err=True,
            )
            raise typer.Exit(code=1)
        install = PluginInstall("symlink", next(iter(roots)), "all" if len(symlink_hosts) == 2 else symlink_hosts[0].name)
        if cli_stale:
            if cli.mode == "source" and cli.location in roots:
                pass
            elif cli.mode == "source":
                typer.echo("Detected source components resolve to different checkouts.", err=True)
                raise typer.Exit(code=1)
            elif cli.mode == "uv-tool":
                typer.echo(
                    "Cannot atomically combine a uv CLI replacement with source-symlink host payloads.",
                    err=True,
                )
                raise typer.Exit(code=1)
            else:
                typer.echo(
                    "Cannot update source-symlink host payloads while the standalone CLI is stale; "
                    "reinstall the CLI first so no mixed-version state is created.",
                    err=True,
                )
                raise typer.Exit(code=1)
        _apply_symlink_update(install, manifest)
        return

    if packaged_hosts:
        if cli_stale and cli.mode != "uv-tool":
            typer.echo(
                "Cannot update packaged host payloads while the non-uv CLI is stale; "
                "reinstall the CLI first so the component set remains coherent.",
                err=True,
            )
            raise typer.Exit(code=1)
        _apply_packaged_transaction(manifest, packaged_hosts, replace_cli=cli_stale and cli.mode == "uv-tool")
        return

    if cli_stale and cli.mode == "uv-tool":
        _apply_uv_upgrade(manifest)
        return

    if cli_stale and cli.mode == "source" and cli.location is not None:
        _apply_symlink_update(PluginInstall("symlink", cli.location, None), manifest)
        return

    _apply_reinstall_hint(manifest, _detect_plugin_install())


def _apply_uv_upgrade(manifest: ReleaseManifest) -> None:
    """Download the wheel, verify sha256 (F9), then install the local file via uv."""
    tmp_path = str(_download_verified_wheel(manifest))
    tool_root = Path(sys.prefix).resolve()
    durable_backup = "uv/tools/z-harness" in str(tool_root) or "uv/tools/z_harness" in str(tool_root)
    transaction = _cli_transaction_path()
    launcher_paths = [Path(path) for path in (shutil.which("z-harness"), shutil.which("zh")) if path]
    if not durable_backup or not _safe_uv_tool_root(tool_root):
        os.unlink(tmp_path)
        typer.echo("Refusing CLI replacement outside the supported HOME uv tool root.", err=True)
        raise typer.Exit(code=1)
    if any(not _safe_launcher(path) for path in launcher_paths):
        os.unlink(tmp_path)
        typer.echo("Refusing CLI replacement with an unconfined launcher path.", err=True)
        raise typer.Exit(code=1)
    try:
        lifecycle_lock = _acquire_lifecycle_lock()
    except RuntimeError as exc:
        os.unlink(tmp_path)
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        _recover_intervening_transactions()
        if durable_backup:
            transaction.mkdir(parents=True)
            _atomic_write_text(transaction / "tool.path", str(tool_root))
            for index, launcher_path in enumerate(launcher_paths):
                _atomic_write_text(transaction / f"launcher-{index}.path", str(launcher_path))
            _atomic_write_text(transaction / "phase", "preparing")
            _cli_preparation_fault("cli.prepare.metadata")
            shutil.copytree(tool_root, transaction / "tool", symlinks=True)
            _fsync_tree(transaction / "tool")
            _cli_preparation_fault("cli.prepare.tool")
            for index, launcher_path in enumerate(launcher_paths):
                shutil.copy2(launcher_path, transaction / f"launcher-{index}", follow_symlinks=False)
                _fsync_tree(transaction / f"launcher-{index}")
            _cli_preparation_fault("cli.prepare.launchers")
            _atomic_write_text(transaction / "phase", "prepared")
            _cli_preparation_fault("cli.prepare.ready")
        typer.echo(f"Installing z-harness {manifest.version} via uv…")
        if durable_backup:
            _atomic_write_text(transaction / "phase", "applying")
        result = subprocess.run(
            ["uv", "tool", "install", "--upgrade", tmp_path],
            check=False,
        )
        if result.returncode != 0:
            if durable_backup:
                _restore_cli_transaction(transaction)
            typer.echo(
                "uv install failed. You can retry manually with:\n"
                f"  uv tool install {manifest.wheel_url}",
                err=True,
            )
            raise typer.Exit(code=1)
        verifier = shutil.which("z-harness")
        verified_version = ""
        if verifier:
            verification = subprocess.run(
                [verifier, "--version"],
                check=False,
                capture_output=True,
                text=True,
            )
            if verification.returncode == 0:
                verified_version = verification.stdout.strip().split()[-1]
        try:
            coherent = parse_release_candidate(verified_version) == parse_release_candidate(
                manifest.version
            )
        except (ValueError, IndexError):
            coherent = False
        if not coherent:
            if durable_backup:
                _restore_cli_transaction(transaction)
            typer.echo(
                "Updated CLI did not report the explicit release candidate; pre-state restored.",
                err=True,
            )
            raise typer.Exit(code=1)
        fault_step = os.environ.get("Z_HARNESS_TEST_FAIL_AFTER")
        if fault_step in {"cli.tool", "cli.launcher"}:
            if durable_backup:
                _restore_cli_transaction(transaction)
            typer.echo(f"Injected failure after {fault_step}; CLI pre-state restored.", err=True)
            raise typer.Exit(code=97)
        if durable_backup:
            shutil.rmtree(transaction)
        typer.echo(f"Successfully upgraded to z-harness {manifest.version}.")
    finally:
        os.unlink(tmp_path)
        _release_lifecycle_lock(lifecycle_lock)


def _source_transaction_path() -> Path:
    """Return durable source-update recovery metadata outside the checkout."""

    return _cli_transaction_path().parent / "source-current.json"


def _confined_to_home(path: Path) -> bool:
    """Return whether a resolved mutable path remains under the user's HOME."""

    try:
        path.resolve().relative_to(Path.home().resolve())
    except (OSError, ValueError):
        return False
    return True


def _restore_source_transaction(record_path: Path) -> None:
    """Restore a clean fast-forwarded checkout without a force reset."""

    record = json.loads(record_path.read_text(encoding="utf-8"))
    root = Path(record["root"])
    old_head = record["old_head"]
    if not _confined_to_home(root) or not isinstance(old_head, str) or len(old_head) != 40:
        raise RuntimeError("Refusing corrupt or unconfined source recovery record")
    restored = subprocess.run(
        ["git", "-C", str(root), "reset", "--keep", old_head],
        check=False,
    )
    if restored.returncode != 0:
        raise RuntimeError(f"Could not restore source checkout {root}; recovery record retained")
    record_path.unlink()


def _recover_source_transaction() -> None:
    """Recover an interrupted candidate-bound source update, if present."""

    record_path = _source_transaction_path()
    if record_path.exists():
        _restore_source_transaction(record_path)


def _apply_symlink_update(
    install: PluginInstall,
    manifest: ReleaseManifest | None = None,
) -> None:
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

    if manifest is None:
        # Compatibility for direct internal callers; production update always
        # supplies the explicit manifest candidate.
        typer.echo(f"Updating z-harness source checkout at {install.root}…")
        pull = subprocess.run(
            ["git", "-C", str(install.root), "pull", "--ff-only"],
            check=False,
        )
        if pull.returncode != 0:
            raise typer.Exit(code=1)
        typer.echo("z-harness source checkout updated. Restart the host to load refreshed commands.")
        return

    try:
        with _lifecycle_ownership():
            _recover_intervening_transactions()
            _apply_candidate_source_update(install, manifest)
    except RuntimeError as exc:
        typer.echo(f"Source transaction failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _apply_candidate_source_update(install: PluginInstall, manifest: ReleaseManifest) -> None:
    """Fast-forward one clean checkout to the exact explicit candidate."""

    assert install.root is not None
    if not _confined_to_home(install.root):
        typer.echo("Refusing to mutate a source checkout outside HOME.", err=True)
        raise typer.Exit(code=1)
    expected = parse_release_candidate(manifest.version)
    branch = subprocess.run(
        ["git", "-C", str(install.root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    remote = subprocess.run(
        ["git", "-C", str(install.root), "config", "--get", f"branch.{branch}.remote"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fetch = subprocess.run(
        [
            "git",
            "-C",
            str(install.root),
            "fetch",
            "--no-tags",
            remote,
            f"refs/tags/{expected.git_tag}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        typer.echo("git fetch failed; no source mutation was performed.", err=True)
        raise typer.Exit(code=1)
    old_head = subprocess.run(
        ["git", "-C", str(install.root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    candidate_head = subprocess.run(
        ["git", "-C", str(install.root), "rev-parse", "FETCH_HEAD^{commit}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    candidate_version = subprocess.run(
        ["git", "-C", str(install.root), "show", f"{candidate_head}:VERSION"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        tagged_candidate = parse_release_candidate(candidate_version)
    except ValueError as exc:
        typer.echo(f"Tagged source VERSION is not a release candidate: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if tagged_candidate != expected or candidate_version != expected.plugin_version:
        typer.echo(
            f"Tagged source is {candidate_version}, not explicit candidate {expected.plugin_version}; "
            "no source mutation was performed.",
            err=True,
        )
        raise typer.Exit(code=1)
    reachable = subprocess.run(
        ["git", "-C", str(install.root), "merge-base", "--is-ancestor", old_head, candidate_head],
        check=False,
    )
    if reachable.returncode != 0:
        typer.echo(
            f"Candidate tag {expected.git_tag} is not a fast-forward from the installed checkout; "
            "no source mutation was performed.",
            err=True,
        )
        raise typer.Exit(code=1)

    record_path = _source_transaction_path()
    record_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(record_path, json.dumps({"root": str(install.root), "old_head": old_head}))
    typer.echo(f"Updating z-harness source checkout at {install.root}…")
    merge = subprocess.run(
        ["git", "-C", str(install.root), "merge", "--ff-only", candidate_head],
        check=False,
    )
    if merge.returncode != 0:
        _restore_source_transaction(record_path)
        typer.echo(
            "git merge --ff-only failed. Resolve the checkout manually; "
            "z-update will not merge, reset, or force-update your source tree.",
            err=True,
        )
        raise typer.Exit(code=1)
    installed_version = _payload_version(install.root)
    installed_head = subprocess.run(
        ["git", "-C", str(install.root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        installed_candidate = parse_release_candidate(installed_version or "")
    except ValueError:
        installed_candidate = None
    if (
        installed_head != candidate_head
        or installed_candidate != expected
        or installed_version != expected.plugin_version
    ):
        _restore_source_transaction(record_path)
        typer.echo("Source update failed candidate coherence and was restored.", err=True)
        raise typer.Exit(code=1)
    record_path.unlink()

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
        recovery_lock = _acquire_lifecycle_lock()
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    try:
        _recover_intervening_transactions()
    except RuntimeError as exc:
        typer.echo(f"Lifecycle recovery failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        _release_lifecycle_lock(recovery_lock)
    try:
        manifest = fetch_manifest()
    except ManifestSchemaError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    except (FetchError, ManifestParseError) as exc:
        typer.echo(f"Error fetching release manifest: {exc}", err=True)
        raise typer.Exit(code=1)

    components = inventory_components()
    _echo_inventory(components)
    result = compare_versions(__version__, manifest)

    if result == VersionComparisonResult.EQUAL:
        _apply_detected_transaction(manifest, components)
        return

    if result == VersionComparisonResult.NEWER:
        _apply_detected_transaction(manifest, components)
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

    # result == VersionComparisonResult.STALE. Host payloads remain part of the
    # same decision; CLI staleness never short-circuits their inventory.
    typer.echo(
        f"A newer version of z-harness is available: {manifest.version} "
        f"(installed: {__version__})."
    )
    _apply_detected_transaction(manifest, components)
