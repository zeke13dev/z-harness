"""tmux actuation primitives for the session-watchdog daemon.

Purpose (T004, criterion #9): wrap every tmux subprocess call the daemon needs
(``capture-pane``, ``send-keys``, ``has-session``, ``new-session``,
``kill-session``) with an explicit, mandatory subprocess ``timeout``, and
reimplement the submit-race-safe compound action (literal-text ``send-keys``,
a settle gap, then a *separate* ``Enter``) referenced read-only from
``scripts/hermes/mcp_hermes_orchestrator.py:844-856`` — that module is so-MCP
reference material only and is never imported or modified (INTENT "Not doing":
"so-MCP stays untouched as reference material only").

Design decisions:
- D-timeout: this task's ``Files:`` scope is ``tmux_actuator.py`` only — no new
  ``watchdog.*`` config knob is added here (T002 already froze the level-0
  knob set). Every wrapper instead exposes an explicit ``timeout`` keyword
  defaulting to the module-level ``DEFAULT_TIMEOUT_S`` constant, so callers
  always get an override seam and no call site can silently omit a timeout.
  Recorded as a decision in LEDGER.md, not silently hardcoded.
- The submit-race pattern (``submit_text``): a freshly-booted TUI's composer
  can be mid bracketed-paste when a combined "text + Enter" send-keys lands,
  swallowing the Enter and leaving the prompt typed but unsubmitted. Typing
  the prompt as literal text (``-l``) and sending ``Enter`` as a SEPARATE
  ``send-keys`` call, with a settle sleep between them, avoids the race —
  exactly mirroring the reference's ``_SUBMIT_SETTLE_SECONDS`` gap.

Error handling (STYLE.md:EH-001): every wrapper here is hard-fail. A hung tmux
invocation raises ``TmuxTimeoutError`` (chained from
``subprocess.TimeoutExpired``, STYLE.md:EH-003) rather than blocking; a
non-zero tmux exit raises ``TmuxActuationError``. ``has_session`` is the one
exception to "non-zero is an error": tmux's own ``has-session`` semantics
encode "session does not exist" as a non-zero exit, so that call intentionally
returns a bool instead of raising on non-zero (still raises
``TmuxTimeoutError`` on a hang, per STYLE.md:EH-002 — only the exception types
we catch are named, never a bare ``except``).
"""

from __future__ import annotations

import subprocess
import time
from typing import Callable, Sequence

DEFAULT_TIMEOUT_S = 15.0
"""Default per-call subprocess timeout (seconds) for tmux invocations."""

SUBMIT_SETTLE_SECONDS = 0.2
"""Settle gap between the literal-text send-keys and the submit Enter,
mirroring ``mcp_hermes_orchestrator.py``'s ``_SUBMIT_SETTLE_SECONDS`` so a
booting TUI's bracketed-paste closes before Enter arrives."""

_sleep: Callable[[float], None] = time.sleep
"""Indirection so tests can monkeypatch the settle sleep to a no-op."""


class TmuxActuationError(RuntimeError):
    """A tmux invocation exited non-zero. Hard-fail (STYLE.md:EH-001)."""


class TmuxTimeoutError(RuntimeError):
    """A tmux invocation exceeded its timeout. Hard-fail (STYLE.md:EH-001)."""


