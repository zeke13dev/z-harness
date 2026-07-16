"""Tests for runtime/watchdog/poll.py (per-session poll-cycle composition).

Coverage (T016 acceptance, criteria #2/#3/#4/#5/#7): the five composed
behaviors of one ``poll_session`` cycle, each with a stubbed adapter / actuator
/ judge / Discord callable so no test touches a real tmux pane, provider CLI, or
webhook (STYLE.md:T-002 — the composed modules' own subprocess paths are covered
by their sibling test files), and every artifact pinned under ``tmp_path``
(STYLE.md:T-004):

1. threshold-crossing handoff + real tmux actuation (handoff_command then
   clear_command submitted);
2. judge-unavailable degrade-and-still-trigger (a ``judge_degraded`` signal is
   logged and the choreography still completes + actuates);
3. stuck nudge then nudge-max Discord escalation, with the ``nudge_count >
   nudge_max`` marker persisted so the escalation is exactly-once across polls;
4. needs_input first-alert then digest-deduped skip on an unchanged prompt, with
   the digest persisted to a sidecar that survives a simulated daemon restart;
5. a fanout origin advances child leases without bypassing sealed-group join
   readiness or creating a coordinator wake.

Tests assert on the observable contract — persisted ``sessions.json`` state,
the exact actuation calls, the sidecar file, and signal-log entries — not on
private helpers (STYLE.md:T-001).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from runtime.watchdog import notify, poll, registry, tmux_actuator
from runtime.watchdog.adapters.base import ContextReading, HostAdapter
from runtime.watchdog.adapters.claude import ClaudeAdapter

_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


# ── stubs ────────────────────────────────────────────────────────────────────

class StubAdapter(HostAdapter):
    """Controllable ``HostAdapter`` for poll composition tests."""

    host = "claude"

    def __init__(
        self,
        *,
        reading: ContextReading | None = None,
        injection_ready: bool = True,
        needs_input: bool = False,
    ) -> None:
        self._reading = reading
        self._injection_ready = injection_ready
        self._needs_input = needs_input

    def read_context(self, transcript_path, offset, *, window_tokens):
        if self._reading is not None:
            return self._reading
        # Default: no new bytes consumed this cycle (leaves last_seen untouched).
        return ContextReading(
            new_offset=offset, used_tokens=None,
            window_tokens=window_tokens, pct_used=None,
        )

    def injection_ready(self, pane_text):
        return self._injection_ready

    def needs_input(self, pane_text):
        return self._needs_input

    def handoff_command(self):
        return "/z-handoff"

    def clear_command(self):
        return "/clear"


class RecordingSubmit:
    """Records ``(target, text)`` submit calls in place of ``submit_text``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, target, text, **kwargs):
        self.calls.append((target, text))


class RecordingAlert:
    """Records Discord alert invocations; reports success (True / count)."""

    def __init__(self, *, ret=True) -> None:
        self.calls: list[tuple] = []
        self._ret = ret

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._ret


def _succeeding_judge(*, context_pct, threshold_pct, prompt, repo_root, role, timeout_s):
    return {"verdict": {"source": "judge", "raw_output": "ok"}, "judge_degraded": None}


def _degraded_judge(*, context_pct, threshold_pct, prompt, repo_root, role, timeout_s):
    return {
        "verdict": {"source": "mechanical_fallback", "stop": context_pct >= threshold_pct},
        "judge_degraded": {"role": role, "reason": "role_unresolved", "attempts": 0},
    }


# ── fixtures / helpers ───────────────────────────────────────────────────────

def _record(tmp_path: Path, *, state="running", last_seen=None, **overrides) -> dict:
    rec = registry.new_session_record(
        "session-watchdog",
        str(tmp_path),
        "claude",
        "zw-session-watchdog-abcd1234",
        str(tmp_path / "transcript.jsonl"),
        now="2020-01-01T00:00:00Z",  # far-past so idle detection can fire
    )
    if state != "registered":
        rec = registry.transition(rec, state, now="2020-01-01T00:00:01Z")
    if last_seen is not None:
        rec["last_seen"] = last_seen
    rec.update(overrides)
    return rec


