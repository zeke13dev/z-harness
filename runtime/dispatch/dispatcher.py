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

- **B3** — Args composition is the dispatcher's responsibility.
  ``final_args`` is produced by :func:`_compose_argv` (which honors
  ``model_arg_template`` ``{model}`` substitution) followed by ``caller_args``.
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

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess
import importlib.util
import json
import threading
import time

from runtime.compat import log_event
from runtime.dispatch.driver import HostDriver
from runtime.dispatch.env import build_env
from runtime.dispatch.result import DispatchResult
from runtime.dispatch.timeout import DispatchTimeoutError


def _compose_argv(provider_config: dict, effective_model: str | None) -> list[str]:
    """Compose the base argv from *provider_config*, honoring ``model_arg_template``.

    Ported from ``scripts/resolve-provider.py::compose_argv``.

    When ``model_arg_template`` is None (v1 provider), returns
    ``list(provider_config["args_template"])`` unchanged — no model resolution
    is attempted.

    When ``model_arg_template`` is set, resolves the model string (caller value
    then ``default_model`` fallback) and renders ``{model}`` in each token.

    Raises:
        ValueError: When ``model_arg_template`` is set but no model can be
            resolved from ``effective_model`` or ``provider_config["default_model"]``.
    """
    argv: list[str] = list(provider_config.get("args_template", []))

    model_arg_template: list[str] | None = provider_config.get("model_arg_template")
    if model_arg_template is None:
        # v1 provider: no model arg; return args_template without model resolution.
        return argv

    # Resolve the effective model string.
    model: str | None = effective_model if effective_model else None
    if not model:
        model = provider_config.get("default_model") or None
    if not model:
        raise ValueError(
            "_compose_argv: effective_model is empty/null and provider has no default_model"
        )

    # Render {model} substitution in each token of model_arg_template.
    rendered = [
        token.replace("{model}", model) if "{model}" in token else token
        for token in model_arg_template
    ]
    argv.extend(rendered)

    return argv


@dataclass(frozen=True)
class ModelRouteResolution:
    """Resolved native-model route plus telemetry metadata."""

    effective_model: str
    source: str
    route: str
    route_kind: str
    thinking: str = ""
    reasoning: str = ""
    override_applied: bool = False
    override_support: str = "advisory"

    def telemetry(self) -> dict:
        """Return JSON-serialisable telemetry fields for model routing events."""
        payload: dict = {
            "effective_model": self.effective_model,
            "source": self.source,
            "route": self.route,
            "route_kind": self.route_kind,
            "override_applied": self.override_applied,
            "override_support": self.override_support,
        }
        if self.thinking:
            payload["thinking"] = self.thinking
        if self.reasoning:
            payload["reasoning"] = self.reasoning
        return payload


def _class_model(config_values: dict[str, object], class_name: str) -> str:
    value = config_values.get(f"model_classes.{class_name}.model")
    return value if isinstance(value, str) else ""


def resolve_model_route(
    route: str,
    config_values: dict[str, object],
    *,
    source: str,
    override_applied: bool = False,
    override_support: str = "advisory",
) -> ModelRouteResolution:
    """Resolve a class name or exact model label to an effective model."""
    if not isinstance(route, str) or not route:
        raise ValueError("model route must be a non-empty string")

    class_model = _class_model(config_values, route)
    if class_model:
        return ModelRouteResolution(
            effective_model=class_model,
            source=source,
            route=route,
            route_kind="class",
            thinking=str(config_values.get(f"model_classes.{route}.thinking") or ""),
            reasoning=str(config_values.get(f"model_classes.{route}.reasoning") or ""),
            override_applied=override_applied,
            override_support=override_support,
        )

    return ModelRouteResolution(
        effective_model=route,
        source=source,
        route=route,
        route_kind="exact",
        override_applied=override_applied,
        override_support=override_support,
    )


def resolve_implementer_model(
    tier: str,
    config_values: dict[str, object],
    *,
    override_applied: bool = False,
    override_support: str = "advisory",
) -> ModelRouteResolution:
    """Resolve /z-execute implementer tier low|medium|high|retry."""
    key = f"model_routing.implementer.{tier}"
    route = config_values.get(key)
    if not isinstance(route, str) or not route:
        raise ValueError(f"missing implementer model route for tier {tier!r}")
    return resolve_model_route(
        route,
        config_values,
        source=key,
        override_applied=override_applied,
        override_support=override_support,
    )


