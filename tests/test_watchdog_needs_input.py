"""Tests for runtime/watchdog/needs_input.py (needs_input detection + Discord
brief dispatch).

Coverage (T012 acceptance, criterion #5):
- a session not showing ``needs_input`` never dispatches;
- the first poll observing an unanswered needs_input prompt dispatches
  exactly one Discord send (mocked ``alert_fn``) and returns the prompt's
  digest;
- a second, later poll with the identical unanswered prompt (same digest,
  passed back in as ``last_digest``) dispatches zero further sends;
- a poll where the prompt payload changes (different options or question)
  dispatches exactly one new send, with a different digest;
- ``extract_question_and_options`` correctly separates a numbered-option
  menu, a bulleted-option menu, and a bare (no-option) prompt.

Tests never touch a real tmux pane or a real Discord webhook (STYLE.md:T-004
— hermetic): ``adapter``/``alert_fn`` are fakes injected per the module's
dependency-injection seam.
"""

from __future__ import annotations

import pytest

from runtime.watchdog import needs_input, registry


class _FakeAdapter:
    """Minimal ``HostAdapter`` stand-in; only ``needs_input`` is exercised
    by ``needs_input.py``."""

    host = "claude"

    def __init__(self, is_needs_input: bool = True) -> None:
        self._is_needs_input = is_needs_input

    def read_context(self, transcript_path, offset, *, window_tokens):  # pragma: no cover
        raise NotImplementedError

    def injection_ready(self, pane_text: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def needs_input(self, pane_text: str) -> bool:
        return self._is_needs_input

    def handoff_command(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def clear_command(self) -> str:  # pragma: no cover
        raise NotImplementedError


class _RecordingAlert:
    """Fake ``notify.send_needs_input_alert`` stand-in that records every call."""

    def __init__(self, result: bool = True) -> None:
        self.calls: list[tuple[str, str, tuple]] = []
        self._result = result

    def __call__(self, session_label: str, question: str, options=(), **kwargs) -> bool:
        self.calls.append((session_label, question, tuple(options)))
        return self._result


def _record() -> dict:
    return registry.new_session_record(
        "session-watchdog",
        "/plans/session-watchdog",
        "claude",
        "zw-session-watchdog-abcd1234",
        "/tmp/transcript.jsonl",
        now="2026-07-10T12:00:00Z",
    )


PANE_NUMBERED = """\
  Select Model and Effort

› 1. gpt-5.5 (default)
  2. gpt-5.4
  3. gpt-5.4-mini

  Press enter to confirm or esc to go back
"""

PANE_NUMBERED_CHANGED = """\
  Select Model and Effort

› 1. gpt-5.5 (default)
  2. gpt-5.4
  3. gpt-6.0-preview

  Press enter to confirm or esc to go back
"""

PANE_BULLETED = """\
Pick a target branch:

- main
- feature-x
- release-1.0
"""

PANE_BARE_PROMPT = """\
Continue with this plan? (y/n)
"""


# ── evaluate_needs_input: gating on adapter.needs_input ─────────────────────

def test_not_needs_input_never_dispatches() -> None:
    alert_fn = _RecordingAlert()
    result = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED,
        adapter=_FakeAdapter(is_needs_input=False),
        last_digest=None,
        alert_fn=alert_fn,
    )
    assert result["action"] == "skip"
    assert result["sent"] is False
    assert result["digest"] is None
    assert alert_fn.calls == []


# ── first poll: exactly one send ─────────────────────────────────────────────

def test_first_poll_of_unanswered_prompt_dispatches_exactly_one_send() -> None:
    alert_fn = _RecordingAlert()
    result = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED,
        adapter=_FakeAdapter(),
        last_digest=None,
        alert_fn=alert_fn,
    )
    assert result["action"] == "sent"
    assert result["sent"] is True
    assert len(alert_fn.calls) == 1
    session_label, question, options = alert_fn.calls[0]
    assert session_label == "zw-session-watchdog-abcd1234"
    assert question == "Select Model and Effort"
    assert options == ("gpt-5.5 (default)", "gpt-5.4", "gpt-5.4-mini")
    assert result["digest"] is not None


# ── second poll, identical prompt: zero further sends ────────────────────────

def test_second_poll_identical_prompt_dispatches_zero_further_sends() -> None:
    alert_fn = _RecordingAlert()
    first = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED,
        adapter=_FakeAdapter(),
        last_digest=None,
        alert_fn=alert_fn,
    )
    assert len(alert_fn.calls) == 1

    second = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED,
        adapter=_FakeAdapter(),
        last_digest=first["digest"],
        alert_fn=alert_fn,
    )
    assert second["action"] == "skip"
    assert second["sent"] is False
    assert second["digest"] == first["digest"]
    # Still exactly one send total across both polls.
    assert len(alert_fn.calls) == 1


# ── poll with a changed prompt payload: exactly one new send ────────────────

def test_changed_prompt_payload_dispatches_exactly_one_new_send() -> None:
    alert_fn = _RecordingAlert()
    first = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED,
        adapter=_FakeAdapter(),
        last_digest=None,
        alert_fn=alert_fn,
    )
    assert len(alert_fn.calls) == 1

    second = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED_CHANGED,
        adapter=_FakeAdapter(),
        last_digest=first["digest"],
        alert_fn=alert_fn,
    )
    assert second["action"] == "sent"
    assert second["sent"] is True
    assert second["digest"] != first["digest"]
    assert len(alert_fn.calls) == 2


# ── alert_fn failure: digest still updates so a failed send is not retried
#    forever against the same unanswered prompt ──────────────────────────────

def test_alert_send_failure_still_updates_digest() -> None:
    alert_fn = _RecordingAlert(result=False)
    result = needs_input.evaluate_needs_input(
        _record(),
        pane_text=PANE_NUMBERED,
        adapter=_FakeAdapter(),
        last_digest=None,
        alert_fn=alert_fn,
    )
    assert result["action"] == "send_failed"
    assert result["sent"] is False
    assert result["digest"] is not None
    assert len(alert_fn.calls) == 1


# ── extract_question_and_options ─────────────────────────────────────────────

def test_extract_numbered_options() -> None:
    question, options = needs_input.extract_question_and_options(PANE_NUMBERED)
    assert question == "Select Model and Effort"
    assert options == ["gpt-5.5 (default)", "gpt-5.4", "gpt-5.4-mini"]


def test_extract_bulleted_options() -> None:
    question, options = needs_input.extract_question_and_options(PANE_BULLETED)
    assert question == "Pick a target branch:"
    assert options == ["main", "feature-x", "release-1.0"]


def test_extract_bare_prompt_has_no_options() -> None:
    question, options = needs_input.extract_question_and_options(PANE_BARE_PROMPT)
    assert question == "Continue with this plan? (y/n)"
    assert options == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
