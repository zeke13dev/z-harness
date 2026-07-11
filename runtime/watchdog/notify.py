"""Discord notify + digest-dedup primitives for the session-watchdog daemon.

Purpose (T006, criteria #4/#5/#7): wrap ``scripts/notify-discord.sh``'s webhook
path with the three composable primitives the level-1 poll loop needs to
satisfy the needs_input / stuck-nudge-escalation / fanout-reconciliation
acceptance behaviors, without reimplementing any of the script's own webhook,
truncation, or timeout logic:

- ``needs_input_digest`` — a stable digest over a needs_input question+options
  payload, so the poll loop can dedup repeated polls of the same unanswered
  prompt against a persisted last-seen digest (criterion #5: "exactly one
  Discord brief... digest-deduped across polls").
- ``escalation_action`` — given a session's ``nudge_count`` and the resolved
  ``watchdog.nudge_max``, decides whether the next unanswered-stuck cycle
  should be a plain-text ``"nudge"`` or a ``"discord_alert"`` (criterion #4).
- ``format_reconciliation_payload`` — one entry per fanout child plus the
  subset that are ``failed`` (each of which also needs a Discord alert,
  criterion #7).
- ``send_discord_alert`` — the actual wrapper around
  ``scripts/notify-discord.sh``; every other ``send_*`` helper in this module
  funnels through it so the subprocess contract is enforced in exactly one
  place.

Design decisions:
- ``escalation_action`` and ``format_reconciliation_payload`` take their
  thresholds/session data as caller-supplied arguments rather than resolving
  ``watchdog.nudge_max`` internally via ``registry.get_config_int`` — mirrors
  the adapter seam's stance (``adapters/base.py``: "adapters are
  host-mechanics-only and never shell out to ``scripts/config.py``
  themselves"; the poll loop resolves the knob once and passes it in). This
  keeps ``notify.py`` a pure, subprocess-thin module aside from the one
  intentional subprocess call in ``send_discord_alert`` (recorded in
  LEDGER.md).
- ``send_discord_alert`` mirrors ``notify-discord.sh``'s own fail-open
  contract instead of translating it into a raise: the script itself exits 0
  on a successful send OR when Discord is disabled (no webhook configured)
  and exits 1 only on an actual send failure. This wrapper is therefore
  best-effort (STYLE.md:EH-001) and returns a bool rather than raising —
  a lost notification must never crash the daemon's poll loop.
- Menu options are treated as an ordered sequence of opaque strings (the
  extracted label text); digesting preserves their order since option order
  is part of what a human is choosing between, so a payload with reordered
  options is intentionally treated as a materially different prompt.

Non-scope (level 1 owns these — deliberately absent here): persisting a
session's last-sent needs_input digest and nudge_count in ``sessions.json``,
deciding *when* a poll cycle is stuck enough to call ``escalation_action``,
and the plain-text nudge delivery itself (a tmux ``send_keys`` action, see
``tmux_actuator.py``) — this module ships the Discord-facing primitives only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

# Repo root: notify.py -> watchdog -> runtime -> <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]

NOTIFY_SCRIPT = _REPO_ROOT / "scripts" / "notify-discord.sh"
"""Default path to the wrapped webhook script (``notify-discord.sh <title> <body>``)."""

DEFAULT_TIMEOUT_S = 10.0
"""Default subprocess timeout (seconds) for the ``notify-discord.sh`` call —
generous headroom over the script's own 3s curl ``--max-time``."""


# ── (a) needs_input digest-dedup ─────────────────────────────────────────────

