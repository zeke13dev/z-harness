"""``claude`` ``HostAdapter`` implementation for the session-watchdog daemon.

Purpose (T005, criterion #10): implement the four ``HostAdapter`` capabilities
against the ``~/.claude/projects/<project-slug>/<session-id>.jsonl`` transcript
contract and the so-MCP reference's prompt-glyph gate
(``scripts/hermes/mcp_hermes_orchestrator.py:534-563``, read-only reference,
never imported — INTENT "Not doing": so-MCP stays untouched as reference
material only).

Transcript usage contract (precheck-verified against a real, redacted
transcript excerpt — see ``tests/fixtures/watchdog/claude/PROVENANCE.txt``):
each turn's assistant message carries ``message.usage`` with
``input_tokens`` / ``cache_read_input_tokens`` / ``cache_creation_input_tokens``
/ ``output_tokens`` as top-level integer fields. Non-assistant lines (``mode``,
``user``, tool-result lines) carry no such object and are skipped.

Design decisions:
- Effective used tokens = ``input_tokens + cache_read_input_tokens +
  cache_creation_input_tokens + output_tokens`` (recorded in LEDGER.md): the
  first three fields are exactly the prompt Anthropic billed for this turn
  (new + cache-hit + cache-write context); adding ``output_tokens`` reflects
  the context size the *next* turn will actually see once this turn's
  response is appended to history. Per ``HOST_MECHANICS.md``'s stated bias
  ("an under-report... can suppress or delay a real context-threshold
  handoff trigger"), including ``output_tokens`` is the more conservative
  (higher) reading, not the leaner one — it never under-counts.
- ``injection_ready`` and ``needs_input`` share one detector
  (``_prompt_glyph_ready``) for claude specifically: claude's composer glyph
  disappears entirely while generating and reappears the instant the pane is
  safe to type into AND the human's turn is expected — the same signal
  answers both questions for this host. ``HOST_MECHANICS.md`` documents that
  ``omp`` and ``codex`` diverge (omp needs a footer-percentage + busy-marker
  conjunction; codex needs an extra menu-footer phrase) — this is why
  ``base.py`` keeps the two as distinct interface methods despite claude's
  adapter collapsing them.
"""

from __future__ import annotations

import json

from runtime.watchdog.adapters.base import ContextReading, HostAdapter

_USAGE_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)

HANDOFF_COMMAND = "/z-handoff"
"""The z-harness handoff skill — host-agnostic by construction (a normal
slash-command prompt), invoked identically across claude/codex/omp."""

CLEAR_COMMAND = "/clear"
"""Claude Code's built-in clear-equivalent slash command."""


class ClaudeAdapter(HostAdapter):
    """``HostAdapter`` for the ``claude`` host (Claude Code CLI)."""

    host = "claude"

    def read_context(
        self, transcript_path: str, offset: int, *, window_tokens: int
    ) -> ContextReading:
        """See ``HostAdapter.read_context``.

        Seeks to ``offset``, reads to EOF, and consumes only complete
        (newline-terminated) lines — a dangling partial tail (a write still
        in flight) is left unconsumed so the next read re-attempts it whole
        rather than parsing a truncated fragment. A syntactically malformed
        *complete* line (has its trailing newline but is not valid JSON, or
        lacks the expected ``message.usage`` shape) is skipped rather than
        raising; its bytes are still consumed since it will never become
        valid. The usage reading itself is taken from the newest
        successfully-parsed assistant line in this read; if none qualifies,
        ``used_tokens``/``pct_used`` are ``None`` (context_unknown for this
        cycle) per the interface contract in ``base.py``.
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

        last_usage: dict[str, int] | None = None
        for raw_line in consumed.split(b"\n"):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue  # malformed complete line — skip, never raise.
            usage = _extract_usage(record)
            if usage is not None:
                last_usage = usage  # append-only file: later = newer.

        if last_usage is None:
            return ContextReading(
                new_offset=new_offset,
                used_tokens=None,
                window_tokens=window_tokens,
                pct_used=None,
            )

        used_tokens = sum(last_usage[field] for field in _USAGE_FIELDS)
        pct_used = (used_tokens / window_tokens) * 100
        return ContextReading(
            new_offset=new_offset,
            used_tokens=used_tokens,
            window_tokens=window_tokens,
            pct_used=pct_used,
        )

    def injection_ready(self, pane_text: str) -> bool:
        """See ``HostAdapter.injection_ready``; see module docstring for why
        this coincides with ``needs_input`` on claude."""
        return _prompt_glyph_ready(pane_text)

    def needs_input(self, pane_text: str) -> bool:
        """See ``HostAdapter.needs_input``; see module docstring for why
        this coincides with ``injection_ready`` on claude."""
        return _prompt_glyph_ready(pane_text)

    def handoff_command(self) -> str:
        return HANDOFF_COMMAND

    def clear_command(self) -> str:
        return CLEAR_COMMAND


def _extract_usage(record: object) -> dict[str, int] | None:
    """Return the ``_USAGE_FIELDS`` from ``record`` if it is a well-formed
    assistant usage line; ``None`` otherwise (not an assistant line, no
    ``message.usage`` object, or a non-int field)."""
    if not isinstance(record, dict) or record.get("type") != "assistant":
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    if not all(isinstance(usage.get(field), int) for field in _USAGE_FIELDS):
        return None
    return {field: usage[field] for field in _USAGE_FIELDS}


def _prompt_glyph_ready(pane_text: str) -> bool:
    """Reimplementation of so-MCP's ``_needs_input()``
    (``mcp_hermes_orchestrator.py:534-563``, read-only reference, never
    imported), adjusted for Claude Code's statusline footer: the idle
    composer glyph ``❯`` (or a bare ``>`` continuation glyph) may sit up to
    ~4 non-blank lines above the pane bottom because the current UI renders
    a separator + model line + mode footer BELOW the composer (found live,
    2026-07-11 session-watchdog smoke test — the original last-3 window
    missed a genuinely idle pane). The glyph scan therefore covers the last
    6 non-blank lines, and a visible busy marker ("esc to interrupt")
    anywhere in that window wins over the glyph: a working session can
    still render the composer glyph above its spinner. A still-visible
    selection-menu footer ("enter select" / "esc cancel") in the last 8
    non-blank lines also counts as ready/needs-input.
    """
    lines = [line.rstrip() for line in pane_text.strip().splitlines() if line.strip()]
    for line in lines[-8:]:
        low = line.strip().lower()
        if "esc to interrupt" in low:
            return False
    for line in lines[-6:]:
        stripped = line.strip()
        if stripped.endswith("❯") or stripped.endswith(">"):
            return True
    for line in lines[-8:]:
        low = line.strip().lower()
        if "enter select" in low or "esc cancel" in low:
            return True
    return False
