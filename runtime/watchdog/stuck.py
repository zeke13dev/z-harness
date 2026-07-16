"""Stuck-session detection + nudge escalation for the session-watchdog daemon.

Purpose (T011, criterion #4): given one session record, decide whether this
poll cycle should leave it alone, send a plain-text nudge, or escalate to a
Discord alert — and perform whichever action was decided.

Public surface:
- ``evaluate_stuck`` — the entry point. Applies the D1 short-circuit binding
  obligation (a ``needs_input``/``awaiting_children`` session is never
  nudged), then the idle-time + ``nudge_max`` decision, dispatching the
  chosen action itself and returning the (possibly updated) record alongside
  the action taken.

Design decisions:
- D1 short-circuit binding obligation: the ``needs_input`` /
  ``awaiting_children`` skip lives HERE, at the module level, not in any
  caller — every caller of this module automatically inherits "a
  needs_input session is never nudged" and cannot forget to check it
  (INTENT criterion #4).
- Dependency-injection seam discipline (mirrors T005's ``HostAdapter`` seam
  and T007's ``judge.py`` stance): ``adapter``, the actuator submit
  function, the Discord alert function, and the clock (``now``) are all
  caller-supplied. This module never resolves ``watchdog.stuck_after_s`` /
  ``watchdog.nudge_max`` itself (STYLE.md:P-004) — the poll loop resolves
  both knobs once and passes them in — and never captures a pane itself;
  the caller supplies the already-captured ``pane_text`` (mirrors
  ``adapters/base.py``'s "adapters are host-mechanics-only" stance: this
  module is escalation-policy-only).
- Persistence stays caller-side (mirrors ``judge.py``/``notify.py``): this
  module returns the updated record (``nudge_count`` incremented,
  ``last_nudge_at`` stamped) but never calls
  ``registry.write_registry`` itself — the poll loop owns persisting the
  registry after every session's cycle.
- A nudge is gated on ``adapter.injection_ready(pane_text)``: submitting
  text into a pane that isn't ready to receive it (e.g. mid bracketed-paste,
  or displaying an unrelated transient state) risks corrupting the session's
  input rather than nudging it, so a not-ready pane is treated as "do
  nothing this cycle" rather than forcing the submit or silently
  incrementing ``nudge_count`` for a nudge that was never actually sent.
- The Discord escalation reuses ``notify.escalation_action`` (already the
  frozen nudge/alert boundary decision from T006) rather than
  re-implementing the ``nudge_count >= nudge_max`` comparison here — one
  source of truth for the escalation boundary.
- "Exactly one Discord alert" persisted marker: the frozen T003 registry
  schema (``SCHEMA_VERSION=1``) has no dedicated "escalated" field, and this
  module must not widen it. Instead the alert fires exactly once, at the
  ``nudge_count == nudge_max`` crossing, and the returned record's
  ``nudge_count`` is bumped to ``nudge_max + 1`` as the persisted "already
  escalated" marker — the poll loop writes this back to the registry, so the
  *next* poll cycle sees ``nudge_count > nudge_max`` and skips rather than
  re-alerting. This reuses the existing ``nudge_count`` field rather than
  adding a new one (STYLE.md/D-frozen-schema discipline).

Non-scope (the poll loop owns these — deliberately absent here): resolving
``watchdog.stuck_after_s`` / ``watchdog.nudge_max`` from config, capturing
the pane text, persisting the returned record via
``registry.write_registry``, and deciding when a session transitions into
(or out of) the ``stuck`` lifecycle state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from runtime.watchdog import notify
from runtime.watchdog import tmux_actuator
from runtime.watchdog.adapters.base import HostAdapter

_SKIP_STATES = frozenset({"needs_input", "awaiting_children"})
"""States the D1 short-circuit binding obligation exempts from nudging."""

DEFAULT_NUDGE_TEXT = tmux_actuator.NUDGE_TEXT
"""Plain-text nudge submitted via ``tmux_actuator.submit_text`` when a
session is stuck and below ``nudge_max``."""


def _parse_iso(ts: str) -> datetime:
    """Parse an ``registry.py``-style ``YYYY-MM-DDTHH:MM:SSZ`` timestamp.

    Raises:
        ValueError: if ``ts`` is not a well-formed ISO-8601 UTC timestamp —
            a malformed ``last_seen`` is a real data problem, not a runtime
            condition to silently degrade from.
    """
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def evaluate_stuck(
    record: dict,
    now: datetime,
    *,
    pane_text: str,
    adapter: HostAdapter,
    stuck_after_s: int,
    nudge_max: int,
    submit_fn: Callable[..., None] = tmux_actuator.submit_text,
    alert_fn: Callable[..., bool] = notify.send_discord_alert,
    nudge_text: str = DEFAULT_NUDGE_TEXT,
) -> dict:
    """Decide and perform this cycle's stuck-detection action for ``record``.

    Args:
        record: The session record (``registry.py`` schema); read-only —
            this function returns a new dict rather than mutating in place.
        now: The current time (caller-supplied clock, for deterministic
            tests).
        pane_text: The session's already-captured tmux pane text.
        adapter: The session's ``HostAdapter`` (used for
            ``injection_ready``).
        stuck_after_s: The resolved ``watchdog.stuck_after_s`` idle-time
            threshold, in seconds.
        nudge_max: The resolved ``watchdog.nudge_max`` unanswered-nudge cap.
        submit_fn: The race-safe text submitter; defaults to
            ``tmux_actuator.submit_text`` (injected so tests never touch a
            real tmux pane).
        alert_fn: The Discord alert sender; defaults to
            ``notify.send_discord_alert`` (injected so tests never hit a
            real webhook).
        nudge_text: The plain-text nudge to submit. Defaults to
            ``DEFAULT_NUDGE_TEXT``.

    Returns:
        ``{"action": "skip" | "nudge" | "nudge_failed" | "paused" |
        "escalated" | "discord_alert", "record": dict}``.
        ``action`` is:
        - ``"skip"`` — ``record["state"]`` is ``needs_input`` or
          ``awaiting_children`` (D1), the session is not idle *strictly past*
          ``stuck_after_s`` (idle time exactly equal to the threshold is not
          yet stuck), the pane is not ``injection_ready`` this cycle, or this
          stuck episode was already escalated in a prior poll cycle
          (``nudge_count > nudge_max``); ``record`` is returned unchanged.
        - ``"nudge"`` — the session is idle past ``stuck_after_s``,
          ``nudge_count < nudge_max``, and the pane accepted the submit;
          ``record`` is returned with ``nudge_count`` incremented by one and
          ``last_nudge_at`` stamped to ``now``.
        - ``"nudge_failed"`` — a definite delivery failure consumed the
          bounded attempt; ``nudge_count`` and ``last_nudge_at`` advance so a
          later poll cannot reuse the same durable attempt marker.
        - ``"paused"`` / ``"escalated"`` — the lifecycle dispatcher could
          not report explicit completion or failure; the record is unchanged.
        - ``"discord_alert"`` — the session is idle past ``stuck_after_s``
          and ``nudge_count == nudge_max`` (the first cycle to reach the
          cap); exactly one Discord alert is dispatched via ``alert_fn`` and
          ``record`` is returned with ``nudge_count`` bumped to
          ``nudge_max + 1`` — the persisted "already escalated" marker that
          makes every subsequent poll cycle skip instead of re-alerting.
    """
    if record["state"] in _SKIP_STATES:
        return {"action": "skip", "record": record}

    idle_s = (now - _parse_iso(record["last_seen"])).total_seconds()
    if idle_s <= stuck_after_s:
        return {"action": "skip", "record": record}

    nudge_count = record["nudge_count"]

    if nudge_count > nudge_max:
        # Already escalated in a prior poll cycle — the nudge_count >
        # nudge_max marker set below. Do not dispatch a second alert.
        return {"action": "skip", "record": record}

    decision = notify.escalation_action(nudge_count, nudge_max)

    if decision == "discord_alert":
        session_label = record.get("tmux_target", record.get("session_id", ""))
        alert_status = alert_fn(
            f"stuck session: {session_label}",
            f"no response after {nudge_max} nudge(s); idle {int(idle_s)}s.",
        )
        if alert_status in {"paused", "escalated"}:
            return {"action": alert_status, "record": record}
        updated = dict(record)
        updated["nudge_count"] = nudge_count + 1
        return {"action": "discord_alert", "record": updated}

    # decision == "nudge"
    if not adapter.injection_ready(pane_text):
        return {"action": "skip", "record": record}

    delivered = submit_fn(record["tmux_target"], nudge_text)
    if delivered in {"paused", "escalated"}:
        return {"action": delivered, "record": record}
    if delivered is False or delivered == "failed":
        updated = dict(record)
        updated["nudge_count"] = nudge_count + 1
        updated["last_nudge_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"action": "nudge_failed", "record": updated}
    updated = dict(record)
    updated["nudge_count"] = nudge_count + 1
    updated["last_nudge_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"action": "nudge", "record": updated}
