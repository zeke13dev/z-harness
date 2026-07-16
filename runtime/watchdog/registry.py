"""sessions.json registry primitives for the session-watchdog daemon.

Purpose (T003, criterion #9): define the ``sessions.json`` record schema and the
low-level, dependency-free primitives every later watchdog level composes:

- the record schema factory (``new_session_record``) and its validator
  (``validate_record``), carrying ``schema_version`` from day one;
- the session lifecycle + handoff-choreography state enum (``VALID_STATES``) and
  a hard-fail transition validator (``transition`` / ``is_valid_transition``);
- the ``ws-<uuid4>`` session-id generator and ``zw-<slug>-<shortid>`` tmux-name
  generator — both irreversible public-surface contracts;
- a flock-guarded temp+``os.replace`` atomic JSON write (``atomic_write_json``),
  the flush primitive a SIGTERM handler will call in a later level;
- a daemon single-instance pidfile lock (``acquire_single_instance_lock``) with a
  ``kill -0`` liveness check and automatic stale-lock cleanup;
- an append helper for ``signals.jsonl`` (``append_signal``), the internal event
  log for daemon events such as ``judge_degraded``, size-capped per
  ``watchdog.signals_max_mb``.

Non-scope (level 1 owns these — deliberately absent here): the SIGTERM handler
itself, the startup reconcile pass, and the poll loop. This module ships
primitives only.

Design decisions:
- D2 (offset-tracked reads): each record persists ``transcript_offset``, the
  byte offset last consumed from ``transcript_path``, so reads resume where they
  left off across daemon restarts.
- D7 (fanout graph in the daemon's own registry): parent/child linkage lives in
  each record's ``parent_id`` / ``children`` fields — the watchdog never takes
  registry ownership of the sessions it watches.
- The record schema, ``SCHEMA_VERSION``, and the ``ws-`` / ``zw-`` prefixes are
  frozen public surface (see package docstring).

Concurrency (STYLE.md:P-006): ``atomic_write_json`` serializes writers on a
sidecar ``<path>.lock`` (``flock`` LOCK_EX) and publishes via ``os.replace`` so a
concurrent reader always observes either the old or the new file, never a torn
one. Generic ``read_json`` remains best-effort; authoritative registry loading
takes the sidecar lock, completes a valid ``.<name>.next`` replacement, migrates
v1 to v2, and rejects corrupt, future, or mixed-version state.
A caller mutating the registry (add/transition some records, write it back) must
NOT read a whole-file snapshot, mutate that snapshot, and write it back while a
concurrent writer does the same — the two snapshots diverge and whichever writes
last silently clobbers the other's records (a lost update). ``fanout.run_fanout``
(adds fanout children) and the daemon's poll pass (transitions the polled
session) are exactly this pair. Route every such mutation through
``locked_registry_update(path, mutate_fn)``: it takes the sidecar lock, re-reads
the registry FRESH under that lock, applies ONLY the caller's own record changes
(``mutate_fn`` mutates the fresh mapping in place — the polled session's record,
the new children, the marked-orphaned records — never a stale whole-file
overwrite), writes under the held lock, and releases. Because the merge base is
the locked re-read, a record a concurrent writer persisted after this caller's
own in-memory snapshot was taken survives. ``locked_registry_update`` is built on
``hold_registry_lock`` (holds the SAME ``<path>.lock`` sidecar
``atomic_write_json`` locks on, so any writer using the default ``lock=True``
blocks until the cycle releases it) + ``write_registry(..., lock=False)`` (the
holder must pass ``lock=False`` to avoid self-deadlocking on its own already-held
lock). A shutdown flush that legitimately writes an authoritative snapshot (the
SIGTERM handler) still holds ``hold_registry_lock`` around its
``write_registry(..., lock=False)`` so it never tears a concurrent writer's
update, but does not merge — its in-memory mapping IS the authority at exit.

Config (STYLE.md:P-004): ``get_config_int`` shells out to ``scripts/config.py``
rather than reimplementing the config precedence chain; nothing threshold-shaped
is hardcoded (T002).

Sealed joins (T007, criterion #6): fanout admissions create one explicit open
epoch per coordinator. Sealing closes admission; the final authorized outcome
atomically creates stable join and wake-outbox records. External delivery is
at least once until a generation-fenced acknowledgement deduplicates logical
coordinator handling.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

# ── schema constants (frozen public surface) ─────────────────────────────────

SCHEMA_VERSION = 1
"""Frozen session-record and handoff-artifact schema version."""

REGISTRY_VERSION = 2
"""Authoritative sessions.json document schema version."""

RECORD_SCHEMA_VERSION = SCHEMA_VERSION
"""Explicit alias separating record compatibility from the v2 envelope."""

_REGISTRY_SECTIONS: tuple[str, ...] = (
    "sessions",
    "coordinators",
    "children",
    "groups",
    "workstreams",
    "outcomes",
    "joins",
    "outbox",
    "action_markers",
    "artifact_pointers",
)
REGISTRY_SECTIONS = frozenset(_REGISTRY_SECTIONS)
"""Durable v2 registry collections preserved by every locked mutation."""

SESSION_ID_PREFIX = "ws-"
"""Session-id prefix; full form is ``ws-<uuid4>`` (see ``new_session_id``)."""

TMUX_NAME_PREFIX = "zw-"
"""tmux session-name prefix; full form ``zw-<slug>-<shortid>`` (INTENT surface)."""

VALID_HOSTS = frozenset({"claude", "codex", "omp"})
"""Hosts the watchdog can babysit (INTENT: full codex/omp parity in v1)."""

# Repo root: registry.py -> watchdog -> runtime -> <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Ordered field list — the COMPLETE record schema (T003 acceptance).
_REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "session_id",
    "slug",
    "plan_dir",
    "host",
    "tmux_target",
    "transcript_path",
    "transcript_offset",
    "state",
    "state_changed_at",
    "state_generation",
    "created_at",
    "last_seen",
    "last_context_check",
    "last_nudge_at",
    "nudge_count",
    "parent_id",
    "children",
)
REQUIRED_FIELDS = frozenset(_REQUIRED_FIELDS)
"""The complete set of keys every valid session record must carry."""

# ── state machine (session lifecycle + handoff choreography) ─────────────────

INITIAL_STATE = "registered"

# Session lifecycle states.
_LIFECYCLE_STATES = frozenset({
    "allocating",
    "registered",
    "running",
    "needs_input",
    "stuck",
    "awaiting_children",
    "orphaned",
    "cancelled",
    "failed",
    "done",
})
# Context-threshold handoff choreography states.
_HANDOFF_STATES = frozenset({
    "handoff_requested",
    "handoff_written",
    "cleared",
    "resumed",
})
VALID_STATES = _LIFECYCLE_STATES | _HANDOFF_STATES
"""Every accepted ``state`` value (lifecycle + handoff choreography)."""

TERMINAL_STATES = frozenset({"done", "failed", "cancelled", "orphaned"})
"""States with no outgoing transition. ``orphaned`` is never auto-adopted."""

CHILD_OUTCOME_STATES = frozenset({"done", "failed", "cancelled", "orphaned"})
"""Versioned explicit and reconciled child terminal outcome values."""

CHILD_OUTCOME_SCHEMA_VERSION = 1
"""Frozen child terminal-report payload version."""

CHILD_SUPERVISION_SCHEMA_VERSION = 1
GROUP_SCHEMA_VERSION = 1
JOIN_SCHEMA_VERSION = 1
WAKE_OUTBOX_SCHEMA_VERSION = 1
DEFAULT_CHILD_LEASE_TIMEOUT_S = 3600
DEFAULT_CHILD_GRACE_S = 300
DEFAULT_CHILD_RESOLUTION_WINDOW_S = 60

# Adjacency list of legal transitions. A state absent as a key (or an empty set)
# is terminal. Self-transitions are intentionally NOT listed: re-stamping the
# same state is not a transition and would falsely bump state_changed_at.
# ``cleared -> handoff_requested`` is deliberately absent (a cleared session
# resumes; it does not re-request a handoff mid-flight).
_TRANSITIONS: dict[str, frozenset[str]] = {
    "allocating": frozenset({"registered", "orphaned", "failed", "cancelled"}),
    "registered": frozenset({
        "running", "needs_input", "awaiting_children",
        "handoff_requested", "orphaned", "failed", "cancelled", "done",
    }),
    "running": frozenset({
        "needs_input", "stuck", "awaiting_children",
        "handoff_requested", "orphaned", "failed", "cancelled", "done",
    }),
    "needs_input": frozenset({"running", "orphaned", "failed", "cancelled", "done"}),
    "stuck": frozenset({
        "running", "needs_input", "handoff_requested",
        "orphaned", "failed", "cancelled", "done",
    }),
    "awaiting_children": frozenset({
        "running", "orphaned", "failed", "cancelled", "done",
    }),
    # Handoff choreography is a linear pipeline; each step may still be orphaned
    # or fail out of band, but cannot skip forward or loop back.
    "handoff_requested": frozenset({
        "handoff_written", "orphaned", "failed", "cancelled",
    }),
    "handoff_written": frozenset({"cleared", "orphaned", "failed", "cancelled"}),
    "cleared": frozenset({"resumed", "orphaned", "failed", "cancelled"}),
    "resumed": frozenset({"running", "orphaned", "failed", "cancelled", "done"}),
    # Terminal states.
    "orphaned": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
    "done": frozenset(),
}


class InvalidTransitionError(ValueError):
    """Raised by ``transition`` on an illegal or unknown-state transition."""


class DaemonAlreadyRunningError(RuntimeError):
    """Raised by ``acquire_single_instance_lock`` when a live daemon holds it."""


class RegistryFormatError(ValueError):
    """Raised when authoritative registry state is malformed or mixed-version."""


class UnsupportedRegistryVersionError(RegistryFormatError):
    """Raised when registry state was written by a newer implementation."""


class RootRegistrationConflictError(ValueError):
    """Raised when an idempotency key is replayed with a different manifest."""


class ChildOutcomeError(ValueError):
    """Base class for rejected child terminal outcome mutations."""


class UnauthorizedChildReporterError(ChildOutcomeError):
    """Raised when a reporter is not authorized for the addressed child."""


class StaleChildGenerationError(ChildOutcomeError):
    """Raised when an outcome addresses a superseded child generation."""


class ChildOutcomeConflictError(ChildOutcomeError):
    """Raised when one child generation receives conflicting explicit reports."""


class GroupAdmissionError(ValueError):
    """Raised when child admission conflicts with a sealed registration epoch."""


class StaleCoordinatorGenerationError(ValueError):
    """Raised when a join acknowledgement comes from a superseded coordinator."""


class StaleCoordinatorRolloverError(ValueError):
    """Raised when a rollover writer addresses a superseded incarnation."""


class CoordinatorRolloverConflictError(ValueError):
    """Raised when a replay tries to change a prepared rollover's destination."""


# ── timestamps ───────────────────────────────────────────────────────────────

def _iso_now() -> str:
    """Return the current UTC time as an ``YYYY-MM-DDTHH:MM:SSZ`` string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── id / name generators (frozen public surface) ─────────────────────────────

def new_session_id() -> str:
    """Return a fresh ``ws-<uuid4>`` session id.

    Returns:
        A collision-resistant id, e.g. ``ws-3f2504e0-4f89-41d3-9a0c-...``.
    """
    return f"{SESSION_ID_PREFIX}{uuid.uuid4()}"


def _sanitize_slug(slug: str) -> str:
    """Reduce ``slug`` to a tmux-safe token (no ``.``/``:``; lowercased).

    Best-effort transform: any run of characters outside ``[A-Za-z0-9_-]`` is
    collapsed to a single ``-``; returns ``"session"`` if nothing survives.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", slug).strip("-").lower()
    return cleaned or "session"


