"""commands/serve.py — `z-harness serve` command.

Starts the z-harness MCP server via stdio transport.
"""

from __future__ import annotations

import typer


def run(
    ctx: typer.Context,
    *,
    transport: str = "stdio",
) -> int:
    """Start the z-harness MCP server.

    Args:
        transport: MCP transport protocol (currently only "stdio").
    """
    from z_harness_cli.mcp.server import serve

    serve(transport=transport)
    return 0
