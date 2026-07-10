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
one. Readers (``read_json`` / ``read_registry``) take no lock and are best-effort.

Config (STYLE.md:P-004): ``get_config_int`` shells out to ``scripts/config.py``
rather than reimplementing the config precedence chain; nothing threshold-shaped
is hardcoded (T002).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── schema constants (frozen public surface) ─────────────────────────────────

SCHEMA_VERSION = 1
"""sessions.json record schema version. Bump only on an incompatible change."""

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
    "registered",
    "running",
    "needs_input",
    "stuck",
    "awaiting_children",
    "orphaned",
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

TERMINAL_STATES = frozenset({"done", "failed", "orphaned"})
"""States with no outgoing transition. ``orphaned`` is never auto-adopted."""

# Adjacency list of legal transitions. A state absent as a key (or an empty set)
# is terminal. Self-transitions are intentionally NOT listed: re-stamping the
# same state is not a transition and would falsely bump state_changed_at.
# ``cleared -> handoff_requested`` is deliberately absent (a cleared session
# resumes; it does not re-request a handoff mid-flight).
_TRANSITIONS: dict[str, frozenset[str]] = {
    "registered": frozenset({
        "running", "needs_input", "awaiting_children",
        "handoff_requested", "orphaned", "failed", "done",
    }),
    "running": frozenset({
        "needs_input", "stuck", "awaiting_children",
        "handoff_requested", "orphaned", "failed", "done",
    }),
    "needs_input": frozenset({"running", "orphaned", "failed", "done"}),
    "stuck": frozenset({
        "running", "needs_input", "handoff_requested",
        "orphaned", "failed", "done",
    }),
    "awaiting_children": frozenset({"running", "orphaned", "failed", "done"}),
    # Handoff choreography is a linear pipeline; each step may still be orphaned
    # or fail out of band, but cannot skip forward or loop back.
    "handoff_requested": frozenset({"handoff_written", "orphaned", "failed"}),
    "handoff_written": frozenset({"cleared", "orphaned", "failed"}),
    "cleared": frozenset({"resumed", "orphaned", "failed"}),
    "resumed": frozenset({"running", "orphaned", "failed", "done"}),
    # Terminal states.
    "orphaned": frozenset(),
    "failed": frozenset(),
    "done": frozenset(),
}


class InvalidTransitionError(ValueError):
    """Raised by ``transition`` on an illegal or unknown-state transition."""


class DaemonAlreadyRunningError(RuntimeError):
    """Raised by ``acquire_single_instance_lock`` when a live daemon holds it."""


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
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id or new_session_id(),
        "slug": slug,
        "plan_dir": plan_dir,
        "host": host,
        "tmux_target": tmux_target,
        "transcript_path": transcript_path,
        "transcript_offset": 0,
        "state": INITIAL_STATE,
        "state_changed_at": ts,
        "created_at": ts,
        "last_seen": ts,
        "last_context_check": None,
        "last_nudge_at": None,
        "nudge_count": 0,
        "parent_id": parent_id,
        "children": [],
    }


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
    if record["schema_version"] != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version {record['schema_version']!r} != {SCHEMA_VERSION}"
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

    Every accepted transition sets ``state`` and ``state_changed_at``. Hard-fail:
    an illegal transition (e.g. ``cleared`` -> ``handoff_requested``) or an
    unknown target state raises rather than silently no-op'ing.

    Args:
        record: The current session record (not mutated).
        new_state: The target state; must be in ``VALID_STATES``.
        now: ISO timestamp override (deterministic tests); defaults to now.

    Returns:
        A shallow copy of ``record`` with updated ``state`` / ``state_changed_at``.

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
    return updated


# ── atomic writes + reads (flush primitive) ──────────────────────────────────

def atomic_write_json(path: Path | str, obj: object, *, lock: bool = True) -> None:
    """Atomically write ``obj`` as JSON to ``path``. Hard-fail.

    This is the flush primitive a SIGTERM handler calls to persist
    ``sessions.json`` (STYLE.md:P-006, INVARIANTS inv_003): writes to a temp
    file in the same directory, ``flush`` + ``fsync``, then ``os.replace`` onto
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

        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
            tmp_name = None  # ownership transferred to the target
        finally:
            if tmp_name is not None:
                # Replace never happened — remove the orphan temp file.
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
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


def write_registry(path: Path | str, sessions: dict[str, dict]) -> None:
    """Validate every record then atomically write the registry. Hard-fail.

    Wraps ``sessions`` (a mapping of ``session_id`` -> record) under a top-level
    ``{schema_version, sessions}`` envelope. Each record is validated before the
    write so a malformed record can never reach disk (T003: every write leaves
    valid JSON matching the schema).

    Args:
        path: Destination ``sessions.json``.
        sessions: Mapping of session id -> session record.

    Raises:
        ValueError: if any record fails ``validate_record``.
        OSError: on write failure (see ``atomic_write_json``).
    """
    for record in sessions.values():
        validate_record(record)
    atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "sessions": sessions})


def read_registry(path: Path | str) -> dict[str, dict]:
    """Best-effort read of the registry; returns ``{}`` on missing/corrupt file.

    Returns:
        The ``sessions`` mapping, or an empty dict if the file is absent, torn,
        or structurally unexpected.
    """
    data = read_json(path, default={})
    if not isinstance(data, dict):
        return {}
    sessions = data.get("sessions", {})
    return sessions if isinstance(sessions, dict) else {}


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

    Drops the ``flock`` and closes ``fd``; optionally unlinks ``lock_path``. Any
    OS error during teardown is swallowed — the fd close alone releases the lock.
    """
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except OSError:
        pass
    if lock_path is not None:
        try:
            Path(lock_path).unlink()
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
