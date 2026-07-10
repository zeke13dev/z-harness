"""Tests for runtime/watchdog/daemon.py (T015, criterion #9).

Coverage:
- the registered SIGTERM handler, invoked directly, flushes whatever the
  CURRENT in-memory sessions mapping is at call time (not a stale snapshot
  captured at installation time) and never exits without flushing first;
- ``touch_heartbeat`` advances the target file's mtime;
- ``run_lifecycle`` raises ``DaemonAlreadyRunningError`` on a second
  concurrent acquire attempt and cleanly releases the lock on exit, including
  when the wrapped body raises;
- ``run_startup_reconcile`` (T017, criteria #8/#9): a dead-target record is
  orphaned exactly once (alerted once) and never re-alerted on a second call;
  a stale lock naming a dead pid is acquired successfully; every
  ``has_session`` call is passed an explicit timeout.

Tests are hermetic (STYLE.md:T-004): all filesystem effects go under
pytest's ``tmp_path`` fixture. An autouse fixture restores the process's real
SIGTERM disposition after every test, since ``install_sigterm_handler`` calls
``signal.signal`` for real (STYLE.md:P-006 concurrency-assumption discipline
applied to global process state, not just files).
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime.watchdog import daemon, registry


@pytest.fixture(autouse=True)
def _restore_sigterm_disposition():
    """Restore the process's original SIGTERM handler after each test."""
    original = signal.getsignal(signal.SIGTERM)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, original)


# ── SIGTERM handler ───────────────────────────────────────────────────────────

def test_sigterm_handler_flushes_current_sessions_and_exits(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    sessions: dict[str, dict] = {}
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="zw-s-1", transcript_path="/t.jsonl",
    )
    sessions[record["session_id"]] = record

    handler = daemon.install_sigterm_handler(lambda: sessions, registry_path)
    assert signal.getsignal(signal.SIGTERM) is handler

    with pytest.raises(SystemExit) as exc_info:
        handler(signal.SIGTERM, None)
    assert exc_info.value.code == 0

    written = registry.read_registry(registry_path)
    assert written == sessions
    raw = json.loads(registry_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == registry.SCHEMA_VERSION


def test_sigterm_handler_flushes_current_mapping_not_install_time_snapshot(
    tmp_path: Path,
) -> None:
    """Mutating the mapping AFTER install must still be reflected at flush time."""
    registry_path = tmp_path / "sessions.json"
    sessions: dict[str, dict] = {}

    handler = daemon.install_sigterm_handler(lambda: sessions, registry_path)

    # Mutate the mapping only after installation — proves the handler reads
    # the live closure, not a copy taken when install_sigterm_handler ran.
    record = registry.new_session_record(
        slug="late", plan_dir="/p", host="omp",
        tmux_target="zw-late-1", transcript_path="/t.jsonl",
    )
    sessions[record["session_id"]] = record

    with pytest.raises(SystemExit):
        handler(signal.SIGTERM, None)

    written = registry.read_registry(registry_path)
    assert record["session_id"] in written
    assert written[record["session_id"]] == record


def test_sigterm_handler_propagates_flush_failure_without_exiting(
    tmp_path: Path,
) -> None:
    """A hard-fail flush error must surface, never be swallowed to allow exit."""
    registry_path = tmp_path / "sessions.json"
    bad_record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
    )
    bad_record["state"] = "not_a_valid_state"  # fails validate_record
    sessions = {bad_record["session_id"]: bad_record}

    handler = daemon.install_sigterm_handler(lambda: sessions, registry_path)

    with pytest.raises(ValueError):
        handler(signal.SIGTERM, None)
    # No partial/garbage file left behind by the failed write, and the
    # process did not proceed to sys.exit (a ValueError was raised instead
    # of SystemExit).
    assert not registry_path.exists()


# ── touch_heartbeat ────────────────────────────────────────────────────────────

def test_touch_heartbeat_creates_file_and_advances_mtime(tmp_path: Path) -> None:
    heartbeat = tmp_path / "nested" / "heartbeat"
    assert not heartbeat.exists()

    daemon.touch_heartbeat(heartbeat)
    assert heartbeat.exists()
    first_mtime = heartbeat.stat().st_mtime

    time.sleep(0.05)
    daemon.touch_heartbeat(heartbeat)
    second_mtime = heartbeat.stat().st_mtime

    assert second_mtime > first_mtime


