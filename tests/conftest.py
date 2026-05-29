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
import signal
import subprocess

import pytest


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