def resolve_native_agent_model(
    agent_id: str,
    frontmatter_model: str,
    config_values: dict[str, object],
    *,
    override_applied: bool = False,
    override_support: str = "advisory",
) -> ModelRouteResolution:
    """Resolve a native agent by exact agent id, default route, then frontmatter."""
    if not agent_id:
        raise ValueError("agent_id must be non-empty")

    route_agent_id = agent_id.replace("-", "_")
    exact_key = f"model_routing.native_agents.{route_agent_id}"
    exact_route = config_values.get(exact_key)
    if isinstance(exact_route, str) and exact_route:
        return resolve_model_route(
            exact_route,
            config_values,
            source=exact_key,
            override_applied=override_applied,
            override_support=override_support,
        )

    default_key = "model_routing.native_agents.default"
    default_route = config_values.get(default_key)
    if isinstance(default_route, str) and default_route:
        return resolve_model_route(
            default_route,
            config_values,
            source=default_key,
            override_applied=override_applied,
            override_support=override_support,
        )

    if not frontmatter_model:
        raise ValueError(f"native agent {agent_id!r} has no frontmatter model fallback")
    return resolve_model_route(
        frontmatter_model,
        config_values,
        source="frontmatter",
        override_applied=False,
        override_support="frontmatter",
    )


