"""Durable admission and transition ledger for costly orchestration work.

The ledger enforces INTENT acceptance criterion #3 at a non-model boundary:
logical work identity is stable across attempts, while every reservation and
state change has its own immutable identifier.  SQLite ``BEGIN IMMEDIATE``
transactions serialize admissions, and ``synchronous=FULL`` commits preserve
run ceilings and fencing across process crashes.

Public surface:

* :class:`OrchestrationLedger` configures runs, reserves work, advances state,
  transfers writer authority, and reads reservations.
* :class:`Reservation` is the immutable caller-facing snapshot.
* ``LedgerError`` subclasses identify fail-closed admission and transition
  failures.

Concurrency: callers may use separate instances in separate processes.  Each
operation opens its own connection and performs its read/validate/write cycle
in one write transaction.  The sidecar SQLite journal is part of the durable
database protocol; callers must not copy a live database file in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3


_STATES = frozenset({"reserved", "dispatching", "started", "settled", "indeterminate"})
_LEGAL_TRANSITIONS = {
    "reserved": frozenset({"dispatching", "indeterminate", "settled"}),
    "dispatching": frozenset({"started", "indeterminate", "settled"}),
    "started": frozenset({"indeterminate", "settled"}),
    "indeterminate": frozenset({"settled"}),
    "settled": frozenset(),
}


class LedgerError(RuntimeError):
    """Base class for hard-fail ledger contract violations."""


class RunConfigurationError(LedgerError):
    """Raised when a run is missing or its durable ceiling is changed."""


class AdmissionCeilingExceeded(LedgerError):
    """Raised when a reservation would consume more than the run ceiling."""


class DuplicateLiveWork(LedgerError):
    """Raised when logical work already has a non-settled reservation."""


class IllegalReentry(LedgerError):
    """Raised when repeated logical work does not name its settled predecessor."""


class IllegalTransition(LedgerError):
    """Raised when a reservation cannot move across the requested state edge."""


class StaleWriter(LedgerError):
    """Raised when writer identity or fence no longer owns a reservation."""


class IdentifierConflict(LedgerError):
    """Raised when an immutable reservation or transition ID is reused."""


@dataclass(frozen=True)
class Reservation:
    """Immutable snapshot of one admitted attempt at logical work."""

    run_id: str
    logical_work_id: str
    reservation_id: str
    reentry_of: str | None
    admitted_sequence: int
    state: str
    writer_id: str
    writer_fence: int


class OrchestrationLedger:
    """Persistent transactional admission ledger.

    Args:
        path: SQLite database path.  Parent directories are created eagerly.
        timeout: Seconds SQLite waits for a concurrent writer transaction.

    Raises:
        OSError: If the database parent directory cannot be created.
        sqlite3.Error: If schema initialization fails.
    """

    def __init__(self, path: Path | str, *, timeout: float = 30.0) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def configure_run(self, run_id: str, admission_ceiling: int) -> None:
        """Create a run or verify its immutable admission ceiling.

        Args:
            run_id: Stable run identity.
            admission_ceiling: Maximum reservations over the run's full life.

        Raises:
            RunConfigurationError: If the ceiling is invalid or differs from
                the already-persisted value.
            sqlite3.Error: If durable persistence fails.
        """
        if admission_ceiling < 0:
            raise RunConfigurationError("admission ceiling must be non-negative")
        with self._write_transaction() as connection:
            row = connection.execute(
                "SELECT admission_ceiling FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO runs(run_id, admission_ceiling) VALUES (?, ?)",
                    (run_id, admission_ceiling),
                )
            elif row["admission_ceiling"] != admission_ceiling:
                raise RunConfigurationError(
                    f"run {run_id!r} already has admission ceiling "
                    f"{row['admission_ceiling']}"
                )

    def reserve(
        self,
        *,
        run_id: str,
        logical_work_id: str,
        reservation_id: str,
        transition_id: str,
        writer_id: str,
        reentry_of: str | None = None,
    ) -> Reservation:
        """Atomically reserve one durable run slot before dispatch.

        Replaying the same transition ID with identical identity fields is
        idempotent.  Repeating settled logical work requires ``reentry_of`` to
        name its latest reservation; an indeterminate attempt must first be
        settled, preventing ambiguous duplicate-live recovery.

        Args:
            run_id: Configured run identity.
            logical_work_id: Immutable identity shared by legal re-entries.
            reservation_id: Unique identity for this admitted attempt.
            transition_id: Unique identity for the reserve operation.
            writer_id: Identity receiving transition authority.
            reentry_of: Latest settled reservation for explicit re-entry.

        Returns:
            The newly reserved or idempotently replayed reservation.

        Raises:
            RunConfigurationError: If ``run_id`` has not been configured.
            AdmissionCeilingExceeded: If no admission slot remains.
            DuplicateLiveWork: If the logical work has live/indeterminate work.
            IllegalReentry: If historical work is not explicitly linked.
            IdentifierConflict: If an immutable ID is reused differently.
            sqlite3.Error: If durable persistence fails.
        """
        with self._write_transaction() as connection:
            replay = connection.execute(
                """SELECT t.reservation_id, t.from_state, t.to_state,
                          t.writer_id, t.kind, r.run_id, r.logical_work_id,
                          r.reentry_of
                   FROM transitions AS t
                   JOIN reservations AS r USING (reservation_id)
                   WHERE t.transition_id = ?""",
                (transition_id,),
            ).fetchone()
            if replay is not None:
                if (
                    replay["reservation_id"] != reservation_id
                    or replay["run_id"] != run_id
                    or replay["logical_work_id"] != logical_work_id
                    or replay["writer_id"] != writer_id
                    or replay["reentry_of"] != reentry_of
                    or replay["from_state"] is not None
                    or replay["to_state"] != "reserved"
                    or replay["kind"] != "reserve"
                ):
                    raise IdentifierConflict(f"transition ID {transition_id!r} was reused")
                return self._reservation(connection, reservation_id)

            run = connection.execute(
                "SELECT admission_ceiling, admissions_used, next_fence FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise RunConfigurationError(f"run {run_id!r} is not configured")
            if run["admissions_used"] >= run["admission_ceiling"]:
                raise AdmissionCeilingExceeded(f"run {run_id!r} admission ceiling reached")
            if connection.execute(
                "SELECT 1 FROM reservations WHERE reservation_id = ?", (reservation_id,)
            ).fetchone():
                raise IdentifierConflict(f"reservation ID {reservation_id!r} was reused")

            previous = connection.execute(
                """SELECT reservation_id, state FROM reservations
                   WHERE run_id = ? AND logical_work_id = ?
                   ORDER BY admitted_sequence DESC LIMIT 1""",
                (run_id, logical_work_id),
            ).fetchone()
            if previous is None:
                if reentry_of is not None:
                    raise IllegalReentry("first admission cannot name a predecessor")
            elif previous["state"] != "settled":
                raise DuplicateLiveWork(
                    f"logical work {logical_work_id!r} already has a live reservation"
                )
            elif reentry_of != previous["reservation_id"]:
                raise IllegalReentry(
                    "re-entry must name the latest settled reservation"
                )

            sequence = run["admissions_used"] + 1
            fence = run["next_fence"] + 1
            connection.execute(
                "UPDATE runs SET admissions_used = ?, next_fence = ? WHERE run_id = ?",
                (sequence, fence, run_id),
            )
            connection.execute(
                """INSERT INTO reservations(
                       reservation_id, run_id, logical_work_id, reentry_of,
                       admitted_sequence, state, writer_id, writer_fence
                   ) VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?)""",
                (
                    reservation_id,
                    run_id,
                    logical_work_id,
                    reentry_of,
                    sequence,
                    writer_id,
                    fence,
                ),
            )
            connection.execute(
                """INSERT INTO transitions(
                       transition_id, reservation_id, from_state, to_state,
                       writer_id, writer_fence, result_writer_id,
                       result_writer_fence, kind
                   ) VALUES (?, ?, NULL, 'reserved', ?, ?, ?, ?, 'reserve')""",
                (transition_id, reservation_id, writer_id, fence, writer_id, fence),
            )
            return self._reservation(connection, reservation_id)

    def advance(
        self,
        *,
        reservation_id: str,
        transition_id: str,
        writer_id: str,
        writer_fence: int,
        to_state: str,
    ) -> Reservation:
        """Atomically perform one legal, fenced state transition.

        Settlement is deliberately independent of admission accounting and is
        legal from every non-settled state.  Thus a full run can always record
        a terminal outcome after any reserve/dispatch/start crash cut.

        Args:
            reservation_id: Attempt being advanced.
            transition_id: Immutable ID making this operation idempotent.
            writer_id: Current writer identity.
            writer_fence: Current writer generation.
            to_state: One of dispatching, started, indeterminate, or settled.

        Returns:
            The current reservation snapshot.

        Raises:
            IdentifierConflict: If ``transition_id`` was reused differently.
            IllegalTransition: If the reservation or state edge is invalid.
            StaleWriter: If the caller no longer owns writer authority.
            sqlite3.Error: If durable persistence fails.
        """
        if to_state not in _STATES or to_state == "reserved":
            raise IllegalTransition(f"invalid transition target {to_state!r}")
        with self._write_transaction() as connection:
            replay = connection.execute(
                "SELECT * FROM transitions WHERE transition_id = ?", (transition_id,)
            ).fetchone()
            if replay is not None:
                if (
                    replay["reservation_id"] != reservation_id
                    or replay["to_state"] != to_state
                    or replay["writer_id"] != writer_id
                    or replay["writer_fence"] != writer_fence
                    or replay["kind"] != "advance"
                ):
                    raise IdentifierConflict(f"transition ID {transition_id!r} was reused")
                return self._reservation(connection, reservation_id)

            current = self._reservation(connection, reservation_id)
            self._require_writer(current, writer_id, writer_fence)
            if to_state not in _LEGAL_TRANSITIONS[current.state]:
                raise IllegalTransition(f"cannot transition {current.state!r} to {to_state!r}")
            connection.execute(
                "UPDATE reservations SET state = ? WHERE reservation_id = ?",
                (to_state, reservation_id),
            )
            connection.execute(
                """INSERT INTO transitions(
                       transition_id, reservation_id, from_state, to_state,
                       writer_id, writer_fence, result_writer_id,
                       result_writer_fence, kind
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'advance')""",
                (
                    transition_id,
                    reservation_id,
                    current.state,
                    to_state,
                    writer_id,
                    writer_fence,
                    writer_id,
                    writer_fence,
                ),
            )
            return self._reservation(connection, reservation_id)

    def transfer_writer(
        self,
        *,
        reservation_id: str,
        transition_id: str,
        writer_id: str,
        writer_fence: int,
        new_writer_id: str,
    ) -> Reservation:
        """Atomically fence the current writer and transfer recovery authority.

        Args:
            reservation_id: Non-settled attempt whose authority is transferred.
            transition_id: Immutable ID making this transfer idempotent.
            writer_id: Current writer identity.
            writer_fence: Current writer generation.
            new_writer_id: Identity receiving a fresh monotonic fence.

        Returns:
            Reservation carrying the new writer identity and fence.

        Raises:
            IdentifierConflict: If ``transition_id`` was reused differently.
            IllegalTransition: If the reservation is already settled.
            StaleWriter: If the caller no longer owns writer authority.
            sqlite3.Error: If durable persistence fails.
        """
        with self._write_transaction() as connection:
            replay = connection.execute(
                "SELECT * FROM transitions WHERE transition_id = ?", (transition_id,)
            ).fetchone()
            if replay is not None:
                current = self._reservation(connection, reservation_id)
                if (
                    replay["reservation_id"] != reservation_id
                    or replay["from_state"] != replay["to_state"]
                    or replay["writer_id"] != writer_id
                    or replay["writer_fence"] != writer_fence
                    or replay["result_writer_id"] != new_writer_id
                    or replay["kind"] != "transfer"
                ):
                    raise IdentifierConflict(f"transition ID {transition_id!r} was reused")
                return current

            current = self._reservation(connection, reservation_id)
            self._require_writer(current, writer_id, writer_fence)
            if current.state == "settled":
                raise IllegalTransition("cannot transfer a settled reservation")
            run = connection.execute(
                "SELECT next_fence FROM runs WHERE run_id = ?", (current.run_id,)
            ).fetchone()
            new_fence = run["next_fence"] + 1
            connection.execute(
                "UPDATE runs SET next_fence = ? WHERE run_id = ?",
                (new_fence, current.run_id),
            )
            connection.execute(
                """UPDATE reservations SET writer_id = ?, writer_fence = ?
                   WHERE reservation_id = ?""",
                (new_writer_id, new_fence, reservation_id),
            )
            connection.execute(
                """INSERT INTO transitions(
                       transition_id, reservation_id, from_state, to_state,
                       writer_id, writer_fence, result_writer_id,
                       result_writer_fence, kind
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'transfer')""",
                (
                    transition_id,
                    reservation_id,
                    current.state,
                    current.state,
                    writer_id,
                    writer_fence,
                    new_writer_id,
                    new_fence,
                ),
            )
            return self._reservation(connection, reservation_id)

    def get_reservation(self, reservation_id: str) -> Reservation:
        """Read one durable reservation snapshot.

        Args:
            reservation_id: Attempt identity to load.

        Returns:
            The reservation snapshot.

        Raises:
            IllegalTransition: If the reservation does not exist.
            sqlite3.Error: If the database cannot be read.
        """
        with self._connect() as connection:
            return self._reservation(connection, reservation_id)

    def run_usage(self, run_id: str) -> tuple[int, int]:
        """Return durable ``(admissions_used, admission_ceiling)`` for a run.

        Args:
            run_id: Configured run identity.

        Returns:
            Used admissions and immutable ceiling.

        Raises:
            RunConfigurationError: If the run is unknown.
            sqlite3.Error: If the database cannot be read.
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT admissions_used, admission_ceiling FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise RunConfigurationError(f"run {run_id!r} is not configured")
            return row["admissions_used"], row["admission_ceiling"]

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    admission_ceiling INTEGER NOT NULL CHECK (admission_ceiling >= 0),
                    admissions_used INTEGER NOT NULL DEFAULT 0 CHECK (admissions_used >= 0),
                    next_fence INTEGER NOT NULL DEFAULT 0 CHECK (next_fence >= 0),
                    CHECK (admissions_used <= admission_ceiling)
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    logical_work_id TEXT NOT NULL,
                    reentry_of TEXT REFERENCES reservations(reservation_id),
                    admitted_sequence INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('reserved', 'dispatching', 'started', 'settled', 'indeterminate')
                    ),
                    writer_id TEXT NOT NULL,
                    writer_fence INTEGER NOT NULL,
                    UNIQUE (run_id, admitted_sequence),
                    UNIQUE (run_id, logical_work_id, admitted_sequence)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_live_reservation_per_logical_work
                    ON reservations(run_id, logical_work_id)
                    WHERE state != 'settled';
                CREATE TABLE IF NOT EXISTS transitions (
                    transition_id TEXT PRIMARY KEY,
                    reservation_id TEXT NOT NULL REFERENCES reservations(reservation_id),
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    writer_id TEXT NOT NULL,
                    writer_fence INTEGER NOT NULL,
                    result_writer_id TEXT NOT NULL,
                    result_writer_fence INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('reserve', 'advance', 'transfer'))
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _write_transaction(self) -> _WriteTransaction:
        return _WriteTransaction(self._connect())

    @staticmethod
    def _reservation(
        connection: sqlite3.Connection, reservation_id: str
    ) -> Reservation:
        row = connection.execute(
            "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
        ).fetchone()
        if row is None:
            raise IllegalTransition(f"unknown reservation {reservation_id!r}")
        return Reservation(
            run_id=row["run_id"],
            logical_work_id=row["logical_work_id"],
            reservation_id=row["reservation_id"],
            reentry_of=row["reentry_of"],
            admitted_sequence=row["admitted_sequence"],
            state=row["state"],
            writer_id=row["writer_id"],
            writer_fence=row["writer_fence"],
        )

    @staticmethod
    def _require_writer(
        reservation: Reservation, writer_id: str, writer_fence: int
    ) -> None:
        if (
            reservation.writer_id != writer_id
            or reservation.writer_fence != writer_fence
        ):
            raise StaleWriter(
                f"writer {writer_id!r} fence {writer_fence} does not own "
                f"reservation {reservation.reservation_id!r}"
            )


class _WriteTransaction:
    """Commit-or-rollback context for one serialized ledger mutation."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        self.connection.execute("BEGIN IMMEDIATE")
        return self.connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            if exc_type is None:
                self.connection.execute("COMMIT")
            else:
                self.connection.execute("ROLLBACK")
        finally:
            self.connection.close()
        return False
