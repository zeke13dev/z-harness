"""
Tests for runtime/drivers/antigravity/auth.py.

Uses monkeypatched HOME and env to cover:
  - cli_auth True when ~/.gemini/oauth_creds.json exists
  - cli_auth False when file absent → warning added
  - sdk_auth True when GEMINI_API_KEY set and non-empty
  - sdk_auth False when GEMINI_API_KEY absent or empty
  - SDK-deferred warning always present
  - cli_auth missing warning present iff file absent
  - Return shape matches AuthStatus TypedDict
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.drivers.antigravity.auth import (
    _CLI_AUTH_MISSING_WARNING,
    _SDK_DEFERRED_WARNING,
    check_auth,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME to a temp directory for the duration of a test."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture()
def no_sdk_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure GEMINI_API_KEY is absent for this test."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def sdk_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a non-empty GEMINI_API_KEY for this test."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key-value")


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------


def test_check_auth_returns_required_keys(fake_home, no_sdk_key):
    """check_auth() must return a dict with cli_auth, sdk_auth, warnings keys."""
    result = check_auth()
    assert "cli_auth" in result
    assert "sdk_auth" in result
    assert "warnings" in result
    assert isinstance(result["cli_auth"], bool)
    assert isinstance(result["sdk_auth"], bool)
    assert isinstance(result["warnings"], list)


# ---------------------------------------------------------------------------
# cli_auth: file present
# ---------------------------------------------------------------------------


def test_cli_auth_true_when_creds_file_exists(fake_home, no_sdk_key):
    """cli_auth is True when ~/.gemini/oauth_creds.json exists."""
    gemini_dir = fake_home / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_text("{}")
    result = check_auth()
    assert result["cli_auth"] is True


def test_cli_auth_no_missing_warning_when_creds_exist(fake_home, no_sdk_key):
    """cli_auth missing warning is absent when creds file exists."""
    gemini_dir = fake_home / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_text("{}")
    result = check_auth()
    assert _CLI_AUTH_MISSING_WARNING not in result["warnings"]


# ---------------------------------------------------------------------------
# cli_auth: file absent
# ---------------------------------------------------------------------------


def test_cli_auth_false_when_creds_file_absent(fake_home, no_sdk_key):
    """cli_auth is False when ~/.gemini/oauth_creds.json does not exist."""
    result = check_auth()
    assert result["cli_auth"] is False


def test_cli_auth_missing_warning_when_creds_absent(fake_home, no_sdk_key):
    """cli_auth missing warning is included when creds file is absent."""
    result = check_auth()
    assert _CLI_AUTH_MISSING_WARNING in result["warnings"]


def test_cli_auth_check_is_presence_only(fake_home, no_sdk_key):
    """cli_auth True even for an empty/invalid JSON file (presence check only)."""
    gemini_dir = fake_home / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_bytes(b"")
    result = check_auth()
    assert result["cli_auth"] is True


# ---------------------------------------------------------------------------
# sdk_auth
# ---------------------------------------------------------------------------


def test_sdk_auth_true_when_key_set(fake_home, sdk_key_set):
    """sdk_auth is True when GEMINI_API_KEY is non-empty."""
    result = check_auth()
    assert result["sdk_auth"] is True


def test_sdk_auth_false_when_key_absent(fake_home, no_sdk_key):
    """sdk_auth is False when GEMINI_API_KEY is not set."""
    result = check_auth()
    assert result["sdk_auth"] is False


def test_sdk_auth_false_when_key_empty(fake_home, monkeypatch):
    """sdk_auth is False when GEMINI_API_KEY is set to empty string."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    result = check_auth()
    assert result["sdk_auth"] is False


# ---------------------------------------------------------------------------
# warnings: SDK-deferred always present
# ---------------------------------------------------------------------------


def test_sdk_deferred_warning_always_present_when_cli_auth_true(fake_home, no_sdk_key):
    """SDK-deferred warning is always included, even when cli_auth is True."""
    gemini_dir = fake_home / ".gemini"
    gemini_dir.mkdir()
    (gemini_dir / "oauth_creds.json").write_text("{}")
    result = check_auth()
    assert _SDK_DEFERRED_WARNING in result["warnings"]


def test_sdk_deferred_warning_always_present_when_cli_auth_false(fake_home, no_sdk_key):
    """SDK-deferred warning is always included when cli_auth is False."""
    result = check_auth()
    assert _SDK_DEFERRED_WARNING in result["warnings"]


def test_sdk_deferred_warning_always_present_when_sdk_key_set(fake_home, sdk_key_set):
    """SDK-deferred warning is present even when GEMINI_API_KEY is set."""
    result = check_auth()
    assert _SDK_DEFERRED_WARNING in result["warnings"]


# ---------------------------------------------------------------------------
# No side effects (no network, no OAuth, no file writes)
# ---------------------------------------------------------------------------


def test_check_auth_does_not_write_files(fake_home, no_sdk_key):
    """check_auth() must not create any files in the home directory."""
    before = set(fake_home.rglob("*"))
    check_auth()
    after = set(fake_home.rglob("*"))
    assert after == before, f"check_auth() created unexpected files: {after - before}"


# ---------------------------------------------------------------------------
# Standalone __main__ mode
# ---------------------------------------------------------------------------


def test_standalone_main_prints_json(fake_home, no_sdk_key):
    """Running as __main__ prints valid JSON with expected keys."""
    result = subprocess.run(
        [sys.executable, "-m", "runtime.drivers.antigravity.auth"],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(fake_home), "PYTHONPATH": str(Path(__file__).parents[4])},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = json.loads(result.stdout)
    assert "cli_auth" in data
    assert "sdk_auth" in data
    assert "warnings" in data
