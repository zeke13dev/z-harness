"""
tests/drivers/claude/test_env_hygiene.py — Unit tests for env_hygiene.py.

Covers:
  - build_subprocess_env() always returns CLAUDECODE=""
  - apply_env_hygiene(base_env) returns a new dict without mutating input
  - apply_env_hygiene merges base_env with CLAUDECODE override
  - cleared_vars list contains "CLAUDECODE" and no values
  - detect_self_hosted() returns True iff CLAUDECODE is non-empty in os.environ

Run:
    pytest tests/drivers/claude/test_env_hygiene.py -v
"""

from __future__ import annotations

import os

import pytest

from runtime.drivers.claude.env_hygiene import (
    BARE_FLAG,
    CLAUDECODE_VAR,
    apply_env_hygiene,
    build_subprocess_env,
    detect_self_hosted,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_claudecode_var_is_string_constant() -> None:
    """CLAUDECODE_VAR must be the canonical string, not an inline literal."""
    assert CLAUDECODE_VAR == "CLAUDECODE"


def test_bare_flag_is_string_constant() -> None:
    assert BARE_FLAG == "--bare"


# ---------------------------------------------------------------------------
# build_subprocess_env
# ---------------------------------------------------------------------------


def test_build_subprocess_env_clears_claudecode(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDECODE must be "" in the returned env regardless of parent env value."""
    monkeypatch.setenv(CLAUDECODE_VAR, "1")
    env = build_subprocess_env()
    assert env[CLAUDECODE_VAR] == ""


def test_build_subprocess_env_clears_when_already_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLAUDECODE_VAR, "")
    env = build_subprocess_env()
    assert env[CLAUDECODE_VAR] == ""


def test_build_subprocess_env_clears_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLAUDECODE_VAR, raising=False)
    env = build_subprocess_env()
    assert env[CLAUDECODE_VAR] == ""


def test_build_subprocess_env_does_not_mutate_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLAUDECODE_VAR, "something")
    _ = build_subprocess_env()
    assert os.environ[CLAUDECODE_VAR] == "something"


def test_build_subprocess_env_returns_dict() -> None:
    result = build_subprocess_env()
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# apply_env_hygiene — core acceptance criterion
# ---------------------------------------------------------------------------


def test_apply_env_hygiene_merges_and_clears() -> None:
    """apply_env_hygiene({"CLAUDECODE": "1"}) yields {"CLAUDECODE": ""} merged with base."""
    base = {"CLAUDECODE": "1", "OTHER_VAR": "keep_me"}
    result, cleared_vars = apply_env_hygiene(base)

    assert result["CLAUDECODE"] == "", "CLAUDECODE must be cleared to empty string"
    assert result["OTHER_VAR"] == "keep_me", "other vars must be preserved"
    assert "CLAUDECODE" in cleared_vars, "cleared_vars must list CLAUDECODE by name"


def test_apply_env_hygiene_does_not_mutate_input() -> None:
    """Input dict must not be mutated."""
    base = {"CLAUDECODE": "1", "EXTRA": "value"}
    original_claudecode = base["CLAUDECODE"]
    _, _ = apply_env_hygiene(base)
    assert base["CLAUDECODE"] == original_claudecode, "apply_env_hygiene must not mutate its input"


def test_apply_env_hygiene_returns_new_dict() -> None:
    base = {"CLAUDECODE": "1"}
    result, _ = apply_env_hygiene(base)
    assert result is not base, "apply_env_hygiene must return a NEW dict"


def test_apply_env_hygiene_cleared_vars_contains_no_values() -> None:
    """cleared_vars must contain only variable names, never their values."""
    base = {"CLAUDECODE": "secret-value"}
    _, cleared_vars = apply_env_hygiene(base)
    # The list should contain the *name* CLAUDECODE_VAR, not its value
    assert CLAUDECODE_VAR in cleared_vars
    assert "secret-value" not in cleared_vars


def test_apply_env_hygiene_when_claudecode_absent() -> None:
    """Hygiene must still set CLAUDECODE="" even if it was absent from base."""
    base: dict[str, str] = {"SOME_VAR": "val"}
    result, cleared_vars = apply_env_hygiene(base)
    assert result["CLAUDECODE"] == ""
    assert "CLAUDECODE" in cleared_vars


# ---------------------------------------------------------------------------
# detect_self_hosted
# ---------------------------------------------------------------------------


def test_detect_self_hosted_true_when_nonempty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLAUDECODE_VAR, "1")
    assert detect_self_hosted() is True


def test_detect_self_hosted_false_when_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLAUDECODE_VAR, "")
    assert detect_self_hosted() is False


def test_detect_self_hosted_false_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLAUDECODE_VAR, raising=False)
    assert detect_self_hosted() is False
