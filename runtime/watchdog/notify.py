"""Fail-open Discord notification primitives for the session watchdog.

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
- ``lifecycle_notification`` / ``deliver_lifecycle_notification`` — stable
  event envelopes and observable delivery outcomes for daemon, intervention,
  rollover, child-outcome, join, and coordinator-wake events (T005,
  acceptance criterion #9).

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
- Delivery is fail-open (STYLE.md:EH-001): lifecycle outcomes distinguish
  delivered, disabled, and failed without raising. Existing notification
  helpers retain their documented boolean return contracts; structured
  ``DeliveryResult`` values are confined to the lifecycle API.
- Daemon, intervention, rollover, and join notifications are best-effort/
  at-most-once. Child-outcome and coordinator-wake notifications are retryable with
  the same stable event ID; exactly-once logical wake handling remains the
  coordinator acknowledgement contract, not a Discord guarantee.
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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from runtime.watchdog import registry

# Repo root: notify.py -> watchdog -> runtime -> <repo root>.
_REPO_ROOT = Path(__file__).resolve().parents[2]

NOTIFY_SCRIPT = _REPO_ROOT / "scripts" / "notify-discord.sh"
"""Default path to the wrapped webhook script (``notify-discord.sh <title> <body>``)."""

DEFAULT_TIMEOUT_S = 10.0
"""Default subprocess timeout (seconds) for the ``notify-discord.sh`` call —
generous headroom over the script's own 3s curl ``--max-time``."""

LIFECYCLE_EVENT_KINDS = frozenset(
    {"daemon", "intervention", "rollover", "child_outcome", "join", "coordinator_wake"}
)
"""Supported lifecycle notification families."""

BEST_EFFORT_AT_MOST_ONCE = "best_effort_at_most_once"
RETRYABLE = "retryable"
CONFIG_SCRIPT = _REPO_ROOT / "scripts" / "config.py"


@dataclass(frozen=True)
class LifecycleNotification:
    """One deterministic lifecycle notification envelope.

    Attributes:
        event_id: Stable ID derived only from ``kind`` and ``stable_key``.
        kind: One member of ``LIFECYCLE_EVENT_KINDS``.
        stable_key: Canonical logical identity fields supplied by the caller.
        title: Discord title; deliberately excluded from event identity.
        body: Discord body; deliberately excluded from event identity.
        delivery_class: ``retryable`` for child outcomes and coordinator
            wakes, otherwise ``best_effort_at_most_once``.
    """

    event_id: str
    kind: str
    stable_key: tuple[tuple[str, str], ...]
    title: str
    body: str
    delivery_class: str


@dataclass(frozen=True)
class DeliveryResult:
    """Observable fail-open result of one transport attempt.

    ``status`` is ``delivered``, ``disabled``, or ``failed``. Converting the
    result to ``bool`` returns true only for ``delivered``; no status raises or
    directs the caller to undo a lifecycle transition.
    """

    status: str
    event_id: str | None = None
    delivery_class: str = BEST_EFFORT_AT_MOST_ONCE

    def __bool__(self) -> bool:
        """Return whether Discord confirmed delivery; never raise."""
        return self.status == "delivered"


# ── lifecycle event identity and delivery ───────────────────────────────────

