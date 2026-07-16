"""Per-session poll-cycle composition for the session-watchdog daemon.

Purpose (T016, criteria #2/#3/#4/#5/#7): compose the level-0/level-1 primitives
(``adapters.<host>``, ``handoff``, ``stuck``, ``needs_input``, ``reconcile``,
``tmux_actuator``, ``registry``) into a single per-session poll cycle. Given one
already-captured ``pane_text`` and one session record, ``poll_session`` runs
exactly one pass of the daemon's four automated behaviors and persists the
result to ``sessions.json``. The daemon poll loop (a later concern) captures the
pane, resolves the ``watchdog.*`` knobs once, and calls this per watched
session.

The cycle is a prioritized cascade — the first arm that acts decisively persists
and returns, so a session is never (e.g.) handed off *and* nudged in the same
cycle. Order and gates:

1. **Context read (always)** — ``adapter.read_context`` advances and persists
   ``transcript_offset``. ``last_seen`` is stamped ONLY when new transcript
   bytes were consumed (``new_offset`` advanced), because ``stuck.evaluate_stuck``
   measures idle time as ``now - last_seen`` and criterion #4 defines stuck as
   "no new transcript events for ``stuck_after_s``" — stamping ``last_seen``
   every poll unconditionally would make a busy-looping-silent session never
   look stuck.
2. **Fanout-origin lifecycle** (a record with a non-empty ``children`` list) —
   a ``registered``/``running`` origin transitions to ``awaiting_children``; an
   ``awaiting_children`` origin runs ``reconcile.reconcile_children`` (criterion
   #7). Origins never fall through to the handoff/stuck/needs_input arms: their
   job after fanout is to wait for and reconcile children.
3. **Context-threshold handoff** (criteria #2/#3) — when
   ``pct_used >= threshold_pct`` AND the record is ``registered``/``running`` AND
   ``adapter.injection_ready(pane_text)``, drive ``handoff.maybe_trigger_handoff``
   and then actuate the real choreography through marker-first ``handoff`` and
   ``clear`` requests. ``cleared`` and ``resumed`` are persisted only after the
   corresponding host stage completes; an ambiguous prepared marker pauses.
4. **needs_input** (criterion #5) — when ``adapter.needs_input(pane_text)``,
   dispatch a Discord brief via ``needs_input.evaluate_needs_input`` deduped
   against a per-session digest sidecar (see below), and transition the record
   into the ``needs_input`` lifecycle state so the stuck arm never nudges a
   session that is legitimately waiting on the human. When the pane is no longer
   waiting, a record still in ``needs_input`` is transitioned back to ``running``.
5. **stuck** (criterion #4) — ``stuck.evaluate_stuck`` decides skip/nudge/alert
   and returns the (possibly updated) record, which is persisted verbatim so the
   ``nudge_count > nudge_max`` "already escalated" marker (LEDGER T011) survives
   across polls and the Discord escalation stays exactly-once.

Every host-side intervention in this cascade is claimed through
``tmux_actuator.dispatch_lifecycle_action`` before its effect runs. Prepared
markers survive daemon restarts; an ambiguous prepared action pauses instead
of being silently repeated.

Design decisions:
- Dependency-injection seam discipline (mirrors every sibling module — ``stuck``,
  ``needs_input``, ``reconcile``, ``handoff``): every ``watchdog.*`` knob is a
  caller-supplied argument (the daemon resolves them once via
  ``registry.get_config_int``), while host effects use validated lifecycle
  requests. This module resolves no config itself
  (STYLE.md:P-004).
- Every tmux and judge invocation funnels through the existing explicit-timeout
  wrappers (``tmux_actuator.submit_text``/``has_session``,
  ``judge.dispatch_judge_verdict``) — no new bare ``subprocess`` call is
  introduced here (criterion #9).
- needs_input digest dedup is persisted to a per-session sidecar file
  (``<state_dir>/needs_input_digests/<session_id>.digest``) rather than the
  frozen T003 registry schema, so the dedup survives across separate daemon /
  ``--once`` invocations, not just in-process memory (T012's caller-owns-
  persistence contract). Sidecar reads/writes are best-effort (STYLE.md:EH-001):
  a lost digest at worst re-sends one Discord brief, matching needs_input.py's
  fail-open stance — it must never crash the poll loop.
- Reconciliation advances persisted child lease outcomes, then asks the
  registry to materialize sealed-group joins. The registry remains the sole
  readiness authority; unsealed child terminality never creates a wake.
- Persistence: ``poll_session`` persists on the returning arm through
  ``registry.locked_registry_update`` (``_persist_changed``), which re-reads the
  registry fresh under the sidecar lock and merges ONLY the records this cycle
  changed (the polled session's record + any children ``reconcile_children``
  marked) onto it — never a stale whole-file overwrite (T-REV-001). A single
  daemon process owns the poll loop (``registry.acquire_single_instance_lock``,
  T003/T015) so poll cycles are not concurrent with EACH OTHER, but a fanout CLI
  invocation (``fanout.run_fanout``) can persist new child records to the same
  registry concurrently with a poll pass; the locked-fresh-merge is what keeps a
  poll's transition from clobbering those freshly-added children (and vice
  versa). Precondition of the minimal merge: the ``sessions`` mapping handed to
  ``poll_session`` reflects the on-disk registry the daemon started this pass
  from (the single-writer invariant) — records the daemon holds but this cycle
  did not touch are already on disk, so the fresh re-read carries them.
  ``handoff.maybe_trigger_handoff`` additionally persists each choreography
  transition itself (crash-safety, T010) via its own locked write; the final
  merge reconciles the in-memory map with disk.

Non-scope (the daemon loop owns these — deliberately absent here): capturing the
pane text, resolving the ``watchdog.*`` knobs from config, the single-instance
lock, the heartbeat, the ``--once`` / ``status`` CLI verbs, and the sleep between
poll passes.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from runtime.watchdog import (
    handoff,
    judge,
    needs_input,
    notify,
    reconcile,
    registry,
    stuck,
    tmux_actuator,
)
from runtime.watchdog.adapters.base import HostAdapter

_ISO_SECONDS_FMT = "%Y-%m-%dT%H:%M:%SZ"
"""Second-precision UTC format matching ``registry._iso_now`` — the format
``stuck.evaluate_stuck`` parses ``last_seen`` with, so it MUST be used here."""

_ORIGIN_ARM_STATES = frozenset({"registered", "running"})
"""States a fanout origin (non-empty ``children``) is armed into
``awaiting_children`` from, and the states the handoff arm triggers from."""

_DIGEST_SUBDIR = "needs_input_digests"
"""Per-session needs_input-digest sidecar subdir under the state directory."""


# ── clock ──────────────────────────────────────────────────────────────────

def _now_dt(now: datetime | None) -> datetime:
    """Return ``now`` or the current UTC time (deterministic-test seam)."""
    return now or datetime.now(timezone.utc)


def _iso(now: datetime) -> str:
    """Format ``now`` as a second-precision UTC ``registry``-style timestamp."""
    return now.strftime(_ISO_SECONDS_FMT)


# ── needs_input digest sidecar (survives across daemon/--once invocations) ──

def _digest_path(digest_dir: Path, session_id: str) -> Path:
    """Return the per-session needs_input-digest sidecar file path."""
    return digest_dir / f"{session_id}.digest"


def _read_last_digest(path: Path) -> str | None:
    """Best-effort read of a persisted needs_input digest; ``None`` if absent.

    Named-exception-only (STYLE.md:EH-002): a missing sidecar (first cycle for
    this session, or a fresh daemon) or an I/O error yields ``None`` — the
    caller treats that as "nothing alerted yet this episode", so a genuinely
    new prompt is briefed rather than silently suppressed.
    """
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    return text or None


def _write_last_digest(path: Path, digest: str) -> None:
    """Best-effort persist of a needs_input digest to the sidecar.

    Best-effort (STYLE.md:EH-001): a failed write at worst re-sends one Discord
    brief next cycle (the digest is not remembered), which mirrors
    ``needs_input.py``'s documented fail-open contract — a lost digest must
    never crash the daemon's poll loop. Written atomically
    (``registry.atomic_write_json``'s tempfile+replace primitive is JSON-only,
    so a plain write suffices here for a single opaque token; a torn read is
    already handled by ``_read_last_digest`` returning ``None``).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(digest, encoding="utf-8")
    except OSError:
        return


