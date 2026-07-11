"""``codex`` ``HostAdapter`` implementation for the session-watchdog daemon.

Purpose (T008, criterion #10): implement the four ``HostAdapter`` capabilities
against the codex CLI's rollout transcript
(``~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<session-id>.jsonl``) and
prompt/menu mechanics, per the grounded findings in
``runtime/watchdog/HOST_MECHANICS.md`` (READ FIRST) and the fixtures under
``tests/fixtures/watchdog/codex/``.

Transcript usage contract: a turn's usage is reported by a standalone
``event_msg`` line whose ``payload.type == "token_count"`` carries
``payload.info.total_token_usage.total_tokens`` — a self-contained reading,
unlike ``claude``'s per-assistant-message ``usage`` object. Critically, a
turn can complete (``event_msg`` with ``payload.type == "task_complete"``)
with **zero** preceding ``token_count`` events anywhere in the file (real
fixture: ``tests/fixtures/watchdog/codex/task_complete_missing_usage.json``)
— this is not an error state, it must degrade to the byte-length fallback
estimator documented below rather than raise or report a false 0%.

Design decisions:
- Denominator stays ``window_tokens`` (caller-supplied), matching the
  ``HostAdapter`` contract T005 established for ``claude`` — codex's
  transcript also carries a ``model_context_window`` field per-event, but
  using it here would make the pct-used formula host-specific; the poll
  loop already resolves one ``watchdog.context_window_tokens`` value and
  passes it to every adapter uniformly.
- Fallback estimator (HOST_MECHANICS.md): when a read's newly-consumed
  chunk contains a completed turn (``task_complete``) but no
  ``token_count`` event, ``used_tokens`` is estimated as
  ``bytes_since_session_start / average_bytes_per_token`` using a
  deliberately conservative (smaller than the ~4-bytes/token nominal
  English-text average) constant so the estimate biases toward
  *over*-reporting usage — an under-report is the dangerous direction
  (it can suppress or delay a real context-threshold handoff trigger).
  The reading is flagged ``degraded=True`` (see ``base.ContextReading``)
  so the caller never treats it as equivalent to a real ``token_count``
  read.
- When neither a ``token_count`` event nor a ``task_complete`` event
  appears in the newly-consumed chunk (a turn still in progress), the read
  is genuinely inconclusive this cycle — same ``context_unknown`` sentinel
  ``claude.py`` uses (``used_tokens``/``pct_used`` both ``None``,
  ``degraded=False``), not a fallback estimate.
- ``injection_ready`` keys off the leading ``›`` glyph (U+203A) that marks
  both the idle composer (STATE 1) and a highlighted menu row (STATE 2) in
  ``tests/fixtures/watchdog/codex/prompt_ready_pane.txt`` — HOST_MECHANICS.md
  documents both under the same "prompt-glyph for input-ready detection"
  heading. ``needs_input`` is a separate, codex-specific footer-phrase
  matcher ("press enter to confirm" / "esc to go back") since codex's menu
  footer text does not match the omp-tuned substrings
  (``"enter select"`` / ``"esc cancel"``) the so-MCP reference hard-codes —
  this is the documented divergence ``base.py`` anticipated when it kept
  the two capabilities as distinct interface methods.
"""

from __future__ import annotations

import json
import math

from runtime.watchdog.adapters.base import ContextReading, HostAdapter

HANDOFF_COMMAND = "/z-handoff"
"""The z-harness handoff skill — host-agnostic by construction (a normal
slash-command prompt), invoked identically across claude/codex/omp."""

CLEAR_COMMAND = "/new"
"""codex's clear-equivalent: "start a new chat during a conversation"
(HOST_MECHANICS.md; observed live, no confirmation dialog)."""

_READY_GLYPH = "›"
"""codex's input-ready / highlighted-menu-row leading glyph (U+203A)."""

_MENU_FOOTER_PHRASES: tuple[str, ...] = (
    "press enter to confirm",
    "esc to go back",
)
"""codex's interactive-selection-menu footer text — distinct from the
omp-tuned ``"enter select"``/``"esc cancel"`` substrings."""

_CONSERVATIVE_BYTES_PER_TOKEN = 3.0
"""Deliberately smaller than the ~4-bytes/token nominal English-text/code
average so the degraded byte-length fallback estimate biases toward
*over*-reporting token usage (the safe direction) rather than under-
reporting it (HOST_MECHANICS.md)."""