def _paths(tmp_path: Path) -> dict:
    return {
        "registry_path": tmp_path / "sessions.json",
        "signals_path": tmp_path / "signals.jsonl",
        "repo_root": tmp_path,
    }


def _read_registry(tmp_path: Path) -> dict[str, dict]:
    return registry.read_registry(tmp_path / "sessions.json")


# ── (1) threshold-crossing handoff + actuation ──────────────────────────────

def test_threshold_crossing_handoff_actuates(tmp_path, monkeypatch):
    """pct_used >= threshold + injection_ready + running drives the full
    handoff choreography to ``resumed`` and submits handoff then clear."""
    rec = _record(tmp_path)
    sessions = {rec["session_id"]: rec}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(
        reading=ContextReading(new_offset=10, used_tokens=180000, window_tokens=200000, pct_used=90.0),
    )
    submit = RecordingSubmit()
    monkeypatch.setattr(tmux_actuator, "submit_text", submit)

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        signals_max_mb=50, now=_NOW,
        judge_dispatch=_succeeding_judge,
        **_paths(tmp_path),
    )

    assert res["action"] == "handoff"
    assert res["handoff_result"]["triggered"] is True
    assert res["record"]["state"] == "resumed"
    # The two real choreography actuations, in order.
    assert submit.calls == [
        ("zw-session-watchdog-abcd1234", "/z-handoff"),
        ("zw-session-watchdog-abcd1234", "/clear"),
    ]
    # handoff.json written under the record's plan_dir.
    assert (tmp_path / "handoff.json").is_file()
    # Persisted registry reflects the resumed state.
    assert _read_registry(tmp_path)[rec["session_id"]]["state"] == "resumed"


def test_below_threshold_no_handoff(tmp_path):
    """A reading below threshold never triggers the handoff arm."""
    rec = _record(tmp_path, last_seen=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    sessions = {rec["session_id"]: rec}
    adapter = StubAdapter(
        reading=ContextReading(new_offset=5, used_tokens=100000, window_tokens=200000, pct_used=50.0),
    )
    submit = RecordingSubmit()

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, judge_dispatch=_succeeding_judge,
        **_paths(tmp_path),
    )

    assert res["action"] == "skip"
    assert res["record"]["state"] == "running"
    assert submit.calls == []


def test_handoff_skipped_when_pane_not_injection_ready(tmp_path):
    """Over-threshold but not injection_ready: trigger skipped this cycle."""
    rec = _record(tmp_path, last_seen=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    sessions = {rec["session_id"]: rec}
    adapter = StubAdapter(
        reading=ContextReading(new_offset=10, used_tokens=180000, window_tokens=200000, pct_used=90.0),
        injection_ready=False,
    )
    submit = RecordingSubmit()

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="working...",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, judge_dispatch=_succeeding_judge,
        **_paths(tmp_path),
    )

    assert res["record"]["state"] == "running"  # not driven into handoff
    assert submit.calls == []


def test_crashed_handoff_dispatch_never_strands_resumed_state(
    tmp_path, monkeypatch,
):
    rec = _record(tmp_path)
    sessions = {rec["session_id"]: rec}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(
        reading=ContextReading(
            new_offset=10, used_tokens=180000,
            window_tokens=200000, pct_used=90.0,
        ),
    )

    def _ambiguous_submit(target, text):
        raise tmux_actuator.TmuxTimeoutError("ambiguous host outcome")

    monkeypatch.setattr(tmux_actuator, "submit_text", _ambiguous_submit)
    with pytest.raises(tmux_actuator.TmuxTimeoutError):
        poll.poll_session(
            rec, sessions, adapter=adapter, pane_text="ready >",
            threshold_pct=80, window_tokens=200000,
            stuck_after_s=600, nudge_max=2, now=_NOW,
            judge_dispatch=_succeeding_judge, **_paths(tmp_path),
        )

    persisted = _read_registry(tmp_path)
    assert persisted[rec["session_id"]]["state"] == "handoff_written"

    recorder = RecordingSubmit()
    monkeypatch.setattr(tmux_actuator, "submit_text", recorder)
    resumed_attempt = poll.poll_session(
        persisted[rec["session_id"]], persisted,
        adapter=StubAdapter(), pane_text="ready >",
        threshold_pct=80, window_tokens=200000,
        stuck_after_s=600, nudge_max=2, now=_NOW,
        judge_dispatch=_succeeding_judge, **_paths(tmp_path),
    )
    assert resumed_attempt["action"] == "paused"
    assert resumed_attempt["record"]["state"] == "handoff_written"
    assert recorder.calls == []


