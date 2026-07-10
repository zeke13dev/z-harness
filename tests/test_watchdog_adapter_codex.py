"""Tests for runtime/watchdog/adapters/codex.py (session-watchdog, T008).

Coverage (T008 acceptance, criterion #10):
- context read: a nominal ``token_count`` event yields a confident reading
  (real numbers from ``tests/fixtures/watchdog/codex/token_count_nominal.json``);
- context read: a completed turn with ZERO ``token_count`` events (real
  fixture ``task_complete_missing_usage.json``) falls back to the degraded
  byte-length estimator — never ``None``/0%, and flagged ``degraded=True``;
- context read: a turn still in progress (no ``token_count``, no
  ``task_complete``) is the ``context_unknown`` sentinel, not a fallback;
- context read: missing file and a malformed complete line both degrade to
  ``context_unknown`` rather than raising;
- the ``›``-glyph injection-ready gate and the codex-specific
  needs_input footer-phrase matcher, using the real captured pane text in
  ``tests/fixtures/watchdog/codex/prompt_ready_pane.txt``;
- handoff/clear command mapping for the codex host.

Tests are hermetic (STYLE.md:T-004): transcripts are built in ``tmp_path``,
no real ``~/.codex/sessions`` path is touched.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from runtime.watchdog import registry
from runtime.watchdog.adapters import codex

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "watchdog" / "codex"

_WINDOW = 200000


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


# ── host identity ─────────────────────────────────────────────────────────────


def test_codex_adapter_host_matches_registry_valid_hosts() -> None:
    assert codex.CodexAdapter.host == "codex"
    assert codex.CodexAdapter.host in registry.VALID_HOSTS


# ── read_context: nominal token_count read ────────────────────────────────────


def test_read_context_nominal_token_count_read(tmp_path: Path) -> None:
    fixture = _load_fixture("token_count_nominal.json")
    lines = (
        json.dumps(fixture["session_meta"]) + "\n"
        + json.dumps(fixture["token_count_event"]) + "\n"
    )
    target = tmp_path / "rollout.jsonl"
    target.write_text(lines)

    adapter = codex.CodexAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    expected_total = fixture["token_count_event"]["payload"]["info"][
        "total_token_usage"
    ]["total_tokens"]
    assert expected_total == 22331  # hand-verified against the real capture.
    assert reading.used_tokens == expected_total
    assert reading.pct_used == pytest.approx(expected_total / _WINDOW * 100)
    assert reading.window_tokens == _WINDOW
    assert reading.new_offset == target.stat().st_size
    assert reading.degraded is False


# ── read_context: completed turn with ZERO token_count events ────────────────


def test_read_context_missing_usage_falls_back_degraded_never_zero(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture("task_complete_missing_usage.json")
    lines = (
        json.dumps(fixture["task_started"]) + "\n"
        + json.dumps(fixture["task_complete_with_no_prior_token_count"]) + "\n"
    )
    target = tmp_path / "rollout.jsonl"
    target.write_text(lines)

    adapter = codex.CodexAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    assert reading.used_tokens is not None  # never a bare context_unknown here.
    assert reading.pct_used is not None
    assert reading.used_tokens > 0  # never reports 0% for a completed turn.
    assert reading.degraded is True  # flagged as a low-confidence estimate.
    assert reading.new_offset == target.stat().st_size

    # The estimate must match the documented degraded byte-length formula
    # exactly (not just be "some positive number") — proves the fallback
    # path actually ran the conservative estimator, not a stray guess.
    expected_used = math.ceil(
        reading.new_offset / codex._CONSERVATIVE_BYTES_PER_TOKEN
    )
    assert reading.used_tokens == expected_used
    assert reading.pct_used == pytest.approx(expected_used / _WINDOW * 100)


def test_read_context_turn_in_progress_is_context_unknown_not_fallback(
    tmp_path: Path,
) -> None:
    # A task_started with no task_complete and no token_count yet must NOT
    # trigger the degraded fallback -- it is genuinely inconclusive this
    # cycle, same as claude's context_unknown sentinel.
    fixture = _load_fixture("task_complete_missing_usage.json")
    target = tmp_path / "rollout.jsonl"
    target.write_text(json.dumps(fixture["task_started"]) + "\n")

    adapter = codex.CodexAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    assert reading.used_tokens is None
    assert reading.pct_used is None
    assert reading.degraded is False
    assert reading.new_offset == target.stat().st_size


def test_read_context_missing_file_returns_context_unknown(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.jsonl"
    adapter = codex.CodexAdapter()
    reading = adapter.read_context(str(missing), 5, window_tokens=_WINDOW)
    assert reading.new_offset == 5  # unchanged — nothing was consumed.
    assert reading.used_tokens is None
    assert reading.pct_used is None
    assert reading.degraded is False


def test_read_context_malformed_complete_line_skipped_context_unknown(
    tmp_path: Path,
) -> None:
    target = tmp_path / "rollout.jsonl"
    target.write_text(
        json.dumps({"type": "session_meta", "payload": {}}) + "\n"
        + "{not valid json at all\n"
    )

    adapter = codex.CodexAdapter()
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW)

    assert reading.used_tokens is None
    assert reading.pct_used is None
    assert reading.degraded is False
    # Both lines carried their newline terminator, so both are consumed.
    assert reading.new_offset == target.stat().st_size


# ── injection-ready glyph / needs_input footer-phrase matcher ─────────────────
# Real captured panes from tests/fixtures/watchdog/codex/prompt_ready_pane.txt.

_READY_COMPOSER_PANE = "\n".join(
    [
        "› Write tests for @filename",
        "",
        "  gpt-5.5 medium · /private/tmp/scratchpad",
    ]
)

_SELECTION_MENU_PANE = "\n".join(
    [
        "  Select Model and Effort",
        "  Access legacy models by running codex -m <model_name> or in your config.toml",
        "",
        "› 1. gpt-5.5 (default)    Frontier model for complex coding, research, and real-world work.",
        "  2. gpt-5.4              Strong model for everyday coding.",
        "  3. gpt-5.4-mini         Small, fast, and cost-efficient model for simpler coding tasks.",
        "  4. gpt-5.3-codex-spark  Ultra-fast coding model.",
        "",
        "  Press enter to confirm or esc to go back",
    ]
)

_BUSY_PANE = "\n".join(
    [
        "  Reading files…",
        "  (esc to interrupt)",
    ]
)


def test_ready_composer_pane_is_injection_ready_not_needs_input() -> None:
    adapter = codex.CodexAdapter()
    assert adapter.injection_ready(_READY_COMPOSER_PANE) is True
    assert adapter.needs_input(_READY_COMPOSER_PANE) is False


def test_selection_menu_pane_is_injection_ready_and_needs_input() -> None:
    adapter = codex.CodexAdapter()
    assert adapter.injection_ready(_SELECTION_MENU_PANE) is True
    assert adapter.needs_input(_SELECTION_MENU_PANE) is True


def test_busy_pane_is_neither_ready_nor_needs_input() -> None:
    adapter = codex.CodexAdapter()
    assert adapter.injection_ready(_BUSY_PANE) is False
    assert adapter.needs_input(_BUSY_PANE) is False


def test_omp_tuned_footer_substrings_alone_do_not_match_codex_menu() -> None:
    # Guards the documented divergence: codex's real menu footer text
    # ("press enter to confirm"/"esc to go back") must be matched
    # explicitly -- it does not share substrings with the omp-tuned
    # "enter select"/"esc cancel" phrases the so-MCP reference hard-codes.
    omp_style_pane = "\n".join(
        [
            "❯ 1. Yes",
            "  2. No",
            "  (up/down to navigate · enter select · esc cancel)",
        ]
    )
    adapter = codex.CodexAdapter()
    assert adapter.needs_input(omp_style_pane) is False


# ── handoff/clear command mapping ─────────────────────────────────────────────


def test_handoff_and_clear_commands() -> None:
    adapter = codex.CodexAdapter()
    assert adapter.handoff_command() == "/z-handoff"
    assert adapter.clear_command() == "/new"
