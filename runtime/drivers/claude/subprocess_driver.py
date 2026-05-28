"""
runtime/drivers/claude/subprocess_driver.py — HostDriver that spawns ``claude -p --bare``.

``SubprocessClaudeDriver`` is used when another host (Cursor, Codex, a test
harness, …) wants to delegate work to Claude as a subprocess back-end.  It
always passes ``--bare`` and ``--output-format stream-json --verbose`` to the
``claude`` CLI, and always clears ``CLAUDECODE`` in the child environment
(``env_hygiene.apply_env_hygiene``).

Telemetry events emitted
------------------------
- ``subprocess_spawn``  — after ``Popen`` returns, with ``pid`` and ``args_redacted``
- ``subprocess_exit``   — after ``proc.wait()``, with ``exit_code``, ``is_error``, ``wall_ms``

Error handling
--------------
On non-zero exit the driver reads ``is_error`` from the last ``stream-json``
line before raising :class:`DriverExecutionError`.  Exit-code 1 alone is
insufficient because ``claude`` only emits ``0`` or ``1`` (see SPEC Invariant 3).

UUID validation
---------------
If a ``session_id`` is supplied to ``_spawn``, the driver validates it is a
valid UUID4 using ``uuid.UUID(session_id, version=4)`` and raises
:class:`ValueError` before touching ``subprocess.Popen``.

API-key redaction
-----------------
Args are scanned for ``--api-key``, ``ANTHROPIC_API_KEY=``, and values that
look like API keys (``sk-`` prefix) before being included in the telemetry
payload.  The actual subprocess argv is never modified.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from typing import Iterator

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult
from runtime.drivers.claude.env_hygiene import (
    BARE_FLAG,
    apply_env_hygiene,
)

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class DriverExecutionError(Exception):
    """Raised when claude exits non-zero and ``is_error`` is confirmed in output."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The claude CLI binary name.
_CLAUDE_BIN: str = "claude"

#: Flags always appended to every claude invocation.
_REQUIRED_FLAGS: list[str] = [
    BARE_FLAG,
    "--output-format",
    "stream-json",
    "--verbose",
]

#: Telemetry redaction patterns — arg names whose *following* value is a secret.
_REDACT_NEXT_AFTER: frozenset[str] = frozenset({"--api-key"})

#: Prefixes that identify secret-looking values in a single combined arg.
_SECRET_VALUE_PREFIXES: tuple[str, ...] = ("sk-",)

#: Combined-arg prefixes that indicate the value portion is a secret.
_SECRET_ARG_PREFIXES: tuple[str, ...] = ("ANTHROPIC_API_KEY=",)


# ---------------------------------------------------------------------------
# SubprocessClaudeDriver
# ---------------------------------------------------------------------------