def test_handoff_requested_with_ambiguous_context_pauses_without_fallthrough(
    tmp_path,
):
    rec = registry.transition(
        _record(tmp_path), "handoff_requested", now="2026-07-10T11:59:00Z",
    )
    registry.write_registry(tmp_path / "sessions.json", {rec["session_id"]: rec})
    result = poll.poll_session(
        rec, {rec["session_id"]: rec}, adapter=StubAdapter(), pane_text="ready >",
        threshold_pct=80, window_tokens=200000,
        stuck_after_s=600, nudge_max=2, now=_NOW,
        judge_dispatch=_succeeding_judge, **_paths(tmp_path),
    )
    assert result["action"] == "paused"
    assert result["record"]["state"] == "handoff_requested"


# ── (2) judge-unavailable degrade-and-still-trigger ─────────────────────────

def test_judge_degraded_still_triggers_and_logs(tmp_path, monkeypatch):
    """With the judge unavailable, the handoff sequence still completes via the
    mechanical fallback and a ``judge_degraded`` signal is logged."""
    rec = _record(tmp_path)
    sessions = {rec["session_id"]: rec}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(
        reading=ContextReading(new_offset=10, used_tokens=180000, window_tokens=200000, pct_used=95.0),
    )
    submit = RecordingSubmit()
    monkeypatch.setattr(tmux_actuator, "submit_text", submit)

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        signals_max_mb=50, now=_NOW, judge_dispatch=_degraded_judge,
        **_paths(tmp_path),
    )

    assert res["action"] == "handoff"
    assert res["record"]["state"] == "resumed"
    assert res["handoff_result"]["judge_degraded"] is not None
    assert len(submit.calls) == 2  # still actuated
    # A judge_degraded entry appears in signals.jsonl.
    lines = (tmp_path / "signals.jsonl").read_text(encoding="utf-8").splitlines()
    kinds = [json.loads(line)["kind"] for line in lines if line.strip()]
    assert "judge_degraded" in kinds


# ── (3) stuck nudge then nudge-max Discord escalation (marker persisted) ─────

def test_stuck_nudge_then_escalation_exactly_once(tmp_path, monkeypatch):
    """Idle session is nudged up to nudge_max, then escalates to exactly one
    Discord alert; the nudge_count>nudge_max marker persists so later polls
    skip instead of re-alerting."""
    nudge_max = 2
    rec = _record(tmp_path)  # last_seen far in the past -> idle
    sessions = {rec["session_id"]: rec}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter()  # default reading: no new bytes -> last_seen stays
    submit = RecordingSubmit()
    alert = RecordingAlert()
    monkeypatch.setattr(tmux_actuator, "submit_text", submit)
    monkeypatch.setattr(notify, "send_discord_alert", alert)

    def _poll_once(record):
        return poll.poll_session(
            record, {record["session_id"]: record}, adapter=adapter,
            pane_text="idle >", threshold_pct=80, window_tokens=200000,
            stuck_after_s=600, nudge_max=nudge_max, now=_NOW,
            **_paths(tmp_path),
        )

    # Two nudges (nudge_count 0 -> 1 -> 2).
    res = _poll_once(rec)
    assert res["action"] == "nudge"
    assert res["record"]["nudge_count"] == 1
    res = _poll_once(res["record"])
    assert res["action"] == "nudge"
    assert res["record"]["nudge_count"] == 2
    # At nudge_max -> exactly one Discord alert, marker bumped past max.
    res = _poll_once(res["record"])
    assert res["action"] == "discord_alert"
    assert res["record"]["nudge_count"] == nudge_max + 1
    assert len(alert.calls) == 1
    # A later poll with the persisted marker skips — no second alert.
    res = _poll_once(res["record"])
    assert res["action"] == "skip"
    assert len(alert.calls) == 1
    assert len(submit.calls) == 2  # only the two plain-text nudges, never the alert