class CodexAdapter(HostAdapter):
    """``HostAdapter`` for the ``codex`` host (codex CLI)."""

    host = "codex"

    def read_context(
        self, transcript_path: str, offset: int, *, window_tokens: int
    ) -> ContextReading:
        """See ``HostAdapter.read_context``.

        Mirrors ``claude.ClaudeAdapter.read_context``'s incremental,
        complete-lines-only read shape (seek to ``offset``, consume only
        newline-terminated lines, leave a dangling in-flight tail
        unconsumed). Within the newly-consumed chunk: a ``token_count``
        event yields a confident reading; a completed turn
        (``task_complete``) with no ``token_count`` event yields a degraded
        byte-length estimate; neither yields the ``context_unknown``
        sentinel. A malformed complete line is skipped (never raises).
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

        last_total_tokens: int | None = None
        saw_task_complete = False
        for raw_line in consumed.split(b"\n"):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue  # malformed complete line — skip, never raise.
            total_tokens = _extract_token_count_total(record)
            if total_tokens is not None:
                last_total_tokens = total_tokens  # append-only: later = newer.
            if _is_task_complete(record):
                saw_task_complete = True

        if last_total_tokens is not None:
            pct_used = (last_total_tokens / window_tokens) * 100
            return ContextReading(
                new_offset=new_offset,
                used_tokens=last_total_tokens,
                window_tokens=window_tokens,
                pct_used=pct_used,
                degraded=False,
            )

        if saw_task_complete:
            # A turn completed with zero token_count events since offset —
            # "no reading yet", not an error. Fall back to the degraded
            # byte-length estimator rather than raising or reporting 0%.
            used_tokens = _byte_length_fallback_tokens(new_offset)
            pct_used = (used_tokens / window_tokens) * 100
            return ContextReading(
                new_offset=new_offset,
                used_tokens=used_tokens,
                window_tokens=window_tokens,
                pct_used=pct_used,
                degraded=True,
            )

        return ContextReading(
            new_offset=new_offset,
            used_tokens=None,
            window_tokens=window_tokens,
            pct_used=None,
            degraded=False,
        )

    def injection_ready(self, pane_text: str) -> bool:
        """See ``HostAdapter.injection_ready``; see module docstring for the
        shared idle-composer/menu-row glyph signal."""
        lines = [line.rstrip() for line in pane_text.strip().splitlines() if line.strip()]
        return any(line.strip().startswith(_READY_GLYPH) for line in lines[-8:])

    def needs_input(self, pane_text: str) -> bool:
        """See ``HostAdapter.needs_input``; matches codex's own
        interactive-selection-menu footer phrasing (distinct from omp's)."""
        lines = [line.rstrip() for line in pane_text.strip().splitlines() if line.strip()]
        for line in lines[-8:]:
            low = line.strip().lower()
            if any(phrase in low for phrase in _MENU_FOOTER_PHRASES):
                return True
        return False

    def handoff_command(self) -> str:
        return HANDOFF_COMMAND

    def clear_command(self) -> str:
        return CLEAR_COMMAND


def _extract_token_count_total(record: object) -> int | None:
    """Return ``payload.info.total_token_usage.total_tokens`` from ``record``
    if it is a well-formed ``token_count`` event_msg line; ``None``
    otherwise (not an event_msg, not a token_count payload, or a malformed/
    non-int total)."""
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    total_usage = info.get("total_token_usage")
    if not isinstance(total_usage, dict):
        return None
    total_tokens = total_usage.get("total_tokens")
    if not isinstance(total_tokens, int):
        return None
    return total_tokens


def _is_task_complete(record: object) -> bool:
    """Return whether ``record`` is a ``task_complete`` event_msg line."""
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return False
    payload = record.get("payload")
    return isinstance(payload, dict) and payload.get("type") == "task_complete"


def _byte_length_fallback_tokens(bytes_since_session_start: int) -> int:
    """Degraded, upward-biased token estimate from raw transcript bytes
    (HOST_MECHANICS.md) — used only when no ``token_count`` event exists
    yet for a completed turn."""
    return math.ceil(bytes_since_session_start / _CONSERVATIVE_BYTES_PER_TOKEN)
