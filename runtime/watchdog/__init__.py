"""Session-watchdog daemon package (``runtime/watchdog/``).

Purpose: a z-harness-native, long-lived watchdog daemon that babysits
tmux-hosted managed agent sessions across the claude / codex / omp hosts. This
package owns the session registry (``sessions.json``), the tmux actuator, host
adapters, notification, and judge-dispatch primitives that the poll loop and
CLI verbs (shipped in later levels) compose.

Design decisions:
- ``registry`` ships *primitives only* (T003, criterion #9): the schema factory,
  the state-transition validator, id/name generators, the flock-guarded atomic
  write flush primitive, the daemon single-instance pidfile lock, and the
  ``signals.jsonl`` append helper. The SIGTERM handler, startup reconcile pass,
  and poll loop belong to level 1 and are intentionally NOT in this package yet.
- The ``sessions.json`` record schema and the ``ws-`` / ``zw-`` id contracts are
  irreversible public surface — every later level builds on them (see
  ``registry.SCHEMA_VERSION``).

This module re-exports the stable registry surface so callers can
``from runtime.watchdog import new_session_record`` etc.
"""

from __future__ import annotations

from runtime.watchdog.registry import (  # noqa: F401  (re-export)
    INITIAL_STATE,
    SCHEMA_VERSION,
    SESSION_ID_PREFIX,
    TERMINAL_STATES,
    TMUX_NAME_PREFIX,
    VALID_HOSTS,
    VALID_STATES,
    DaemonAlreadyRunningError,
    InvalidTransitionError,
    acquire_single_instance_lock,
    append_signal,
    atomic_write_json,
    get_config_int,
    is_terminal,
    is_valid_transition,
    new_session_id,
    new_session_record,
    new_tmux_name,
    read_json,
    read_lock_pid,
    read_registry,
    release_single_instance_lock,
    transition,
    validate_record,
    write_registry,
)

__all__ = [
    "INITIAL_STATE",
    "SCHEMA_VERSION",
    "SESSION_ID_PREFIX",
    "TERMINAL_STATES",
    "TMUX_NAME_PREFIX",
    "VALID_HOSTS",
    "VALID_STATES",
    "DaemonAlreadyRunningError",
    "InvalidTransitionError",
    "acquire_single_instance_lock",
    "append_signal",
    "atomic_write_json",
    "get_config_int",
    "is_terminal",
    "is_valid_transition",
    "new_session_id",
    "new_session_record",
    "new_tmux_name",
    "read_json",
    "read_lock_pid",
    "read_registry",
    "release_single_instance_lock",
    "transition",
    "validate_record",
    "write_registry",
]
