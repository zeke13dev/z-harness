"""
runtime/drivers/codex — Codex CLI HostDriver package.

This package implements the CLI-tier HostDriver for the Codex CLI backend within
the host-neutral z-harness runtime. It owns:

- auth.py      : three-step auth resolution chain (CODEX_API_KEY →
                 OPENAI_API_KEY via model_providers workaround →
                 ~/.codex/auth.json presence check)
- driver.py    : main HostDriver implementation (subprocess invocation,
                 stream parsing, error handling)
- stream.py    : stream-json JSONL parser (frame-by-frame)
- mcp.py       : MCP registration helper (wraps `codex mcp add`)
- probe.py     : early probe tasks (session-resumption flag detection,
                 cross-env collision smoke test)

Public entry point:

    from runtime.drivers.codex import CodexDriver
"""

from runtime.drivers.codex.auth import AuthResolutionError, AuthResult, resolve_auth
from runtime.drivers.codex.driver import CodexDriver

__all__ = ["AuthResult", "AuthResolutionError", "CodexDriver", "resolve_auth"]
