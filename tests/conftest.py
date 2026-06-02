"""Shared pytest fixtures for the follow-up-sink test suite.

The sink's per-entry / global lock is held by a background daemon (forked by
`sink-lock.sh acquire`) that blocks in `signal.pause()` until released or
signalled. Tests that exercise the acquire path — directly or via
`sink-claim.sh` / `sink-status-set.sh` — and leave a holder alive (contention,
takeover, or simply not releasing in a negative-path assertion) would otherwise
leak that daemon past the test. Accumulated leaks destabilise later lock tests
(a stale holder changes acquire/takeover outcomes) and bloat the process table.

This autouse fixture SIGTERMs any daemon spawned during each test.
"""

import os
import shutil
import signal
import subprocess
import tempfile

import pytest


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
    tmp = tempfile.mkdtemp(prefix="zh-test-xdg-state-")
    os.environ["XDG_STATE_HOME"] = tmp
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("XDG_STATE_HOME", None)
        else:
            os.environ["XDG_STATE_HOME"] = prior
        shutil.rmtree(tmp, ignore_errors=True)


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
