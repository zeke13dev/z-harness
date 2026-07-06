"""
runtime/drivers/codex/mcp.py — MCP registration helper for the Codex CLI.

Wraps ``codex mcp add`` to register an MCP server in the user's Codex config.
The exported MCP JSON is used as input to build the current Codex CLI shape:
``codex mcp add [--env KEY=VALUE ...] <name> -- <command> <args...>``.
Registration is idempotent: the function checks for an existing
``[mcp_servers.<server_name>]`` entry in the Codex config TOML before
invoking the CLI, and skips re-registration if the entry is already present
and matches the exported command/args/env/tool-approval policy.

This module is intentionally a one-time-setup helper, not a hot-path component.
It is called at most once per driver lifecycle (typically during ``init()``),
never on every dispatch.

TOML parsing
------------
Uses stdlib ``tomllib`` (Python 3.11+) for reading config.toml.  The Codex CLI
does not currently expose an argv flag for MCP tool approval policy, so after
``codex mcp add`` succeeds this module patches only the direct
``[mcp_servers.<server_name>]`` TOML keys needed for that policy and any
Codex-native tool filters.

Error handling
--------------
A missing/malformed MCP JSON config, missing server entry, or non-zero exit
from ``codex mcp add`` raises ``McpRegistrationError`` with diagnostic text.
``FileNotFoundError`` (codex not on PATH) is not caught here — the caller
should handle it if needed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class McpRegistrationError(Exception):
    """Raised when MCP registration cannot be prepared or completed.

    Attributes:
        stderr: Diagnostic text from validation or the failed subprocess.
        returncode: The subprocess exit code, or ``-1`` for local validation
            failures before ``codex mcp add`` is launched.
    """

    def __init__(self, message: str, *, stderr: str, returncode: int) -> None:
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_mcp_registered(
    mcp_config_path: str,
    server_name: str,
    codex_path: str,
) -> bool:
    """Register an MCP server with Codex CLI if it is not already registered.

    Checks ``~/.codex/config.toml`` (or the path derived from ``codex_path``)
    for an existing ``[mcp_servers.<server_name>]`` entry.  If the entry is
    found, returns ``False`` immediately — no subprocess is launched.  If the
    entry is absent, invokes ``codex mcp add`` and returns ``True``.

    Args:
        mcp_config_path: Filesystem path to the exported MCP JSON config.  The
            entry at ``mcpServers[server_name]`` supplies the command, args,
            and env values used to build ``codex mcp add`` argv.
        server_name: The logical server name to check and register (e.g.
            ``"filesystem"``).  Must match the ``[mcp_servers.<name>]`` TOML
            key that ``codex mcp add`` would create.
        codex_path: Absolute path to the ``codex`` binary.  Passed as the
            first element of the subprocess argv, so the caller controls which
            codex installation is used.

    Returns:
        ``True`` if registration was performed (``codex mcp add`` was invoked
        and succeeded), ``False`` if the server was already registered and the
        subprocess was skipped.

    Raises:
        McpRegistrationError: If the MCP JSON config is missing/malformed, the
            server entry is absent/invalid, or ``codex mcp add`` exits with a
            non-zero return code. ``stderr`` and ``returncode`` attributes
            carry diagnostic output and the exit code respectively.
    """
    config_toml_path = _resolve_config_toml(codex_path)
    already_registered = _is_already_registered(config_toml_path, server_name)

    if already_registered:
        try:
            desired_server = _load_mcp_server_config(mcp_config_path, server_name)
        except McpRegistrationError:
            # Preserve historical idempotency: if callers only know the entry is
            # present but cannot provide a readable desired config, do not
            # mutate the user's global Codex config.
            return False
        if _registered_server_matches(config_toml_path, server_name, desired_server):
            return False
        _invoke_codex_mcp_remove(codex_path=codex_path, server_name=server_name)
    else:
        desired_server = _load_mcp_server_config(mcp_config_path, server_name)

    _invoke_codex_mcp_add(
        codex_path=codex_path,
        mcp_config_path=mcp_config_path,
        server_name=server_name,
    )
    _ensure_registered_server_policy(config_toml_path, server_name, desired_server)
    return True


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _resolve_config_toml(codex_path: str) -> Path:
    """Return the path to ~/.codex/config.toml.

    The location is always ``~/.codex/config.toml`` regardless of ``codex_path``;
    Codex CLI does not support a custom config directory via argv.

    Args:
        codex_path: Not used for path resolution (Codex always uses ``~/.codex``),
            but kept in the signature to allow future overriding if needed.

    Returns:
        Absolute ``Path`` to ``~/.codex/config.toml``.
    """
    # codex_path is not used for path resolution — Codex always uses ~/.codex.
    # The parameter exists so callers can eventually pass an override.
    _ = codex_path  # unused intentionally
    return Path.home() / ".codex" / "config.toml"


def _is_already_registered(config_toml_path: Path, server_name: str) -> bool:
    """Return True if ``[mcp_servers.<server_name>]`` exists in the config TOML.

    If the config file does not exist or cannot be parsed, the entry is treated
    as absent (returns ``False``), allowing ``codex mcp add`` to proceed.

    Args:
        config_toml_path: Path to the ``config.toml`` file to inspect.
        server_name: The server key to look up under ``mcp_servers``.

    Returns:
        ``True`` if the section is present, ``False`` otherwise.
    """
    if not config_toml_path.exists():
        return False

    try:
        with config_toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        print(
            f"[codex_mcp] WARNING: could not parse {config_toml_path}: {exc}",
            file=sys.stderr,
        )
        return False

    mcp_servers = data.get("mcp_servers", {})
    return server_name in mcp_servers


def _registered_server_matches(
    config_toml_path: Path,
    server_name: str,
    desired_server: dict[str, object],
) -> bool:
    """Return True iff the registered server exactly matches desired config."""
    try:
        with config_toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return False

    mcp_servers = data.get("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        return False
    server = mcp_servers.get(server_name)
    if not isinstance(server, dict):
        return False

    return (
        server.get("command") == desired_server.get("command")
        and list(server.get("args") or []) == list(desired_server.get("args") or [])
        and dict(server.get("env") or {}) == dict(desired_server.get("env") or {})
        and _optional_string_list(server.get("enabled_tools"))
        == _optional_string_list(desired_server.get("enabled_tools"))
        and _optional_string_list(server.get("disabled_tools"))
        == _optional_string_list(desired_server.get("disabled_tools"))
        and server.get("default_tools_approval_mode")
        == desired_server.get("default_tools_approval_mode")
    )


def _ensure_registered_server_policy(
    config_toml_path: Path,
    server_name: str,
    desired_server: dict[str, object],
) -> None:
    """Patch Codex TOML for MCP tool approval policy and filters after ``mcp add``.

    ``codex mcp add`` owns command/args/env writing, but it has no flag for
    ``default_tools_approval_mode`` or tool filters.  Keep this patch surgical:
    only replace, insert, or remove those direct keys in
    ``[mcp_servers.<server_name>]``.
    """
    mode = desired_server.get("default_tools_approval_mode")
    if mode is not None and not isinstance(mode, str):
        _raise_config_error(
            f"MCP server {server_name!r} default_tools_approval_mode must be a string",
            server_name=server_name,
        )
    enabled_tools = _validate_optional_tool_list(
        desired_server.get("enabled_tools"),
        key="enabled_tools",
        server_name=server_name,
    )
    disabled_tools = _validate_optional_tool_list(
        desired_server.get("disabled_tools"),
        key="disabled_tools",
        server_name=server_name,
    )
    if mode is None and enabled_tools is None and disabled_tools is None:
        return

    try:
        original = config_toml_path.read_text(encoding="utf-8")
    except OSError as exc:
        _raise_config_error(
            f"could not read Codex config {config_toml_path}: {exc}",
            server_name=server_name,
        )

    header = f"[mcp_servers.{server_name}]"
    lines = original.splitlines()
    try:
        start = lines.index(header)
    except ValueError:
        _raise_config_error(
            f"Codex config {config_toml_path} is missing {header}",
            server_name=server_name,
        )

    end = start + 1
    while end < len(lines) and not lines[end].startswith("["):
        end += 1

    direct_updates: dict[str, str | None] = {
        "default_tools_approval_mode": (
            f'default_tools_approval_mode = "{mode}"' if mode is not None else None
        ),
        "enabled_tools": _toml_string_array_line("enabled_tools", enabled_tools),
        "disabled_tools": _toml_string_array_line("disabled_tools", disabled_tools),
    }
    changed = False
    insert_at = start + 1
    idx = start + 1
    while idx < end:
        key = lines[idx].split("=", 1)[0].strip()
        if key in direct_updates:
            desired_line = direct_updates.pop(key)
            if desired_line is None:
                del lines[idx]
                end -= 1
                changed = True
                continue
            if lines[idx] != desired_line:
                lines[idx] = desired_line
                changed = True
        idx += 1

    for desired_line in reversed([line for line in direct_updates.values() if line is not None]):
        lines.insert(insert_at, desired_line)
        changed = True

    if not changed:
        return

    updated = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    try:
        config_toml_path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        _raise_config_error(
            f"could not write Codex config {config_toml_path}: {exc}",
            server_name=server_name,
        )


def _invoke_codex_mcp_remove(*, codex_path: str, server_name: str) -> None:
    """Remove an existing Codex MCP server entry before refreshing it."""
    result = subprocess.run(
        [codex_path, "mcp", "remove", server_name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        raise McpRegistrationError(
            f"codex mcp remove failed for server '{server_name}' "
            f"(exit {result.returncode}): {stderr_text.strip()}",
            stderr=stderr_text,
            returncode=result.returncode,
        )


def _invoke_codex_mcp_add(
    *,
    codex_path: str,
    mcp_config_path: str,
    server_name: str,
) -> None:
    """Run ``codex mcp add`` and raise McpRegistrationError on non-zero exit.

    Args:
        codex_path: Absolute path to the ``codex`` binary.
        mcp_config_path: Path to the exported MCP JSON config.
        server_name: Server name to load from ``mcpServers`` and pass to the
            CLI.

    Raises:
        McpRegistrationError: If the MCP config cannot be loaded/validated or
            the subprocess exits non-zero.
    """
    server = _load_mcp_server_config(mcp_config_path, server_name)
    cmd = [codex_path, "mcp", "add"]
    for key, value in server["env"].items():
        cmd.extend(["--env", f"{key}={value}"])
    cmd.extend([server_name, "--", server["command"], *server["args"]])

    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace")
        raise McpRegistrationError(
            f"codex mcp add failed for server '{server_name}' "
            f"(exit {result.returncode}): {stderr_text.strip()}",
            stderr=stderr_text,
            returncode=result.returncode,
        )


def _load_mcp_server_config(
    mcp_config_path: str,
    server_name: str,
) -> dict[str, object]:
    """Load and validate one ``mcpServers`` entry from an exported config."""
    path = Path(mcp_config_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _raise_config_error(
            f"could not read MCP config {path}: {exc}",
            server_name=server_name,
        )
    except json.JSONDecodeError as exc:
        _raise_config_error(
            f"could not parse MCP config {path}: {exc}",
            server_name=server_name,
        )

    if not isinstance(raw, dict):
        _raise_config_error(
            f"MCP config {path} must be a JSON object",
            server_name=server_name,
        )

    mcp_servers = raw.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        _raise_config_error(
            f"MCP config {path} must contain an object mcpServers",
            server_name=server_name,
        )

    if server_name not in mcp_servers:
        _raise_config_error(
            f"MCP config {path} does not define server {server_name!r}",
            server_name=server_name,
        )

    server = mcp_servers[server_name]
    if not isinstance(server, dict):
        _raise_config_error(
            f"MCP server {server_name!r} in {path} must be an object",
            server_name=server_name,
        )

    command = server.get("command")
    if not isinstance(command, str):
        _raise_config_error(
            f"MCP server {server_name!r} in {path} must define string command",
            server_name=server_name,
        )

    args = server.get("args", [])
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        _raise_config_error(
            f"MCP server {server_name!r} in {path} must define args as a list of strings",
            server_name=server_name,
        )

    env = server.get("env", {})
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in env.items()
    ):
        _raise_config_error(
            f"MCP server {server_name!r} in {path} must define env as an object of string values",
            server_name=server_name,
        )

    default_tools_approval_mode = server.get("default_tools_approval_mode")
    if default_tools_approval_mode is not None and default_tools_approval_mode not in {
        "auto",
        "prompt",
        "approve",
    }:
        _raise_config_error(
            f"MCP server {server_name!r} in {path} must define "
            "default_tools_approval_mode as one of auto, prompt, approve",
            server_name=server_name,
        )

    result: dict[str, object] = {
        "command": command,
        "args": args,
        "env": env,
    }
    if default_tools_approval_mode is not None:
        result["default_tools_approval_mode"] = default_tools_approval_mode
    for key in ("enabled_tools", "disabled_tools"):
        value = _validate_optional_tool_list(
            server.get(key),
            key=key,
            server_name=server_name,
        )
        if value is not None:
            result[key] = value
    return result


def _optional_string_list(value: object) -> list[str] | None:
    """Return *value* as a list of strings, or None when absent/invalid."""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return list(value)


def _validate_optional_tool_list(
    value: object,
    *,
    key: str,
    server_name: str,
) -> list[str] | None:
    """Validate an optional Codex MCP tool-filter list."""
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        _raise_config_error(
            f"MCP server {server_name!r} {key} must be a list of strings",
            server_name=server_name,
        )
    return list(value)


def _toml_string_array_line(key: str, values: list[str] | None) -> str | None:
    """Render a direct TOML array assignment for a list of strings."""
    if values is None:
        return None
    return f"{key} = {json.dumps(values)}"


def _raise_config_error(message: str, *, server_name: str) -> None:
    """Raise a local MCP registration error before launching Codex CLI."""
    raise McpRegistrationError(
        f"cannot register MCP server '{server_name}': {message}",
        stderr=message,
        returncode=-1,
    )