def new_tmux_name(slug: str) -> str:
    """Return a unique ``zw-<slug>-<shortid>`` tmux session name.

    Args:
        slug: Human-facing plan slug; sanitized to a tmux-safe token.

    Returns:
        A name like ``zw-session-watchdog-3f2504e0`` — the ``shortid`` suffix
        (8 hex chars) guarantees uniqueness across fanout children of one slug.
    """
    return f"{TMUX_NAME_PREFIX}{_sanitize_slug(slug)}-{uuid.uuid4().hex[:8]}"


def deterministic_tmux_name(slug: str, resource_id: str) -> str:
    """Return a stable tmux name for a durably allocated host resource.

    Args:
        slug: Human-facing allocation slug.
        resource_id: Stable allocation identity; its first 16 hex characters
            distinguish the resource without relying on process-local order.

    Returns:
        A deterministic ``zw-``-prefixed tmux session name.

    Raises:
        ValueError: if ``resource_id`` has no usable alphanumeric suffix.
    """
    suffix = re.sub(r"[^A-Za-z0-9]", "", resource_id).lower()[:16]
    if not suffix:
        raise ValueError("resource_id must contain an alphanumeric character")
    return f"{TMUX_NAME_PREFIX}{_sanitize_slug(slug)}-{suffix}"


# ── record schema factory + validator ────────────────────────────────────────

def new_session_record(
    slug: str,
    plan_dir: str,
    host: str,
    tmux_target: str,
    transcript_path: str,
    *,
    session_id: str | None = None,
    parent_id: str | None = None,
    report_capability: str | None = None,
    child_lease_timeout_s: int = DEFAULT_CHILD_LEASE_TIMEOUT_S,
    child_grace_s: int = DEFAULT_CHILD_GRACE_S,
    child_resolution_window_s: int = DEFAULT_CHILD_RESOLUTION_WINDOW_S,
    now: str | None = None,
) -> dict:
    """Build a fresh, schema-complete session record.

    Args:
        slug: Plan slug the session works on.
        plan_dir: Absolute path to the plan directory.
        host: One of ``VALID_HOSTS`` (``claude`` / ``codex`` / ``omp``).
        tmux_target: tmux target (session or pane) the session runs in.
        transcript_path: Absolute path to the session transcript file.
        session_id: Explicit id; a fresh ``ws-<uuid4>`` is minted when omitted.
        parent_id: Fanout parent session id, or ``None`` for a root session.
        report_capability: Plaintext allocation capability to hash for a child
            record. The plaintext is never persisted.
        child_lease_timeout_s: Persisted child liveness lease duration.
        child_grace_s: Persisted grace after the child lease expires.
        child_resolution_window_s: Delay before an inferred outcome may notify.
        now: ISO timestamp override (for deterministic tests); defaults to
            the current UTC time.

    Returns:
        A dict carrying every key in ``REQUIRED_FIELDS`` at its initial value,
        with ``state`` == ``INITIAL_STATE``.

    Raises:
        ValueError: if ``host`` is not in ``VALID_HOSTS`` (guards the frozen
            surface at construction time).
    """
    if host not in VALID_HOSTS:
        raise ValueError(f"unknown host {host!r}; expected one of {sorted(VALID_HOSTS)}")
    ts = now or _iso_now()
    record = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "session_id": session_id or new_session_id(),
        "slug": slug,
        "plan_dir": plan_dir,
        "host": host,
        "tmux_target": tmux_target,
        "transcript_path": transcript_path,
        "transcript_offset": 0,
        "state": INITIAL_STATE,
        "state_changed_at": ts,
        "state_generation": 0,
        "created_at": ts,
        "last_seen": ts,
        "last_context_check": None,
        "last_nudge_at": None,
        "nudge_count": 0,
        "parent_id": parent_id,
        "children": [],
    }
    if parent_id is not None:
        if min(child_lease_timeout_s, child_grace_s, child_resolution_window_s) < 0:
            raise ValueError("child supervision durations must be non-negative")
        record["supervision"] = {
            "schema_version": CHILD_SUPERVISION_SCHEMA_VERSION,
            "report_capability_sha256": hashlib.sha256(
                (report_capability or secrets.token_urlsafe(32)).encode("utf-8")
            ).hexdigest(),
            "lease_timeout_s": child_lease_timeout_s,
            "grace_s": child_grace_s,
            "resolution_window_s": child_resolution_window_s,
        }
    return record


def validate_record(record: dict) -> None:
    """Validate ``record`` against the frozen schema. Hard-fail.

    Checks every required key is present, the schema version matches, and the
    enum/typed fields hold legal values. Callers must treat a raised error as a
    hard rejection — do NOT persist an invalid record.

    Args:
        record: The session record to validate.

    Raises:
        ValueError: on a missing field, a wrong ``schema_version``, an unknown
            ``state`` or ``host``, or a mistyped ``children`` / ``nudge_count`` /
            ``transcript_offset``.
    """
    if not isinstance(record, dict):
        raise ValueError(f"record must be a dict, got {type(record).__name__}")
    missing = REQUIRED_FIELDS - record.keys()
    if missing:
        raise ValueError(f"record missing required fields: {sorted(missing)}")
    if record["schema_version"] != RECORD_SCHEMA_VERSION:
        raise ValueError(
            f"schema_version {record['schema_version']!r} != {RECORD_SCHEMA_VERSION}"
        )
    if record["state"] not in VALID_STATES:
        raise ValueError(f"unknown state {record['state']!r}")
    if record["host"] not in VALID_HOSTS:
        raise ValueError(f"unknown host {record['host']!r}")
    if not isinstance(record["children"], list):
        raise ValueError("children must be a list")
    if not isinstance(record["nudge_count"], int) or record["nudge_count"] < 0:
        raise ValueError("nudge_count must be a non-negative int")
    if not isinstance(record["transcript_offset"], int) or record["transcript_offset"] < 0:
        raise ValueError("transcript_offset must be a non-negative int")
    if not isinstance(record["state_generation"], int) or record["state_generation"] < 0:
        raise ValueError("state_generation must be a non-negative int")
    _validate_coordinator_rollover_fields(record)
    supervision = record.get("supervision")
    if supervision is not None:
        if record["parent_id"] is None or not isinstance(supervision, dict):
            raise ValueError("supervision contract is valid only for child records")
        expected = {
            "schema_version", "report_capability_sha256", "lease_timeout_s", "grace_s",
            "resolution_window_s",
        }
        if set(supervision) != expected:
            raise ValueError("child supervision contract has invalid fields")
        if supervision["schema_version"] != CHILD_SUPERVISION_SCHEMA_VERSION:
            raise ValueError("child supervision contract has invalid schema_version")
        capability_digest = supervision["report_capability_sha256"]
        if (
            not isinstance(capability_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", capability_digest)
        ):
            raise ValueError("child supervision capability digest must be sha256")
        for field in ("lease_timeout_s", "grace_s", "resolution_window_s"):
            if not isinstance(supervision[field], int) or supervision[field] < 0:
                raise ValueError(f"child supervision {field} must be non-negative")


# ── state transitions ─────────────────────────────────────────────────────────

def is_terminal(state: str) -> bool:
    """Return True if ``state`` has no outgoing transition."""
    return state in TERMINAL_STATES


def is_valid_transition(src: str, dst: str) -> bool:
    """Return True if moving ``src`` -> ``dst`` is a legal state transition.

    Self-transitions (``src == dst``) are not legal transitions and return
    False; unknown ``src`` states return False.
    """
    return dst in _TRANSITIONS.get(src, frozenset())


def transition(record: dict, new_state: str, *, now: str | None = None) -> dict:
    """Return a copy of ``record`` moved to ``new_state``, stamping the clock.

    Every accepted transition sets ``state`` / ``state_changed_at`` and
    increments the persisted ``state_generation`` fence. Hard-fail: an illegal
    transition (e.g. ``cleared`` -> ``handoff_requested``) or an unknown target
    state raises rather than silently no-op'ing.

    Args:
        record: The current session record (not mutated).
        new_state: The target state; must be in ``VALID_STATES``.
        now: ISO timestamp override (deterministic tests); defaults to now.

    Returns:
        A shallow copy with updated state, timestamp, and monotonic generation.

    Raises:
        InvalidTransitionError: if ``new_state`` is unknown or the transition
            from the record's current state is not legal.
    """
    src = record.get("state")
    if new_state not in VALID_STATES:
        raise InvalidTransitionError(f"unknown target state: {new_state!r}")
    if not is_valid_transition(src, new_state):
        raise InvalidTransitionError(f"illegal transition {src!r} -> {new_state!r}")
    updated = dict(record)
    updated["state"] = new_state
    updated["state_changed_at"] = now or _iso_now()
    updated["state_generation"] = int(record["state_generation"]) + 1
    return updated


# ── atomic writes + reads (flush primitive) ──────────────────────────────────

def _replacement_path(path: Path | str) -> Path:
    """Return the deterministic crash-recovery candidate beside ``path``."""
    path = Path(path)
    return path.with_name(f".{path.name}.next")


def atomic_write_json(path: Path | str, obj: object, *, lock: bool = True) -> None:
    """Atomically write ``obj`` as JSON to ``path``. Hard-fail.

    This is the flush primitive a SIGTERM handler calls to persist
    ``sessions.json`` (STYLE.md:P-006, INVARIANTS inv_003): writes to a
    deterministic recovery file in the same directory, ``flush`` + ``fsync``,
    then ``os.replace`` onto
    the target so a concurrent reader never sees a partial file. When
    ``lock`` is True (default), the write is serialized under a sidecar
    ``<path>.lock`` (``flock`` LOCK_EX) so concurrent writers cannot interleave.

    Args:
        path: Destination file.
        obj: Any JSON-serializable object.
        lock: Serialize on the sidecar lock (set False only when the caller
            already holds exclusive access).

    Raises:
        OSError: on any I/O failure — a broken registry path is a real problem
            that must surface, not be swallowed (STYLE.md:EH-004).
        TypeError / ValueError: if ``obj`` is not JSON-serializable.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, indent=2, sort_keys=True) + "\n"

    lock_fd: int | None = None
    try:
        if lock:
            lock_path = Path(str(path) + ".lock")
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

        next_path = _replacement_path(path)
        tmp_fd = os.open(
            str(next_path), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600
        )
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # A crash before this replace leaves one deterministic, fully-fsynced
        # recovery candidate. Registry loading validates and completes it under
        # the same sidecar lock; malformed partial candidates are discarded.
        os.replace(next_path, path)
    finally:
        if lock_fd is not None:
            # Close even if LOCK_UN raises — closing the fd drops the flock.
            try:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
            except OSError:
                pass


def read_json(path: Path | str, default: object = None) -> object:
    """Best-effort read of a JSON file; returns ``default`` on any failure.

    Named-exception-only (STYLE.md:EH-002): a missing file, an I/O error, or a
    torn/partial JSON payload all yield ``default`` rather than raising, so a
    reader racing an in-flight writer degrades gracefully.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _new_registry_document() -> dict[str, object]:
    """Return an empty, schema-complete v2 registry document."""
    document: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "registry_version": REGISTRY_VERSION,
    }
    document.update({section: {} for section in _REGISTRY_SECTIONS})
    return document


class _RegistrySessions(dict[str, dict]):
    """Session view retaining its read baseline for minimal locked persistence."""

    def __init__(self, sessions: dict[str, dict]) -> None:
        super().__init__(sessions)
        self.baseline = copy.deepcopy(sessions)