def _run(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` under an explicit ``timeout``, without exit-code checking.

    Every public wrapper in this module funnels through here so the mandatory
    timeout is enforced in exactly one place.

    Raises:
        TmuxTimeoutError: if the subprocess exceeds ``timeout`` seconds — never
            blocks past the deadline.
    """
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TmuxTimeoutError(
            f"tmux command timed out after {timeout}s: {' '.join(argv)}"
        ) from exc


def _run_checked(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` under ``timeout`` and hard-fail on a non-zero exit.

    Raises:
        TmuxTimeoutError: see ``_run``.
        TmuxActuationError: if tmux exits non-zero.
    """
    proc = _run(argv, timeout=timeout)
    if proc.returncode != 0:
        raise TmuxActuationError(
            (proc.stderr or proc.stdout or "tmux command failed").strip()
            + f" (argv={list(argv)})"
        )
    return proc


# ── individual tmux verbs ─────────────────────────────────────────────────────

def capture_pane(target: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    """Return the captured pane text for ``target``. Hard-fail.

    Args:
        target: tmux session/pane target (e.g. ``zw-slug-abcd1234``).
        timeout: Subprocess timeout in seconds.

    Returns:
        The pane's stdout text.

    Raises:
        TmuxTimeoutError: on a hang.
        TmuxActuationError: if capture-pane exits non-zero (e.g. no such pane).
    """
    proc = _run_checked(["tmux", "capture-pane", "-p", "-t", target], timeout=timeout)
    return proc.stdout or ""


def has_session(target: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> bool:
    """Return whether ``target`` is a live tmux session. Best-effort exit-code
    read (STYLE.md:EH-001): tmux's own ``has-session`` semantics already encode
    absence as a non-zero exit, so that case returns ``False`` rather than
    raising.

    Raises:
        TmuxTimeoutError: on a hang — a stuck ``tmux`` process is a real
            problem and must surface, not be read as "session absent".
    """
    proc = _run(["tmux", "has-session", "-t", target], timeout=timeout)
    return proc.returncode == 0


def new_session(
    name: str,
    command: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> None:
    """Create a detached tmux session named ``name``. Hard-fail.

    Args:
        name: The new tmux session name (by convention a ``zw-`` prefixed id
            minted via ``registry.new_tmux_name``).
        command: Optional command to launch inside the session (e.g. the host
            CLI); omitted entirely when ``None``.
        timeout: Subprocess timeout in seconds.

    Raises:
        TmuxTimeoutError: on a hang.
        TmuxActuationError: if tmux exits non-zero (e.g. name already in use).
    """
    argv = ["tmux", "new-session", "-d", "-s", name]
    if command is not None:
        argv.append(command)
    _run_checked(argv, timeout=timeout)


def kill_session(target: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
    """Kill tmux session ``target``. Hard-fail.

    Raises:
        TmuxTimeoutError: on a hang.
        TmuxActuationError: if tmux exits non-zero (e.g. no such session).
    """
    _run_checked(["tmux", "kill-session", "-t", target], timeout=timeout)


def send_keys(target: str, keys: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
    """Send a single named key (e.g. ``"Down"``, ``"Enter"``) to ``target``.
    Hard-fail.

    For arbitrary literal text use ``send_keys_literal`` instead — this
    wrapper does not pass ``-l`` and so tmux interprets ``keys`` as a key
    name/sequence.

    Raises:
        TmuxTimeoutError: on a hang.
        TmuxActuationError: if tmux exits non-zero.
    """
    _run_checked(["tmux", "send-keys", "-t", target, keys], timeout=timeout)


def send_keys_literal(target: str, text: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
    """Send ``text`` to ``target`` as literal characters (tmux ``-l``). Hard-fail.

    Deliberately does NOT submit — pairs with a separate ``send_enter`` (or
    use ``submit_text`` for the settle-gapped compound action) so a booting
    TUI's bracketed-paste cannot swallow the Enter.

    Raises:
        TmuxTimeoutError: on a hang.
        TmuxActuationError: if tmux exits non-zero.
    """
    _run_checked(["tmux", "send-keys", "-t", target, "-l", text], timeout=timeout)


def send_enter(target: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> None:
    """Send a submit ``Enter`` keystroke to ``target``. Hard-fail.

    Raises:
        TmuxTimeoutError: on a hang.
        TmuxActuationError: if tmux exits non-zero.
    """
    _run_checked(["tmux", "send-keys", "-t", target, "Enter"], timeout=timeout)


def submit_text(
    target: str,
    text: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    settle_seconds: float = SUBMIT_SETTLE_SECONDS,
) -> None:
    """Type ``text`` into ``target`` and submit it, race-safely. Hard-fail.

    Reimplements the submit-race pattern referenced read-only from
    ``mcp_hermes_orchestrator.py:838-856``: literal-text ``send-keys``, a
    settle sleep, then a submit ``Enter`` as a SEPARATE ``send-keys`` call.
    Sending text + Enter as one call races a freshly-booted TUI's
    bracketed-paste close and can swallow the Enter, leaving the prompt typed
    but never submitted.

    Args:
        target: tmux session/pane target.
        text: The literal prompt text to type.
        timeout: Subprocess timeout in seconds, applied to each of the two
            underlying tmux calls.
        settle_seconds: Sleep gap between the literal text and the Enter.

    Raises:
        TmuxTimeoutError: on a hang in either underlying call.
        TmuxActuationError: if either underlying call exits non-zero.
    """
    send_keys_literal(target, text, timeout=timeout)
    _sleep(settle_seconds)
    send_enter(target, timeout=timeout)