def needs_input_digest(question: str, options: Sequence[str] = ()) -> str:
    """Return a stable digest key for a needs_input question+options payload.

    Identical ``(question, options)`` pairs always produce the same digest;
    any change to either — including a reordering of ``options`` — produces a
    different one. The poll loop compares this against a session's persisted
    last-sent digest to decide whether the current needs_input prompt has
    already been alerted (criterion #5's dedup-across-polls requirement).

    Args:
        question: The extracted prompt/question text.
        options: The extracted menu option labels, in on-screen order.

    Returns:
        A 64-character hex SHA-256 digest.
    """
    canonical = json.dumps(
        {"question": question, "options": list(options)}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def format_needs_input_message(
    session_label: str, question: str, options: Sequence[str] = ()
) -> tuple[str, str]:
    """Build the ``(title, body)`` Discord message naming ``session_label``.

    Args:
        session_label: Human-identifying label for the session (by
            convention its tmux target, e.g. ``zw-slug-abcd1234``).
        question: The extracted prompt/question text.
        options: The extracted menu option labels, in on-screen order.

    Returns:
        A ``(title, body)`` pair suitable for ``send_discord_alert``.
    """
    title = f"needs_input: {session_label}"
    if options:
        rendered_options = "\n".join(f"- {option}" for option in options)
        body = f"{question}\n\nOptions:\n{rendered_options}"
    else:
        body = question
    return title, body


def send_needs_input_alert(
    session_label: str,
    question: str,
    options: Sequence[str] = (),
    *,
    script_path: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> bool:
    """Format and send the needs_input Discord brief for one session.

    Best-effort (STYLE.md:EH-001): see ``send_discord_alert``. Callers are
    responsible for only invoking this once per distinct ``needs_input_digest``
    (the dedup decision itself lives in the level-1 poll loop, not here).

    Returns:
        ``True`` if ``notify-discord.sh`` exited 0 (sent, or Discord is
        disabled); ``False`` on a genuine send failure.
    """
    title, body = format_needs_input_message(session_label, question, options)
    return send_discord_alert(title, body, script_path=script_path, timeout=timeout)


# ── (b) nudge-count escalation ───────────────────────────────────────────────

def escalation_action(nudge_count: int, nudge_max: int) -> str:
    """Return ``"nudge"`` or ``"discord_alert"`` for a stuck session's next step.

    Hard-fail (STYLE.md:EH-001): a session below ``nudge_max`` unanswered
    nudges gets another plain-text ``"nudge"``; at or above ``nudge_max`` it
    escalates to exactly one ``"discord_alert"`` (criterion #4).

    Args:
        nudge_count: The number of unanswered nudges already sent this stuck
            episode.
        nudge_max: The resolved ``watchdog.nudge_max`` config value.

    Returns:
        ``"nudge"`` if ``nudge_count < nudge_max``, else ``"discord_alert"``.

    Raises:
        ValueError: if ``nudge_count`` is negative or ``nudge_max`` is not a
            positive int — both indicate a caller bug, not a runtime
            condition to degrade gracefully from.
    """
    if nudge_max < 1:
        raise ValueError(f"nudge_max must be >= 1, got {nudge_max!r}")
    if nudge_count < 0:
        raise ValueError(f"nudge_count must be >= 0, got {nudge_count!r}")
    return "nudge" if nudge_count < nudge_max else "discord_alert"


# ── (c) fanout reconciliation ─────────────────────────────────────────────────

def format_reconciliation_payload(
    root_slug: str, children: Sequence[Mapping[str, object]]
) -> dict:
    """Build the reconciliation payload: one entry per fanout child.

    Args:
        root_slug: The plan slug the fanout ran against.
        children: One mapping per fanout child session record (each carrying
            at least ``session_id``, ``tmux_target``, and terminal ``state``
            — see ``registry.py``'s session record schema).

    Returns:
        A dict with ``root_slug``, ``entries`` (one per child, each flagged
        ``failed`` when its ``state`` is ``"failed"``), and ``failed_entries``
        (the subset needing an additional Discord alert, criterion #7).
    """
    entries: list[dict] = []
    failed_entries: list[dict] = []
    for child in children:
        failed = child.get("state") == "failed"
        entry = {
            "session_id": child.get("session_id"),
            "tmux_target": child.get("tmux_target"),
            "state": child.get("state"),
            "failed": failed,
        }
        entries.append(entry)
        if failed:
            failed_entries.append(entry)
    return {
        "root_slug": root_slug,
        "entries": entries,
        "failed_entries": failed_entries,
    }


def format_failed_child_message(root_slug: str, entry: Mapping[str, object]) -> tuple[str, str]:
    """Build the ``(title, body)`` Discord alert for one failed fanout child.

    Args:
        root_slug: The plan slug the fanout ran against.
        entry: One ``failed_entries`` item from ``format_reconciliation_payload``.

    Returns:
        A ``(title, body)`` pair suitable for ``send_discord_alert``.
    """
    title = f"fanout child failed: {root_slug}"
    body = (
        f"session_id={entry.get('session_id')} "
        f"tmux_target={entry.get('tmux_target')} state={entry.get('state')}"
    )
    return title, body


def send_reconciliation_alerts(
    payload: Mapping[str, object],
    *,
    script_path: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> int:
    """Send one Discord alert per ``failed_entries`` item in ``payload``.

    Best-effort (STYLE.md:EH-001): a lost alert for one failed child does not
    abort attempting the rest.

    Args:
        payload: A dict shaped like ``format_reconciliation_payload``'s return.
        script_path: Override for the wrapped script (tests only).
        timeout: Subprocess timeout in seconds, per alert.

    Returns:
        The count of alerts that ``send_discord_alert`` reported as sent.
    """
    root_slug = str(payload.get("root_slug", ""))
    sent = 0
    for entry in payload.get("failed_entries", []):
        title, body = format_failed_child_message(root_slug, entry)
        if send_discord_alert(title, body, script_path=script_path, timeout=timeout):
            sent += 1
    return sent


# ── notify-discord.sh wrapper ─────────────────────────────────────────────────

def send_discord_alert(
    title: str,
    body: str,
    *,
    script_path: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> bool:
    """Send one Discord notification via ``scripts/notify-discord.sh``.

    Best-effort (STYLE.md:EH-001): mirrors the wrapped script's own fail-open
    contract rather than translating it into a raise. A hung or missing
    script (``subprocess.TimeoutExpired``, ``OSError`` — e.g. bash itself is
    absent) is caught and reported as ``False``; the daemon's poll loop must
    keep running even when a single notification is lost.

    Args:
        title: Notification title (script truncates to 256 chars).
        body: Notification body (script truncates to 4096 chars).
        script_path: Override for the wrapped script (tests only); defaults
            to ``NOTIFY_SCRIPT``.
        timeout: Subprocess timeout in seconds.

    Returns:
        ``True`` if the script exited 0 (message sent, or Discord is
        disabled because no webhook is configured); ``False`` on a genuine
        send failure, a timeout, or a launch error.
    """
    script = Path(script_path) if script_path is not None else NOTIFY_SCRIPT
    try:
        proc = subprocess.run(
            ["bash", str(script), title, body],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0