def _apply_snapshot_delta(
    fresh: dict[str, dict], snapshot: _RegistrySessions
) -> None:
    """Apply only caller-visible snapshot changes to fresh registry state."""
    baseline = snapshot.baseline
    for session_id in baseline.keys() - snapshot.keys():
        fresh.pop(session_id, None)
    for session_id, current in snapshot.items():
        original = baseline.get(session_id)
        if original is None:
            fresh[session_id] = copy.deepcopy(current)
            continue
        changed_fields = original.keys() | current.keys()
        changed_fields = {
            field for field in changed_fields
            if field not in original
            or field not in current
            or original[field] != current[field]
        }
        if not changed_fields:
            continue
        merged = dict(fresh.get(session_id, original))
        for field in changed_fields:
            if field in current:
                merged[field] = copy.deepcopy(current[field])
            else:
                merged.pop(field, None)
        fresh[session_id] = merged


def _validate_document(document: object, *, expected_version: int) -> dict[str, object]:
    """Validate one registry document version and return it narrowed to a dict.

    Args:
        document: Parsed JSON value.
        expected_version: Envelope version the caller is validating.

    Returns:
        The validated document.

    Raises:
        RegistryFormatError: if the envelope, collections, or record versions
            are malformed or mixed.
    """
    if not isinstance(document, dict):
        raise RegistryFormatError("registry document must be a JSON object")
    if expected_version == 1:
        if "registry_version" in document:
            raise RegistryFormatError("mixed v1/v2 registry envelope")
        if document.get("schema_version") != SCHEMA_VERSION:
            raise RegistryFormatError(
                f"registry schema_version must be {SCHEMA_VERSION}, got "
                f"{document.get('schema_version')!r}"
            )
        allowed = {"schema_version", "sessions"}
        if set(document) != allowed:
            raise RegistryFormatError(
                f"v1 registry has unexpected fields: {sorted(set(document) - allowed)}"
            )
        sections = ("sessions",)
    else:
        if document.get("registry_version") != expected_version:
            raise RegistryFormatError(
                f"registry_version must be {expected_version}, got "
                f"{document.get('registry_version')!r}"
            )
        if document.get("schema_version") != SCHEMA_VERSION:
            raise RegistryFormatError(
                f"schema_version must remain {SCHEMA_VERSION}, got "
                f"{document.get('schema_version')!r}"
            )
        required = {"schema_version", "registry_version", *_REGISTRY_SECTIONS}
        missing = required - document.keys()
        if missing:
            raise RegistryFormatError(f"v2 registry missing sections: {sorted(missing)}")
        unexpected = set(document) - required
        if unexpected:
            raise RegistryFormatError(
                f"v2 registry has unexpected fields: {sorted(unexpected)}"
            )
        sections = _REGISTRY_SECTIONS
    for section in sections:
        if not isinstance(document.get(section), dict):
            raise RegistryFormatError(f"registry section {section!r} must be an object")
    for session_id, record in document["sessions"].items():
        validated_record = record
        if expected_version == 1 and "state_generation" not in record:
            validated_record = {**record, "state_generation": 0}
        try:
            validate_record(validated_record)
        except ValueError as exc:
            raise RegistryFormatError(
                f"invalid session record {session_id!r}: {exc}"
            ) from exc
        if record["session_id"] != session_id:
            raise RegistryFormatError(
                f"session key {session_id!r} does not match record id "
                f"{record['session_id']!r}"
            )
    if expected_version == REGISTRY_VERSION:
        for section in _REGISTRY_SECTIONS[1:]:
            for key, value in document[section].items():
                if not isinstance(value, dict):
                    raise RegistryFormatError(
                        f"registry entry {section}.{key} must be an object"
                    )
                entry_version = value.get("registry_version", REGISTRY_VERSION)
                if entry_version != REGISTRY_VERSION:
                    raise RegistryFormatError(
                        f"mixed registry version at {section}.{key}: {entry_version!r}"
                    )
        for key, entry in document["coordinators"].items():
            _validate_coordinator_entry(key, entry)
        for key, entry in document["outcomes"].items():
            _validate_child_outcome_entry(key, entry)
        for key, entry in document["groups"].items():
            if key.startswith("group:v1:") or "schema_version" in entry:
                _validate_group_entry(key, entry)
        for key, entry in document["joins"].items():
            if key.startswith("join:v1:") or "schema_version" in entry:
                _validate_join_entry(key, entry)
        for key, entry in document["outbox"].items():
            if key.startswith("wake:v1:") or "schema_version" in entry:
                _validate_wake_outbox_entry(key, entry)
    return document


def _validate_coordinator_entry(key: str, entry: dict[str, object]) -> None:
    """Validate the durable identity and payload integrity of one root.

    Args:
        key: Versioned root idempotency key from the coordinator mapping.
        entry: Durable root registration stored under ``key``.

    Raises:
        RegistryFormatError: if required identity or payload fields are
            missing, inconsistent, or corrupt.
    """
    required = {
        "registry_version", "schema_version", "coordinator_id",
        "idempotency_key", "manifest_sha256", "manifest", "state",
    }
    missing = required - entry.keys()
    if missing:
        raise RegistryFormatError(
            f"coordinator {key!r} missing fields: {sorted(missing)}"
        )
    if not isinstance(key, str) or not key.startswith("root-v1:"):
        raise RegistryFormatError(f"invalid coordinator key {key!r}")
    if entry["idempotency_key"] != key:
        raise RegistryFormatError(
            f"coordinator key {key!r} does not match its idempotency_key"
        )
    coordinator_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if entry["coordinator_id"] != f"wc-{coordinator_digest[:32]}":
        raise RegistryFormatError(f"coordinator {key!r} has invalid durable identity")
    if entry["schema_version"] != SCHEMA_VERSION:
        raise RegistryFormatError(f"coordinator {key!r} has invalid schema_version")
    if entry["state"] != "registered":
        raise RegistryFormatError(f"coordinator {key!r} has invalid state")
    manifest = entry["manifest"]
    if not isinstance(manifest, dict):
        raise RegistryFormatError(f"coordinator {key!r} manifest must be an object")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if entry["manifest_sha256"] != manifest_digest:
        raise RegistryFormatError(f"coordinator {key!r} manifest digest mismatch")


def _validate_child_outcome_entry(key: str, entry: dict[str, object]) -> None:
    """Validate one durable child outcome and its reporter evidence."""
    required = {
        "registry_version", "schema_version", "outcome_id", "child_id",
        "generation", "state", "source", "reporter", "evidence", "effective_at",
        "resolution_deadline", "notification_claimed_at", "notification_status",
        "notification_attempts",
    }
    missing = required - entry.keys()
    if missing:
        raise RegistryFormatError(f"outcome {key!r} missing fields: {sorted(missing)}")
    if entry["outcome_id"] != key or not key.startswith("child-outcome:v1:"):
        raise RegistryFormatError(f"invalid child outcome identity {key!r}")
    if entry["registry_version"] != REGISTRY_VERSION:
        raise RegistryFormatError(f"outcome {key!r} has invalid registry_version")
    if entry["schema_version"] != CHILD_OUTCOME_SCHEMA_VERSION:
        raise RegistryFormatError(f"outcome {key!r} has invalid schema_version")
    if entry["state"] not in CHILD_OUTCOME_STATES:
        raise RegistryFormatError(f"outcome {key!r} has invalid terminal state")
    if entry["source"] not in {"explicit", "lease_reaper"}:
        raise RegistryFormatError(f"outcome {key!r} has invalid source")
    reporter = entry["reporter"]
    if not isinstance(reporter, dict) or set(reporter) != {"kind", "id"}:
        raise RegistryFormatError(f"outcome {key!r} has invalid reporter provenance")
    if reporter["kind"] not in {"allocation_capability", "watchdog"} or not reporter["id"]:
        raise RegistryFormatError(f"outcome {key!r} has invalid reporter authority")
    if not isinstance(entry["evidence"], dict) or not entry["evidence"]:
        raise RegistryFormatError(f"outcome {key!r} requires non-empty evidence")
    if child_outcome_id(str(entry["child_id"]), str(entry["generation"])) != key:
        raise RegistryFormatError(f"outcome {key!r} identity digest mismatch")
    if entry["notification_status"] not in {"pending", "delivered", "failed", "disabled"}:
        raise RegistryFormatError(f"outcome {key!r} has invalid notification status")
    if not isinstance(entry["notification_attempts"], int) or entry["notification_attempts"] < 0:
        raise RegistryFormatError(f"outcome {key!r} has invalid notification attempts")


def _validate_group_entry(key: str, entry: dict[str, object]) -> None:
    """Validate one explicit registration epoch."""
    required = {
        "registry_version", "schema_version", "group_id", "epoch",
        "coordinator_session_id", "admitted_children", "state", "created_at",
        "sealed_at", "join_id",
    }
    if required - entry.keys():
        raise RegistryFormatError(f"group {key!r} missing required fields")
    if entry["group_id"] != key or not key.startswith("group:v1:"):
        raise RegistryFormatError(f"invalid group identity {key!r}")
    if entry["schema_version"] != GROUP_SCHEMA_VERSION or entry["epoch"] != 1:
        raise RegistryFormatError(f"group {key!r} has invalid version or epoch")
    if entry["state"] not in {"open", "sealed", "join_ready", "acknowledged"}:
        raise RegistryFormatError(f"group {key!r} has invalid state")
    if not isinstance(entry["admitted_children"], list) or len(
        set(entry["admitted_children"])
    ) != len(entry["admitted_children"]):
        raise RegistryFormatError(f"group {key!r} has invalid admissions")
    if entry["state"] == "open" and entry["sealed_at"] is not None:
        raise RegistryFormatError(f"open group {key!r} cannot be sealed")
    if entry["state"] in {"join_ready", "acknowledged"} and not entry["join_id"]:
        raise RegistryFormatError(f"ready group {key!r} has no join")


def _validate_join_entry(key: str, entry: dict[str, object]) -> None:
    """Validate one stable sealed-group join."""
    required = {
        "registry_version", "schema_version", "join_id", "group_id", "epoch",
        "coordinator_session_id", "coordinator_generation", "outcomes",
        "created_at", "notification_status", "notification_attempts",
    }
    if required - entry.keys() or entry.get("join_id") != key:
        raise RegistryFormatError(f"join {key!r} is malformed")
    if entry["schema_version"] != JOIN_SCHEMA_VERSION or not key.startswith("join:v1:"):
        raise RegistryFormatError(f"join {key!r} has invalid identity")
    if not isinstance(entry["outcomes"], dict) or not entry["outcomes"]:
        raise RegistryFormatError(f"join {key!r} has no terminal outcomes")
    if set(entry["outcomes"].values()) - CHILD_OUTCOME_STATES:
        raise RegistryFormatError(f"join {key!r} has non-terminal outcomes")
    if entry["notification_status"] not in {"pending", "delivered", "failed", "disabled"}:
        raise RegistryFormatError(f"join {key!r} has invalid notification status")


