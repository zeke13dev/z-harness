"""``omp`` ``HostAdapter`` implementation for the session-watchdog daemon.

Purpose (T009, criterion #10): implement the four ``HostAdapter`` capabilities
against the omp CLI's per-chat session transcript
(``${PI_CODING_AGENT_DIR:-~/.omp/agent}/sessions/<cwd-slug>/<ISO-ts>_<session-
id>.jsonl``) and TUI mechanics, per the grounded findings in
``runtime/watchdog/HOST_MECHANICS.md`` (READ FIRST, ``## omp`` section) and the
fixtures under ``tests/fixtures/watchdog/omp/``.

Transcript usage contract: each assistant ``message`` event carries
``message.usage.totalTokens`` plus a ``message.contextSnapshot`` object, but
(unlike codex's self-contained ``token_count`` event) **never** the model's
max context window — that denominator must be cross-referenced separately by
model id via ``omp models``/``omp models --json`` (HOST_MECHANICS.md, ``[O-5]``).
No captured provenance exists in this repo for ``omp models --json``'s exact
JSON field shape (only the human-readable table was captured), so this module
does not parse that output itself: it accepts an already-resolved
``model_context_windows`` mapping injected at construction, keeping
``read_context`` free of subprocess calls and fully testable against fixtures
without a live ``omp`` binary (a later level that wires the daemon startup
owns calling ``omp models --json`` and building this mapping).

Design decisions:
- Model-window resolution: on a usable usage reading, the message's ``model``
  id is looked up in the injected ``model_context_windows`` map. A hit yields
  a confident reading (``degraded=False``) using that model's real window as
  the denominator. A miss (unknown/custom provider model) degrades to the
  byte-length fallback estimator, per HOST_MECHANICS.md's documented
  last-resort fallback for an unresolvable model id — the caller-supplied
  ``window_tokens`` (the interface's uniform, host-agnostic fallback
  denominator; see ``base.py``) is used as the denominator in that case,
  exactly as ``codex.py``'s own degraded path does.
- Missing/degraded usage (``stopReason == "error"``): ``usage`` is present
  but every numeric field is zeroed and ``contextSnapshot`` is entirely
  absent (real fixture:
  ``tests/fixtures/watchdog/omp/usage_missing_or_degraded.json``). Trusting
  ``totalTokens`` at face value here would report a false 0%, which could
  suppress or delay a real handoff trigger. This module treats the presence
  of ``contextSnapshot`` as the usability gate (its absence already implies
  the zeroed-usage error shape) rather than special-casing ``stopReason``
  directly — one condition covers both documented symptoms.
- An assistant message whose usage is unusable still means a turn happened
  (the analogue of codex's ``task_complete``-without-``token_count`` case):
  it degrades to the byte-length estimator rather than leaving the cycle's
  reading as ``context_unknown`` — a completed-but-unmeasured turn must never
  read as a false 0%.
- ``context_estimate_degraded_signal`` builds the shaped signal payload for a
  degraded ``ContextReading`` but never writes it — same returns-dict/
  caller-writes contract ``judge.py`` (T007) established for
  ``judge_degraded``: the caller already owns ``signals_path`` and appends
  via ``registry.append_signal`` (STYLE.md:P-003 — fields enumerated
  explicitly, never spread).
- Dual-condition ready gate (HOST_MECHANICS.md): the default idle composer
  renders no printable prompt glyph at all (contradicting the so-MCP
  reference's ``❯``-glyph assumption), so ``injection_ready`` instead keys off
  the live footer's ``<pct>%/<window>`` reading. Critically, that same
  percentage keeps rendering while omp is busy (spinner + ``Working…`` +
  ``⟨esc⟩`` hint) — percentage alone is therefore NOT sufficient. The gate is
  a conjunction: percentage present AND no busy marker anywhere in the pane.
  ``needs_input`` uses this same conjunction as its primary signal (mirroring
  ``claude.py``'s single shared detector) plus one additional, omp-specific
  path: a full-screen selection overlay (e.g. ``/model``'s picker) that
  replaces the composer's footer entirely (no percentage renders at all) but
  shows a lone ``>`` filter-input line followed by a rendered option list
  (STATE 3 in ``prompt_ready_pane.txt``) — a case the percentage-based gate
  can never see since the overlay covers the footer.
"""

from __future__ import annotations

import json
import math
import re

from runtime.watchdog.adapters.base import ContextReading, HostAdapter

HANDOFF_COMMAND = "/z-handoff"
"""The z-harness handoff skill — host-agnostic by construction (a normal
slash-command prompt), invoked identically across claude/codex/omp."""

CLEAR_COMMAND = "/new"
"""omp's clear-equivalent: "Start a new session" (HOST_MECHANICS.md; same
command name as codex's, observed live, no confirmation dialog)."""