class SubprocessClaudeDriver(HostDriver):
    """HostDriver that spawns ``claude -p --bare`` as a child process.

    Lifecycle
    ---------
    1. Caller calls ``driver.init(provider_config)`` once.
    2. For each prompt, caller calls ``driver.dispatch(command_id, args, env)``
       which delegates to :meth:`_spawn` and returns a :class:`DispatchHandle`.
    3. Caller iterates ``handle.events()`` to consume stream-json frames.
    4. Caller calls ``handle.wait()`` to collect the :class:`DispatchResult`.
    5. Caller calls ``driver.teardown()`` (no-op for this driver).

    Environment hygiene
    -------------------
    :func:`~runtime.drivers.claude.env_hygiene.apply_env_hygiene` is called
    inside :meth:`_spawn` to ensure ``CLAUDECODE=""`` in the child env.  The
    parent process env is never mutated.
    """

    def __init__(self) -> None:
        self._provider_config: dict = {}
        self._run_id: str = "subprocess-claude-driver"
        self._repo_root: str = ""

    # ------------------------------------------------------------------
    # HostDriver interface
    # ------------------------------------------------------------------

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Store provider config and optional runtime context.

        Args:
            provider_config: Provider block from providers.json.
            context: Optional runtime injections.  Recognised keys:
                - ``"run_id"`` (str) — forwarded to telemetry calls.
                - ``"repo_root"`` (str) — forwarded to telemetry calls.
                Unknown keys are silently ignored per C1-D5.
        """
        self._provider_config = provider_config
        ctx = context or {}
        if "run_id" in ctx:
            self._run_id = str(ctx["run_id"])
        if "repo_root" in ctx:
            self._repo_root = str(ctx["repo_root"])

    def dispatch(
        self,
        command_id: str,
        args: list[str],
        env: dict,
    ) -> DispatchHandle:
        """Launch ``claude -p --bare`` and return a streaming handle.

        Args:
            command_id: The command identifier (e.g. ``"z-ask"``).
            args: Additional args appended after the required flags.  The
                first element is treated as the prompt string when passed
                to :meth:`_spawn`.
            env: Full environment mapping from the dispatcher.

        Returns:
            A :class:`DispatchHandle` backed by the live subprocess.
        """
        prompt = args[0] if args else ""
        return self._spawn(prompt, session_id=None, extra_args=args[1:], env=env)

    def teardown(self) -> None:
        """No-op; SubprocessClaudeDriver holds no persistent resources."""

    # ------------------------------------------------------------------
    # Public lower-level helpers (used by T004 session layer)
    # ------------------------------------------------------------------

    def _build_args(self, prompt: str, session_id: str | None = None) -> list[str]:
        """Build the full argv for ``claude -p``.

        Args:
            prompt: The prompt text to pass as the positional argument.
            session_id: Optional validated UUID4 to pass via ``--resume``.

        Returns:
            A flat list of strings ready for :class:`subprocess.Popen`.

        Note:
            This method does **not** validate ``session_id`` — callers must
            validate before calling (see :meth:`_spawn`).
        """
        argv: list[str] = [_CLAUDE_BIN, "-p"]
        argv.extend(_REQUIRED_FLAGS)
        if session_id is not None:
            argv.extend(["--resume", session_id])
        argv.append(prompt)
        return argv

    def _spawn(
        self,
        prompt: str,
        session_id: str | None = None,
        extra_args: list[str] | None = None,
        env: dict | None = None,
    ) -> DispatchHandle:
        """Validate, apply env hygiene, spawn claude, return a DispatchHandle.

        Args:
            prompt: The prompt text.
            session_id: If provided, must be a valid UUID4 string; raises
                :class:`ValueError` before spawn if invalid.
            extra_args: Additional argv fragments appended after the prompt.
            env: Base environment dict; ``apply_env_hygiene`` is always applied
                before the child process is started.

        Raises:
            ValueError: If ``session_id`` is provided but is not a valid UUID4.
        """
        # UUID4 validation — must happen before subprocess.Popen.
        if session_id is not None:
            _validate_uuid4(session_id)  # raises ValueError on invalid

        # Build argv.
        argv = self._build_args(prompt, session_id=session_id)
        if extra_args:
            argv.extend(extra_args)

        # Apply env hygiene — never inherit parent CLAUDECODE.
        base = dict(env) if env is not None else {}
        clean_env, _cleared_vars = apply_env_hygiene(base)

        # Redact secrets for telemetry (argv untouched for actual spawn).
        args_redacted = _redact_args(argv)

        t_start = time.monotonic()

        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_env,
        )

        _fire_telemetry(
            "subprocess_spawn",
            {
                "command": _CLAUDE_BIN,
                "args_redacted": args_redacted,
                "pid": proc.pid,
            },
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

        run_id = self._run_id
        repo_root = self._repo_root

        # Collect all parsed events so _wait_fn can inspect the last one.
        _collected_events: list[dict] = []

        def _events_fn() -> Iterator[dict]:
            """Yield parsed stream-json frames from claude stdout."""
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    _collected_events.append(parsed)
                    yield parsed
                except json.JSONDecodeError:
                    print(
                        f"[subprocess_driver] WARNING: malformed JSONL line: {line!r}",
                        file=sys.stderr,
                    )

        def _wait_fn() -> DispatchResult:
            """Block until claude exits; emit telemetry; raise on error."""
            proc.wait()
            elapsed_ms = (time.monotonic() - t_start) * 1000.0

            exit_code = proc.returncode if proc.returncode is not None else -1

            # Determine is_error from last stream-json line, not exit code alone.
            is_error = _extract_is_error(_collected_events, exit_code)

            stderr_text = ""
            if proc.stderr is not None:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")

            _fire_telemetry(
                "subprocess_exit",
                {
                    "exit_code": exit_code,
                    "is_error": is_error,
                    "wall_ms": round(elapsed_ms, 1),
                },
                run_id=run_id,
                repo_root=repo_root,
            )

            if exit_code != 0:
                raise DriverExecutionError(
                    f"claude exited with code {exit_code}; is_error={is_error}. "
                    f"stderr: {stderr_text[:500]!r}"
                )

            return DispatchResult(
                exit_code=exit_code,
                is_error=is_error,
                stderr=stderr_text,
                wall_ms=elapsed_ms,
                stdout_events=list(_collected_events),
            )

        return DispatchHandle(
            _events_fn=_events_fn,
            _wait_fn=_wait_fn,
        )


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _validate_uuid4(value: str) -> None:
    """Raise ValueError if *value* is not a valid UUID4 string.

    Parses with ``uuid.UUID(value)`` (no version= kwarg — that would silently
    normalise the version bits rather than raising).  Then asserts that the
    parsed UUID's version attribute is exactly 4.

    Args:
        value: The string to validate.

    Raises:
        ValueError: If *value* is not a valid UUID or is not version 4.
    """
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(
            f"session_id must be a valid UUID4; got {value!r}"
        ) from exc
    if parsed.version != 4:
        raise ValueError(
            f"session_id must be a UUID4 (version 4); got version {parsed.version} in {value!r}"
        )


def _redact_args(argv: list[str]) -> list[str]:
    """Return a copy of *argv* with secret values replaced by ``"<redacted>"``.

    Redacts:
    - The value following a ``--api-key`` flag.
    - Combined args of the form ``ANTHROPIC_API_KEY=<value>``.
    - Any bare value that starts with ``sk-``.

    Args:
        argv: The original argument list.

    Returns:
        A new list; the original is not mutated.
    """
    result: list[str] = []
    redact_next = False
    for arg in argv:
        if redact_next:
            result.append("<redacted>")
            redact_next = False
            continue
        if arg in _REDACT_NEXT_AFTER:
            result.append(arg)
            redact_next = True
            continue
        if any(arg.startswith(prefix) for prefix in _SECRET_ARG_PREFIXES):
            key_part = arg.split("=", 1)[0]
            result.append(f"{key_part}=<redacted>")
            continue
        if any(arg.startswith(prefix) for prefix in _SECRET_VALUE_PREFIXES):
            result.append("<redacted>")
            continue
        result.append(arg)
    return result


def _extract_is_error(events: list[dict], exit_code: int) -> bool:
    """Determine whether the run was an error from stream-json events.

    Checks the last event's ``is_error`` field first (Invariant 3).  Falls
    back to ``exit_code != 0`` if no events were collected or no ``is_error``
    field is present.

    Args:
        events: All collected parsed event dicts, in order.
        exit_code: The process exit code.

    Returns:
        True if the run should be treated as an error.
    """
    if events:
        last = events[-1]
        if "is_error" in last:
            return bool(last["is_error"])
    return exit_code != 0


def _fire_telemetry(
    kind: str,
    payload: dict,
    *,
    run_id: str,
    repo_root: str,
) -> None:
    """Emit a telemetry event; swallow all failures.

    Telemetry is fire-and-forget: a failure here must never prevent the
    driver from returning a result or raising a meaningful error to its caller.
    """
    if _log_event is None:
        return
    try:
        _log_event(
            run_id=run_id,
            kind=kind,
            payload=payload,
            repo_root=repo_root,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(
            f"[subprocess_driver] WARNING: telemetry event '{kind}' failed: {exc}",
            file=sys.stderr,
        )