def test_failed_nudges_consume_attempts_and_escalate_at_cap(tmp_path, monkeypatch):
    rec = _record(tmp_path)
    registry.write_registry(tmp_path / "sessions.json", {rec["session_id"]: rec})
    calls: list[tuple[str, str]] = []

    def _definite_failure(target, text):
        calls.append((target, text))
        return False

    monkeypatch.setattr(tmux_actuator, "submit_text", _definite_failure)
    current = rec
    expected = (("nudge_failed", 1), ("escalated", 1), ("nudge_failed", 2))
    for expected_action, expected_count in expected:
        result = poll.poll_session(
            current, {current["session_id"]: current},
            adapter=StubAdapter(), pane_text="idle >",
            threshold_pct=80, window_tokens=200000,
            stuck_after_s=600, nudge_max=2, now=_NOW,
            **_paths(tmp_path),
        )
        assert result["action"] == expected_action
        assert result["record"]["nudge_count"] == expected_count
        current = result["record"]

    assert len(calls) == 2
    markers = registry.read_registry_document(
        tmp_path / "sessions.json"
    )["action_markers"]
    assert sum(marker["status"] == "failed" for marker in markers.values()) == 2
    assert sum(marker["status"] == "escalated" for marker in markers.values()) == 1


def test_prepared_nudge_pauses_without_consuming_attempt(tmp_path, monkeypatch):
    rec = _record(tmp_path)
    registry.write_registry(tmp_path / "sessions.json", {rec["session_id"]: rec})

    def _ambiguous_delivery(_target, _text):
        raise tmux_actuator.TmuxTimeoutError("delivery outcome unknown")

    monkeypatch.setattr(tmux_actuator, "submit_text", _ambiguous_delivery)
    with pytest.raises(tmux_actuator.TmuxTimeoutError):
        poll.poll_session(
            rec, {rec["session_id"]: rec}, adapter=StubAdapter(), pane_text="idle >",
            threshold_pct=80, window_tokens=200000, stuck_after_s=600,
            nudge_max=2, now=_NOW, **_paths(tmp_path),
        )

    persisted = _read_registry(tmp_path)[rec["session_id"]]
    result = poll.poll_session(
        persisted, {persisted["session_id"]: persisted}, adapter=StubAdapter(),
        pane_text="idle >", threshold_pct=80, window_tokens=200000,
        stuck_after_s=600, nudge_max=2, now=_NOW, **_paths(tmp_path),
    )
    assert result["action"] == "paused"
    assert result["record"]["nudge_count"] == 0
    markers = registry.read_registry_document(
        tmp_path / "sessions.json"
    )["action_markers"]
    assert [marker["attempt"] for marker in markers.values()] == [1]


def test_needs_input_pane_is_never_nudged(tmp_path):
    """A session whose pane still shows a needs_input menu is never nudged
    (criterion #4), even though it is idle: the needs_input arm returns before
    the stuck arm can run."""
    rec = _record(tmp_path)  # idle (far-past last_seen)
    sessions = {rec["session_id"]: rec}
    adapter = StubAdapter(needs_input=True)  # pane still shows the menu
    submit = RecordingSubmit()
    stuck_alert = RecordingAlert()

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text=_MENU_PANE,
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW,
        needs_input_alert_fn=RecordingAlert(), **_paths(tmp_path),
    )

    # The needs_input arm handled the cycle and returned; the stuck arm never
    # ran, so no nudge text was submitted and no stuck escalation fired.
    assert res["action"] == "needs_input"
    assert res["record"]["state"] == "needs_input"
    assert submit.calls == []
    assert stuck_alert.calls == []


