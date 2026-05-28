"""
runtime/drivers/cursor/mcp_config.py — Cursor MCP config writer.

Writes z-harness's MCP server registration to:
  - ~/.cursor/mcp.json      (global scope, always written)
  - .cursor/mcp.json        (project scope, written when project_root is supplied)

MCPoison guard (CVE-2025-54136 mitigation):
  The key name written into mcpServers MUST be the literal string
  ``MCP_KEY_NAME = "z-harness"``.  ``_assert_key_name`` enforces this before
  any write and raises ``MCPKeyNameError`` if the key is anything else.

Atomic write strategy:
  The updated JSON is written to ``<target>.tmp`` and then renamed over the
  target with ``os.replace``, which is atomic within the same filesystem.

Telemetry events emitted:
  ``mcp_config_write`` — on each successful write; fields: config_path,
  key_name, server_count (total mcpServers entries after merge).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

try:
    from runtime.compat import log_event
except ImportError:
    log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MCP_KEY_NAME: str = "z-harness"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MCPKeyNameError(ValueError):
    """Raised when the requested MCP key name differs from MCP_KEY_NAME.

    This is a security guard against MCP Poisoning (CVE-2025-54136): only the
    canonical key ``"z-harness"`` may be registered via this module.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _assert_key_name(key: str) -> None:
    """Raise MCPKeyNameError if *key* is not the canonical MCP_KEY_NAME.

    Parameters
    ----------
    key : str
        The key that the caller intends to register under mcpServers.

    Raises
    ------
    MCPKeyNameError
        If *key* != ``MCP_KEY_NAME``.
    """
    if key != MCP_KEY_NAME:
        raise MCPKeyNameError(
            f"MCP key name must be {MCP_KEY_NAME!r}; got {key!r}. "
            "This restriction prevents MCP Poisoning (CVE-2025-54136)."
        )


def _global_config_path() -> Path:
    """Return the absolute path to Cursor's global MCP config file."""
    return Path.home() / ".cursor" / "mcp.json"


def _project_config_path(project_root: str) -> Path:
    """Return the absolute path to the project-scoped MCP config file."""
    return Path(project_root) / ".cursor" / "mcp.json"


def _read_config(path: Path) -> dict:
    """Read and parse the JSON config at *path*, returning {} if absent.

    Parameters
    ----------
    path : Path
        Absolute path to the mcp.json file.

    Returns
    -------
    dict
        Parsed config, or ``{"mcpServers": {}}`` if the file does not exist.

    Raises
    ------
    json.JSONDecodeError
        If the file exists but contains invalid JSON.
    """
    if not path.exists():
        return {"mcpServers": {}}
    with path.open("r", encoding="utf-8") as fh:
        data: dict = json.load(fh)
    if "mcpServers" not in data:
        data["mcpServers"] = {}
    return data


def _write_config_atomic(path: Path, config: dict) -> None:
    """Atomically write *config* as JSON to *path*.

    Writes to ``<path>.tmp`` first, then renames over the target with
    ``os.replace``, which is atomic within the same filesystem on POSIX.

    Parameters
    ----------
    path : Path
        Destination file path.
    config : dict
        Config dict to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp_path), str(path))


def _emit_write(config_path: Path, key_name: str, server_count: int) -> None:
    """Emit ``mcp_config_write`` telemetry if log_event is available."""
    if log_event is None:
        return
    try:
        log_event(
            run_id="cursor-mcp-config",
            kind="mcp_config_write",
            payload={
                "config_path": str(config_path),
                "key_name": key_name,
                "server_count": server_count,
            },
            repo_root=os.getcwd(),
        )
    except (FileNotFoundError, RuntimeError):
        pass


def _merge_and_write(path: Path, server_def: dict, key_name: str) -> int:
    """Read config at *path*, merge *server_def* under *key_name*, write back.

    Parameters
    ----------
    path : Path
        Absolute path to the mcp.json config file.
    server_def : dict
        Server definition to register under ``mcpServers[key_name]``.
    key_name : str
        Key to use inside ``mcpServers``; must equal ``MCP_KEY_NAME``.

    Returns
    -------
    int
        Total number of entries in ``mcpServers`` after the merge.
    """
    config = _read_config(path)
    config["mcpServers"][key_name] = server_def
    _write_config_atomic(path, config)
    server_count = len(config["mcpServers"])
    _emit_write(path, key_name, server_count)
    return server_count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_mcp_server(
    server_def: dict,
    project_root: Optional[str] = None,
) -> None:
    """Register the z-harness MCP server in Cursor's mcp.json config files.

    Always writes to ``~/.cursor/mcp.json`` (global).  When *project_root* is
    supplied, also writes to ``<project_root>/.cursor/mcp.json`` (project).

    Existing entries in ``mcpServers`` are preserved (dict-merge, not replace).
    The ``z-harness`` key is upserted in-place.

    The write is atomic: the updated JSON is first written to a ``.tmp`` sibling
    and then renamed over the target via ``os.replace``.

    Parameters
    ----------
    server_def : dict
        MCP server definition dict (e.g. ``{"command": "...", "args": [...]}``).
        Schema validation beyond ``isinstance(server_def, dict)`` is delegated
        to the caller (C1's responsibility).
    project_root : str or None
        If provided, also write ``.cursor/mcp.json`` inside this directory.

    Raises
    ------
    MCPKeyNameError
        Always raised if the internal key constant ever diverges from
        ``"z-harness"`` — i.e., this is a static guard that fires at call time.
    TypeError
        If *server_def* is not a ``dict``.
    """
    if not isinstance(server_def, dict):
        raise TypeError(
            f"server_def must be a dict; got {type(server_def).__name__!r}"
        )

    # MCPoison guard — asserted before any filesystem write.
    _assert_key_name(MCP_KEY_NAME)

    global_path = _global_config_path()
    _merge_and_write(global_path, server_def, MCP_KEY_NAME)

    if project_root is not None:
        project_path = _project_config_path(project_root)
        _merge_and_write(project_path, server_def, MCP_KEY_NAME)
