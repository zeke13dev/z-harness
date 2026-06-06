"""
runtime/drivers/antigravity/host_driver_shim.py — HostDriver-conforming wrapper for AntigravityDriver.

AntigravityDriver exposes ``dispatch(prompt: str) -> Iterator[dict]`` — a bare,
synchronous, iterator-based API that does not match the ``HostDriver`` contract
(``dispatch(command_id, args, env) -> DispatchHandle``).  This shim bridges the
two shapes so the dispatcher and ``select_driver("antigravity")`` can treat the
agy backend identically to any other HostDriver.

Bridging decisions
------------------
- **prompt construction** — ``args`` from the dispatcher is already a flat argv
  list (``provider_config["args_template"] + caller_args``).  The shim joins
  the list with a single space to form the prompt string.  This is "good enough"
  for a CLI forwarder; callers that need structured prompts should compose them
  before dispatch.
- **sync iterator -> DispatchHandle** — ``AntigravityDriver.dispatch()`` is a
  synchronous generator.  ``_events_fn`` captures the generator and yields from
  it; ``_wait_fn`` is called after the generator is exhausted and constructs a
  ``DispatchResult`` from the collected outcome.  Both closures share mutable
  state via a ``_outcome`` box so errors raised inside the generator are visible
  to ``_wait_fn``.
- **env passthrough** — The shim does not forward ``env`` to the agy subprocess.
  AntigravityDriver uses ``subprocess.Popen`` without an explicit ``env``
  argument, so it inherits the current process environment.  Callers that need
  env overrides should set them on the process environment before calling this
  driver.  This limitation is documented so it is visible at 3 am.

Public surface
--------------
AntigravityHostDriverShim
    A HostDriver subclass.  Wire it in via ``select_driver("antigravity")``.

    init(provider_config, context=None)
        Stores provider config; reads ``run_id`` and ``repo_root`` from context.

    dispatch(command_id, args, env) -> DispatchHandle
        Joins ``args`` into a prompt string, delegates to
        ``AntigravityDriver.dispatch(prompt)``, and wraps the result in a
        ``DispatchHandle`` whose ``events()`` yields the iterator dicts and
        whose ``wait()`` returns a ``DispatchResult``.

    teardown()
        No-op; AntigravityDriver holds no persistent resources.
"""

from __future__ import annotations

import os
import time
from typing import Iterator

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult
from runtime.drivers.antigravity.driver import (
    AntigravityDriver,
    DriverConstraintError,
    DriverDispatchError,
)
from runtime.drivers.antigravity.preflight import DriverUnavailableError


class AntigravityHostDriverShim(HostDriver):
    """HostDriver-conforming wrapper around AntigravityDriver.

    Bridges the ``dispatch(prompt) -> Iterator[dict]`` surface of
    AntigravityDriver to the ``dispatch(command_id, args, env) -> DispatchHandle``
    contract required by the z-harness dispatcher.

    Prompt construction
    -------------------
    The ``args`` list passed by the dispatcher is joined with a single space
    to form the agy prompt.  An empty args list produces an empty string prompt,
    which agy will reject -- callers are expected to pass at least one argument.

    Env note
    --------
    The ``env`` dict is not forwarded to the agy subprocess.  AntigravityDriver
    uses ``subprocess.Popen`` without an explicit ``env`` argument, so it inherits
    the current process environment.  Callers that need env overrides should set
    them on the process environment before calling this driver.  See module
    docstring for the rationale.
    """

    def __init__(self) -> None:
        self._provider_config: dict = {}
        self._run_id: str = "agy-shim"
        self._repo_root: str = os.getcwd()

    # ------------------------------------------------------------------
    # HostDriver interface
    # ------------------------------------------------------------------

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Store provider config; extract run_id and repo_root from context.

        Args:
            provider_config: The provider block from providers.json.
            context: Optional runtime injections.  Recognised keys:
                - ``"run_id"`` (str) -- forwarded to AntigravityDriver and telemetry.
                - ``"repo_root"`` (str) -- forwarded to AntigravityDriver and telemetry.
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
        """Join args into a prompt and delegate to AntigravityDriver.dispatch().

        Args:
            command_id: Ignored; present for interface compatibility.
            args: Flat argv from the dispatcher.  Joined with spaces to form
                the agy prompt.
            env: Not forwarded to agy subprocess (see class docstring).

        Returns:
            A DispatchHandle whose events() yields dicts from the agy stream
            and whose wait() returns a DispatchResult.

        Raises:
            DriverUnavailableError: If agy is not installed (raised synchronously
                from within events() iteration via the preflight check in
                AntigravityDriver.dispatch()).
        """
        prompt = " ".join(args)

        driver = AntigravityDriver(
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

        t_start = time.monotonic()

        # Mutable outcome box shared between _events_fn and _wait_fn.
        # Using a list as a single-element container so the closures can write to it.
        _outcome: list[dict] = []  # will hold one dict: {"ok": True} or {"error": exc}

        def _events_fn() -> Iterator[dict]:
            """Iterate AntigravityDriver.dispatch() and yield each event dict.

            Captures any exception into _outcome so _wait_fn can reflect it in
            the DispatchResult.  On clean completion, records {"ok": True}.

            Exceptions from AntigravityDriver.dispatch() (DriverUnavailableError,
            DriverConstraintError, DriverDispatchError) propagate to the caller
            as-is so the dispatcher receives actionable errors, not wrapped ones.
            """
            try:
                for event in driver.dispatch(prompt):
                    yield event
                _outcome.append({"ok": True})
            except (DriverUnavailableError, DriverConstraintError, DriverDispatchError) as exc:
                _outcome.append({"error": exc})
                raise

        def _wait_fn() -> DispatchResult:
            """Construct a DispatchResult based on the events iterator outcome.

            If _outcome is empty (caller called wait() before exhausting events()),
            we treat the dispatch as incomplete with exit_code=-1.
            """
            elapsed_ms = (time.monotonic() - t_start) * 1000.0

            if not _outcome:
                # wait() was called before events() was exhausted -- treat as error.
                return DispatchResult(
                    exit_code=-1,
                    is_error=True,
                    stderr="wait() called before events() iterator was exhausted",
                    wall_ms=elapsed_ms,
                )

            outcome = _outcome[0]
            if outcome.get("ok"):
                return DispatchResult(
                    exit_code=0,
                    is_error=False,
                    wall_ms=elapsed_ms,
                )

            exc = outcome.get("error")
            error_msg = str(exc) if exc is not None else "unknown error"
            return DispatchResult(
                exit_code=1,
                is_error=True,
                stderr=error_msg,
                wall_ms=elapsed_ms,
            )

        return DispatchHandle(
            _events_fn=_events_fn,
            _wait_fn=_wait_fn,
        )

    def teardown(self) -> None:
        """No-op; AntigravityDriver holds no persistent resources between dispatches."""