def _noop_send_alerts(payload: Mapping[str, object]) -> int:
    """Suppress legacy alerts until sealed-group join owns wake timing."""
    return 0


# ── serialized persistence ──────────────────────────────────────────────────

def _persist_changed(
    registry_path: Path | str,
    incoming: dict[str, dict],
    sessions: dict[str, dict],
) -> dict[str, dict]:
    """Persist only the records this cycle changed, merged onto a fresh read.

    Diffs ``sessions`` (this cycle's working mapping) against ``incoming`` (the
    snapshot the cycle started from) to isolate exactly the records THIS cycle
    mutated — the polled session's record and any children
    ``reconcile_children`` marked terminal — and routes them through
    ``registry.locked_registry_update`` so they merge onto a fresh locked
    re-read rather than a stale whole-file snapshot (T-REV-001). A record a
    concurrent ``fanout.run_fanout`` persisted since this cycle read its
    ``incoming`` snapshot is absent from the changed set, so the fresh re-read
    carries it through untouched — the poll never clobbers freshly-added fanout
    children.

    Returns the merged mapping just written, so the daemon poll pass threads
    fresh registry state (including any concurrent additions) into the next
    session's cycle.
    """
    changed = {sid: rec for sid, rec in sessions.items() if incoming.get(sid) != rec}

    def _apply(fresh: dict[str, dict]) -> None:
        fresh.update(changed)

    return registry.locked_registry_update(registry_path, _apply)