def lifecycle_notification(
    kind: str,
    stable_key: Mapping[str, str],
    title: str,
    body: str,
) -> LifecycleNotification:
    """Build a lifecycle notification with a deterministic event ID.

    Hard-fail: an unsupported kind or empty identity is a caller contract bug,
    not a transport condition. Presentation text is excluded from the hash so
    a retry of the same logical event retains its ID.

    Args:
        kind: Lifecycle family from ``LIFECYCLE_EVENT_KINDS``.
        stable_key: Non-empty logical identity fields, such as root ID plus
            daemon generation, outcome ID, join ID, or wake outbox ID.
        title: Human-facing Discord title.
        body: Human-facing Discord body.

    Returns:
        An immutable notification envelope.

    Raises:
        ValueError: If ``kind`` is unsupported or ``stable_key`` is empty.
    """
    if kind not in LIFECYCLE_EVENT_KINDS:
        raise ValueError(f"unsupported lifecycle notification kind: {kind!r}")
    if not stable_key:
        raise ValueError("stable_key must identify the logical lifecycle event")
    canonical_key = tuple(sorted((str(key), str(value)) for key, value in stable_key.items()))
    canonical = json.dumps(
        {"kind": kind, "stable_key": canonical_key},
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    delivery_class = (
        RETRYABLE
        if kind in {"child_outcome", "coordinator_wake"}
        else BEST_EFFORT_AT_MOST_ONCE
    )
    return LifecycleNotification(
        event_id=f"watchdog-notify:v1:{digest}",
        kind=kind,
        stable_key=canonical_key,
        title=title,
        body=body,
        delivery_class=delivery_class,
    )


def child_outcome_notification(
    outcome: Mapping[str, object],
) -> LifecycleNotification:
    """Render one durable child outcome as a stable fail-open notification.

    Args:
        outcome: Committed registry outcome carrying its stable ID and provenance.

    Returns:
        A retryable lifecycle envelope backed by the durable outcome record.
    """
    outcome_id = str(outcome["outcome_id"])
    return lifecycle_notification(
        "child_outcome",
        {"outcome_id": outcome_id},
        "watchdog child outcome",
        (
            f"child_id={outcome['child_id']} state={outcome['state']} "
            f"source={outcome['source']} outcome_id={outcome_id}"
        ),
    )


def join_notification(join: Mapping[str, object]) -> LifecycleNotification:
    """Render one stable sealed-group join notification.

    Args:
        join: Durable join record carrying ``join_id`` and ``group_id``.

    Returns:
        A best-effort notification keyed only by the stable join ID.
    """
    return lifecycle_notification(
        "join",
        {"join_id": str(join["join_id"])},
        "watchdog fanout join ready",
        f"group_id={join['group_id']} join_id={join['join_id']}",
    )


def coordinator_wake_notification(
    outbox: Mapping[str, object],
) -> LifecycleNotification:
    """Render one retryable stable coordinator-wake notification.

    Args:
        outbox: Durable wake outbox record.

    Returns:
        A retryable notification keyed only by the stable outbox ID.
    """
    return lifecycle_notification(
        "coordinator_wake",
        {"outbox_id": str(outbox["outbox_id"])},
        "watchdog coordinator wake",
        (
            f"session_id={outbox['coordinator_session_id']} "
            f"outbox_id={outbox['outbox_id']}"
        ),
    )


def coordinator_rollover_notification(rollover: Mapping[str, object]) -> LifecycleNotification:
    """Render the one stable, fail-open event for a logical rollover."""
    rollover_id = str(rollover["rollover_id"])
    return lifecycle_notification(
        "rollover",
        {"rollover_id": rollover_id},
        "watchdog coordinator rollover",
        (
            f"logical_coordinator_id={rollover['logical_coordinator_id']} "
            f"rollover_id={rollover_id} incarnation={rollover['to_incarnation']}"
        ),
    )


def deliver_pending_join_notifications(
    registry_path: str | Path,
    signals_path: str | Path,
    *,
    max_mb: int,
    deliver: Callable[[LifecycleNotification], DeliveryResult] | None = None,
) -> list[DeliveryResult]:
    """Deliver fail-open join and retryable coordinator-wake notifications.

    Args:
        registry_path: Authoritative registry path.
        signals_path: Append-only delivery telemetry path.
        max_mb: Signal-log rotation ceiling.
        deliver: Optional lifecycle transport override.

    Returns:
        Observable results for attempts made during this pass.
    """
    deliver = deliver or deliver_lifecycle_notification
    document = registry.read_registry_document(registry_path)
    candidates = [
        ("joins", join_id, join_notification(join))
        for join_id, join in document["joins"].items()
        if join.get("notification_status") == "pending"
    ]
    candidates.extend(
        ("outbox", outbox_id, coordinator_wake_notification(outbox))
        for outbox_id, outbox in document["outbox"].items()
        if outbox.get("state") == "pending"
        and outbox.get("notification_status") in {"pending", "failed", "disabled"}
    )
    results: list[DeliveryResult] = []
    for section, record_id, event in candidates:
        claimed = registry.claim_join_notification(registry_path, section, record_id)
        if claimed is None:
            continue
        result = deliver(event)
        registry.finish_join_notification(
            registry_path,
            section,
            record_id,
            status=result.status,
            attempt=int(claimed["notification_attempts"]),
        )
        registry.append_signal(
            signals_path,
            "lifecycle_notification_delivery",
            {
                "record_id": record_id,
                "event_id": event.event_id,
                "kind": event.kind,
                "delivery_class": result.delivery_class,
                "status": result.status,
            },
            max_mb=max_mb,
        )
        results.append(result)
    return results


def deliver_lifecycle_notification(
    event: LifecycleNotification,
    *,
    script_path: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport_enabled: bool | None = None,
) -> DeliveryResult:
    """Attempt one lifecycle delivery without controlling lifecycle state.

    Best-effort: disabled transports and delivery errors are returned as
    observable results and never raise. A ``retryable`` result authorizes a
    caller-managed later attempt with the same ``event_id``; this function
    does not retry or mutate an outbox itself.

    Args:
        event: Stable lifecycle notification envelope.
        script_path: Override for the wrapped script (tests only).
        timeout: Subprocess timeout in seconds.
        transport_enabled: Explicit transport state. ``False`` skips the
            subprocess and returns ``disabled``; ``None`` preserves the
            wrapped script's normal configuration path.

    Returns:
        Observable ``DeliveryResult`` with the event ID and classification.
    """
    result = _send_discord_alert_result(
        event.title,
        event.body,
        script_path=script_path,
        timeout=timeout,
        transport_enabled=transport_enabled,
    )
    return DeliveryResult(
        status=result.status,
        event_id=event.event_id,
        delivery_class=event.delivery_class,
    )


def claim_action_notification(
    registry_path: str | Path,
    action_id: str,
    event: LifecycleNotification,
) -> bool:
    """Durably claim one action-backed notification attempt.

    Best-effort/at-most-once events may be claimed only once. Retryable events
    may be reclaimed after ``failed`` or ``disabled`` delivery, always under
    the same action/event identity. The completed lifecycle action remains
    authoritative regardless of notification state.

    Args:
        registry_path: Authoritative watchdog registry path.
        action_id: Existing completed action-marker ID.
        event: Notification whose stable key names ``action_id``.

    Returns:
        True when this caller owns a delivery attempt, otherwise false.

    Raises:
        ValueError: If the action marker is absent or not completed.
        OSError: If the durable claim cannot be persisted.
    """
    claimed = False

    def _claim(document: dict[str, object]) -> None:
        nonlocal claimed
        marker = document["action_markers"].get(action_id)  # type: ignore[union-attr]
        if marker is None or marker.get("status") != "completed":
            raise ValueError(f"notification action is not completed: {action_id!r}")
        previous_event_id = marker.get("notification_event_id")
        if previous_event_id not in {None, event.event_id}:
            raise ValueError(f"notification identity conflict for action {action_id!r}")
        previous_status = marker.get("notification_status")
        if previous_event_id is not None and (
            event.delivery_class == BEST_EFFORT_AT_MOST_ONCE
            or previous_status == "delivered"
        ):
            return
        marker["notification_event_id"] = event.event_id
        marker["notification_delivery_class"] = event.delivery_class
        marker["notification_status"] = "pending"
        marker["notification_attempts"] = int(marker.get("notification_attempts", 0)) + 1
        claimed = True

    registry.locked_registry_document_update(registry_path, _claim)
    return claimed


def finish_action_notification(
    registry_path: str | Path,
    action_id: str,
    result: DeliveryResult,
) -> None:
    """Persist one observable delivery result without changing action state.

    Args:
        registry_path: Authoritative watchdog registry path.
        action_id: Existing completed action-marker ID.
        result: Fail-open transport result for the claimed event.

    Raises:
        ValueError: If the claim identity no longer matches ``result``.
        OSError: If the result cannot be persisted.
    """
    def _finish(document: dict[str, object]) -> None:
        marker = document["action_markers"].get(action_id)  # type: ignore[union-attr]
        if marker is None or marker.get("notification_event_id") != result.event_id:
            raise ValueError(f"notification claim is absent for action {action_id!r}")
        marker["notification_status"] = result.status

    registry.locked_registry_document_update(registry_path, _finish)


def log_lifecycle_delivery(
    signals_path: str | Path,
    event: LifecycleNotification,
    result: DeliveryResult,
    *,
    action_id: str,
    max_mb: int,
) -> None:
    """Append explicit fail-open delivery telemetry to the watchdog signal log.

    Args:
        signals_path: Internal watchdog signal-log path.
        event: Attempted stable lifecycle envelope.
        result: Observable transport outcome.
        action_id: Durable action marker backing the attempt.
        max_mb: Signal-log rotation ceiling.
    """
    registry.append_signal(
        signals_path,
        "lifecycle_notification_delivery",
        {
            "action_id": action_id,
            "event_id": event.event_id,
            "kind": event.kind,
            "delivery_class": result.delivery_class,
            "status": result.status,
        },
        max_mb=max_mb,
    )


def retry_pending_wake_notifications(
    registry_path: str | Path,
    signals_path: str | Path,
    *,
    max_mb: int,
    deliver: Callable[[LifecycleNotification], DeliveryResult] = (
        deliver_lifecycle_notification
    ),
) -> list[DeliveryResult]:
    """Retry durable failed/disabled coordinator-wake notification attempts.

    Pending attempts are also retried after daemon restart because ``pending``
    means delivery outcome was not durably recorded. Duplicate external sends
    are permitted for this retryable class; the stable event ID is unchanged.

    Args:
        registry_path: Authoritative watchdog registry path.
        signals_path: Internal watchdog signal-log path.
        max_mb: Signal-log rotation ceiling.
        deliver: Injected lifecycle transport for tests.

    Returns:
        Delivery results for attempts made in this pass.

    Raises:
        OSError: If durable retry state cannot be read or persisted.
    """
    document = registry.read_registry_document(registry_path)
    candidates = [
        (action_id, marker)
        for action_id, marker in document["action_markers"].items()
        if marker.get("action") == "coordinator_wake"
        and marker.get("notification_delivery_class") == RETRYABLE
        and marker.get("notification_status") in {"pending", "failed", "disabled"}
    ]
    results: list[DeliveryResult] = []
    for action_id, marker in candidates:
        event = lifecycle_notification(
            "coordinator_wake",
            {"action_id": action_id},
            "watchdog coordinator wake",
            f"session_id={marker['session_id']}",
        )
        if not claim_action_notification(registry_path, action_id, event):
            continue
        result = deliver(event)
        finish_action_notification(registry_path, action_id, result)
        log_lifecycle_delivery(
            signals_path, event, result, action_id=action_id, max_mb=max_mb
        )
        results.append(result)
    return results


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
        ``True`` when the wrapped script exits zero, otherwise ``False``.
        This legacy boolean contract deliberately does not expose lifecycle
        delivery metadata.
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
    transport_enabled: bool | None = None,
) -> bool:
    """Send one Discord notification via ``scripts/notify-discord.sh``.

    Best-effort (STYLE.md:EH-001): disabled transport, a non-zero exit, a hung
    script, or a launch error returns ``False`` rather than raising. The
    daemon's poll loop must keep running even when a notification is disabled
    or lost.

    Args:
        title: Notification title (script truncates to 256 chars).
        body: Notification body (script truncates to 4096 chars).
        script_path: Override for the wrapped script (tests only); defaults
            to ``NOTIFY_SCRIPT``.
        timeout: Subprocess timeout in seconds.
        transport_enabled: Explicit transport state. ``False`` returns
            ``False`` without launching the script; ``None`` preserves the
            legacy wrapped-script behavior, including its successful no-op
            when Discord is not configured.

    Returns:
        ``True`` only when the transport invocation exits zero. This public
        legacy helper remains boolean; lifecycle callers use the structured
        private result through ``deliver_lifecycle_notification``.
    """
    return bool(_send_discord_alert_result(
        title,
        body,
        script_path=script_path,
        timeout=timeout,
        # Preserve the legacy shell contract: absent Discord configuration is
        # a successful no-op for boolean callers. Only lifecycle delivery
        # resolves disabled configuration into structured observability.
        transport_enabled=True if transport_enabled is None else transport_enabled,
    ))


