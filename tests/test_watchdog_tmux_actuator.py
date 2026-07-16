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
from pathlib import Path
from typing import Any

import pytest

from runtime.watchdog import registry, tmux_actuator as ta

_WAKE_GENERATION = "coordinator:v1:coordinator-1:1"
_WAKE_OUTBOX_ID = f"wake:v1:{'a' * 64}"
_WAKE_TEXT = (
    "fanout 'root' children all terminal (automated watchdog):\n"
    f"watchdog_ack outbox_id={_WAKE_OUTBOX_ID} "
    f"coordinator_generation={_WAKE_GENERATION}\n"
    "- zw-child: done"
)


def _seed_wake_authority(registry_path: Path) -> None:
    record = registry.new_session_record(
        "root", str(registry_path.parent), "claude", "zw-coordinator-1", "",
        session_id="coordinator-1", now="1",
    )
    record = registry.transition(record, "awaiting_children", now="7")
    registry.write_registry(registry_path, {record["session_id"]: record})


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


# ── deterministic daemon action boundary ────────────────────────────────────

def test_lifecycle_action_marker_is_durable_before_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "sessions.json"
    _seed_wake_authority(registry_path)
    observed: list[dict[str, dict]] = []

    def effect(target: str, text: str) -> bool:
        observed.append(registry.read_registry_document(registry_path)["action_markers"])
        return True

    monkeypatch.setattr(ta, "submit_text", effect)

    result = ta.dispatch_lifecycle_action(
        registry_path,
        session_id="coordinator-1",
        action="coordinator_wake",
        generation=_WAKE_GENERATION,
        attempt=1,
        max_attempts=2,
        target="zw-coordinator-1",
        text=_WAKE_TEXT,
        now="2026-07-14T19:00:00Z",
    )

    assert result["status"] == "completed"
    assert observed[0][result["action_id"]]["status"] == "prepared"
    persisted = registry.read_registry_document(registry_path)["action_markers"]
    assert persisted[result["action_id"]]["status"] == "completed"


