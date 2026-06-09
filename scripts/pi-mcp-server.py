#!/Users/zeke/.hermes/hermes-agent/venv/bin/python3
"""
pi-mcp-server — MCP server wrapping pi-cli for Hermes Agent orchestration.

Tools:
  pi_instruct           One-shot pi invocation via subprocess pipes. Returns output,
                        model used, exit code, and usage stats.
  pi_inspect_model      List available pi models as structured JSON.

Exit codes:
  0  Normal MCP server lifecycle (process runs until stdin closes or SIGTERM)
  1  Fatal initialization error (module import failure)

All MCP JSON-RPC on stdout. Diagnostics to stderr.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from typing import Any

# macOS fork-safety: prevent CoreFoundation abort when pi subprocess triggers fork
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

from mcp.server.fastmcp import FastMCP  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "deepseek"
DEFAULT_TIMEOUT = 300  # seconds
PI_BIN = "pi"  # resolves from PATH; must include pi in PATH or set PI_BIN env

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "pi-mcp-server",
    instructions="MCP server wrapping pi-cli for Hermes Agent orchestration",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _content_text_parts(message: dict[str, Any]) -> list[str]:
    """Extract text content parts from a pi message dict."""
    content = message.get("content", [])
    if not isinstance(content, list):
        return []
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return parts


def _extract_text_and_usage(ndjson_output: str) -> tuple[str, dict[str, Any]]:
    """Parse pi --mode json NDJSON output.

    Strategy: iterate all lines, keep the last message_end or turn_end.
    Also accept agent_end if it has text content (otherwise skip — it's
    often a summary event with empty content). Fall back to raw output
    if no structured lines found.

    Returns (text_output, usage_dict).
    """
    last_message: dict[str, Any] | None = None

    for line in ndjson_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = obj.get("type")
        if event_type in ("message_end", "turn_end"):
            last_message = obj.get("message", {})
        elif event_type == "agent_end" and _content_text_parts(obj.get("message", {})):
            last_message = obj.get("message", {})

    if last_message is None:
        # No structured message found — return raw output
        return ndjson_output.strip(), {}

    # Extract text blocks from content array
    text_parts = _content_text_parts(last_message)
    text = "\n".join(text_parts) if text_parts else ""

    usage = last_message.get("usage", {})
    return text.strip(), usage


_RE_MODEL_CONTEXT = re.compile(r"^\d+[KM]$")
_RE_MODEL_BOOL = re.compile(r"^(yes|no)$")


def _parse_models_table(stdout: str) -> list[dict[str, str]]:
    """Parse pi --list-models table output.

    Uses token-level splitting with content-aware column assignment.
    This is robust against column-width overruns (model names longer than
    the space-padding between columns) because it identifies columns by
    their content patterns rather than fixed positions.

    Input example:
        provider  model              context  max-out  thinking  images
        deepseek  deepseek-v4-flash  1M       384K     yes       no
        deepseek  deepseek-v4-pro    1M       384K     yes       no

    Returns list of {provider, model, context, max_output}.
    """
    lines = stdout.strip().splitlines()
    if len(lines) < 2:
        return []

    models: list[dict[str, str]] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < 4:
            continue

        # Column layout (right-to-left):
        #   ...thinking images
        #   ...context  max-out  thinking  images
        # The last 2 tokens are always yes/no booleans (thinking, images).
        # The 2 before those are context and max-output (e.g. "1M", "384K").
        # The first token is the provider. Everything in between is the model
        # name (which can contain spaces when it overruns its column width).
        bool_tokens: list[str] = []
        while tokens and _RE_MODEL_BOOL.match(tokens[-1]):
            bool_tokens.insert(0, tokens.pop())
            if len(bool_tokens) >= 2:
                break

        size_tokens: list[str] = []
        while tokens and _RE_MODEL_CONTEXT.match(tokens[-1]):
            size_tokens.insert(0, tokens.pop())
            if len(size_tokens) >= 2:
                break

        if len(tokens) < 2 or len(size_tokens) < 2:
            # Can't reliably parse this row — skip it
            continue

        provider = tokens[0]
        model = " ".join(tokens[1:]) if len(tokens) > 1 else tokens[0]
        context = size_tokens[0]
        max_output = size_tokens[1]

        models.append({
            "provider": provider,
            "model": model,
            "context": context,
            "max_output": max_output,
        })

    return models


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def pi_instruct(
    instruction: str,
    context: str | None = None,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run a one-shot pi instruction and return the output.

    Spawns pi --mode json --no-session -p via subprocess pipes. Supplies
    the instruction on stdin (optionally prefixed with context as a system
    prompt directive). Waits up to `timeout` seconds for completion.

    Args:
        instruction: The instruction to send to pi.
        context: Optional additional context appended as system prompt.
        model: Model to use (default: deepseek-v4-flash).
        provider: Provider to use (default: deepseek).
        timeout: Maximum wait in seconds (default: 300).

    Returns:
        dict with keys: output (str), model_used (str), exit_code (int),
        and optionally usage (dict with token counts and cost).
    """
    stripped = instruction.strip()
    if not stripped:
        return {
            "output": "",
            "model_used": f"{provider}/{model}",
            "exit_code": -1,
            "error": "instruction is empty or whitespace-only",
        }

    pi_bin = os.environ.get("PI_BIN", PI_BIN)

    cmd = [
        pi_bin,
        "--provider", provider,
        "--model", model,
        "--no-session",
        "--mode", "json",
        "-p",
    ]
    if context:
        cmd.extend(["--append-system-prompt", context])

    start_time = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid if sys.platform != "win32" else None,
        )
    except FileNotFoundError:
        return {
            "output": "",
            "model_used": f"{provider}/{model}",
            "exit_code": -1,
            "error": f"pi binary not found: {pi_bin}",
        }

    try:
        stdout, stderr = proc.communicate(
            input=instruction,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Kill the process group
        if sys.platform != "win32":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)  # type: ignore[arg-type]
            except (ProcessLookupError, OSError):
                pass
        proc.kill()
        _ = proc.wait()
        elapsed = time.monotonic() - start_time
        return {
            "output": "",
            "model_used": f"{provider}/{model}",
            "exit_code": -1,
            "error": f"timed out after {elapsed:.0f}s (limit: {timeout}s)",
        }

    elapsed = time.monotonic() - start_time
    exit_code = proc.returncode

    if exit_code != 0:
        return {
            "output": stderr.strip() or stdout.strip(),
            "model_used": f"{provider}/{model}",
            "exit_code": exit_code,
            "error": f"pi exited with code {exit_code}" + (f" in {elapsed:.1f}s" if elapsed > 1 else ""),
        }

    text, usage = _extract_text_and_usage(stdout)

    result: dict[str, Any] = {
        "output": text,
        "model_used": f"{provider}/{model}",
        "exit_code": 0,
    }
    if usage:
        result["usage"] = usage

    return result


@mcp.tool()
def pi_inspect_model() -> dict[str, Any]:
    """List available pi models with their capabilities.

    Runs pi --list-models and parses the table output into structured JSON.

    Returns:
        dict with key "models": list of {provider, model, context, max_output}.
    """
    pi_bin = os.environ.get("PI_BIN", PI_BIN)

    try:
        result = subprocess.run(
            [pi_bin, "--list-models"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return {
            "models": [],
            "error": f"pi binary not found: {pi_bin}",
        }
    except subprocess.TimeoutExpired:
        return {
            "models": [],
            "error": "pi --list-models timed out",
        }

    if result.returncode != 0:
        return {
            "models": [],
            "error": f"pi exited with code {result.returncode}: {result.stderr.strip()}",
        }

    models = _parse_models_table(result.stdout)
    return {"models": models}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run the MCP server over stdio."""
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"pi-mcp-server: fatal error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