# ── (4) needs_input first-alert then digest-deduped skip ────────────────────

_MENU_PANE = "Which model?\n1. gpt-5.5 (default)\n2. claude\nPress enter to select"


def test_needs_input_first_alert_then_deduped(tmp_path):
    """A needs_input pane briefs Discord exactly once; an unchanged prompt on a
    later poll is digest-deduped (no second brief), and the digest survives a
    simulated daemon restart via the sidecar."""
    rec = _record(tmp_path)
    adapter = StubAdapter(needs_input=True)
    alert = RecordingAlert(ret=True)

    res = poll.poll_session(
        rec, {rec["session_id"]: rec}, adapter=adapter, pane_text=_MENU_PANE,
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, needs_input_alert_fn=alert, **_paths(tmp_path),
    )
    assert res["action"] == "needs_input"
    assert res["needs_input_result"]["action"] == "sent"
    assert res["record"]["state"] == "needs_input"
    assert len(alert.calls) == 1
    # Sidecar persisted the digest.
    sidecar = tmp_path / "needs_input_digests" / f"{rec['session_id']}.digest"
    assert sidecar.is_file()
    assert sidecar.read_text(encoding="utf-8") == res["needs_input_result"]["digest"]

    # Simulate a separate daemon/--once invocation: fresh in-memory state, same
    # sidecar on disk. Same prompt -> deduped, no second alert.
    reloaded = _read_registry(tmp_path)[rec["session_id"]]
    res2 = poll.poll_session(
        reloaded, {reloaded["session_id"]: reloaded}, adapter=adapter,
        pane_text=_MENU_PANE, threshold_pct=80, window_tokens=200000,
        stuck_after_s=600, nudge_max=2, now=_NOW,
        needs_input_alert_fn=alert, **_paths(tmp_path),
    )
    assert res2["needs_input_result"]["action"] == "skip"
    assert len(alert.calls) == 1  # still exactly one across both invocations


# ── (5) fanout reconciliation nudge + failed-child Discord alert ────────────

def _child(tmp_path, state, tmux_target):
    child = registry.new_session_record(
        "session-watchdog/cluster", str(tmp_path), "claude", tmux_target,
        "", parent_id="ws-parent", now="2020-01-01T00:00:00Z",
    )
    if state != "registered":
        child = registry.transition(child, state, now="2020-01-01T00:00:01Z")
    return child


def test_fanout_origin_armed_into_awaiting_children(tmp_path):
    """A running origin with children is transitioned to awaiting_children."""
    child = _child(tmp_path, "running", "zw-child-1")
    origin = _record(tmp_path, children=[child["session_id"]])
    sessions = {origin["session_id"]: origin, child["session_id"]: child}
    # Seed disk to match the daemon's in-memory pass snapshot (the single-writer
    # invariant poll's locked-fresh-merge assumes, T-REV-001).
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter()

    res = poll.poll_session(
        origin, sessions, adapter=adapter, pane_text="working >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, **_paths(tmp_path),
    )
    assert res["action"] == "await_children"
    assert res["record"]["state"] == "awaiting_children"
    # The untouched live child is preserved in the persisted registry.
    assert _read_registry(tmp_path)[child["session_id"]]["state"] == "running"


