"""
runtime/drivers/antigravity/mcp_config.py — MCP config read/write helpers.

Provides utilities for reading and updating Antigravity's MCP configuration
file at ``~/.gemini/config/mcp_config.json`` (global scope) or
``.agents/mcp_config.json`` relative to the current working directory
(project scope).

Known bug (May 2026):
    Do not use environment variable references in mcp_config.json values;
    expansion is broken as of agy May 2026. Use literal paths.

v1 supports stdio transport only.  SSE and Streamable HTTP are not supported;
passing any other transport type raises ``NotImplementedError``.

Telemetry events emitted:
  ``agy_mcp_config_read``  — on every successful read; fields: path, server_count
  ``agy_mcp_config_write`` — on successful write; fields: path, servers_added
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

try:
    from runtime.compat import log_event
except ImportError:
    log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _config_path(scope: str) -> Path:
    """Return the absolute path to the MCP config file for the given scope."""
    if scope == "global":
        return Path.home() / ".gemini" / "config" / "mcp_config.json"
    elif scope == "project":
        return Path.cwd() / ".agents" / "mcp_config.json"
    else:
        raise ValueError(f"Unknown scope {scope!r}; expected 'global' or 'project'")


def _emit_read(path: Path, server_count: int, repo_root: str) -> None:
    """Emit ``agy_mcp_config_read`` telemetry."""
    if log_event is None:
        return
    try:
        log_event(
            run_id="agy-mcp-config",
            kind="agy_mcp_config_read",
            payload={"path": str(path), "server_count": server_count},
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError):
        pass


def _emit_write(path: Path, servers_added: int, repo_root: str) -> None:
    """Emit ``agy_mcp_config_write`` telemetry."""
    if log_event is None:
        return
    try:
        log_event(
            run_id="agy-mcp-config",
            kind="agy_mcp_config_write",
            payload={"path": str(path), "servers_added": servers_added},
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_mcp_config(scope: str = "global", repo_root: Optional[str] = None) -> dict:
    """
    Read the MCP configuration file for the given scope.

    Parameters
    ----------
    scope : str
        ``"global"`` reads ``~/.gemini/config/mcp_config.json``.
        ``"project"`` reads ``.agents/mcp_config.json`` relative to cwd.
    repo_root : str or None
        Absolute path to the repository root for telemetry.  Defaults to
        ``os.getcwd()`` when not supplied.

    Returns
    -------
    dict
        Parsed configuration, or an empty dict if the file does not exist.

    Notes
    -----
    Does not validate or expand environment variable references in existing
    config entries.  See module-level docstring for the known env-var bug.
    """
    effective_repo_root = repo_root if repo_root is not None else os.getcwd()
    path = _config_path(scope)
    if not path.exists():
        _emit_read(path, server_count=0, repo_root=effective_repo_root)
        return {}

    with path.open("r", encoding="utf-8") as fh:
        config: dict = json.load(fh)

    mcpServers = config.get("mcpServers", {})
    server_count = len(mcpServers)
    _emit_read(path, server_count=server_count, repo_root=effective_repo_root)
    return config


def add_stdio_server(
    name: str,
    command: str,
    args: List[str],
    *,
    transport: str = "stdio",
    write: bool = False,
    scope: str = "global",
    repo_root: Optional[str] = None,
) -> dict:
    """
    Add a stdio MCP server entry to the config and optionally persist it.

    Parameters
    ----------
    name : str
        Server name key inside ``mcpServers``.
    command : str
        Executable command for the server process.
    args : list[str]
        Arguments passed to the server process.
    transport : str
        Must be ``"stdio"`` (the only supported transport in v1).  Any other
        value raises ``NotImplementedError``.
    write : bool
        When ``True``, the updated config is written back to disk and
        ``agy_mcp_config_write`` telemetry is emitted.  Defaults to ``False``
        (read-only safety — no disk mutation without explicit opt-in).
    scope : str
        ``"global"`` or ``"project"`` — passed to ``read_mcp_config``.
    repo_root : str or None
        Absolute path to the repository root for telemetry.  Defaults to
        ``os.getcwd()`` when not supplied.

    Returns
    -------
    dict
        The updated config dict (regardless of whether it was written).

    Raises
    ------
    NotImplementedError
        If ``transport`` is not ``"stdio"``.  SSE and Streamable HTTP are not
        supported in v1.

    Notes
    -----
    Do not use environment variable references in command or args values;
    expansion is broken as of agy May 2026. Use literal paths.
    """
    if transport != "stdio":
        raise NotImplementedError(
            f"Transport {transport!r} is not supported in v1; only 'stdio' is supported. "
            "SSE and Streamable HTTP transports are deferred to a future release."
        )

    effective_repo_root = repo_root if repo_root is not None else os.getcwd()

    config = read_mcp_config(scope=scope, repo_root=effective_repo_root)
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"][name] = {
        "command": command,
        "args": args,
    }

    if write:
        path = _config_path(scope)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
            fh.write("\n")
        _emit_write(path, servers_added=1, repo_root=effective_repo_root)

    return config
