"""Shared fixtures for the runtime test suite.

Since the Phase-D flip, z_harness_base() defaults to an EXTERNAL location
(XDG_STATE_HOME/z-harness/<repo-id>, then ~/.local/state/...). Tests that invoke
log-event.sh (e.g. test_compat.py's log_event tests) and read the emitted
events.jsonl back from a known path would otherwise see their events land in the
developer's real external state dir instead — failing, and polluting that dir.

Pin Z_HARNESS_BASE_DIR (tier 1, absolute) to a throwaway dir per test so emitted
artifacts stay hermetic and the tests can read them back from <base>/archive/...
"""

import os
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _hermetic_artifact_base(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="zh-runtime-test-base-")
    monkeypatch.setenv("Z_HARNESS_BASE_DIR", tmp)
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