# ── run_lifecycle ──────────────────────────────────────────────────────────────

def test_run_lifecycle_raises_on_second_concurrent_acquire_and_releases_cleanly(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "daemon.lock"

    with daemon.run_lifecycle(lock_path) as fd1:
        assert isinstance(fd1, int)
        with pytest.raises(registry.DaemonAlreadyRunningError):
            with daemon.run_lifecycle(lock_path):
                pass  # pragma: no cover - never reached

    # After the outer context exits, the lock is free again.
    with daemon.run_lifecycle(lock_path) as fd2:
        assert isinstance(fd2, int)


def test_run_lifecycle_releases_lock_even_when_body_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with daemon.run_lifecycle(lock_path):
            raise _Boom("body failed")

    # Lock was released on the exceptional exit path too.
    with daemon.run_lifecycle(lock_path):
        pass


# ── run_startup_reconcile ─────────────────────────────────────────────────────

def _dead_pid() -> int:
    """Return a pid guaranteed dead (a reaped child), for stale-lock tests."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _fixture_registry(registry_path: Path) -> tuple[dict, dict]:
    """Write a two-record registry: one live target, one dead target."""
    live = registry.new_session_record(
        slug="live", plan_dir="/p", host="claude",
        tmux_target="zw-live-1", transcript_path="/t-live.jsonl",
    )
    dead = registry.new_session_record(
        slug="dead", plan_dir="/p", host="claude",
        tmux_target="zw-dead-1", transcript_path="/t-dead.jsonl",
    )
    sessions = {live["session_id"]: live, dead["session_id"]: dead}
    registry.write_registry(registry_path, sessions)
    return live, dead


def test_run_startup_reconcile_orphans_dead_target_exactly_once(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    lock_path = tmp_path / "daemon.lock"
    live, dead = _fixture_registry(registry_path)

    calls: list[tuple[str, float]] = []

    def fake_has_session(target: str, *, timeout: float) -> bool:
        calls.append((target, timeout))
        return target == live["tmux_target"]

    alerts: list[tuple[str, str]] = []

    def fake_alert_fn(title: str, body: str) -> bool:
        alerts.append((title, body))
        return True

    updated = daemon.run_startup_reconcile(
        registry_path,
        lock_path,
        has_session=fake_has_session,
        alert_fn=fake_alert_fn,
        timeout=7.0,
    )

    # The dead record is orphaned; the live one is untouched (never
    # auto-adopted into a different lifecycle state).
    assert updated[dead["session_id"]]["state"] == "orphaned"
    assert updated[live["session_id"]]["state"] == registry.INITIAL_STATE
    assert len(alerts) == 1

    # Persisted to disk before returning.
    on_disk = registry.read_registry(registry_path)
    assert on_disk[dead["session_id"]]["state"] == "orphaned"

    # Every has_session call carried an explicit timeout.
    assert calls
    assert all(timeout == 7.0 for _target, timeout in calls)

    # Lock was released — a second acquire attempt succeeds.
    with daemon.run_lifecycle(lock_path):
        pass

    # A second reconcile pass over the now-orphaned record fires zero
    # additional alerts (terminal state skipped outright).
    updated_again = daemon.run_startup_reconcile(
        registry_path,
        lock_path,
        has_session=fake_has_session,
        alert_fn=fake_alert_fn,
        timeout=7.0,
    )
    assert updated_again[dead["session_id"]]["state"] == "orphaned"
    assert len(alerts) == 1  # unchanged


def test_run_startup_reconcile_acquires_stale_lock_from_dead_pid(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "sessions.json"
    lock_path = tmp_path / "daemon.lock"
    registry.write_registry(registry_path, {})
    # Simulate a crashed daemon: a pidfile naming a dead pid, no flock holder.
    lock_path.write_text(f"{_dead_pid()}\n", encoding="utf-8")

    updated = daemon.run_startup_reconcile(
        registry_path,
        lock_path,
        has_session=lambda target, *, timeout: True,
        alert_fn=lambda title, body: True,
    )
    assert updated == {}