_CONSERVATIVE_BYTES_PER_TOKEN = 3.0
"""Deliberately smaller than the ~4-bytes/token nominal English-text/code
average so the degraded byte-length fallback estimate biases toward
*over*-reporting token usage (the safe direction) rather than under-
reporting it (HOST_MECHANICS.md) — same constant codex.py uses."""

_FOOTER_PCT_RE = re.compile(r"\d+(?:\.\d+)?%\s*/\s*\d+K")
"""Matches omp's live footer context-usage readout, e.g. ``9.4%/272K``."""

_BUSY_TEXT_MARKERS: tuple[str, ...] = ("working…", "working...", "⟨esc⟩", "(esc to interrupt)")
"""Lowercased busy-state substrings (HOST_MECHANICS.md: "Working…" + an
"esc" interrupt hint accompany the spinner while omp is busy)."""

_BUSY_SPINNER_CHARS = "⠁⠂⠄⡀⢀⠠⠐⠈⠹⠸⠼⠴⠦⠧⠇⠏"
"""Braille-dot spinner glyphs named in HOST_MECHANICS.md's busy-marker set."""


class OmpAdapter(HostAdapter):
    """``HostAdapter`` for the ``omp`` host (omp CLI).

    Args:
        model_context_windows: Cached ``{model_id: window_tokens}`` mapping,
            already resolved (e.g. from a parsed ``omp models --json`` run
            done elsewhere — see module docstring). Defaults to an empty
            mapping, in which case every reading degrades to the byte-length
            fallback until a real mapping is injected.
    """

    host = "omp"

    def __init__(self, model_context_windows: dict[str, int] | None = None) -> None:
        self._model_context_windows: dict[str, int] = dict(model_context_windows or {})

    def read_context(
        self, transcript_path: str, offset: int, *, window_tokens: int
    ) -> ContextReading:
        """See ``HostAdapter.read_context``.

        Mirrors ``claude.py``/``codex.py``'s incremental, complete-lines-only
        read shape (seek to ``offset``, consume only newline-terminated
        lines, leave a dangling in-flight tail unconsumed). Within the newly-
        consumed chunk: a usable assistant-message reading whose model
        resolves against ``self._model_context_windows`` yields a confident
        reading; a usable reading whose model does NOT resolve, or an
        assistant message with unusable (error-shaped) usage, both yield a
        degraded byte-length estimate; no assistant message at all in the
        chunk yields the ``context_unknown`` sentinel. A malformed complete
        line is skipped (never raises).
        """
        try:
            with open(transcript_path, "rb") as handle:
                handle.seek(offset)
                chunk = handle.read()
        except (FileNotFoundError, OSError):
            return ContextReading(
                new_offset=offset,
                used_tokens=None,
                window_tokens=window_tokens,
                pct_used=None,
            )

        last_newline = chunk.rfind(b"\n")
        if last_newline == -1:
            # No complete line in this increment yet — nothing to consume.
            return ContextReading(
                new_offset=offset,
                used_tokens=None,
                window_tokens=window_tokens,
                pct_used=None,
            )

        consumed = chunk[: last_newline + 1]
        new_offset = offset + len(consumed)

        last_usable: tuple[int, str | None] | None = None
        saw_unusable_message = False
        for raw_line in consumed.split(b"\n"):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue  # malformed complete line — skip, never raise.
            message = _extract_assistant_message(record)
            if message is None:
                continue
            usable = _extract_usable_usage(message)
            if usable is not None:
                last_usable = usable  # append-only file: later = newer.
            else:
                saw_unusable_message = True

        if last_usable is not None:
            total_tokens, model = last_usable
            window = self._model_context_windows.get(model) if model else None
            if window is not None:
                pct_used = (total_tokens / window) * 100
                return ContextReading(
                    new_offset=new_offset,
                    used_tokens=total_tokens,
                    window_tokens=window,
                    pct_used=pct_used,
                    degraded=False,
                )
            # Model id unresolved against the cached registry — degrade to
            # the byte-length estimator (HOST_MECHANICS.md's documented
            # last-resort fallback), using the caller-supplied window_tokens.
            return _degraded_byte_length_reading(new_offset, window_tokens)

        if saw_unusable_message:
            # A turn completed with an error-shaped/zeroed usage reading —
            # "no confident reading yet", not an error. Same treatment as
            # codex's task_complete-without-token_count case.
            return _degraded_byte_length_reading(new_offset, window_tokens)

        return ContextReading(
            new_offset=new_offset,
            used_tokens=None,
            window_tokens=window_tokens,
            pct_used=None,
            degraded=False,
        )

    def injection_ready(self, pane_text: str) -> bool:
        """See ``HostAdapter.injection_ready``; see module docstring for the
        dual-condition (percentage-present AND no-busy-marker) gate."""
        return _dual_condition_ready(pane_text)

    def needs_input(self, pane_text: str) -> bool:
        """See ``HostAdapter.needs_input``; see module docstring: the same
        dual-condition gate as ``injection_ready``, plus the omp-specific
        full-screen selection-overlay path the percentage gate cannot see."""
        return _dual_condition_ready(pane_text) or _selection_overlay_present(pane_text)

    def handoff_command(self) -> str:
        return HANDOFF_COMMAND

    def clear_command(self) -> str:
        return CLEAR_COMMAND