# ── entry point ─────────────────────────────────────────────────────────────

def poll_session(
    record: dict,
    sessions: dict[str, dict],
    *,
    adapter: HostAdapter,
    pane_text: str,
    registry_path: Path | str,
    signals_path: Path | str,
    repo_root: Path | str,
    threshold_pct: float,
    window_tokens: int,
    stuck_after_s: int,
    nudge_max: int,
    judge_timeout_s: float | None = None,
    signals_max_mb: int | None = None,
    digest_dir: Path | str | None = None,
    now: datetime | None = None,
    has_session: Callable[..., bool] = tmux_actuator.has_session,
    judge_dispatch: Callable[..., dict] = judge.dispatch_judge_verdict,
    judge_role: str = judge.JUDGE_ROLE,
    needs_input_alert_fn: Callable[..., bool] = notify.send_needs_input_alert,
    dispatch_action: Callable[..., dict] = tmux_actuator.dispatch_lifecycle_action,
    lifecycle_notify: Callable[..., notify.DeliveryResult] = (
        notify.deliver_lifecycle_notification
    ),
) -> dict:
    """Run one poll cycle for a single session record and persist the result.

    Composes the level-0/level-1 primitives into the prioritized cascade
    described in the module docstring: context read (always) → fanout-origin
    lifecycle → context-threshold handoff → needs_input → stuck. The first arm
    that acts decisively persists the full sessions mapping and returns.

    Best-effort trigger decisions, hard-fail persistence (STYLE.md:EH-001):
    the context read, injection-ready gates, and the internal gates of each
    composed module never raise on an inconclusive cycle; but every
    ``registry.transition`` / ``registry.write_registry`` is hard-fail — a
    broken registry path must surface, matching ``registry.atomic_write_json``.

    Args:
        record: The session record to poll (T003 schema). Not mutated in place;
            a working copy is threaded through the arms.
        sessions: The full ``session_id`` -> record mapping the daemon holds.
            ``reconcile_children`` needs it to resolve children; the final
            ``write_registry`` persists it. Copied, not mutated in place.
        adapter: The session's ``HostAdapter`` (host-mechanics: read_context,
            injection_ready, needs_input, handoff/clear commands).
        pane_text: The session's already-captured tmux pane text.
        registry_path: Path to ``sessions.json``.
        signals_path: Path to ``signals.jsonl`` (``judge_degraded`` sink).
        repo_root: Absolute repo root, forwarded to the judge dispatch for
            provider-role resolution.
        threshold_pct: Resolved ``watchdog.context_threshold_pct``.
        window_tokens: Resolved ``watchdog.context_window_tokens`` denominator.
        stuck_after_s: Resolved ``watchdog.stuck_after_s`` idle threshold.
        nudge_max: Resolved ``watchdog.nudge_max`` unanswered-nudge cap.
        judge_timeout_s: Resolved ``watchdog.judge_timeout_s`` (``None`` defers
            to the judge dispatch's own default).
        signals_max_mb: Resolved ``watchdog.signals_max_mb`` rotation cap
            (``None`` resolves it via config only on the ``judge_degraded`` path).
        digest_dir: Directory for per-session needs_input digest sidecars;
            defaults to ``<registry_path parent>/needs_input_digests``.
        now: Injected clock (deterministic tests); defaults to current UTC.
        has_session: Injected ``tmux_actuator.has_session``-shaped liveness check
            (forwarded to ``reconcile_children``).
        judge_dispatch: Injected ``judge.dispatch_judge_verdict``-shaped callable.
        judge_role: Provider role forwarded to ``judge_dispatch``.
        needs_input_alert_fn: Injected Discord sender for the needs_input brief.
        dispatch_action: Marker-first deterministic lifecycle dispatcher.
        lifecycle_notify: Fail-open lifecycle notification delivery callable.

    Returns:
        A structured result dict with fields enumerated explicitly
        (STYLE.md:P-003):
        ``{"session_id", "action", "record", "sessions", "reading",
        "handoff_result", "needs_input_result", "stuck_result",
        "reconcile_payload", "lifecycle_notification_result"}``. ``action``
        is one of ``"await_children"``,
        ``"reconcile"``, ``"handoff"``, ``"needs_input"``, ``"nudge"``,
        ``"discord_alert"``, or ``"skip"``. ``record`` is the final record;
        ``sessions`` is the full post-write mapping; the arm-specific sub-result
        fields are populated for the arm that acted and ``None`` otherwise.
        ``"paused"`` reports a durable prepared marker whose side-effect
        outcome is ambiguous; no additional intervention is attempted.
    """
    sessions = dict(sessions)
    # Deep snapshot of the state this cycle starts from — the diff base for
    # ``_persist_changed`` so only records THIS cycle mutates are merged onto a
    # fresh locked re-read at persist time (T-REV-001). Deep so later in-place
    # mutations to the working records never retroactively alter the base.
    incoming = copy.deepcopy(sessions)
    record = dict(record)
    session_id = record["session_id"]
    now_dt = _now_dt(now)
    now_iso = _iso(now_dt)

    # A queued/duplicate poll may carry the pre-rollover record. Never let it
    # read or persist against the old host target: authority is the fresh
    # generation under the registry lock, and stale work is a harmless no-op.
    authoritative = registry.read_registry(registry_path).get(session_id)
    if authoritative is not None and (
        authoritative.get("state_generation") != record.get("state_generation")
        or authoritative.get("tmux_target") != record.get("tmux_target")
    ):
        return {
            "session_id": session_id,
            "action": "stale",
            "record": authoritative,
            "sessions": registry.read_registry(registry_path),
            "reading": None,
            "handoff_result": None,
            "needs_input_result": None,
            "stuck_result": None,
            "reconcile_payload": None,
            "lifecycle_notification_result": None,
        }

    resolved_digest_dir = (
        Path(digest_dir)
        if digest_dir is not None
        else Path(registry_path).parent / _DIGEST_SUBDIR
    )

    # ── (a) context read (always) ──────────────────────────────────────────
    reading = adapter.read_context(
        record["transcript_path"], record["transcript_offset"],
        window_tokens=window_tokens,
    )
    if reading.new_offset > record["transcript_offset"]:
        # New transcript activity this cycle — reset the idle clock. Stamped
        # only on real progress so a silent/stuck session's last_seen ages
        # (criterion #4: "no new transcript events for stuck_after_s").
        record["last_seen"] = now_iso
    record["transcript_offset"] = reading.new_offset
    record["last_context_check"] = now_iso
    sessions[session_id] = record

    result = {
        "session_id": session_id,
        "action": "skip",
        "record": record,
        "sessions": sessions,
        "reading": reading,
        "handoff_result": None,
        "needs_input_result": None,
        "stuck_result": None,
        "reconcile_payload": None,
        "lifecycle_notification_result": None,
    }

    # ── (e) fanout-origin lifecycle ────────────────────────────────────────
    if record.get("children"):
        return _poll_fanout_origin(
            record, sessions, result, incoming,
            adapter=adapter, pane_text=pane_text, registry_path=registry_path,
            has_session=has_session, lifecycle_notify=lifecycle_notify,
            now_iso=now_iso,
        )

    # ── (b) context-threshold handoff ──────────────────────────────────────
    handoff_in_progress = record["state"] in {
        "handoff_requested", "handoff_written", "cleared",
    }
    handoff_threshold_crossed = (
        reading.pct_used is not None
        and reading.pct_used >= threshold_pct
        and record["state"] in _ORIGIN_ARM_STATES
    )
    if (handoff_in_progress or handoff_threshold_crossed) and not adapter.injection_ready(
        pane_text
    ):
        sessions = _persist_changed(registry_path, incoming, sessions)
        result.update(action="paused", sessions=sessions)
        return result
    if handoff_in_progress or handoff_threshold_crossed:
        handoff_result = handoff.maybe_trigger_handoff(
            record, reading.pct_used,
            threshold_pct=threshold_pct,
            registry_path=registry_path,
            signals_path=signals_path,
            repo_root=repo_root,
            pane_text=pane_text,
            judge_dispatch=judge_dispatch,
            judge_role=judge_role,
            judge_timeout_s=judge_timeout_s,
            signals_max_mb=signals_max_mb,
        )
        if handoff_result["triggered"]:
            record = handoff_result["record"]
            sessions[session_id] = record
            if record["state"] == "handoff_written":
                handoff_dispatch = dispatch_action(
                    registry_path,
                    session_id=session_id,
                    action="handoff",
                    generation=record["state_changed_at"],
                    attempt=1,
                    max_attempts=1,
                    target=record["tmux_target"],
                    text=adapter.handoff_command(),
                    host_ready=True,
                )
                if handoff_dispatch["status"] != "completed":
                    sessions = _persist_changed(registry_path, incoming, sessions)
                    result.update(
                        action="paused", record=record, sessions=sessions,
                        handoff_result=handoff_result,
                    )
                    return result
                record = registry.transition(record, "cleared", now=now_iso)
                sessions[session_id] = record
                sessions = _persist_changed(registry_path, incoming, sessions)
                incoming = copy.deepcopy(sessions)
            if record["state"] == "cleared":
                clear_dispatch = dispatch_action(
                    registry_path,
                    session_id=session_id,
                    action="clear",
                    generation=record["state_changed_at"],
                    attempt=1,
                    max_attempts=1,
                    target=record["tmux_target"],
                    text=adapter.clear_command(),
                    host_ready=True,
                )
                if clear_dispatch["status"] != "completed":
                    sessions = _persist_changed(registry_path, incoming, sessions)
                    result.update(
                        action="paused", record=record, sessions=sessions,
                        handoff_result=handoff_result,
                    )
                    return result
                record = registry.transition(record, "resumed", now=now_iso)
                sessions[session_id] = record
            sessions = _persist_changed(registry_path, incoming, sessions)
            result.update(
                action="handoff", record=record, sessions=sessions,
                handoff_result=handoff_result,
            )
            return result
        if handoff_in_progress:
            sessions = _persist_changed(registry_path, incoming, sessions)
            result.update(
                action="paused", sessions=sessions,
                handoff_result=handoff_result,
            )
            return result
    # Not over-threshold, not ready, or not triggered — fall through: the
    # needs_input/stuck arms' own gates keep a working session untouched.

    # ── (d) needs_input ────────────────────────────────────────────────────
    if adapter.needs_input(pane_text):
        return _poll_needs_input(
            record, sessions, result, incoming,
            adapter=adapter, pane_text=pane_text, registry_path=registry_path,
            digest_dir=resolved_digest_dir, alert_fn=needs_input_alert_fn,
            now_iso=now_iso,
        )
    if record["state"] == "needs_input":
        # Pane no longer waiting on the human — the prompt was answered; return
        # to running so the stuck arm can watch it again.
        record = registry.transition(record, "running", now=now_iso)
        sessions[session_id] = record

    # ── (c) stuck ──────────────────────────────────────────────────────────
    def _marked_submit(target: str, text: str) -> str:
        dispatched = dispatch_action(
            registry_path,
            session_id=session_id,
            action="nudge",
            generation=record["last_seen"],
            attempt=record["nudge_count"] + 1,
            max_attempts=nudge_max,
            target=target,
            text=text,
            host_ready=True,
        )
        return str(dispatched["status"])

    def _marked_escalation(title: str, body: str) -> str:
        dispatched = dispatch_action(
            registry_path,
            session_id=session_id,
            action="escalation",
            generation=record["last_seen"],
            attempt=1,
            max_attempts=1,
            title=title,
            body=body,
            host_ready=True,
        )
        return str(dispatched["status"])

    stuck_result = stuck.evaluate_stuck(
        record, now_dt,
        pane_text=pane_text, adapter=adapter,
        stuck_after_s=stuck_after_s, nudge_max=nudge_max,
        submit_fn=_marked_submit, alert_fn=_marked_escalation,
    )
    # Persist the returned record VERBATIM — including the nudge_count past-max
    # marker bump on a discord_alert (LEDGER T011) that makes escalation
    # exactly-once across polls.
    record = stuck_result["record"]
    sessions[session_id] = record
    sessions = _persist_changed(registry_path, incoming, sessions)
    result.update(
        action=stuck_result["action"], record=record, sessions=sessions,
        stuck_result=stuck_result,
    )
    return result


