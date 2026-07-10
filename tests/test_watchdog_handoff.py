"""Tests for runtime/watchdog/handoff.py (context-threshold handoff state
machine).

Coverage (T010 acceptance, criteria #2/#3):
- an over-threshold record is driven end-to-end through
  ``registered/running -> handoff_requested -> handoff_written -> cleared ->
  resumed``, with a distinct, strictly increasing ``state_changed_at`` per
  transition and ``handoff.json`` showing a post-trigger mtime;
- the trigger boundary is at-or-above (``pct_used >= threshold_pct``), not
  strictly-above — exactly at the threshold still triggers, just below does
  not;
- a ``context_unknown`` (``None``) reading never triggers;
- a judge-unavailable dispatch still drives the full pipeline to ``resumed``
  via the mechanical fallback, and appends exactly one ``judge_degraded``
  entry to ``signals.jsonl``.

Tests substitute a stub ``judge_dispatch`` throughout (STYLE.md:T-002 note:
the real judge dispatch shells out to a provider CLI and is covered by
``test_watchdog_judge.py`` already; this module's own contract is the
choreography around whatever ``judge_dispatch`` returns) and pin every
artifact under ``tmp_path`` (STYLE.md:T-004) — no real registry/signals file
outside the test's own temp dir is ever touched.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from runtime.watchdog import handoff, registry


def _fresh_record(plan_dir: Path, transcript_path: Path) -> dict:
    record = registry.new_session_record(
        "session-watchdog",
        str(plan_dir),
        "claude",
        "zw-session-watchdog-test:0.0",
        str(transcript_path),
        now="2026-07-10T20:00:00.000000Z",
    )
    return registry.transition(record, "running", now="2026-07-10T20:00:01.000000Z")


def _succeeding_judge_dispatch(*, context_pct, threshold_pct, prompt, repo_root, role, timeout_s):
    assert isinstance(prompt, str) and prompt  # a real prompt was built
    return {
        "verdict": {"source": "judge", "raw_output": "safe to hand off now"},
        "judge_degraded": None,
    }


def _degraded_judge_dispatch(*, context_pct, threshold_pct, prompt, repo_root, role, timeout_s):
    return {
        "verdict": {
            "source": "mechanical_fallback",
            "stop": context_pct >= threshold_pct,
            "context_pct": context_pct,
            "threshold_pct": threshold_pct,
        },
        "judge_degraded": {
            "role": role,
            "reason": "role_unresolved: test-forced",
            "attempts": 0,
            "timeout_s": timeout_s or 60.0,
        },
    }


def test_maybe_trigger_handoff_end_to_end(tmp_path, monkeypatch):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    record = _fresh_record(plan_dir, tmp_path / "transcript.jsonl")

    # Spy on registry.write_registry to capture a snapshot of this session's
    # record at every persisted step (T010 acceptance: "all four transition
    # timestamps are present and monotonic").
    snapshots: list[dict] = []
    real_write_registry = registry.write_registry

    def _spy_write_registry(path, sessions):
        snapshots.append(copy.deepcopy(sessions[record["session_id"]]))
        real_write_registry(path, sessions)

    monkeypatch.setattr(registry, "write_registry", _spy_write_registry)

    trigger_time = time.time()
    result = handoff.maybe_trigger_handoff(
        record,
        95.0,
        threshold_pct=80.0,
        registry_path=registry_path,
        signals_path=signals_path,
        repo_root=str(tmp_path),
        pane_text="some recent pane output",
        judge_dispatch=_succeeding_judge_dispatch,
    )

    assert result["triggered"] is True
    assert result["reason"] is None
    assert result["record"]["state"] == "resumed"
    assert result["judge_degraded"] is None

    # Exactly the 4 choreography transitions were persisted, in order.
    assert [s["state"] for s in snapshots] == [
        "handoff_requested", "handoff_written", "cleared", "resumed",
    ]
    timestamps = [s["state_changed_at"] for s in snapshots]
    assert timestamps == sorted(timestamps)
    assert len(set(timestamps)) == 4, "state_changed_at must be distinct per transition"

    # sessions.json on disk reflects the final persisted state.
    on_disk = registry.read_registry(registry_path)
    assert on_disk[record["session_id"]]["state"] == "resumed"

    # handoff.json was written with a post-trigger mtime.
    handoff_path = plan_dir / "handoff.json"
    assert result["handoff_path"] == handoff_path
    assert handoff_path.exists()
    assert handoff_path.stat().st_mtime >= trigger_time
    payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert payload["session_id"] == record["session_id"]
    assert payload["verdict"]["source"] == "judge"
    assert payload["judge_degraded"] is None

    # No judge_degraded signal on the successful-dispatch path.
    assert not signals_path.exists() or signals_path.read_text(encoding="utf-8") == ""


def test_maybe_trigger_handoff_judge_degraded(tmp_path):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    record = _fresh_record(plan_dir, tmp_path / "transcript.jsonl")

    result = handoff.maybe_trigger_handoff(
        record,
        90.0,
        threshold_pct=80.0,
        registry_path=registry_path,
        signals_path=signals_path,
        repo_root=str(tmp_path),
        judge_dispatch=_degraded_judge_dispatch,
        signals_max_mb=1,
    )

    assert result["triggered"] is True
    assert result["record"]["state"] == "resumed"
    assert result["judge_degraded"] is not None
    assert result["verdict"]["source"] == "mechanical_fallback"

    lines = signals_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "exactly one judge_degraded entry"
    event = json.loads(lines[0])
    assert event["kind"] == "judge_degraded"
    assert event["payload"]["reason"] == "role_unresolved: test-forced"

    on_disk = registry.read_registry(registry_path)
    assert on_disk[record["session_id"]]["state"] == "resumed"


def test_maybe_trigger_handoff_boundary_is_at_or_above(tmp_path):
    """Criterion #2's ">= threshold" boundary (matches T007's mechanical
    fallback): exactly at the threshold still triggers."""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    record = _fresh_record(plan_dir, tmp_path / "transcript.jsonl")

    result = handoff.maybe_trigger_handoff(
        record,
        80.0,
        threshold_pct=80.0,
        registry_path=registry_path,
        signals_path=signals_path,
        repo_root=str(tmp_path),
        judge_dispatch=_succeeding_judge_dispatch,
    )

    assert result["triggered"] is True
    assert result["record"]["state"] == "resumed"


def test_maybe_trigger_handoff_below_threshold_is_noop(tmp_path):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    record = _fresh_record(plan_dir, tmp_path / "transcript.jsonl")

    result = handoff.maybe_trigger_handoff(
        record,
        79.9,
        threshold_pct=80.0,
        registry_path=registry_path,
        signals_path=signals_path,
        repo_root=str(tmp_path),
        judge_dispatch=_succeeding_judge_dispatch,
    )

    assert result["triggered"] is False
    assert result["reason"] == "below_threshold"
    assert result["record"] is record
    assert result["record"]["state"] == "running"
    assert not (plan_dir / "handoff.json").exists()
    assert not registry_path.exists()


def test_maybe_trigger_handoff_context_unknown_is_noop(tmp_path):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    record = _fresh_record(plan_dir, tmp_path / "transcript.jsonl")

    result = handoff.maybe_trigger_handoff(
        record,
        None,
        threshold_pct=80.0,
        registry_path=registry_path,
        signals_path=signals_path,
        repo_root=str(tmp_path),
        judge_dispatch=_succeeding_judge_dispatch,
    )

    assert result["triggered"] is False
    assert result["reason"] == "context_unknown"
    assert not registry_path.exists()
