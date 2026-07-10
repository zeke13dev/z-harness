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
5. a fanout origin's all-terminal-children reconciliation nudge plus a
   failed-child Discord alert, fired exactly once even when a not-ready pane
   forces a retry.

Tests assert on the observable contract — persisted ``sessions.json`` state,
the exact actuation calls, the sidecar file, and signal-log entries — not on
private helpers (STYLE.md:T-001).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from runtime.watchdog import poll, registry
from runtime.watchdog.adapters.base import ContextReading, HostAdapter

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

def test_threshold_crossing_handoff_actuates(tmp_path):
    """pct_used >= threshold + injection_ready + running drives the full
    handoff choreography to ``resumed`` and submits handoff then clear."""
    rec = _record(tmp_path)
    sessions = {rec["session_id"]: rec}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(
        reading=ContextReading(new_offset=10, used_tokens=180000, window_tokens=200000, pct_used=90.0),
    )
    submit = RecordingSubmit()

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        signals_max_mb=50, now=_NOW,
        submit_fn=submit, judge_dispatch=_succeeding_judge,
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
        now=_NOW, submit_fn=submit, judge_dispatch=_succeeding_judge,
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
        now=_NOW, submit_fn=submit, judge_dispatch=_succeeding_judge,
        **_paths(tmp_path),
    )

    assert res["record"]["state"] == "running"  # not driven into handoff
    assert submit.calls == []


# ── (2) judge-unavailable degrade-and-still-trigger ─────────────────────────

def test_judge_degraded_still_triggers_and_logs(tmp_path):
    """With the judge unavailable, the handoff sequence still completes via the
    mechanical fallback and a ``judge_degraded`` signal is logged."""
    rec = _record(tmp_path)
    sessions = {rec["session_id"]: rec}
    registry.write_registry(tmp_path / "sessions.json", sessions)
    adapter = StubAdapter(
        reading=ContextReading(new_offset=10, used_tokens=180000, window_tokens=200000, pct_used=95.0),
    )
    submit = RecordingSubmit()

    res = poll.poll_session(
        rec, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        signals_max_mb=50, now=_NOW, submit_fn=submit, judge_dispatch=_degraded_judge,
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

def test_stuck_nudge_then_escalation_exactly_once(tmp_path):
    """Idle session is nudged up to nudge_max, then escalates to exactly one
    Discord alert; the nudge_count>nudge_max marker persists so later polls
    skip instead of re-alerting."""
    nudge_max = 2
    rec = _record(tmp_path)  # last_seen far in the past -> idle
    sessions = {rec["session_id"]: rec}
    adapter = StubAdapter()  # default reading: no new bytes -> last_seen stays
    submit = RecordingSubmit()
    alert = RecordingAlert()

    def _poll_once(record):
        return poll.poll_session(
            record, {record["session_id"]: record}, adapter=adapter,
            pane_text="idle >", threshold_pct=80, window_tokens=200000,
            stuck_after_s=600, nudge_max=nudge_max, now=_NOW,
            submit_fn=submit, stuck_alert_fn=alert, **_paths(tmp_path),
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
        now=_NOW, submit_fn=submit, stuck_alert_fn=stuck_alert,
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
        "", now="2020-01-01T00:00:00Z",
    )
    if state != "registered":
        child = registry.transition(child, state, now="2020-01-01T00:00:01Z")
    return child


def test_fanout_origin_armed_into_awaiting_children(tmp_path):
    """A running origin with children is transitioned to awaiting_children."""
    child = _child(tmp_path, "running", "zw-child-1")
    origin = _record(tmp_path, children=[child["session_id"]])
    sessions = {origin["session_id"]: origin, child["session_id"]: child}
    adapter = StubAdapter()

    res = poll.poll_session(
        origin, sessions, adapter=adapter, pane_text="working >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, **_paths(tmp_path),
    )
    assert res["action"] == "await_children"
    assert res["record"]["state"] == "awaiting_children"


def test_fanout_reconciliation_nudge_and_failed_child_alert(tmp_path):
    """When every child is terminal, the awaiting_children origin gets exactly
    one reconciliation nudge listing per-child statuses, one Discord alert per
    failed child, and transitions out of awaiting_children."""
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
    adapter = StubAdapter()
    submit = RecordingSubmit()
    recon_alert = RecordingAlert(ret=1)

    def _dead(target, **kwargs):  # live_child's pane is gone
        return target != "zw-child-dead"

    res = poll.poll_session(
        origin, sessions, adapter=adapter, pane_text="ready >",
        threshold_pct=80, window_tokens=200000, stuck_after_s=600, nudge_max=2,
        now=_NOW, submit_fn=submit, has_session=_dead,
        reconcile_alert_fn=recon_alert, **_paths(tmp_path),
    )

    assert res["action"] == "reconcile"
    assert res["reconcile_payload"] is not None
    # The dead child was marked failed.
    persisted = _read_registry(tmp_path)
    assert persisted[live_child["session_id"]]["state"] == "failed"
    # Exactly one text nudge listing both children's statuses.
    assert len(submit.calls) == 1
    summary = submit.calls[0][1]
    assert "zw-child-dead" in summary and "failed" in summary
    assert "zw-child-done" in summary and "done" in summary
    # Exactly one failed-child Discord alert.
    assert len(recon_alert.calls) == 1
    # Origin transitioned out of awaiting_children so a later poll cannot re-nudge.
    assert res["record"]["state"] == "running"


def test_fanout_reconciliation_retries_when_pane_not_ready(tmp_path):
    """A not-ready pane at reconciliation time sends nothing and stays
    awaiting_children; the failed-child alert + nudge fire exactly once when
    the pane later becomes ready (no double-alert on the retry cycle)."""
    live_child = _child(tmp_path, "running", "zw-child-dead")
    origin = _record(
        tmp_path, state="awaiting_children", children=[live_child["session_id"]],
    )
    sessions = {origin["session_id"]: origin, live_child["session_id"]: live_child}
    submit = RecordingSubmit()
    recon_alert = RecordingAlert(ret=1)

    def _dead(target, **kwargs):
        return False

    common = dict(
        pane_text="busy", threshold_pct=80, window_tokens=200000,
        stuck_after_s=600, nudge_max=2, now=_NOW, submit_fn=submit,
        has_session=_dead, reconcile_alert_fn=recon_alert, **_paths(tmp_path),
    )

    # Cycle 1: pane not ready -> nothing sent, still awaiting_children.
    res = poll.poll_session(
        origin, sessions, adapter=StubAdapter(injection_ready=False), **common,
    )
    assert res["record"]["state"] == "awaiting_children"
    assert submit.calls == [] and recon_alert.calls == []

    # Cycle 2: pane ready -> exactly one nudge + one failed-child alert.
    reloaded = _read_registry(tmp_path)
    origin2 = reloaded[origin["session_id"]]
    res2 = poll.poll_session(
        origin2, reloaded, adapter=StubAdapter(injection_ready=True), **common,
    )
    assert res2["record"]["state"] == "running"
    assert len(submit.calls) == 1
    assert len(recon_alert.calls) == 1


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
        now=_NOW, submit_fn=RecordingSubmit(), stuck_alert_fn=RecordingAlert(),
        **_paths(tmp_path),
    )
    assert res["record"]["transcript_offset"] == 250
    assert res["record"]["last_seen"] == _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
