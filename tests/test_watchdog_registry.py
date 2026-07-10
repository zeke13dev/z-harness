"""Tests for runtime/watchdog/registry.py (session-watchdog registry primitives).

Coverage (T003 acceptance, criterion #9):
- concurrent-write safety: many processes writing the same registry never leave
  a torn/partial file a reader can observe;
- transition validation: illegal transitions are rejected, accepted ones stamp
  ``state_changed_at``;
- pidlock staleness cleanup + single-instance rejection;
- every write leaves valid JSON matching the schema;
- id/name generator contracts (``ws-`` / ``zw-``) and the signals.jsonl append.

Tests are hermetic (STYLE.md:T-004): all filesystem effects go under pytest's
``tmp_path`` fixture — no real z-harness artifacts are touched. The one config
integration test only *reads* the repo config (read-only).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime.watchdog import registry


# ── module-level worker for the cross-process concurrency test ───────────────
# Must be importable (multiprocessing spawn pickles the target by qualified name).

def _concurrent_writer(path_str: str, session_id: str, iterations: int) -> None:
    """Write a single-record registry ``iterations`` times to ``path_str``.

    Each write uses the same flock-guarded atomic primitive the daemon uses, so
    concurrent invocations exercise real cross-process serialization.
    """
    record = registry.new_session_record(
        slug="concurrent",
        plan_dir="/plans/concurrent",
        host="claude",
        tmux_target="zw-concurrent-0",
        transcript_path="/t/transcript.jsonl",
        session_id=session_id,
    )
    for _ in range(iterations):
        registry.write_registry(path_str, {session_id: record})


# ── id / name generators ──────────────────────────────────────────────────────

def test_session_id_contract_and_uniqueness() -> None:
    ids = {registry.new_session_id() for _ in range(500)}
    assert len(ids) == 500  # collision-resistant
    for sid in ids:
        assert sid.startswith("ws-")
        # ws- + a 36-char uuid4 string.
        assert len(sid) == len("ws-") + 36


def test_tmux_name_contract_sanitizes_and_is_unique() -> None:
    names = {registry.new_tmux_name("session-watchdog") for _ in range(200)}
    assert len(names) == 200
    for name in names:
        assert name.startswith("zw-")
        assert "session-watchdog" in name

    # Unsafe tmux characters (``.``/``:``/spaces) are stripped from the slug.
    dirty = registry.new_tmux_name("Foo.Bar:Baz Qux")
    assert dirty.startswith("zw-")
    body = dirty[len("zw-"):]
    assert "." not in body and ":" not in body and " " not in body
    assert body.startswith("foo-bar-baz-qux-")


# ── schema factory + validator ────────────────────────────────────────────────

def test_new_record_has_complete_field_set_and_validates() -> None:
    record = registry.new_session_record(
        slug="s",
        plan_dir="/p",
        host="codex",
        tmux_target="zw-s-1",
        transcript_path="/t.jsonl",
    )
    assert set(record.keys()) == registry.REQUIRED_FIELDS
    assert record["schema_version"] == registry.SCHEMA_VERSION
    assert record["state"] == registry.INITIAL_STATE
    assert record["transcript_offset"] == 0
    assert record["children"] == []
    assert record["parent_id"] is None
    registry.validate_record(record)  # must not raise


def test_new_record_rejects_unknown_host() -> None:
    with pytest.raises(ValueError):
        registry.new_session_record(
            slug="s", plan_dir="/p", host="bogus",
            tmux_target="t", transcript_path="/t",
        )


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("session_id"),
    lambda r: r.__setitem__("state", "not_a_state"),
    lambda r: r.__setitem__("host", "bogus"),
    lambda r: r.__setitem__("children", "nope"),
    lambda r: r.__setitem__("nudge_count", -1),
    lambda r: r.__setitem__("transcript_offset", -5),
    lambda r: r.__setitem__("schema_version", 999),
])
def test_validate_record_rejects_malformed(mutate) -> None:
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="omp",
        tmux_target="t", transcript_path="/t",
    )
    mutate(record)
    with pytest.raises(ValueError):
        registry.validate_record(record)


# ── state transitions ─────────────────────────────────────────────────────────

def test_accepted_transition_stamps_state_changed_at() -> None:
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
        now="2026-01-01T00:00:00Z",
    )
    assert record["state_changed_at"] == "2026-01-01T00:00:00Z"

    moved = registry.transition(record, "running", now="2026-01-01T01:00:00Z")
    assert moved["state"] == "running"
    assert moved["state_changed_at"] == "2026-01-01T01:00:00Z"
    # Source record is not mutated (functional update).
    assert record["state"] == "registered"


def test_full_handoff_choreography_is_valid_and_stamps_each_step() -> None:
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
    )
    record = registry.transition(record, "running", now="t0")
    chain = ["handoff_requested", "handoff_written", "cleared", "resumed"]
    for i, state in enumerate(chain):
        record = registry.transition(record, state, now=f"stamp-{i}")
        assert record["state"] == state
        assert record["state_changed_at"] == f"stamp-{i}"


@pytest.mark.parametrize("src,dst", [
    ("cleared", "handoff_requested"),   # explicitly-named illegal transition
    ("done", "running"),                # terminal cannot restart
    ("orphaned", "running"),            # terminal, never auto-adopted
    ("failed", "resumed"),              # terminal cannot resume
    ("needs_input", "cleared"),         # cannot enter handoff mid-flow
    ("running", "running"),             # self-transition is not a transition
])
def test_invalid_transitions_are_rejected(src: str, dst: str) -> None:
    assert registry.is_valid_transition(src, dst) is False
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
    )
    record["state"] = src
    with pytest.raises(registry.InvalidTransitionError):
        registry.transition(record, dst)


def test_transition_rejects_unknown_target_state() -> None:
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
    )
    with pytest.raises(registry.InvalidTransitionError):
        registry.transition(record, "teleported")


def test_terminal_states_have_no_exits() -> None:
    for term in registry.TERMINAL_STATES:
        assert registry.is_terminal(term)
        for other in registry.VALID_STATES:
            assert registry.is_valid_transition(term, other) is False


# ── atomic write + registry round-trip ────────────────────────────────────────

def test_write_registry_round_trips_and_stays_schema_valid(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="zw-s-1", transcript_path="/t.jsonl",
    )
    registry.write_registry(path, {record["session_id"]: record})

    # File is valid JSON with the expected envelope.
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == registry.SCHEMA_VERSION
    assert record["session_id"] in raw["sessions"]

    # read_registry recovers the record and it re-validates.
    sessions = registry.read_registry(path)
    assert sessions == {record["session_id"]: record}
    registry.validate_record(sessions[record["session_id"]])


def test_write_registry_refuses_invalid_record(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    record = registry.new_session_record(
        slug="s", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
    )
    record["state"] = "bogus"
    with pytest.raises(ValueError):
        registry.write_registry(path, {record["session_id"]: record})
    # Nothing partial written.
    assert not path.exists()


def test_read_registry_tolerates_missing_and_corrupt(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert registry.read_registry(missing) == {}

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    assert registry.read_registry(corrupt) == {}


def test_concurrent_writes_never_expose_torn_json(tmp_path: Path) -> None:
    """Cross-process writers + a racing reader: the file always parses.

    STYLE.md:P-006 / inv_003 — os.replace publishes the whole file atomically,
    so a reader observes either the old or the new registry but never a partial.
    """
    import multiprocessing as mp

    path = tmp_path / "sessions.json"
    # Seed a valid file so the reader has something to observe from the start.
    seed = registry.new_session_record(
        slug="seed", plan_dir="/p", host="claude",
        tmux_target="t", transcript_path="/t",
    )
    registry.write_registry(path, {seed["session_id"]: seed})

    ctx = mp.get_context("spawn")
    workers = [
        ctx.Process(
            target=_concurrent_writer,
            args=(str(path), registry.new_session_id(), 60),
        )
        for _ in range(4)
    ]
    for w in workers:
        w.start()

    # Race the writers with repeated reads; each must parse as a valid registry.
    deadline = time.monotonic() + 10
    reads = 0
    while any(w.is_alive() for w in workers) and time.monotonic() < deadline:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)  # would raise on a torn write
        assert parsed["schema_version"] == registry.SCHEMA_VERSION
        assert len(parsed["sessions"]) == 1
        reads += 1

    for w in workers:
        w.join(timeout=10)
        assert w.exitcode == 0

    assert reads > 0
    # Final state is a single valid record from one writer.
    final = registry.read_registry(path)
    assert len(final) == 1
    (only_record,) = final.values()
    registry.validate_record(only_record)


# ── daemon single-instance pidfile lock ──────────────────────────────────────

def _dead_pid() -> int:
    """Return a pid guaranteed dead (a reaped child), for stale-lock tests."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_pidlock_single_instance_rejects_second_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    fd = registry.acquire_single_instance_lock(lock_path)
    try:
        assert registry.read_lock_pid(lock_path) == os.getpid()
        with pytest.raises(registry.DaemonAlreadyRunningError):
            registry.acquire_single_instance_lock(lock_path)
    finally:
        registry.release_single_instance_lock(fd, lock_path)

    # After release, the lock can be acquired again.
    fd2 = registry.acquire_single_instance_lock(lock_path)
    registry.release_single_instance_lock(fd2, lock_path)


