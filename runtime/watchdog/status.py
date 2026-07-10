"""Daemon status computation for the session-watchdog daemon.

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
- Best-effort throughout (STYLE.md:EH-001): a missing registry or heartbeat
  file degrades to an empty/`` None`` result rather than raising, mirroring
  ``registry.read_registry``'s own best-effort contract — a stale or
  crash-mid-write daemon must never break ``watchdog status``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from runtime.watchdog import registry


def compute_status(
    registry_path: Path | str,
    heartbeat_path: Path | str,
    *,
    now: Callable[[], float] = time.time,
) -> dict:
    """Return the current daemon status: registered sessions + heartbeat age.

    Best-effort (STYLE.md:EH-001): a missing or corrupt registry file yields
    an empty ``sessions`` list (via ``registry.read_registry``'s own
    best-effort contract) rather than raising; a missing heartbeat file
    yields ``heartbeat_age_s: None``.

    Args:
        registry_path: Path to ``sessions.json``.
        heartbeat_path: Path to the daemon heartbeat file (see
            ``daemon.touch_heartbeat``).
        now: Zero-arg callable returning the current epoch-seconds time;
            defaults to ``time.time`` and is overridable for deterministic
            tests.

    Returns:
        A dict with:

        - ``sessions``: a list of session summary dicts, each carrying at
          least ``session_id``, ``slug``, ``host``, ``state``, and
          ``tmux_target`` (read verbatim from each registry record).
        - ``heartbeat_age_s``: seconds elapsed since ``heartbeat_path``'s
          mtime, or ``None`` when the file is absent.
    """
    sessions = registry.read_registry(registry_path)
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

    return {"sessions": summaries, "heartbeat_age_s": heartbeat_age_s}
