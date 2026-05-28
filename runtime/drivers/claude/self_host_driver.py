"""
runtime/drivers/claude/self_host_driver.py — In-process HostDriver for Claude Code.

When z-harness runs inside Claude Code (as a plugin), the host IS the current
process.  Rather than spawning a subprocess, SelfHostDriver delegates command
execution to in-process tool primitives (Read, Edit, Bash, Agent).

SelfHostDriver MUST only be instantiated when ``CLAUDECODE`` is non-empty in
the environment (i.e. ``detect_self_hosted()`` returns True), OR when the
caller explicitly passes ``force=True`` to ``__init__`` to override detection.
Attempting to instantiate without the env signal and without ``force=True``
raises :class:`DriverInitError`.

Telemetry events emitted
------------------------
- ``driver_selected`` — on ``init()``, with
  ``driver_class="SelfHostDriver"``,
  ``host="claude-self"``,
  ``detection_method="env"`` or ``"explicit"``.

No subprocess is spawned under any code path in this class.
"""

from __future__ import annotations

import sys
from typing import Iterator

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult
from runtime.drivers.claude.env_hygiene import detect_self_hosted

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class DriverInitError(Exception):
    """Raised when SelfHostDriver is instantiated outside a Claude Code session.

    This exception is raised from ``__init__`` if ``detect_self_hosted()``
    returns False and ``force=True`` was not passed.

    Callers that intentionally want to use SelfHostDriver outside Claude Code
    (e.g. in tests) should pass ``force=True`` to suppress the check.
    """


# ---------------------------------------------------------------------------
# SelfHostDriver
# ---------------------------------------------------------------------------


class SelfHostDriver(HostDriver):
    """In-process HostDriver that delegates to Claude Code tool primitives.

    This driver is structurally different from all other z-harness drivers
    because it does NOT spawn a subprocess.  Instead it delegates to the
    tool primitives available in the host Claude Code process (Read, Edit,
    Bash, Agent).  The ``dispatch()`` method skeleton is in place; the
    actual tool-primitive layer raises ``NotImplementedError`` pending the
    C1 interface definition.

    Instantiation guard
    -------------------
    ``__init__`` checks ``detect_self_hosted()`` and raises
    :class:`DriverInitError` unless the env signal is present or
    ``force=True`` is passed.

    Parameters
    ----------
    force:
        Skip the ``detect_self_hosted()`` check.  Use only in tests or
        when the caller has already verified the host environment by other
        means.
    """

    def __init__(self, *, force: bool = False) -> None:
        if not force and not detect_self_hosted():
            raise DriverInitError(
                "SelfHostDriver requires CLAUDECODE to be set in the environment. "
                "Pass force=True to override this check (tests / explicit use only)."
            )

        # Record how we determined we are self-hosted for telemetry.
        self._detection_method: str = "explicit" if force else "env"

        # Runtime state set in init(); None until then.
        self._run_id: str | None = None
        self._repo_root: str | None = None
        self._tools_registry: dict | None = None

    # ------------------------------------------------------------------
    # HostDriver ABC — init
    # ------------------------------------------------------------------

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Initialise the driver with provider configuration.

        Stores runtime injections from ``context`` and emits the
        ``driver_selected`` telemetry event.

        Parameters
        ----------
        provider_config:
            Provider block from ``.z-harness/providers.json``.  This driver
            does not require any specific keys; unknown keys are ignored.
        context:
            Optional dict for runtime injections.  Recognised keys:

            - ``"run_id"`` — z-harness run identifier for telemetry.
            - ``"repo_root"`` — absolute path to the repo root.
            - ``"tools_registry"`` — live tool registry from the host process
              (C1-D5 context injection).

            Unknown keys are silently ignored (Liskov substitutability).
        """
        ctx = context or {}
        self._run_id = ctx.get("run_id") or "self-host-driver"
        self._repo_root = ctx.get("repo_root") or ""
        self._tools_registry = ctx.get("tools_registry")

        self._fire_telemetry(
            "driver_selected",
            {
                "driver_class": "SelfHostDriver",
                "host": "claude-self",
                "detection_method": self._detection_method,
            },
        )

    # ------------------------------------------------------------------
    # HostDriver ABC — dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        command_id: str,
        args: list[str],
        env: dict,
    ) -> DispatchHandle:
        """Dispatch a command via in-process tool primitives.

        The tool-primitive layer is not yet implemented (pending C1 interface
        definition); ``events()`` on the returned handle raises
        ``NotImplementedError``.  The dispatch skeleton — routing, handle
        construction — is in place so downstream work can build on it.

        No subprocess is spawned.

        Parameters
        ----------
        command_id:
            Kebab-case command identifier (e.g. ``"z-ask"``).
        args:
            Final flat argv as composed by the dispatcher.  Passed to the
            tool-primitive layer as metadata; not used to construct an argv
            for any subprocess.
        env:
            Full environment mapping prepared by ``runtime.dispatch.env``.
            Available to tool primitives for context injection.

        Returns
        -------
        DispatchHandle
            Handle whose ``events()`` raises ``NotImplementedError`` (tool
            primitives not yet wired) and whose ``wait()`` returns a
            placeholder ``DispatchResult``.
        """
        # Capture locals for closures; avoids late-binding surprises.
        _command_id = command_id
        _args = list(args)
        _env = dict(env)

        def _events_fn() -> Iterator[dict]:
            raise NotImplementedError(
                "SelfHostDriver tool-primitive layer is not yet implemented. "
                "Pending C1 interface definition for in-process Read/Edit/Bash/Agent."
            )
            yield  # pragma: no cover — make mypy / type checkers see Iterator type

        def _wait_fn() -> DispatchResult:
            # Placeholder result; replaced once tool primitives are wired.
            return DispatchResult(
                exit_code=1,
                is_error=True,
                stderr=(
                    "SelfHostDriver.dispatch(): tool-primitive layer not implemented. "
                    f"command_id={_command_id!r}"
                ),
            )

        return DispatchHandle(
            _events_fn=_events_fn,
            _wait_fn=_wait_fn,
        )

    # ------------------------------------------------------------------
    # HostDriver ABC — teardown (no-op; no resources to release)
    # ------------------------------------------------------------------

    def teardown(self) -> None:
        """No-op teardown — SelfHostDriver holds no persistent resources."""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fire_telemetry(self, kind: str, payload: dict) -> None:
        """Emit a telemetry event; fire-and-forget, never raises."""
        if _log_event is None:
            return
        try:
            _log_event(
                run_id=self._run_id or "self-host-driver",
                kind=kind,
                payload=payload,
                repo_root=self._repo_root or "",
            )
        except (FileNotFoundError, RuntimeError, OSError) as exc:
            print(
                f"[self_host_driver] WARNING: telemetry event '{kind}' failed: {exc}",
                file=sys.stderr,
            )