def _send_discord_alert_result(
    title: str,
    body: str,
    *,
    script_path: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT_S,
    transport_enabled: bool | None = None,
) -> DeliveryResult:
    """Return an observable result for one Discord transport attempt.

    Best-effort: configuration lookup and transport errors become ``failed``;
    an empty configured webhook becomes ``disabled``. The webhook value is
    inspected only for emptiness and is never logged or returned.

    A custom ``script_path`` is an explicit test/tooling transport and is
    treated as enabled unless ``transport_enabled`` is supplied. Production
    callers use the default script and therefore resolve real configuration
    before invocation, avoiding the shell script's ambiguous zero exit when
    Discord is disabled.

    Returns:
        ``DeliveryResult`` with ``delivered``, ``disabled``, or ``failed``.
    """
    if transport_enabled is False:
        return DeliveryResult(status="disabled")
    if transport_enabled is None and script_path is None:
        try:
            configured = subprocess.run(
                [sys.executable, str(CONFIG_SCRIPT), "get", "notify.discord_webhook_url"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            return DeliveryResult(status="failed")
        if configured.returncode != 0:
            return DeliveryResult(status="failed")
        if not configured.stdout.strip():
            return DeliveryResult(status="disabled")
    script = Path(script_path) if script_path is not None else NOTIFY_SCRIPT
    try:
        proc = subprocess.run(
            ["bash", str(script), title, body],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return DeliveryResult(status="failed")
    status = "delivered" if proc.returncode == 0 else "failed"
    return DeliveryResult(status=status)