def test_fanout_origin_stuck_in_needs_input_is_unblocked_and_armed(tmp_path):
    """An origin that entered needs_input BEFORE fanout must not deadlock:
    once the pane is no longer waiting, the origin arm clears
    needs_input -> running and arms awaiting_children in the same cycle
    (found live, 2026-07-11 fanout smoke test)."""
    child = _child(tmp_path, "running", "zw-child-1")
    origin = _record(tmp_path, children=[child["session_id"]])
    origin = registry.transition(origin, "needs_input", now="2020-01-01T00:00:02Z")
    sessions = {origin["session_id"]: origin, child["session_id"]: child}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(needs_input=False)

    res = poll.poll_session(
        origin, sessions, adapter=adapter, pane_text="working",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, **_paths(tmp_path),
    )
    assert res["action"] == "await_children"
    assert res["record"]["state"] == "awaiting_children"


def test_fanout_origin_still_waiting_in_needs_input_is_not_armed(tmp_path):
    """An origin whose pane still shows a menu stays needs_input — the clear
    only fires once the human answered."""
    child = _child(tmp_path, "running", "zw-child-1")
    origin = _record(tmp_path, children=[child["session_id"]])
    origin = registry.transition(origin, "needs_input", now="2020-01-01T00:00:02Z")
    sessions = {origin["session_id"]: origin, child["session_id"]: child}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(needs_input=True)

    res = poll.poll_session(
        origin, sessions, adapter=adapter, pane_text="1. yes 2. no",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, **_paths(tmp_path),
    )
    assert res["record"]["state"] == "needs_input"


def test_terminal_children_do_not_bypass_sealed_group_join(tmp_path, monkeypatch):
    """Terminal children alone never wake or transition their coordinator."""
    done_child = _child(tmp_path, "done", "zw-child-done")
    live_child = _child(tmp_path, "running", "zw-child-dead")  # pane killed OOB
    origin = _record(
        tmp_path, state="awaiting_children",
        children=[done_child["session_id"], live_child["session_id"]],
    )
    sessions = {
        origin["session_id"]: origin,
        done_child["session_id"]: done_child,
        live_child["session_id"]: live_child,
    }
    # Seed disk to match the in-memory pass snapshot (single-writer invariant).
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter()
    submit = RecordingSubmit()
    monkeypatch.setattr(tmux_actuator, "submit_text", submit)

    def _dead(target, **kwargs):  # live_child's pane is gone
        return target != "zw-child-dead"

    res = poll.poll_session(
        origin, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, has_session=_dead, **_paths(tmp_path),
    )

    assert res["action"] == "reconcile"
    assert res["reconcile_payload"] is not None
    # The dead child was marked failed; the untouched terminal child survives.
    persisted = _read_registry(tmp_path)
    assert persisted[live_child["session_id"]]["state"] == "failed"
    assert persisted[done_child["session_id"]]["state"] == "done"
    outcomes = registry.read_registry_document(
        tmp_path / "sessions.json"
    )["outcomes"]
    reaped = next(iter(outcomes.values()))
    assert reaped["state"] == "failed" and reaped["source"] == "lease_reaper"
    assert all(outcome["state"] != "done" for outcome in outcomes.values())
    assert submit.calls == []
    assert res["record"]["state"] == "awaiting_children"
    assert registry.read_registry_document(
        tmp_path / "sessions.json"
    )["action_markers"] == {}


# ── (a) context read offset/last_seen persistence ───────────────────────────

def test_context_read_persists_offset_and_advances_last_seen(tmp_path):
    """New transcript bytes advance the offset AND refresh last_seen; a cycle
    with no new bytes advances neither (so idle detection can still fire)."""
    rec = _record(tmp_path, last_seen="2020-01-01T00:00:00Z", transcript_offset=100)
    adapter = StubAdapter(
        reading=ContextReading(new_offset=250, used_tokens=None, window_tokens=200000, pct_used=None),
    )
    res = poll.poll_session(
        rec, {rec["session_id"]: rec}, adapter=adapter, pane_text="working",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW,
        **_paths(tmp_path),
    )
    assert res["record"]["transcript_offset"] == 250
    assert res["record"]["last_seen"] == _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── (T-REV-001) poll persist does not clobber a concurrent fanout child ──────

