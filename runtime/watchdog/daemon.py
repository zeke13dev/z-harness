"""Daemon lifecycle primitives for the session-watchdog daemon.

Purpose (T015, criterion #9): ship the three lifecycle primitives every later
watchdog level composes into the actual daemon process:

- ``install_sigterm_handler`` — registers a ``SIGTERM`` handler that atomically
  flushes the CURRENT in-memory sessions mapping to ``sessions.json`` before the
  process exits (registry.write_registry / registry.atomic_write_json, T003);
- ``touch_heartbeat`` — updates a heartbeat file's mtime, the signal a later
  ``watchdog status`` reads to report daemon heartbeat age;
- ``run_lifecycle`` — a context manager wrapping
  ``registry.acquire_single_instance_lock`` / ``release_single_instance_lock``
  (T003) so daemon startup/shutdown correctly acquires-then-releases the
  single-instance lock, propagating ``DaemonAlreadyRunningError`` when a live
  daemon already holds it.

Non-scope (level 2 owns these — deliberately absent here): the poll loop, the
``status`` / ``run --once`` CLI verbs, and invoking the T014 startup-reconcile
pass. This module ships primitives only; T014's ``reconcile.py`` review note
explicitly deferred single-instance-lock USAGE to this task.

Design decisions:
- DI seam (STYLE.md:P-004 spirit): ``install_sigterm_handler`` takes a
  zero-arg ``get_sessions`` callable rather than a snapshot dict, so the
  handler always flushes whatever the caller's in-memory mapping holds *at
  signal time* — not a stale copy captured at installation time.
- Signal-safety: the registered handler does the minimum possible work (one
  flush call, then exit) and performs no other I/O or locking. CPython signal
  handlers execute between bytecode instructions in the main thread (not in a
  true async-signal context), so calling ``registry.write_registry`` here is
  safe in practice, but keeping the handler minimal bounds the work done
  during signal delivery regardless.
- No swallowed flush failure (STYLE.md:EH-004, no-fallback stance):
  ``write_registry`` is hard-fail (T003). The handler does not catch its
  exceptions — a broken registry path must surface loudly rather than let the
  daemon exit "cleanly" over an un-flushed registry. ``sys.exit(0)`` is only
  reached after the flush succeeds.
"""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from runtime.watchdog import registry

SigtermHandler = Callable[[int, object], None]


def install_sigterm_handler(
    get_sessions: Callable[[], dict[str, dict]],
    registry_path: Path | str,
) -> SigtermHandler:
    """Install a ``SIGTERM`` handler that flushes ``get_sessions()`` before exit.

    On receipt of ``SIGTERM``, the handler calls ``get_sessions()`` to read
    whatever the daemon's current in-memory sessions mapping is, writes it via
    ``registry.write_registry`` (validates + atomically flushes, T003), and
    then exits. Never exits without flushing: if the flush raises, the
    exception propagates uncaught rather than being swallowed to allow an
    exit anyway (STYLE.md:EH-004).

    Args:
        get_sessions: Zero-arg callable returning the CURRENT session-id ->
            record mapping at call time (a closure over the daemon's live
            state, not a snapshot taken at install time).
        registry_path: Destination ``sessions.json`` path.

    Returns:
        The registered handler function itself, so callers (and tests) can
        invoke it directly without sending a real signal.
    """

    def _handler(signum: int, frame: object) -> None:
        registry.write_registry(registry_path, get_sessions())
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handler)
    return _handler


def touch_heartbeat(path: Path | str) -> None:
    """Update ``path``'s mtime to now, creating it first if absent. Hard-fail.

    ``watchdog status`` (a later level) reads this file's mtime to report the
    daemon heartbeat age — this function is the write side of that contract.

    Args:
        path: Heartbeat file path.

    Raises:
        OSError: on a filesystem failure creating the parent directory or
            touching the file — a broken heartbeat path is a real problem
            that should surface, not be swallowed (STYLE.md:EH-004).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    os.utime(path, None)


@contextmanager
def run_lifecycle(lock_path: Path | str) -> Iterator[int]:
    """Context manager for the daemon's single-instance lock lifecycle.

    Acquires ``registry.acquire_single_instance_lock(lock_path)`` (T003, with
    its built-in stale-pid cleanup) on entry and releases it via
    ``registry.release_single_instance_lock`` on exit, whether the body
    raises or completes normally.

    Args:
        lock_path: Path to the daemon single-instance pidfile+lock.

    Yields:
        The open lock fd (matching ``acquire_single_instance_lock``'s return).

    Raises:
        DaemonAlreadyRunningError: propagated verbatim when a live daemon
            (its recorded pid passes ``kill -0``) already holds the lock.
    """
    fd = registry.acquire_single_instance_lock(lock_path)
    try:
        yield fd
    finally:
        registry.release_single_instance_lock(fd, lock_path)
