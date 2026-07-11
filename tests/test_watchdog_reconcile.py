"""Tests for runtime/watchdog/reconcile.py (child-terminal + startup orphan
detection).

Coverage (T014 acceptance, criteria #7/#8):
- ``reconcile_children``: killing one of three children's tmux target marks
  only that child ``failed`` while the other two are unaffected and
  evaluation completes;
- ``reconcile_children``: once every child reaches a terminal state (and the
  origin is ``awaiting_children``), exactly one reconciliation-nudge payload
  is built and exactly one failed-child alert dispatch occurs (mocked);
- ``reconcile_children``: the payload does NOT fire when the origin is not in
  ``awaiting_children``, even if every child is already terminal (the
  natural once-marker gate) — the caller consuming a fired payload and
  transitioning the origin out of ``awaiting_children`` is what prevents a
  duplicate fire on a later poll;
- ``reconcile_children``: a hung liveness check on one child does not raise
  out of the batch and does not block evaluating the remaining children;
- ``startup_reconcile``: a record with a dead tmux target is marked
  ``orphaned`` exactly once across two consecutive calls (no duplicate alert
  on the second call);
- ``startup_reconcile``: a record whose tmux target is still alive is left
  untouched.

Tests never touch a real tmux pane or a real Discord webhook (STYLE.md:T-004
— hermetic): ``has_session``/``send_alerts``/``format_payload``/``alert_fn``
are all fakes injected per the module's dependency-injection seam.
"""

from __future__ import annotations

import pytest

from runtime.watchdog import notify, reconcile, registry, tmux_actuator

NOW = "2026-07-10T12:00:00Z"


def _record(*, state: str, tmux_target: str = "zw-x-aaaa1111") -> dict:
    rec = registry.new_session_record(
        "session-watchdog",
        "/plans/session-watchdog",
        "claude",
        tmux_target,
        "/tmp/transcript.jsonl",
        now=NOW,
    )
    rec["state"] = state
    return rec


class _FakeHasSession:
    """Fake ``tmux_actuator.has_session``: alive unless ``target`` is in
    ``dead`` or ``hangs``; a target in ``hangs`` raises ``TmuxTimeoutError``
    instead of returning a bool."""

    def __init__(self, dead: set[str] = frozenset(), hangs: set[str] = frozenset()) -> None:
        self.dead = set(dead)
        self.hangs = set(hangs)
        self.calls: list[str] = []

    def __call__(self, target: str, *, timeout: float) -> bool:
        self.calls.append(target)
        if target in self.hangs:
            raise tmux_actuator.TmuxTimeoutError(f"hung: {target}")
        return target not in self.dead


class _RecordingFormatPayload:
    """Spy wrapping the real ``notify.format_reconciliation_payload``."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, root_slug, children):
        self.calls += 1
        return notify.format_reconciliation_payload(root_slug, children)


class _RecordingSendAlerts:
    """Fake ``notify.send_reconciliation_alerts`` stand-in that records every
    call without touching a real webhook."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, payload, **kwargs) -> int:
        self.calls.append(payload)
        return len(payload.get("failed_entries", []))