def _validate_wake_outbox_entry(key: str, entry: dict[str, object]) -> None:
    """Validate one retryable coordinator-wake outbox action."""
    required = {
        "registry_version", "schema_version", "outbox_id", "join_id", "group_id",
        "coordinator_session_id", "coordinator_generation", "target", "text",
        "state", "delivery_attempts", "last_delivery_status", "created_at",
        "acknowledged_at", "notification_status", "notification_attempts",
    }
    if required - entry.keys() or entry.get("outbox_id") != key:
        raise RegistryFormatError(f"wake outbox {key!r} is malformed")
    if entry["schema_version"] != WAKE_OUTBOX_SCHEMA_VERSION or not key.startswith(
        "wake:v1:"
    ):
        raise RegistryFormatError(f"wake outbox {key!r} has invalid identity")
    if entry["state"] not in {"pending", "acknowledged"}:
        raise RegistryFormatError(f"wake outbox {key!r} has invalid state")
    if not isinstance(entry["delivery_attempts"], int) or entry["delivery_attempts"] < 0:
        raise RegistryFormatError(f"wake outbox {key!r} has invalid attempts")


def _migrate_v1_to_v2(document: dict[str, object]) -> dict[str, object]:
    """Convert a validated legacy v1 envelope into a v2 document."""
    migrated = _new_registry_document()
    migrated["sessions"] = document["sessions"]
    for record in migrated["sessions"].values():  # type: ignore[union-attr]
        record.setdefault("state_generation", 0)
    return migrated


_MIGRATIONS: dict[int, Callable[[dict[str, object]], dict[str, object]]] = {
    1: _migrate_v1_to_v2,
}


def _migrate_to_current(document: object) -> tuple[dict[str, object], bool]:
    """Validate and stepwise-migrate a supported registry document."""
    version = _document_version(document)
    current = _validate_document(document, expected_version=version)
    migrated = False
    while version < REGISTRY_VERSION:
        migrate = _MIGRATIONS.get(version)
        if migrate is None:
            raise UnsupportedRegistryVersionError(
                f"no migration from registry version {version}"
            )
        current = migrate(current)
        version += 1
        current = _validate_document(current, expected_version=version)
        migrated = True
    return current, migrated


def _read_json_strict(path: Path) -> object:
    """Read JSON from ``path`` and surface malformed authority loudly."""
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise RegistryFormatError(f"malformed registry JSON at {path}: {exc}") from exc


