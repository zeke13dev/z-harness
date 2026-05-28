"""
tests/drivers/cursor/test_mcp_config.py — Unit tests for runtime/drivers/cursor/mcp_config.py.

Acceptance criteria:
  - test_register_creates_new_file: non-existent config path → file created with correct structure
  - test_register_merges_existing: existing file with other keys → z-harness key added, existing keys preserved
  - test_register_wrong_key_raises: passing key != "z-harness" → MCPKeyNameError
  - test_atomic_write: uses tmp file + replace (os.replace call verified)
  - test_mcp_config_write_event_emitted: event emitted with correct fields
  - All tests use tmp_path fixture (no writes to real ~/.cursor/)

Run:
    pytest tests/drivers/cursor/test_mcp_config.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import call, patch

import pytest

from runtime.drivers.cursor.mcp_config import (
    MCP_KEY_NAME,
    MCPKeyNameError,
    _assert_key_name,
    register_mcp_server,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def suppress_log_event(monkeypatch):
    """Suppress real log_event calls; tests that inspect telemetry patch explicitly."""
    with patch("runtime.drivers.cursor.mcp_config.log_event") as _mock:
        yield _mock


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Point HOME and Path.home() at a temp dir so we never touch real ~/.cursor."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# test_register_creates_new_file — non-existent path → correct structure
# ---------------------------------------------------------------------------


def test_register_creates_new_file(fake_home):
    """register_mcp_server creates ~/.cursor/mcp.json when it doesn't exist."""
    server_def = {"command": "python3", "args": ["-m", "z_harness_mcp"]}
    config_path = fake_home / ".cursor" / "mcp.json"

    assert not config_path.exists(), "Pre-condition: config must not exist yet"

    register_mcp_server(server_def)

    assert config_path.exists(), "Config file should be created"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert "z-harness" in data["mcpServers"]
    assert data["mcpServers"]["z-harness"] == server_def


# ---------------------------------------------------------------------------
# test_register_merges_existing — existing keys preserved, z-harness added
# ---------------------------------------------------------------------------