def test_poll_session_does_not_clobber_concurrent_fanout_child(tmp_path):
    """A poll cycle persisting its own transition must not drop a fanout child
    that a concurrent ``fanout.run_fanout`` added to ``sessions.json`` after the
    daemon read its pass-start snapshot (T-REV-001, the "no session record is
    lost" acceptance).

    Modeled deterministically: the daemon reads its pass snapshot (``{watched}``)
    from disk, then a concurrent fanout persists an unrelated child record
    ``C`` to disk. When ``poll_session`` then persists its cycle for
    ``watched``, its locked-fresh-merge re-reads the registry (now holding
    ``C``) and applies ONLY the record it changed, so ``C`` survives rather than
    being clobbered by the stale ``{watched}`` snapshot the poll started from.
    """
    watched = _record(tmp_path, last_seen=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
    # The daemon's pass-start registry + the snapshot it hands to poll_session.
    registry.write_registry(tmp_path / "sessions.json", {watched["session_id"]: watched})
    pass_snapshot = _read_registry(tmp_path)

    # A concurrent fanout lands an unrelated child on disk AFTER the snapshot.
    child = registry.new_session_record(
        "root/cluster", str(tmp_path), "claude", "zw-child-99",
        "", session_id="ws-fanout-child-99", now="2020-01-01T00:00:00Z",
    )
    on_disk = _read_registry(tmp_path)
    on_disk[child["session_id"]] = child
    registry.write_registry(tmp_path / "sessions.json", on_disk)

    # Pane not injection_ready -> handoff arm skipped; not needs_input; the
    # recent last_seen keeps stuck from nudging -> a plain persisting skip.
    adapter = StubAdapter(injection_ready=False)
    res = poll.poll_session(
        watched, pass_snapshot, adapter=adapter, pane_text="working...",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW,
        **_paths(tmp_path),
    )

    persisted = _read_registry(tmp_path)
    # The concurrently-added fanout child survives the poll's persist.
    assert child["session_id"] in persisted
    registry.validate_record(persisted[child["session_id"]])
    # The polled session's own cycle still persisted, and the merged mapping the
    # poll returns carries the concurrent child forward for the next cycle.
    assert watched["session_id"] in persisted
    assert child["session_id"] in res["sessions"]


def test_fanout_child_first_poll_empty_transcript_path_degrades(tmp_path):
    """A freshly spawned fanout child registers with ``transcript_path=""``
    (T013's LEDGER decision — the host CLI assigns the transcript file only
    after booting). The real ``ClaudeAdapter.read_context`` catches the
    resulting ``FileNotFoundError`` from ``open("", "rb")`` and returns the
    ``context_unknown`` degraded reading rather than raising; the poll cycle
    must complete without propagating an exception, must not advance
    ``transcript_offset`` past its starting value, and must leave
    ``last_seen`` untouched (no new transcript bytes were consumed, so the
    stuck-detection idle clock is not falsely reset)."""
    original_last_seen = "2020-01-01T00:00:00Z"
    rec = _record(tmp_path, last_seen=original_last_seen, transcript_path="")
    sessions = {rec["session_id"]: rec}
    adapter = ClaudeAdapter()  # real adapter — exercises its own FileNotFoundError catch
    submit = RecordingSubmit()
    alert = RecordingAlert()

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="working...",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW,
        **_paths(tmp_path),
    )

    # Degraded context-read path taken: no confident usage reading this cycle.
    assert res["reading"].used_tokens is None
    assert res["reading"].pct_used is None
    assert res["reading"].new_offset == 0
    # No new bytes consumed -> transcript_offset and last_seen are unchanged
    # (the idle clock for stuck detection is not falsely advanced).
    assert res["record"]["transcript_offset"] == 0
    assert res["record"]["last_seen"] == original_last_seen
    # The cycle completed (no exception propagated) and fell through to the
    # stuck arm; the pane is not injection_ready, so it skips rather than
    # nudging or alerting — nothing was submitted.
    assert res["action"] == "skip"
    assert submit.calls == []
    assert alert.calls == []
