"""
runtime/drivers/cursor/cli_driver.py — HostDriver implementation for the Cursor CLI tier.

Invokes ``cursor-agent -p`` with ``--output-format stream-json``.  Auth is read
from the ``CURSOR_API_KEY`` environment variable; the binary is probed on PATH at
init time.

Telemetry events emitted
------------------------
- ``driver_selected``     — on init, with host="cursor", tier="cli"
- ``subprocess_spawn``    — on each subprocess launch (args_redacted, pid)
- ``subprocess_exit``     — on subprocess exit (exit_code, is_error, wall_ms)

All events are fire-and-forget: telemetry failure is logged to stderr but
never prevents the driver from returning a result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Iterator

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class DriverConfigError(Exception):
    """Raised when required configuration (e.g. CURSOR_API_KEY) is absent."""


class DriverInitError(Exception):
    """Raised when the required binary (cursor-agent) is not found on PATH."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The cursor-agent binary name to look for on PATH.
_CURSOR_AGENT_BIN: str = "cursor-agent"

#: Output format flag passed to cursor-agent.
_OUTPUT_FORMAT_FLAG: list[str] = ["--output-format", "stream-json"]

#: Map of z-harness command modes to cursor-agent --mode values.
_MODE_MAP: dict[str, str] = {
    "ask": "ask",
    "plan": "plan",
    "agent": "agent",
}

#: Default mode when none is provided or when the mode is unrecognised.
_DEFAULT_MODE: str = "ask"


# ---------------------------------------------------------------------------
# CursorCLIDriver
# ---------------------------------------------------------------------------


class CursorCLIDriver(HostDriver):
    """HostDriver that invokes the ``cursor-agent -p`` CLI as a subprocess.

    Lifecycle
    ---------
    1. Caller calls ``driver.init(provider_config)`` once.
    2. For each prompt, caller calls ``driver.dispatch(command_id, args, env)``
       which launches ``cursor-agent -p`` and returns a ``DispatchHandle``.
    3. Caller iterates ``handle.events()`` to consume stream-json frames.
    4. Caller calls ``handle.wait()`` to collect the ``DispatchResult``.
    5. Caller calls ``driver.teardown()`` (no-op for this driver).

    Auth
    ----
    Reads ``CURSOR_API_KEY`` from the environment at ``init()`` time.
    Raises :class:`DriverConfigError` if the variable is absent or empty.

    Binary
    ------
    Probes for ``cursor-agent`` on PATH at ``init()`` time.
    Raises :class:`DriverInitError` if the binary is not found.
    """

    def __init__(self) -> None:
        self._provider_config: dict = {}
        self._run_id: str = "cursor-driver"
        self._repo_root: str = os.getcwd()
        self._cursor_agent_path: str = ""

    # ------------------------------------------------------------------
    # HostDriver interface
    # ------------------------------------------------------------------

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Initialise the driver: validate auth and probe for the binary.

        Args:
            provider_config: The provider block from providers.json.
            context: Optional runtime injections.  Recognised keys:
                - ``"run_id"`` (str) — forwarded to telemetry calls.
                - ``"repo_root"`` (str) — forwarded to telemetry calls.
                Unknown keys are silently ignored per C1-D5.

        Raises:
            DriverConfigError: If CURSOR_API_KEY is not set in the environment.
            DriverInitError: If cursor-agent is not found on PATH.
        """
        self._provider_config = provider_config
        ctx = context or {}
        if "run_id" in ctx:
            self._run_id = str(ctx["run_id"])
        if "repo_root" in ctx:
            self._repo_root = str(ctx["repo_root"])

        # Validate auth — raises DriverConfigError if missing.
        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not api_key:
            raise DriverConfigError(
                "CURSOR_API_KEY environment variable is not set or is empty. "
                "Set CURSOR_API_KEY to authenticate with the Cursor API."
            )

        # Probe for the cursor-agent binary.
        found = shutil.which(_CURSOR_AGENT_BIN)
        if found is None:
            raise DriverInitError(
                f"'{_CURSOR_AGENT_BIN}' binary not found on PATH. "
                "Ensure cursor-agent is installed and available on PATH."
            )
        self._cursor_agent_path = found

        _fire_telemetry(
            "driver_selected",
            {
                "driver_class": "CursorCLIDriver",
                "host": "cursor",
                "tier": "cli",
                "detection_method": "env",
            },
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

    def dispatch(
        self,
        command_id: str,
        args: list[str],
        env: dict,
    ) -> DispatchHandle:
        """Launch ``cursor-agent -p`` and return a streaming handle.

        Args:
            command_id: The command identifier (e.g. ``"z-ask"``).  Used to
                determine the ``--mode`` flag via :meth:`_build_args`.
            args: Additional args from the dispatcher; appended after the base
                cursor-agent argv.
            env: Full subprocess environment from the dispatcher.

        Returns:
            A ``DispatchHandle`` backed by the live subprocess.
        """
        # Inject CURSOR_API_KEY into the subprocess env.
        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        proc_env = dict(env)
        proc_env["CURSOR_API_KEY"] = api_key

        # Determine mode from command_id (e.g. "z-ask" → "ask").
        mode_hint = command_id.lstrip("z-") if command_id.startswith("z-") else command_id
        mode_flag = self._build_args(mode_hint)

        argv = [self._cursor_agent_path, "-p"] + mode_flag + _OUTPUT_FORMAT_FLAG + args

        # Redact args for telemetry (strip any API key values).
        args_redacted = [
            "<redacted>" if "key" in a.lower() or "token" in a.lower() else a
            for a in argv
        ]

        t_start = time.monotonic()

        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
        )

        _fire_telemetry(
            "subprocess_spawn",
            {
                "command": _CURSOR_AGENT_BIN,
                "args_redacted": args_redacted,
                "pid": proc.pid,
            },
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

        run_id = self._run_id
        repo_root = self._repo_root

        def _events_fn() -> Iterator[dict]:
            """Yield parsed stream-json frames from cursor-agent stdout."""
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                import json as _json
                try:
                    yield _json.loads(line)
                except _json.JSONDecodeError:
                    print(
                        f"[cursor_driver] WARNING: malformed JSONL line: {line!r}",
                        file=sys.stderr,
                    )

        def _wait_fn() -> DispatchResult:
            """Block until cursor-agent exits; collect result and emit telemetry."""
            proc.wait()
            elapsed_ms = (time.monotonic() - t_start) * 1000.0

            exit_code = proc.returncode if proc.returncode is not None else -1
            is_error = exit_code != 0

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

            return DispatchResult(
                exit_code=exit_code,
                is_error=is_error,
                stderr=stderr_text,
                wall_ms=elapsed_ms,
            )

        return DispatchHandle(
            _events_fn=_events_fn,
            _wait_fn=_wait_fn,
        )

    def teardown(self) -> None:
        """No-op; CursorCLIDriver holds no persistent resources between dispatches."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_args(mode: str) -> list[str]:
        """Map a z-harness command mode to ``--mode <value>`` argv fragment.

        Args:
            mode: One of ``"ask"``, ``"plan"``, or ``"agent"``.  Any
                unrecognised value falls back to ``"ask"``.

        Returns:
            A two-element list ``["--mode", "<value>"]``.
        """
        cursor_mode = _MODE_MAP.get(mode, _DEFAULT_MODE)
        return ["--mode", cursor_mode]


# ---------------------------------------------------------------------------
# Module-private telemetry helper
# ---------------------------------------------------------------------------


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
            f"[cursor_driver] WARNING: telemetry event '{kind}' failed: {exc}",
            file=sys.stderr,
        )
