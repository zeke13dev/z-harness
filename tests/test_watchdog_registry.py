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

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime.watchdog import notify, registry


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
    assert record["schema_version"] == registry.RECORD_SCHEMA_VERSION
    assert record["state"] == registry.INITIAL_STATE
    assert record["transcript_offset"] == 0
    assert record["children"] == []
    assert record["parent_id"] is None
    registry.validate_record(record)  # must not raise


def test_record_and_registry_versions_remain_separate_public_contracts() -> None:
    assert registry.SCHEMA_VERSION == 1
    assert registry.RECORD_SCHEMA_VERSION == registry.SCHEMA_VERSION
    assert registry.REGISTRY_VERSION == 2


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
    assert raw["registry_version"] == registry.REGISTRY_VERSION
    assert set(raw) == {
        "schema_version", "registry_version", *registry.REGISTRY_SECTIONS
    }
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


def test_read_registry_tolerates_missing_but_rejects_corrupt(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert registry.read_registry(missing) == {}

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(registry.RegistryFormatError, match="malformed registry JSON"):
        registry.read_registry(corrupt)


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
        assert parsed["registry_version"] == registry.REGISTRY_VERSION
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


def test_v1_registry_migrates_to_complete_v2_under_lock(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    record = _rec("legacy", "ws-legacy")
    path.write_text(
        json.dumps({"schema_version": 1, "sessions": {"ws-legacy": record}}),
        encoding="utf-8",
    )

    document = registry.read_registry_document(path)

    assert document["schema_version"] == registry.SCHEMA_VERSION
    assert document["registry_version"] == registry.REGISTRY_VERSION
    assert set(document) == {
        "schema_version", "registry_version", *registry.REGISTRY_SECTIONS
    }
    assert document["sessions"] == {"ws-legacy": record}
    assert json.loads(path.read_text(encoding="utf-8")) == document


def test_registry_rejects_malformed_coordinator_rollover_before_operations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.json"
    record = _rec("coordinator", "ws-coordinator")
    generation = registry.coordinator_generation_for(record)
    # Constructing the fixture directly keeps every corrupt case independent
    # of the lifecycle APIs the loader must protect.
    rollover = {
        "rollover_id": "rollover:v1:" + hashlib.sha256(
            f"ws-coordinator\0{generation}\0{2}".encode()
        ).hexdigest(),
        "logical_coordinator_id": "ws-coordinator",
        "from_generation": generation,
        "from_incarnation": 1,
        "to_incarnation": 2,
        "target": "zw-coordinator:0.0",
        "transcript_path": "/tmp/coordinator.jsonl",
        "prepared_at": "2026-07-16T00:00:00Z",
    }
    record["rollover"] = rollover
    registry.write_registry(path, {record["session_id"]: record})
    baseline = path.read_text(encoding="utf-8")

    corruptions = [
        ("coordinator_incarnation", "two"),
        ("rollover.logical_coordinator_id", "ws-other"),
        ("rollover.from_generation", "coordinator:v1:ws-coordinator:not-a-number"),
        ("rollover.to_incarnation", 3),
        ("rollover.committed_at", "2026-07-16T00:01:00Z"),
    ]
    for field, value in corruptions:
        path.write_text(baseline, encoding="utf-8")
        payload = registry.read_registry_document(path)
        candidate = payload["sessions"][record["session_id"]]
        if "." in field:
            _, nested = field.split(".", 1)
            candidate["rollover"][nested] = value
        else:
            candidate[field] = value
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(
            registry.RegistryFormatError, match="invalid session record"
        ):
            registry.read_registry_document(path)


@pytest.mark.parametrize(
    "field, value, match",
    [
        ("tmux_target", "zw-stale:0.0", "committed rollover target mismatch"),
        (
            "transcript_path",
            "/tmp/stale-coordinator.jsonl",
            "committed rollover transcript mismatch",
        ),
        ("transcript_offset", 1, "committed rollover transcript offset must be zero"),
    ],
)
def test_registry_rejects_committed_rollover_that_disagrees_with_authority(
    tmp_path: Path, field: str, value: object, match: str
) -> None:
    """A committed rollover's destination is current coordinator authority."""
    path = tmp_path / "sessions.json"
    record = _rec("coordinator", "ws-coordinator")
    registry.write_registry(path, {record["session_id"]: record})
    generation = registry.coordinator_generation_for(record)
    prepared, replayed = registry.prepare_coordinator_rollover(
        path,
        session_id=record["session_id"],
        expected_generation=generation,
        target="zw-coordinator:0.0",
        transcript_path="/tmp/coordinator.jsonl",
        now="2026-07-16T00:00:00Z",
    )
    assert replayed is False
    registry.commit_coordinator_rollover(
        path,
        session_id=record["session_id"],
        rollover_id=prepared["rollover_id"],
        now="2026-07-16T00:01:00Z",
    )

    document = registry.read_registry_document(path)
    document["sessions"][record["session_id"]][field] = value
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(registry.RegistryFormatError, match=match):
        registry.read_registry_document(path)


@pytest.mark.parametrize(
    "payload, error_type",
    [
        ({"schema_version": 999}, registry.UnsupportedRegistryVersionError),
        (
            {"schema_version": 2, "registry_version": 2, "sessions": {}},
            registry.RegistryFormatError,
        ),
        ({"registry_version": 2, "sessions": []}, registry.RegistryFormatError),
    ],
)
def test_registry_rejects_future_mixed_and_malformed_state(
    tmp_path: Path, payload: object, error_type: type[Exception]
) -> None:
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(error_type):
        registry.read_registry_document(path)


def test_interrupted_replacement_recovers_valid_next_document(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    registry.write_registry(path, {"ws-old": _rec("old", "ws-old")})
    replacement = registry.read_registry_document(path)
    replacement["sessions"] = {"ws-new": _rec("new", "ws-new")}
    next_path = path.with_name(f".{path.name}.next")
    next_path.write_text(json.dumps(replacement), encoding="utf-8")

    recovered = registry.read_registry_document(path)

    assert set(recovered["sessions"]) == {"ws-new"}
    assert json.loads(path.read_text(encoding="utf-8")) == recovered
    assert not next_path.exists()


def test_interrupted_replacement_migrates_valid_v1_candidate(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    registry.write_registry(path, {"ws-old": _rec("old", "ws-old")})
    next_path = path.with_name(f".{path.name}.next")
    legacy_record = _rec("new", "ws-new")
    legacy_record.pop("state_generation")
    next_path.write_text(
        json.dumps({
            "schema_version": 1,
            "sessions": {"ws-new": legacy_record},
        }),
        encoding="utf-8",
    )

    recovered = registry.read_registry_document(path)

    assert recovered["registry_version"] == registry.REGISTRY_VERSION
    assert set(recovered["sessions"]) == {"ws-new"}
    assert recovered["sessions"]["ws-new"]["state_generation"] == 0
    assert json.loads(path.read_text(encoding="utf-8")) == recovered
    assert not next_path.exists()


def test_malformed_recovery_candidate_fails_loudly_without_deletion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.json"
    registry.write_registry(path, {"ws-old": _rec("old", "ws-old")})
    next_path = path.with_name(f".{path.name}.next")
    next_path.write_text("{malformed", encoding="utf-8")

    with pytest.raises(registry.RegistryFormatError, match="malformed registry JSON"):
        registry.read_registry_document(path)

    assert next_path.read_text(encoding="utf-8") == "{malformed"


# ── locked_registry_update (serialized read-modify-write, T-REV-001) ─────────

def _rec(slug: str, session_id: str) -> dict:
    return registry.new_session_record(
        slug=slug, plan_dir="/p", host="claude",
        tmux_target=f"zw-{slug}-1", transcript_path="/t",
        session_id=session_id,
    )


def test_locked_registry_update_merges_onto_fresh_read(tmp_path: Path) -> None:
    """The mutate fn is applied to a FRESH re-read, not a stale snapshot: a
    record another writer persisted since is preserved (T-REV-001)."""
    path = tmp_path / "sessions.json"
    registry.write_registry(path, {"ws-a": _rec("a", "ws-a")})

    # Another writer lands a record on disk before our update runs.
    on_disk = registry.read_registry(path)
    on_disk["ws-b"] = _rec("b", "ws-b")
    registry.write_registry(path, on_disk)

    def _add_c(fresh: dict) -> None:
        # The fresh mapping must already reflect ws-b (the merge base is the
        # locked re-read), and we only add our own record.
        assert "ws-b" in fresh
        fresh["ws-c"] = _rec("c", "ws-c")

    merged = registry.locked_registry_update(path, _add_c)

    assert set(merged) == {"ws-a", "ws-b", "ws-c"}
    assert set(registry.read_registry(path)) == {"ws-a", "ws-b", "ws-c"}


def test_locked_registry_update_serializes_concurrent_updates(tmp_path: Path) -> None:
    """Two threads each adding their own record via locked_registry_update lose
    nothing: the sidecar lock serializes the read-modify-write cycles so neither
    add clobbers the other (T-REV-001, the "no session record is lost" contract
    at the primitive level)."""
    import threading

    path = tmp_path / "sessions.json"
    registry.write_registry(path, {"ws-seed": _rec("seed", "ws-seed")})

    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def _adder(session_id: str) -> None:
        try:
            start.wait(timeout=5)
            registry.locked_registry_update(
                path, lambda fresh: fresh.__setitem__(session_id, _rec("w", session_id))
            )
        except BaseException as exc:  # noqa: BLE001 — surfaced via assertion
            errors.append(exc)

    threads = [
        threading.Thread(target=_adder, args=(sid,))
        for sid in ("ws-w1", "ws-w2")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"a concurrent update raised: {errors}"
    final = registry.read_registry(path)
    # The seed and BOTH concurrent adds survive — no lost update.
    assert set(final) == {"ws-seed", "ws-w1", "ws-w2"}


def test_snapshot_write_applies_only_changed_fields_to_fresh_state(
    tmp_path: Path,
) -> None:
    """A handoff-style stale snapshot cannot erase concurrent allocation."""
    path = tmp_path / "sessions.json"
    origin = _rec("origin", "ws-origin")
    registry.write_registry(path, {origin["session_id"]: origin})
    handoff_snapshot = registry.read_registry(path)
    child = _rec("child", "ws-child")
    child["parent_id"] = origin["session_id"]

    def _allocate(fresh: dict[str, dict]) -> None:
        fresh[origin["session_id"]]["children"].append(child["session_id"])
        fresh[child["session_id"]] = child

    registry.locked_registry_update(path, _allocate)
    handoff_snapshot[origin["session_id"]] = registry.transition(
        handoff_snapshot[origin["session_id"]],
        "handoff_requested",
        now="2026-07-14T20:00:00Z",
    )
    registry.write_registry(path, handoff_snapshot)

    persisted = registry.read_registry(path)
    assert set(persisted) == {"ws-origin", "ws-child"}
    assert persisted["ws-origin"]["children"] == ["ws-child"]
    assert persisted["ws-origin"]["state"] == "handoff_requested"


def test_locked_document_updates_preserve_every_v2_lifecycle_section(
    tmp_path: Path,
) -> None:
    """Concurrent minimal mutations retain every authoritative state category."""
    import threading

    path = tmp_path / "sessions.json"
    registry.write_registry(path, {"ws-seed": _rec("seed", "ws-seed")})
    manifest = {
        "schema_version": 1,
        "kind": "watchdog-supervision",
        "enabled": True,
    }
    coordinator, _replayed = registry.register_root_manifest(
        path, idempotency_key="root-v1:test", manifest=manifest
    )
    sections = [
        section
        for section in registry.REGISTRY_SECTIONS
        if section not in {"sessions", "coordinators", "outcomes"}
    ]
    barrier = threading.Barrier(len(sections))
    errors: list[BaseException] = []

    def _add(section: str) -> None:
        try:
            barrier.wait(timeout=5)

            def _mutate(document: dict[str, object]) -> None:
                document[section][f"{section}-1"] = {  # type: ignore[index]
                    "registry_version": registry.REGISTRY_VERSION,
                    "value": section,
                }

            registry.locked_registry_document_update(path, _mutate)
        except BaseException as exc:  # noqa: BLE001 — surfaced via assertion
            errors.append(exc)

    threads = [threading.Thread(target=_add, args=(section,)) for section in sections]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    document = registry.read_registry_document(path)
    assert set(document["sessions"]) == {"ws-seed"}
    assert document["coordinators"] == {"root-v1:test": coordinator}
    assert document["outcomes"] == {}
    for section in sections:
        assert document[section] == {
            f"{section}-1": {
                "registry_version": registry.REGISTRY_VERSION,
                "value": section,
            }
        }


def test_root_registration_is_exactly_idempotent_and_conflict_safe(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.json"
    manifest_path = tmp_path / "plan" / "supervision-manifest.json"
    manifest = {"schema_version": 1, "kind": "watchdog-supervision", "enabled": True}
    key = registry.root_idempotency_key(manifest_path)

    first, replayed = registry.register_root_manifest(
        path, idempotency_key=key, manifest=manifest
    )
    replay, replayed_again = registry.register_root_manifest(
        path, idempotency_key=key, manifest=dict(manifest)
    )

    assert replayed is False
    assert replayed_again is True
    assert replay == first
    assert registry.read_registry_document(path)["coordinators"] == {key: first}
    with pytest.raises(registry.RootRegistrationConflictError):
        registry.register_root_manifest(
            path,
            idempotency_key=key,
            manifest={**manifest, "enabled": False},
        )
    assert registry.read_registry_document(path)["coordinators"] == {key: first}


def test_malformed_coordinator_entry_is_rejected_before_replay(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    manifest = {"schema_version": 1, "kind": "watchdog-supervision", "enabled": True}
    key = "root-v1:test"
    registry.register_root_manifest(path, idempotency_key=key, manifest=manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["coordinators"][key]["coordinator_id"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(registry.RegistryFormatError, match="missing fields"):
        registry.register_root_manifest(path, idempotency_key=key, manifest=manifest)


def _admitted_child(path: Path) -> dict:
    parent = _rec("parent", "ws-parent")
    report_capability = "test-child-report-capability"
    child = registry.new_session_record(
        "child", "/plans/child", "claude", "zw-child", "/tmp/child.jsonl",
        session_id="ws-child", parent_id=parent["session_id"],
        report_capability=report_capability,
        child_lease_timeout_s=30, child_grace_s=30,
        now="2026-07-14T10:00:00Z",
    )
    child = registry.transition(child, "running", now="2026-07-14T10:00:01Z")
    parent["children"] = [child["session_id"]]
    registry.write_registry(path, {parent["session_id"]: parent, child["session_id"]: child})
    child["_report_capability"] = report_capability
    return child


def test_authorized_child_outcome_persists_provenance_and_exact_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)
    generation = registry.child_generation(child)
    evidence = {"artifact": "/plans/child/RESULT.json", "exit_code": 0}

    outcome, replayed = registry.report_child_outcome(
        path, child_id=child["session_id"], generation=generation,
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="done", evidence=evidence,
        now="2026-07-14T10:05:00Z",
    )
    replay, replayed_again = registry.report_child_outcome(
        path, child_id=child["session_id"], generation=generation,
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="done", evidence=dict(evidence),
        now="2026-07-14T10:06:00Z",
    )

    document = registry.read_registry_document(path)
    assert replayed is False and replayed_again is True
    assert replay == outcome
    assert document["sessions"][child["session_id"]]["state"] == "done"
    assert document["outcomes"] == {outcome["outcome_id"]: outcome}
    assert outcome["reporter"] == {
        "kind": "allocation_capability", "id": child["session_id"]
    }
    assert outcome["evidence"] == evidence


@pytest.mark.parametrize("failure", ["unauthorized", "stale", "conflict"])
def test_invalid_child_reports_do_not_change_lifecycle_state(
    tmp_path: Path, failure: str,
) -> None:
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)
    generation = registry.child_generation(child)
    if failure == "conflict":
        registry.report_child_outcome(
            path, child_id=child["session_id"], generation=generation,
            reporter_id=child["session_id"],
            report_capability=child["_report_capability"],
            state="done", evidence={"ok": True},
        )
        before = registry.read_registry_document(path)
        error = registry.ChildOutcomeConflictError
        kwargs = {"reporter_id": child["session_id"],
                  "report_capability": child["_report_capability"],
                  "generation": generation,
                  "state": "failed", "evidence": {"exit_code": 1}}
    else:
        before = registry.read_registry_document(path)
        error = (
            registry.UnauthorizedChildReporterError
            if failure == "unauthorized" else registry.StaleChildGenerationError
        )
        kwargs = {
            "reporter_id": child["session_id"],
            "report_capability": (
                "wrong-capability" if failure == "unauthorized"
                else child["_report_capability"]
            ),
            "generation": generation if failure == "unauthorized" else "stale-generation",
            "state": "done", "evidence": {"ok": True},
        }

    with pytest.raises(error):
        registry.report_child_outcome(path, child_id=child["session_id"], **kwargs)

    assert registry.read_registry_document(path) == before


def test_lease_and_grace_bound_reaping_and_preserve_explicit_precedence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)
    generation = registry.child_generation(child)

    assert registry.reap_child_lease(
        path, child_id=child["session_id"], generation=generation,
        reachable=False, observed_at="2026-07-14T10:01:00Z",
    ) is None
    reaped = registry.reap_child_lease(
        path, child_id=child["session_id"], generation=generation,
        reachable=None, observed_at="2026-07-14T10:01:02Z",
    )
    assert reaped is not None and reaped["state"] == "orphaned"
    assert reaped["source"] == "lease_reaper"

    explicit, _ = registry.report_child_outcome(
        path, child_id=child["session_id"], generation=generation,
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="done", evidence={"result": "ok"},
        now="2026-07-14T10:01:02Z",
    )
    document = registry.read_registry_document(path)
    assert explicit["source"] == "explicit"
    assert document["sessions"][child["session_id"]]["state"] == "done"


def test_deadline_boundary_inference_wins_independent_of_claim_order(
    tmp_path: Path,
) -> None:
    durable_results = []
    for order in ("claim_first", "report_first"):
        path = tmp_path / f"{order}.json"
        child = _admitted_child(path)
        generation = registry.child_generation(child)
        reaped = registry.reap_child_lease(
            path,
            child_id=child["session_id"],
            generation=generation,
            reachable=False,
            observed_at="2026-07-14T10:01:02Z",
        )
        assert reaped is not None
        deadline = str(reaped["resolution_deadline"])

        def report_at_boundary() -> None:
            with pytest.raises(registry.ChildOutcomeConflictError, match="won at deadline"):
                registry.report_child_outcome(
                    path,
                    child_id=child["session_id"],
                    generation=generation,
                    reporter_id=child["session_id"],
                    report_capability=child["_report_capability"],
                    state="done",
                    evidence={"artifact": "RESULT.json"},
                    now=deadline,
                )

        if order == "claim_first":
            claimed = registry.claim_child_outcome_notification(
                path, str(reaped["outcome_id"]), now=deadline
            )
            report_at_boundary()
        else:
            report_at_boundary()
            claimed = registry.claim_child_outcome_notification(
                path, str(reaped["outcome_id"]), now=deadline
            )
        assert claimed is not None
        document = registry.read_registry_document(path)
        outcome = document["outcomes"][reaped["outcome_id"]]
        durable_results.append((document["sessions"][child["session_id"]]["state"], outcome))

    assert durable_results[0] == durable_results[1]
    assert durable_results[0][0] == "failed"
    assert durable_results[0][1]["source"] == "lease_reaper"
    assert durable_results[0][1]["notification_attempts"] == 1


def test_completion_reaping_barrier_always_resolves_to_explicit_outcome(
    tmp_path: Path,
) -> None:
    import threading

    path = tmp_path / "sessions.json"
    child = _admitted_child(path)
    generation = registry.child_generation(child)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    emitted = []

    def complete() -> None:
        try:
            barrier.wait(timeout=5)
            outcome, _ = registry.report_child_outcome(
                path, child_id=child["session_id"], generation=generation,
                reporter_id=child["session_id"],
                report_capability=child["_report_capability"],
                state="done",
                evidence={"artifact": "RESULT.json"}, now="2026-07-14T10:02:00Z",
            )
            emitted.append(notify.child_outcome_notification(outcome))
        except BaseException as exc:  # noqa: BLE001 — asserted below
            errors.append(exc)

    def reap() -> None:
        try:
            reaped = registry.reap_child_lease(
                path, child_id=child["session_id"], generation=generation,
                reachable=False, observed_at="2026-07-14T10:02:00Z",
            )
            barrier.wait(timeout=5)
            if reaped is not None:
                claimed = registry.claim_child_outcome_notification(
                    path, reaped["outcome_id"], now="2026-07-14T10:02:00Z"
                )
                if claimed is not None:
                    emitted.append(notify.child_outcome_notification(claimed))
        except BaseException as exc:  # noqa: BLE001 — asserted below
            errors.append(exc)

    threads = [threading.Thread(target=complete), threading.Thread(target=reap)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    document = registry.read_registry_document(path)
    outcome = next(iter(document["outcomes"].values()))
    assert outcome["state"] == "done" and outcome["source"] == "explicit"
    assert document["sessions"][child["session_id"]]["state"] == "done"
    assert [event.body for event in emitted] == [
        f"child_id={child['session_id']} state=done source=explicit "
        f"outcome_id={outcome['outcome_id']}"
    ]


def test_sealed_group_concurrent_final_outcomes_create_one_join_and_wake(
    tmp_path: Path,
) -> None:
    """Criterion #6: final transitions atomically create one stable join/outbox."""
    import threading

    path = tmp_path / "sessions.json"
    parent = _rec("root", "ws-root")
    parent = registry.transition(parent, "awaiting_children", now="2026-07-14T12:00:00Z")
    capabilities = {"ws-a": "cap-a", "ws-b": "cap-b"}
    children = {}
    for child_id, capability in capabilities.items():
        child = registry.new_session_record(
            child_id, f"/plans/{child_id}", "claude", f"zw-{child_id}", "",
            session_id=child_id, parent_id=parent["session_id"],
            report_capability=capability, now="2026-07-14T11:00:00Z",
        )
        children[child_id] = registry.transition(
            child, "running", now="2026-07-14T11:00:01Z"
        )
    parent["children"] = list(children)
    registry.write_registry(path, {parent["session_id"]: parent, **children})
    registry.locked_registry_update(path, lambda _sessions: None)
    group_id = registry.group_id_for(parent["session_id"])

    assert registry.read_registry_document(path)["joins"] == {}
    registry.seal_group(path, group_id, now="2026-07-14T12:01:00Z")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _finish(child_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            registry.report_child_outcome(
                path,
                child_id=child_id,
                generation=registry.child_generation(children[child_id]),
                reporter_id=child_id,
                report_capability=capabilities[child_id],
                state="done" if child_id == "ws-a" else "failed",
                evidence={"artifact": f"{child_id}.json"},
                now="2026-07-14T12:02:00Z",
            )
        except BaseException as exc:  # noqa: BLE001 — surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=_finish, args=(child_id,)) for child_id in children]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    document = registry.read_registry_document(path)
    assert len(document["joins"]) == len(document["outbox"]) == 1
    join = next(iter(document["joins"].values()))
    outbox = next(iter(document["outbox"].values()))
    assert join["outcomes"] == {"ws-a": "done", "ws-b": "failed"}
    assert outbox["join_id"] == join["join_id"]
    assert outbox["coordinator_generation"] == registry.coordinator_generation_for(parent)
    assert f"outbox_id={outbox['outbox_id']}" in outbox["text"]
    assert f"coordinator_generation={outbox['coordinator_generation']}" in outbox["text"]

    late = registry.new_session_record(
        "late", "/plans/late", "claude", "zw-late", "",
        session_id="ws-late", parent_id=parent["session_id"],
        report_capability="late-cap",
    )
    with pytest.raises(registry.GroupAdmissionError, match="sealed"):
        registry.locked_registry_update(path, lambda sessions: sessions.update({"ws-late": late}))
    assert "ws-late" not in registry.read_registry(path)


def test_provisional_reaper_outcome_defers_join_until_explicit_resolution(
    tmp_path: Path,
) -> None:
    """Criterion #6: provisional inference cannot freeze a stale wake summary."""
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)

    def _arm(sessions: dict[str, dict]) -> None:
        sessions["ws-parent"] = registry.transition(
            sessions["ws-parent"], "awaiting_children", now="2026-07-14T10:01:00Z"
        )

    registry.locked_registry_update(path, _arm)
    registry.seal_group(path, registry.group_id_for("ws-parent"))
    reaped = registry.reap_child_lease(
        path,
        child_id=child["session_id"],
        generation=registry.child_generation(child),
        reachable=False,
        observed_at="2026-07-14T10:01:02Z",
    )
    assert reaped is not None
    assert registry.materialize_ready_joins(
        path, now="2026-07-14T10:01:30Z"
    ) == []
    assert registry.read_registry_document(path)["joins"] == {}

    registry.report_child_outcome(
        path,
        child_id=child["session_id"],
        generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"],
        state="done",
        evidence={"artifact": "RESULT.json"},
        now="2026-07-14T10:01:30Z",
    )
    document = registry.read_registry_document(path)
    join = next(iter(document["joins"].values()))
    assert join["outcomes"] == {child["session_id"]: "done"}


@pytest.mark.parametrize("persistence_path", ["write_registry", "document_update"])
def test_all_document_writes_reject_late_parented_child_after_seal(
    tmp_path: Path, persistence_path: str,
) -> None:
    """Criterion #6: every persistence API reconciles sealed admissions."""
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)
    registry.seal_group(path, registry.group_id_for("ws-parent"))
    late = registry.new_session_record(
        "late", "/plans/late", "claude", "zw-late", "",
        session_id="ws-late", parent_id="ws-parent", report_capability="late-cap",
    )

    with pytest.raises(registry.GroupAdmissionError, match="sealed"):
        if persistence_path == "write_registry":
            sessions = registry.read_registry(path)
            sessions[late["session_id"]] = late
            registry.write_registry(path, sessions)
        else:
            registry.locked_registry_document_update(
                path,
                lambda document: document["sessions"].update({late["session_id"]: late}),
            )
    assert late["session_id"] not in registry.read_registry(path)


def test_same_second_coordinator_transitions_have_distinct_ack_fences(
    tmp_path: Path,
) -> None:
    """Criterion #6: generation fencing is monotonic, not timestamp-derived."""
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)

    def _arm(sessions: dict[str, dict]) -> None:
        sessions["ws-parent"] = registry.transition(
            sessions["ws-parent"], "awaiting_children", now="2026-07-14T12:00:00Z"
        )

    registry.locked_registry_update(path, _arm)
    registry.seal_group(path, registry.group_id_for("ws-parent"))
    registry.report_child_outcome(
        path, child_id=child["session_id"], generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"], state="done",
        evidence={"artifact": "RESULT.json"}, now="2026-07-14T12:00:00Z",
    )
    outbox = next(iter(registry.read_registry_document(path)["outbox"].values()))

    def _advance(sessions: dict[str, dict]) -> None:
        sessions["ws-parent"] = registry.transition(
            sessions["ws-parent"], "running", now="2026-07-14T12:00:00Z"
        )

    registry.locked_registry_update(path, _advance)
    parent = registry.read_registry(path)["ws-parent"]
    assert registry.coordinator_generation_for(parent) != outbox["coordinator_generation"]
    with pytest.raises(registry.StaleCoordinatorGenerationError):
        registry.acknowledge_join_wake(
            path, outbox["outbox_id"],
            coordinator_generation=outbox["coordinator_generation"],
        )


def test_join_ack_is_generation_fenced_and_exactly_once(tmp_path: Path) -> None:
    """Criterion #6: stable wakes deduplicate logical handling at acknowledgement."""
    path = tmp_path / "sessions.json"
    child = _admitted_child(path)

    def _arm(sessions: dict[str, dict]) -> None:
        sessions["ws-parent"] = registry.transition(
            sessions["ws-parent"], "awaiting_children", now="2026-07-14T12:00:00Z"
        )

    registry.locked_registry_update(path, _arm)
    group_id = registry.group_id_for("ws-parent")
    registry.seal_group(path, group_id)
    registry.report_child_outcome(
        path, child_id=child["session_id"], generation=registry.child_generation(child),
        reporter_id=child["session_id"],
        report_capability=child["_report_capability"], state="done",
        evidence={"artifact": "RESULT.json"},
    )
    outbox = next(iter(registry.read_registry_document(path)["outbox"].values()))
    generation = outbox["coordinator_generation"]
    with pytest.raises(registry.StaleCoordinatorGenerationError):
        registry.acknowledge_join_wake(
            path, outbox["outbox_id"], coordinator_generation="stale"
        )
    acknowledged, replayed = registry.acknowledge_join_wake(
        path, outbox["outbox_id"], coordinator_generation=generation
    )

    def _advance(sessions: dict[str, dict]) -> None:
        sessions["ws-parent"] = registry.transition(
            sessions["ws-parent"], "running", now="2026-07-14T12:01:00Z"
        )

    registry.locked_registry_update(path, _advance)
    replay, replayed_again = registry.acknowledge_join_wake(
        path, outbox["outbox_id"], coordinator_generation=generation
    )
    assert acknowledged["state"] == replay["state"] == "acknowledged"
    assert replayed is False and replayed_again is True


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


def test_pidlock_release_preserves_one_stable_inode(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.lock"
    first_fd = registry.acquire_single_instance_lock(lock_path)
    first_inode = os.fstat(first_fd).st_ino
    registry.release_single_instance_lock(first_fd, lock_path)

    assert lock_path.stat().st_ino == first_inode
    second_fd = registry.acquire_single_instance_lock(lock_path)
    try:
        assert os.fstat(second_fd).st_ino == first_inode
    finally:
        registry.release_single_instance_lock(second_fd, lock_path)


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
