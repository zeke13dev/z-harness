"""Tests for runtime/watchdog/stuck.py (stuck-session detection + nudge escalation).

Coverage (T011 acceptance, criterion #4):
- a ``needs_input``-state record is NEVER nudged regardless of idle time (the
  D1 short-circuit binding obligation) — nor is an ``awaiting_children``
  record;
- a stuck record below ``nudge_max`` receives exactly one plain-text nudge
  (via the injected ``submit_fn``) and its ``nudge_count`` increments by
  exactly one;
- a record already at ``nudge_max`` receives exactly one Discord alert
  dispatch (via the injected ``alert_fn``) and no plain-text nudge is sent;
- two consecutive at-``nudge_max`` polls produce exactly ONE Discord alert
  total — the second poll sees the persisted ``nudge_count > nudge_max``
  marker (set by the first poll's returned record) and skips rather than
  re-alerting;
- a record whose idle time has not yet crossed ``stuck_after_s`` is skipped,
  including idle time exactly equal to ``stuck_after_s`` (the contract
  requires idle time to *exceed* the threshold, not merely meet it);
- a nudge-eligible record whose pane is not ``injection_ready`` is skipped
  (no submit call, no ``nudge_count`` mutation) rather than forcing the
  submit or falsely incrementing the count.

Tests never touch a real tmux pane or a real Discord webhook (STYLE.md:T-004
— hermetic): ``submit_fn``/``alert_fn``/``adapter`` are all fakes injected
per the module's dependency-injection seam.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.watchdog import registry, stuck

STUCK_AFTER_S = 300
NUDGE_MAX = 2


class _FakeAdapter:
    """Minimal ``HostAdapter`` stand-in; only ``injection_ready`` is exercised
    by ``stuck.py``."""

    host = "claude"

    def __init__(self, ready: bool = True) -> None:
        self._ready = ready

    def read_context(self, transcript_path, offset, *, window_tokens):  # pragma: no cover
        raise NotImplementedError

    def injection_ready(self, pane_text: str) -> bool:
        return self._ready

    def needs_input(self, pane_text: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def handoff_command(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def clear_command(self) -> str:  # pragma: no cover
        raise NotImplementedError


class _RecordingSubmit:
    """Fake ``tmux_actuator.submit_text`` stand-in that records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, target: str, text: str, **kwargs) -> None:
        self.calls.append((target, text))


