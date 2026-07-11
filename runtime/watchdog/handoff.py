"""Context-threshold handoff state machine for the session-watchdog daemon.

Purpose (T010, criteria #2/#3): wire the persisted handoff choreography
INTENT describes as "external transcript measurement, judge-advised stopping
point, then a crash-safe persisted state machine driving ``/z-handoff`` →
``/clear`` → resume pointer". This module is the single entry point,
``maybe_trigger_handoff``: given a session record and its already-measured
context-usage percentage, it drives the record through
``registered/running -> handoff_requested -> handoff_written -> cleared ->
resumed`` (T003's frozen adjacency graph), persisting every step via
``registry.write_registry`` so ``sessions.json`` shows a distinct,
monotonically increasing ``state_changed_at`` per transition, writes
``handoff.json`` to ``<record's plan_dir>/handoff.json``, and consults the
``watchdog_judge`` provider (T007's ``judge.dispatch_judge_verdict``) for a
stopping-point recommendation — degrading to the mechanical fallback and
logging a ``judge_degraded`` signal whenever the judge is unavailable.

Design decisions:
- Boundary (criterion #2 wording fix): the trigger condition is
  ``pct_used >= threshold_pct`` (at-or-above), matching the boundary T007's
  ``mechanical_fallback_verdict`` already established for the mechanical
  fallback. Criterion #2's prose says "exceeds"; the reviewer flagged this as
  an unresolved wording ambiguity between "exceeds" (>) and T007's ">="
  (LEDGER.md T007 entry). This module picks ">=" so the mechanical-fallback
  boundary and the state-machine trigger boundary can never disagree about
  whether a given ``pct_used`` crossed the line — decision recorded in this
  task's LEDGER entry, not silently re-derived per caller.
- ``plan_dir`` is read solely from ``record["plan_dir"]`` (binding level-1
  obligation): no separate ``plan_dir`` argument is accepted, so there is
  exactly one place ``handoff.json``'s destination can come from.
- DI seam (same discipline as T007/T011-T015 siblings): every collaborator
  — the registry/signals file paths, the judge dispatch callable, the judge
  role/timeout, the signals rotation cap, and the clock — is a caller-
  supplied argument. This module never resolves ``watchdog.*`` config itself
  and never touches tmux: the actual pane actuation (submitting
  ``adapter.handoff_command()`` / ``adapter.clear_command()`` text) composes
  a *live* pane-readiness gate across possibly-many poll cycles, which is
  poll-loop/composition-layer work (INTENT "no daemon-loop code" scope note
  for this level) — not a single synchronous state-transition call. This
  keeps the acceptance surface here to exactly what T010's four acceptance
  obligations describe: the persisted state machine, ``handoff.json``, and
  the judge-advised verdict + degrade path.
- Judge prompt construction (T007's explicit non-scope item, "the level that
  wires the context-threshold state machine is the one that will define...
  that contract") lands here: ``_build_judge_prompt`` embeds the session's
  identity, the measured/threshold percentages, and a bounded excerpt of the
  caller-supplied ``pane_text`` so the judge has situational context for its
  stopping-point recommendation. No structured verdict schema exists yet
  (T007), so the judge's raw response continues to travel verbatim under
  ``verdict["raw_output"]``; this module does not parse it.
- The judge's verdict is advisory, not flow-controlling: T003's frozen
  handoff adjacency is a strict linear pipeline
  (``handoff_requested -> handoff_written -> cleared -> resumed``) with no
  "postpone" branch, so once the mechanical ``>=`` trigger fires, the full
  sequence always completes — the judge's recommendation is recorded in
  ``handoff.json`` for the resumed session to read, not used to gate
  progression at this level.
- ``handoff.json`` is written via ``registry.atomic_write_json`` (STYLE.md
  WL-001 rung 2 — reuse: the same tempfile+``os.replace`` primitive
  ``sessions.json`` itself uses, registry.py:349) rather than a bespoke
  write, so a concurrent reader never observes a torn handoff pointer file
  (STYLE.md:P-006).
- Monotonic timestamps: ``registry.transition``'s default clock
  (``registry._iso_now()``) has one-second resolution, which four
  back-to-back transitions in the same call can trivially tie. This module's
  default clock (``_default_clock``) instead returns microsecond-precision
  UTC timestamps and bumps by one microsecond whenever two consecutive calls
  would otherwise collide, guaranteeing the "distinct, monotonically
  increasing ``state_changed_at`` per transition" acceptance obligation
  without a real sleep. Callers may inject their own zero-arg ``now``
  callable (e.g. for fully deterministic tests).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from runtime.watchdog import judge, registry

_PANE_EXCERPT_CHARS = 4000
"""Cap on how much ``pane_text`` is embedded in the judge prompt — a full
scrollback capture must not produce an unbounded prompt."""

_TRIGGER_SOURCE_STATES = frozenset({"registered", "running"})
"""States ``maybe_trigger_handoff`` will drive into ``handoff_requested``
from (criterion #2's literal "registered/running -> handoff_requested").
A record in any other state (e.g. ``needs_input``, ``stuck``) is left alone
this cycle — a later poll re-evaluates once it returns to one of these."""


# ── clock ─────────────────────────────────────────────────────────────────

def _default_clock() -> Callable[[], str]:
    """Return a zero-arg callable yielding strictly increasing UTC timestamps.

    Best-effort monotonicity guard (see module design decisions): each call
    reads the wall clock at microsecond precision and bumps by one
    microsecond over the previous call's value when the wall clock has not
    itself advanced, so four calls in the same synchronous pipeline never
    collide.
    """
    state: dict[str, datetime | None] = {"last": None}

    def _tick() -> str:
        current = datetime.now(timezone.utc)
        last = state["last"]
        if last is not None and current <= last:
            current = last + timedelta(microseconds=1)
        state["last"] = current
        return current.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    return _tick


# ── judge prompt ──────────────────────────────────────────────────────────

def _build_judge_prompt(
    record: dict, pct_used: float, threshold_pct: float, pane_text: str
) -> str:
    """Build the free-text prompt asking the judge for a stopping-point call.

    Non-scope elsewhere (see ``judge.py``'s module docstring): prompt
    construction was explicitly deferred to this level. The result is opaque
    free text (``judge.dispatch_judge_verdict``'s contract) — no structured
    verdict schema exists yet, so the judge's response is stored verbatim.

    Args:
        record: The session record (uses ``session_id``/``slug``/``host``).
        pct_used: Measured context-usage percentage that triggered this call.
        threshold_pct: The configured ``watchdog.context_threshold_pct``.
        pane_text: Recent pane capture giving the judge situational context;
            truncated to the trailing ``_PANE_EXCERPT_CHARS`` characters.

    Returns:
        The prompt string to pass as ``judge_dispatch``'s ``prompt`` kwarg.
    """
    excerpt = pane_text[-_PANE_EXCERPT_CHARS:] if pane_text else "(no pane text captured)"
    return (
        f"Session {record['session_id']!r} (slug {record['slug']!r}, host "
        f"{record['host']!r}) has used {pct_used:.1f}% of its context "
        f"window, at or above the configured {threshold_pct:.1f}% handoff "
        "threshold. A crash-safe handoff is about to be written and the "
        "session cleared and resumed. Recommend whether now is a safe "
        "stopping point given the recent pane output below, or note "
        "anything the resumed session should be told to finish first.\n\n"
        f"--- recent pane output ---\n{excerpt}"
    )


# ── entry point ───────────────────────────────────────────────────────────

def maybe_trigger_handoff(
    record: dict,
    pct_used: float | None,
    *,
    threshold_pct: float,
    registry_path: str | Path,
    signals_path: str | Path,
    repo_root: str | Path,
    pane_text: str = "",
    judge_dispatch: Callable[..., dict] = judge.dispatch_judge_verdict,
    judge_role: str = judge.JUDGE_ROLE,
    judge_timeout_s: float | None = None,
    signals_max_mb: int | None = None,
    now: Callable[[], str] | None = None,
) -> dict:
    """Drive ``record`` through the handoff choreography if threshold-crossed.

    Best-effort trigger decision, hard-fail choreography (STYLE.md:EH-001):
    determining whether to trigger never raises (an unknown/below-threshold
    reading is simply a no-op this cycle), but once triggered, every
    ``registry.transition``/``registry.write_registry`` call is hard-fail —
    a broken registry path must surface, not be swallowed (STYLE.md:EH-004,
    matching ``registry.atomic_write_json``'s own stance).

    Args:
        record: The current session record (T003 schema). Not mutated;
            each step operates on the value ``registry.transition`` returns.
        pct_used: This cycle's measured context-usage percentage, or
            ``None`` for the ``context_unknown`` sentinel (``HostAdapter``'s
            documented "no confident reading this cycle" case) — treated as
            a no-op, never as 0%.
        threshold_pct: The configured ``watchdog.context_threshold_pct``.
        registry_path: Path to ``sessions.json``. Read once to obtain the
            full sessions mapping, then upserted and rewritten after each
            transition.
        signals_path: Path to ``signals.jsonl`` (``registry.append_signal``
            destination for a ``judge_degraded`` event).
        repo_root: Absolute repo root, forwarded to ``judge_dispatch`` for
            provider-role resolution.
        pane_text: Recent pane capture embedded in the judge prompt for
            situational context. Defaults to ``""`` (prompt notes no pane
            text was captured).
        judge_dispatch: Injected judge dispatcher; defaults to
            ``judge.dispatch_judge_verdict``. Tests substitute a stub.
        judge_role: Provider role forwarded to ``judge_dispatch``.
        judge_timeout_s: Per-attempt judge timeout forwarded to
            ``judge_dispatch``; ``None`` defers to its own default.
        signals_max_mb: Rotation cap forwarded to ``registry.append_signal``;
            ``None`` resolves ``watchdog.signals_max_mb`` via config (only
            reached on the ``judge_degraded`` path).
        now: Injected zero-arg clock returning ISO timestamps; defaults to
            ``_default_clock()`` (see module design decisions). Tests inject
            a fully deterministic clock when exact values matter.

    Returns:
        ``{"triggered": bool, "record": dict, "reason": str | None,
        "handoff_path": Path | None, "verdict": dict | None,
        "judge_degraded": dict | None}``. When ``triggered`` is ``False``,
        ``record`` is returned unchanged and ``reason`` explains why
        (``"context_unknown"``, ``"below_threshold"``, or
        ``"invalid_source_state:<state>"``).
    """
    if pct_used is None:
        return {
            "triggered": False,
            "record": record,
            "reason": "context_unknown",
            "handoff_path": None,
            "verdict": None,
            "judge_degraded": None,
        }
    if pct_used < threshold_pct:
        return {
            "triggered": False,
            "record": record,
            "reason": "below_threshold",
            "handoff_path": None,
            "verdict": None,
            "judge_degraded": None,
        }
    if record.get("state") not in _TRIGGER_SOURCE_STATES:
        return {
            "triggered": False,
            "record": record,
            "reason": f"invalid_source_state:{record.get('state')!r}",
            "handoff_path": None,
            "verdict": None,
            "judge_degraded": None,
        }

    clock = now or _default_clock()
    sessions = registry.read_registry(registry_path)

    def _persist(next_state: str) -> dict:
        updated = registry.transition(record, next_state, now=clock())
        sessions[updated["session_id"]] = updated
        registry.write_registry(registry_path, sessions)
        return updated

    record = _persist("handoff_requested")

    prompt = _build_judge_prompt(record, pct_used, threshold_pct, pane_text)
    dispatch_result = judge_dispatch(
        context_pct=pct_used,
        threshold_pct=threshold_pct,
        prompt=prompt,
        repo_root=repo_root,
        role=judge_role,
        timeout_s=judge_timeout_s,
    )
    verdict = dispatch_result["verdict"]
    judge_degraded = dispatch_result.get("judge_degraded")
    if judge_degraded is not None:
        registry.append_signal(
            signals_path, "judge_degraded", judge_degraded,
            max_mb=signals_max_mb, now=clock(),
        )

    handoff_path = Path(record["plan_dir"]) / "handoff.json"
    registry.atomic_write_json(handoff_path, {
        "schema_version": registry.SCHEMA_VERSION,
        "session_id": record["session_id"],
        "slug": record["slug"],
        "host": record["host"],
        "tmux_target": record["tmux_target"],
        "context_pct": pct_used,
        "threshold_pct": threshold_pct,
        "verdict": verdict,
        "judge_degraded": judge_degraded,
        "written_at": clock(),
    })

    record = _persist("handoff_written")
    record = _persist("cleared")
    record = _persist("resumed")

    return {
        "triggered": True,
        "record": record,
        "reason": None,
        "handoff_path": handoff_path,
        "verdict": verdict,
        "judge_degraded": judge_degraded,
    }
