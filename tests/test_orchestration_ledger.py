"""Behavioral tests for the durable orchestration reservation ledger."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from runtime.orchestration_ledger import (
    AdmissionCeilingExceeded,
    DuplicateLiveWork,
    IdentifierConflict,
    IllegalReentry,
    IllegalTransition,
    OrchestrationLedger,
    StaleWriter,
)


def _ledger(tmp_path: Path, ceiling: int = 4) -> OrchestrationLedger:
    ledger = OrchestrationLedger(tmp_path / "ledger.sqlite3")
    ledger.configure_run("run", ceiling)
    return ledger


def _reserve(
    ledger: OrchestrationLedger,
    number: int,
    *,
    logical_work_id: str | None = None,
    reentry_of: str | None = None,
):
    return ledger.reserve(
        run_id="run",
        logical_work_id=logical_work_id or f"work-{number}",
        reservation_id=f"reservation-{number}",
        transition_id=f"reserve-{number}",
        writer_id=f"writer-{number}",
        reentry_of=reentry_of,
    )


def _advance(
    ledger: OrchestrationLedger,
    reservation,
    to_state: str,
    number: int,
):
    return ledger.advance(
        reservation_id=reservation.reservation_id,
        transition_id=f"transition-{number}",
        writer_id=reservation.writer_id,
        writer_fence=reservation.writer_fence,
        to_state=to_state,
    )


def test_concurrent_final_slot_is_admitted_once(tmp_path: Path) -> None:
    """Criterion #3: a racing final slot cannot become N+1 admissions."""
    ledger = _ledger(tmp_path, ceiling=1)

    def attempt(number: int) -> str:
        contender = OrchestrationLedger(ledger.path)
        try:
            _reserve(contender, number)
        except AdmissionCeilingExceeded:
            return "rejected"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))

    assert sorted(results) == ["admitted", "rejected"]
    assert ledger.run_usage("run") == (1, 1)


def test_duplicate_live_logical_work_fails_closed(tmp_path: Path) -> None:
    """Criterion #3: distinct attempt IDs cannot duplicate live logical work."""
    ledger = _ledger(tmp_path)
    _reserve(ledger, 1, logical_work_id="same-work")

    with pytest.raises(DuplicateLiveWork):
        _reserve(ledger, 2, logical_work_id="same-work")
    assert ledger.run_usage("run") == (1, 4)


def test_concurrent_duplicate_live_logical_work_is_admitted_once(
    tmp_path: Path,
) -> None:
    """Criterion #3: racing attempt IDs cannot both claim one logical node."""
    ledger = _ledger(tmp_path)

    def attempt(number: int) -> str:
        contender = OrchestrationLedger(ledger.path)
        try:
            _reserve(contender, number, logical_work_id="same-work")
        except DuplicateLiveWork:
            return "duplicate"
        return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (1, 2)))

    assert sorted(results) == ["admitted", "duplicate"]
    assert ledger.run_usage("run") == (1, 4)


def test_run_ceiling_survives_reopen_and_rejects_n_plus_one(tmp_path: Path) -> None:
    """Criterion #3: process restart cannot reset the durable admission count."""
    ledger = _ledger(tmp_path, ceiling=2)
    _reserve(ledger, 1)
    _reserve(ledger, 2)

    reopened = OrchestrationLedger(ledger.path)
    with pytest.raises(AdmissionCeilingExceeded):
        _reserve(reopened, 3)
    assert reopened.run_usage("run") == (2, 2)


def test_reentry_is_explicit_and_consumes_an_admission(tmp_path: Path) -> None:
    """Criterion #3: logical identity survives a separately identified re-entry."""
    ledger = _ledger(tmp_path, ceiling=2)
    first = _reserve(ledger, 1, logical_work_id="same-work")
    settled = _advance(ledger, first, "settled", 1)

    with pytest.raises(IllegalReentry):
        _reserve(ledger, 2, logical_work_id="same-work")
    second = _reserve(
        ledger,
        2,
        logical_work_id="same-work",
        reentry_of=settled.reservation_id,
    )
    assert second.logical_work_id == first.logical_work_id
    assert second.reservation_id != first.reservation_id
    assert second.reentry_of == first.reservation_id
    assert ledger.run_usage("run") == (2, 2)


def test_indeterminate_work_must_settle_before_reentry(tmp_path: Path) -> None:
    """Criterion #3: uncertain crash recovery never creates duplicate live work."""
    ledger = _ledger(tmp_path)
    first = _reserve(ledger, 1, logical_work_id="same-work")
    uncertain = _advance(ledger, first, "indeterminate", 1)

    with pytest.raises(DuplicateLiveWork):
        _reserve(
            ledger,
            2,
            logical_work_id="same-work",
            reentry_of=uncertain.reservation_id,
        )


def test_writer_transfer_fences_stale_writer(tmp_path: Path) -> None:
    """Criterion #3: stale recovery writers cannot publish later transitions."""
    ledger = _ledger(tmp_path)
    original = _reserve(ledger, 1)
    recovered = ledger.transfer_writer(
        reservation_id=original.reservation_id,
        transition_id="transfer-1",
        writer_id=original.writer_id,
        writer_fence=original.writer_fence,
        new_writer_id="recovery-writer",
    )

    with pytest.raises(StaleWriter):
        _advance(ledger, original, "dispatching", 1)
    settled = _advance(ledger, recovered, "settled", 2)
    assert recovered.writer_fence > original.writer_fence
    assert settled.state == "settled"


