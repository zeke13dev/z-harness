"""Behavioral tests for the host-bound terminal batch protocol (criterion #4)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from runtime.capability_authority import (
    AUTHORITY_VERSION,
    Capability,
    CapabilityAuthority,
    CapabilityEvidence,
    CapabilityKey,
)
from runtime.orchestration_batch import (
    BatchIdentityConflict,
    BatchNotDrained,
    BatchPromotionBlocked,
    HostPrimitives,
    ModelPollingRejected,
    OrchestrationBatchCoordinator,
    TaskRootRejected,
    TerminalEvent,
    UnknownBatch,
)
from runtime.orchestration_ledger import OrchestrationLedger


class HostHarness:
    """Deterministic executable host primitives used by the protocol tests."""

    def __init__(self) -> None:
        self.events: tuple[TerminalEvent, ...] = ()
        self.collections = 0
        self.terminations: list[tuple[str, str]] = []

    def collect(self, batch_id: str) -> tuple[TerminalEvent, ...]:
        assert batch_id
        self.collections += 1
        return self.events

    def terminate(self, batch_id: str, task_id: str) -> bool:
        self.terminations.append((batch_id, task_id))
        return True


def _key() -> CapabilityKey:
    return CapabilityKey("codex", "cli", "build-1", "z-execute", "bounded")


def _coordinator(
    tmp_path: Path,
    *,
    host: HostHarness | None = None,
    capability: Capability = Capability.NATIVE_BOUNDED,
    evidence_id: str = "proof-1",
    primitive_evidence_id: str | None = None,
    now: int = 150,
) -> tuple[OrchestrationBatchCoordinator, OrchestrationLedger, HostHarness]:
    ledger = OrchestrationLedger(tmp_path / "ledger.sqlite3")
    ledger.configure_run("run", 10)
    authority = CapabilityAuthority(tmp_path / "authority.json")
    key = _key()
    harness = host or HostHarness()
    authority.persist(
        CapabilityEvidence(
            evidence_id=evidence_id,
            authority_version=AUTHORITY_VERSION,
            key=key,
            capability=capability,
            evidence_surface="cli",
            installed_export_fingerprint="export-1",
            issued_at=100,
            expires_at=200,
            terminal_collection_primitive=_identity(harness.collect),
            active_child_termination_primitive=_identity(harness.terminate),
        )
    )
    coordinator = OrchestrationBatchCoordinator(
        ledger,
        authority=authority,
        capability_key=key,
        installed_export_fingerprint="export-1",
        now=lambda: now,
        host_id="codex",
        root_task_id="root",
        primitives=HostPrimitives(
            primitive_evidence_id or evidence_id,
            harness.collect,
            harness.terminate,
        ),
    )
    return coordinator, ledger, harness


def _identity(primitive: object) -> str:
    function = getattr(primitive, "__func__", primitive)
    return f"{function.__module__}:{function.__qualname__}"


def _reserve(coordinator: OrchestrationBatchCoordinator, batch_id: str = "batch-1"):
    return coordinator.reserve_batch(
        run_id="run",
        batch_id=batch_id,
        task_ids=("task-a", "task-b"),
    )


def _event(task_id: str, version: int, outcome: str = "ok") -> TerminalEvent:
    return TerminalEvent(task_id, outcome, version, version * 10)


def test_partial_completion_replay_and_terminal_wakes_are_idempotent(
    tmp_path: Path,
) -> None:
    """Criterion #4: each terminal-set version emits at most one wake."""
    coordinator, _, _ = _coordinator(tmp_path)
    initial = _reserve(coordinator)

    first = coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )
    replay = coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )
    second = coordinator.record_terminal(
        "batch-1", event=_event("task-b", 2), actor_id="codex"
    )

    assert initial.state == "active"
    assert (first.terminal_set_version, first.wake_sequence) == (1, 10)
    assert replay is None
    assert (second.terminal_set_version, second.wake_sequence) == (2, 20)
    assert coordinator.snapshot("batch-1").terminal_task_ids == ("task-a", "task-b")


