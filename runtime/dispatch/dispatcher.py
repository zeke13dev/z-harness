"""
runtime.dispatch.dispatcher
============================

Core dispatcher that sits between callers and host drivers.

Design decisions applied here:

- **C1-D4** — The driver owns subprocess lifecycle and output-format parsing.
  The dispatcher iterates ``handle.events()`` and treats every yielded dict as
  opaque; it does not inspect or branch on event content.

- **SPEC Invariant #7** — ``dispatch_start`` and ``dispatch_end`` event
  payloads MUST NOT include any field derived from ``build_env()``'s output.
  The env dict is never logged.  Payload fields are exhaustively enumerated as
  ``{driver, command_id, session_id}`` for ``dispatch_start`` and
  ``{driver, command_id, wall_ms, exit_code, is_error}`` for ``dispatch_end``.

- **B3** — Args composition is the dispatcher's responsibility:
  ``final_args = provider_config["args_template"] + caller_args``.
  Drivers receive a ready-to-use flat argv and must not re-compose it.

Timeout strategy
----------------
Timeout is enforced in two phases:

(a) **Event-iteration phase** — a ``threading.Timer`` sets ``_timed_out_flag``
    after ``timeout_s`` seconds.  The ``handle.events()`` loop checks this flag
    after each yielded event and breaks early when set.  The timer is
    cancelled in a ``finally`` block before proceeding.

(b) **handle.wait() phase** — after the event loop completes, ``handle.wait()``
    is called on a daemon background thread.  The main thread joins that thread
    with the *remaining* timeout budget (``timeout_s - elapsed``).  If the
    join times out (i.e. ``wait_thread.is_alive()`` is True), ``timed_out``
    is set and the path proceeds identically to phase-a timeout: emit
    ``dispatch_end`` with ``exit_code=-1`` and raise ``DispatchTimeoutError``.
    The daemon thread may leak if the driver's ``handle.wait()`` hangs; this
    is acceptable because the process is already in a broken state and the
    driver's ``teardown()`` is responsible for subprocess cleanup.

JSONDecodeError handling during event iteration (added per T015 acceptance)
---------------------------------------------------------------------------
When ``handle.events()`` raises ``json.JSONDecodeError`` on a given iteration,
the dispatcher swallows that specific error, records it to an internal
``_stderr_parts`` buffer, and continues to the next iteration.  All other
exceptions from the iteration body still propagate via the existing
``_raised_non_timeout`` path.  After iteration completes, any recorded parse
errors are appended to ``result.stderr`` before returning.  This ensures that
a single malformed line in the stream does not abort collection of subsequent
valid events.
"""

from __future__ import annotations

import json
import threading
import time

from runtime.compat import log_event
from runtime.dispatch.driver import HostDriver
from runtime.dispatch.env import build_env
from runtime.dispatch.result import DispatchResult
from runtime.dispatch.timeout import DispatchTimeoutError


