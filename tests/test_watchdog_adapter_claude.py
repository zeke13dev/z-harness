"""Tests for runtime/watchdog/adapters/{base,claude}.py (session-watchdog).

Coverage (T005 acceptance, criterion #10):
- context read against a real (redacted) ``~/.claude/projects`` transcript
  excerpt (``tests/fixtures/watchdog/claude/``), asserting the computed
  used-tokens/pct against hand-verified sums of the fixture's real usage
  numbers (see ``PROVENANCE.txt``);
- append-then-reread-from-offset: a spy on the module's ``open`` proves the
  second read only consumes the newly-appended bytes (D2 — never re-reads
  the whole file), not just that the output happens to be correct;
- malformed/truncated trailing line tolerance: an unterminated tail is left
  unconsumed (offset stops before it, re-attempted on the next read) and a
  terminated-but-invalid line is skipped without raising, correctly falling
  back to the ``context_unknown`` sentinel (``used_tokens``/``pct_used`` are
  ``None``) when no valid usage line is found;
- the prompt-glyph injection gate / needs_input detector (reimplemented from
  ``mcp_hermes_orchestrator.py:534-563``, read-only reference, never
  imported) across an idle-prompt pane, a busy/thinking pane, and a
  selection-menu pane;
- handoff/clear command mapping for the claude host.

Tests are hermetic (STYLE.md:T-004): fixtures are copied into ``tmp_path``
before mutation, no real ``~/.claude/projects`` path is touched.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from runtime.watchdog import registry
from runtime.watchdog.adapters import base
from runtime.watchdog.adapters import claude

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "watchdog" / "claude"

# Hand-verified sums of the real usage numbers copied into the fixtures (see
# PROVENANCE.txt) — input_tokens + cache_creation_input_tokens +
# cache_read_input_tokens + output_tokens for each fixture's newest line.
_NOMINAL_LAST_USAGE = 2 + 826 + 173301 + 1115  # == 175244
_APPENDED_USAGE = 131 + 2296 + 261843 + 2451  # == 266721
_FIRST_LINE_USAGE = 17809 + 11121 + 25725 + 255  # == 54910

_WINDOW = 200000


# ── HostAdapter seam (base.py) ────────────────────────────────────────────────


def test_host_adapter_is_abstract() -> None:
    with pytest.raises(TypeError):
        base.HostAdapter()  # type: ignore[abstract]


def test_claude_adapter_host_matches_registry_valid_hosts() -> None:
    assert claude.ClaudeAdapter.host == "claude"
    assert claude.ClaudeAdapter.host in registry.VALID_HOSTS


# ── read_context: nominal usage read ──────────────────────────────────────────


def test_read_context_nominal_usage_read(tmp_path: Path) -> None:
    target = tmp_path / "transcript.jsonl"
    target.write_bytes((FIXTURES_DIR / "transcript_nominal.jsonl").read_bytes())

    adapter = claude.ClaudeAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    assert reading.used_tokens == _NOMINAL_LAST_USAGE
    assert reading.pct_used == pytest.approx(_NOMINAL_LAST_USAGE / _WINDOW * 100)
    assert reading.window_tokens == _WINDOW
    assert reading.new_offset == target.stat().st_size


def test_read_context_missing_file_returns_context_unknown(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.jsonl"
    adapter = claude.ClaudeAdapter()
    reading = adapter.read_context(str(missing), 5, window_tokens=_WINDOW)
    assert reading.new_offset == 5  # unchanged — nothing was consumed.
    assert reading.used_tokens is None
    assert reading.pct_used is None


# ── read_context: append-then-reread-from-offset (D2) ────────────────────────


def test_read_context_append_then_reread_from_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "transcript.jsonl"
    target.write_bytes((FIXTURES_DIR / "transcript_nominal.jsonl").read_bytes())

    adapter = claude.ClaudeAdapter()
    reading1 = adapter.read_context(str(target), 0, window_tokens=_WINDOW)
    assert reading1.new_offset == target.stat().st_size

    appended_bytes = (FIXTURES_DIR / "transcript_appended_lines.jsonl").read_bytes()
    with open(target, "ab") as handle:
        handle.write(appended_bytes)

    # Spy on the module's `open` to record exactly how many bytes each
    # `.read()` call against `target` returned — proves the second call only
    # consumed the newly-appended bytes, not the whole (now-larger) file.
    read_sizes: list[int] = []
    real_open = builtins.open

    def _spy_open(path: object, mode: str = "r", *args: object, **kwargs: object):
        handle = real_open(path, mode, *args, **kwargs)  # type: ignore[arg-type]
        if str(path) == str(target) and "b" in mode:
            original_read = handle.read

            def _tracked_read(*read_args: object) -> bytes:
                data = original_read(*read_args)
                read_sizes.append(len(data))
                return data

            handle.read = _tracked_read  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(claude, "open", _spy_open, raising=False)
    reading2 = adapter.read_context(str(target), reading1.new_offset, window_tokens=_WINDOW)

    assert read_sizes == [len(appended_bytes)]
    assert reading2.new_offset == reading1.new_offset + len(appended_bytes)
    assert reading2.used_tokens == _APPENDED_USAGE
    assert reading2.pct_used == pytest.approx(_APPENDED_USAGE / _WINDOW * 100)


# ── read_context: malformed / truncated trailing line tolerance ──────────────


def test_read_context_truncated_tail_unconsumed_not_raised(tmp_path: Path) -> None:
    fixture_bytes = (FIXTURES_DIR / "transcript_malformed_tail.jsonl").read_bytes()
    target = tmp_path / "transcript.jsonl"
    target.write_bytes(fixture_bytes)

    adapter = claude.ClaudeAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    last_newline = fixture_bytes.rfind(b"\n")
    assert last_newline != -1
    # The unterminated tail line is left unconsumed — offset stops right
    # after the last COMPLETE line, not at end-of-file.
    assert reading.new_offset == last_newline + 1
    assert reading.new_offset < len(fixture_bytes)
    # The last complete line IS a valid usage line, so this cycle is not
    # context_unknown — the truncated tail is simply held back for later.
    assert reading.used_tokens == _FIRST_LINE_USAGE
    assert reading.pct_used == pytest.approx(_FIRST_LINE_USAGE / _WINDOW * 100)

    # Re-reading at the returned offset (transcript not yet grown further)
    # must not raise and must not advance past the still-incomplete tail.
    reading_again = adapter.read_context(str(target), reading.new_offset, window_tokens=_WINDOW)
    assert reading_again.new_offset == reading.new_offset
    assert reading_again.used_tokens is None
    assert reading_again.pct_used is None


def test_read_context_malformed_complete_line_skipped_context_unknown(tmp_path: Path) -> None:
    # A syntactically invalid line that DOES carry its trailing newline (a
    # genuinely corrupt line, not just an in-flight write) must be skipped —
    # never raise — and, with no other usage-bearing line in this read,
    # falls back to the context_unknown sentinel.
    target = tmp_path / "transcript.jsonl"
    target.write_text(
        json.dumps({"type": "mode", "mode": "default", "sessionId": "s"}) + "\n"
        + "{not valid json at all\n"
    )

    adapter = claude.ClaudeAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    assert reading.used_tokens is None
    assert reading.pct_used is None
    # Both lines carried their newline terminator, so both are consumed —
    # this is "skip and move on", not "hold back and retry".
    assert reading.new_offset == target.stat().st_size


# ── prompt-glyph injection gate / needs_input detection ───────────────────────


_IDLE_PANE = "\n".join(
    [
        "  Wrote 42 lines to foo.py",
        "  Done.",
        "> ",
    ]
)

_BUSY_PANE = "\n".join(
    [
        "⠋ Thinking…",
        "  (esc to interrupt)",
    ]
)

_MENU_PANE = "\n".join(
    [
        "Do you want to proceed?",
        "❯ 1. Yes",
        "  2. No",
        "  (up/down to navigate · enter select · esc cancel)",
    ]
)


def test_idle_pane_is_injection_ready_and_needs_input() -> None:
    adapter = claude.ClaudeAdapter()
    assert adapter.injection_ready(_IDLE_PANE) is True
    assert adapter.needs_input(_IDLE_PANE) is True


def test_busy_pane_is_neither_ready_nor_needs_input() -> None:
    adapter = claude.ClaudeAdapter()
    assert adapter.injection_ready(_BUSY_PANE) is False
    assert adapter.needs_input(_BUSY_PANE) is False


def test_selection_menu_pane_is_ready_and_needs_input_via_footer_hint() -> None:
    adapter = claude.ClaudeAdapter()
    assert adapter.injection_ready(_MENU_PANE) is True
    assert adapter.needs_input(_MENU_PANE) is True


# ── handoff/clear command mapping ─────────────────────────────────────────────


def test_handoff_and_clear_commands() -> None:
    adapter = claude.ClaudeAdapter()
    assert adapter.handoff_command() == "/z-handoff"
    assert adapter.clear_command() == "/clear"