def _poll_fanout_origin(
    record: dict,
    sessions: dict[str, dict],
    result: dict,
    incoming: dict[str, dict],
    *,
    adapter: HostAdapter,
    pane_text: str,
    registry_path: Path | str,
    has_session: Callable[..., bool],
    lifecycle_notify: Callable[..., notify.DeliveryResult],
    now_iso: str,
) -> dict:
    """Handle a fanout origin's ``awaiting_children`` lifecycle for one cycle.

    A ``registered``/``running`` origin is armed into ``awaiting_children``. An
    origin already ``awaiting_children`` advances child leases and atomically
    materializes a join only when its explicit registration epoch is sealed.
    """
    session_id = record["session_id"]

    # An origin that entered ``needs_input`` BEFORE fanout would otherwise
    # deadlock: this arm captures every record with children ahead of the
    # needs_input arm, but ``needs_input`` matched neither branch below, so
    # the state never cleared (found live, 2026-07-11 fanout smoke test).
    # Mirror the needs_input arm's clear here: once the pane is no longer
    # waiting on a human, walk needs_input -> running and fall through to the
    # arming branch in this same cycle.
    if record["state"] == "needs_input" and not adapter.needs_input(pane_text):
        record = registry.transition(record, "running", now=now_iso)
        sessions[session_id] = record

    if record["state"] in _ORIGIN_ARM_STATES:
        record = registry.transition(record, "awaiting_children", now=now_iso)
        sessions[session_id] = record
        sessions = _persist_changed(registry_path, incoming, sessions)
        result.update(action="await_children", record=record, sessions=sessions)
        return result

    if record["state"] == "awaiting_children":
        reconciled = reconcile.reconcile_children(
            record, sessions,
            has_session=has_session, send_alerts=_noop_send_alerts,
            registry_path=registry_path,
            lifecycle_notify=lifecycle_notify,
            now=now_iso,
        )
        sessions = reconciled["records"]
        payload = reconciled["payload"]
        sessions = _persist_changed(registry_path, incoming, sessions)
        registry.materialize_ready_joins(registry_path, now=now_iso)
        result.update(
            action="reconcile", record=record, sessions=sessions,
            reconcile_payload=payload,
        )
        return result

    # A terminal / handoff-choreography origin: nothing to reconcile this cycle.
    sessions = _persist_changed(registry_path, incoming, sessions)
    result.update(record=record, sessions=sessions)
    return result


