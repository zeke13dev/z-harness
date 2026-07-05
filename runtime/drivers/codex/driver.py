"""
runtime/drivers/codex/driver.py — HostDriver implementation for the Codex CLI.

Invokes ``codex exec --json -``, piping the prompt to stdin.  Auth env
additions from ``auth.resolve_auth()`` are injected
into the subprocess environment; ANTHROPIC_API_KEY and CLAUDE_API_KEY are
explicitly stripped from the env unless the provider config opts in via
``allow_cross_vendor_env: true``.

Timeout field naming note
-------------------------
The C1 canonical provider schema (runtime/contract/provider.schema.json) names
the timeout field ``timeout_s``.  The C2 SPEC draft referred to it as
``session_timeout_s`` — that name is drift and has been corrected here.
This driver reads ``provider_config.get("timeout_s")`` as the canonical key.
``session_timeout_s`` is not read; do not add it to the schema.

Telemetry events emitted
------------------------
- ``codex_driver_invoke``   — on each subprocess launch
- ``codex_driver_complete`` — on clean exit (exit_code == 0)
- ``codex_driver_error``    — on any error path (exit_code != 0 or timeout)
- ``codex_env_collision_detected`` — informational, when ANTHROPIC_API_KEY and
  OPENAI_API_KEY are both present in the base env (before stripping)

All events are fire-and-forget: telemetry failure is logged to stderr but
never prevents the driver from returning a result.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import Iterator, Optional

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult
from runtime.drivers.codex.auth import AuthResolutionError, resolve_auth
from runtime.drivers.codex.stream import EVENT_FAMILY_UNKNOWN, parse_stream

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Environment variables always stripped from the codex subprocess env unless
#: the provider config explicitly opts in via ``allow_cross_vendor_env: true``.
_CROSS_VENDOR_KEYS: tuple[str, ...] = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")

#: Codex CLI invocation prefix; prompt arrives on stdin.
_CODEX_CMD: list[str] = ["codex", "exec", "--json", "-"]

#: Default timeout in seconds when provider_config does not specify one.
_DEFAULT_TIMEOUT_S: int = 120


# ---------------------------------------------------------------------------
# CodexDriver
# ---------------------------------------------------------------------------


class CodexDriver(HostDriver):
    """HostDriver that invokes the Codex CLI as a subprocess.

    Lifecycle
    ---------
    1. Caller calls ``driver.init(provider_config)`` once.
    2. For each prompt, caller calls ``driver.dispatch(command_id, args, env)``
        which launches ``codex exec --json -`` and returns a ``DispatchHandle``.
    3. Caller iterates ``handle.events()`` to consume Codex JSONL frames.
    4. Caller calls ``handle.wait()`` to collect the ``DispatchResult``.
    5. Caller calls ``driver.teardown()`` (no-op for this driver).

    Subprocess environment
    ----------------------
    - Parent environment is passed through (via the ``env`` argument from the
      dispatcher, which already went through ``runtime.dispatch.env.build_env``).
    - Auth env additions from ``resolve_auth()`` are merged in.
    - ANTHROPIC_API_KEY and CLAUDE_API_KEY are stripped unless
      ``provider_config["allow_cross_vendor_env"] is True``.

    Timeout
    -------
    Reads ``provider_config["timeout_s"]`` (C1 canonical field name).
    On timeout the subprocess is ``kill()``-ed and ``wait()``-ed to avoid
    zombie processes.  The resulting ``DispatchResult`` carries exit_code=-1
    and ``is_error=True``.
    """

    def __init__(self) -> None:
        self._provider_config: dict = {}
        self._run_id: str = "codex-driver"
        self._repo_root: str = os.getcwd()

    # ------------------------------------------------------------------
    # HostDriver interface
    # ------------------------------------------------------------------

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Store provider config; validate relevant fields.

        Args:
            provider_config: The provider block from providers.json.
                Must contain at minimum the fields required by the C1 schema
                (``kind``, ``command``, ``args_template``, ``stdin``,
                ``timeout_s``, ``model_label``).
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
        """Launch ``codex exec --json -`` and return a streaming handle.

        CodexDriver always uses ``_CODEX_CMD`` as the subprocess argv.  The
        dispatcher's ``args`` list is still used to build stdin: when it starts
        with ``provider_config["args_template"]``, that prefix is stripped and
        the remaining tokens are joined into the prompt.  The ``env`` argument
        from the dispatcher is used as the starting environment (already
        processed by ``runtime.dispatch.env.build_env``); this method merges
        auth env additions and strips cross-vendor keys on top of it.

        Args:
            command_id: Ignored; present for interface compatibility.
            args: Dispatcher-composed argv; used only to derive stdin prompt.
            env: Starting subprocess environment from the dispatcher.

        Returns:
            A ``DispatchHandle`` backed by the live subprocess.

        Raises:
            ``AuthResolutionError`` if no Codex credential can be found.
            ``OSError`` if the codex binary cannot be launched.
        """
        auth_result = resolve_auth(
            self._provider_config,
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

        proc_env = _build_proc_env(
            base_env=env,
            auth_additions=auth_result.env_additions,
            provider_config=self._provider_config,
            run_id=self._run_id,
            repo_root=self._repo_root,
        )

        timeout_s: int = self._provider_config.get("timeout_s", _DEFAULT_TIMEOUT_S)
        provider_name: str = self._provider_config.get("name", "codex")
        model_label: str = self._provider_config.get("model_label", "unknown")

        try:
            _fire_telemetry(
                "codex_driver_invoke",
                {
                    "provider_name": provider_name,
                    "auth_strategy": auth_result.strategy,
                    "model_label": model_label,
                },
                run_id=self._run_id,
                repo_root=self._repo_root,
            )
        except Exception as exc:  # noqa: BLE001 — telemetry must never block dispatch
            print(
                f"[codex_driver] WARNING: codex_driver_invoke telemetry failed: {exc}",
                file=sys.stderr,
            )

        t_start = time.monotonic()

        proc = subprocess.Popen(
            _CODEX_CMD,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=proc_env,
        )
        _write_prompt_to_stdin(
            proc,
            _prompt_from_dispatch_args(args, self._provider_config),
        )

        # Capture telemetry state for the closures below.
        run_id = self._run_id
        repo_root = self._repo_root
        stream_stats = {
            "frames_parsed": 0,
            "frames_by_family": {},
        }
        stream_stats_lock = threading.Lock()

        def _events_fn() -> Iterator[dict]:
            """Yield parsed JSONL frames from codex stdout as dicts.

            Delegates to ``parse_stream()`` (runtime.drivers.codex.stream) for
            all JSONL parsing, timeout detection, and error-frame handling.
            Each ``Frame`` yielded by ``parse_stream`` is mapped back to its
            original ``raw`` dict so that the dispatcher receives plain dicts
            (as required by the C1 DispatchHandle.events() contract) without
            losing any fields the Codex CLI emits.

            Typed exceptions from ``parse_stream`` (CodexExecutionError,
            CodexTimeoutError, CodexCrashError) propagate to the dispatcher
            unchanged — drivers must not swallow I/O errors per C1 contract.
            """
            for frame in parse_stream(
                proc,
                run_id=run_id,
                repo_root=repo_root,
            ):
                event_family = frame.event_family or EVENT_FAMILY_UNKNOWN
                with stream_stats_lock:
                    stream_stats["frames_parsed"] += 1
                    frames_by_family = stream_stats["frames_by_family"]
                    frames_by_family[event_family] = (
                        frames_by_family.get(event_family, 0) + 1
                    )
                yield frame.raw

        def _wait_fn() -> DispatchResult:
            """Block until codex exits; enforce timeout; collect result."""
            elapsed_ms = (time.monotonic() - t_start) * 1000.0
            timed_out = False

            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()
                proc.wait()

            exit_code = proc.returncode if proc.returncode is not None else -1
            is_error = exit_code != 0 or timed_out

            stderr_text = ""
            if proc.stderr is not None:
                stderr_text = proc.stderr.read().decode("utf-8", errors="replace")

            elapsed_ms = (time.monotonic() - t_start) * 1000.0

            if is_error:
                error_kind = "timeout" if timed_out else "non_zero_exit"
                try:
                    _fire_telemetry(
                        "codex_driver_error",
                        {
                            "error_kind": error_kind,
                            "exit_code": exit_code,
                            "elapsed_ms": round(elapsed_ms, 1),
                        },
                        run_id=run_id,
                        repo_root=repo_root,
                    )
                except Exception as exc:  # noqa: BLE001 — telemetry must never block result
                    print(
                        f"[codex_driver] WARNING: codex_driver_error telemetry failed: {exc}",
                        file=sys.stderr,
                    )
            else:
                with stream_stats_lock:
                    frames_parsed = stream_stats["frames_parsed"]
                    frames_by_family = dict(stream_stats["frames_by_family"])
                try:
                    _fire_telemetry(
                        "codex_driver_complete",
                        {
                            "exit_code": exit_code,
                            "frames_parsed": frames_parsed,
                            "frames_by_family": frames_by_family,
                            "elapsed_ms": round(elapsed_ms, 1),
                        },
                        run_id=run_id,
                        repo_root=repo_root,
                    )
                except Exception as exc:  # noqa: BLE001 — telemetry must never block result
                    print(
                        f"[codex_driver] WARNING: codex_driver_complete telemetry failed: {exc}",
                        file=sys.stderr,
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
        """No-op; CodexDriver holds no persistent resources between dispatches."""


# ---------------------------------------------------------------------------
# Module-private helpers
# ---------------------------------------------------------------------------


def _build_proc_env(
    base_env: dict,
    auth_additions: dict[str, str],
    provider_config: dict,
    run_id: str = "codex-driver",
    repo_root: str = "",
) -> dict:
    """Build the subprocess environment for a codex invocation.

    Merges ``base_env`` with ``auth_additions``, then strips
    ``_CROSS_VENDOR_KEYS`` unless the provider config opts in.

    Fires ``codex_env_collision_detected`` (informational) when both
    ANTHROPIC_API_KEY and OPENAI_API_KEY are present in ``base_env`` before
    any stripping occurs.  This detection step does not alter the stripping
    behaviour.

    Args:
        base_env: Starting environment (already processed by dispatch.env).
        auth_additions: Variables from ``AuthResult.env_additions``.
        provider_config: Provider config dict; checked for
            ``allow_cross_vendor_env: true`` opt-in.
        run_id: Forwarded to telemetry; defaults to "codex-driver".
        repo_root: Forwarded to telemetry; defaults to "".

    Returns:
        New environment dict; ``base_env`` is not mutated.
    """
    # Collision detection: check BEFORE merging auth_additions or stripping.
    if "ANTHROPIC_API_KEY" in base_env and "OPENAI_API_KEY" in base_env:
        try:
            _fire_telemetry(
                "codex_env_collision_detected",
                {"colliding_keys": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]},
                run_id=run_id,
                repo_root=repo_root,
            )
        except Exception as exc:  # noqa: BLE001 — telemetry must never block env build
            print(
                f"[codex_driver] WARNING: codex_env_collision_detected telemetry failed: {exc}",
                file=sys.stderr,
            )

    env = dict(base_env)
    env.update(auth_additions)

    allow_cross_vendor: bool = bool(
        provider_config.get("allow_cross_vendor_env", False)
    )
    if not allow_cross_vendor:
        for key in _CROSS_VENDOR_KEYS:
            env.pop(key, None)

    return env


def _prompt_from_dispatch_args(args: list[str], provider_config: dict) -> str:
    """Return the prompt portion of a dispatcher-composed argv list."""
    prompt_args = list(args)
    args_template = provider_config.get("args_template")
    if isinstance(args_template, list):
        prefix = [str(part) for part in args_template]
        if prompt_args[: len(prefix)] == prefix:
            prompt_args = prompt_args[len(prefix) :]
    return " ".join(str(part) for part in prompt_args)


def _write_prompt_to_stdin(proc: subprocess.Popen, prompt: str) -> None:
    """Send the prompt to ``codex exec --json -`` and close stdin."""
    if proc.stdin is None:
        return

    try:
        if prompt:
            payload = prompt if prompt.endswith("\n") else f"{prompt}\n"
            proc.stdin.write(payload.encode("utf-8"))
        proc.stdin.close()
    except BrokenPipeError:
        # The process may exit before reading stdin, for example on immediate
        # CLI validation failure. wait() will report the subprocess status.
        pass


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
    except Exception as exc:  # noqa: BLE001 — telemetry must never block the caller
        print(
            f"[codex_driver] WARNING: telemetry event '{kind}' failed: {exc}",
            file=sys.stderr,
        )
