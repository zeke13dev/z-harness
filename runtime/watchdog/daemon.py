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

Also (T017, criteria #8/#9): ``run_startup_reconcile`` composes the three
primitives above with T014's ``reconcile.startup_reconcile`` into the daemon's
actual startup sequence — acquire the single-instance lock, reconcile the
registry against live tmux state, persist the result — so every later poll
cycle starts from a registry that already reflects reality.

Also (T019, criterion #1): ``run_poll_pass`` composes the level-2 per-session
cycle (``poll.poll_session``) into a single pass over every non-terminal
registered session: resolve every ``watchdog.*`` knob exactly once
(``registry.get_config_int``), capture each session's pane
(``tmux_actuator.capture_pane``), select the record's host adapter, and
dispatch ``poll.poll_session``. The ``cli.py`` ``status`` / ``run [--once]``
verbs are the thin argparse layer over this module's primitives.

Non-scope (deliberately absent here): the ``status`` / ``run [--once]``
argparse wiring itself (``cli.py``'s job) and host-adapter selection (the
caller supplies ``adapter_for_host`` — this module stays host-agnostic,
mirroring every sibling module's DI-seam discipline).

Design decisions:
- DI seam (STYLE.md:P-004 spirit): ``install_sigterm_handler`` takes a
  zero-arg ``get_sessions`` callable rather than a snapshot dict, so the
  handler always flushes whatever the caller's in-memory mapping holds *at
  signal time* — not a stale copy captured at installation time.
- Signal-safety: the registered handler does the minimum possible work (take
  the registry sidecar lock, one flush call, then exit). CPython signal
  handlers execute between bytecode instructions in the main thread (not in a
  true async-signal context), so calling ``registry.write_registry`` under
  ``registry.hold_registry_lock`` here is safe in practice, and keeping the
  handler minimal bounds the work done during signal delivery. The lock ensures
  the flush never tears a concurrent writer's registry update (T-REV-001); the
  critical section is a single validated ``os.replace`` write, so its window is
  tiny. (The daemon poll loop never holds this lock across poll arms — its
  ``locked_registry_update`` cycles acquire and release inside a single call —
  so a SIGTERM arriving between poll passes finds the lock free.)
- No swallowed flush failure (STYLE.md:EH-004, no-fallback stance):
  ``write_registry`` is hard-fail (T003). The handler does not catch its
  exceptions — a broken registry path must surface loudly rather than let the
  daemon exit "cleanly" over an un-flushed registry. ``sys.exit(0)`` is only
  reached after the flush succeeds.
- ``run_poll_pass`` skips a terminal-state record (``registry.is_terminal``)
  outright rather than dispatching it to ``poll.poll_session``:
  ``tmux_actuator.capture_pane`` hard-fails on a dead pane
  (``TmuxActuationError``), and a terminal session (``done``/``failed``/
  ``orphaned``) needs no further polling — capturing its pane would only
  crash the whole pass for no benefit.
- A per-session ``capture_pane`` failure (a hung or already-dead pane this
  cycle — narrower than the terminal-state check above, e.g. a target that
  died out-of-band since the last reconcile) is caught by NAMED exception
  only (STYLE.md:EH-002: ``TmuxActuationError``/``TmuxTimeoutError``) and
  that session is skipped for this pass rather than crashing the remaining
  siblings — mirrors ``reconcile.py``'s T014 "never blocking sibling
  evaluation" precedent.
"""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from runtime.watchdog import notify, poll, reconcile, registry, tmux_actuator
from runtime.watchdog.adapters.base import HostAdapter

SigtermHandler = Callable[[int, object], None]


def install_sigterm_handler(
    get_sessions: Callable[[], dict[str, dict]],
    registry_path: Path | str,
) -> SigtermHandler:
    """Install a ``SIGTERM`` handler that flushes ``get_sessions()`` before exit.

    On receipt of ``SIGTERM``, the handler calls ``get_sessions()`` to read
    whatever the daemon's current in-memory sessions mapping is and flushes it
    as the authoritative shutdown snapshot via ``registry.write_registry``
    (validates + atomically flushes, T003) — held under
    ``registry.hold_registry_lock`` (with ``lock=False`` since the handler
    already holds the sidecar lock) so the flush never tears a concurrent
    registry writer's update mid-replace (T-REV-001) — and then exits. Never
    exits without flushing: if the flush raises, the exception propagates
    uncaught rather than being swallowed to allow an exit anyway
    (STYLE.md:EH-004).

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
        # Flush the live in-memory mapping as the authoritative shutdown
        # snapshot, but hold the registry sidecar lock across the write
        # (``lock=False`` since we already hold it) so the flush never tears a
        # concurrent writer's registry update mid-``os.replace`` (T-REV-001).
        # This is deliberately a snapshot write, not a merge: at exit the
        # daemon's own mapping IS the authority for the sessions it owns.
        with registry.hold_registry_lock(registry_path):
            registry.write_registry(registry_path, get_sessions(), lock=False)
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


def run_startup_reconcile(
    registry_path: Path | str,
    lock_path: Path | str,
    *,
    has_session: Callable[..., bool] = tmux_actuator.has_session,
    alert_fn: Callable[..., bool] = notify.send_discord_alert,
    timeout: float = tmux_actuator.DEFAULT_TIMEOUT_S,
    now: str | None = None,
) -> dict[str, dict]:
    """Run the daemon's startup reconcile pass before any poll cycle begins.

    Acquires the single-instance lock via ``run_lifecycle`` (reusing T003's
    stale-dead-pid auto-cleanup — no new lock logic here), reads the current
    registry, reconciles it against live tmux state
    (``reconcile.startup_reconcile``, T014: marks a record whose tmux target
    is gone ``orphaned`` exactly once, alerting via ``alert_fn``, never
    auto-adopting it back into a lifecycle state), persists the result, and
    returns the updated sessions mapping.

    Concurrency (T-REV-001): the reconcile pass — whose per-record
    ``has_session`` tmux checks each carry a subprocess timeout — runs against
    an UNLOCKED snapshot read, holding no registry sidecar lock, so it never
    blocks a concurrent ``fanout.run_fanout`` persist or the SIGTERM flush.
    Only the resulting orphaned-record marks are then merged onto a fresh
    locked re-read via ``registry.locked_registry_update``, so a child record a
    fanout persisted while the tmux checks were running survives rather than
    being clobbered by the pre-check snapshot.

    Args:
        registry_path: Path to ``sessions.json``.
        lock_path: Path to the daemon single-instance pidfile+lock.
        has_session: Injected ``tmux_actuator.has_session``-shaped callable.
        alert_fn: Injected ``notify.send_discord_alert``-shaped callable.
        timeout: Explicit subprocess timeout passed to every ``has_session``
            call.
        now: ISO timestamp override (deterministic tests); defaults to now.

    Returns:
        The updated ``session_id`` -> record mapping, already persisted to
        ``registry_path``.

    Raises:
        DaemonAlreadyRunningError: propagated verbatim (via ``run_lifecycle``)
            when a live daemon already holds the lock.
    """
    with run_lifecycle(lock_path):
        # Run the tmux-check reconcile pass against an unlocked snapshot so the
        # per-record has_session subprocess calls never hold the registry
        # sidecar lock (T-REV-001), then merge only the records this pass
        # actually changed (the newly-orphaned ones) onto a fresh locked
        # re-read.
        pre = registry.read_registry(registry_path)
        reconciled = reconcile.startup_reconcile(
            pre,
            has_session=has_session,
            timeout=timeout,
            alert_fn=alert_fn,
            now=now,
        )
        changed = {sid: rec for sid, rec in reconciled.items() if pre.get(sid) != rec}

        def _apply(fresh: dict[str, dict]) -> None:
            fresh.update(changed)

        return registry.locked_registry_update(registry_path, _apply)


def run_poll_pass(
    sessions: dict[str, dict],
    *,
    registry_path: Path | str,
    signals_path: Path | str,
    repo_root: Path | str,
    adapter_for_host: Callable[[str], HostAdapter],
    get_config_int: Callable[[str], int] = registry.get_config_int,
    capture_pane: Callable[..., str] = tmux_actuator.capture_pane,
    poll_session: Callable[..., dict] = poll.poll_session,
) -> dict[str, dict]:
    """Run one poll pass over every non-terminal registered session.

    Resolves every ``watchdog.*`` knob exactly once (T019, criterion #1),
    then for each ``sessions`` record NOT in a terminal state
    (``registry.is_terminal``): selects its host adapter via
    ``adapter_for_host``, captures its pane (``capture_pane``), and dispatches
    ``poll_session`` exactly once. A per-session pane-capture failure (a dead
    or hung target — narrower than the terminal-state skip above) is caught
    by named exception and that session is skipped for this pass rather than
    crashing the remaining siblings (see module docstring).

    This function does not itself acquire the single-instance lock or touch
    the heartbeat — the caller (``cli.py``'s ``run [--once]`` verb) wraps this
    call in ``run_lifecycle`` and calls ``touch_heartbeat`` after it returns,
    mirroring every other primitive in this module.

    Args:
        sessions: The current ``session_id`` -> record mapping (e.g. from
            ``run_startup_reconcile`` or ``registry.read_registry``). Not
            mutated in place.
        registry_path: Path to ``sessions.json`` (forwarded to
            ``poll_session``, which persists after each dispatched session).
        signals_path: Path to ``signals.jsonl`` (forwarded to
            ``poll_session``'s ``judge_degraded`` sink).
        repo_root: Absolute repo root (forwarded to ``poll_session`` for
            judge provider-role resolution).
        adapter_for_host: Callable resolving a session record's ``host``
            field (``"claude"``/``"codex"``/``"omp"``) to a ``HostAdapter``
            instance. Injected so this module stays host-agnostic (mirrors
            every sibling module's DI-seam discipline) — ``cli.py`` owns the
            actual claude/codex/omp mapping.
        get_config_int: Injected ``registry.get_config_int``-shaped callable
            (deterministic tests never shell out to ``scripts/config.py``).
        capture_pane: Injected ``tmux_actuator.capture_pane``-shaped callable.
        poll_session: Injected ``poll.poll_session``-shaped callable.

    Returns:
        The final ``session_id`` -> record mapping after every dispatched
        session's cycle (already persisted to ``registry_path`` by
        ``poll_session`` itself on each dispatch).
    """
    threshold_pct = get_config_int("watchdog.context_threshold_pct")
    window_tokens = get_config_int("watchdog.context_window_tokens")
    stuck_after_s = get_config_int("watchdog.stuck_after_s")
    nudge_max = get_config_int("watchdog.nudge_max")
    judge_timeout_s = get_config_int("watchdog.judge_timeout_s")
    signals_max_mb = get_config_int("watchdog.signals_max_mb")

    sessions = dict(sessions)
    for record in list(sessions.values()):
        if registry.is_terminal(record["state"]):
            continue

        try:
            pane_text = capture_pane(record["tmux_target"])
        except (tmux_actuator.TmuxActuationError, tmux_actuator.TmuxTimeoutError):
            # Dead or hung pane this cycle — retried next pass rather than
            # blocking the remaining sessions.
            continue

        adapter = adapter_for_host(record["host"])
        result = poll_session(
            record, sessions,
            adapter=adapter,
            pane_text=pane_text,
            registry_path=registry_path,
            signals_path=signals_path,
            repo_root=repo_root,
            threshold_pct=float(threshold_pct),
            window_tokens=window_tokens,
            stuck_after_s=stuck_after_s,
            nudge_max=nudge_max,
            judge_timeout_s=float(judge_timeout_s),
            signals_max_mb=signals_max_mb,
        )
        sessions = result["sessions"]

    return sessions