def test_conflicting_replay_and_out_of_order_versions_fail_closed(tmp_path: Path) -> None:
    """Criterion #4: terminal identity cannot be rebound or applied out of order."""
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)
    coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )

    with pytest.raises(BatchIdentityConflict, match="identity was reused"):
        coordinator.record_terminal(
            "batch-1", event=_event("task-b", 1), actor_id="codex"
        )
    with pytest.raises(BatchIdentityConflict, match="advance exactly once"):
        coordinator.record_terminal(
            "batch-1", event=_event("task-b", 3), actor_id="codex"
        )


def test_same_terminal_outcome_under_new_wake_identity_is_rejected(
    tmp_path: Path,
) -> None:
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)
    coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )

    with pytest.raises(BatchIdentityConflict, match="identity was rebound"):
        coordinator.record_terminal(
            "batch-1",
            event=TerminalEvent("task-a", "ok", 2, 999),
            actor_id="codex",
        )


def test_drain_and_durable_settlement_precede_refill(tmp_path: Path) -> None:
    """Criterion #4: no new batch is admitted before full durable settlement."""
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)

    with pytest.raises(BatchNotDrained):
        _reserve(coordinator, "batch-2")
    coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )
    with pytest.raises(BatchNotDrained):
        coordinator.settle_batch("batch-1")
    coordinator.record_terminal(
        "batch-1", event=_event("task-b", 2), actor_id="codex"
    )
    assert coordinator.settle_batch("batch-1").state == "settled"
    assert _reserve(coordinator, "batch-2").state == "active"


def test_settlement_and_batch_reservation_replay_are_idempotent(tmp_path: Path) -> None:
    coordinator, _, _ = _coordinator(tmp_path)
    original = _reserve(coordinator)
    assert _reserve(coordinator) == original
    coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )
    coordinator.record_terminal(
        "batch-1", event=_event("task-b", 2), actor_id="codex"
    )
    settled = coordinator.settle_batch("batch-1")
    assert coordinator.settle_batch("batch-1") == settled


def test_crash_resume_preserves_wake_version_and_drain_state(tmp_path: Path) -> None:
    """Criterion #4: restart cannot duplicate a wake or skip the drain gate."""
    coordinator, ledger, harness = _coordinator(tmp_path)
    _reserve(coordinator)
    event = _event("task-a", 1)
    coordinator.record_terminal("batch-1", event=event, actor_id="codex")

    authority = CapabilityAuthority(tmp_path / "authority.json")
    resumed = OrchestrationBatchCoordinator(
        OrchestrationLedger(ledger.path),
        authority=authority,
        capability_key=_key(),
        installed_export_fingerprint="export-1",
        now=lambda: 150,
        host_id="codex",
        root_task_id="root",
        primitives=HostPrimitives("proof-1", harness.collect, harness.terminate),
    )
    assert resumed.record_terminal(
        "batch-1", event=event, actor_id="codex"
    ) is None
    assert resumed.snapshot("batch-1").terminal_set_version == 1
    with pytest.raises(BatchNotDrained):
        _reserve(resumed, "batch-2")


def test_concurrent_duplicate_terminal_delivery_emits_one_wake(tmp_path: Path) -> None:
    """Criterion #4: concurrent replay commits one transition and one wake."""
    coordinator, ledger, harness = _coordinator(tmp_path)
    _reserve(coordinator)

    def deliver(_: int) -> object:
        contender = OrchestrationBatchCoordinator(
            OrchestrationLedger(ledger.path),
            authority=CapabilityAuthority(tmp_path / "authority.json"),
            capability_key=_key(),
            installed_export_fingerprint="export-1",
            now=lambda: 150,
            host_id="codex",
            root_task_id="root",
            primitives=HostPrimitives("proof-1", harness.collect, harness.terminate),
        )
        return contender.record_terminal(
            "batch-1", event=_event("task-a", 1), actor_id="codex"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(deliver, (1, 2)))

    assert sum(result is not None for result in results) == 1
    assert coordinator.snapshot("batch-1").terminal_set_version == 1


