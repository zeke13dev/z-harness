#!/usr/bin/env python3
"""
pi-mcp-server — MCP server wrapping pi-cli for Hermes Agent orchestration.

Tools (public):
  pi_instruct             One-shot pi invocation via subprocess pipes.
  pi_inspect_model        List available pi models.
  pi_start_session        Start an interactive pi session (multi-turn).
  pi_send                 Send a message to an existing session.
  pi_list_sessions        List all active sessions and their status.
  pi_session_status       Get status and last output of a single session.

Session model:
  Each "turn" in a session is a fresh `pi --session-id <id> --mode json -p`
  invocation.  pi's session state persists on disk between turns, so we get
  full conversation history without keeping background processes alive.
  Session metadata (owner, created_at, cumulative cost) is tracked in a
  JSON state file at ~/.hermes/pi-sessions.json.

Exit codes:
  0  Normal server lifecycle
  1  Fatal initialization error
"""

from __future__ import annotations

import json
import os
import random
import re
import signal
import string
import subprocess
import sys
import time
import uuid
from typing import Any

# macOS fork-safety
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

from mcp.server.fastmcp import FastMCP  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_PROVIDER = "deepseek"
DEFAULT_TIMEOUT = 300  # seconds
PI_BIN = "pi"

SESSION_STATE_DIR = os.path.expanduser("~/.hermes")
SESSION_STATE_FILE = os.path.join(SESSION_STATE_DIR, "pi-sessions.json")

# ---------------------------------------------------------------------------
# Session state persistence
# ---------------------------------------------------------------------------