def test_old_operation_replays_remain_idempotent_after_writer_transfer(
    tmp_path: Path,
) -> None:
    """Criterion #3: later fencing cannot reinterpret an immutable old retry."""
    ledger = _ledger(tmp_path)
    original = _reserve(ledger, 1)
    recovered = ledger.transfer_writer(
        reservation_id=original.reservation_id,
        transition_id="transfer-1",
        writer_id=original.writer_id,
        writer_fence=original.writer_fence,
        new_writer_id="recovery-writer",
    )

    assert _reserve(ledger, 1) == recovered
    assert ledger.transfer_writer(
        reservation_id=original.reservation_id,
        transition_id="transfer-1",
        writer_id=original.writer_id,
        writer_fence=original.writer_fence,
        new_writer_id="recovery-writer",
    ) == recovered


@pytest.mark.parametrize(
    ("states", "next_transition"),
    [
        ((), 1),
        (("dispatching",), 2),
        (("dispatching", "started"), 3),
        (("dispatching", "started", "indeterminate"), 4),
    ],
)
def test_every_crash_cut_reopens_and_permits_terminal_settlement(
    tmp_path: Path, states: tuple[str, ...], next_transition: int
) -> None:
    """Criterion #3: reserve/dispatch/start/recovery crash cuts remain closable."""
    ledger = _ledger(tmp_path, ceiling=1)
    reservation = _reserve(ledger, 1)
    for number, state in enumerate(states, start=1):
        reservation = _advance(ledger, reservation, state, number)
        ledger = OrchestrationLedger(ledger.path)
        reservation = ledger.get_reservation(reservation.reservation_id)

    # Admission is exhausted, but settlement is a non-deniable control action.
    with pytest.raises(AdmissionCeilingExceeded):
        _reserve(ledger, 2)
    settled = _advance(ledger, reservation, "settled", next_transition)
    assert settled.state == "settled"
    assert OrchestrationLedger(ledger.path).get_reservation(
        reservation.reservation_id
    ).state == "settled"


def test_illegal_edges_and_post_terminal_mutation_fail_closed(tmp_path: Path) -> None:
    """Criterion #3: only the declared state machine edges are accepted."""
    ledger = _ledger(tmp_path)
    reservation = _reserve(ledger, 1)
    with pytest.raises(IllegalTransition):
        _advance(ledger, reservation, "started", 1)
    settled = _advance(ledger, reservation, "settled", 2)
    with pytest.raises(IllegalTransition):
        _advance(ledger, settled, "dispatching", 3)


def test_reserve_and_transition_replays_are_idempotent(tmp_path: Path) -> None:
    """Criterion #3: retrying committed operations cannot double-charge or advance."""
    ledger = _ledger(tmp_path, ceiling=1)
    reservation = _reserve(ledger, 1)
    assert _reserve(ledger, 1) == reservation
    dispatching = _advance(ledger, reservation, "dispatching", 1)
    assert _advance(ledger, reservation, "dispatching", 1) == dispatching
    assert ledger.run_usage("run") == (1, 1)


def test_settlement_replay_after_restart_is_idempotent(tmp_path: Path) -> None:
    """Criterion #3: a crash after commit cannot duplicate terminal settlement."""
    ledger = _ledger(tmp_path, ceiling=1)
    reservation = _reserve(ledger, 1)
    settled = _advance(ledger, reservation, "settled", 1)

    reopened = OrchestrationLedger(ledger.path)
    assert _advance(reopened, reservation, "settled", 1) == settled
    assert reopened.run_usage("run") == (1, 1)


def test_immutable_transition_ids_reject_conflicting_reuse(tmp_path: Path) -> None:
    """Criterion #3: transition identity cannot be rebound after persistence."""
    ledger = _ledger(tmp_path)
    first = _reserve(ledger, 1)
    second = _reserve(ledger, 2)
    _advance(ledger, first, "dispatching", 1)

    with pytest.raises(IdentifierConflict):
        ledger.advance(
            reservation_id=second.reservation_id,
            transition_id="transition-1",
            writer_id=second.writer_id,
            writer_fence=second.writer_fence,
            to_state="dispatching",
        )


def test_failed_admission_and_transition_transactions_leave_no_partial_state(
    tmp_path: Path,
) -> None:
    """Criterion #3: rejected operations preserve counters and prior state."""
    ledger = _ledger(tmp_path, ceiling=2)
    reservation = _reserve(ledger, 1, logical_work_id="same-work")
    with pytest.raises(DuplicateLiveWork):
        _reserve(ledger, 2, logical_work_id="same-work")
    with pytest.raises(IllegalTransition):
        _advance(ledger, reservation, "started", 2)

    reopened = OrchestrationLedger(ledger.path)
    assert reopened.run_usage("run") == (1, 2)
    assert reopened.get_reservation(reservation.reservation_id).state == "reserved"
