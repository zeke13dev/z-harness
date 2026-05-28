"""
Tests for runtime/drivers/antigravity/mcp_config.py.

Exercises:
  - read_mcp_config("global") with and without existing file
  - read_mcp_config("project") with and without existing file
  - Invalid scope raises ValueError
  - Telemetry: agy_mcp_config_read emitted with path and server_count
  - add_stdio_server returns updated config (write=False, no disk write)
  - add_stdio_server with write=True writes file and emits agy_mcp_config_write
  - add_stdio_server with unsupported transport raises NotImplementedError
  - write=False default enforced (no disk mutation without opt-in)
  - Telemetry unavailable: no crash
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.drivers.antigravity.mcp_config import add_stdio_server, read_mcp_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def suppress_log_event(monkeypatch):
    """
    Suppress real log_event calls by default so tests don't require
    scripts/log-event.sh.  Tests that need to inspect telemetry calls use
    patch('runtime.drivers.antigravity.mcp_config.log_event') explicitly.
    """
    with patch("runtime.drivers.antigravity.mcp_config.log_event") as _mock:
        yield _mock


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Point HOME at a temp directory so we never touch the real ~/.gemini."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Path.home() reads $HOME on POSIX; make it consistent
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture()
def fake_cwd(tmp_path, monkeypatch):
    """Point cwd at a temp directory so project-scope tests stay isolated."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# read_mcp_config — global scope
# ---------------------------------------------------------------------------


def test_read_global_returns_empty_dict_when_missing(fake_home):
    """Missing ~/.gemini/config/mcp_config.json returns {}."""
    result = read_mcp_config("global")
    assert result == {}


def test_read_global_parses_existing_file(fake_home):
    """Existing mcp_config.json is parsed and returned."""
    config_dir = fake_home / ".gemini" / "config"
    config_dir.mkdir(parents=True)
    payload = {"mcpServers": {"my-server": {"command": "python", "args": ["-m", "my_mcp"]}}}
    (config_dir / "mcp_config.json").write_text(json.dumps(payload), encoding="utf-8")

    result = read_mcp_config("global")
    assert result == payload


def test_read_global_server_count_reflects_entries(fake_home):
    """server_count in telemetry matches the number of mcpServers entries."""
    config_dir = fake_home / ".gemini" / "config"
    config_dir.mkdir(parents=True)
    payload = {
        "mcpServers": {
            "server-a": {"command": "a", "args": []},
            "server-b": {"command": "b", "args": []},
        }
    }
    (config_dir / "mcp_config.json").write_text(json.dumps(payload), encoding="utf-8")

    with patch("runtime.drivers.antigravity.mcp_config.log_event") as mock_log:
        read_mcp_config("global")

    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["payload"]["server_count"] == 2


# ---------------------------------------------------------------------------
# read_mcp_config — project scope
# ---------------------------------------------------------------------------


def test_read_project_returns_empty_dict_when_missing(fake_cwd):
    """Missing .agents/mcp_config.json returns {}."""
    result = read_mcp_config("project")
    assert result == {}


def test_read_project_parses_existing_file(fake_cwd):
    """.agents/mcp_config.json is parsed and returned."""
    agents_dir = fake_cwd / ".agents"
    agents_dir.mkdir()
    payload = {"mcpServers": {"proj-server": {"command": "node", "args": ["server.js"]}}}
    (agents_dir / "mcp_config.json").write_text(json.dumps(payload), encoding="utf-8")

    result = read_mcp_config("project")
    assert result == payload


# ---------------------------------------------------------------------------
# read_mcp_config — invalid scope
# ---------------------------------------------------------------------------


def test_read_invalid_scope_raises():
    """Unknown scope raises ValueError."""
    with pytest.raises(ValueError, match="Unknown scope"):
        read_mcp_config("workspace")


# ---------------------------------------------------------------------------
# read_mcp_config — telemetry agy_mcp_config_read
# ---------------------------------------------------------------------------


def test_read_emits_event_with_path_and_server_count(fake_home):
    """agy_mcp_config_read is emitted with correct path and server_count=0 when missing."""
    with patch("runtime.drivers.antigravity.mcp_config.log_event") as mock_log:
        read_mcp_config("global")

    mock_log.assert_called_once()
    payload = mock_log.call_args.kwargs["payload"]
    assert "path" in payload
    assert payload["server_count"] == 0
    assert mock_log.call_args.kwargs["kind"] == "agy_mcp_config_read"


def test_read_path_in_telemetry_matches_global_location(fake_home):
    """The path field in telemetry points to ~/.gemini/config/mcp_config.json."""
    with patch("runtime.drivers.antigravity.mcp_config.log_event") as mock_log:
        read_mcp_config("global")

    path_in_event = mock_log.call_args.kwargs["payload"]["path"]
    assert path_in_event.endswith(os.path.join(".gemini", "config", "mcp_config.json"))


# ---------------------------------------------------------------------------
# add_stdio_server — write=False (no disk mutation)
# ---------------------------------------------------------------------------