class _RecordingAlertFn:
    """Fake ``notify.send_discord_alert`` stand-in that records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str, body: str, **kwargs) -> bool:
        self.calls.append((title, body))
        return True


# ── reconcile_children: only the dead child is affected ─────────────────────

def test_dead_child_marks_only_that_child_failed_others_unaffected() -> None:
    c1 = _record(state="running", tmux_target="zw-a-1")
    c2 = _record(state="running", tmux_target="zw-a-2")  # this one dies
    c3 = _record(state="running", tmux_target="zw-a-3")
    origin = {
        "session_id": "ws-origin",
        "slug": "session-watchdog",
        "state": "awaiting_children",
        "children": [c1["session_id"], c2["session_id"], c3["session_id"]],
    }
    records = {c1["session_id"]: c1, c2["session_id"]: c2, c3["session_id"]: c3}
    has_session = _FakeHasSession(dead={"zw-a-2"})

    result = reconcile.reconcile_children(origin, records, has_session=has_session, now=NOW)

    updated = result["records"]
    assert updated[c1["session_id"]]["state"] == "running"  # unaffected
    assert updated[c2["session_id"]]["state"] == "failed"  # marked failed
    assert updated[c3["session_id"]]["state"] == "running"  # unaffected
    # every child's target was checked — evaluation completed for all three
    assert set(has_session.calls) == {"zw-a-1", "zw-a-2", "zw-a-3"}
    # c1/c3 are still running: not every child is terminal yet
    assert result["payload"] is None


def test_all_children_terminal_fires_exactly_one_payload_and_alert() -> None:
    c1 = _record(state="done", tmux_target="zw-b-1")
    c2 = _record(state="done", tmux_target="zw-b-2")
    c3 = _record(state="running", tmux_target="zw-b-3")  # dies this cycle
    origin = {
        "session_id": "ws-origin",
        "slug": "session-watchdog",
        "state": "awaiting_children",
        "children": [c1["session_id"], c2["session_id"], c3["session_id"]],
    }
    records = {c1["session_id"]: c1, c2["session_id"]: c2, c3["session_id"]: c3}
    has_session = _FakeHasSession(dead={"zw-b-3"})
    format_payload = _RecordingFormatPayload()
    send_alerts = _RecordingSendAlerts()

    result = reconcile.reconcile_children(
        origin,
        records,
        has_session=has_session,
        format_payload=format_payload,
        send_alerts=send_alerts,
        now=NOW,
    )

    assert result["records"][c3["session_id"]]["state"] == "failed"
    assert format_payload.calls == 1  # exactly one reconciliation-nudge dispatch
    assert len(send_alerts.calls) == 1  # exactly one failed-child alert dispatch
    payload = result["payload"]
    assert payload is not None
    assert len(payload["entries"]) == 3
    assert len(payload["failed_entries"]) == 1
    assert payload["failed_entries"][0]["session_id"] == c3["session_id"]


def test_no_payload_when_origin_not_awaiting_children_even_if_all_terminal() -> None:
    """The natural once-marker gate: without the origin being
    ``awaiting_children``, an all-terminal child set must not fire a
    payload/alert — this is what lets the caller prevent a duplicate fire by
    transitioning the origin out of ``awaiting_children`` after consuming a
    payload."""
    c1 = _record(state="done", tmux_target="zw-c-1")
    c2 = _record(state="failed", tmux_target="zw-c-2")
    origin = {
        "session_id": "ws-origin",
        "slug": "session-watchdog",
        "state": "running",  # NOT awaiting_children
        "children": [c1["session_id"], c2["session_id"]],
    }
    records = {c1["session_id"]: c1, c2["session_id"]: c2}
    format_payload = _RecordingFormatPayload()
    send_alerts = _RecordingSendAlerts()

    result = reconcile.reconcile_children(
        origin,
        records,
        has_session=_FakeHasSession(),
        format_payload=format_payload,
        send_alerts=send_alerts,
        now=NOW,
    )

    assert result["payload"] is None
    assert format_payload.calls == 0
    assert send_alerts.calls == []


def test_hung_liveness_check_on_one_child_does_not_block_the_others() -> None:
    c1 = _record(state="running", tmux_target="zw-d-1")  # hangs
    c2 = _record(state="running", tmux_target="zw-d-2")  # dies
    origin = {
        "session_id": "ws-origin",
        "slug": "session-watchdog",
        "state": "awaiting_children",
        "children": [c1["session_id"], c2["session_id"]],
    }
    records = {c1["session_id"]: c1, c2["session_id"]: c2}
    has_session = _FakeHasSession(dead={"zw-d-2"}, hangs={"zw-d-1"})

    result = reconcile.reconcile_children(origin, records, has_session=has_session, now=NOW)

    # c1's hung check is skipped (record untouched, retried next cycle); c2
    # is still evaluated and marked failed — one child's failure never
    # crashes or halts the batch.
    assert result["records"][c1["session_id"]]["state"] == "running"
    assert result["records"][c2["session_id"]]["state"] == "failed"


# ── startup_reconcile: orphan exactly once across two calls ─────────────────

def test_dead_target_marked_orphaned_exactly_once_across_two_calls() -> None:
    rec = _record(state="running", tmux_target="zw-e-1")
    records = {rec["session_id"]: rec}
    has_session = _FakeHasSession(dead={"zw-e-1"})
    alert_fn = _RecordingAlertFn()

    first = reconcile.startup_reconcile(
        records, has_session=has_session, alert_fn=alert_fn, now=NOW
    )
    assert first[rec["session_id"]]["state"] == "orphaned"
    assert len(alert_fn.calls) == 1

    second = reconcile.startup_reconcile(
        first, has_session=has_session, alert_fn=alert_fn, now=NOW
    )
    assert second[rec["session_id"]]["state"] == "orphaned"
    # no duplicate alert on the second call
    assert len(alert_fn.calls) == 1


def test_live_target_is_left_untouched() -> None:
    rec = _record(state="running", tmux_target="zw-f-1")
    records = {rec["session_id"]: rec}
    has_session = _FakeHasSession()  # nothing dead
    alert_fn = _RecordingAlertFn()

    result = reconcile.startup_reconcile(
        records, has_session=has_session, alert_fn=alert_fn, now=NOW
    )

    assert result[rec["session_id"]]["state"] == "running"
    assert alert_fn.calls == []


def test_fanout_child_with_empty_transcript_path_is_handled_normally() -> None:
    """T013 note: fanout children are registered with transcript_path=""; this
    module must not assume a non-empty transcript_path anywhere."""
    rec = registry.new_session_record(
        "session-watchdog/cluster-a",
        "/plans/session-watchdog/cluster-a",
        "claude",
        "zw-g-1",
        "",  # transcript_path unknown at spawn time
        now=NOW,
    )
    records = {rec["session_id"]: rec}
    has_session = _FakeHasSession(dead={"zw-g-1"})
    alert_fn = _RecordingAlertFn()

    result = reconcile.startup_reconcile(
        records, has_session=has_session, alert_fn=alert_fn, now=NOW
    )

    assert result[rec["session_id"]]["state"] == "orphaned"
    assert len(alert_fn.calls) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
