"""
runtime/drivers/codex/mcp.py — MCP registration helper for the Codex CLI.

Wraps ``codex mcp add`` to register an MCP server in the user's Codex config.
Registration is idempotent: the function checks for an existing
``[mcp_servers.<server_name>]`` entry in the Codex config TOML before
invoking the CLI, and skips re-registration if the entry is already present.

This module is intentionally a one-time-setup helper, not a hot-path component.
It is called at most once per driver lifecycle (typically during ``init()``),
never on every dispatch.

TOML parsing
------------
Uses stdlib ``tomllib`` (Python 3.11+) for reading config.toml.  Writing is
delegated entirely to ``codex mcp add``; this module never hand-edits TOML.

Error handling
--------------
A non-zero exit from ``codex mcp add`` raises ``McpRegistrationError`` with
the captured stderr text.  ``FileNotFoundError`` (codex not on PATH) is not
caught here — the caller should handle it if needed.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class McpRegistrationError(Exception):
    """Raised when ``codex mcp add`` exits non-zero.

    Attributes:
        stderr: The captured stderr output from the failed subprocess.
        returncode: The exit code returned by the ``codex mcp add`` subprocess.
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
        mcp_config_path: Filesystem path to the MCP configuration file (the
            value of the ``mcp_config_path`` field from the provider entry in
            ``providers.json``).  Passed directly to ``codex mcp add``.
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
        McpRegistrationError: If ``codex mcp add`` exits with a non-zero
            return code.  ``stderr`` and ``returncode`` attributes carry the
            captured output and exit code respectively.
    """
    config_toml_path = _resolve_config_toml(codex_path)

    if _is_already_registered(config_toml_path, server_name):
        return False

    _invoke_codex_mcp_add(
        codex_path=codex_path,
        mcp_config_path=mcp_config_path,
        server_name=server_name,
    )
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


def _invoke_codex_mcp_add(
    *,
    codex_path: str,
    mcp_config_path: str,
    server_name: str,
) -> None:
    """Run ``codex mcp add`` and raise McpRegistrationError on non-zero exit.

    Args:
        codex_path: Absolute path to the ``codex`` binary.
        mcp_config_path: Path to the MCP config file; passed to the CLI.
        server_name: Server name; passed to the CLI.

    Raises:
        McpRegistrationError: If the subprocess exits non-zero.
    """
    cmd = [codex_path, "mcp", "add", "--config", mcp_config_path, server_name]

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