def _load_state() -> dict[str, Any]:
    """Load session state from disk."""
    if not os.path.exists(SESSION_STATE_FILE):
        return {}
    try:
        with open(SESSION_STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    """Save session state to disk."""
    os.makedirs(SESSION_STATE_DIR, exist_ok=True)
    with open(SESSION_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _generate_session_id() -> str:
    """Generate a short human-readable session ID."""
    prefix = random.choice(string.ascii_lowercase)
    suffix = uuid.uuid4().hex[:7]
    return f"{prefix}-{suffix}"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Helpers: output parsing
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

    Returns (text_output, usage_dict).
    """
    last_message: dict[str, Any] | None = None
    last_usage: dict[str, Any] = {}

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
            usage = obj.get("message", {}).get("usage", {}) or obj.get("usage", {})
            if usage:
                last_usage = usage
        elif event_type == "agent_end" and _content_text_parts(obj.get("message", {})):
            last_message = obj.get("message", {})
        elif event_type in ("message_update",):
            # Accumulate usage from update events
            usage = obj.get("assistantMessageEvent", {}).get("partial", {}).get("usage", {})
            if usage:
                last_usage = usage
        # Also capture usage at turn_end / agent_end level
        if event_type == "turn_end" and obj.get("message", {}).get("usage"):
            last_usage = obj["message"]["usage"]
        if event_type == "agent_end":
            msg = obj.get("message", {})
            usage = msg.get("usage", {}) if isinstance(msg, dict) else {}
            if usage:
                last_usage = usage
            # Try the outer messages list for cumulative usage
            msgs = obj.get("messages", [])
            for m in reversed(msgs):
                u = m.get("usage", {}) if isinstance(m, dict) else {}
                if u:
                    last_usage = u
                    break

    if last_message is None:
        return ndjson_output.strip(), {}

    text_parts = _content_text_parts(last_message)
    text = "\n".join(text_parts) if text_parts else ""

    # Fallback: also check last_message.usage
    if not last_usage:
        last_usage = last_message.get("usage", {}) if isinstance(last_message, dict) else {}

    return text.strip(), last_usage


def _has_question(output: str) -> bool:
    """Heuristic: does pi's output look like it's asking the user a question?"""
    if not output:
        return False
    lines = output.strip().splitlines()

    # Check the last 10 non-empty lines for question-ish content
    text_block = "\n".join(l for l in lines if l.strip())[-2000:]
    checks = [
        "?" in text_block,                         # contains question mark
        "Options:" in text_block,                   # decision menu
        "Choose" in text_block,                     # choice prompt
        "Which" in text_block or "which" in text_block,
        "preference" in text_block.lower(),
        "signal convergence" in text_block.lower(),
    ]
    return sum(1 for c in checks if c) >= 2 or (
        "?" in text_block and any(kw in text_block.lower() for kw in
                                  ["prefer", "choose", "option", "continue", "proceed", "should I"])
    )


def _needs_user_input(output: str) -> bool:
    """Determine if pi is waiting for user input (vs. just reporting progress)."""
    if not output:
        return True  # empty output might mean it crashed
    # Check for explicit decision requests
    decision_patterns = [
        r"What'?s your (preference|choice|decision)",
        r"Options:\s*\n",
        r"shall (I|we)",
        r"should (I|we)",
        r"Do you want",
        r"Which (one|option|approach|framing)",
        r"Would you like",
        r"Are you (sure|ready)",
        r"Proceed\?",
        r"Continue\?",
        r"can you (confirm|decide|choose|pick)",
        r"need your (feedback|input|decision)",
        r"@user",
    ]
    for pat in decision_patterns:
        if re.search(pat, output, re.IGNORECASE | re.MULTILINE):
            return True
    return _has_question(output)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "pi-mcp-server",
    instructions="MCP server wrapping pi-cli for Hermes Agent orchestration",
)

# ---------------------------------------------------------------------------
# Internal: run pi
# ---------------------------------------------------------------------------


def _run_pi(
    instruction: str,
    *,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    timeout: int = DEFAULT_TIMEOUT,
    session_id: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Run pi and return structured result.

    If session_id is provided, uses --session-id for session continuation.
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
        "--mode", "json",
        "-p",  # non-interactive (process and exit)
    ]

    if session_id:
        cmd.extend(["--session-id", session_id])

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
        stdout, stderr = proc.communicate(input=instruction, timeout=timeout)
    except subprocess.TimeoutExpired:
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


# ---------------------------------------------------------------------------
# Tool: pi_instruct (one-shot, unchanged)
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

    Spawns pi --mode json --no-session -p via subprocess pipes.  Use for
    self-contained tasks that don't need follow-up questions.

    Args:
        instruction: The instruction to send to pi.
        context: Optional additional context (file path to a prompt).
        model: Model to use (default: deepseek-v4-flash).
        provider: Provider to use (default: deepseek).
        timeout: Maximum wait in seconds (default: 300).

    Returns:
        dict with keys: output (str), model_used (str), exit_code (int),
        and optionally usage (dict with token counts).
    """
    return _run_pi(instruction, model=model, provider=provider, timeout=timeout, context=context)


# ---------------------------------------------------------------------------
# Tool: pi_start_session (interactive, multi-turn)
# ---------------------------------------------------------------------------


@mcp.tool()
def pi_start_session(
    instruction: str,
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    timeout: int = DEFAULT_TIMEOUT,
    session_id: str | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Start an interactive pi session.

    Unlike pi_instruct, this creates a named session that persists on disk.
    Subsequent messages can be sent via pi_send(session_id, ...).

    Args:
        instruction: The initial instruction for pi.
        model: Model to use (default: deepseek-v4-flash).
        provider: Provider to use (default: deepseek).
        timeout: Maximum wait in seconds (default: 300).
        session_id: Optional explicit session ID (e.g. "btc-candidate-1").
                    Auto-generated if omitted.
        description: Optional human-readable description for the session.

    Returns:
        dict with keys: session_id (str), output (str), has_question (bool),
        needs_input (bool), model_used (str), usage (dict), exit_code (int).
    """
    sid = session_id or _generate_session_id()

    result = _run_pi(instruction, model=model, provider=provider, timeout=timeout, session_id=sid)

    output = result.get("output", "")
    usage = result.get("usage", {})

    # Save session state
    state = _load_state()
    state[sid] = {
        "session_id": sid,
        "description": description or f"pi session ({sid})",
        "model": f"{provider}/{model}",
        "provider": provider,
        "created_at": _now_iso(),
        "last_used": _now_iso(),
        "turn_count": 1,
        "cumulative_cost": _extract_cost(usage),
        "last_output": output[:2000],  # truncated preview
        "last_exit_code": result.get("exit_code", 0),
    }
    _save_state(state)

    return {
        "session_id": sid,
        "output": output,
        "has_question": _has_question(output),
        "needs_input": _needs_user_input(output),
        "model_used": result.get("model_used", f"{provider}/{model}"),
        "usage": usage,
        "exit_code": result.get("exit_code", 0),
    }


# ---------------------------------------------------------------------------
# Tool: pi_send (continue an interactive session)
# ---------------------------------------------------------------------------


@mcp.tool()
def pi_send(
    session_id: str,
    message: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Send a message to an existing interactive pi session.

    Resumes the session identified by session_id, sends the user's message,
    and returns pi's response.  The full conversation history is preserved
    by pi's session persistence.

    Args:
        session_id: The session ID from pi_start_session.
        message: The user's reply or instruction.
        timeout: Maximum wait in seconds (default: 300).

    Returns:
        dict with keys: session_id (str), output (str), has_question (bool),
        needs_input (bool), turn_count (int), usage (dict), exit_code (int).
    """
    if not message.strip():
        return {
            "session_id": session_id,
            "output": "",
            "has_question": False,
            "needs_input": False,
            "turn_count": 0,
            "exit_code": -1,
            "error": "message is empty",
        }

    state = _load_state()
    if session_id not in state:
        return {
            "session_id": session_id,
            "output": "",
            "has_question": False,
            "needs_input": False,
            "turn_count": 0,
            "exit_code": -1,
            "error": f"session not found: {session_id}. Use pi_list_sessions() to see active sessions.",
        }

    session_info = state[session_id]
    provider, model = _parse_model(session_info.get("model", f"{DEFAULT_PROVIDER}/{DEFAULT_MODEL}"))

    result = _run_pi(message, model=model, provider=provider, timeout=timeout, session_id=session_id)

    output = result.get("output", "")
    usage = result.get("usage", {})

    turn_count = session_info.get("turn_count", 0) + 1
    prev_cost = session_info.get("cumulative_cost", 0.0)
    cum_cost = prev_cost + _extract_cost(usage)

    _extract_usage_for_cost(usage)

    state[session_id] = {
        **session_info,
        "last_used": _now_iso(),
        "turn_count": turn_count,
        "cumulative_cost": cum_cost,
        "last_output": output[:2000],
        "last_exit_code": result.get("exit_code", 0),
    }
    _save_state(state)

    return {
        "session_id": session_id,
        "output": output,
        "has_question": _has_question(output),
        "needs_input": _needs_user_input(output),
        "turn_count": turn_count,
        "model_used": result.get("model_used", f"{provider}/{model}"),
        "usage": usage,
        "cumulative_cost": round(cum_cost, 6),
        "exit_code": result.get("exit_code", 0),
    }


# ---------------------------------------------------------------------------
# Tool: pi_list_sessions
# ---------------------------------------------------------------------------


@mcp.tool()
def pi_list_sessions() -> dict[str, Any]:
    """List all tracked pi sessions and their status.

    Returns:
        dict with key "sessions": list of {session_id, description, model,
        turn_count, cumulative_cost, last_used, last_output_preview, has_pending_question}.
    """
    state = _load_state()
    sessions = []
    for sid, info in state.items():
        last_out = info.get("last_output", "")
        sessions.append({
            "session_id": sid,
            "description": info.get("description", ""),
            "model": info.get("model", ""),
            "provider": info.get("provider", ""),
            "turn_count": info.get("turn_count", 0),
            "cumulative_cost": info.get("cumulative_cost", 0.0),
            "created_at": info.get("created_at", ""),
            "last_used": info.get("last_used", ""),
            "last_output_preview": last_out[:500] if last_out else "",
            "has_pending_question": _has_question(last_out) if last_out else False,
            "needs_user_input": _needs_user_input(last_out) if last_out else False,
        })
    # Sort by last_used descending
    sessions.sort(key=lambda s: s.get("last_used", ""), reverse=True)
    return {"sessions": sessions, "count": len(sessions)}


# ---------------------------------------------------------------------------
# Tool: pi_session_status
# ---------------------------------------------------------------------------


@mcp.tool()
def pi_session_status(
    session_id: str,
) -> dict[str, Any]:
    """Get the status and last output of a single pi session.

    Args:
        session_id: The session ID to query.

    Returns:
        dict with session metadata, last output, and whether it needs input.
    """
    state = _load_state()
    if session_id not in state:
        return {
            "session_id": session_id,
            "error": f"session not found: {session_id}",
            "found": False,
        }

    info = state[session_id]
    last_out = info.get("last_output", "")

    return {
        "session_id": session_id,
        "description": info.get("description", ""),
        "model": info.get("model", ""),
        "provider": info.get("provider", ""),
        "turn_count": info.get("turn_count", 0),
        "cumulative_cost": info.get("cumulative_cost", 0.0),
        "created_at": info.get("created_at", ""),
        "last_used": info.get("last_used", ""),
        "last_output": last_out,
        "has_pending_question": _has_question(last_out) if last_out else False,
        "needs_user_input": _needs_user_input(last_out) if last_out else False,
        "found": True,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_PATTERN = re.compile(r"^(?:(\w+)/)?(.+)$")


def _parse_model(model_str: str) -> tuple[str, str]:
    """Parse 'provider/model' into (provider, model)."""
    m = _MODEL_PATTERN.match(model_str)
    if m:
        return m.group(1) or DEFAULT_PROVIDER, m.group(2)
    return DEFAULT_PROVIDER, model_str


def _extract_cost(usage: dict[str, Any]) -> float:
    """Extract total cost from a usage dict."""
    if not usage:
        return 0.0
    cost = usage.get("cost", {}) if isinstance(usage.get("cost"), dict) else {}
    return float(cost.get("total", 0.0))


def _extract_usage_for_cost(usage: dict[str, Any]) -> dict[str, Any]:
    """Normalize usage dict for cost calculation."""
    cost = usage.get("cost", {})
    if isinstance(cost, dict):
        return {"total_cost": float(cost.get("total", 0.0))}
    return {}


# ---------------------------------------------------------------------------
# Tool: pi_inspect_model
# ---------------------------------------------------------------------------

_RE_MODEL_CONTEXT = re.compile(r"^\d+[KM]$")
_RE_MODEL_BOOL = re.compile(r"^(yes|no)$")


def _parse_models_table(stdout: str) -> list[dict[str, str]]:
    """Parse pi --list-models table output."""
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


@mcp.tool()
def pi_inspect_model() -> dict[str, Any]:
    """List available pi models with their capabilities.

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
        return {"models": [], "error": f"pi binary not found: {pi_bin}"}
    except subprocess.TimeoutExpired:
        return {"models": [], "error": "pi --list-models timed out"}

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
