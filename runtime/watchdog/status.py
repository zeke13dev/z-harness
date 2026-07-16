"""Authoritative lifecycle status computation for the session watchdog.

Purpose (T018, criterion #1): expose ``compute_status``, the pure read-side
function a later ``watchdog status`` CLI verb composes to report registered
sessions plus daemon heartbeat age.

Non-scope (a later level owns these — deliberately absent here): the CLI verb
itself (argument parsing, exit code, human-readable rendering) and any write
side effects — this module only reads ``registry.read_registry`` (T003) and a
heartbeat file's mtime.

Design decisions:
- ``now`` is an injectable callable (defaulting to ``time.time``) rather than
  a bare ``time.time()`` call, so heartbeat-age computation is deterministic
  in tests (STYLE.md:T-004).
- Missing files represent an unstarted daemon and empty authority. Malformed or
  future registry state is a hard failure so status can never misreport corrupt
  authority as an empty successful registry.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from runtime.watchdog import registry


def compute_status(
    registry_path: Path | str,
    heartbeat_path: Path | str,
    lock_path: Path | str | None = None,
    *,
    now: Callable[[], float] = time.time,
) -> dict:
    """Return authoritative roots, sessions, and daemon process status.

    A missing registry yields empty roots/sessions. Malformed or unsupported
    state raises from ``registry.read_registry_document``.

    Args:
        registry_path: Path to ``sessions.json``.
        heartbeat_path: Path to the daemon heartbeat file (see
            ``daemon.touch_heartbeat``).
        lock_path: Optional daemon pidfile+lock. When omitted, process status
            is reported as not running for compatibility with read-only callers.
        now: Zero-arg callable returning the current epoch-seconds time;
            defaults to ``time.time`` and is overridable for deterministic
            tests.

    Returns:
        A dict carrying registry version, durable root registrations, legacy
        session summaries, and daemon status.

        - ``sessions``: a list of session summary dicts, each carrying at
          least ``session_id``, ``slug``, ``host``, ``state``, and
          ``tmux_target`` (read verbatim from each registry record).
        - ``daemon``: authoritative lock status, pid, and seconds elapsed since
          the heartbeat mtime (``None`` when the heartbeat is absent).

    Raises:
        RegistryFormatError: if authoritative state is malformed or future.
        OSError: on authoritative registry or daemon-lock read failure.
    """
    document = registry.read_registry_document(registry_path)
    sessions = document["sessions"]
    summaries = [
        {
            "session_id": record.get("session_id"),
            "slug": record.get("slug"),
            "host": record.get("host"),
            "state": record.get("state"),
            "tmux_target": record.get("tmux_target"),
        }
        for record in sessions.values()
    ]

    heartbeat_age_s: float | None = None
    try:
        mtime = Path(heartbeat_path).stat().st_mtime
    except OSError:
        heartbeat_age_s = None
    else:
        heartbeat_age_s = now() - mtime

    roots = [
        {
            "coordinator_id": entry.get("coordinator_id"),
            "idempotency_key": entry.get("idempotency_key"),
            "manifest_sha256": entry.get("manifest_sha256"),
            "state": entry.get("state"),
        }
        for entry in document["coordinators"].values()
    ]
    roots.sort(key=lambda entry: str(entry["coordinator_id"]))
    running, pid = (
        registry.daemon_lock_status(lock_path)
        if lock_path is not None
        else (False, None)
    )
    return {
        "registry_version": document["registry_version"],
        "roots": roots,
        "sessions": summaries,
        "daemon": {
            "running": running,
            "pid": pid,
            "heartbeat_age_s": heartbeat_age_s,
        },
    }
