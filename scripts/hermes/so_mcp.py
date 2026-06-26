"""Deprecated compatibility shim for Hermes ``so`` MCP orchestration.

Use ``hermes.mcp_hermes_orchestrator`` or
``scripts/hermes/mcp-hermes-orchestrator.py``. The orchestrator MCP server owns
its tmux lifecycle internally; this module only re-exports the active API for
older imports.
"""

from __future__ import annotations

from hermes import mcp_hermes_orchestrator as _orchestrator

CAPTURE_LIMIT = _orchestrator.CAPTURE_LIMIT
CommandRunner = _orchestrator.CommandRunner
SoMcpError = _orchestrator.SoMcpError
SoSessionRecord = _orchestrator.SoSessionRecord
SoSessionStore = _orchestrator.SoSessionStore
SubprocessCommandRunner = _orchestrator.SubprocessCommandRunner
build_initial_prompt = _orchestrator.build_initial_prompt
main = _orchestrator.main
mcp = _orchestrator.mcp
new_session_id = _orchestrator.new_session_id
read_so_session = _orchestrator.read_so_session
send_to_so_session = _orchestrator.send_to_so_session
start_so_session = _orchestrator.start_so_session
state_path = _orchestrator.state_path
tmux_session_name = _orchestrator.tmux_session_name
utc_now = _orchestrator.utc_now

AgentCommandError = SoMcpError
build_initial_so_prompt = build_initial_prompt

__all__ = [
    "AgentCommandError",
    "CAPTURE_LIMIT",
    "CommandRunner",
    "SoMcpError",
    "SoSessionRecord",
    "SoSessionStore",
    "SubprocessCommandRunner",
    "build_initial_prompt",
    "build_initial_so_prompt",
    "main",
    "mcp",
    "new_session_id",
    "read_so_session",
    "send_to_so_session",
    "start_so_session",
    "state_path",
    "tmux_session_name",
    "utc_now",
]
