"""Durable host-bound terminal batching for conditional Release C.

The coordinator implements INTENT criterion #4.  A batch is fixed at reserve
time, terminal delivery is a versioned idempotent SQLite transition, and a
later batch cannot be admitted until the current batch is fully drained and
durably settled.  Promotion requires exact ``native_bounded`` authority plus
two executable host primitives bound to the same evidence identity.

Public surface:

* :class:`HostPrimitives` binds collection and termination to evidence.
* :class:`TerminalEvent` and :class:`TerminalWake` carry host event identity.
* :class:`OrchestrationBatchCoordinator` reserves, collects, settles, and reads.

Concurrency: every mutation uses ``BEGIN IMMEDIATE`` against the same durable
SQLite database as :class:`runtime.orchestration_ledger.OrchestrationLedger`.
Separate coordinator instances are safe across threads and processes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3

from runtime.capability_authority import (
    Capability,
    CapabilityAuthority,
    CapabilityKey,
)
from runtime.orchestration_ledger import OrchestrationLedger


class BatchProtocolError(RuntimeError):
    """Base class for fail-closed batch protocol violations."""


class BatchPromotionBlocked(BatchProtocolError):
    """Raised when exact authority or executable host primitives are absent."""


class BatchNotDrained(BatchProtocolError):
    """Raised when refill or settlement is attempted before a full drain."""


class BatchIdentityConflict(BatchProtocolError):
    """Raised when an immutable batch or terminal identity is rebound."""


class TaskRootRejected(BatchProtocolError):
    """Raised when task-level work attempts to use the supervisor root."""


class ModelPollingRejected(BatchProtocolError):
    """Raised for model-authored polling at the host event boundary."""


class UnknownBatch(BatchProtocolError):
    """Raised when a batch or member does not exist."""


@dataclass(frozen=True)
class TerminalEvent:
    """One host-emitted terminal transition."""

    task_id: str
    outcome: str
    terminal_set_version: int
    wake_sequence: int


@dataclass(frozen=True)
class TerminalWake:
    """The single durable model wake for one terminal-set version."""

    batch_id: str
    terminal_set_version: int
    wake_sequence: int


@dataclass(frozen=True)
class BatchSnapshot:
    """Immutable caller-facing state for one fixed batch."""

    batch_id: str
    run_id: str
    task_ids: tuple[str, ...]
    terminal_task_ids: tuple[str, ...]
    terminal_set_version: int
    wake_sequence: int
    state: str
    host_id: str
    root_task_id: str
    evidence_id: str
    terminal_collection_primitive: str
    active_child_termination_primitive: str


@dataclass(frozen=True)
class HostPrimitives:
    """Executable host operations proven by one capability evidence record.

    ``collect_terminal`` must return the complete event set delivered by one
    host wake. ``terminate_active_child`` is retained as the executable proof
    required before promotion and is exposed through :meth:`terminate_child`.
    """

    evidence_id: str
    collect_terminal: Callable[[str], Iterable[TerminalEvent]]
    terminate_active_child: Callable[[str, str], bool]


@dataclass(frozen=True)
class _CapabilityBinding:
    """Exact immutable authority and executable binding persisted per batch."""

    evidence_id: str
    terminal_collection_primitive: str
    active_child_termination_primitive: str


class OrchestrationBatchCoordinator:
    """Coordinate one durable, fixed, host-bound batch at a time per run."""

    def __init__(
        self,
        ledger: OrchestrationLedger,
        *,
        authority: CapabilityAuthority,
        capability_key: CapabilityKey,
        installed_export_fingerprint: str,
        now: Callable[[], int],
        host_id: str,
        root_task_id: str,
        primitives: HostPrimitives,
    ) -> None:
        """Bind the coordinator to an exact host capability tuple.

        Args:
            ledger: Existing durable admission ledger; its SQLite file stores
                the batch tables as well.
            authority: Exact capability authority.
            capability_key: Invocation tuple whose evidence permits batching.
            installed_export_fingerprint: Currently installed export identity.
            now: Deterministic epoch-second source used for expiry checks.
            host_id: Non-model host identity allowed to deliver events.
            root_task_id: Immutable supervisor identity excluded from members.
            primitives: Executable operations bound to the evidence identity.
        """
        self._ledger = ledger
        self._authority = authority
        self._capability_key = capability_key
        self._fingerprint = installed_export_fingerprint
        self._now = now
        self._host_id = host_id
        self._root_task_id = root_task_id
        self._primitives = primitives
        self._initialize()

    def reserve_batch(
        self,
        *,
        run_id: str,
        batch_id: str,
        task_ids: Iterable[str],
    ) -> BatchSnapshot:
        """Reserve an immutable batch after exact promotion validation.

        Idempotent replay of an identical settled or live batch is allowed.
        A distinct batch for the run is rejected until every prior member is
        terminal and the prior batch's settlement commit has completed.

        Raises:
            BatchPromotionBlocked: If authority or host primitives are invalid.
            TaskRootRejected: If the root appears as task-level work.
            BatchNotDrained: If a prior batch has not durably settled.
            BatchIdentityConflict: If ``batch_id`` is reused differently.
            sqlite3.Error: If persistence fails.
        """
        binding = self._require_promoted()
        members = tuple(task_ids)
        if not members or len(set(members)) != len(members):
            raise BatchIdentityConflict("batch members must be non-empty and unique")
        if self._root_task_id in members:
            raise TaskRootRejected("supervisor root cannot be task-level batch work")

        with self._write_transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM orchestration_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if existing is not None:
                self._require_batch_binding(existing)
                snapshot = self._snapshot(connection, batch_id)
                if (
                    snapshot.run_id != run_id
                    or snapshot.task_ids != members
                    or snapshot.host_id != self._host_id
                    or snapshot.root_task_id != self._root_task_id
                    or snapshot.evidence_id != binding.evidence_id
                    or snapshot.terminal_collection_primitive
                    != binding.terminal_collection_primitive
                    or snapshot.active_child_termination_primitive
                    != binding.active_child_termination_primitive
                ):
                    raise BatchIdentityConflict(f"batch ID {batch_id!r} was reused")
                return snapshot

            unsettled = connection.execute(
                "SELECT batch_id FROM orchestration_batches "
                "WHERE run_id = ? AND state != 'settled' LIMIT 1",
                (run_id,),
            ).fetchone()
            if unsettled is not None:
                raise BatchNotDrained(
                    f"batch {unsettled['batch_id']!r} must settle before refill"
                )
            connection.execute(
                """INSERT INTO orchestration_batches(
                       batch_id, run_id, host_id, root_task_id, evidence_id,
                       terminal_collection_primitive,
                       active_child_termination_primitive, member_count,
                       terminal_count, terminal_set_version, wake_sequence, state
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 'active')""",
                (
                    batch_id,
                    run_id,
                    self._host_id,
                    self._root_task_id,
                    binding.evidence_id,
                    binding.terminal_collection_primitive,
                    binding.active_child_termination_primitive,
                    len(members),
                ),
            )
            connection.executemany(
                "INSERT INTO orchestration_batch_members(batch_id, ordinal, task_id) "
                "VALUES (?, ?, ?)",
                ((batch_id, ordinal, task_id) for ordinal, task_id in enumerate(members)),
            )
            return self._snapshot(connection, batch_id)

    def collect_once(self, batch_id: str, *, actor_id: str) -> tuple[TerminalWake, ...]:
        """Invoke the host collector once and persist every returned event.

        Args:
            batch_id: Fixed batch to drain.
            actor_id: Must equal the bound non-model host identity.

        Returns:
            Newly emitted wakes; exact replays produce no additional wake.

        Raises:
            ModelPollingRejected: If a model/non-host actor attempts polling.
            BatchProtocolError: If a delivered event violates the state machine.
        """
        self._require_host(actor_id)
        with self._read_connection() as connection:
            self._require_batch_binding(self._batch_row(connection, batch_id))
        wakes: list[TerminalWake] = []
        for event in self._primitives.collect_terminal(batch_id):
            wake = self.record_terminal(batch_id, event=event, actor_id=actor_id)
            if wake is not None:
                wakes.append(wake)
        return tuple(wakes)

    def record_terminal(
        self, batch_id: str, *, event: TerminalEvent, actor_id: str
    ) -> TerminalWake | None:
        """Persist one host terminal event and its at-most-once wake atomically."""
        self._require_host(actor_id)
        if event.terminal_set_version < 1 or event.wake_sequence < 1:
            raise BatchIdentityConflict("terminal version and wake sequence must be positive")
        with self._write_transaction() as connection:
            batch = self._batch_row(connection, batch_id)
            self._require_batch_binding(batch)
            member = connection.execute(
                "SELECT outcome FROM orchestration_batch_members "
                "WHERE batch_id = ? AND task_id = ?",
                (batch_id, event.task_id),
            ).fetchone()
            if member is None:
                raise UnknownBatch(f"task {event.task_id!r} is not in batch {batch_id!r}")

            replay = connection.execute(
                """SELECT task_id, outcome FROM orchestration_terminal_events
                   WHERE batch_id = ? AND terminal_set_version = ? AND wake_sequence = ?""",
                (batch_id, event.terminal_set_version, event.wake_sequence),
            ).fetchone()
            if replay is not None:
                if replay["task_id"] != event.task_id or replay["outcome"] != event.outcome:
                    raise BatchIdentityConflict("terminal transition identity was reused")
                return None
            task_replay = connection.execute(
                """SELECT terminal_set_version, wake_sequence, outcome
                   FROM orchestration_terminal_events
                   WHERE batch_id = ? AND task_id = ?""",
                (batch_id, event.task_id),
            ).fetchone()
            if task_replay is not None:
                raise BatchIdentityConflict("terminal transition identity was rebound")
            if member["outcome"] is not None:
                raise BatchIdentityConflict(
                    f"task {event.task_id!r} terminal state lacks its immutable event"
                )
            if batch["state"] == "settled":
                raise BatchIdentityConflict("settled batch cannot accept new terminal work")
            if event.terminal_set_version != batch["terminal_set_version"] + 1:
                raise BatchIdentityConflict("terminal-set version must advance exactly once")
            if event.wake_sequence <= batch["wake_sequence"]:
                raise BatchIdentityConflict("wake sequence must increase monotonically")

            connection.execute(
                "UPDATE orchestration_batch_members SET outcome = ? "
                "WHERE batch_id = ? AND task_id = ?",
                (event.outcome, batch_id, event.task_id),
            )
            connection.execute(
                """INSERT INTO orchestration_terminal_events(
                       batch_id, terminal_set_version, wake_sequence, task_id, outcome
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    batch_id,
                    event.terminal_set_version,
                    event.wake_sequence,
                    event.task_id,
                    event.outcome,
                ),
            )
            terminal_count = batch["terminal_count"] + 1
            connection.execute(
                """UPDATE orchestration_batches
                   SET terminal_count = ?, terminal_set_version = ?,
                       wake_sequence = ?, state = 'draining'
                   WHERE batch_id = ?""",
                (
                    terminal_count,
                    event.terminal_set_version,
                    event.wake_sequence,
                    batch_id,
                ),
            )
            return TerminalWake(
                batch_id, event.terminal_set_version, event.wake_sequence
            )

    def settle_batch(self, batch_id: str) -> BatchSnapshot:
        """Durably settle a fully drained batch; replay is idempotent."""
        with self._write_transaction() as connection:
            batch = self._batch_row(connection, batch_id)
            self._require_batch_binding(batch)
            if batch["state"] == "settled":
                return self._snapshot(connection, batch_id)
            if batch["terminal_count"] != batch["member_count"]:
                raise BatchNotDrained(
                    "every fixed batch member must be terminal before settlement"
                )
            connection.execute(
                "UPDATE orchestration_batches SET state = 'settled' WHERE batch_id = ?",
                (batch_id,),
            )
            return self._snapshot(connection, batch_id)

    def terminate_child(self, batch_id: str, task_id: str, *, actor_id: str) -> bool:
        """Invoke the evidence-bound active-child termination primitive."""
        self._require_host(actor_id)
        with self._read_connection() as connection:
            batch = self._batch_row(connection, batch_id)
            self._require_batch_binding(batch)
            if connection.execute(
                "SELECT 1 FROM orchestration_batch_members WHERE batch_id = ? AND task_id = ?",
                (batch_id, task_id),
            ).fetchone() is None:
                raise UnknownBatch(f"task {task_id!r} is not in batch {batch_id!r}")
        return bool(self._primitives.terminate_active_child(batch_id, task_id))

    def snapshot(self, batch_id: str) -> BatchSnapshot:
        """Read durable batch state without invoking terminal collection."""
        with self._read_connection() as connection:
            self._require_batch_binding(self._batch_row(connection, batch_id))
            return self._snapshot(connection, batch_id)

    def poll(self, batch_id: str) -> None:
        """Reject model-authored polling unconditionally.

        Host runtimes use ``collect_once`` in response to a native terminal
        signal; polling is not a supported collection mechanism.
        """
        raise ModelPollingRejected(
            f"model-authored polling is prohibited for batch {batch_id!r}"
        )

    def _require_promoted(self) -> _CapabilityBinding:
        if self._capability_key.host != self._host_id:
            raise BatchPromotionBlocked("coordinator host does not match capability evidence")
        resolution = self._authority.resolve(
            self._capability_key,
            installed_export_fingerprint=self._fingerprint,
            now=self._now(),
        )
        if resolution.capability is not Capability.NATIVE_BOUNDED:
            raise BatchPromotionBlocked(f"bounded batching blocked: {resolution.reason}")
        if (
            resolution.evidence_id is None
            or resolution.evidence_id != self._primitives.evidence_id
        ):
            raise BatchPromotionBlocked("host primitives do not match exact capability evidence")
        if not callable(self._primitives.collect_terminal) or not callable(
            self._primitives.terminate_active_child
        ):
            raise BatchPromotionBlocked("executable host primitives are required")
        collection_identity = _primitive_identity(self._primitives.collect_terminal)
        termination_identity = _primitive_identity(
            self._primitives.terminate_active_child
        )
        if (
            collection_identity is None
            or termination_identity is None
            or collection_identity != resolution.terminal_collection_primitive
            or termination_identity
            != resolution.active_child_termination_primitive
        ):
            raise BatchPromotionBlocked(
                "executable host primitives do not match immutable capability claims"
            )
        return _CapabilityBinding(
            resolution.evidence_id, collection_identity, termination_identity
        )

    def _require_host(self, actor_id: str) -> None:
        if actor_id != self._host_id:
            raise ModelPollingRejected("only the bound host may collect terminal events")

    def _require_batch_binding(self, batch: sqlite3.Row) -> None:
        """Reject any coordinator whose immutable identity differs from the batch."""

        collection_identity = _primitive_identity(self._primitives.collect_terminal)
        termination_identity = _primitive_identity(
            self._primitives.terminate_active_child
        )
        if (
            batch["host_id"] != self._host_id
            or batch["root_task_id"] != self._root_task_id
            or batch["evidence_id"] != self._primitives.evidence_id
            or batch["terminal_collection_primitive"] != collection_identity
            or batch["active_child_termination_primitive"] != termination_identity
        ):
            raise BatchIdentityConflict(
                "coordinator identity does not match immutable batch binding"
            )

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orchestration_batches (
                    batch_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    host_id TEXT NOT NULL,
                    root_task_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    terminal_collection_primitive TEXT NOT NULL,
                    active_child_termination_primitive TEXT NOT NULL,
                    member_count INTEGER NOT NULL CHECK (member_count > 0),
                    terminal_count INTEGER NOT NULL DEFAULT 0,
                    terminal_set_version INTEGER NOT NULL DEFAULT 0,
                    wake_sequence INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL CHECK (state IN ('active', 'draining', 'settled')),
                    CHECK (terminal_count >= 0 AND terminal_count <= member_count)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_unsettled_batch_per_run
                    ON orchestration_batches(run_id) WHERE state != 'settled';
                CREATE TABLE IF NOT EXISTS orchestration_batch_members (
                    batch_id TEXT NOT NULL REFERENCES orchestration_batches(batch_id),
                    ordinal INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    outcome TEXT,
                    PRIMARY KEY (batch_id, task_id),
                    UNIQUE (batch_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS orchestration_terminal_events (
                    batch_id TEXT NOT NULL REFERENCES orchestration_batches(batch_id),
                    terminal_set_version INTEGER NOT NULL,
                    wake_sequence INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    PRIMARY KEY (batch_id, terminal_set_version, wake_sequence),
                    UNIQUE (batch_id, terminal_set_version),
                    UNIQUE (batch_id, wake_sequence),
                    UNIQUE (batch_id, task_id)
                );
                """
            )
            self._add_binding_columns_for_legacy_schema(connection)
        finally:
            connection.close()

    @staticmethod
    def _add_binding_columns_for_legacy_schema(connection: sqlite3.Connection) -> None:
        """Add nullable binding columns so legacy rows remain visibly unbound."""

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(orchestration_batches)"
            ).fetchall()
        }
        for name in (
            "root_task_id",
            "terminal_collection_primitive",
            "active_child_termination_primitive",
        ):
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE orchestration_batches ADD COLUMN {name} TEXT"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._ledger.path, timeout=self._ledger.timeout, isolation_level=None
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield one read connection and close it on success or failure."""

        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _write_transaction(self) -> _BatchWriteTransaction:
        return _BatchWriteTransaction(self._connect())

    @staticmethod
    def _batch_row(connection: sqlite3.Connection, batch_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM orchestration_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise UnknownBatch(f"unknown batch {batch_id!r}")
        return row

    @classmethod
    def _snapshot(cls, connection: sqlite3.Connection, batch_id: str) -> BatchSnapshot:
        row = cls._batch_row(connection, batch_id)
        members = connection.execute(
            "SELECT task_id, outcome FROM orchestration_batch_members "
            "WHERE batch_id = ? ORDER BY ordinal",
            (batch_id,),
        ).fetchall()
        return BatchSnapshot(
            batch_id=row["batch_id"],
            run_id=row["run_id"],
            task_ids=tuple(member["task_id"] for member in members),
            terminal_task_ids=tuple(
                member["task_id"] for member in members if member["outcome"] is not None
            ),
            terminal_set_version=row["terminal_set_version"],
            wake_sequence=row["wake_sequence"],
            state=row["state"],
            host_id=row["host_id"],
            root_task_id=row["root_task_id"],
            evidence_id=row["evidence_id"],
            terminal_collection_primitive=row["terminal_collection_primitive"],
            active_child_termination_primitive=row[
                "active_child_termination_primitive"
            ],
        )


def _primitive_identity(primitive: object) -> str | None:
    """Derive the stable import identity of an executable host primitive."""

    function = getattr(primitive, "__func__", primitive)
    module = getattr(function, "__module__", None)
    qualname = getattr(function, "__qualname__", None)
    if not isinstance(module, str) or not module:
        return None
    if not isinstance(qualname, str) or not qualname or "<locals>" in qualname:
        return None
    return f"{module}:{qualname}"


class _BatchWriteTransaction:
    """Commit-or-rollback context for one serialized batch mutation."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> sqlite3.Connection:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            self._connection.close()
            raise
        return self._connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        try:
            if exc_type is None:
                self._connection.execute("COMMIT")
            else:
                self._connection.execute("ROLLBACK")
        finally:
            self._connection.close()
        return False
