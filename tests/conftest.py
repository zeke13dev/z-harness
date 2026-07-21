"""Shared pytest fixtures for the z-harness test suite.

The sink's per-entry / global lock is held by a background daemon (forked by
`sink-lock.sh acquire`) that blocks in `signal.pause()` until released or
signalled. Tests that exercise the acquire path — directly or via
`sink-claim.sh` / `sink-status-set.sh` — and leave a holder alive (contention,
takeover, or simply not releasing in a negative-path assertion) would otherwise
leak that daemon past the test. Accumulated leaks destabilise later lock tests
(a stale holder changes acquire/takeover outcomes) and bloat the process table.

This autouse fixture SIGTERMs any daemon spawned during each test.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class _AnchorSnapshot:
    """Exact restorable state for a pre-session Git base anchor."""

    contents: bytes
    mode: int
    uid: int
    gid: int
    atime_ns: int
    mtime_ns: int


def _git_base_anchor() -> Path | None:
    """Resolve the current repository's Git-common-dir base anchor.

    Returns:
        The absolute anchor path, or ``None`` outside a Git repository.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = Path.cwd() / common_dir
    return common_dir.resolve() / ".z-harness-base"


def _quarantine_anchor(anchor: Path) -> Path | None:
    """Atomically move the current anchor into a private same-dir quarantine.

    The move targets a new file inside a uniquely created directory, so it
    cannot clobber another path. The moved object can then be inspected without
    a pathname race.

    Returns:
        The quarantined object, or ``None`` if no anchor existed at move time.
    """
    quarantine_dir = Path(
        tempfile.mkdtemp(prefix=".z-harness-base.pytest-quarantine-", dir=anchor.parent)
    )
    quarantined = quarantine_dir / "anchor"
    try:
        os.rename(anchor, quarantined)
    except FileNotFoundError:
        quarantine_dir.rmdir()
        return None
    except OSError:
        try:
            quarantine_dir.rmdir()
        except OSError:
            pass
        raise
    return quarantined


def _discard_quarantined(quarantined: Path) -> None:
    """Delete an already-validated quarantined regular file or symlink."""
    quarantined.unlink()
    quarantined.parent.rmdir()