def load_model_routing_config(repo_root: str | Path) -> dict[str, object]:
    """Load flattened config values from ``scripts/config.py`` for routing."""
    config_path = Path(repo_root) / "scripts" / "config.py"
    spec = importlib.util.spec_from_file_location("z_harness_config_for_routing", config_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import config.py from {config_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values, _sources = module.load_config()
    return values


def provider_applies_model_override(provider_config: dict) -> bool:
    """Return whether this provider has a concrete model transport."""
    return bool(provider_config.get("model_arg_template") or provider_config.get("model_env_var"))


def _omp_provider_from_argv(argv: list[str]) -> str:
    if not argv:
        return ""
    first = argv[0]
    if "/" not in first:
        return ""
    return first.split("/", 1)[0]


def _auth_backend_for_provider(provider_config: dict, argv: list[str]) -> tuple[str, str]:
    command = os.path.basename(str(provider_config.get("command") or ""))
    omp_provider = _omp_provider_from_argv(argv)
    if command == "omp-consult.sh" or omp_provider:
        if omp_provider == "google-antigravity":
            return "OMP OAuth / Antigravity", omp_provider
        if omp_provider == "openai-codex":
            return "OMP OAuth / Codex", omp_provider
        if omp_provider:
            return f"OMP OAuth / {omp_provider}", omp_provider
        return "OMP OAuth", ""
    if provider_config.get("auth_env"):
        return f"env:{provider_config['auth_env']}", ""
    return "cli-managed", ""


def _attempted_model_for_provider(
    provider_config: dict,
    argv: list[str],
    effective_model: str | None,
) -> str:
    if effective_model:
        return effective_model
    if provider_config.get("default_model"):
        return str(provider_config["default_model"])
    if argv and "/" in argv[0]:
        return argv[0]
    return str(provider_config.get("model_label") or "")


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
        role: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        persona_id: str | None = None,
        selection_source: str | None = None,
        draw_id: str | None = None,
        reviewer_participant: str | None = None,
        model_source: str | None = None,
        model_route: str | None = None,
        model_route_kind: str | None = None,
        model_thinking: str | None = None,
        model_reasoning: str | None = None,
        model_override_applied: bool | None = None,
        model_override_support: str | None = None,
    ) -> DispatchResult:
        """Execute a command via *driver* and return the final result.

        Sequence
        --------
        1. Compose ``final_args`` via :func:`_compose_argv` (honors
           ``model_arg_template`` ``{model}`` substitution) + ``caller_args``.
        2. Emit ``dispatch_start`` event.
        3. Resolve persona/model/runtime overrides; emit override events.
        4. Build subprocess env via :func:`~runtime.dispatch.env.build_env`,
           passing the resolved effective_model so ``model_env_var`` is set.
        5. Call ``driver.dispatch(command_id, final_args, env)`` → handle.
        6. Iterate ``handle.events()`` under a wall-clock timeout guard (phase a),
           collecting yielded dicts into ``stdout_events``.
        7. Call ``handle.wait()`` on a background thread, joining with the
           remaining timeout budget (phase b).
        8. Attach collected ``stdout_events`` to the returned ``DispatchResult``.
        9. Emit ``dispatch_end`` event.
        10. Call ``driver.teardown()``.
        11. Return the ``DispatchResult``.

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
            role: Optional role identifier (e.g. ``"reviewer"``).  When
                provided, included in the ``persona_bound`` event payload.
                Not used for resolution — the caller resolves the role before
                calling ``run()`` (see SPEC §D resolution-ownership note).
            task_id: Optional task identifier for the current task attempt
                (e.g. ``"T007"``).  Included in ``persona_bound`` when provided.
            attempt_id: Optional attempt identifier (e.g. ``"T007-v1"``).
                Included in ``persona_bound`` when provided.
            persona_id: Optional persona identifier from the draw result
                (i.e. the ``name`` field from ``random-for-role`` JSON).
                Always present in ``persona_bound`` — falls back to the
                resolved persona name, or ``null`` when neither is available.
            selection_source: Optional selection source tag from the draw
                (e.g. ``"random_role_pool"``, ``"forced_control"``,
                ``"fixed_panel"``, ``"fallback_empty_pool"``).  Included in
                ``persona_bound`` when provided.
            draw_id: Optional draw identifier from ``random-for-role`` or
                ``forced-control``.  Included in ``persona_bound`` when
                provided.  Acts as the join key between draw and outcome
                events.
            reviewer_participant: Optional discriminator for reviewer role
                dispatches — must be one of ``"base_codex"`` or ``"random_arm"``
                when provided.  Included in ``persona_bound`` when provided.
                Raises :exc:`ValueError` on an invalid value.
            model_source: Optional routing source label for model telemetry,
                e.g. ``"model_routing.native_agents.explore"`` or
                ``"frontmatter"``.  Defaults to the legacy override/provider
                source calculation.
            model_route: Optional configured route before class expansion.
            model_route_kind: Optional ``"class"`` or ``"exact"`` discriminator.
            model_thinking: Optional class thinking metadata.
            model_reasoning: Optional class reasoning metadata.
            model_override_applied: Whether the host actually received a concrete
                model override transport.  When omitted, inferred from provider
                support for model args/env.
            model_override_support: Human-readable support state, usually
                ``"applied"`` or ``"advisory"``.

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

        # 1. Compose final argv (B3) and preflight provider dispatch before
        # any driver call.  Model is needed here for {model} substitution in
        # model_arg_template.
        _early_model: str | None = model if model is not None else provider_config.get("model")
        try:
            base_args: list[str] = _compose_argv(provider_config, _early_model)
        except ValueError as exc:
            self._emit_provider_preflight_failed(
                command_id=command_id,
                role=role,
                runtime=runtime,
                provider_config=provider_config,
                argv=[],
                effective_model=_early_model,
                reason=(
                    f"argv/model composition failed: {exc}; set default_model "
                    "or configure a concrete model"
                ),
            )
            raise
        self._preflight_provider(
            command_id=command_id,
            role=role,
            runtime=runtime,
            provider_config=provider_config,
            argv=base_args,
            effective_model=_early_model,
        )
        final_args: list[str] = base_args + list(caller_args)

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
                "command": command_id,
                "override_field": "persona",
                "value": persona,
                "original": _pc_persona,
            })
        if model is not None and model_source is None:
            self._emit("persona_override_used", {
                "command": command_id,
                "override_field": "model",
                "value": model,
                "original": _pc_model,
            })
        if runtime is not None:
            self._emit("persona_override_used", {
                "command": command_id,
                "override_field": "runtime",
                "value": runtime,
                "original": _pc_runtime,
            })

        # Determine source per axis for telemetry.
        def _axis_source(override_val: str | None, pc_val: str | None) -> str:
            if override_val is not None:
                return "override"
            if pc_val is not None:
                return "provider_config"
            return "none"

        # Build the resolved triple (explicit kwargs win over provider_config).
        _resolved_persona = persona if persona is not None else _pc_persona
        _resolved_model = model if model is not None else _pc_model
        _resolved_runtime = runtime if runtime is not None else _pc_runtime

        _resolved_model_source = model_source or _axis_source(model, _pc_model)
        if model_override_applied is None:
            model_override_applied = (
                _resolved_model is not None and provider_applies_model_override(provider_config)
            )
        _resolved_model_support = model_override_support or (
            "applied" if model_override_applied else "advisory"
        )

        # 2. Build env AFTER resolving _resolved_model so model_env_var is set
        #    correctly (SPEC Invariant #7: env dict is never logged).
        env = build_env(provider_config, effective_model=_resolved_model)
        env["Z_HARNESS_RUN_ID"] = self._run_id
        if role:
            env["Z_HARNESS_PROVIDER_ROLE"] = role


        # Validate reviewer_participant before emitting into telemetry.
        _REVIEWER_PARTICIPANT_VALUES = {"base_codex", "random_arm"}
        if reviewer_participant is not None and reviewer_participant not in _REVIEWER_PARTICIPANT_VALUES:
            raise ValueError(
                f"reviewer_participant must be one of {sorted(_REVIEWER_PARTICIPANT_VALUES)!r},"
                f" got {reviewer_participant!r}"
            )

        # persona_id in the attribution tuple: use the explicitly-supplied
        # persona_id (from the draw result) if given; otherwise fall back to
        # the resolved persona name.  Always present — emits null when neither
        # kwarg nor resolved persona is available so downstream joins are robust.
        _effective_persona_id = persona_id if persona_id is not None else _resolved_persona

        _persona_bound_payload: dict = {
            "run_id": self._run_id,
            "command": command_id,
            "persona": _resolved_persona,
            "persona_id": _effective_persona_id,
            "model": _resolved_model,
            "runtime": _resolved_runtime,
            "source": {
                "persona": _axis_source(persona, _pc_persona),
                "model": _resolved_model_source,
                "runtime": _axis_source(runtime, _pc_runtime),
            },
            "model_override_applied": model_override_applied,
            "model_override_support": _resolved_model_support,
        }
        # Attribution tuple fields — include only when provided by the caller.
        if role is not None:
            _persona_bound_payload["role"] = role
        if task_id is not None:
            _persona_bound_payload["task_id"] = task_id
        if attempt_id is not None:
            _persona_bound_payload["attempt_id"] = attempt_id
        if selection_source is not None:
            _persona_bound_payload["selection_source"] = selection_source
        if draw_id is not None:
            _persona_bound_payload["draw_id"] = draw_id
        if reviewer_participant is not None:
            _persona_bound_payload["reviewer_participant"] = reviewer_participant
        self._emit("persona_bound", _persona_bound_payload)

        _model_resolved_payload = {
            "command": command_id,
            "model": _resolved_model,
            "effective_model": _resolved_model,
            "runtime": _resolved_runtime,
            "source": _resolved_model_source,
            "override_applied": model_override_applied,
            "override_support": _resolved_model_support,
        }
        if model_route is not None:
            _model_resolved_payload["route"] = model_route
        if model_route_kind is not None:
            _model_resolved_payload["route_kind"] = model_route_kind
        if model_thinking:
            _model_resolved_payload["thinking"] = model_thinking
        if model_reasoning:
            _model_resolved_payload["reasoning"] = model_reasoning
        self._emit("model_resolved", _model_resolved_payload)

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

    def _provider_name(self, runtime: str | None, provider_config: dict) -> str:
        return str(provider_config.get("provider") or runtime or provider_config.get("runtime") or "")

    def _preflight_payload(
        self,
        *,
        command_id: str,
        role: str | None,
        runtime: str | None,
        provider_config: dict,
        argv: list[str],
        effective_model: str | None,
        reason: str | None = None,
    ) -> dict:
        auth_backend, _omp_provider = _auth_backend_for_provider(provider_config, argv)
        payload: dict = {
            "command": command_id,
            "role": role,
            "provider": self._provider_name(runtime, provider_config),
            "runtime": runtime or provider_config.get("runtime"),
            "cli_command": provider_config.get("command"),
            "attempted_model": _attempted_model_for_provider(
                provider_config,
                argv,
                effective_model,
            ),
            "auth_backend": auth_backend,
            "argv_argc": len(argv),
        }
        if reason is not None:
            payload["auth_ready"] = False
            payload["reason"] = reason
        return payload

    def _emit_provider_preflight_failed(
        self,
        *,
        command_id: str,
        role: str | None,
        runtime: str | None,
        provider_config: dict,
        argv: list[str],
        effective_model: str | None,
        reason: str,
    ) -> None:
        self._emit(
            "provider_preflight_failed",
            self._preflight_payload(
                command_id=command_id,
                role=role,
                runtime=runtime,
                provider_config=provider_config,
                argv=argv,
                effective_model=effective_model,
                reason=reason,
            ),
        )

    def _fail_provider_preflight(
        self,
        *,
        command_id: str,
        role: str | None,
        runtime: str | None,
        provider_config: dict,
        argv: list[str],
        effective_model: str | None,
        reason: str,
    ) -> None:
        self._emit_provider_preflight_failed(
            command_id=command_id,
            role=role,
            runtime=runtime,
            provider_config=provider_config,
            argv=argv,
            effective_model=effective_model,
            reason=reason,
        )
        provider = self._provider_name(runtime, provider_config) or "<unknown>"
        model = _attempted_model_for_provider(provider_config, argv, effective_model)
        auth_backend, _omp_provider = _auth_backend_for_provider(provider_config, argv)
        raise RuntimeError(
            f"provider_preflight_failed: role={role or '<unknown>'}, "
            f"provider={provider}, model={model}, auth_backend={auth_backend} — {reason}"
        )

    def _preflight_provider(
        self,
        *,
        command_id: str,
        role: str | None,
        runtime: str | None,
        provider_config: dict,
        argv: list[str],
        effective_model: str | None,
    ) -> None:
        command_value = provider_config.get("command")
        command = str(command_value).strip() if isinstance(command_value, str) else ""
        requires_command = (
            "command" in provider_config
            or bool(provider_config.get("provider"))
        )
        if requires_command and not command:
            self._fail_provider_preflight(
                command_id=command_id,
                role=role,
                runtime=runtime,
                provider_config=provider_config,
                argv=argv,
                effective_model=effective_model,
                reason="provider command is empty — fix providers.json command",
            )
        if command and not shutil.which(command):
            self._fail_provider_preflight(
                command_id=command_id,
                role=role,
                runtime=runtime,
                provider_config=provider_config,
                argv=argv,
                effective_model=effective_model,
                reason=f"command={command} not on PATH — install the CLI or update PATH",
            )

        auth_env = provider_config.get("auth_env")
        if auth_env and not os.environ.get(str(auth_env)):
            self._fail_provider_preflight(
                command_id=command_id,
                role=role,
                runtime=runtime,
                provider_config=provider_config,
                argv=argv,
                effective_model=effective_model,
                reason=f"auth env var {auth_env} is not set",
            )

        auth_backend, omp_provider = _auth_backend_for_provider(provider_config, argv)
        auth_ready: bool | str = True if auth_env else "not_required"
        if omp_provider:
            if not shutil.which("omp"):
                self._fail_provider_preflight(
                    command_id=command_id,
                    role=role,
                    runtime=runtime,
                    provider_config=provider_config,
                    argv=argv,
                    effective_model=effective_model,
                    reason="'omp' is not on PATH — install oh-my-pi or choose a direct CLI provider",
                )
            timeout_s = float(os.environ.get("Z_HARNESS_PROVIDER_PREFLIGHT_TIMEOUT_S", "25"))
            try:
                token = subprocess.run(
                    ["omp", "token", omp_provider],
                    capture_output=True,
                    text=False,
                    timeout=timeout_s,
                    check=False,
                )
                token_ok = token.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                token_ok = False
            if not token_ok:
                self._fail_provider_preflight(
                    command_id=command_id,
                    role=role,
                    runtime=runtime,
                    provider_config=provider_config,
                    argv=argv,
                    effective_model=effective_model,
                    reason=(
                        f"auth not ready for {omp_provider}; run 'omp', then '/login' "
                        "for that provider before retrying"
                    ),
                )
            auth_ready = True

        payload = self._preflight_payload(
            command_id=command_id,
            role=role,
            runtime=runtime,
            provider_config=provider_config,
            argv=argv,
            effective_model=effective_model,
        )
        payload["auth_backend"] = auth_backend
        payload["auth_ready"] = auth_ready
        self._emit("provider_preflight_ok", payload)

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
