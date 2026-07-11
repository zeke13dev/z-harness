"""Tests for runtime/watchdog/judge.py (session-watchdog judge dispatch).

Coverage (T007 acceptance, criteria #3/#9):
- an unresolvable/unbound ``watchdog_judge`` role degrades gracefully to the
  mechanical fallback verdict plus a ``judge_degraded`` event, without a
  dispatch attempt and without raising;
- a resolved provider that times out twice (initial attempt + exactly one
  retry) degrades to the same fallback + ``judge_degraded`` event, with
  ``attempts == 2``;
- a resolved provider that fails once then succeeds on the retry returns the
  judge's verdict with no ``judge_degraded`` event (the retry recovers);
- a successful first-attempt dispatch returns the judge's verdict without
  emitting ``judge_degraded`` and without a second subprocess call;
- the stdin/positional-arg dispatch protocol (``descriptor["stdin"]``) is
  honored in both directions;
- ``mechanical_fallback_verdict``'s threshold-only stop/no-stop decision;
- the ``judge_degraded`` event's exact field set (STYLE.md:P-003).

Tests mock the provider call (``judge.subprocess.run``) and role resolution
(``judge.resolve_provider``) throughout (STYLE.md:T-002 note in module
docstring: a real timeout cannot be exercised hermetically without actually
blocking, and no real LLM CLI may ever be invoked from a test) and are
otherwise hermetic (STYLE.md:T-004): no real ``resolve-provider.py``
subprocess or provider CLI is ever launched.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from runtime.watchdog import judge


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _RecordingRun:
    """Fake ``subprocess.run`` that records every call's argv + kwargs and
    returns a fixed result (or the next of a queued sequence)."""

    def __init__(self, results: list[subprocess.CompletedProcess[str]] | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._results = list(results) if results is not None else [_completed()]

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        if len(self._results) > 1:
            return self._results.pop(0)
        return self._results[0]


class _HangingRun:
    """Fake ``subprocess.run`` that always raises ``TimeoutExpired`` —
    simulates a hung provider call without ever actually blocking."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))


class _TimeoutThenSuccessRun:
    """Fake ``subprocess.run``: raises ``TimeoutExpired`` on the first call,
    then succeeds on the retry."""

    def __init__(self, stdout: str = "judge says stop") -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self._stdout = stdout

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        if len(self.calls) == 1:
            raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout"))
        return _completed(returncode=0, stdout=self._stdout)


_FAKE_DESCRIPTOR_STDIN = {
    "role": "watchdog_judge",
    "provider": "omp-fake-judge",
    "command": "fake-judge-cli",
    "args_template": ["--flag"],
    "stdin": True,
    "timeout_s": 60,
}

_FAKE_DESCRIPTOR_POSITIONAL = {
    "role": "watchdog_judge",
    "provider": "fake-cli",
    "command": "fake-judge-cli",
    "args_template": ["--flag"],
    "stdin": False,
    "timeout_s": 60,
}


# ── (a) unresolvable role degrades without raise, zero dispatch attempts ────

def test_unresolvable_role_degrades_to_fallback_without_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_unbound(role: str, repo_root: str) -> dict:
        raise RuntimeError(
            "resolve-provider.py exited with code 1: role is unbound — "
            "add a [roles.<command/default>.<role>].runtime binding"
        )

    monkeypatch.setattr(judge, "resolve_provider", _raise_unbound)
    run = _RecordingRun()
    monkeypatch.setattr(judge.subprocess, "run", run)

    result = judge.dispatch_judge_verdict(
        context_pct=85.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )

    assert not run.calls, "resolution failure must not attempt any dispatch"
    assert result["verdict"] == {
        "source": "mechanical_fallback",
        "stop": True,
        "context_pct": 85.0,
        "threshold_pct": 80.0,
    }
    degraded = result["judge_degraded"]
    assert degraded is not None
    assert degraded["role"] == "watchdog_judge"
    assert degraded["attempts"] == 0
    assert "role_unresolved" in degraded["reason"]


