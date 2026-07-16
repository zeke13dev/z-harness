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
- ``run_poll_pass`` (T019, criterion #1): resolves every ``watchdog.*`` knob
  exactly once, dispatches the injected ``poll_session`` exactly once per
  non-terminal session with the record's captured pane, skips a terminal-state
  record outright (no capture/dispatch), and skips (without crashing the
  pass) a session whose pane capture raises ``TmuxActuationError``/
  ``TmuxTimeoutError``.

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

from runtime.watchdog import daemon, notify, registry, tmux_actuator


def test_daemon_exports_only_deterministic_lifecycle_actions() -> None:
    assert daemon.DETERMINISTIC_ACTION_ALLOWLIST == frozenset({
        "clear", "coordinator_wake", "escalation", "handoff", "nudge",
    })
    assert "judge" not in daemon.DETERMINISTIC_ACTION_ALLOWLIST
    assert "reconcile_semantics" not in daemon.DETERMINISTIC_ACTION_ALLOWLIST


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


def test_touch_heartbeat_persists_one_incarnation_across_readiness_updates(
    tmp_path: Path,
) -> None:
    heartbeat = tmp_path / "heartbeat"
    incarnation_id = daemon.new_incarnation_id()

    daemon.touch_heartbeat(heartbeat, incarnation_id)
    daemon.touch_heartbeat(heartbeat, incarnation_id)

    assert daemon.read_incarnation_id(heartbeat) == incarnation_id


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


# ── run_poll_pass ────────────────────────────────────────────────────────────

class _RecordingCall:
    """Records every positional/keyword invocation and returns a canned value
    (or invokes an injected side-effect callable) per call."""

    def __init__(self, ret=None, side_effect=None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self._ret = ret
        self._side_effect = side_effect

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._side_effect is not None:
            return self._side_effect(*args, **kwargs)
        return self._ret


def _poll_pass_fixture(tmp_path: Path) -> tuple[Path, dict, dict]:
    """Write a two-record (both ``running``) registry; return (path, live, live2)."""
    registry_path = tmp_path / "sessions.json"
    live = registry.new_session_record(
        slug="alpha", plan_dir="/p", host="claude",
        tmux_target="zw-alpha-1", transcript_path="/t-alpha.jsonl",
    )
    live = registry.transition(live, "running")
    live2 = registry.new_session_record(
        slug="beta", plan_dir="/p", host="codex",
        tmux_target="zw-beta-1", transcript_path="/t-beta.jsonl",
    )
    live2 = registry.transition(live2, "running")
    sessions = {live["session_id"]: live, live2["session_id"]: live2}
    registry.write_registry(registry_path, sessions)
    return registry_path, live, live2


def _fake_poll_session(record, sessions, **kwargs):
    """Fake ``poll.poll_session``: leaves the mapping untouched, returns it."""
    updated = dict(sessions)
    updated[record["session_id"]] = record
    return {"sessions": updated}


def test_run_poll_pass_dispatches_poll_session_once_per_non_terminal_session(
    tmp_path: Path,
) -> None:
    registry_path, live, live2 = _poll_pass_fixture(tmp_path)
    sessions = registry.read_registry(registry_path)

    capture_pane = _RecordingCall(ret="pane text")
    poll_session = _RecordingCall(side_effect=_fake_poll_session)
    get_config_int = _RecordingCall(ret=1)
    adapter_calls: list[str] = []

    def adapter_for_host(host: str):
        adapter_calls.append(host)
        return object()

    daemon.run_poll_pass(
        sessions,
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=adapter_for_host,
        get_config_int=get_config_int,
        capture_pane=capture_pane,
        poll_session=poll_session,
    )

    assert len(poll_session.calls) == 2
    dispatched_ids = {call[0][0]["session_id"] for call in poll_session.calls}
    assert dispatched_ids == {live["session_id"], live2["session_id"]}
    assert sorted(adapter_calls) == ["claude", "codex"]
    captured_targets = {call[0][0] for call in capture_pane.calls}
    assert captured_targets == {"zw-alpha-1", "zw-beta-1"}


def test_run_poll_pass_resolves_every_knob_exactly_once(tmp_path: Path) -> None:
    registry_path, _live, _live2 = _poll_pass_fixture(tmp_path)
    sessions = registry.read_registry(registry_path)

    get_config_int = _RecordingCall(ret=1)

    daemon.run_poll_pass(
        sessions,
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=lambda host: object(),
        get_config_int=get_config_int,
        capture_pane=lambda target, **kwargs: "pane text",
        poll_session=_fake_poll_session,
    )

    resolved_keys = [call[0][0] for call in get_config_int.calls]
    assert sorted(resolved_keys) == sorted(
        [
            "watchdog.context_threshold_pct",
            "watchdog.context_window_tokens",
            "watchdog.stuck_after_s",
            "watchdog.nudge_max",
            "watchdog.judge_timeout_s",
            "watchdog.signals_max_mb",
        ]
    )
    # Exactly once each — no per-session re-resolution.
    assert len(resolved_keys) == len(set(resolved_keys)) == 6


def test_run_poll_pass_skips_terminal_state_session(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    done = registry.new_session_record(
        slug="gamma", plan_dir="/p", host="claude",
        tmux_target="zw-gamma-1", transcript_path="/t-gamma.jsonl",
    )
    done = registry.transition(done, "orphaned")
    sessions = {done["session_id"]: done}
    registry.write_registry(registry_path, sessions)

    capture_pane = _RecordingCall(ret="pane text")
    poll_session = _RecordingCall(side_effect=_fake_poll_session)

    result = daemon.run_poll_pass(
        sessions,
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=lambda host: object(),
        get_config_int=lambda key: 1,
        capture_pane=capture_pane,
        poll_session=poll_session,
    )

    assert capture_pane.calls == []
    assert poll_session.calls == []
    assert result == sessions


def test_run_poll_pass_skips_session_on_capture_pane_failure(tmp_path: Path) -> None:
    """A dead/hung pane for one session must not block dispatching the other."""
    registry_path, live, live2 = _poll_pass_fixture(tmp_path)
    sessions = registry.read_registry(registry_path)

    def flaky_capture_pane(target, **kwargs):
        if target == live["tmux_target"]:
            raise tmux_actuator.TmuxActuationError("no such pane")
        return "pane text"

    poll_session = _RecordingCall(side_effect=_fake_poll_session)

    daemon.run_poll_pass(
        sessions,
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=lambda host: object(),
        get_config_int=lambda key: 1,
        capture_pane=flaky_capture_pane,
        poll_session=poll_session,
    )

    assert len(poll_session.calls) == 1
    assert poll_session.calls[0][0][0]["session_id"] == live2["session_id"]


def test_intervention_notification_failure_occurs_after_durable_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path, live, _live2 = _poll_pass_fixture(tmp_path)
    sessions = {live["session_id"]: live}
    registry.write_registry(registry_path, sessions)
    monkeypatch.setattr(tmux_actuator, "submit_text", lambda target, text: True)
    observed: list[str] = []

    def lifecycle_notify(event):
        markers = registry.read_registry_document(registry_path)["action_markers"]
        assert markers
        assert next(iter(markers.values()))["status"] == "completed"
        observed.append(event.event_id)
        return notify.DeliveryResult(
            status="failed",
            event_id=event.event_id,
            delivery_class=event.delivery_class,
        )

    def dispatching_poll(record, current, *, dispatch_action, **_kwargs):
        dispatched = dispatch_action(
            registry_path,
            session_id=record["session_id"],
            action="nudge",
            generation=record["last_seen"],
            attempt=1,
            max_attempts=1,
            target=record["tmux_target"],
            text=tmux_actuator.NUDGE_TEXT,
            host_ready=True,
        )
        assert dispatched["status"] == "completed"
        assert dispatched["notification"].status == "failed"
        return {"sessions": current}

    result = daemon.run_poll_pass(
        sessions,
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=lambda host: object(),
        get_config_int=lambda key: 1,
        capture_pane=lambda target: "ready",
        poll_session=dispatching_poll,
        lifecycle_notify=lifecycle_notify,
    )

    assert observed
    assert result[live["session_id"]]["state"] == "running"
    marker = next(iter(registry.read_registry_document(registry_path)["action_markers"].values()))
    assert marker["notification_status"] == "failed"
    signal = json.loads((tmp_path / "signals.jsonl").read_text(encoding="utf-8"))
    assert signal["kind"] == "lifecycle_notification_delivery"
    assert signal["payload"]["status"] == "failed"


def test_completed_marker_replay_does_not_redeliver_intervention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path, live, _live2 = _poll_pass_fixture(tmp_path)
    sessions = {live["session_id"]: live}
    registry.write_registry(registry_path, sessions)
    monkeypatch.setattr(tmux_actuator, "submit_text", lambda target, text: True)
    delivered: list[str] = []

    def lifecycle_notify(event):
        delivered.append(event.event_id)
        return notify.DeliveryResult(
            status="delivered",
            event_id=event.event_id,
            delivery_class=event.delivery_class,
        )

    def replaying_poll(record, current, *, dispatch_action, **_kwargs):
        request = {
            "session_id": record["session_id"],
            "action": "nudge",
            "generation": record["last_seen"],
            "attempt": 1,
            "max_attempts": 1,
            "target": record["tmux_target"],
            "text": tmux_actuator.NUDGE_TEXT,
            "host_ready": True,
        }
        first = dispatch_action(registry_path, **request)
        replay = dispatch_action(registry_path, **request)
        assert "notification" in first
        assert "notification" not in replay
        return {"sessions": current}

    daemon.run_poll_pass(
        sessions,
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=lambda host: object(),
        get_config_int=lambda key: 1,
        capture_pane=lambda target: "ready",
        poll_session=replaying_poll,
        lifecycle_notify=lifecycle_notify,
    )

    assert len(delivered) == 1


def test_poll_pass_retries_durable_wake_notification_with_stable_id(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "sessions.json"
    registry.write_registry(registry_path, {})
    action_id = "wake-action-retry"

    def _seed(document):
        document["action_markers"][action_id] = {
            "registry_version": registry.REGISTRY_VERSION,
            "action": "coordinator_wake",
            "session_id": "coordinator-1",
            "generation": "generation-1",
            "attempt": 1,
            "status": "completed",
            "created_at": "2026-01-01T00:00:00Z",
        }

    registry.locked_registry_document_update(registry_path, _seed)
    event = notify.lifecycle_notification(
        "coordinator_wake", {"action_id": action_id}, "wake", "first"
    )
    assert notify.claim_action_notification(registry_path, action_id, event)
    notify.finish_action_notification(
        registry_path,
        action_id,
        notify.DeliveryResult("failed", event.event_id, notify.RETRYABLE),
    )
    seen: list[str] = []

    def delivered(retry_event):
        seen.append(retry_event.event_id)
        return notify.DeliveryResult(
            "delivered", retry_event.event_id, retry_event.delivery_class
        )

    daemon.run_poll_pass(
        {},
        registry_path=registry_path,
        signals_path=tmp_path / "signals.jsonl",
        repo_root=tmp_path,
        adapter_for_host=lambda host: object(),
        get_config_int=lambda key: 1,
        lifecycle_notify=delivered,
    )

    marker = registry.read_registry_document(registry_path)["action_markers"][action_id]
    assert seen == [event.event_id]
    assert marker["notification_status"] == "delivered"
    assert marker["notification_attempts"] == 2


def test_pending_join_wake_retries_across_passes_until_generation_fenced_ack(
    tmp_path: Path,
) -> None:
    """Criterion #6: host delivery is at least once while logical ack is once."""
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    parent = registry.new_session_record(
        "root", "/plans/root", "claude", "zw-root", "",
        session_id="ws-root", now="2026-07-14T10:00:00Z",
    )
    parent = registry.transition(parent, "awaiting_children", now="2026-07-14T10:01:00Z")
    child = registry.new_session_record(
        "child", "/plans/child", "claude", "zw-child", "",
        session_id="ws-child", parent_id="ws-root", report_capability="cap",
        now="2026-07-14T10:00:00Z",
    )
    child = registry.transition(child, "running", now="2026-07-14T10:00:01Z")
    parent["children"] = ["ws-child"]
    registry.write_registry(registry_path, {"ws-root": parent, "ws-child": child})
    registry.locked_registry_update(registry_path, lambda _sessions: None)
    registry.seal_group(registry_path, registry.group_id_for("ws-root"))
    registry.report_child_outcome(
        registry_path, child_id="ws-child", generation=registry.child_generation(child),
        reporter_id="ws-child", report_capability="cap", state="failed",
        evidence={"reason": "test"},
    )
    outbox = next(iter(registry.read_registry_document(registry_path)["outbox"].values()))
    calls: list[str] = []

    def dispatch(_path, **kwargs):
        calls.append(kwargs["text"])
        if len(calls) == 1:
            raise tmux_actuator.TmuxTimeoutError("delivery outcome unknown")
        return {"status": "completed", "action_id": "action-2", "attempt": 2}

    disabled = notify.DeliveryResult(
        status="disabled", event_id="ignored", delivery_class=notify.RETRYABLE,
    )
    first_results = daemon.deliver_pending_join_wakes(
        registry_path, signals_path, max_mb=1, dispatch_action=dispatch,
        lifecycle_notify=lambda _event: disabled,
    )
    daemon.deliver_pending_join_wakes(
        registry_path, signals_path, max_mb=1, dispatch_action=dispatch,
        lifecycle_notify=lambda _event: disabled,
    )
    durable = registry.read_registry_document(registry_path)["outbox"][outbox["outbox_id"]]
    assert first_results[0]["status"] == "paused"
    assert len(calls) == 2 and calls[0] == calls[1] == outbox["text"]
    assert durable["delivery_attempts"] == 2

    registry.acknowledge_join_wake(
        registry_path, outbox["outbox_id"],
        coordinator_generation=outbox["coordinator_generation"],
    )
    daemon.deliver_pending_join_wakes(
        registry_path, signals_path, max_mb=1, dispatch_action=dispatch,
        lifecycle_notify=lambda _event: disabled,
    )
    assert len(calls) == 2


def test_pending_join_wake_escalates_at_stable_configured_attempt_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wake retries inject at least once, then exhaust one stable cap."""
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    parent = registry.new_session_record(
        "root", "/plans/root", "claude", "zw-root", "",
        session_id="ws-root", now="2026-07-14T10:00:00Z",
    )
    parent = registry.transition(parent, "awaiting_children", now="2026-07-14T10:01:00Z")
    child = registry.new_session_record(
        "child", "/plans/child", "claude", "zw-child", "",
        session_id="ws-child", parent_id="ws-root", report_capability="cap",
        now="2026-07-14T10:00:00Z",
    )
    child = registry.transition(child, "running", now="2026-07-14T10:00:01Z")
    parent["children"] = ["ws-child"]
    registry.write_registry(registry_path, {"ws-root": parent, "ws-child": child})
    registry.locked_registry_update(registry_path, lambda _sessions: None)
    registry.seal_group(registry_path, registry.group_id_for("ws-root"))
    registry.report_child_outcome(
        registry_path, child_id="ws-child", generation=registry.child_generation(child),
        reporter_id="ws-child", report_capability="cap", state="failed",
        evidence={"reason": "test"},
    )
    outbox = next(iter(registry.read_registry_document(registry_path)["outbox"].values()))
    monkeypatch.setattr(tmux_actuator, "submit_text", lambda _target, _text: False)
    disabled = notify.DeliveryResult(
        status="disabled", event_id="ignored", delivery_class=notify.RETRYABLE,
    )

    first = daemon.deliver_pending_join_wakes(
        registry_path, signals_path, max_mb=1, max_attempts=2,
        lifecycle_notify=lambda _event: disabled,
    )
    second = daemon.deliver_pending_join_wakes(
        registry_path, signals_path, max_mb=1, max_attempts=2,
        lifecycle_notify=lambda _event: disabled,
    )
    exhausted = daemon.deliver_pending_join_wakes(
        registry_path, signals_path, max_mb=1, max_attempts=2,
        lifecycle_notify=lambda _event: disabled,
    )

    assert [first[0]["status"], second[0]["status"], exhausted[0]["status"]] == [
        "failed", "escalated", "escalated",
    ]
    assert [first[0]["attempt"], second[0]["attempt"], exhausted[0]["attempt"]] == [
        1, 2, 3,
    ]
    document = registry.read_registry_document(registry_path)
    marker_statuses = [
        marker["status"] for marker in document["action_markers"].values()
        if marker["session_id"] == "ws-root"
    ]
    assert marker_statuses.count("failed") == 2
    assert marker_statuses.count("escalated") == 1
    assert document["outbox"][outbox["outbox_id"]]["delivery_attempts"] == 3
