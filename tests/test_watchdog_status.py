"""Tests for runtime/watchdog/status.py (T018, criterion #1).

Coverage:
- ``compute_status`` reads a fixture registry with multiple sessions across
  several states and surfaces ``session_id``/``slug``/``host``/``state``/
  ``tmux_target`` for each;
- heartbeat age is computed deterministically against an injected ``now``
  when the heartbeat file is present, and is ``None`` when absent;
- a missing registry file never raises — it degrades to
  ``{"sessions": [], "heartbeat_age_s": None}`` (when the heartbeat file is
  also absent).

Tests are hermetic (STYLE.md:T-004): all filesystem effects go under
pytest's ``tmp_path`` fixture.
"""

from __future__ import annotations

from pathlib import Path

from runtime.watchdog import registry, status


def _fixture_registry(registry_path: Path) -> dict[str, dict]:
    """Write a registry with sessions spanning several lifecycle states."""
    running = registry.new_session_record(
        slug="alpha", plan_dir="/p/alpha", host="claude",
        tmux_target="zw-alpha-1", transcript_path="/t-alpha.jsonl",
    )
    running = registry.transition(running, "running")

    needs_input = registry.new_session_record(
        slug="beta", plan_dir="/p/beta", host="codex",
        tmux_target="zw-beta-1", transcript_path="/t-beta.jsonl",
    )
    needs_input = registry.transition(needs_input, "needs_input")

    orphaned = registry.new_session_record(
        slug="gamma", plan_dir="/p/gamma", host="omp",
        tmux_target="zw-gamma-1", transcript_path="/t-gamma.jsonl",
    )
    orphaned = registry.transition(orphaned, "orphaned")

    sessions = {
        running["session_id"]: running,
        needs_input["session_id"]: needs_input,
        orphaned["session_id"]: orphaned,
    }
    registry.write_registry(registry_path, sessions)
    return sessions


def test_compute_status_reports_sessions_across_states(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    heartbeat_path = tmp_path / "heartbeat"
    fixture = _fixture_registry(registry_path)
    heartbeat_path.write_text("", encoding="utf-8")

    result = status.compute_status(registry_path, heartbeat_path, now=lambda: 0.0)

    assert len(result["sessions"]) == 3
    by_id = {entry["session_id"]: entry for entry in result["sessions"]}
    for session_id, record in fixture.items():
        entry = by_id[session_id]
        assert entry["slug"] == record["slug"]
        assert entry["host"] == record["host"]
        assert entry["state"] == record["state"]
        assert entry["tmux_target"] == record["tmux_target"]

    states = {entry["state"] for entry in result["sessions"]}
    assert states == {"running", "needs_input", "orphaned"}


def test_compute_status_heartbeat_age_present_file_deterministic(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "sessions.json"
    registry.write_registry(registry_path, {})
    heartbeat_path = tmp_path / "heartbeat"
    heartbeat_path.write_text("", encoding="utf-8")

    mtime = heartbeat_path.stat().st_mtime
    fake_now = mtime + 42.5

    result = status.compute_status(
        registry_path, heartbeat_path, now=lambda: fake_now
    )

    assert result["heartbeat_age_s"] == 42.5


def test_compute_status_heartbeat_age_none_when_file_absent(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    registry.write_registry(registry_path, {})
    heartbeat_path = tmp_path / "heartbeat-does-not-exist"

    result = status.compute_status(registry_path, heartbeat_path, now=lambda: 100.0)

    assert result["heartbeat_age_s"] is None
    assert result["sessions"] == []


def test_compute_status_missing_registry_never_raises(tmp_path: Path) -> None:
    registry_path = tmp_path / "does-not-exist" / "sessions.json"
    heartbeat_path = tmp_path / "heartbeat-also-absent"

    result = status.compute_status(registry_path, heartbeat_path)

    assert result == {"sessions": [], "heartbeat_age_s": None}


def test_compute_status_missing_registry_with_present_heartbeat(
    tmp_path: Path,
) -> None:
    """A missing registry combined with a present heartbeat still degrades
    gracefully on the registry side while reporting a real heartbeat age."""
    registry_path = tmp_path / "does-not-exist" / "sessions.json"
    heartbeat_path = tmp_path / "heartbeat"
    heartbeat_path.write_text("", encoding="utf-8")
    mtime = heartbeat_path.stat().st_mtime

    result = status.compute_status(
        registry_path, heartbeat_path, now=lambda: mtime + 5.0
    )

    assert result["sessions"] == []
    assert result["heartbeat_age_s"] == 5.0