class _RecordingAlert:
    """Fake ``notify.send_discord_alert`` stand-in that records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str, body: str, **kwargs) -> bool:
        self.calls.append((title, body))
        return True


def _record(*, state: str, idle_s: int, nudge_count: int, now: datetime) -> dict:
    rec = registry.new_session_record(
        "session-watchdog",
        "/plans/session-watchdog",
        "claude",
        "zw-session-watchdog-abcd1234",
        "/tmp/transcript.jsonl",
        now=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    rec["state"] = state
    rec["nudge_count"] = nudge_count
    last_seen = now - timedelta(seconds=idle_s)
    rec["last_seen"] = last_seen.strftime("%Y-%m-%dT%H:%M:%SZ")
    return rec


NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


def _evaluate(record: dict, *, ready: bool = True, submit=None, alert=None):
    submit_fn = submit if submit is not None else _RecordingSubmit()
    alert_fn = alert if alert is not None else _RecordingAlert()
    result = stuck.evaluate_stuck(
        record,
        NOW,
        pane_text="",
        adapter=_FakeAdapter(ready=ready),
        stuck_after_s=STUCK_AFTER_S,
        nudge_max=NUDGE_MAX,
        submit_fn=submit_fn,
        alert_fn=alert_fn,
    )
    return result, submit_fn, alert_fn


# ── D1 short-circuit: needs_input / awaiting_children are never nudged ──────

def test_needs_input_state_never_nudged_regardless_of_idle_time() -> None:
    record = _record(state="needs_input", idle_s=999_999, nudge_count=0, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "skip"
    assert submit_fn.calls == []
    assert alert_fn.calls == []
    assert result["record"]["nudge_count"] == 0


def test_needs_input_state_never_nudged_even_at_nudge_max() -> None:
    record = _record(state="needs_input", idle_s=999_999, nudge_count=NUDGE_MAX, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "skip"
    assert submit_fn.calls == []
    assert alert_fn.calls == []


def test_awaiting_children_state_never_nudged_regardless_of_idle_time() -> None:
    record = _record(state="awaiting_children", idle_s=999_999, nudge_count=0, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "skip"
    assert submit_fn.calls == []
    assert alert_fn.calls == []


# ── not yet stuck: idle time below threshold ─────────────────────────────────

def test_running_state_below_stuck_threshold_is_skipped() -> None:
    record = _record(state="running", idle_s=STUCK_AFTER_S - 1, nudge_count=0, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "skip"
    assert submit_fn.calls == []
    assert alert_fn.calls == []


def test_running_state_idle_exactly_at_threshold_is_skipped() -> None:
    """Idle time must EXCEED stuck_after_s, not merely equal it."""
    record = _record(state="running", idle_s=STUCK_AFTER_S, nudge_count=0, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "skip"
    assert submit_fn.calls == []
    assert alert_fn.calls == []


# ── below nudge_max: exactly one nudge, nudge_count increments by one ───────

def test_stuck_below_nudge_max_sends_exactly_one_nudge_and_increments_count() -> None:
    record = _record(state="stuck", idle_s=STUCK_AFTER_S + 1, nudge_count=0, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "nudge"
    assert len(submit_fn.calls) == 1
    assert submit_fn.calls[0][0] == record["tmux_target"]
    assert alert_fn.calls == []
    assert result["record"]["nudge_count"] == 1
    assert result["record"]["last_nudge_at"] is not None


def test_stuck_below_nudge_max_gated_on_injection_ready_skips_when_not_ready() -> None:
    record = _record(state="stuck", idle_s=STUCK_AFTER_S + 1, nudge_count=0, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record, ready=False)
    assert result["action"] == "skip"
    assert submit_fn.calls == []
    assert alert_fn.calls == []
    # No nudge was actually sent — nudge_count must not be falsely bumped.
    assert result["record"]["nudge_count"] == 0


@pytest.mark.parametrize("status", ["paused", "escalated"])
def test_ambiguous_dispatch_status_does_not_consume_nudge_attempt(status: str) -> None:
    record = _record(state="stuck", idle_s=STUCK_AFTER_S + 1, nudge_count=0, now=NOW)
    result, _submit_fn, alert_fn = _evaluate(
        record, submit=lambda _target, _text: status,
    )
    assert result["action"] == status
    assert result["record"]["nudge_count"] == 0
    assert result["record"]["last_nudge_at"] is None
    assert alert_fn.calls == []


# ── at/above nudge_max: exactly one Discord alert, no further nudge ─────────

def test_stuck_at_nudge_max_sends_exactly_one_discord_alert_and_no_nudge() -> None:
    record = _record(state="stuck", idle_s=STUCK_AFTER_S + 1, nudge_count=NUDGE_MAX, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "discord_alert"
    assert len(alert_fn.calls) == 1
    assert submit_fn.calls == []
    # nudge_count is bumped past nudge_max — the persisted "already
    # escalated" marker (frozen registry schema has no dedicated field).
    assert result["record"]["nudge_count"] == NUDGE_MAX + 1


def test_stuck_already_escalated_marker_skips_further_alerts() -> None:
    """A record whose nudge_count is already past nudge_max (i.e. a prior
    poll cycle already escalated and persisted the marker) must not
    re-alert."""
    record = _record(state="stuck", idle_s=STUCK_AFTER_S + 1, nudge_count=NUDGE_MAX + 1, now=NOW)
    result, submit_fn, alert_fn = _evaluate(record)
    assert result["action"] == "skip"
    assert alert_fn.calls == []
    assert submit_fn.calls == []
    assert result["record"]["nudge_count"] == NUDGE_MAX + 1


def test_stuck_two_consecutive_at_max_polls_send_exactly_one_alert_total() -> None:
    """The core criterion #4 obligation: across repeated polls of the same
    stuck episode, exactly ONE Discord alert is ever dispatched."""
    record = _record(state="stuck", idle_s=STUCK_AFTER_S + 1, nudge_count=NUDGE_MAX, now=NOW)

    first_result, first_submit, first_alert = _evaluate(record)
    assert first_result["action"] == "discord_alert"
    assert len(first_alert.calls) == 1
    assert first_submit.calls == []

    # Poll loop persists the returned record and polls again with it.
    second_result, second_submit, second_alert = _evaluate(first_result["record"])
    assert second_result["action"] == "skip"
    assert second_alert.calls == []
    assert second_submit.calls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