def _poll_needs_input(
    record: dict,
    sessions: dict[str, dict],
    result: dict,
    incoming: dict[str, dict],
    *,
    adapter: HostAdapter,
    pane_text: str,
    registry_path: Path | str,
    digest_dir: Path,
    alert_fn: Callable[..., bool],
    now_iso: str,
) -> dict:
    """Dispatch a deduped needs_input Discord brief and manage the state.

    Reads the persisted last-sent digest from the per-session sidecar, calls
    ``needs_input.evaluate_needs_input`` (which sends the brief only on a
    genuinely new prompt), persists the new digest back to the sidecar, and
    transitions a ``registered``/``running`` record into the ``needs_input``
    lifecycle state so ``stuck`` never nudges a session waiting on the human
    (criterion #4).
    """
    session_id = record["session_id"]
    sidecar = _digest_path(digest_dir, session_id)
    last_digest = _read_last_digest(sidecar)

    ni_result = needs_input.evaluate_needs_input(
        record, pane_text=pane_text, adapter=adapter,
        last_digest=last_digest, alert_fn=alert_fn,
    )
    if ni_result["digest"] is not None and ni_result["digest"] != last_digest:
        # A genuinely new prompt was briefed (or send-failed but returns the new
        # digest so we do not retry the identical failed send) — remember it so
        # the next poll dedups it, even across a daemon restart.
        _write_last_digest(sidecar, ni_result["digest"])

    if record["state"] in _ORIGIN_ARM_STATES:
        record = registry.transition(record, "needs_input", now=now_iso)
        sessions[session_id] = record

    sessions = _persist_changed(registry_path, incoming, sessions)
    result.update(
        action="needs_input", record=record, sessions=sessions,
        needs_input_result=ni_result,
    )
    return result