def test_add_stdio_server_returns_updated_config_no_write(fake_home):
    """add_stdio_server returns config with new entry, no file written (write=False)."""
    result = add_stdio_server("my-tool", "python3", ["-m", "my_tool_server"])
    assert "mcpServers" in result
    assert "my-tool" in result["mcpServers"]
    assert result["mcpServers"]["my-tool"]["command"] == "python3"
    assert result["mcpServers"]["my-tool"]["args"] == ["-m", "my_tool_server"]


def test_add_stdio_server_does_not_write_file_by_default(fake_home):
    """write=False (default) must not create the mcp_config.json file on disk."""
    add_stdio_server("my-tool", "python3", ["-m", "my_tool_server"])

    config_file = fake_home / ".gemini" / "config" / "mcp_config.json"
    assert not config_file.exists(), "Config file must not be written when write=False"


def test_add_stdio_server_no_write_does_not_emit_write_event(fake_home):
    """No agy_mcp_config_write event is emitted when write=False."""
    with patch("runtime.drivers.antigravity.mcp_config.log_event") as mock_log:
        add_stdio_server("my-tool", "cmd", [])

    emitted_kinds = [call.kwargs["kind"] for call in mock_log.call_args_list]
    assert "agy_mcp_config_write" not in emitted_kinds


# ---------------------------------------------------------------------------
# add_stdio_server — write=True (persists to disk)
# ---------------------------------------------------------------------------


def test_add_stdio_server_write_true_creates_file(fake_home):
    """write=True creates mcp_config.json with the new server entry."""
    add_stdio_server("my-tool", "npx", ["my-server"], write=True)

    config_file = fake_home / ".gemini" / "config" / "mcp_config.json"
    assert config_file.exists()
    data = json.loads(config_file.read_text(encoding="utf-8"))
    assert "my-tool" in data["mcpServers"]


def test_add_stdio_server_write_true_emits_write_event(fake_home):
    """write=True emits agy_mcp_config_write with path and servers_added."""
    with patch("runtime.drivers.antigravity.mcp_config.log_event") as mock_log:
        add_stdio_server("my-tool", "npx", ["my-server"], write=True)

    write_calls = [c for c in mock_log.call_args_list if c.kwargs["kind"] == "agy_mcp_config_write"]
    assert len(write_calls) == 1
    payload = write_calls[0].kwargs["payload"]
    assert "path" in payload
    assert payload["servers_added"] == 1


def test_add_stdio_server_write_true_round_trips(fake_home):
    """Config written by write=True can be read back via read_mcp_config."""
    add_stdio_server("round-trip", "/usr/bin/node", ["server.js"], write=True)
    config = read_mcp_config("global")
    assert "round-trip" in config["mcpServers"]
    assert config["mcpServers"]["round-trip"]["command"] == "/usr/bin/node"


def test_add_stdio_server_preserves_existing_entries(fake_home):
    """Adding a new server does not overwrite existing mcpServers entries."""
    config_dir = fake_home / ".gemini" / "config"
    config_dir.mkdir(parents=True)
    existing = {"mcpServers": {"existing": {"command": "old", "args": []}}}
    (config_dir / "mcp_config.json").write_text(json.dumps(existing), encoding="utf-8")

    add_stdio_server("new-server", "new-cmd", [], write=True)
    config = read_mcp_config("global")
    assert "existing" in config["mcpServers"]
    assert "new-server" in config["mcpServers"]


# ---------------------------------------------------------------------------
# add_stdio_server — unsupported transport raises NotImplementedError
# ---------------------------------------------------------------------------


def test_add_stdio_server_rejects_sse_transport(fake_home):
    """Passing transport='sse' raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="stdio"):
        add_stdio_server("my-tool", "cmd", [], transport="sse")


def test_add_stdio_server_rejects_http_transport(fake_home):
    """Passing transport='http' raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="stdio"):
        add_stdio_server("my-tool", "cmd", [], transport="http")


def test_add_stdio_server_unsupported_transport_does_not_write(fake_home):
    """NotImplementedError from bad transport must not create any file."""
    with pytest.raises(NotImplementedError):
        add_stdio_server("my-tool", "cmd", [], transport="streamable-http", write=True)

    config_file = fake_home / ".gemini" / "config" / "mcp_config.json"
    assert not config_file.exists()


# ---------------------------------------------------------------------------
# Telemetry unavailable — no crash
# ---------------------------------------------------------------------------


def test_read_succeeds_when_log_event_is_none(fake_home):
    """read_mcp_config does not crash when log_event is None."""
    with patch("runtime.drivers.antigravity.mcp_config.log_event", None):
        result = read_mcp_config("global")
    assert result == {}


def test_add_stdio_server_succeeds_when_log_event_is_none(fake_home):
    """add_stdio_server does not crash when log_event is None."""
    with patch("runtime.drivers.antigravity.mcp_config.log_event", None):
        result = add_stdio_server("tool", "cmd", [], write=True)
    assert "tool" in result["mcpServers"]
