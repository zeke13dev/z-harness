"""Reconciliation: child-terminal + startup orphan detection for the
session-watchdog daemon.

Purpose (T014, criteria #7/#8): given the daemon's in-memory ``sessions.json``
records, detect two kinds of state drift a live poll loop cannot otherwise
notice on its own:

- ``reconcile_children`` — a fanout child (see ``fanout.py``, T013) whose tmux
  pane was killed out-of-band never tells the daemon it died; this function
  marks such a child ``failed`` and, once every child of a fanout origin has
  reached a terminal state, hands the caller exactly one reconciliation-nudge
  payload plus a Discord alert for any failed child (criterion #7).
- ``startup_reconcile`` — a daemon restart may find records whose tmux target
  no longer exists (the host process/pane died while the daemon was down);
  this function marks each such record ``orphaned`` exactly once, alerting via
  Discord, and never auto-adopts it back into a lifecycle state (criterion
  #8). Reusing ``registry.acquire_single_instance_lock``'s existing stale-pid
  cleanup for the daemon lock is a caller (T015 ``daemon.py``) concern — no
  new lock logic is introduced in this module.

Design decisions:
- Exactly-once semantics for both functions fall out of ``registry.py``'s own
  frozen state graph rather than a new persisted marker: ``TERMINAL_STATES``
  have no outgoing transitions (T003), so a record already ``failed`` /
  ``orphaned`` / ``done`` is skipped before any tmux check or alert is even
  attempted — a second call over the same terminal record is a guaranteed
  no-op, never a duplicate transition or alert.
- The reconciliation-nudge payload's own "fire once" gate is the origin
  record's ``state``: ``reconcile_children`` only builds and returns the
  payload when ``origin_record["state"] == "awaiting_children"`` AND every
  child has reached a terminal state. Per ``registry.py``'s
  ``VALID_TRANSITIONS``, ``awaiting_children`` can move to ``running`` /
  ``done`` / ``failed`` / ``orphaned`` but never back to
  ``awaiting_children`` — so once the caller (the level-2 poll loop) acts on
  a returned payload and transitions the origin out of ``awaiting_children``,
  a later call for the same origin naturally stops returning a payload even
  if invoked again. This is the "derive a natural once-marker from state"
  option (documented alternative to a bare caller-discipline contract) and is
  the chosen contract for this module.
- Dependency-injection seam discipline (mirrors ``stuck.py``/``needs_input.py``):
  ``has_session``, ``format_payload``, ``send_alerts``, and ``alert_fn`` are
  all caller-supplied, defaulting to the real ``tmux_actuator``/``notify``
  implementations, so tests never touch a real tmux pane or Discord webhook.
- A hung tmux liveness check (``tmux_actuator.TmuxTimeoutError``) is caught
  per-record and skipped rather than propagated (STYLE.md:EH-002 — a named
  exception only): the acceptance criterion requires evaluating every child
  "without... blocking evaluation of the remaining children", so one stuck
  ``has_session`` call must not abort the whole reconciliation pass. The
  affected record is simply retried on the next poll/startup cycle.
- Neither function persists anything (mirrors ``fanout.py``'s
  ``spawn_children``/``run_fanout`` split): both return updated in-memory
  mappings for the caller to merge and flush via
  ``registry.write_registry`` — write_registry stays caller-side.

Non-scope (later levels own these — deliberately absent here): transitioning
the origin record itself out of ``awaiting_children`` after consuming the
returned payload (level-2 poll loop concern), and any new daemon
single-instance lock logic (T015 ``daemon.py`` calls
``registry.acquire_single_instance_lock``/``release_single_instance_lock``
around a ``startup_reconcile`` call; this module does not touch the lock).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from runtime.watchdog import notify, registry, tmux_actuator


def _format_orphaned_message(record: Mapping[str, object]) -> tuple[str, str]:
    """Build the ``(title, body)`` Discord alert for one newly orphaned record.

    Args:
        record: The session record just transitioned to ``orphaned``.

    Returns:
        A ``(title, body)`` pair suitable for ``notify.send_discord_alert``.
    """
    title = f"orphaned: {record.get('slug', '')}"
    body = (
        f"session_id={record.get('session_id')} "
        f"tmux_target={record.get('tmux_target')}"
    )
    return title, body


def reconcile_children(
    origin_record: Mapping[str, object],
    records: Mapping[str, dict],
    *,
    has_session: Callable[..., bool] = tmux_actuator.has_session,
    timeout: float = tmux_actuator.DEFAULT_TIMEOUT_S,
    format_payload: Callable[[str, Sequence[Mapping[str, object]]], dict] = (
        notify.format_reconciliation_payload
    ),
    send_alerts: Callable[..., int] = notify.send_reconciliation_alerts,
    registry_path: Path | str | None = None,
    lifecycle_notify: Callable[..., notify.DeliveryResult] = (
        notify.deliver_lifecycle_notification
    ),
    now: str | None = None,
) -> dict:
    """Reconcile a fanout origin's children against live tmux state.

    For each child listed in ``origin_record["children"]``, checks whether its
    ``tmux_target`` is still a live tmux session (``has_session``). A child
    whose target is gone is marked ``failed`` via ``registry.transition``; a
    child already in a terminal state (``done``/``failed``/``orphaned``) is
    left untouched (no tmux check, no re-transition — see module docstring).
    A single child's evaluation failing (a hung liveness check, or a
    concurrently-raced illegal transition) never blocks evaluating the
    remaining children.

    Once every child has reached a terminal state AND ``origin_record``'s own
    ``state`` is ``"awaiting_children"``, builds exactly one
    reconciliation-nudge payload (``format_payload``, T006) listing each
    child's terminal status, and — only when at least one child is
    ``failed`` — dispatches exactly one Discord alert batch for those failed
    children (``send_alerts``).

    Args:
        origin_record: The fanout origin's session record (not mutated).
        records: The full ``session_id`` -> record mapping (not mutated).
        has_session: Injected ``tmux_actuator.has_session``-shaped callable.
        timeout: Explicit subprocess timeout passed to every ``has_session``
            call.
        format_payload: Injected ``notify.format_reconciliation_payload``.
        send_alerts: Injected ``notify.send_reconciliation_alerts``.
        now: ISO timestamp override (deterministic tests).

    Returns:
        ``{"records": records, "payload": payload}`` — ``records`` is a copy
        of the input mapping with any newly-failed children updated in
        place; ``payload`` is the reconciliation-nudge payload (see
        ``notify.format_reconciliation_payload``) once every child is
        terminal and the origin is ``awaiting_children``, else ``None``.
    """
    updated: dict[str, dict] = dict(records)
    child_ids = list(origin_record.get("children", []))
    observed_at = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for child_id in child_ids:
        child = updated.get(child_id)
        if child is None:
            continue  # unknown child id — nothing to reconcile against
        if registry.is_terminal(child.get("state")):
            if registry_path is not None:
                outcome_id = registry.child_outcome_id(
                    str(child_id), registry.child_generation(child)
                )
                claimed = registry.claim_child_outcome_notification(
                    registry_path, outcome_id, now=observed_at
                )
                if claimed is not None:
                    result = lifecycle_notify(notify.child_outcome_notification(claimed))
                    registry.finish_child_outcome_notification(
                        registry_path,
                        outcome_id,
                        status=result.status,
                        attempt=int(claimed["notification_attempts"]),
                    )
            continue  # already terminal: no re-check, no re-transition

        try:
            alive: bool | None = has_session(child["tmux_target"], timeout=timeout)
        except tmux_actuator.TmuxTimeoutError:
            alive = None
        if alive:
            continue

        if registry_path is not None:
            outcome = registry.reap_child_lease(
                registry_path,
                child_id=str(child_id),
                generation=registry.child_generation(child),
                reachable=alive,
                observed_at=observed_at,
            )
            if outcome is not None:
                claimed = registry.claim_child_outcome_notification(
                    registry_path, str(outcome["outcome_id"]), now=observed_at
                )
                if claimed is not None:
                    # The winner is durable before this fail-open effect.
                    result = lifecycle_notify(notify.child_outcome_notification(claimed))
                    registry.finish_child_outcome_notification(
                        registry_path,
                        str(outcome["outcome_id"]),
                        status=result.status,
                        attempt=int(claimed["notification_attempts"]),
                    )
            updated = registry.read_registry(registry_path)
            continue

        if alive is None:
            # Legacy pure-call compatibility has no durable lease authority;
            # leave ambiguous checks untouched for a later persisted pass.
            continue

        try:
            updated[child_id] = registry.transition(child, "failed", now=observed_at)
        except registry.InvalidTransitionError:
            # Raced with a concurrent transition since the read above — skip
            # rather than crash the whole reconciliation pass.
            continue

    all_terminal = bool(child_ids) and all(
        cid in updated and registry.is_terminal(updated[cid].get("state"))
        for cid in child_ids
    )

    payload: dict | None = None
    if all_terminal and origin_record.get("state") == "awaiting_children":
        children_records = [updated[cid] for cid in child_ids]
        payload = format_payload(str(origin_record.get("slug", "")), children_records)
        if payload.get("failed_entries"):
            send_alerts(payload)

    return {"records": updated, "payload": payload}


def startup_reconcile(
    records: Mapping[str, dict],
    *,
    has_session: Callable[..., bool] = tmux_actuator.has_session,
    timeout: float = tmux_actuator.DEFAULT_TIMEOUT_S,
    alert_fn: Callable[..., bool] = notify.send_discord_alert,
    now: str | None = None,
) -> dict[str, dict]:
    """Mark records whose tmux target no longer exists as ``orphaned``.

    Every non-terminal record whose ``tmux_target`` fails
    ``has_session`` is transitioned to ``orphaned`` (``registry.transition``)
    and alerted exactly once via ``alert_fn``; it is never auto-adopted back
    into a lifecycle state (criterion #8: "never auto-adopting it back into a
    lifecycle state"). A record already terminal (including one this same
    function orphaned on a prior call) is skipped outright — no tmux check,
    no re-alert — which is what makes two consecutive calls over the same
    records produce exactly one alert per dead record (see module docstring).
    A child record freshly spawned by fanout with ``transcript_path == ""``
    (T013) is handled the same as any other record: this function never reads
    or assumes a non-empty ``transcript_path``.

    Args:
        records: The full ``session_id`` -> record mapping (not mutated).
        has_session: Injected ``tmux_actuator.has_session``-shaped callable.
        timeout: Explicit subprocess timeout passed to every ``has_session``
            call.
        alert_fn: Injected ``notify.send_discord_alert``-shaped callable.
        now: ISO timestamp override (deterministic tests).

    Returns:
        A copy of ``records`` with any newly-dead record transitioned to
        ``orphaned``. Callers persist the result via
        ``registry.write_registry``.
    """
    updated: dict[str, dict] = dict(records)

    for session_id, record in records.items():
        if registry.is_terminal(record.get("state")):
            continue  # already terminal — includes a prior orphaned mark
        if record.get("parent_id") is not None:
            # Child disappearance is resolved only by the durable lease/grace
            # path above so startup cannot bypass outcome provenance or grace.
            continue

        try:
            alive = has_session(record.get("tmux_target", ""), timeout=timeout)
        except tmux_actuator.TmuxTimeoutError:
            continue  # a hung check must not block the remaining records
        if alive:
            continue

        try:
            orphaned = registry.transition(record, "orphaned", now=now)
        except registry.InvalidTransitionError:
            continue
        updated[session_id] = orphaned
        alert_fn(*_format_orphaned_message(orphaned))

    return updated