def test_concurrent_competing_terminal_versions_fail_closed(tmp_path: Path) -> None:
    """Criterion #4: racing version claims cannot create two version-one wakes."""
    coordinator, ledger, harness = _coordinator(tmp_path)
    _reserve(coordinator)

    def deliver(task_id: str) -> str:
        contender = OrchestrationBatchCoordinator(
            OrchestrationLedger(ledger.path),
            authority=CapabilityAuthority(tmp_path / "authority.json"),
            capability_key=_key(),
            installed_export_fingerprint="export-1",
            now=lambda: 150,
            host_id="codex",
            root_task_id="root",
            primitives=HostPrimitives("proof-1", harness.collect, harness.terminate),
        )
        try:
            contender.record_terminal(
                "batch-1", event=_event(task_id, 1), actor_id="codex"
            )
        except BatchIdentityConflict:
            return "rejected"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(deliver, ("task-a", "task-b")))

    assert sorted(results) == ["committed", "rejected"]
    assert coordinator.snapshot("batch-1").terminal_set_version == 1


def test_host_collection_drains_one_signal_without_model_polling(tmp_path: Path) -> None:
    """Criterion #4: only the bound host invokes the executable collector."""
    harness = HostHarness()
    harness.events = (_event("task-a", 1), _event("task-b", 2))
    coordinator, _, harness = _coordinator(tmp_path, host=harness)
    _reserve(coordinator)

    wakes = coordinator.collect_once("batch-1", actor_id="codex")

    assert [wake.terminal_set_version for wake in wakes] == [1, 2]
    assert harness.collections == 1
    with pytest.raises(ModelPollingRejected):
        coordinator.collect_once("batch-1", actor_id="model")
    with pytest.raises(ModelPollingRejected):
        coordinator.poll("batch-1")
    assert harness.collections == 1


def test_task_level_root_work_is_rejected(tmp_path: Path) -> None:
    """Criterion #4: the supervisor root never becomes a batch member."""
    coordinator, _, _ = _coordinator(tmp_path)
    with pytest.raises(TaskRootRejected):
        coordinator.reserve_batch(
            run_id="run",
            batch_id="batch-1",
            task_ids=("root", "task-a"),
        )


@pytest.mark.parametrize(
    ("capability", "now"),
    (
        (Capability.DEGRADED_SINGLE_AGENT, 150),
        (Capability.BLOCKED, 150),
        (Capability.NATIVE_BOUNDED, 200),
    ),
)
def test_non_native_or_expired_authority_blocks_promotion(
    tmp_path: Path, capability: Capability, now: int
) -> None:
    """Criterion #4: uncertain capability evidence never enables batching."""
    coordinator, _, _ = _coordinator(tmp_path, capability=capability, now=now)
    with pytest.raises(BatchPromotionBlocked):
        _reserve(coordinator)


def test_host_primitives_must_match_exact_capability_evidence(tmp_path: Path) -> None:
    coordinator, _, _ = _coordinator(tmp_path, primitive_evidence_id="other-proof")
    with pytest.raises(BatchPromotionBlocked, match="exact capability evidence"):
        _reserve(coordinator)


def test_promotion_requires_both_immutable_primitive_claims(tmp_path: Path) -> None:
    coordinator, _, harness = _coordinator(tmp_path)
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.persist(
        CapabilityEvidence(
            evidence_id="proof-1",
            authority_version=AUTHORITY_VERSION,
            key=_key(),
            capability=Capability.NATIVE_BOUNDED,
            evidence_surface="cli",
            installed_export_fingerprint="export-1",
            issued_at=100,
            expires_at=200,
            terminal_collection_primitive=_identity(harness.collect),
        )
    )

    with pytest.raises(BatchPromotionBlocked, match="immutable capability claims"):
        _reserve(coordinator)


def test_coordinator_host_must_match_exact_capability_tuple(tmp_path: Path) -> None:
    coordinator, ledger, harness = _coordinator(tmp_path)
    wrong_host = OrchestrationBatchCoordinator(
        ledger,
        authority=CapabilityAuthority(tmp_path / "authority.json"),
        capability_key=_key(),
        installed_export_fingerprint="export-1",
        now=lambda: 150,
        host_id="other-host",
        root_task_id="root",
        primitives=HostPrimitives("proof-1", harness.collect, harness.terminate),
    )

    with pytest.raises(BatchPromotionBlocked, match="host does not match"):
        _reserve(wrong_host)