def context_estimate_degraded_signal(reading: ContextReading) -> dict:
    """Build the ``context_estimate_degraded`` event payload for a degraded
    ``ContextReading`` (byte-length fallback). This function only returns the
    dict — the caller is responsible for appending it to ``signals.jsonl``
    (via T003's ``registry.append_signal``) whenever ``reading.degraded`` is
    ``True``, exactly the returns-dict-caller-writes contract ``judge.py``
    established for ``judge_degraded`` (STYLE.md:P-003 — every field
    enumerated explicitly).
    """
    return {
        "host": OmpAdapter.host,
        "used_tokens": reading.used_tokens,
        "window_tokens": reading.window_tokens,
        "pct_used": reading.pct_used,
    }


def _extract_assistant_message(record: object) -> dict | None:
    """Return ``record["message"]`` if ``record`` is a well-formed
    ``type: "message"`` line whose nested message is the assistant's turn;
    ``None`` otherwise (not a message event, or not an assistant turn)."""
    if not isinstance(record, dict) or record.get("type") != "message":
        return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    return message


def _extract_usable_usage(message: dict) -> tuple[int, str | None] | None:
    """Return ``(total_tokens, model_id)`` from ``message`` if it carries a
    usable usage reading; ``None`` when the message exists but its usage is
    unusable (an error-terminated turn: ``usage`` present with every numeric
    field zeroed and ``contextSnapshot`` entirely absent — real fixture:
    ``usage_missing_or_degraded.json``). ``contextSnapshot`` presence is used
    as the single usability gate since its absence already implies the
    zeroed-usage error shape.
    """
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    total_tokens = usage.get("totalTokens")
    if not isinstance(total_tokens, int):
        return None
    context_snapshot = message.get("contextSnapshot")
    if not isinstance(context_snapshot, dict):
        return None  # error-terminated turn shape — unusable, not "0%".
    model = message.get("model")
    return total_tokens, (model if isinstance(model, str) else None)


def _degraded_byte_length_reading(new_offset: int, window_tokens: int) -> ContextReading:
    """Degraded, upward-biased token estimate from raw transcript bytes
    (HOST_MECHANICS.md) — used both when a usable reading's model can't be
    resolved against the cached registry, and when a completed turn carries
    no usable usage reading at all."""
    used_tokens = math.ceil(new_offset / _CONSERVATIVE_BYTES_PER_TOKEN)
    pct_used = (used_tokens / window_tokens) * 100
    return ContextReading(
        new_offset=new_offset,
        used_tokens=used_tokens,
        window_tokens=window_tokens,
        pct_used=pct_used,
        degraded=True,
    )


def _has_busy_marker(pane_text: str) -> bool:
    """Return whether any busy-state marker (HOST_MECHANICS.md: "Working…" +
    an ``⟨esc⟩``/"(esc to interrupt)" hint, or a braille spinner glyph)
    appears anywhere in ``pane_text``."""
    low = pane_text.lower()
    if any(marker in low for marker in _BUSY_TEXT_MARKERS):
        return True
    return any(ch in pane_text for ch in _BUSY_SPINNER_CHARS)


def _dual_condition_ready(pane_text: str) -> bool:
    """omp's documented ready gate (HOST_MECHANICS.md): the footer's
    ``<pct>%/<window>`` marker is present AND no busy marker appears
    anywhere in the pane — percentage alone is NOT sufficient since the
    footer keeps rendering the percentage while omp is busy (STATE 2 in
    ``prompt_ready_pane.txt``)."""
    if not _FOOTER_PCT_RE.search(pane_text):
        return False
    return not _has_busy_marker(pane_text)


def _selection_overlay_present(pane_text: str) -> bool:
    """omp's full-screen selection-overlay ``needs_input`` signal (STATE 3
    in ``prompt_ready_pane.txt``): the footer's ``<pct>%/<window>`` reading
    is entirely absent (the overlay replaces the composer) AND a rendered
    option-list follows a lone ``>`` filter-input line."""
    if _FOOTER_PCT_RE.search(pane_text):
        return False
    lines = pane_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == ">":
            return any(candidate.strip() for candidate in lines[index + 1 :])
    return False