def test_unresolvable_role_missing_script_degrades_too(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_missing(role: str, repo_root: str) -> dict:
        raise FileNotFoundError("scripts/resolve-provider.py not found")

    monkeypatch.setattr(judge, "resolve_provider", _raise_missing)
    result = judge.dispatch_judge_verdict(
        context_pct=50.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )
    assert result["verdict"]["stop"] is False
    assert result["judge_degraded"] is not None


# ── (b) timeout-then-timeout degrades to fallback + judge_degraded ─────────

def test_timeout_then_timeout_degrades_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    hang = _HangingRun()
    monkeypatch.setattr(judge.subprocess, "run", hang)

    result = judge.dispatch_judge_verdict(
        context_pct=90.0,
        threshold_pct=80.0,
        prompt="stop?",
        repo_root="/fake/repo",
        timeout_s=5,
    )

    assert len(hang.calls) == 2, "exactly one retry (2 total attempts)"
    assert result["verdict"] == {
        "source": "mechanical_fallback",
        "stop": True,
        "context_pct": 90.0,
        "threshold_pct": 80.0,
    }
    degraded = result["judge_degraded"]
    assert degraded is not None
    assert degraded["role"] == "watchdog_judge"
    assert degraded["attempts"] == 2
    assert degraded["timeout_s"] == 5

    # Every attempt carried the caller-supplied explicit timeout.
    for _argv, kwargs in hang.calls:
        assert kwargs.get("timeout") == 5


def test_timeout_then_timeout_fallback_stop_false_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    monkeypatch.setattr(judge.subprocess, "run", _HangingRun())

    result = judge.dispatch_judge_verdict(
        context_pct=50.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )
    assert result["verdict"]["stop"] is False
    assert result["judge_degraded"] is not None


# ── (c) one failure then a successful retry recovers (no degrade) ──────────

def test_retry_recovers_after_one_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _TimeoutThenSuccessRun(stdout="judge verdict: proceed")
    monkeypatch.setattr(judge.subprocess, "run", run)

    result = judge.dispatch_judge_verdict(
        context_pct=85.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )

    assert len(run.calls) == 2
    assert result["judge_degraded"] is None
    assert result["verdict"] == {"source": "judge", "raw_output": "judge verdict: proceed"}


# ── (d) successful first-attempt dispatch: no retry, no judge_degraded ──────

def test_successful_call_returns_judge_verdict_without_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _RecordingRun(results=[_completed(returncode=0, stdout="  judge says continue  \n")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    result = judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )

    assert len(run.calls) == 1, "a successful first attempt must not retry"
    assert result["judge_degraded"] is None
    assert result["verdict"] == {"source": "judge", "raw_output": "judge says continue"}


def test_nonzero_exit_counts_as_a_failed_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _RecordingRun(results=[_completed(returncode=1, stdout="", stderr="boom")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    result = judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )

    assert len(run.calls) == 2, "non-zero exit is a failure, retried exactly once"
    assert result["judge_degraded"] is not None
    assert result["judge_degraded"]["attempts"] == 2


def test_empty_stdout_counts_as_a_failed_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _RecordingRun(results=[_completed(returncode=0, stdout="   \n")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    result = judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )

    assert len(run.calls) == 2
    assert result["judge_degraded"] is not None


# ── (e) stdin vs positional-arg dispatch protocol ───────────────────────────

def test_stdin_true_pipes_prompt_to_stdin_not_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _RecordingRun(results=[_completed(returncode=0, stdout="ok")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="THE PROMPT", repo_root="/fake/repo"
    )

    (argv, kwargs), = run.calls
    assert argv == ["fake-judge-cli", "--flag"]
    assert kwargs.get("input") == "THE PROMPT"


def test_stdin_false_appends_prompt_as_positional_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_POSITIONAL))
    run = _RecordingRun(results=[_completed(returncode=0, stdout="ok")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="THE PROMPT", repo_root="/fake/repo"
    )

    (argv, kwargs), = run.calls
    assert argv == ["fake-judge-cli", "--flag", "THE PROMPT"]
    assert "input" not in kwargs or kwargs.get("input") is None


# ── (f) timeout wiring: default vs caller-supplied ──────────────────────────

def test_default_timeout_used_when_not_specified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _RecordingRun(results=[_completed(returncode=0, stdout="ok")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )

    (_argv, kwargs), = run.calls
    assert kwargs.get("timeout") == judge.DEFAULT_TIMEOUT_S == 60


def test_caller_supplied_timeout_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    run = _RecordingRun(results=[_completed(returncode=0, stdout="ok")])
    monkeypatch.setattr(judge.subprocess, "run", run)

    judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo", timeout_s=12
    )

    (_argv, kwargs), = run.calls
    assert kwargs.get("timeout") == 12


# ── (g) mechanical_fallback_verdict standalone unit coverage ───────────────

def test_mechanical_fallback_stop_true_at_or_above_threshold() -> None:
    assert judge.mechanical_fallback_verdict(80.0, 80.0)["stop"] is True
    assert judge.mechanical_fallback_verdict(95.0, 80.0)["stop"] is True


def test_mechanical_fallback_stop_false_below_threshold() -> None:
    assert judge.mechanical_fallback_verdict(79.9, 80.0)["stop"] is False


# ── (h) judge_degraded event field set (STYLE.md:P-003) ────────────────────

def test_judge_degraded_event_has_exact_field_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(judge, "resolve_provider", lambda role, repo_root: dict(_FAKE_DESCRIPTOR_STDIN))
    monkeypatch.setattr(judge.subprocess, "run", _HangingRun())

    result = judge.dispatch_judge_verdict(
        context_pct=90.0, threshold_pct=80.0, prompt="stop?", repo_root="/fake/repo"
    )
    assert set(result["judge_degraded"].keys()) == {"role", "reason", "attempts", "timeout_s"}