def test_cross_host_coordinator_cannot_mutate_existing_batch(tmp_path: Path) -> None:
    coordinator, ledger, harness = _coordinator(tmp_path)
    _reserve(coordinator)
    attacker = OrchestrationBatchCoordinator(
        ledger,
        authority=CapabilityAuthority(tmp_path / "authority.json"),
        capability_key=_key(),
        installed_export_fingerprint="export-1",
        now=lambda: 150,
        host_id="attacker-host",
        root_task_id="root",
        primitives=HostPrimitives("proof-1", harness.collect, harness.terminate),
    )

    with pytest.raises(BatchIdentityConflict, match="immutable batch binding"):
        attacker.record_terminal(
            "batch-1", event=_event("task-a", 1), actor_id="attacker-host"
        )
    with pytest.raises(BatchIdentityConflict, match="immutable batch binding"):
        attacker.settle_batch("batch-1")


def test_arbitrary_callable_substitution_cannot_use_claimed_evidence(
    tmp_path: Path,
) -> None:
    coordinator, ledger, _ = _coordinator(tmp_path)

    class SubstitutedPrimitives:
        def collect(self, batch_id: str) -> tuple[TerminalEvent, ...]:
            return (_event("task-a", 1),)

        def terminate(self, batch_id: str, task_id: str) -> bool:
            return True

    substituted = SubstitutedPrimitives()
    attacker = OrchestrationBatchCoordinator(
        ledger,
        authority=CapabilityAuthority(tmp_path / "authority.json"),
        capability_key=_key(),
        installed_export_fingerprint="export-1",
        now=lambda: 150,
        host_id="codex",
        root_task_id="root",
        primitives=HostPrimitives(
            "proof-1", substituted.collect, substituted.terminate
        ),
    )

    with pytest.raises(BatchPromotionBlocked, match="immutable capability claims"):
        _reserve(attacker)

    _reserve(coordinator)
    with pytest.raises(BatchIdentityConflict, match="immutable batch binding"):
        attacker.collect_once("batch-1", actor_id="codex")
    with pytest.raises(BatchIdentityConflict, match="immutable batch binding"):
        attacker.terminate_child("batch-1", "task-a", actor_id="codex")


def test_both_host_primitives_must_be_executable(tmp_path: Path) -> None:
    coordinator, ledger, _ = _coordinator(tmp_path)
    authority = CapabilityAuthority(tmp_path / "authority.json")
    missing_termination = OrchestrationBatchCoordinator(
        ledger,
        authority=authority,
        capability_key=_key(),
        installed_export_fingerprint="export-1",
        now=lambda: 150,
        host_id="codex",
        root_task_id="root",
        primitives=HostPrimitives("proof-1", lambda _: (), None),  # type: ignore[arg-type]
    )

    with pytest.raises(BatchPromotionBlocked, match="executable host primitives"):
        _reserve(missing_termination)


def test_authority_revocation_blocks_later_batch_even_after_construction(
    tmp_path: Path,
) -> None:
    """Criterion #4: promotion is re-resolved at every admission boundary."""
    coordinator, _, _ = _coordinator(tmp_path)
    authority = CapabilityAuthority(tmp_path / "authority.json")
    authority.revoke(_key(), revoked_at=151, reason="primitive withdrawn")

    with pytest.raises(BatchPromotionBlocked, match="revoked_evidence"):
        _reserve(coordinator)


def test_authority_expiry_does_not_deny_terminal_ingestion_or_settlement(
    tmp_path: Path,
) -> None:
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)
    CapabilityAuthority(tmp_path / "authority.json").revoke(
        _key(), revoked_at=151, reason="no new admission"
    )

    coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )
    coordinator.record_terminal(
        "batch-1", event=_event("task-b", 2), actor_id="codex"
    )

    assert coordinator.settle_batch("batch-1").state == "settled"


def test_active_child_termination_uses_evidence_bound_primitive(tmp_path: Path) -> None:
    coordinator, _, harness = _coordinator(tmp_path)
    _reserve(coordinator)

    assert coordinator.terminate_child(
        "batch-1", "task-a", actor_id="codex"
    ) is True
    assert harness.terminations == [("batch-1", "task-a")]
    with pytest.raises(UnknownBatch):
        coordinator.terminate_child(
            "batch-1", "not-a-member", actor_id="codex"
        )