def _republish_quarantined(anchor: Path, quarantined: Path) -> None:
    """Restore a quarantined non-directory object without clobbering a newer path.

    Raises:
        RuntimeError: If the object cannot be linked back without clobbering.
    """
    try:
        os.link(quarantined, anchor, follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError(
            f"Git base anchor retained safely at {quarantined}; "
            f"refusing to clobber {anchor}"
        ) from exc
    _discard_quarantined(quarantined)


def _snapshot_and_remove_anchor(anchor: Path | None) -> _AnchorSnapshot | None:
    """Quarantine, snapshot, and remove a regular pre-session anchor.

    Args:
        anchor: Absolute Git base-anchor path, if the session is in Git.

    Returns:
        Restorable state when an anchor existed, otherwise ``None``.

    Raises:
        RuntimeError: If a quarantined anchor cannot be safely handled.
    """
    if anchor is None:
        return None
    quarantined = _quarantine_anchor(anchor)
    if quarantined is None:
        return None
    before = quarantined.lstat()
    if not stat.S_ISREG(before.st_mode):
        _republish_quarantined(anchor, quarantined)
        raise RuntimeError(f"refusing to replace non-regular Git base anchor: {anchor}")

    try:
        contents = quarantined.read_bytes()
        snapshot = _AnchorSnapshot(
            contents=contents,
            mode=stat.S_IMODE(before.st_mode),
            uid=before.st_uid,
            gid=before.st_gid,
            atime_ns=before.st_atime_ns,
            mtime_ns=before.st_mtime_ns,
        )
    except OSError:
        _republish_quarantined(anchor, quarantined)
        raise
    _discard_quarantined(quarantined)
    return snapshot


def _anchor_is_session_owned(anchor: Path, session_state_root: Path) -> bool:
    """Return whether a regular anchor points inside this session's state root."""
    try:
        anchor_stat = anchor.lstat()
        if not stat.S_ISREG(anchor_stat.st_mode):
            return False
        payload = json.loads(anchor.read_bytes())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    path_value = payload.get("path") if isinstance(payload, dict) else None
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        return False
    try:
        Path(path_value).resolve(strict=False).relative_to(session_state_root.resolve())
    except ValueError:
        return False
    return True


def _stage_anchor_snapshot(anchor: Path, snapshot: _AnchorSnapshot) -> Path:
    """Write restorable anchor state to a unique same-directory staging file."""
    fd, temporary_name = tempfile.mkstemp(prefix=".z-harness-base.pytest-", dir=anchor.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(snapshot.contents)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchown(stream.fileno(), snapshot.uid, snapshot.gid)
            os.fchmod(stream.fileno(), snapshot.mode)
        os.utime(temporary, ns=(snapshot.atime_ns, snapshot.mtime_ns))
        return temporary
    except OSError:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def _publish_staged_snapshot(anchor: Path, staged: Path) -> None:
    """Publish staged anchor state atomically without clobbering another path.

    Raises:
        RuntimeError: If another anchor already occupies the destination. The
            staged snapshot is retained at the path named in the exception.
    """
    try:
        os.link(staged, anchor)
    except OSError as exc:
        raise RuntimeError(
            f"pre-session Git base anchor retained safely at {staged}; "
            f"refusing to clobber {anchor}"
        ) from exc
    staged.unlink()


def _restore_anchor_state(
    anchor: Path | None,
    snapshot: _AnchorSnapshot | None,
    session_state_root: Path,
) -> None:
    """Restore the initial anchor state without removing a foreign anchor.

    Raises:
        RuntimeError: If an unrelated anchor appeared during the session.
    """
    if anchor is None:
        return
    if snapshot is None:
        current = _quarantine_anchor(anchor)
        if current is None:
            return
        if _anchor_is_session_owned(current, session_state_root):
            _discard_quarantined(current)
            return
        _republish_quarantined(anchor, current)
        return

    staged = _stage_anchor_snapshot(anchor, snapshot)
    try:
        current = _quarantine_anchor(anchor)
    except OSError as exc:
        raise RuntimeError(
            f"pre-session anchor retained at {staged}; "
            f"failed to quarantine current anchor {anchor}"
        ) from exc
    if current is None:
        _publish_staged_snapshot(anchor, staged)
        return
    if _anchor_is_session_owned(current, session_state_root):
        _discard_quarantined(current)
        _publish_staged_snapshot(anchor, staged)
        return

    try:
        _republish_quarantined(anchor, current)
    except RuntimeError as exc:
        raise RuntimeError(
            f"pre-session anchor retained at {staged}; {exc}"
        ) from exc
    raise RuntimeError(
        f"pre-session anchor retained at {staged}; refusing to overwrite "
        f"unrelated Git base anchor: {anchor}"
    )


@pytest.fixture(autouse=True, scope="session")
def _hermetic_external_base():
    """Keep the now-external default artifact base out of the developer's real state dir.

    Since the Phase-D flip, z_harness_base() defaults to an EXTERNAL location:
    XDG_STATE_HOME/z-harness/<repo-id>, falling back to ~/.local/state/z-harness.
    Any test that git-inits a tmp repo and runs a z-harness script therefore
    writes into the developer's REAL ~/.local/state/z-harness unless it pins
    Z_HARNESS_BASE_DIR — polluting that dir and letting event-emission
    assertions pass vacuously (the file lands somewhere the test never reads).

    Point XDG_STATE_HOME at a throwaway dir for the whole session so any test
    that does not explicitly set Z_HARNESS_BASE_DIR (tier 1, which still wins)
    stays hermetic.
    """
    prior = os.environ.get("XDG_STATE_HOME")
    session_state_root = Path(tempfile.mkdtemp(prefix="zh-test-xdg-state-"))
    anchor = None
    snapshot = None
    anchor_prepared = False
    try:
        anchor = _git_base_anchor()
        snapshot = _snapshot_and_remove_anchor(anchor)
        anchor_prepared = True
        os.environ["XDG_STATE_HOME"] = str(session_state_root)
        yield
    finally:
        try:
            # Restore Git-visible state before deleting the path an anchor may name.
            if anchor_prepared:
                _restore_anchor_state(anchor, snapshot, session_state_root)
        finally:
            if prior is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = prior
            shutil.rmtree(session_state_root, ignore_errors=True)


def _live_daemon_pids() -> set[int]:
    proc = subprocess.run(
        ["pgrep", "-f", "zero_lock_under_hblock"],
        capture_output=True, text=True,
    )
    pids = set()
    for line in proc.stdout.split():
        try:
            pids.add(int(line))
        except ValueError:
            pass
    return pids


@pytest.fixture(autouse=True)
def _reap_leaked_lock_daemons():
    before = _live_daemon_pids()
    yield
    for pid in _live_daemon_pids() - before:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