def test_pidlock_cleans_stale_lock_from_dead_pid(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    # Simulate a crashed daemon: a pidfile naming a dead pid, no flock holder.
    lock_path.write_text(f"{_dead_pid()}\n", encoding="utf-8")

    fd = registry.acquire_single_instance_lock(lock_path)
    try:
        # Stale pid was overwritten with our own — automatic cleanup.
        assert registry.read_lock_pid(lock_path) == os.getpid()
    finally:
        registry.release_single_instance_lock(fd, lock_path)


# ── signals.jsonl append ──────────────────────────────────────────────────────

def test_append_signal_writes_structured_jsonl(tmp_path: Path) -> None:
    signals = tmp_path / "signals.jsonl"
    registry.append_signal(
        signals, "judge_degraded", {"reason": "timeout"},
        max_mb=50, now="2026-01-01T00:00:00Z",
    )
    registry.append_signal(
        signals, "orphaned", {"session_id": "ws-x"},
        max_mb=50,
    )
    lines = signals.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "ts": "2026-01-01T00:00:00Z",
        "kind": "judge_degraded",
        "payload": {"reason": "timeout"},
    }
    second = json.loads(lines[1])
    assert second["kind"] == "orphaned"
    assert second["payload"] == {"session_id": "ws-x"}


def test_append_signal_rotates_when_over_cap(tmp_path: Path) -> None:
    signals = tmp_path / "signals.jsonl"
    # Pre-fill just over a 1 MiB cap so the next append triggers rotation.
    signals.write_text("x" * (1024 * 1024 + 16), encoding="utf-8")
    registry.append_signal(signals, "judge_degraded", {"n": 1}, max_mb=1)

    rotated = Path(str(signals) + ".1")
    assert rotated.exists()
    # The live file now holds only the fresh event.
    lines = signals.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "judge_degraded"


def test_get_config_int_resolves_signals_max_mb() -> None:
    """Integration: the size cap is resolved from config, never hardcoded (T002)."""
    value = registry.get_config_int("watchdog.signals_max_mb")
    assert isinstance(value, int)
    assert value > 0