def test_immutable_batch_identity_rejects_changed_members(tmp_path: Path) -> None:
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)

    with pytest.raises(BatchIdentityConflict, match="reused"):
        coordinator.reserve_batch(
            run_id="run",
            batch_id="batch-1",
            task_ids=("task-a", "task-c"),
        )


def test_recovery_rejects_changed_root_supervisor_identity(tmp_path: Path) -> None:
    coordinator, ledger, harness = _coordinator(tmp_path)
    original = _reserve(coordinator)
    assert original.root_task_id == "root"
    changed_root = OrchestrationBatchCoordinator(
        ledger,
        authority=CapabilityAuthority(tmp_path / "authority.json"),
        capability_key=_key(),
        installed_export_fingerprint="export-1",
        now=lambda: 150,
        host_id="codex",
        root_task_id="different-root",
        primitives=HostPrimitives("proof-1", harness.collect, harness.terminate),
    )

    with pytest.raises(BatchIdentityConflict, match="immutable batch binding"):
        changed_root.snapshot("batch-1")
    with pytest.raises(BatchIdentityConflict, match="immutable batch binding"):
        changed_root.reserve_batch(
            run_id="run",
            batch_id="batch-1",
            task_ids=("task-a", "task-b"),
        )


def test_terminal_outcome_cannot_be_rebound_under_new_version(tmp_path: Path) -> None:
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)
    coordinator.record_terminal(
        "batch-1", event=_event("task-a", 1), actor_id="codex"
    )

    with pytest.raises(BatchIdentityConflict, match="identity was rebound"):
        coordinator.record_terminal(
            "batch-1",
            event=replace(_event("task-a", 2), outcome="failed"),
            actor_id="codex",
        )


def test_read_and_initialization_connections_close_on_success_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator, _, _ = _coordinator(tmp_path)
    _reserve(coordinator)
    opened: list[TrackingConnection] = []
    original_connect = coordinator._connect

    class TrackingConnection:
        def __init__(
            self,
            connection: object,
            *,
            fail_scripts: bool = False,
            fail_begin: bool = False,
        ) -> None:
            object.__setattr__(self, "connection", connection)
            object.__setattr__(self, "closed", False)
            object.__setattr__(self, "fail_scripts", fail_scripts)
            object.__setattr__(self, "fail_begin", fail_begin)

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

        def __setattr__(self, name: str, value: object) -> None:
            setattr(self.connection, name, value)

        def close(self) -> None:
            self.connection.close()
            object.__setattr__(self, "closed", True)

        def executescript(self, script: str) -> object:
            if self.fail_scripts:
                raise sqlite3.OperationalError("injected initialization failure")
            return self.connection.executescript(script)

        def execute(self, statement: str, parameters: object = ()) -> object:
            if self.fail_begin and statement == "BEGIN IMMEDIATE":
                raise sqlite3.OperationalError("injected transaction failure")
            return self.connection.execute(statement, parameters)

    def tracked_connect() -> TrackingConnection:
        tracked = TrackingConnection(original_connect())
        opened.append(tracked)
        return tracked

    monkeypatch.setattr(coordinator, "_connect", tracked_connect)

    coordinator.snapshot("batch-1")
    coordinator.terminate_child("batch-1", "task-a", actor_id="codex")
    with pytest.raises(UnknownBatch):
        coordinator.snapshot("missing")
    coordinator._initialize()

    failing_begin = TrackingConnection(original_connect(), fail_begin=True)
    opened.append(failing_begin)
    monkeypatch.setattr(coordinator, "_connect", lambda: failing_begin)
    with pytest.raises(sqlite3.OperationalError, match="transaction failure"):
        coordinator.settle_batch("batch-1")

    failing = TrackingConnection(original_connect(), fail_scripts=True)
    opened.append(failing)
    monkeypatch.setattr(coordinator, "_connect", lambda: failing)
    with pytest.raises(sqlite3.OperationalError, match="initialization failure"):
        coordinator._initialize()

    assert opened
    assert all(connection.closed for connection in opened)