def _document_version(document: object) -> int:
    """Return a document version, rejecting missing, mixed, or future state."""
    if not isinstance(document, dict):
        raise RegistryFormatError("registry document must be a JSON object")
    if "schema_version" not in document:
        raise RegistryFormatError("registry is missing schema_version")
    if "registry_version" not in document:
        version = document["schema_version"]
    else:
        if document["schema_version"] != SCHEMA_VERSION:
            raise RegistryFormatError(
                "mixed record and registry schema versions: "
                f"{document['schema_version']!r}/{document['registry_version']!r}"
            )
        version = document["registry_version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RegistryFormatError(f"invalid registry version {version!r}")
    if version > REGISTRY_VERSION:
        raise UnsupportedRegistryVersionError(
            f"registry version {version} is newer than supported {REGISTRY_VERSION}"
        )
    return version


def _load_registry_document_locked(path: Path | str) -> tuple[dict[str, object], bool]:
    """Load, recover, and stepwise-migrate registry state with its lock held."""
    path = Path(path)
    next_path = _replacement_path(path)
    target_exists = path.exists()
    candidate_exists = next_path.exists()
    if not target_exists and not candidate_exists:
        return _new_registry_document(), False

    target: object | None = None
    target_error: RegistryFormatError | None = None
    if target_exists:
        try:
            target = _read_json_strict(path)
            _document_version(target)
        except UnsupportedRegistryVersionError:
            raise
        except RegistryFormatError as exc:
            target_error = exc

    if candidate_exists:
        candidate = _read_json_strict(next_path)
        candidate, candidate_migrated = _migrate_to_current(candidate)
        if candidate_migrated:
            _write_registry_document_locked(path, candidate)
        else:
            os.replace(next_path, path)
        target = candidate
        target_error = None

    if target_error is not None:
        raise target_error
    if target is None:
        return _new_registry_document(), False

    return _migrate_to_current(target)


def _write_registry_document_locked(path: Path | str, document: dict[str, object]) -> None:
    """Validate and atomically publish a v2 document with its lock held."""
    _reconcile_group_admissions(document)
    _validate_document(document, expected_version=REGISTRY_VERSION)
    atomic_write_json(path, document, lock=False)


def read_registry_document(path: Path | str) -> dict[str, object]:
    """Load the authoritative v2 registry, migrating/recovering under lock.

    Missing state yields an empty in-memory v2 document. Malformed, mixed, and
    unsupported-future state raises; legacy v1 state is converted stepwise and
    durably replaced before this function returns.

    Args:
        path: Registry path.

    Returns:
        A validated v2 registry document.

    Raises:
        RegistryFormatError: on malformed or mixed-version state.
        UnsupportedRegistryVersionError: on unsupported future state.
        OSError: on filesystem failure.
    """
    with hold_registry_lock(path):
        document, migrated = _load_registry_document_locked(path)
        if migrated:
            _write_registry_document_locked(path, document)
        return document


def write_registry(path: Path | str, sessions: dict[str, dict], *, lock: bool = True) -> None:
    """Persist sessions while preserving all other authoritative v2 sections.

    Plain dictionaries remain authoritative replacements. A session view
    returned by ``read_registry`` retains its read baseline, so this function
    applies only that view's changed records and fields onto the fresh locked
    document. Long-running lifecycle work can therefore persist its own state
    transition without erasing a child allocation admitted after its read.

    Args:
        path: Destination ``sessions.json``.
        sessions: Authoritative plain mapping, or a baseline-tracked view from
            ``read_registry`` whose changes should be merged minimally.
        lock: Acquire the sidecar lock; false only when already held.

    Raises:
        RegistryFormatError: if existing authority or a record is malformed.
        OSError: on write failure.
    """
    def _write() -> None:
        document, _migrated = _load_registry_document_locked(path)
        if isinstance(sessions, _RegistrySessions):
            _apply_snapshot_delta(document["sessions"], sessions)
        else:
            document["sessions"] = sessions
        _write_registry_document_locked(path, document)

    if lock:
        with hold_registry_lock(path):
            _write()
    else:
        _write()


@contextmanager
def hold_registry_lock(path: Path | str) -> Iterator[None]:
    """Hold the registry's sidecar lock across a read-modify-write cycle. Hard-fail.

    Serializes a caller's read -> mutate -> write sequence on ``path`` (e.g.
    ``fanout.run_fanout``) against any concurrent writer that goes through
    ``atomic_write_json``'s default ``lock=True`` (e.g. the daemon's poll loop
    persisting its own in-memory mutation via ``write_registry``) — see the
    module docstring's Concurrency section. Without this, a competing write
    landing between the caller's read and write is a lost update: the
    caller's write, sourced from an in-memory snapshot taken before the
    competing write landed, silently overwrites it (or vice versa).

    Reuses the SAME ``<path>.lock`` sidecar file ``atomic_write_json`` locks
    on (not a new lock primitive) — a caller inside this context must pass
    ``lock=False`` to ``write_registry`` / ``atomic_write_json``, since
    ``flock`` on a *different* file descriptor to the same file (even from
    the same process) blocks rather than re-entering.

    Args:
        path: The registry path (e.g. ``sessions.json``) whose ``<path>.lock``
            sidecar is acquired; ``path`` itself is never opened here.

    Yields:
        None. The lock is held for the duration of the ``with`` block.

    Raises:
        OSError: on an unexpected filesystem failure opening the lock file.
    """
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        # Best-effort unlock/close (STYLE.md:EH-005): closing the fd alone
        # drops the flock even if LOCK_UN raises.
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        except OSError:
            pass


def locked_registry_update(
    path: Path | str,
    mutate_fn: Callable[[dict[str, dict]], None],
) -> dict[str, dict]:
    """Lock, re-read FRESH, apply ``mutate_fn``, write, release. Hard-fail.

    The one safe way for a concurrent writer to mutate ``sessions.json``
    (STYLE.md:P-006, T-REV-001): take the sidecar lock, re-read the registry
    fresh UNDER that lock (the authoritative merge base), hand the fresh
    mapping to ``mutate_fn`` to apply ONLY this caller's own record changes in
    place, then persist under the still-held lock via
    ``write_registry(..., lock=False)`` and release. Because the merge base is
    the locked re-read — not a whole-file snapshot the caller took earlier —
    any record a concurrent writer persisted between this caller's own
    snapshot and this write survives instead of being clobbered (see the
    module docstring's Concurrency section for the lost-update scenario this
    closes, e.g. ``fanout.run_fanout`` children vs. a poll pass's transition).

    ``mutate_fn`` MUST be minimal — it applies only the records THIS caller
    changed (a poll cycle: the polled session's record + any transitions it
    made; a fanout: the origin's children linkage + the new child records; a
    startup reconcile: the records it marked ``orphaned``) — and must NOT
    reintroduce a stale whole-file overwrite (e.g. ``fresh.clear()`` followed
    by a stale snapshot), which would defeat the point.

    Args:
        path: The registry path (``sessions.json``).
        mutate_fn: A callable that mutates the freshly-read ``session_id`` ->
            record mapping IN PLACE, applying this caller's record changes.

    Returns:
        The merged mapping just written (the fresh re-read after ``mutate_fn``).

    Raises:
        ValueError: if a resulting record fails ``validate_record``.
        OSError: on a registry write failure (see ``atomic_write_json``).
    """
    with hold_registry_lock(path):
        document, _migrated = _load_registry_document_locked(path)
        sessions = document["sessions"]
        mutate_fn(sessions)
        _write_registry_document_locked(path, document)
        return sessions


def locked_registry_document_update(
    path: Path | str,
    mutate_fn: Callable[[dict[str, object]], None],
) -> dict[str, object]:
    """Fresh-read, minimally mutate, and atomically persist the complete v2 state.

    Args:
        path: Registry path.
        mutate_fn: In-place mutation applied to the fresh v2 document while the
            single registry sidecar lock is held.

    Returns:
        The complete document just written.

    Raises:
        RegistryFormatError: if source or resulting state is invalid.
        OSError: on filesystem failure.
    """
    with hold_registry_lock(path):
        document, _migrated = _load_registry_document_locked(path)
        mutate_fn(document)
        _write_registry_document_locked(path, document)
        return document


def root_idempotency_key(manifest_path: Path | str) -> str:
    """Return the stable v1 registration key for an opt-in root manifest.

    Args:
        manifest_path: Path of the root's normalized supervision manifest.

    Returns:
        A versioned SHA-256 key bound to the canonical manifest location.
    """
    canonical_path = str(Path(manifest_path).expanduser().resolve())
    digest = hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()
    return f"root-v1:{digest}"


def register_root_manifest(
    path: Path | str,
    *,
    idempotency_key: str,
    manifest: dict[str, object],
) -> tuple[dict[str, object], bool]:
    """Idempotently register one normalized opt-in root under lock.

    Args:
        path: Authoritative registry path.
        idempotency_key: Stable logical registration key.
        manifest: Validated normalized supervision manifest.

    Returns:
        ``(registration, replayed)``. Exact replay returns the original durable
        registration unchanged with ``replayed`` true.

    Raises:
        RootRegistrationConflictError: if the key already names a different
            payload.
        RegistryFormatError: if existing authority is malformed.
        OSError: on filesystem failure.
    """
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    manifest_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    coordinator_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    coordinator_id = f"wc-{coordinator_digest[:32]}"
    replayed = False

    def _register(document: dict[str, object]) -> None:
        nonlocal replayed
        coordinators = document["coordinators"]
        existing = coordinators.get(idempotency_key)  # type: ignore[union-attr]
        if existing is not None:
            if existing.get("manifest_sha256") != manifest_digest:
                raise RootRegistrationConflictError(
                    f"idempotency key {idempotency_key!r} is already registered "
                    "with a different manifest"
                )
            replayed = True
            return
        coordinators[idempotency_key] = {  # type: ignore[index]
            "registry_version": REGISTRY_VERSION,
            "schema_version": SCHEMA_VERSION,
            "coordinator_id": coordinator_id,
            "idempotency_key": idempotency_key,
            "manifest_sha256": manifest_digest,
            "manifest": copy.deepcopy(manifest),
            "state": "registered",
        }

    document = locked_registry_document_update(path, _register)
    registration = document["coordinators"][idempotency_key]  # type: ignore[index]
    return registration, replayed


# ── sealed registration epochs and coordinator wakes ────────────────────────

def group_id_for(coordinator_session_id: str) -> str:
    """Return the stable initial-group identity for one coordinator session.

    Args:
        coordinator_session_id: Durable parent session identity.

    Returns:
        A content-derived ``group:v1:`` identity.
    """
    digest = hashlib.sha256(coordinator_session_id.encode("utf-8")).hexdigest()
    return f"group:v1:{digest}"


def _join_id(group_id: str, epoch: int) -> str:
    digest = hashlib.sha256(f"{group_id}\0{epoch}".encode("utf-8")).hexdigest()
    return f"join:v1:{digest}"


def _wake_outbox_id(join_id: str) -> str:
    digest = hashlib.sha256(join_id.encode("utf-8")).hexdigest()
    return f"wake:v1:{digest}"


def admit_group_children(
    document: dict[str, object],
    *,
    coordinator_session_id: str,
    child_ids: list[str],
    now: str | None = None,
) -> dict[str, object]:
    """Admit children into the coordinator's open initial epoch.

    This helper mutates a document already held under the registry lock. Exact
    replay is harmless; any new admission after sealing is rejected.
    """
    groups: dict[str, dict] = document["groups"]  # type: ignore[assignment]
    group_id = group_id_for(coordinator_session_id)
    group = groups.get(group_id)
    timestamp = now or _iso_now()
    if group is None:
        group = {
            "registry_version": REGISTRY_VERSION,
            "schema_version": GROUP_SCHEMA_VERSION,
            "group_id": group_id,
            "epoch": 1,
            "coordinator_session_id": coordinator_session_id,
            "admitted_children": [],
            "state": "open",
            "created_at": timestamp,
            "sealed_at": None,
            "join_id": None,
        }
        groups[group_id] = group
    admitted = list(group["admitted_children"])
    additions = [child_id for child_id in child_ids if child_id not in admitted]
    if additions and group["state"] != "open":
        raise GroupAdmissionError(f"registration epoch is sealed: {group_id!r}")
    for child_id in additions:
        child = document["sessions"].get(child_id)  # type: ignore[union-attr]
        if child is None or child.get("parent_id") != coordinator_session_id:
            raise GroupAdmissionError(f"child is not owned by group coordinator: {child_id!r}")
        admitted.append(child_id)
    group["admitted_children"] = admitted
    return group


def _reconcile_group_admissions(document: dict[str, object]) -> None:
    """Admit every parented session before any authoritative document write."""
    children_by_parent: dict[str, list[str]] = {}
    for child_id, record in document["sessions"].items():  # type: ignore[union-attr]
        parent_id = record.get("parent_id")
        if parent_id is not None:
            children_by_parent.setdefault(str(parent_id), []).append(child_id)
    for parent_id, child_ids in children_by_parent.items():
        admit_group_children(
            document,
            coordinator_session_id=parent_id,
            child_ids=child_ids,
        )


def coordinator_generation_for(record: dict[str, object]) -> str:
    """Return the persisted monotonic generation fence for a coordinator."""
    return f"coordinator:v1:{record['session_id']}:{record['state_generation']}"


# ── generation-fenced coordinator rollover ─────────────────────────────────

def coordinator_incarnation_for(record: dict[str, object]) -> int:
    """Return the monotonic host incarnation for one stable coordinator."""
    value = record.get("coordinator_incarnation", 1)
    if not isinstance(value, int) or value < 1:
        raise RegistryFormatError("coordinator incarnation must be a positive int")
    return value


def _validate_coordinator_rollover_fields(record: dict) -> None:
    """Validate optional coordinator-rollover state persisted on a session.

    The original record schema predates coordinator rollover, so records that
    have neither field remain valid and migrate unchanged.  Once either field
    is present, however, it is durable authority state: reject malformed or
    internally inconsistent values while loading the registry, before any
    lifecycle operation can act on them.
    """
    incarnation = record.get("coordinator_incarnation", 1)
    if type(incarnation) is not int or incarnation < 1:
        raise ValueError("coordinator_incarnation must be a positive int")
    if "rollover" not in record:
        return

    rollover = record["rollover"]
    if not isinstance(rollover, dict):
        raise ValueError("rollover must be an object")
    required = {
        "rollover_id", "logical_coordinator_id", "from_generation",
        "from_incarnation", "to_incarnation", "target", "transcript_path",
        "prepared_at",
    }
    allowed = required | {"to_generation", "committed_at"}
    missing = required - rollover.keys()
    unexpected = rollover.keys() - allowed
    if missing or unexpected:
        raise ValueError("rollover has invalid fields")

    session_id = record["session_id"]
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("rollover requires a string session_id")
    string_fields = (
        "rollover_id", "logical_coordinator_id", "from_generation",
        "target", "transcript_path", "prepared_at",
    )
    if any(
        not isinstance(rollover[field], str) or not rollover[field]
        for field in string_fields
    ):
        raise ValueError("rollover has invalid string fields")
    if "to_generation" in rollover and (
        not isinstance(rollover["to_generation"], str)
        or not rollover["to_generation"]
    ):
        raise ValueError("rollover has invalid to_generation")
    if "committed_at" in rollover and (
        not isinstance(rollover["committed_at"], str)
        or not rollover["committed_at"]
    ):
        raise ValueError("rollover has invalid committed_at")
    if (
        type(rollover["from_incarnation"]) is not int
        or rollover["from_incarnation"] < 1
    ):
        raise ValueError("rollover from_incarnation must be a positive int")
    if type(rollover["to_incarnation"]) is not int:
        raise ValueError("rollover to_incarnation must be an int")
    if rollover["to_incarnation"] != rollover["from_incarnation"] + 1:
        raise ValueError("rollover incarnations must be consecutive")
    if rollover["logical_coordinator_id"] != session_id:
        raise ValueError("rollover logical coordinator identity mismatch")

    generation_prefix = f"coordinator:v1:{session_id}:"
    from_generation = rollover["from_generation"]
    if not from_generation.startswith(generation_prefix):
        raise ValueError("rollover from_generation identity mismatch")
    try:
        from_generation_number = int(from_generation[len(generation_prefix):])
    except ValueError as exc:
        raise ValueError("rollover from_generation must end in an integer") from exc
    if (
        from_generation_number < 0
        or str(from_generation_number) != from_generation[len(generation_prefix):]
    ):
        raise ValueError("rollover from_generation must be canonical")
    expected_rollover_id = "rollover:v1:" + hashlib.sha256(
        f"{session_id}\0{from_generation}\0{rollover['to_incarnation']}".encode()
    ).hexdigest()
    if rollover["rollover_id"] != expected_rollover_id:
        raise ValueError("rollover durable identity mismatch")

    expected_to_generation = (
        f"coordinator:v1:{session_id}:{from_generation_number + 1}"
    )
    if (
        "to_generation" in rollover
        and rollover["to_generation"] != expected_to_generation
    ):
        raise ValueError("rollover to_generation identity mismatch")
    committed = "committed_at" in rollover
    if committed:
        if incarnation != rollover["to_incarnation"]:
            raise ValueError("committed rollover incarnation mismatch")
        if record["state_generation"] != from_generation_number + 1:
            raise ValueError("committed rollover generation mismatch")
        if rollover.get("to_generation") != expected_to_generation:
            raise ValueError("committed rollover requires to_generation")
        # A committed intent is no longer merely a proposed destination: its
        # destination is the current coordinator authority.  Keeping these
        # fields in agreement makes a torn or manually-corrupted authority
        # document fail during load, before a consumer can act on an old host
        # target or resume an offset from a different transcript.
        if record["tmux_target"] != rollover["target"]:
            raise ValueError("committed rollover target mismatch")
        if record["transcript_path"] != rollover["transcript_path"]:
            raise ValueError("committed rollover transcript mismatch")
        if record["transcript_offset"] != 0:
            raise ValueError("committed rollover transcript offset must be zero")
    else:
        if incarnation != rollover["from_incarnation"]:
            raise ValueError("prepared rollover incarnation mismatch")
        # A prepared transfer may survive a crash while another authoritative
        # lifecycle mutation advances the record.  It is then stale and will
        # be safely discarded/rebased by prepare, rather than making otherwise
        # valid recovery state unloadable.  It may never point into the future.
        if record["state_generation"] < from_generation_number:
            raise ValueError("prepared rollover generation is from the future")


def prepare_coordinator_rollover(
    path: Path | str,
    *,
    session_id: str,
    expected_generation: str,
    target: str,
    transcript_path: str,
    now: str | None = None,
) -> tuple[dict[str, object], bool]:
    """Durably prepare a target incarnation without changing authority.

    The returned record carries a canonical ``rollover`` intent.  Callers write
    that intent atomically to ``handoff.json`` before calling
    :func:`commit_coordinator_rollover`; a crash between the two stages is
    therefore replayable without allocating a second logical coordinator.
    """
    timestamp = now or _iso_now()
    prepared: dict[str, object] | None = None
    replayed = False

    def _prepare(document: dict[str, object]) -> None:
        nonlocal prepared, replayed
        record = document["sessions"].get(session_id)  # type: ignore[union-attr]
        if record is None:
            raise ValueError(f"coordinator is absent: {session_id!r}")
        current = coordinator_generation_for(record)
        existing = record.get("rollover")
        if existing is not None:
            if not isinstance(existing, dict):
                raise StaleCoordinatorRolloverError("stale coordinator rollover generation")

            # A completed transfer remains replayable by its original caller:
            # that caller may have crashed after the authority commit but before
            # observing the result.  A *new* current generation, however, is a
            # separate transfer and must replace the retained completed intent.
            if (
                existing.get("committed_at") is not None
                and existing.get("from_generation") == expected_generation
            ):
                if existing.get("target") != target or existing.get("transcript_path") != transcript_path:
                    raise CoordinatorRolloverConflictError("rollover destination conflicts with prepared transfer")
                prepared = copy.deepcopy(existing)
                replayed = True
                return

            # An uncommitted intent only owns the exact generation it was
            # prepared from.  If another authoritative mutation advanced the
            # record, it never transferred authority and can safely be
            # discarded in favour of a fresh intent.  This recovers the crash
            # window between prepare and commit without allowing its stale ID
            # to mutate the new generation later.
            if existing.get("from_generation") == expected_generation and current == expected_generation:
                if existing.get("target") != target or existing.get("transcript_path") != transcript_path:
                    raise CoordinatorRolloverConflictError("rollover destination conflicts with prepared transfer")
                prepared = copy.deepcopy(existing)
                replayed = True
                return
            if current != expected_generation:
                raise StaleCoordinatorRolloverError("stale coordinator rollover generation")
        if current != expected_generation:
            raise StaleCoordinatorRolloverError("stale coordinator rollover generation")
        next_incarnation = coordinator_incarnation_for(record) + 1
        rollover_id = "rollover:v1:" + hashlib.sha256(
            f"{session_id}\0{expected_generation}\0{next_incarnation}".encode()
        ).hexdigest()
        prepared = {
            "rollover_id": rollover_id,
            "logical_coordinator_id": session_id,
            "from_generation": expected_generation,
            "from_incarnation": next_incarnation - 1,
            "to_incarnation": next_incarnation,
            "target": target,
            "transcript_path": transcript_path,
            "prepared_at": timestamp,
        }
        record["rollover"] = copy.deepcopy(prepared)

    locked_registry_document_update(path, _prepare)
    assert prepared is not None
    return prepared, replayed


def commit_coordinator_rollover(
    path: Path | str, *, session_id: str, rollover_id: str, now: str | None = None
) -> tuple[dict[str, object], bool]:
    """Fresh-read and atomically transfer a prepared coordinator authority.

    Existing children, groups, joins, outbox IDs, acknowledgements and action
    markers remain in place. Pending wake payloads are retargeted and fenced to
    the strictly newer incarnation; acknowledged wakes are immutable history.
    """
    timestamp = now or _iso_now()
    result: dict[str, object] | None = None
    replayed = False

    def _commit(document: dict[str, object]) -> None:
        nonlocal result, replayed
        record = document["sessions"].get(session_id)  # type: ignore[union-attr]
        if record is None:
            raise ValueError(f"coordinator is absent: {session_id!r}")
        existing = record.get("rollover")
        if not isinstance(existing, dict) or existing.get("rollover_id") != rollover_id:
            raise StaleCoordinatorRolloverError("rollover is absent or stale")
        if existing.get("committed_at") is not None:
            result = copy.deepcopy(existing)
            replayed = True
            return
        if coordinator_generation_for(record) != existing["from_generation"]:
            raise StaleCoordinatorRolloverError("coordinator changed after rollover preparation")
        record["tmux_target"] = existing["target"]
        record["transcript_path"] = existing["transcript_path"]
        record["transcript_offset"] = 0
        record["coordinator_incarnation"] = existing["to_incarnation"]
        record["state_generation"] = int(record["state_generation"]) + 1
        record["state_changed_at"] = timestamp
        record["last_seen"] = timestamp
        generation = coordinator_generation_for(record)
        for join in document["joins"].values():  # type: ignore[union-attr]
            if join.get("coordinator_session_id") == session_id and join.get("notification_status") != "delivered":
                join["coordinator_generation"] = generation
        for outbox in document["outbox"].values():  # type: ignore[union-attr]
            if outbox.get("coordinator_session_id") == session_id and outbox.get("state") == "pending":
                old_generation = str(outbox["coordinator_generation"])
                outbox["coordinator_generation"] = generation
                outbox["target"] = record["tmux_target"]
                outbox["text"] = str(outbox["text"]).replace(old_generation, generation)
        existing["committed_at"] = timestamp
        existing["to_generation"] = generation
        result = copy.deepcopy(existing)

    locked_registry_document_update(path, _commit)
    assert result is not None
    return result, replayed


def publish_and_commit_coordinator_rollover(
    path: Path | str,
    *,
    session_id: str,
    expected_generation: str,
    target: str,
    transcript_path: str,
    publish_handoff: Callable[[dict[str, object]], None],
    now: str | None = None,
) -> tuple[dict[str, object], bool]:
    """Publish and commit one rollover while retaining the registry fence.

    ``handoff.json`` is deliberately published after the prepared intent is
    durable but before authority changes, preserving the crash-replay window.
    Keeping the registry lock across all three stages prevents a superseded
    writer from publishing an old intent after a newer generation has won.
    """
    timestamp = now or _iso_now()
    with hold_registry_lock(path):
        document, _migrated = _load_registry_document_locked(path)
        record = document["sessions"].get(session_id)  # type: ignore[union-attr]
        if record is None:
            raise ValueError(f"coordinator is absent: {session_id!r}")
        current = coordinator_generation_for(record)
        existing = record.get("rollover")
        replayed = False
        if existing is not None:
            if not isinstance(existing, dict):
                raise StaleCoordinatorRolloverError("stale coordinator rollover generation")
            if (
                existing.get("committed_at") is not None
                and existing.get("from_generation") == expected_generation
            ):
                if existing.get("target") != target or existing.get("transcript_path") != transcript_path:
                    raise CoordinatorRolloverConflictError("rollover destination conflicts with prepared transfer")
                prepared = copy.deepcopy(existing)
                replayed = True
            elif existing.get("from_generation") == expected_generation and current == expected_generation:
                if existing.get("target") != target or existing.get("transcript_path") != transcript_path:
                    raise CoordinatorRolloverConflictError("rollover destination conflicts with prepared transfer")
                prepared = copy.deepcopy(existing)
                replayed = True
            else:
                if current != expected_generation:
                    raise StaleCoordinatorRolloverError("stale coordinator rollover generation")
                existing = None
        if existing is None:
            if current != expected_generation:
                raise StaleCoordinatorRolloverError("stale coordinator rollover generation")
            next_incarnation = coordinator_incarnation_for(record) + 1
            prepared = {
                "rollover_id": "rollover:v1:" + hashlib.sha256(
                    f"{session_id}\0{expected_generation}\0{next_incarnation}".encode()
                ).hexdigest(),
                "logical_coordinator_id": session_id,
                "from_generation": expected_generation,
                "from_incarnation": next_incarnation - 1,
                "to_incarnation": next_incarnation,
                "target": target,
                "transcript_path": transcript_path,
                "prepared_at": timestamp,
            }
            record["rollover"] = copy.deepcopy(prepared)
            # A crash after this write leaves a replayable prepared intent.
            _write_registry_document_locked(path, document)

        # The handoff is published before the authority mutation, so persist
        # the exact fenced generation it will commit as part of that intent.
        # Older prepared intents (written before this field existed) gain it
        # on their first safe replay.
        if prepared.get("committed_at") is None and "to_generation" not in prepared:
            prepared["to_generation"] = (
                f"coordinator:v1:{session_id}:{int(record['state_generation']) + 1}"
            )
            record["rollover"] = copy.deepcopy(prepared)
            _write_registry_document_locked(path, document)

        publish_handoff(prepared)
        if replayed and prepared.get("committed_at") is not None:
            return prepared, True

        # Re-read is unnecessary: the registry lock remains held from prepare
        # through publication, so this prepared intent cannot be superseded.
        record["tmux_target"] = prepared["target"]
        record["transcript_path"] = prepared["transcript_path"]
        record["transcript_offset"] = 0
        record["coordinator_incarnation"] = prepared["to_incarnation"]
        record["state_generation"] = int(record["state_generation"]) + 1
        record["state_changed_at"] = timestamp
        record["last_seen"] = timestamp
        generation = coordinator_generation_for(record)
        for join in document["joins"].values():  # type: ignore[union-attr]
            if join.get("coordinator_session_id") == session_id and join.get("notification_status") != "delivered":
                join["coordinator_generation"] = generation
        for outbox in document["outbox"].values():  # type: ignore[union-attr]
            if outbox.get("coordinator_session_id") == session_id and outbox.get("state") == "pending":
                old_generation = str(outbox["coordinator_generation"])
                outbox["coordinator_generation"] = generation
                outbox["target"] = record["tmux_target"]
                outbox["text"] = str(outbox["text"]).replace(old_generation, generation)
        current_intent = record["rollover"]
        assert isinstance(current_intent, dict)
        current_intent["committed_at"] = timestamp
        current_intent["to_generation"] = generation
        result = copy.deepcopy(current_intent)
        _write_registry_document_locked(path, document)
        return result, False


def _materialize_ready_join(
    document: dict[str, object], group: dict[str, object], *, now: str
) -> dict[str, object] | None:
    """Create one stable join and wake outbox while the registry lock is held."""
    if group["state"] == "open":
        return None
    existing_id = group.get("join_id")
    if existing_id:
        return document["joins"][existing_id]  # type: ignore[index]
    child_ids = list(group["admitted_children"])
    if not child_ids:
        return None
    sessions: dict[str, dict] = document["sessions"]  # type: ignore[assignment]
    outcomes: dict[str, dict] = document["outcomes"]  # type: ignore[assignment]
    child_states: dict[str, str] = {}
    for child_id in child_ids:
        child = sessions.get(child_id)
        if child is None or not is_terminal(str(child["state"])):
            return None
        outcome_id = child_outcome_id(child_id, child_generation(child))
        outcome = outcomes.get(outcome_id)
        if outcome is None:
            return None
        if outcome["source"] == "lease_reaper" and now < str(
            outcome["resolution_deadline"]
        ):
            return None
        child_states[child_id] = str(outcome["state"])
    coordinator_id = str(group["coordinator_session_id"])
    coordinator = sessions.get(coordinator_id)
    if coordinator is None or coordinator["state"] != "awaiting_children":
        return None
    generation = coordinator_generation_for(coordinator)
    join_id = _join_id(str(group["group_id"]), int(group["epoch"]))
    outbox_id = _wake_outbox_id(join_id)
    text = (
        f"fanout '{coordinator['slug']}' children all terminal (automated watchdog):\n"
        f"watchdog_ack outbox_id={outbox_id} coordinator_generation={generation}\n"
        + "\n".join(f"- {child_id}: {child_states[child_id]}" for child_id in child_ids)
    )
    join = {
        "registry_version": REGISTRY_VERSION,
        "schema_version": JOIN_SCHEMA_VERSION,
        "join_id": join_id,
        "group_id": group["group_id"],
        "epoch": group["epoch"],
        "coordinator_session_id": coordinator_id,
        "coordinator_generation": generation,
        "outcomes": child_states,
        "created_at": now,
        "notification_status": "pending",
        "notification_attempts": 0,
    }
    outbox = {
        "registry_version": REGISTRY_VERSION,
        "schema_version": WAKE_OUTBOX_SCHEMA_VERSION,
        "outbox_id": outbox_id,
        "join_id": join_id,
        "group_id": group["group_id"],
        "coordinator_session_id": coordinator_id,
        "coordinator_generation": generation,
        "target": coordinator["tmux_target"],
        "text": text,
        "state": "pending",
        "delivery_attempts": 0,
        "last_delivery_status": None,
        "created_at": now,
        "acknowledged_at": None,
        "notification_status": "pending",
        "notification_attempts": 0,
    }
    document["joins"][join_id] = join  # type: ignore[index]
    document["outbox"][outbox_id] = outbox  # type: ignore[index]
    group["state"] = "join_ready"
    group["join_id"] = join_id
    return join


def materialize_ready_joins(
    path: Path | str, *, now: str | None = None
) -> list[dict[str, object]]:
    """Atomically materialize every newly ready sealed-group join.

    Args:
        path: Authoritative registry path.
        now: Optional deterministic creation timestamp.

    Returns:
        Newly created joins; stable existing joins are omitted.
    """
    timestamp = now or _iso_now()
    created: list[dict[str, object]] = []

    def _materialize(document: dict[str, object]) -> None:
        for group in document["groups"].values():  # type: ignore[union-attr]
            before = group.get("join_id")
            join = _materialize_ready_join(document, group, now=timestamp)
            if join is not None and before is None:
                created.append(copy.deepcopy(join))

    locked_registry_document_update(path, _materialize)
    return created


def seal_group(
    path: Path | str, group_id: str, *, epoch: int = 1, now: str | None = None
) -> tuple[dict[str, object], bool]:
    """Explicitly seal one registration epoch and evaluate join readiness.

    Args:
        path: Authoritative registry path.
        group_id: Stable group identity.
        epoch: Expected registration epoch.
        now: Optional deterministic seal timestamp.

    Returns:
        The durable group and whether the seal was an exact replay.

    Raises:
        GroupAdmissionError: If the group is absent or the epoch is stale.
    """
    timestamp = now or _iso_now()
    replayed = False

    def _seal(document: dict[str, object]) -> None:
        nonlocal replayed
        group = document["groups"].get(group_id)  # type: ignore[union-attr]
        if group is None:
            raise GroupAdmissionError(f"unknown group: {group_id!r}")
        if int(group["epoch"]) != epoch:
            raise GroupAdmissionError(f"stale group epoch for {group_id!r}")
        if group["state"] != "open":
            replayed = True
        else:
            group["state"] = "sealed"
            group["sealed_at"] = timestamp
        _materialize_ready_join(document, group, now=timestamp)

    document = locked_registry_document_update(path, _seal)
    return document["groups"][group_id], replayed  # type: ignore[index]


def record_wake_delivery(
    path: Path | str, outbox_id: str, *, status: str
) -> dict[str, object]:
    """Record one at-least-once coordinator wake delivery attempt.

    Args:
        path: Authoritative registry path.
        outbox_id: Stable wake identity.
        status: Observable host-dispatch result.

    Returns:
        The updated outbox record.
    """
    if status not in {"completed", "failed", "paused", "escalated"}:
        raise ValueError(f"invalid wake delivery status: {status!r}")

    def _record(document: dict[str, object]) -> None:
        outbox = document["outbox"].get(outbox_id)  # type: ignore[union-attr]
        if outbox is None:
            raise ValueError(f"unknown wake outbox: {outbox_id!r}")
        if outbox["state"] == "pending":
            outbox["delivery_attempts"] = int(outbox["delivery_attempts"]) + 1
            outbox["last_delivery_status"] = status

    document = locked_registry_document_update(path, _record)
    return document["outbox"][outbox_id]  # type: ignore[index]


def claim_join_notification(
    path: Path | str, section: str, record_id: str
) -> dict[str, object] | None:
    """Claim a join or coordinator-wake notification delivery attempt.

    Args:
        path: Authoritative registry path.
        section: ``joins`` or ``outbox``.
        record_id: Stable record identity.

    Returns:
        A claimed record snapshot, or None when delivery is already settled.
    """
    if section not in {"joins", "outbox"}:
        raise ValueError(f"unsupported notification section: {section!r}")
    claimed: dict[str, object] | None = None

    def _claim(document: dict[str, object]) -> None:
        nonlocal claimed
        record = document[section].get(record_id)  # type: ignore[union-attr]
        if record is None:
            raise ValueError(f"unknown notification record: {record_id!r}")
        status = record["notification_status"]
        if status == "delivered" or (
            section == "joins" and int(record["notification_attempts"]) > 0
        ):
            return
        record["notification_status"] = "pending"
        record["notification_attempts"] = int(record["notification_attempts"]) + 1
        claimed = copy.deepcopy(record)

    locked_registry_document_update(path, _claim)
    return claimed


def finish_join_notification(
    path: Path | str,
    section: str,
    record_id: str,
    *,
    status: str,
    attempt: int,
) -> None:
    """Persist a fail-open join or coordinator-wake notification result.

    Args:
        path: Authoritative registry path.
        section: ``joins`` or ``outbox``.
        record_id: Stable record identity.
        status: Fail-open transport result.
        attempt: Claimed attempt ordinal.
    """
    if status not in {"delivered", "failed", "disabled"}:
        raise ValueError(f"invalid notification status: {status!r}")

    def _finish(document: dict[str, object]) -> None:
        record = document[section].get(record_id)  # type: ignore[union-attr]
        if record is None:
            raise ValueError(f"unknown notification record: {record_id!r}")
        if record["notification_status"] == "delivered":
            return
        if int(record["notification_attempts"]) == attempt or status == "delivered":
            record["notification_status"] = status

    locked_registry_document_update(path, _finish)


def acknowledge_join_wake(
    path: Path | str,
    outbox_id: str,
    *,
    coordinator_generation: str,
    now: str | None = None,
) -> tuple[dict[str, object], bool]:
    """Generation-fence and deduplicate logical coordinator join handling.

    Args:
        path: Authoritative registry path.
        outbox_id: Stable wake identity.
        coordinator_generation: Generation handling the logical join.
        now: Optional deterministic acknowledgement timestamp.

    Returns:
        The acknowledged outbox and whether this was an exact replay.

    Raises:
        StaleCoordinatorGenerationError: If coordinator authority is stale.
    """
    timestamp = now or _iso_now()
    replayed = False

    def _ack(document: dict[str, object]) -> None:
        nonlocal replayed
        outbox = document["outbox"].get(outbox_id)  # type: ignore[union-attr]
        if outbox is None:
            raise ValueError(f"unknown wake outbox: {outbox_id!r}")
        if outbox["coordinator_generation"] != coordinator_generation:
            raise StaleCoordinatorGenerationError(
                f"stale coordinator generation for wake {outbox_id!r}"
            )
        if outbox["state"] == "acknowledged":
            replayed = True
            return
        coordinator = document["sessions"].get(  # type: ignore[union-attr]
            outbox["coordinator_session_id"]
        )
        if coordinator is None or coordinator_generation_for(
            coordinator
        ) != coordinator_generation:
            raise StaleCoordinatorGenerationError(
                f"stale coordinator generation for wake {outbox_id!r}"
            )
        outbox["state"] = "acknowledged"
        outbox["acknowledged_at"] = timestamp
        join = document["joins"][outbox["join_id"]]  # type: ignore[index]
        group = document["groups"][outbox["group_id"]]  # type: ignore[index]
        join["acknowledged_at"] = timestamp
        group["state"] = "acknowledged"

    document = locked_registry_document_update(path, _ack)
    return document["outbox"][outbox_id], replayed  # type: ignore[index]


# ── child terminal outcomes and leases ──────────────────────────────────────

def child_generation(record: dict[str, object]) -> str:
    """Return the stable generation fence for one admitted child record."""
    generation = record.get("created_at")
    if not isinstance(generation, str) or not generation:
        raise ChildOutcomeError("child record has no valid generation")
    return generation


def child_outcome_id(child_id: str, generation: str) -> str:
    """Return the stable outcome identity shared by explicit and reaped results."""
    digest = hashlib.sha256(f"{child_id}\0{generation}".encode("utf-8")).hexdigest()
    return f"child-outcome:v1:{digest}"


def _child_for_outcome(
    document: dict[str, object], child_id: str, generation: str
) -> dict[str, object]:
    """Resolve one admitted child and enforce its generation fence."""
    child = document["sessions"].get(child_id)  # type: ignore[union-attr]
    if child is None or child.get("parent_id") is None:
        raise UnauthorizedChildReporterError(
            f"session {child_id!r} is not an admitted child"
        )
    if child_generation(child) != generation:
        raise StaleChildGenerationError(
            f"stale generation for child {child_id!r}"
        )
    return child


def child_supervision_contract(record: dict[str, object]) -> dict[str, object]:
    """Return the persisted authorization and lease policy for one child."""
    contract = record.get("supervision")
    if not isinstance(contract, dict):
        raise ChildOutcomeError("child has no supervision contract")
    return contract


def report_child_outcome(
    path: Path | str,
    *,
    child_id: str,
    generation: str,
    reporter_id: str,
    report_capability: str,
    state: str,
    evidence: dict[str, object],
    now: str | None = None,
) -> tuple[dict[str, object], bool]:
    """Authorize and durably commit one explicit child terminal report.

    The allocation-bound capability authorizes the child reporter in v1.
    Exact replay is idempotent; a different explicit payload for the same
    generation is a hard conflict. Explicit evidence can replace provisional
    reaping until the reaper outcome is durably claimed for notification.

    Args:
        path: Authoritative registry path.
        child_id: Admitted child session identity.
        generation: Stable child generation returned by ``child_generation``.
        reporter_id: Reporting session identity; must equal ``child_id``.
        report_capability: Secret privately provisioned to this child allocation.
        state: One of ``CHILD_OUTCOME_STATES``.
        evidence: Non-empty structured terminal evidence.
        now: Server receipt timestamp override for tests.

    Returns:
        ``(outcome, replayed)`` after the transition is durable.

    Raises:
        UnauthorizedChildReporterError: if the reporter or child is unauthorized.
        StaleChildGenerationError: if the generation is not current.
        ChildOutcomeConflictError: on a conflicting explicit report.
        ChildOutcomeError: on malformed outcome fields.
    """
    if state not in CHILD_OUTCOME_STATES:
        raise ChildOutcomeError(f"invalid child terminal state {state!r}")
    if not isinstance(evidence, dict) or not evidence:
        raise ChildOutcomeError("child terminal evidence must be a non-empty object")
    effective_at = now or _iso_now()
    outcome_id = child_outcome_id(child_id, generation)
    replayed = False

    def _report(document: dict[str, object]) -> None:
        nonlocal replayed
        child = _child_for_outcome(document, child_id, generation)
        contract = child_supervision_contract(child)
        supplied_digest = hashlib.sha256(report_capability.encode("utf-8")).hexdigest()
        if reporter_id != child_id or not secrets.compare_digest(
            supplied_digest, str(contract["report_capability_sha256"])
        ):
            raise UnauthorizedChildReporterError(
                f"reporter {reporter_id!r} is not authorized for child {child_id!r}"
            )
        outcomes = document["outcomes"]
        existing = outcomes.get(outcome_id)  # type: ignore[union-attr]
        candidate = {
            "registry_version": REGISTRY_VERSION,
            "schema_version": CHILD_OUTCOME_SCHEMA_VERSION,
            "outcome_id": outcome_id,
            "child_id": child_id,
            "generation": generation,
            "state": state,
            "source": "explicit",
            "reporter": {"kind": "allocation_capability", "id": reporter_id},
            "evidence": copy.deepcopy(evidence),
            "effective_at": effective_at,
            "resolution_deadline": effective_at,
            "notification_claimed_at": None,
            "notification_status": "pending",
            "notification_attempts": 0,
        }
        if existing is not None and existing.get("source") == "explicit":
            comparable_fields = {
                "child_id", "generation", "state", "source", "reporter", "evidence",
            }
            if any(existing.get(field) != candidate[field] for field in comparable_fields):
                raise ChildOutcomeConflictError(
                    f"conflicting terminal report for child {child_id!r}"
                )
            replayed = True
            return
        if existing is None and is_terminal(str(child["state"])):
            raise ChildOutcomeConflictError(
                f"child {child_id!r} is already terminal without this outcome"
            )
        if existing is None:
            document["sessions"][child_id] = transition(  # type: ignore[index]
                child, state, now=effective_at
            )
        else:
            if effective_at >= str(existing["resolution_deadline"]):
                raise ChildOutcomeConflictError(
                    f"inferred terminal outcome for child {child_id!r} won at deadline"
                )
            # Explicit authorized evidence outranks disappearance inference.
            resolved = dict(child)
            resolved["state"] = state
            resolved["state_changed_at"] = effective_at
            document["sessions"][child_id] = resolved  # type: ignore[index]
        outcomes[outcome_id] = candidate  # type: ignore[index]
        for group in document["groups"].values():  # type: ignore[union-attr]
            if child_id in group["admitted_children"]:
                _materialize_ready_join(document, group, now=effective_at)

    document = locked_registry_document_update(path, _report)
    return document["outcomes"][outcome_id], replayed  # type: ignore[index]


def reap_child_lease(
    path: Path | str,
    *,
    child_id: str,
    generation: str,
    reachable: bool | None,
    observed_at: str,
) -> dict[str, object] | None:
    """Boundedly infer a failed/orphaned child after lease and grace expiry.

    ``reachable=False`` is definite disappearance and resolves to ``failed``;
    ``None`` is an unreachable/ambiguous host check and resolves to
    ``orphaned``. A live child or an unexpired deadline is a no-op. An explicit
    report wins during the persisted resolution window. Once notification is
    claimed after that deadline, the inferred winner is final.
    """
    if reachable is True:
        return None
    outcome_id = child_outcome_id(child_id, generation)
    committed = False

    def _reap(document: dict[str, object]) -> None:
        nonlocal committed
        child = _child_for_outcome(document, child_id, generation)
        contract = child_supervision_contract(child)
        lease_timeout_s = int(contract["lease_timeout_s"])
        grace_s = int(contract["grace_s"])
        resolution_window_s = int(contract["resolution_window_s"])
        existing = document["outcomes"].get(outcome_id)  # type: ignore[union-attr]
        if existing is not None or is_terminal(str(child["state"])):
            return
        last_seen = datetime.strptime(
            str(child["last_seen"]), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        observed = datetime.strptime(
            observed_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        if (observed - last_seen).total_seconds() <= lease_timeout_s + grace_s:
            return
        state = "failed" if reachable is False else "orphaned"
        evidence = {
            "reason": "target_missing" if reachable is False else "target_unreachable",
            "tmux_target": child["tmux_target"],
            "last_seen": child["last_seen"],
            "lease_timeout_s": lease_timeout_s,
            "grace_s": grace_s,
        }
        outcome = {
            "registry_version": REGISTRY_VERSION,
            "schema_version": CHILD_OUTCOME_SCHEMA_VERSION,
            "outcome_id": outcome_id,
            "child_id": child_id,
            "generation": generation,
            "state": state,
            "source": "lease_reaper",
            "reporter": {"kind": "watchdog", "id": "lease-reaper"},
            "evidence": evidence,
            "effective_at": observed_at,
            "resolution_deadline": (
                observed + timedelta(seconds=resolution_window_s)
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "notification_claimed_at": None,
            "notification_status": "pending",
            "notification_attempts": 0,
        }
        document["sessions"][child_id] = transition(  # type: ignore[index]
            child, state, now=observed_at
        )
        document["outcomes"][outcome_id] = outcome  # type: ignore[index]
        committed = True

    document = locked_registry_document_update(path, _reap)
    if not committed:
        return None
    return document["outcomes"][outcome_id]  # type: ignore[index]


def claim_child_outcome_notification(
    path: Path | str, outcome_id: str, *, now: str | None = None
) -> dict[str, object] | None:
    """Claim a retryable outcome delivery after deterministic winner resolution.

    Explicit outcomes enter ``pending`` in the same commit as terminal state.
    Reclaiming ``pending`` is intentional: it recovers a crash after claim but
    before a delivery result was durably recorded.
    """
    claimed: dict[str, object] | None = None
    claimed_at = now or _iso_now()

    def _claim(document: dict[str, object]) -> None:
        nonlocal claimed
        outcome = document["outcomes"].get(outcome_id)  # type: ignore[union-attr]
        if (
            outcome is None
            or outcome.get("notification_status") == "delivered"
        ):
            return
        if (
            outcome.get("source") == "lease_reaper"
            and claimed_at < str(outcome["resolution_deadline"])
        ):
            return
        outcome["notification_claimed_at"] = claimed_at
        outcome["notification_status"] = "pending"
        outcome["notification_attempts"] = int(outcome["notification_attempts"]) + 1
        claimed = copy.deepcopy(outcome)

    locked_registry_document_update(path, _claim)
    return claimed


def finish_child_outcome_notification(
    path: Path | str,
    outcome_id: str,
    *,
    status: str,
    attempt: int,
) -> None:
    """Persist a fail-open child-outcome delivery result for later replay.

    Args:
        path: Authoritative registry path.
        outcome_id: Stable durable outcome identity.
        status: One of ``delivered``, ``failed``, or ``disabled``.
        attempt: Claim attempt number returned with the claimed outcome.

    Raises:
        ValueError: If no matching pending claim exists or status is invalid.
        OSError: If the durable update cannot be persisted.
    """
    if status not in {"delivered", "failed", "disabled"}:
        raise ValueError(f"invalid child outcome notification status: {status!r}")

    def _finish(document: dict[str, object]) -> None:
        outcome = document["outcomes"].get(outcome_id)  # type: ignore[union-attr]
        if outcome is None:
            raise ValueError(f"child outcome notification is not pending: {outcome_id!r}")
        if outcome.get("notification_status") == "delivered":
            return
        if int(outcome["notification_attempts"]) != attempt:
            # A stale successful send still satisfies delivery; stale failures
            # cannot overwrite the result of a newer retry attempt.
            if status == "delivered":
                outcome["notification_status"] = status
            return
        outcome["notification_status"] = status

    locked_registry_document_update(path, _finish)


def read_registry(path: Path | str) -> dict[str, dict]:
    """Read the legacy session view from authoritative v2 state.

    Returns:
        The ``sessions`` mapping, or an empty dict if the file is absent.

    Raises:
        RegistryFormatError: on malformed, mixed, or unsupported state.
    """
    return _RegistrySessions(read_registry_document(path)["sessions"])


# ── daemon single-instance pidfile lock ──────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` currently exists (``kill -0``).

    Best-effort: a ``PermissionError`` means the process exists but is owned by
    another user (still alive); any other OS error is treated as dead.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_pid_fd(fd: int) -> int:
    """Best-effort read of an integer pid from the start of ``fd``; 0 on failure."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 64).decode("utf-8", errors="replace").strip()
        return int(raw) if raw else 0
    except (OSError, ValueError):
        return 0


def read_lock_pid(lock_path: Path | str) -> int:
    """Best-effort read of the pid recorded in ``lock_path``; 0 if absent/invalid."""
    try:
        raw = Path(lock_path).read_text(encoding="utf-8").strip()
        return int(raw) if raw else 0
    except (FileNotFoundError, OSError, ValueError):
        return 0


def daemon_lock_status(lock_path: Path | str) -> tuple[bool, int | None]:
    """Return whether the daemon lock is held and its recorded pid.

    Args:
        lock_path: Daemon pidfile+lock path.

    Returns:
        ``(running, pid)``. The flock is authoritative; stale pidfile content
        therefore reports ``(False, None)``.

    Raises:
        OSError: on an unexpected lock-file operation failure.
    """
    lock_path = Path(lock_path)
    if not lock_path.exists():
        return False, None
    fd = os.open(str(lock_path), os.O_RDWR)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pid = _read_pid_fd(fd)
            return True, pid or None
        return False, None
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def acquire_single_instance_lock(lock_path: Path | str) -> int:
    """Acquire the daemon single-instance lock. Hard-fail.

    Takes ``flock`` LOCK_EX|LOCK_NB on ``lock_path`` and records the current
    pid. A stale lock left by a crashed daemon (``flock`` already released, but a
    now-dead pid still recorded in the file) is cleaned automatically: the
    acquisition succeeds and the dead pid is overwritten. A lock held by a live
    process is rejected.

    Args:
        lock_path: Path to the single-instance pidfile+lock.

    Returns:
        An open fd whose ``flock`` must be held for the daemon's lifetime;
        release it via ``release_single_instance_lock``.

    Raises:
        DaemonAlreadyRunningError: if a live daemon (its recorded pid passes
            ``kill -0``) already holds the lock.
        OSError: on an unexpected filesystem failure opening the lock.
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # A live process holds the flock; report its recorded pid.
        existing = _read_pid_fd(fd)
        _safe_close(fd)
        raise DaemonAlreadyRunningError(
            f"watchdog daemon already running (pid {existing or 'unknown'}): {lock_path}"
        ) from None
    except OSError:
        _safe_close(fd)
        raise

    # We hold the lock. If the file named a now-dead pid it was a stale lock —
    # overwriting the pid below IS the automatic cleanup.
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, (str(os.getpid()) + "\n").encode("utf-8"))
        os.fsync(fd)
    except OSError:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        _safe_close(fd)
        raise
    return fd


def release_single_instance_lock(fd: int, lock_path: Path | str | None = None) -> None:
    """Release the daemon single-instance lock. Best-effort.

    Drops the ``flock`` and closes ``fd``. The pathname deliberately remains
    stable: unlinking after unlock lets a concurrent opener acquire a flock on
    the old inode while a replacement daemon locks a newly created inode at the
    same path.
    """
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except OSError:
        pass


def _safe_close(fd: int) -> None:
    """Close ``fd``, swallowing ``OSError`` (e.g. an already-closed fd)."""
    try:
        os.close(fd)
    except OSError:
        pass


# ── signals.jsonl append (internal daemon event log) ─────────────────────────

def get_config_int(key: str) -> int:
    """Resolve a watchdog config int via ``scripts/config.py``. Hard-fail.

    Shells out to the sibling config resolver (STYLE.md:P-004) rather than
    reimplementing the config precedence chain, and never hardcodes a default
    (T002): config is authoritative.

    Args:
        key: A dotted config key, e.g. ``watchdog.signals_max_mb``.

    Returns:
        The resolved integer value.

    Raises:
        RuntimeError: if the resolver fails, times out, or returns a non-int.
    """
    config_py = _REPO_ROOT / "scripts" / "config.py"
    try:
        result = subprocess.run(
            [sys.executable, str(config_py), "get", key],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"config.py get {key} failed: {exc}") from exc
    raw = result.stdout.strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"config value for {key} is not an int: {raw!r}") from exc


def _rotate_if_needed(path: Path, max_bytes: int) -> None:
    """Rotate ``path`` to ``<path>.1`` when it reaches ``max_bytes``. Best-effort.

    Single-generation rotation: the previous ``.1`` is overwritten. A stat or
    replace failure is swallowed so a rotation hiccup never blocks the append.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size >= max_bytes:
        try:
            os.replace(path, Path(str(path) + ".1"))
        except OSError:
            pass


def append_signal(
    signals_path: Path | str,
    kind: str,
    payload: dict,
    *,
    max_mb: int | None = None,
    now: str | None = None,
) -> None:
    """Append one JSON-line event to ``signals.jsonl``. Best-effort.

    ``signals.jsonl`` is the internal daemon event log (destination for events
    such as ``judge_degraded``). Before appending, the file is rotated when it
    reaches ``max_mb`` (STYLE.md — size-capped per ``watchdog.signals_max_mb``).
    Losing a single event must never crash the daemon, so filesystem errors are
    swallowed (documented no-hard-fail stance, STYLE.md:EH-001/EH-004); the
    record is written as ``{ts, kind, payload}`` — fields enumerated explicitly,
    the caller's dict nested under ``payload`` rather than spread
    (STYLE.md:P-003).

    Args:
        signals_path: Path to ``signals.jsonl``.
        kind: Event kind (``snake_case``), e.g. ``judge_degraded``.
        payload: Arbitrary JSON-serializable event data, nested under ``payload``.
        max_mb: Rotation ceiling in MiB; when ``None`` it is resolved from
            ``watchdog.signals_max_mb`` via ``get_config_int``.
        now: ISO timestamp override (deterministic tests); defaults to now.
    """
    signals_path = Path(signals_path)
    try:
        signals_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    if max_mb is None:
        # Resolve the cap from config once (hard-fail if unresolvable — a missing
        # knob is a real misconfiguration, not a rotation hiccup).
        max_mb = get_config_int("watchdog.signals_max_mb")
    _rotate_if_needed(signals_path, max_mb * 1024 * 1024)

    record = {"ts": now or _iso_now(), "kind": kind, "payload": payload}
    line = json.dumps(record, sort_keys=True) + "\n"
    try:
        with open(signals_path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        return
