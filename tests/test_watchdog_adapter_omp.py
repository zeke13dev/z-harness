"""Tests for runtime/watchdog/adapters/omp.py (session-watchdog, T009).

Coverage (T009 acceptance, criterion #10):
- context read: a nominal usage reading whose model resolves against the
  injected model-context-window map yields a confident reading (real numbers
  from ``tests/fixtures/watchdog/omp/usage_nominal.json``);
- context read: a usable reading whose model is NOT in the map degrades to
  the byte-length fallback estimator (HOST_MECHANICS.md's documented
  last-resort fallback for an unresolvable model id);
- context read: an error-terminated/zeroed usage reading (real fixture
  ``usage_missing_or_degraded.json``) also degrades to the byte-length
  fallback rather than reporting a false 0%;
- context read: no assistant message in the chunk is the ``context_unknown``
  sentinel, not a fallback;
- context read: missing file and a malformed complete line both degrade to
  ``context_unknown`` rather than raising;
- ``context_estimate_degraded_signal`` builds the shaped payload dict a
  caller appends via ``registry.append_signal``;
- the dual-condition (percentage-present AND no-busy-marker) injection_ready/
  needs_input gate, plus the omp-specific selection-overlay needs_input path,
  using pane text mirroring the real captures in
  ``tests/fixtures/watchdog/omp/prompt_ready_pane.txt``;
- handoff/clear command mapping for the omp host.

Tests are hermetic (STYLE.md:T-004): transcripts are built in ``tmp_path``,
no real ``~/.omp/agent`` path is touched.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from runtime.watchdog import registry
from runtime.watchdog.adapters import omp

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "watchdog" / "omp"

_WINDOW_FALLBACK = 999999
_GPT_55_WINDOW = 200000  # real value observed via `omp models` (HOST_MECHANICS.md [O-5]).


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


# ── host identity ─────────────────────────────────────────────────────────────


def test_omp_adapter_host_matches_registry_valid_hosts() -> None:
    assert omp.OmpAdapter.host == "omp"
    assert omp.OmpAdapter.host in registry.VALID_HOSTS


# ── read_context: nominal usage read, model resolves ─────────────────────────


def test_read_context_nominal_resolves_model_window(tmp_path: Path) -> None:
    fixture = _load_fixture("usage_nominal.json")
    target = tmp_path / "session.jsonl"
    target.write_text(json.dumps(fixture["assistant_message_with_usage"]) + "\n")

    adapter = omp.OmpAdapter(model_context_windows={"gpt-5.5": _GPT_55_WINDOW})
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW_FALLBACK)

    expected_total = fixture["assistant_message_with_usage"]["message"]["usage"]["totalTokens"]
    assert expected_total == 31119  # hand-verified against the real capture.
    assert reading.used_tokens == expected_total
    assert reading.window_tokens == _GPT_55_WINDOW  # the real per-model window, not the fallback.
    assert reading.pct_used == pytest.approx(expected_total / _GPT_55_WINDOW * 100)
    assert reading.new_offset == target.stat().st_size
    assert reading.degraded is False


# ── read_context: usable reading, model NOT in the cached map ────────────────


def test_read_context_unresolved_model_falls_back_degraded(tmp_path: Path) -> None:
    fixture = _load_fixture("usage_nominal.json")
    target = tmp_path / "session.jsonl"
    target.write_text(json.dumps(fixture["assistant_message_with_usage"]) + "\n")

    adapter = omp.OmpAdapter(model_context_windows={})  # "gpt-5.5" unresolved.
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW_FALLBACK)

    assert reading.degraded is True
    assert reading.window_tokens == _WINDOW_FALLBACK  # caller-supplied fallback denominator.
    expected_used = math.ceil(reading.new_offset / omp._CONSERVATIVE_BYTES_PER_TOKEN)
    assert reading.used_tokens == expected_used
    assert reading.pct_used == pytest.approx(expected_used / _WINDOW_FALLBACK * 100)


# ── read_context: error-terminated/zeroed usage falls back, never false 0% ───


def test_read_context_error_terminated_usage_falls_back_degraded_never_zero(
    tmp_path: Path,
) -> None:
    fixture = _load_fixture("usage_missing_or_degraded.json")
    record = {"type": "message", "message": fixture["example_1"]["message"]}
    target = tmp_path / "session.jsonl"
    target.write_text(json.dumps(record) + "\n")

    adapter = omp.OmpAdapter(model_context_windows={"gpt-5.5": _GPT_55_WINDOW})
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW_FALLBACK)

    assert reading.used_tokens is not None  # never a bare context_unknown here.
    assert reading.pct_used is not None
    assert reading.used_tokens > 0  # never reports 0% for a completed (errored) turn.
    assert reading.degraded is True
    assert reading.new_offset == target.stat().st_size

    expected_used = math.ceil(reading.new_offset / omp._CONSERVATIVE_BYTES_PER_TOKEN)
    assert reading.used_tokens == expected_used
    assert reading.pct_used == pytest.approx(expected_used / _WINDOW_FALLBACK * 100)


# ── read_context: no assistant message yet -> context_unknown, not fallback ──


def test_read_context_no_assistant_message_is_context_unknown_not_fallback(
    tmp_path: Path,
) -> None:
    target = tmp_path / "session.jsonl"
    target.write_text(
        json.dumps({"type": "session", "version": 3, "id": "abc"}) + "\n"
    )

    adapter = omp.OmpAdapter(model_context_windows={"gpt-5.5": _GPT_55_WINDOW})
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW_FALLBACK)

    assert reading.used_tokens is None
    assert reading.pct_used is None
    assert reading.degraded is False
    assert reading.new_offset == target.stat().st_size


def test_read_context_missing_file_returns_context_unknown(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.jsonl"
    adapter = omp.OmpAdapter()
    reading = adapter.read_context(str(missing), 5, window_tokens=_WINDOW_FALLBACK)
    assert reading.new_offset == 5  # unchanged — nothing was consumed.
    assert reading.used_tokens is None
    assert reading.pct_used is None
    assert reading.degraded is False


def test_read_context_malformed_complete_line_skipped_context_unknown(
    tmp_path: Path,
) -> None:
    target = tmp_path / "session.jsonl"
    target.write_text(
        json.dumps({"type": "session", "version": 3, "id": "abc"}) + "\n"
        + "{not valid json at all\n"
    )

    adapter = omp.OmpAdapter(model_context_windows={"gpt-5.5": _GPT_55_WINDOW})
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW_FALLBACK)

    assert reading.used_tokens is None
    assert reading.pct_used is None
    assert reading.degraded is False
    # Both lines carried their newline terminator, so both are consumed.
    assert reading.new_offset == target.stat().st_size


# ── context_estimate_degraded_signal ──────────────────────────────────────────


def test_context_estimate_degraded_signal_shape(tmp_path: Path) -> None:
    fixture = _load_fixture("usage_nominal.json")
    target = tmp_path / "session.jsonl"
    target.write_text(json.dumps(fixture["assistant_message_with_usage"]) + "\n")

    adapter = omp.OmpAdapter(model_context_windows={})  # forces the degraded path.
    reading = adapter.read_context(str(target), 0, window_tokens=_WINDOW_FALLBACK)
    assert reading.degraded is True

    payload = omp.context_estimate_degraded_signal(reading)
    assert payload == {
        "host": "omp",
        "used_tokens": reading.used_tokens,
        "window_tokens": reading.window_tokens,
        "pct_used": reading.pct_used,
    }

    # The caller can append it verbatim via registry.append_signal.
    signals_path = tmp_path / "signals.jsonl"
    registry.append_signal(signals_path, "context_estimate_degraded", payload, max_mb=1)
    lines = signals_path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "context_estimate_degraded"
    assert record["payload"] == payload


# ── injection-ready / needs_input dual-condition gate + selection overlay ────
# Pane text mirrors the real captures in
# tests/fixtures/watchdog/omp/prompt_ready_pane.txt.

_STATE1_IDLE_READY_PANE = "\n".join(
    [
        "╭──     GPT-5.5 ·  med   scratchpad   9.4%/272K 󰁨  (sub) ──────────────────────╮",
        "╰─                                                                            ─╯",
    ]
)

_STATE2_BUSY_PANE = "\n".join(
    [
        " ⠼ Working… ⟨esc⟩",
        "",
        "╭──     GPT-5.5 ·  med   scratchpad   10.1%/272K 󰁨  (sub) ─── Reply Pong ──╮",
        "╰─                                                                        ─╯",
    ]
)

_STATE3_SELECTION_OVERLAY_PANE = "\n".join(
    [
        "Models:   ALL    CANONICAL    CURSOR    NVIDIA NIM    OLLAMA",
        "",
        ">",
        "",
        " openai-codex/gpt-5.5  DEFAULT  (medium) [SMOL auto] (medium)",
        "  cursor/gpt-5.6-luna-high",
        "  cursor/gpt-5.6-luna-high-fast",
    ]
)


def test_state1_idle_ready_pane_is_injection_ready_and_needs_input() -> None:
    adapter = omp.OmpAdapter()
    assert adapter.injection_ready(_STATE1_IDLE_READY_PANE) is True
    assert adapter.needs_input(_STATE1_IDLE_READY_PANE) is True


def test_state2_busy_pane_is_neither_ready_nor_needs_input_despite_percentage() -> None:
    # The critical regression this adapter must guard: the footer percentage
    # is STILL present while busy -- percentage alone must not be sufficient.
    adapter = omp.OmpAdapter()
    assert "%/" in _STATE2_BUSY_PANE  # sanity: percentage really is present.
    assert adapter.injection_ready(_STATE2_BUSY_PANE) is False
    assert adapter.needs_input(_STATE2_BUSY_PANE) is False


def test_state3_selection_overlay_is_needs_input_but_not_injection_ready() -> None:
    adapter = omp.OmpAdapter()
    assert adapter.injection_ready(_STATE3_SELECTION_OVERLAY_PANE) is False
    assert adapter.needs_input(_STATE3_SELECTION_OVERLAY_PANE) is True


def test_bare_gt_glyph_alone_without_option_list_is_not_needs_input() -> None:
    # Guards HOST_MECHANICS.md's warning: a `>` glyph must not be keyed off
    # alone -- it must be followed by a rendered option list.
    adapter = omp.OmpAdapter()
    lone_filter_no_options = "Models:   ALL\n\n>\n"
    assert adapter.needs_input(lone_filter_no_options) is False


# ── handoff/clear command mapping ─────────────────────────────────────────────


def test_handoff_and_clear_commands() -> None:
    adapter = omp.OmpAdapter()
    assert adapter.handoff_command() == "/z-handoff"
    assert adapter.clear_command() == "/new"
