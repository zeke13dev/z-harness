"""Tests for runtime/watchdog/handoff.py (context-threshold handoff state
machine).

Coverage (T010 acceptance, criteria #2/#3):
- an over-threshold record durably reaches ``handoff_written`` and writes
  ``handoff.json`` before the poll layer performs either host effect;
- the trigger boundary is at-or-above (``pct_used >= threshold_pct``), not
  strictly-above — exactly at the threshold still triggers, just below does
  not;
- a ``context_unknown`` (``None``) reading never triggers;
- a judge-unavailable dispatch still prepares handoff through the mechanical
  fallback and appends exactly one ``judge_degraded``
  entry to ``signals.jsonl``.

Tests substitute a stub ``judge_dispatch`` throughout (STYLE.md:T-002 note:
the real judge dispatch shells out to a provider CLI and is covered by
``test_watchdog_judge.py`` already; this module's own contract is the
choreography around whatever ``judge_dispatch`` returns) and pin every
artifact under ``tmp_path`` (STYLE.md:T-004) — no real registry/signals file
outside the test's own temp dir is ever touched.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import threading
import time
from pathlib import Path

import pytest

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


def test_maybe_trigger_handoff_prepares_host_stage(tmp_path):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    signals_path = tmp_path / "signals.jsonl"
    record = _fresh_record(plan_dir, tmp_path / "transcript.jsonl")

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
    assert result["record"]["state"] == "handoff_written"
    assert result["judge_degraded"] is None

    # Host actuation belongs to poll.py, so durable lifecycle state stops before
    # the first host effect rather than claiming the coordinator already resumed.
    on_disk = registry.read_registry(registry_path)
    assert on_disk[record["session_id"]]["state"] == "handoff_written"

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
    assert result["record"]["state"] == "handoff_written"
    assert result["judge_degraded"] is not None
    assert result["verdict"]["source"] == "mechanical_fallback"

    lines = signals_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "exactly one judge_degraded entry"
    event = json.loads(lines[0])
    assert event["kind"] == "judge_degraded"
    assert event["payload"]["reason"] == "role_unresolved: test-forced"

    on_disk = registry.read_registry(registry_path)
    assert on_disk[record["session_id"]]["state"] == "handoff_written"


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
    assert result["record"]["state"] == "handoff_written"


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


def test_rollover_is_replayable_and_fences_the_old_generation(tmp_path):
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    record = _fresh_record(plan_dir, tmp_path / "old.jsonl")
    registry.write_registry(registry_path, {record["session_id"]: record})
    generation = registry.coordinator_generation_for(record)

    first, replayed, artifact = handoff.rollover_coordinator(
        registry_path, session_id=record["session_id"], expected_generation=generation,
        target="zw-new:0.0", transcript_path=str(tmp_path / "new.jsonl"), now="2026-07-16T00:00:00Z",
    )
    assert replayed is False and artifact.is_file()
    current = registry.read_registry(registry_path)[record["session_id"]]
    assert current["tmux_target"] == "zw-new:0.0"
    assert current["coordinator_incarnation"] == 2
    assert first["to_generation"] == registry.coordinator_generation_for(current)

    second, replayed, _ = handoff.rollover_coordinator(
        registry_path, session_id=record["session_id"], expected_generation=generation,
        target="zw-new:0.0", transcript_path=str(tmp_path / "new.jsonl"), now="2026-07-16T00:00:00Z",
    )
    assert replayed is True and second["rollover_id"] == first["rollover_id"]
    assert registry.read_registry(registry_path)[record["session_id"]] == current


def test_rollover_allows_a_new_transfer_after_a_committed_replay_generation(tmp_path):
    """Completed intents replay on their old fence but do not block the next one."""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    record = _fresh_record(plan_dir, tmp_path / "old.jsonl")
    registry.write_registry(registry_path, {record["session_id"]: record})

    first, replayed, _ = handoff.rollover_coordinator(
        registry_path,
        session_id=record["session_id"],
        expected_generation=registry.coordinator_generation_for(record),
        target="zw-new:0.0",
        transcript_path=str(tmp_path / "new.jsonl"),
        now="2026-07-16T00:00:00Z",
    )
    assert replayed is False
    after_first = registry.read_registry(registry_path)[record["session_id"]]

    second, replayed, _ = handoff.rollover_coordinator(
        registry_path,
        session_id=record["session_id"],
        expected_generation=registry.coordinator_generation_for(after_first),
        target="zw-newer:0.0",
        transcript_path=str(tmp_path / "newer.jsonl"),
        now="2026-07-16T00:01:00Z",
    )

    assert replayed is False
    assert second["rollover_id"] != first["rollover_id"]
    current = registry.read_registry(registry_path)[record["session_id"]]
    assert current["tmux_target"] == "zw-newer:0.0"
    assert current["coordinator_incarnation"] == 3


def test_concurrent_rollovers_leave_canonical_handoff_at_authoritative_target(tmp_path, monkeypatch):
    """A later rollover cannot be overwritten by an older publisher."""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    record = _fresh_record(plan_dir, tmp_path / "old.jsonl")
    registry.write_registry(registry_path, {record["session_id"]: record})
    first_generation = registry.coordinator_generation_for(record)
    second_generation = f"coordinator:v1:{record['session_id']}:{record['state_generation'] + 1}"
    entered_publish = threading.Event()
    release_publish = threading.Event()
    original_write = registry.atomic_write_json
    original_hold = registry.hold_registry_lock
    second_waiting_for_lock = threading.Event()
    lock_entries = 0
    lock_entries_guard = threading.Lock()

    @contextmanager
    def observed_registry_lock(path):
        nonlocal lock_entries
        with lock_entries_guard:
            lock_entries += 1
            if lock_entries == 2:
                # Prove the later rollover has reached the registry-lock race
                # point before allowing the older publisher to continue.
                second_waiting_for_lock.set()
        with original_hold(path):
            yield

    def delayed_handoff_write(path, obj, *, lock=True):
        if Path(path) == plan_dir / "handoff.json" and not entered_publish.is_set():
            entered_publish.set()
            assert release_publish.wait(timeout=2)
        return original_write(path, obj, lock=lock)

    monkeypatch.setattr(registry, "atomic_write_json", delayed_handoff_write)
    monkeypatch.setattr(registry, "hold_registry_lock", observed_registry_lock)
    errors: list[BaseException] = []

    def first() -> None:
        try:
            handoff.rollover_coordinator(
                registry_path, session_id=record["session_id"], expected_generation=first_generation,
                target="zw-first:0.0", transcript_path=str(tmp_path / "first.jsonl"),
            )
        except BaseException as exc:  # pragma: no cover - assertion surface below
            errors.append(exc)

    def second() -> None:
        try:
            handoff.rollover_coordinator(
                registry_path, session_id=record["session_id"], expected_generation=second_generation,
                target="zw-second:0.0", transcript_path=str(tmp_path / "second.jsonl"),
            )
        except BaseException as exc:  # pragma: no cover - assertion surface below
            errors.append(exc)

    first_thread = threading.Thread(target=first)
    first_thread.start()
    assert entered_publish.wait(timeout=2)
    second_thread = threading.Thread(target=second)
    second_thread.start()
    assert second_waiting_for_lock.wait(timeout=2)
    release_publish.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert not errors
    current = registry.read_registry(registry_path)[record["session_id"]]
    artifact = json.loads((plan_dir / "handoff.json").read_text())
    assert current["tmux_target"] == artifact["target"] == "zw-second:0.0"
    assert artifact["to_generation"] == registry.coordinator_generation_for(current)


def test_rollover_rebases_a_prepared_intent_after_its_generation_changes(tmp_path):
    """A crash-window intent cannot permanently block a later fresh rollover."""
    plan_dir = tmp_path / "plan"
    plan_dir.mkdir()
    registry_path = tmp_path / "sessions.json"
    record = _fresh_record(plan_dir, tmp_path / "old.jsonl")
    registry.write_registry(registry_path, {record["session_id"]: record})
    original_generation = registry.coordinator_generation_for(record)
    stale, replayed = registry.prepare_coordinator_rollover(
        registry_path,
        session_id=record["session_id"],
        expected_generation=original_generation,
        target="zw-abandoned:0.0",
        transcript_path=str(tmp_path / "abandoned.jsonl"),
        now="2026-07-16T00:00:00Z",
    )
    assert replayed is False

    def advance_generation(document):
        current = document["sessions"][record["session_id"]]
        current["state_generation"] += 1

    registry.locked_registry_document_update(registry_path, advance_generation)
    fresh = registry.read_registry(registry_path)[record["session_id"]]
    fresh_generation = registry.coordinator_generation_for(fresh)
    rebased, replayed = registry.prepare_coordinator_rollover(
        registry_path,
        session_id=record["session_id"],
        expected_generation=fresh_generation,
        target="zw-recovered:0.0",
        transcript_path=str(tmp_path / "recovered.jsonl"),
        now="2026-07-16T00:01:00Z",
    )

    assert replayed is False
    assert rebased["rollover_id"] != stale["rollover_id"]
    with pytest.raises(registry.StaleCoordinatorRolloverError):
        registry.commit_coordinator_rollover(
            registry_path,
            session_id=record["session_id"],
            rollover_id=stale["rollover_id"],
        )
    committed, replayed = registry.commit_coordinator_rollover(
        registry_path,
        session_id=record["session_id"],
        rollover_id=rebased["rollover_id"],
        now="2026-07-16T00:02:00Z",
    )
    assert replayed is False
    assert committed["target"] == "zw-recovered:0.0"