class Dispatcher:
    """Coordinates argument composition, env hygiene, event streaming, and
    telemetry bracketing for a single ``HostDriver.dispatch()`` call.

    Constructor
    -----------
    repo_root : str
        Absolute path to the z-harness repository root.  Forwarded to every
        ``log_event()`` call so ``compat.py`` can locate ``log-event.sh``.
    run_id : str
        The current run identifier.  Bound at construction time so all events
        from this dispatcher instance carry the same run identifier without
        callers having to thread it through every ``run()`` call.

    Usage::

        d = Dispatcher(repo_root="/path/to/repo", run_id="20260527T...")
        result = d.run(driver, "z-ask", ["--model", "haiku"], provider_config)
    """

    def __init__(self, repo_root: str, run_id: str) -> None:
        self._repo_root = repo_root
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        driver: HostDriver,
        command_id: str,
        caller_args: list[str],
        provider_config: dict,
        session_id: str | None = None,
        persona: str | None = None,
        model: str | None = None,
        runtime: str | None = None,
    ) -> DispatchResult:
        """Execute a command via *driver* and return the final result.

        Sequence
        --------
        1. Compose ``final_args = provider_config["args_template"] + caller_args``.
        2. Build subprocess env via :func:`~runtime.dispatch.env.build_env`.
        3. Emit ``dispatch_start`` event.
        4. Call ``driver.dispatch(command_id, final_args, env)`` → handle.
        5. Iterate ``handle.events()`` under a wall-clock timeout guard (phase a),
           collecting yielded dicts into ``stdout_events``.
        6. Call ``handle.wait()`` on a background thread, joining with the
           remaining timeout budget (phase b).
        7. Attach collected ``stdout_events`` to the returned ``DispatchResult``.
        8. Emit ``dispatch_end`` event.
        9. Call ``driver.teardown()``.
        10. Return the ``DispatchResult``.

        On timeout (either phase), ``dispatch_end`` is emitted with
        ``exit_code=-1, is_error=True`` and ``DispatchTimeoutError`` is
        re-raised after ``driver.teardown()`` is called.

        On non-timeout exception, ``dispatch_end`` is emitted with
        ``exit_code=-2, is_error=True`` before re-raising.

        Args:
            driver: An initialised :class:`~runtime.dispatch.driver.HostDriver`
                instance (``driver.init()`` must have been called before
                ``run()``).
            command_id: Kebab-case command identifier (e.g. ``"z-ask"``).
            caller_args: Caller-supplied arguments appended after
                ``provider_config["args_template"]``.
            provider_config: Provider configuration block.  Must contain
                ``"args_template"`` (list of str).  May contain
                ``"timeout_s"`` (int, default 300) and ``"auth_env"`` (str).
            session_id: Optional session identifier for resumable dispatches.
            persona: Optional persona name override.  When set, wins over any
                TOML binding; emits ``persona_override_used`` with
                ``override_field="persona"``.
            model: Optional model name override.  When set, wins over any
                TOML binding; emits ``persona_override_used`` with
                ``override_field="model"``.
            runtime: Optional runtime name override.  When set, wins over any
                TOML binding; emits ``persona_override_used`` with
                ``override_field="runtime"``.

        Returns:
            :class:`~runtime.dispatch.result.DispatchResult` from
            ``handle.wait()``, with ``stdout_events`` populated from the
            dispatcher's event iteration, or a synthetic timeout result if
            the timeout fires.

        Raises:
            :class:`~runtime.dispatch.timeout.DispatchTimeoutError`: When the
                dispatch exceeds ``provider_config.get("timeout_s", 300)``
                seconds.  Raised *after* ``dispatch_end`` is emitted and
                ``driver.teardown()`` is called.
        """
        driver_name = type(driver).__name__
        timeout_s: float = float(provider_config.get("timeout_s", 300))

        # 1. Compose final argv (B3).
        final_args: list[str] = list(provider_config["args_template"]) + list(caller_args)

        # 2. Build env (SPEC Invariant #7: never logged).
        env = build_env(provider_config)

        # 3. Emit dispatch_start (payload MUST NOT include env fields).
        t0 = time.monotonic()
        self._emit("dispatch_start", {
            "driver": driver_name,
            "command_id": command_id,
            "session_id": session_id,
        })

        # 3a. Resolve persona/model/runtime overrides and emit events.
        # Determine the original (provider_config-derived) values for each axis.
        _pc_persona: str | None = provider_config.get("persona")
        _pc_model: str | None = provider_config.get("model")
        _pc_runtime: str | None = provider_config.get("runtime")

        # Emit persona_override_used for each axis that was explicitly overridden.
        if persona is not None:
            self._emit("persona_override_used", {
                "command_id": command_id,
                "override_field": "persona",
                "value": persona,
                "original": _pc_persona,
            })
        if model is not None:
            self._emit("persona_override_used", {
                "command_id": command_id,
                "override_field": "model",
                "value": model,
                "original": _pc_model,
            })
        if runtime is not None:
            self._emit("persona_override_used", {
                "command_id": command_id,
                "override_field": "runtime",
                "value": runtime,
                "original": _pc_runtime,
            })

        # Build the resolved triple (explicit kwargs win over provider_config).
        _resolved_persona = persona if persona is not None else _pc_persona
        _resolved_model = model if model is not None else _pc_model
        _resolved_runtime = runtime if runtime is not None else _pc_runtime

        # Determine source per axis for telemetry.
        def _axis_source(override_val: str | None, pc_val: str | None) -> str:
            if override_val is not None:
                return "override"
            if pc_val is not None:
                return "provider_config"
            return "none"

        self._emit("persona_bound", {
            "command_id": command_id,
            "persona": _resolved_persona,
            "model": _resolved_model,
            "runtime": _resolved_runtime,
            "source": {
                "persona": _axis_source(persona, _pc_persona),
                "model": _axis_source(model, _pc_model),
                "runtime": _axis_source(runtime, _pc_runtime),
            },
        })

        self._emit("model_resolved", {
            "command_id": command_id,
            "model": _resolved_model,
            "runtime": _resolved_runtime,
            "source": _axis_source(model, _pc_model),
        })

        # 4. Call driver.dispatch.
        handle = driver.dispatch(command_id, final_args, env)

        # Phase (a): Iterate events under timer-flag timeout guard.
        stdout_events: list[dict] = []
        timed_out = False
        result: DispatchResult | None = None
        _stderr_parts: list[str] = []

        # The timer sets the flag; the events() loop checks after each yield.
        _timed_out_flag = threading.Event()

        def _on_timeout() -> None:
            _timed_out_flag.set()

        timer = threading.Timer(timeout_s, _on_timeout)
        timer.daemon = True
        timer.start()

        _raised_non_timeout: BaseException | None = None
        try:
            _events_iter = iter(handle.events())
            while True:
                if _timed_out_flag.is_set():
                    timed_out = True
                    break
                try:
                    event = next(_events_iter)
                except StopIteration:
                    break
                except json.JSONDecodeError as exc:
                    # Swallow parse errors for individual events so subsequent
                    # valid events can still be collected.  Record the error for
                    # diagnostic purposes via result.stderr.
                    _stderr_parts.append(f"JSONDecodeError: {exc}")
                    continue
                if _timed_out_flag.is_set():
                    timed_out = True
                    break
                stdout_events.append(event)

            # Check flag once more after iterator exhaustion.
            if _timed_out_flag.is_set():
                timed_out = True

            # Phase (b): Run handle.wait() on a background thread with the
            # remaining timeout budget so a hung wait() cannot block forever.
            if not timed_out:
                elapsed_s = time.monotonic() - t0
                remaining_s = max(0.0, timeout_s - elapsed_s)

                wait_result_box: list[DispatchResult | BaseException] = []

                def _do_wait() -> None:
                    try:
                        wait_result_box.append(handle.wait())
                    except BaseException as exc:
                        wait_result_box.append(exc)

                wait_thread = threading.Thread(target=_do_wait, daemon=True)
                wait_thread.start()
                wait_thread.join(timeout=remaining_s)

                if wait_thread.is_alive():
                    # handle.wait() did not return within the remaining budget.
                    # The daemon thread may leak — driver.teardown() is
                    # responsible for cleaning up the underlying subprocess.
                    timed_out = True
                else:
                    val = wait_result_box[0]
                    if isinstance(val, BaseException):
                        _raised_non_timeout = val
                    else:
                        result = val

        except BaseException as exc:
            # Preserve any non-timeout exception raised during events()
            # iteration so it can be re-raised after teardown.
            if not _timed_out_flag.is_set():
                _raised_non_timeout = exc
            else:
                timed_out = True
        finally:
            timer.cancel()

        # Compute wall_ms before any branching so it's available in all paths.
        wall_ms = (time.monotonic() - t0) * 1000.0

        if _raised_non_timeout is not None:
            # Emit dispatch_end before re-raising. exit_code=-2 distinguishes
            # "exception during dispatch" from "timeout" (exit_code=-1).
            self._emit("dispatch_end", {
                "driver": driver_name,
                "command_id": command_id,
                "wall_ms": wall_ms,
                "exit_code": -2,
                "is_error": True,
            })
            driver.teardown()
            raise _raised_non_timeout

        if timed_out:
            # Emit dispatch_end with synthetic timeout values.
            self._emit("dispatch_end", {
                "driver": driver_name,
                "command_id": command_id,
                "wall_ms": wall_ms,
                "exit_code": -1,
                "is_error": True,
            })
            driver.teardown()
            timeout_error = DispatchTimeoutError(timeout_s=timeout_s, pid=-1)
            raise timeout_error

        # Success path.
        assert result is not None

        # Attach the dispatcher's collected events (canonical source since the
        # dispatcher is the entity that iterated handle.events()).
        result.stdout_events = stdout_events

        # Append any parse errors collected during streaming to result.stderr.
        if _stderr_parts:
            parse_errors = "\n".join(_stderr_parts)
            result.stderr = (result.stderr + "\n" + parse_errors).lstrip("\n")

        # 8. Emit dispatch_end.
        self._emit("dispatch_end", {
            "driver": driver_name,
            "command_id": command_id,
            "wall_ms": wall_ms,
            "exit_code": result.exit_code,
            "is_error": result.is_error,
        })

        # 9. Teardown.
        driver.teardown()

        # 10. Return result.
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, kind: str, payload: dict) -> None:
        """Emit a structured event via ``runtime.compat.log_event``.

        The payload is passed as-is; ``compat.py`` injects ``schema_version``.
        This method intentionally has no fallback: a broken log path is a
        real problem that should surface immediately during development.
        """
        log_event(
            run_id=self._run_id,
            kind=kind,
            payload=payload,
            repo_root=self._repo_root,
        )
