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

Supervised intervention boundary (T004, criterion #8):
``dispatch_lifecycle_action`` rejects action names outside the fixed
deterministic allowlist, atomically persists a stable prepared marker before
the host effect, pauses on ambiguous intent/host state or a prepared marker
left by a crash, and durably escalates exhausted bounded attempts.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from runtime.watchdog import notify, registry

DEFAULT_TIMEOUT_S = 15.0
"""Default per-call subprocess timeout (seconds) for tmux invocations."""

SUBMIT_SETTLE_SECONDS = 0.2
"""Settle gap between the literal-text send-keys and the submit Enter,
mirroring ``mcp_hermes_orchestrator.py``'s ``_SUBMIT_SETTLE_SECONDS`` so a
booting TUI's bracketed-paste closes before Enter arrives."""

_sleep: Callable[[float], None] = time.sleep
"""Indirection so tests can monkeypatch the settle sleep to a no-op."""

DETERMINISTIC_ACTION_ALLOWLIST = frozenset({
    "clear",
    "coordinator_wake",
    "escalation",
    "handoff",
    "nudge",
})
"""The complete set of host-side actions the daemon may dispatch."""

NUDGE_TEXT = "still there? (automated watchdog nudge)"
_HANDOFF_TEXT = "/z-handoff"
_CLEAR_TEXTS = frozenset({"/clear", "/new"})
_WAKE_TEXT_RE = re.compile(
    r"fanout '[^\r\n']+' children all terminal \(automated watchdog\):"
    r"\nwatchdog_ack outbox_id=wake:v1:[0-9a-f]{64} "
    r"coordinator_generation=coordinator:v1:[^\s:]+:\d+"
    r"(?:\n- [^\r\n]+: (?:done|failed|cancelled|orphaned))+\Z"
)
_ESCALATION_TITLE_RE = re.compile(r"stuck session: [^\r\n]+\Z")
_ESCALATION_BODY_RE = re.compile(
    r"no response after \d+ nudge\(s\); idle \d+s\.\Z"
)
_ACTION_AUTHORITY = {
    "handoff": (frozenset({"handoff_written"}), "state_changed_at"),
    "clear": (frozenset({"cleared"}), "state_changed_at"),
    "coordinator_wake": (frozenset({"awaiting_children"}), "state_generation"),
    "nudge": (frozenset({"registered", "running", "stuck", "resumed"}), "last_seen"),
    "escalation": (
        frozenset({"registered", "running", "stuck", "resumed"}),
        "last_seen",
    ),
}


class TmuxActuationError(RuntimeError):
    """A tmux invocation exited non-zero. Hard-fail (STYLE.md:EH-001)."""


class TmuxTimeoutError(RuntimeError):
    """A tmux invocation exceeded its timeout. Hard-fail (STYLE.md:EH-001)."""


class LifecycleActionRejectedError(ValueError):
    """A caller requested an action outside the deterministic allowlist."""


def _action_marker_id(
    session_id: str, action: str, generation: str, attempt: int
) -> str:
    """Return a stable, content-derived identifier for one logical attempt."""
    source = f"{session_id}\0{action}\0{generation}\0{attempt}".encode()
    return f"action-{hashlib.sha256(source).hexdigest()[:24]}"


def dispatch_lifecycle_action(
    registry_path: Path | str,
    *,
    session_id: str,
    action: str,
    generation: str,
    attempt: int | None,
    max_attempts: int,
    target: str | None = None,
    text: str | None = None,
    title: str | None = None,
    body: str | None = None,
    intent_confirmed: bool = True,
    host_ready: bool = True,
    now: str | None = None,
) -> dict[str, object]:
    """Persist intent, then dispatch one approved deterministic host action.

    A ``prepared`` marker is committed before the fixed action handler runs. Seeing that
    marker again means the prior side effect has an ambiguous outcome, so a
    restart pauses without retrying. The session, target, lifecycle generation,
    and compatible state are resolved from the fresh registry document under
    the same lock before any marker is created. A definitely failed effect returns
    ``False``; exhausting the caller's bounded attempts then creates an
    explicit durable escalation marker. Unknown actions and invalid attempt
    bounds hard-fail before any registry mutation.

    Args:
        registry_path: Authoritative watchdog registry.
        session_id: Stable logical session identifier.
        action: One member of ``DETERMINISTIC_ACTION_ALLOWLIST``.
        generation: Stable lifecycle generation or episode identifier.
        attempt: One-indexed attempt number, or ``None`` to atomically select
            the next attempt after any definitely failed marker.
        max_attempts: Maximum permitted attempts for this generation.
        target: tmux target for handoff, clear, nudge, or coordinator wake.
        text: Literal text for handoff, clear, nudge, or coordinator wake.
        title: Discord title for escalation.
        body: Discord body for escalation.
        intent_confirmed: False when durable intent is absent or ambiguous.
        host_ready: False when the host cannot unambiguously accept input.
        now: Timestamp override for deterministic tests.

    Returns:
        ``{"status", "action_id", "attempt"}``, where status is one of
        ``paused``, ``completed``, ``failed``, or ``escalated``.

    Raises:
        LifecycleActionRejectedError: for an unknown action, invalid bounds,
            or a request that conflicts with authoritative session state.
        OSError: when the durable marker cannot be persisted.
    """
    if action not in DETERMINISTIC_ACTION_ALLOWLIST:
        raise LifecycleActionRejectedError(f"action is not approved: {action!r}")
    if (attempt is not None and attempt < 1) or max_attempts < 1:
        raise LifecycleActionRejectedError("attempt bounds must be positive")
    if action == "escalation":
        if not title or not body or target is not None or text is not None:
            raise LifecycleActionRejectedError("escalation requires only title and body")
    elif not target or not text or title is not None or body is not None:
        raise LifecycleActionRejectedError(
            f"{action} requires only a tmux target and literal text"
        )
    if action == "handoff" and text != _HANDOFF_TEXT:
        raise LifecycleActionRejectedError("handoff text is not deterministic")
    if action == "clear" and text not in _CLEAR_TEXTS:
        raise LifecycleActionRejectedError("clear text is not deterministic")
    if action == "nudge" and text != NUDGE_TEXT:
        raise LifecycleActionRejectedError("nudge text is not deterministic")
    if action == "coordinator_wake" and not _WAKE_TEXT_RE.fullmatch(text or ""):
        raise LifecycleActionRejectedError("coordinator wake summary is malformed")
    if action == "escalation" and (
        not _ESCALATION_TITLE_RE.fullmatch(title or "")
        or not _ESCALATION_BODY_RE.fullmatch(body or "")
    ):
        raise LifecycleActionRejectedError("escalation request is malformed")
    if not intent_confirmed or not host_ready:
        return {"status": "paused", "action_id": None, "attempt": attempt}

    timestamp = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    escalation_id = _action_marker_id(session_id, action, generation, max_attempts + 1)
    claim_status = "claimed"
    resolved_attempt = attempt
    action_id: str | None = None

    def _validate_authority(document: dict[str, object]) -> None:
        sessions: dict[str, dict] = document["sessions"]
        record = sessions.get(session_id)
        if record is None:
            raise LifecycleActionRejectedError(
                f"session is absent from authoritative registry: {session_id!r}"
            )
        allowed_states, generation_field = _ACTION_AUTHORITY[action]
        if record["state"] not in allowed_states:
            raise LifecycleActionRejectedError(
                f"action {action!r} is incompatible with state {record['state']!r}"
            )
        authority_generation = (
            registry.coordinator_generation_for(record)
            if action == "coordinator_wake"
            else record[generation_field]
        )
        if authority_generation != generation:
            raise LifecycleActionRejectedError(
                f"stale {action!r} generation for session {session_id!r}"
            )
        authoritative_target = record["tmux_target"]
        if action == "escalation":
            if title != f"stuck session: {authoritative_target}":
                raise LifecycleActionRejectedError(
                    "escalation target does not match authoritative registry"
                )
        elif target != authoritative_target:
            raise LifecycleActionRejectedError(
                "tmux target does not match authoritative registry"
            )

    if attempt is not None and attempt > max_attempts:
        def _escalate(document: dict[str, object]) -> None:
            _validate_authority(document)
            markers: dict[str, dict] = document["action_markers"]
            markers.setdefault(escalation_id, {
                "registry_version": registry.REGISTRY_VERSION,
                "action": action,
                "session_id": session_id,
                "generation": generation,
                "attempt": max_attempts + 1,
                "status": "escalated",
                "created_at": timestamp,
            })

        registry.locked_registry_document_update(registry_path, _escalate)
        return {
            "status": "escalated",
            "action_id": escalation_id,
            "attempt": max_attempts + 1,
        }

    def _claim(document: dict[str, object]) -> None:
        nonlocal action_id, claim_status, resolved_attempt
        _validate_authority(document)
        markers: dict[str, dict] = document["action_markers"]
        for marker_id, marker in markers.items():
            if (
                marker.get("session_id") == session_id
                and marker.get("action") == action
                and marker.get("generation") == generation
                and marker.get("status") == "prepared"
            ):
                resolved_attempt = int(marker["attempt"])
                action_id = marker_id
                claim_status = "prepared"
                return
        if resolved_attempt is None:
            for candidate in range(1, max_attempts + 1):
                candidate_id = _action_marker_id(
                    session_id, action, generation, candidate
                )
                existing_candidate = markers.get(candidate_id)
                if existing_candidate is None:
                    resolved_attempt = candidate
                    break
                if existing_candidate["status"] == "failed":
                    continue
                resolved_attempt = candidate
                action_id = candidate_id
                claim_status = str(existing_candidate["status"])
                return
            else:
                claim_status = "escalated"
                markers.setdefault(escalation_id, {
                    "registry_version": registry.REGISTRY_VERSION,
                    "action": action,
                    "session_id": session_id,
                    "generation": generation,
                    "attempt": max_attempts + 1,
                    "status": "escalated",
                    "created_at": timestamp,
                })
                return
        assert resolved_attempt is not None
        action_id = _action_marker_id(
            session_id, action, generation, resolved_attempt
        )
        existing = markers.get(action_id)
        if existing is not None:
            claim_status = str(existing["status"])
            return
        markers[action_id] = {
            "registry_version": registry.REGISTRY_VERSION,
            "action": action,
            "session_id": session_id,
            "generation": generation,
            "attempt": resolved_attempt,
            "status": "prepared",
            "created_at": timestamp,
        }

    registry.locked_registry_document_update(registry_path, _claim)
    if claim_status == "escalated":
        return {
            "status": "escalated",
            "action_id": escalation_id,
            "attempt": max_attempts + 1,
        }
    assert action_id is not None and resolved_attempt is not None
    if claim_status != "claimed":
        status = "paused" if claim_status == "prepared" else claim_status
        return {"status": status, "action_id": action_id, "attempt": resolved_attempt}

    if action == "escalation":
        delivered = notify.send_discord_alert(title, body)
        final_status = "completed" if bool(delivered) else "failed"
    else:
        delivered = submit_text(target, text)
        final_status = "completed" if delivered is not False else "failed"

    def _finish(document: dict[str, object]) -> None:
        markers: dict[str, dict] = document["action_markers"]
        marker = markers[action_id]
        marker["status"] = final_status
        marker["finished_at"] = timestamp
        if final_status == "failed" and resolved_attempt == max_attempts:
            markers.setdefault(escalation_id, {
                "registry_version": registry.REGISTRY_VERSION,
                "action": action,
                "session_id": session_id,
                "generation": generation,
                "attempt": resolved_attempt,
                "status": "escalated",
                "created_at": timestamp,
            })

    registry.locked_registry_document_update(registry_path, _finish)
    if final_status == "failed" and resolved_attempt == max_attempts:
        return {
            "status": "escalated",
            "action_id": escalation_id,
            "attempt": resolved_attempt,
        }
    return {"status": final_status, "action_id": action_id, "attempt": resolved_attempt}


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