def test_unknown_or_semantic_action_cannot_dispatch_or_mutate(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    effects: list[str] = []

    with pytest.raises(ta.LifecycleActionRejectedError):
        ta.dispatch_lifecycle_action(
            registry_path,
            session_id="coordinator-1",
            action="implement_change",
            generation=_WAKE_GENERATION,
            attempt=1,
            max_attempts=1,
            target="zw-coordinator-1",
            text="implement",
        )

    assert effects == []
    assert not registry_path.exists()


def test_ambiguous_intent_or_host_state_pauses_without_mutation(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    for intent_confirmed, host_ready in ((False, True), (True, False)):
        result = ta.dispatch_lifecycle_action(
            registry_path,
            session_id="coordinator-1",
            action="nudge",
            generation="episode-1",
            attempt=1,
            max_attempts=2,
            target="zw-coordinator-1",
            text=ta.NUDGE_TEXT,
            intent_confirmed=intent_confirmed,
            host_ready=host_ready,
        )
        assert result["status"] == "paused"
    assert not registry_path.exists()


def test_restart_pauses_prepared_action_instead_of_repeating_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "sessions.json"
    _seed_wake_authority(registry_path)

    def ambiguous_effect(target: str, text: str) -> None:
        raise ta.TmuxTimeoutError("delivery outcome unknown")

    monkeypatch.setattr(ta, "submit_text", ambiguous_effect)

    with pytest.raises(ta.TmuxTimeoutError):
        ta.dispatch_lifecycle_action(
            registry_path,
            session_id="coordinator-1",
            action="coordinator_wake",
            generation=_WAKE_GENERATION,
            attempt=1,
            max_attempts=2,
            target="zw-coordinator-1",
            text=_WAKE_TEXT,
        )

    monkeypatch.setattr(
        ta, "submit_text", lambda target, text: pytest.fail(
            "restart repeated an ambiguous wake"
        ),
    )
    result = ta.dispatch_lifecycle_action(
        registry_path,
        session_id="coordinator-1",
        action="coordinator_wake",
        generation=_WAKE_GENERATION,
        attempt=1,
        max_attempts=2,
        target="zw-coordinator-1",
        text=_WAKE_TEXT,
    )
    assert result["status"] == "paused"


def test_later_attempt_pauses_while_prior_generation_marker_is_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion #6: timeout ambiguity fences every later wake attempt."""
    registry_path = tmp_path / "sessions.json"
    _seed_wake_authority(registry_path)

    def _timeout(_target: str, _text: str) -> bool:
        raise ta.TmuxTimeoutError("delivery outcome unknown")

    monkeypatch.setattr(ta, "submit_text", _timeout)
    with pytest.raises(ta.TmuxTimeoutError):
        ta.dispatch_lifecycle_action(
            registry_path,
            session_id="coordinator-1",
            action="coordinator_wake",
            generation=_WAKE_GENERATION,
            attempt=1,
            max_attempts=2,
            target="zw-coordinator-1",
            text=_WAKE_TEXT,
        )

    monkeypatch.setattr(
        ta, "submit_text", lambda *_args: pytest.fail("attempt 2 bypassed pause")
    )
    paused = ta.dispatch_lifecycle_action(
        registry_path,
        session_id="coordinator-1",
        action="coordinator_wake",
        generation=_WAKE_GENERATION,
        attempt=2,
        max_attempts=2,
        target="zw-coordinator-1",
        text=_WAKE_TEXT,
    )
    assert paused["status"] == "paused"
    assert paused["attempt"] == 1


def test_exhausted_bounded_attempts_persist_explicit_escalation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "sessions.json"
    _seed_wake_authority(registry_path)
    calls: list[tuple[str, str]] = []

    def fail(target: str, text: str) -> bool:
        calls.append((target, text))
        return False

    monkeypatch.setattr(ta, "submit_text", fail)

    first = ta.dispatch_lifecycle_action(
        registry_path,
        session_id="coordinator-1",
        action="coordinator_wake",
        generation=_WAKE_GENERATION,
        attempt=None,
        max_attempts=2,
        target="zw-coordinator-1",
        text=_WAKE_TEXT,
    )
    second = ta.dispatch_lifecycle_action(
        registry_path,
        session_id="coordinator-1",
        action="coordinator_wake",
        generation=_WAKE_GENERATION,
        attempt=None,
        max_attempts=2,
        target="zw-coordinator-1",
        text=_WAKE_TEXT,
    )

    assert first["status"] == "failed"
    assert first["attempt"] == 1
    assert second["status"] == "escalated"
    assert second["attempt"] == 2
    assert len(calls) == 2
    markers = registry.read_registry_document(registry_path)["action_markers"]
    assert sum(marker["status"] == "failed" for marker in markers.values()) == 2
    assert sum(marker["status"] == "escalated" for marker in markers.values()) == 1


def test_allowlisted_action_rejects_arbitrary_effect_callable(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        ta.dispatch_lifecycle_action(
            tmp_path / "sessions.json",
            session_id="coordinator-1",
            action="nudge",
            generation="episode-1",
            attempt=1,
            max_attempts=1,
            target="zw-coordinator-1",
            text=ta.NUDGE_TEXT,
            effect=lambda: True,
        )


def test_allowlisted_action_rejects_semantic_text_without_mutation(tmp_path: Path) -> None:
    registry_path = tmp_path / "sessions.json"
    with pytest.raises(ta.LifecycleActionRejectedError):
        ta.dispatch_lifecycle_action(
            registry_path,
            session_id="coordinator-1",
            action="nudge",
            generation="episode-1",
            attempt=1,
            max_attempts=1,
            target="zw-coordinator-1",
            text="implement the pending task",
        )
    assert not registry_path.exists()


@pytest.mark.parametrize(
    ("session_id", "target", "generation", "state"),
    [
        ("missing", "zw-coordinator-1", _WAKE_GENERATION, "awaiting_children"),
        ("coordinator-1", "zw-other", _WAKE_GENERATION, "awaiting_children"),
        ("coordinator-1", "zw-coordinator-1", "6", "awaiting_children"),
        ("coordinator-1", "zw-coordinator-1", _WAKE_GENERATION, "running"),
    ],
)
def test_action_rejects_non_authoritative_target_generation_or_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    target: str,
    generation: str,
    state: str,
) -> None:
    registry_path = tmp_path / "sessions.json"
    _seed_wake_authority(registry_path)
    if state == "running":
        document = registry.read_registry_document(registry_path)
        document["sessions"]["coordinator-1"]["state"] = "running"
        registry.write_registry(
            registry_path, document["sessions"],
        )
    monkeypatch.setattr(
        ta, "submit_text", lambda *_args: pytest.fail("rejected action dispatched"),
    )

    with pytest.raises(ta.LifecycleActionRejectedError):
        ta.dispatch_lifecycle_action(
            registry_path,
            session_id=session_id,
            action="coordinator_wake",
            generation=generation,
            attempt=1,
            max_attempts=2,
            target=target,
            text=_WAKE_TEXT,
        )

    assert registry.read_registry_document(registry_path)["action_markers"] == {}
