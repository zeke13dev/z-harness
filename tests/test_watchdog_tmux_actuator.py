"""Tests for runtime/watchdog/tmux_actuator.py (session-watchdog tmux actuation).

Coverage (T004 acceptance, criterion #9):
- every tmux invocation (capture-pane, send-keys, has-session, new-session,
  kill-session) passes an explicit, non-``None`` subprocess ``timeout``;
- a simulated hang (``subprocess.TimeoutExpired``) raises ``TmuxTimeoutError``
  immediately rather than blocking;
- a non-zero tmux exit raises ``TmuxActuationError`` (except ``has_session``,
  whose non-zero exit is legitimate "session absent" signal, not an error);
- the reimplemented submit-race pattern (``submit_text``) sends the prompt as
  literal text, settles, then submits ``Enter`` as a SEPARATE call — matching
  ``mcp_hermes_orchestrator.py:844-856`` (read-only reference, never imported).

Tests mock ``subprocess.run`` throughout (STYLE.md:T-002 — a real hang cannot
be exercised hermetically without actually blocking, so mocking is the
practical choice here) and are otherwise hermetic (STYLE.md:T-004): no real
tmux session is created.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from runtime.watchdog import tmux_actuator as ta


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _RecordingRun:
    """Fake ``subprocess.run`` that records every call's argv + kwargs."""

    def __init__(self, result: subprocess.CompletedProcess[str] | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._result = result if result is not None else _completed()

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        return self._result


class _HangingRun:
    """Fake ``subprocess.run`` that always raises TimeoutExpired immediately —
    simulating a hang without ever actually blocking the test."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))


# ── explicit-timeout coverage across every wrapped verb ───────────────────────

@pytest.mark.parametrize(
    "call",
    [
        lambda: ta.capture_pane("zw-t-1", timeout=3),
        lambda: ta.has_session("zw-t-1", timeout=3),
        lambda: ta.new_session("zw-t-1", timeout=3),
        lambda: ta.kill_session("zw-t-1", timeout=3),
        lambda: ta.send_keys("zw-t-1", "Down", timeout=3),
        lambda: ta.send_keys_literal("zw-t-1", "hello", timeout=3),
        lambda: ta.send_enter("zw-t-1", timeout=3),
    ],
)
def test_every_wrapped_verb_passes_explicit_timeout(monkeypatch: pytest.MonkeyPatch, call: Any) -> None:
    fake = _RecordingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    call()
    assert fake.calls, "expected subprocess.run to be invoked"
    for argv, kwargs in fake.calls:
        assert argv[0] == "tmux"
        assert "timeout" in kwargs
        assert kwargs["timeout"] == 3


def test_submit_text_passes_explicit_timeout_on_both_underlying_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    monkeypatch.setattr(ta, "_sleep", lambda _seconds: None)
    ta.submit_text("zw-t-1", "hello world", timeout=7)
    assert len(fake.calls) == 2
    for _argv, kwargs in fake.calls:
        assert kwargs["timeout"] == 7


# ── timeout -> TmuxTimeoutError, never a block ────────────────────────────────

@pytest.mark.parametrize(
    "call",
    [
        lambda: ta.capture_pane("zw-t-1", timeout=1),
        lambda: ta.has_session("zw-t-1", timeout=1),
        lambda: ta.new_session("zw-t-1", timeout=1),
        lambda: ta.kill_session("zw-t-1", timeout=1),
        lambda: ta.send_keys("zw-t-1", "Down", timeout=1),
        lambda: ta.send_keys_literal("zw-t-1", "hello", timeout=1),
        lambda: ta.send_enter("zw-t-1", timeout=1),
    ],
)
def test_simulated_hang_raises_timeout_error_not_block(monkeypatch: pytest.MonkeyPatch, call: Any) -> None:
    fake = _HangingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    with pytest.raises(ta.TmuxTimeoutError):
        call()
    # The fake raised synchronously — no real waiting occurred, i.e. the wrapper
    # propagated the timeout instead of retrying or swallowing it into a block.
    assert len(fake.calls) == 1


def test_submit_text_hang_on_literal_send_raises_before_enter(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _HangingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    monkeypatch.setattr(ta, "_sleep", lambda _seconds: None)
    with pytest.raises(ta.TmuxTimeoutError):
        ta.submit_text("zw-t-1", "hello", timeout=1)
    assert len(fake.calls) == 1  # never reached the Enter call


# ── non-zero exit -> TmuxActuationError (except has_session) ─────────────────

def test_capture_pane_nonzero_exit_raises_actuation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun(_completed(returncode=1, stderr="can't find pane"))
    monkeypatch.setattr(ta.subprocess, "run", fake)
    with pytest.raises(ta.TmuxActuationError):
        ta.capture_pane("zw-missing", timeout=3)


def test_new_session_nonzero_exit_raises_actuation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun(_completed(returncode=1, stderr="duplicate session"))
    monkeypatch.setattr(ta.subprocess, "run", fake)
    with pytest.raises(ta.TmuxActuationError):
        ta.new_session("zw-dup", timeout=3)


def test_kill_session_nonzero_exit_raises_actuation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun(_completed(returncode=1, stderr="no such session"))
    monkeypatch.setattr(ta.subprocess, "run", fake)
    with pytest.raises(ta.TmuxActuationError):
        ta.kill_session("zw-gone", timeout=3)


def test_has_session_nonzero_exit_returns_false_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun(_completed(returncode=1, stderr="can't find session"))
    monkeypatch.setattr(ta.subprocess, "run", fake)
    assert ta.has_session("zw-gone", timeout=3) is False


def test_has_session_zero_exit_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun(_completed(returncode=0))
    monkeypatch.setattr(ta.subprocess, "run", fake)
    assert ta.has_session("zw-live", timeout=3) is True


# ── new_session optional command argument ─────────────────────────────────────

def test_new_session_without_command_omits_trailing_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    ta.new_session("zw-plain", timeout=3)
    argv, _kwargs = fake.calls[0]
    assert argv == ["tmux", "new-session", "-d", "-s", "zw-plain"]


def test_new_session_with_command_appends_it(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    ta.new_session("zw-plain", "claude", timeout=3)
    argv, _kwargs = fake.calls[0]
    assert argv == ["tmux", "new-session", "-d", "-s", "zw-plain", "claude"]


# ── submit-race pattern: literal text, settle, SEPARATE Enter ────────────────

def test_submit_text_sends_literal_text_then_separate_enter_with_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    settle_calls: list[float] = []
    monkeypatch.setattr(ta, "_sleep", settle_calls.append)

    ta.submit_text("zw-t-1", "do the thing", timeout=5, settle_seconds=0.2)

    assert len(fake.calls) == 2
    literal_argv, _ = fake.calls[0]
    enter_argv, _ = fake.calls[1]
    # First call: literal text via -l, NOT combined with Enter.
    assert literal_argv == ["tmux", "send-keys", "-t", "zw-t-1", "-l", "do the thing"]
    # Second call: Enter sent as its own, separate send-keys invocation.
    assert enter_argv == ["tmux", "send-keys", "-t", "zw-t-1", "Enter"]
    # A settle sleep happened between the two, matching the referenced pattern.
    assert settle_calls == [0.2]


def test_default_settle_seconds_matches_reference_constant() -> None:
    # mcp_hermes_orchestrator.py's _SUBMIT_SETTLE_SECONDS is 0.2 — the
    # reimplementation must match, not drift.
    assert ta.SUBMIT_SETTLE_SECONDS == 0.2


# ── module-level default timeout is a real, non-None constant ────────────────

def test_default_timeout_constant_is_positive_number() -> None:
    assert isinstance(ta.DEFAULT_TIMEOUT_S, (int, float))
    assert ta.DEFAULT_TIMEOUT_S > 0


def test_capture_pane_uses_default_timeout_when_unspecified(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _RecordingRun()
    monkeypatch.setattr(ta.subprocess, "run", fake)
    ta.capture_pane("zw-t-1")
    _argv, kwargs = fake.calls[0]
    assert kwargs["timeout"] == ta.DEFAULT_TIMEOUT_S
