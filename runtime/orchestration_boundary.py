"""Executable admission boundary for degraded orchestration work.

The boundary derives authority inputs from trusted runtime sources and reserves
one durable supervisor-scoped slot before the dispatcher can invoke a driver.
Caller-authored admission data contains only immutable work and transition
identities; it cannot select a capability tuple, clock value, export
fingerprint, or fresh run ceiling (INTENT criteria #2 and #3).

Terminal settlement deliberately bypasses capability and admission checks: an
expired or exhausted supervisor must still be able to record the outcome of
work that was already admitted.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, TypeVar

from runtime.capability_authority import (
    Capability,
    CapabilityAuthority,
    CapabilityKey,
)
from runtime.orchestration_ledger import OrchestrationLedger, Reservation


_T = TypeVar("_T")
_THREAD_STATE = threading.local()


class AdmissionDenied(RuntimeError):
    """Raised before driver execution when exact admission fails closed."""


@dataclass(frozen=True)
class TransitionIds:
    """Distinct immutable identities for one admission lifecycle."""

    reserve: str
    dispatching: str
    started: str
    indeterminate: str
    settled: str


@dataclass(frozen=True)
class AdmissionRequest:
    """Carry caller-selected work identities, never authority assertions.

    ``logical_work_id`` remains stable across attempts; ``reservation_id`` and
    every member of ``transitions`` identify only this attempt.  The durable
    supervisor identity and exact capability tuple are intentionally absent.
    """

    logical_work_id: str
    reservation_id: str
    writer_id: str
    transitions: TransitionIds
    reentry_of: str | None = None


def _system_clock() -> int:
    """Return current UTC epoch seconds; this hard-fail source has no fallback."""

    return int(time.time())


@dataclass(frozen=True)
class BoundarySources:
    """Trusted runtime/export sources bound when a dispatcher boundary is built.

    Callable sources are evaluated at admission time so expiry and installed
    export state cannot be frozen or supplied by an admission caller.
    """

    supervisor_id: str
    host: Callable[[], str]
    surface: Callable[[], str]
    runtime_build: Callable[[object], str]
    installed_export_fingerprint: Callable[[], str]
    command: str
    posture: str
    driver_type: type[object]
    clock: Callable[[], int] = field(default=_system_clock)


class OrchestrationBoundary:
    """Resolve trusted authority and reserve durable state before dispatch."""

    def __init__(
        self,
        authority: CapabilityAuthority,
        ledger: OrchestrationLedger,
        sources: BoundarySources,
    ) -> None:
        """Bind authority, ledger, and non-model runtime sources. Hard-fail.

        ``supervisor_id`` is captured once and owns both the durable ceiling and
        process lock.  Admission callers cannot mint another scope by changing
        a run identifier.
        """

        if not sources.supervisor_id:
            raise ValueError("boundary requires a durable supervisor identity")
        self._authority = authority
        self._ledger = ledger
        self._sources = sources
        self._supervisor_id = sources.supervisor_id
        digest = hashlib.sha256(self._supervisor_id.encode("utf-8")).hexdigest()
        prefix = ledger.path.with_name(f"{ledger.path.name}.degraded-execution")
        self._execution_lock_path = prefix.with_name(f"{prefix.name}.{digest}.lock")

    def _execute_dispatch(
        self,
        request: AdmissionRequest,
        *,
        driver: object,
        command_id: str,
        callback: Callable[[], _T],
    ) -> _T:
        """Admit one exact dispatcher invocation. Hard-fail before callback.

        This method is private because the public production entrypoint is
        :meth:`runtime.dispatch.dispatcher.Dispatcher.run`, which supplies the
        actual driver and command rather than accepting caller assertions.
        Callback failures are marked indeterminate and re-raised unchanged.
        """

        canonical_command = command_id.lstrip("/")
        if canonical_command != self._sources.command:
            raise AdmissionDenied("boundary_command_mismatch")
        if type(driver) is not self._sources.driver_type:
            raise AdmissionDenied("boundary_driver_mismatch")

        active_paths = getattr(_THREAD_STATE, "active_paths", set())
        if self._execution_lock_path in active_paths:
            raise AdmissionDenied("nested degraded execution is forbidden")
        _THREAD_STATE.active_paths = active_paths | {self._execution_lock_path}
        try:
            with _ExecutionLock(self._execution_lock_path):
                return self._execute_locked(
                    request, driver, canonical_command, callback
                )
        finally:
            _THREAD_STATE.active_paths = active_paths

    def _execute_locked(
        self,
        request: AdmissionRequest,
        driver: object,
        command_id: str,
        callback: Callable[[], _T],
    ) -> _T:
        """Resolve fresh trusted sources and execute while holding the mutex."""

        key = CapabilityKey(
            host=self._sources.host(),
            surface=self._sources.surface(),
            runtime_build=self._sources.runtime_build(driver),
            command=command_id,
            posture=self._sources.posture,
        )
        resolution = self._authority.resolve(
            key,
            installed_export_fingerprint=self._sources.installed_export_fingerprint(),
            now=self._sources.clock(),
        )
        if resolution.capability is not Capability.DEGRADED_SINGLE_AGENT:
            raise AdmissionDenied(resolution.reason)

        self._ledger.configure_run(self._supervisor_id, admission_ceiling=1)
        reservation = self._ledger.reserve(
            run_id=self._supervisor_id,
            logical_work_id=request.logical_work_id,
            reservation_id=request.reservation_id,
            transition_id=request.transitions.reserve,
            writer_id=request.writer_id,
            reentry_of=request.reentry_of,
        )
        if reservation.state != "reserved":
            raise AdmissionDenied("reservation_replay_cannot_restart_callback")
        reservation = self._advance(
            reservation, request.transitions.dispatching, "dispatching"
        )
        reservation = self._advance(reservation, request.transitions.started, "started")

        completed = False
        try:
            result = callback()
            completed = True
        finally:
            if not completed:
                self._advance(
                    reservation,
                    request.transitions.indeterminate,
                    "indeterminate",
                )

        self._advance(reservation, request.transitions.settled, "settled")
        return result

    def settle(
        self,
        *,
        reservation_id: str,
        transition_id: str,
        writer_id: str,
        writer_fence: int,
    ) -> Reservation:
        """Settle admitted work without a new admission check. Hard-fail."""

        return self._ledger.advance(
            reservation_id=reservation_id,
            transition_id=transition_id,
            writer_id=writer_id,
            writer_fence=writer_fence,
            to_state="settled",
        )

    def _advance(
        self,
        reservation: Reservation,
        transition_id: str,
        to_state: str,
    ) -> Reservation:
        """Advance using the reservation's current fenced writer. Hard-fail."""

        return self._ledger.advance(
            reservation_id=reservation.reservation_id,
            transition_id=transition_id,
            writer_id=reservation.writer_id,
            writer_fence=reservation.writer_fence,
            to_state=to_state,
        )


class _ExecutionLock:
    """Process-safe nonblocking mutex for one durable supervisor scope."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> _ExecutionLock:
        """Acquire immediately or reject; never wait behind active work."""

        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(self._fd)
            self._fd = None
            raise AdmissionDenied("degraded execution already active") from exc
        except OSError:
            os.close(self._fd)
            self._fd = None
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        """Release and close the owned descriptor; cleanup hard-fails."""

        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None
