"""Native OMP HostDriver backed by the ``omp`` subprocess.

This driver is for native command dispatch only.  The consult-provider
compatibility adapter (``scripts/omp-consult.sh --no-rules --no-session``) is
intentionally not used here: native OMP dispatch receives the harness plugin via
``OMP_PLUGIN_ROOT`` and preserves caller-supplied session/profile/rules flags.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any, Iterator

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]

_OMP_BIN = "omp"
_FORBIDDEN_COMPAT_NAMES = ("omp-consult.sh", "scripts/omp-consult.sh")
_CONSULT_ONLY_FLAGS = ("--no-rules", "--no-session")


class OmpDriverConfigError(ValueError):
    """Raised when native OMP dispatch is invoked with an invalid contract."""


class OmpHostDriver(HostDriver):
    """HostDriver that invokes ``omp`` directly in print mode."""

    def __init__(self) -> None:
        self._provider_config: dict[str, Any] = {}
        self._run_id = "omp-driver"
        self._repo_root = os.getcwd()
        self._plugin_root: str | None = None
        self._omp_bin = _OMP_BIN

    def init(self, provider_config: dict, context: dict | None = None) -> None:
        """Store provider config and optional runtime context.

        Recognised context keys are ``run_id``, ``repo_root``, and either
        ``omp_plugin_root`` or ``plugin_root``.  Unknown keys are ignored.
        """
        self._provider_config = dict(provider_config)
        ctx = context or {}
        if "run_id" in ctx:
            self._run_id = str(ctx["run_id"])
        if "repo_root" in ctx:
            self._repo_root = str(ctx["repo_root"])
        plugin_root = ctx.get("omp_plugin_root", ctx.get("plugin_root"))
        if plugin_root is None:
            plugin_root = self._provider_config.get("omp_plugin_root") or self._provider_config.get("plugin_root")
        if plugin_root is not None:
            self._plugin_root = str(plugin_root)
        command = str(self._provider_config.get("command") or _OMP_BIN)
        _reject_compat_command(command)
        self._omp_bin = command

    def dispatch(self, command_id: str, args: list[str], env: dict) -> DispatchHandle:
        """Launch native ``omp`` and return a streaming dispatch handle.

        ``args`` is the dispatcher's final argv tail.  The final token is the
        prompt.  If the provider config supplies model/profile/session fields and
        the corresponding flags are absent from ``args``, the driver adds them
        before the final prompt.  ``--no-rules`` and ``--no-session`` are
        consult-mode concerns; native dispatch rejects them before spawning.
        """
        prompt = _extract_prompt(args)
        argv = self._build_args(prompt=prompt, args=args)
        proc_env = self._build_env(env)
        return self._spawn(command_id=command_id, argv=argv, env=proc_env, prompt=prompt)

    def teardown(self) -> None:
        """No-op; native OMP subprocesses are per-dispatch."""

    def _build_args(self, *, prompt: str, args: list[str]) -> list[str]:
        """Return full native OMP argv with prompt as the final positional arg."""
        tail = list(args[:-1])
        _reject_consult_only_flags(tail)
        if _contains_forbidden_compat(tail):
            raise OmpDriverConfigError("native OMP driver must not invoke scripts/omp-consult.sh")

        if not _has_print_flag(tail):
            tail.insert(0, "-p")

        model = self._provider_config.get("model") or self._provider_config.get("default_model")
        if model and not _has_flag(tail, "--model"):
            tail.extend(["--model", str(model)])

        profile = self._provider_config.get("profile")
        if profile and not _has_flag(tail, "--profile"):
            tail.extend(["--profile", str(profile)])

        session_id = self._provider_config.get("session_id") or self._provider_config.get("session")
        if session_id and not _has_flag(tail, "--session"):
            tail.extend(["--session", str(session_id)])

        return [self._omp_bin, *tail, prompt]

    def _build_env(self, env: dict) -> dict:
        proc_env = dict(env)
        if self._plugin_root and "OMP_PLUGIN_ROOT" not in proc_env:
            proc_env["OMP_PLUGIN_ROOT"] = self._plugin_root
        return proc_env

    def _spawn(self, *, command_id: str, argv: list[str], env: dict, prompt: str) -> DispatchHandle:
        args_redacted = _redact_args(argv)
        start = time.monotonic()
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        _fire_telemetry(
            "omp_driver_invoke",
            {
                "command": self._omp_bin,
                "args_redacted": args_redacted,
                "pid": proc.pid,
                "has_model": _has_flag(argv, "--model"),
                "has_profile": _has_flag(argv, "--profile"),
                "has_session": _has_flag(argv, "--session"),
            },
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

        collected_events: list[dict] = []
        assistant_chunks: list[str] = []
        explicit_final = False
        final_text: str | None = None
        session_id = _flag_value(argv, "--session")
        run_id = self._run_id
        repo_root = self._repo_root

        def _emit_event(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
            event = _event_envelope(
                driver="omp",
                command_id=command_id,
                session_id=session_id,
                sequence=len(collected_events) + 1,
                kind=kind,
                payload=payload,
            )
            collected_events.append(event)
            return event

        def _events_fn() -> Iterator[dict]:
            nonlocal explicit_final, final_text
            yield _emit_event("prompt_submitted", {"prompt_chars": len(prompt)})
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line.strip():
                    continue
                parsed = _parse_stdout_line(line)
                if parsed is None:
                    assistant_chunks.append(line)
                    yield _emit_event("assistant_delta", {"text": line})
                    continue
                kind, payload = _normalise_frame(parsed)
                if kind == "assistant_delta":
                    text = _payload_text(payload)
                    if text:
                        assistant_chunks.append(text)
                elif kind == "final_result":
                    explicit_final = True
                    final_text = _payload_text(payload)
                yield _emit_event(kind, payload)
            if assistant_chunks and not explicit_final:
                final_text = "\n".join(assistant_chunks)
                yield _emit_event("final_result", {"text": final_text})

        def _wait_fn() -> DispatchResult:
            proc.wait()
            elapsed_ms = (time.monotonic() - start) * 1000.0
            exit_code = proc.returncode if proc.returncode is not None else -1
            stderr_text = ""
            if proc.stderr is not None:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")
            no_usable_output = not any(e.get("kind") == "final_result" for e in collected_events)
            is_error = exit_code != 0 or no_usable_output
            if no_usable_output:
                suffix = "omp produced no usable output"
                stderr_text = f"{stderr_text.rstrip()}\n{suffix}".lstrip()
            _fire_telemetry(
                "omp_driver_error" if is_error else "omp_driver_complete",
                {
                    "exit_code": exit_code,
                    "is_error": is_error,
                    "wall_ms": round(elapsed_ms, 1),
                    "events_parsed": len(collected_events),
                },
                run_id=run_id,
                repo_root=repo_root,
            )
            stdout_text = final_text or ""
            return DispatchResult(
                exit_code=exit_code,
                is_error=is_error,
                stdout_events=list(collected_events),
                stdout=stdout_text,
                stderr=stderr_text,
                wall_ms=elapsed_ms,
                session_id=session_id,
            )

        return DispatchHandle(_events_fn=_events_fn, _wait_fn=_wait_fn)


def _extract_prompt(args: list[str]) -> str:
    if not args:
        raise OmpDriverConfigError("native OMP dispatch requires a prompt as the final argv token")
    prompt = args[-1]
    if not isinstance(prompt, str) or not prompt.strip():
        raise OmpDriverConfigError("native OMP dispatch rejects an empty prompt")
    return prompt


def _has_print_flag(args: list[str]) -> bool:
    return "-p" in args or "--print" in args


def _has_flag(args: list[str], flag: str) -> bool:
    return flag in args or any(arg.startswith(f"{flag}=") for arg in args)


def _flag_value(args: list[str], flag: str) -> str | None:
    for idx, arg in enumerate(args):
        if arg == flag and idx + 1 < len(args):
            return args[idx + 1]
        prefix = f"{flag}="
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return None


def _reject_compat_command(command: str) -> None:
    if any(command.endswith(name) or command == name for name in _FORBIDDEN_COMPAT_NAMES):
        raise OmpDriverConfigError("native OMP driver must not use scripts/omp-consult.sh")


def _reject_consult_only_flags(args: list[str]) -> None:
    forbidden = [flag for flag in _CONSULT_ONLY_FLAGS if _has_flag(args, flag)]
    if forbidden:
        joined = ", ".join(forbidden)
        raise OmpDriverConfigError(f"native OMP dispatch rejects consult-only flags: {joined}")


def _contains_forbidden_compat(args: list[str]) -> bool:
    return any(any(part.endswith(name) or part == name for name in _FORBIDDEN_COMPAT_NAMES) for part in args)


def _parse_stdout_line(line: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalise_frame(frame: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    raw_kind = str(frame.get("kind") or frame.get("type") or frame.get("event") or "event")
    kind = _map_kind(raw_kind)
    payload = frame.get("payload")
    if not isinstance(payload, dict):
        payload = {k: v for k, v in frame.items() if k not in {"kind", "type", "event", "payload"}}

    if kind == "assistant_delta":
        text = frame.get("delta", frame.get("text", frame.get("content")))
        if text is not None and "text" not in payload:
            payload = {**payload, "text": str(text)}
    elif kind == "final_result":
        text = frame.get("result", frame.get("text", frame.get("content")))
        if text is not None and "text" not in payload:
            payload = {**payload, "text": str(text)}
    elif kind == "tool_call":
        name = frame.get("name") or frame.get("tool") or frame.get("tool_name")
        if name is not None and "name" not in payload:
            payload = {**payload, "name": name}
    elif kind == "subagent":
        agent = frame.get("agent") or frame.get("subagent") or frame.get("name")
        if agent is not None and "agent" not in payload:
            payload = {**payload, "agent": agent}
    elif kind == "ask_user":
        question = frame.get("question") or frame.get("prompt") or frame.get("content")
        if question is not None and "question" not in payload:
            payload = {**payload, "question": question}

    return kind, payload


def _map_kind(kind: str) -> str:
    normalized = kind.strip().lower().replace("-", "_")
    mapping = {
        "assistant": "assistant_delta",
        "assistant_text": "assistant_delta",
        "assistant_delta": "assistant_delta",
        "message_delta": "assistant_delta",
        "final": "final_result",
        "result": "final_result",
        "final_result": "final_result",
        "tool": "tool_call",
        "tool_call": "tool_call",
        "tool_result": "tool_result",
        "subagent": "subagent",
        "agent": "subagent",
        "ask_user": "ask_user",
        "askuser": "ask_user",
        "ask_user_question": "ask_user",
        "askuserquestion": "ask_user",
    }
    return mapping.get(normalized, normalized or "event")


def _payload_text(payload: dict[str, Any]) -> str | None:
    value = payload.get("text", payload.get("content", payload.get("delta")))
    return None if value is None else str(value)


def _event_envelope(
    *,
    driver: str,
    command_id: str,
    session_id: str | None,
    sequence: int,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "driver": driver,
        "command_id": command_id,
        "session_id": session_id,
        "sequence": sequence,
        "kind": kind,
        "payload": payload,
    }


_REDACT_VALUE_FLAGS = frozenset(
    {"--api-key", "--token", "--auth-token", "--model", "--profile", "--session"}
)


def _redact_args(argv: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for arg in argv:
        if redact_next:
            redacted.append("<redacted>")
            redact_next = False
            continue
        if arg in _REDACT_VALUE_FLAGS:
            redacted.append(arg)
            redact_next = True
            continue
        if any(arg.startswith(f"{flag}=") for flag in _REDACT_VALUE_FLAGS):
            redacted.append(f"{arg.split('=', 1)[0]}=<redacted>")
            continue
        redacted.append(arg)
    return redacted


def _fire_telemetry(kind: str, payload: dict, *, run_id: str, repo_root: str) -> None:
    if _log_event is None:
        return
    try:
        _log_event(run_id=run_id, kind=kind, payload=payload, repo_root=repo_root)
    except Exception as exc:  # noqa: BLE001 — telemetry must never block dispatch
        print(f"[omp_driver] WARNING: telemetry event '{kind}' failed: {exc}", file=sys.stderr)