def test_register_merges_existing(fake_home):
    """Existing mcpServers entries are preserved after register_mcp_server merges."""
    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir(parents=True)
    existing = {
        "mcpServers": {
            "other-tool": {"command": "other", "args": []},
            "another-tool": {"command": "another", "args": ["--flag"]},
        }
    }
    (cursor_dir / "mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    register_mcp_server({"command": "z", "args": []})

    data = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
    assert "other-tool" in data["mcpServers"], "Existing 'other-tool' must be preserved"
    assert "another-tool" in data["mcpServers"], "Existing 'another-tool' must be preserved"
    assert "z-harness" in data["mcpServers"], "z-harness must be added"


# ---------------------------------------------------------------------------
# test_register_wrong_key_raises — MCPKeyNameError for bad key
# ---------------------------------------------------------------------------


def test_register_wrong_key_raises():
    """_assert_key_name raises MCPKeyNameError for any key != 'z-harness'."""
    with pytest.raises(MCPKeyNameError):
        _assert_key_name("evil-server")


def test_register_wrong_key_raises_for_empty_string():
    """_assert_key_name raises MCPKeyNameError for an empty string."""
    with pytest.raises(MCPKeyNameError):
        _assert_key_name("")


def test_register_wrong_key_raises_for_near_match():
    """_assert_key_name raises MCPKeyNameError for strings that almost match."""
    with pytest.raises(MCPKeyNameError):
        _assert_key_name("z-harness ")  # trailing space


def test_register_wrong_key_accepts_z_harness():
    """_assert_key_name does not raise for the canonical 'z-harness' key."""
    _assert_key_name("z-harness")  # must not raise


# ---------------------------------------------------------------------------
# test_atomic_write — uses tmp file + os.replace (not os.rename)
# ---------------------------------------------------------------------------


def test_atomic_write(fake_home):
    """register_mcp_server writes atomically: os.replace is called, no .tmp left behind."""
    replace_calls = []
    original_replace = os.replace

    def capturing_replace(src, dst):
        replace_calls.append((src, dst))
        return original_replace(src, dst)

    with patch("runtime.drivers.cursor.mcp_config.os.replace", side_effect=capturing_replace):
        register_mcp_server({"command": "z", "args": []})

    # os.replace must have been called at least once
    assert len(replace_calls) >= 1, "os.replace should be called for atomic write"

    # Verify src was a .tmp file and dst was the actual mcp.json
    src, dst = replace_calls[0]
    assert src.endswith(".tmp"), f"Expected tmp source, got: {src}"
    assert dst.endswith("mcp.json"), f"Expected mcp.json destination, got: {dst}"

    # No .tmp file should remain on disk after the successful replace
    cursor_dir = fake_home / ".cursor"
    tmp_files = list(cursor_dir.glob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files remaining: {tmp_files}"


# ---------------------------------------------------------------------------
# test_mcp_config_write_event_emitted — event with correct fields
# ---------------------------------------------------------------------------


def test_mcp_config_write_event_emitted(fake_home):
    """register_mcp_server emits mcp_config_write event with config_path, key_name, server_count."""
    with patch("runtime.drivers.cursor.mcp_config.log_event") as mock_log:
        register_mcp_server({"command": "z", "args": []})

    write_calls = [c for c in mock_log.call_args_list if c.kwargs.get("kind") == "mcp_config_write"]
    assert len(write_calls) >= 1, "At least one mcp_config_write event must be emitted"

    payload = write_calls[0].kwargs["payload"]
    assert "config_path" in payload, "payload must contain 'config_path'"
    assert "key_name" in payload, "payload must contain 'key_name'"
    assert "server_count" in payload, "payload must contain 'server_count'"
    assert payload["key_name"] == "z-harness", "key_name must be 'z-harness'"
    assert isinstance(payload["server_count"], int), "server_count must be an int"
    assert payload["server_count"] >= 1, "server_count must be at least 1"


def test_mcp_config_write_event_config_path_is_real_file(fake_home):
    """config_path in the event payload refers to the actual file written."""
    with patch("runtime.drivers.cursor.mcp_config.log_event") as mock_log:
        register_mcp_server({"command": "z", "args": []})

    write_calls = [c for c in mock_log.call_args_list if c.kwargs.get("kind") == "mcp_config_write"]
    assert write_calls, "mcp_config_write event must be emitted"

    config_path_str = write_calls[0].kwargs["payload"]["config_path"]
    assert Path(config_path_str).exists(), "config_path in event must refer to a written file"


# ---------------------------------------------------------------------------
# Additional tests preserving full coverage from original test suite
# ---------------------------------------------------------------------------


def test_mcp_key_name_is_z_harness():
    """MCP_KEY_NAME must be the literal string 'z-harness'."""
    assert MCP_KEY_NAME == "z-harness"


def test_register_initial_content_structure(fake_home):
    """New config file has the shape {mcpServers: {z-harness: server_def}}."""
    server_def = {"command": "npx", "args": ["z-harness-server"]}
    register_mcp_server(server_def)

    config_path = fake_home / ".cursor" / "mcp.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert list(data.keys()) == ["mcpServers"]
    assert list(data["mcpServers"].keys()) == ["z-harness"]


def test_register_upserts_z_harness_entry(fake_home):
    """Calling register_mcp_server twice updates the z-harness entry in-place."""
    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir(parents=True)
    first_def = {"command": "old", "args": []}
    (cursor_dir / "mcp.json").write_text(
        json.dumps({"mcpServers": {"z-harness": first_def}}), encoding="utf-8"
    )

    new_def = {"command": "new", "args": ["--flag"]}
    register_mcp_server(new_def)

    data = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
    assert data["mcpServers"]["z-harness"] == new_def


def test_register_writes_project_config_when_project_root_given(fake_home, tmp_path):
    """With project_root, .cursor/mcp.json is written inside that directory."""
    project_root = tmp_path / "myproject"
    project_root.mkdir()

    register_mcp_server({"command": "z", "args": []}, project_root=str(project_root))

    project_config = project_root / ".cursor" / "mcp.json"
    assert project_config.exists()
    data = json.loads(project_config.read_text(encoding="utf-8"))
    assert "z-harness" in data["mcpServers"]


def test_register_no_project_config_without_project_root(fake_home, tmp_path):
    """Without project_root, no project .cursor/mcp.json is written in arbitrary dirs."""
    candidate_project = tmp_path / "some_project"
    candidate_project.mkdir()

    register_mcp_server({"command": "z", "args": []})

    assert not (candidate_project / ".cursor").exists()


def test_register_project_merges_does_not_clobber_existing(fake_home, tmp_path):
    """Existing project mcpServers entries survive project-scope write."""
    project_root = tmp_path / "myproject"
    cursor_dir = project_root / ".cursor"
    cursor_dir.mkdir(parents=True)
    existing = {"mcpServers": {"team-tool": {"command": "team", "args": []}}}
    (cursor_dir / "mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    register_mcp_server({"command": "z", "args": []}, project_root=str(project_root))

    data = json.loads((cursor_dir / "mcp.json").read_text(encoding="utf-8"))
    assert "team-tool" in data["mcpServers"]
    assert "z-harness" in data["mcpServers"]


def test_server_count_reflects_total_entries_after_merge(fake_home):
    """server_count in event equals total mcpServers entries after merge."""
    cursor_dir = fake_home / ".cursor"
    cursor_dir.mkdir(parents=True)
    existing = {
        "mcpServers": {
            "tool-a": {"command": "a", "args": []},
            "tool-b": {"command": "b", "args": []},
        }
    }
    (cursor_dir / "mcp.json").write_text(json.dumps(existing), encoding="utf-8")

    with patch("runtime.drivers.cursor.mcp_config.log_event") as mock_log:
        register_mcp_server({"command": "z", "args": []})

    write_calls = [c for c in mock_log.call_args_list if c.kwargs.get("kind") == "mcp_config_write"]
    global_call = next(
        c for c in write_calls
        if "mcp.json" in c.kwargs["payload"]["config_path"]
        and str(fake_home) in c.kwargs["payload"]["config_path"]
    )
    # 2 existing + 1 new z-harness = 3
    assert global_call.kwargs["payload"]["server_count"] == 3


def test_event_emitted_for_project_scope_too(fake_home, tmp_path):
    """mcp_config_write is emitted for both global and project writes."""
    project_root = tmp_path / "proj"
    project_root.mkdir()

    with patch("runtime.drivers.cursor.mcp_config.log_event") as mock_log:
        register_mcp_server({"command": "z", "args": []}, project_root=str(project_root))

    write_calls = [c for c in mock_log.call_args_list if c.kwargs.get("kind") == "mcp_config_write"]
    assert len(write_calls) == 2, f"Expected 2 mcp_config_write events, got {len(write_calls)}"


def test_register_raises_type_error_for_non_dict_server_def(fake_home):
    """register_mcp_server raises TypeError when server_def is not a dict."""
    with pytest.raises(TypeError):
        register_mcp_server(["command", "z"])  # type: ignore[arg-type]


def test_register_raises_type_error_for_string_server_def(fake_home):
    """register_mcp_server raises TypeError when server_def is a string."""
    with pytest.raises(TypeError):
        register_mcp_server("bad")  # type: ignore[arg-type]


def test_register_succeeds_when_log_event_is_none(fake_home):
    """register_mcp_server does not crash when log_event is None (ImportError path)."""
    with patch("runtime.drivers.cursor.mcp_config.log_event", None):
        register_mcp_server({"command": "z", "args": []})

    config_path = fake_home / ".cursor" / "mcp.json"
    assert config_path.exists()
