"""
runtime.dispatch.driver
=======================

Defines the ``HostDriver`` abstract base class and the ``DispatchHandle``
dataclass that every driver implementation must return from ``dispatch()``.

Contract overview
-----------------
- The *driver* owns the subprocess (or in-process equivalent) AND owns
  parsing of whatever output format that subprocess emits.  The dispatcher
  NEVER parses ``stream-json`` or any other output format directly.
- ``DispatchHandle`` is the seam between the driver and the dispatcher.
  The dispatcher iterates ``events()`` while applying ``TimeoutReaper``,
  then calls ``wait()`` once the stream is exhausted.
- ``teardown()`` is called by the dispatcher after ``wait()`` returns,
  regardless of success or failure.  The default no-op is intentional so
  simple drivers need not implement it.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from runtime.dispatch.result import DispatchResult


# ---------------------------------------------------------------------------
# DispatchHandle
# ---------------------------------------------------------------------------


@dataclass
class DispatchHandle:
    """Opaque handle returned by :meth:`HostDriver.dispatch`.

    The dispatcher consumes this handle in two phases:

    1. **Streaming phase** — iterates :meth:`events` while enforcing
       timeouts via ``TimeoutReaper``.  Each yielded ``dict`` is a parsed
       event in the z-harness event envelope (schema_version, type, …).
       The driver is responsible for parsing its subprocess output into
       this normalised dict form — the dispatcher treats events as opaque.

    2. **Completion phase** — calls :meth:`wait` after the events iterator
       is exhausted (or after the reaper fires).  ``wait`` blocks until the
       subprocess exits and returns a :class:`~runtime.dispatch.result.DispatchResult`.

    Implementers must supply ``_events_fn`` and ``_wait_fn`` callables that
    back the two methods.  Both are stored as private fields so subclasses
    can replace them if needed, but the preferred pattern is to supply them
    at construction time from ``HostDriver.dispatch``.

    Example construction inside a driver::

        def dispatch(self, command_id, args, env):
            proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE)
            return DispatchHandle(
                _events_fn=lambda: self._parse_stream(proc.stdout),
                _wait_fn=lambda: self._collect_result(proc),
            )
    """

    _events_fn: object = field(repr=False)
    """Zero-argument callable that returns an ``Iterator[dict]``."""

    _wait_fn: object = field(repr=False)
    """Zero-argument callable that blocks and returns a ``DispatchResult``."""

    def events(self) -> Iterator[dict]:
        """Yield parsed events incrementally as the subprocess produces them.

        Each yielded value is a ``dict`` conforming to the z-harness event
        envelope (``schema_version``, ``type``, and type-specific fields).
        The driver owns parsing; the dispatcher treats these dicts as opaque
        and forwards them to event consumers / log sinks.

        The iterator may block between yields while waiting for the next line
        from the subprocess stdout.  The dispatcher wraps this in
        ``TimeoutReaper``; drivers do not need to implement their own timeout.

        Raises:
            Any subprocess-level ``OSError`` or codec error propagates up to
            the dispatcher unchanged — drivers should not swallow I/O errors.
        """
        yield from self._events_fn()  # type: ignore[call-arg]

    def wait(self) -> "DispatchResult":
        """Block until the subprocess exits and return the final result.

        This method is called by the dispatcher after the ``events()``
        iterator is exhausted (or after ``TimeoutReaper`` forcibly stops
        it).  It must not return until the subprocess has terminated —
        call ``proc.wait()`` (or equivalent) before constructing the result.

        Returns:
            :class:`~runtime.dispatch.result.DispatchResult` describing the
            exit status, captured stdout/stderr excerpts, and any
            driver-specific metadata.

        Raises:
            :class:`subprocess.TimeoutExpired` must NOT be raised here; if
            the reaper already killed the process the driver should detect the
            non-zero exit code and encode it in ``DispatchResult`` instead.
        """
        return self._wait_fn()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# HostDriver ABC
# ---------------------------------------------------------------------------


class HostDriver(abc.ABC):
    """Abstract base class for all z-harness host drivers.

    A *driver* is responsible for:

    - Launching a command on a specific host (remote SSH, local subprocess,
      in-process agent, Codex API, Cursor CLI, …).
    - Parsing that host's native output format into normalised z-harness
      event dicts.
    - Returning a :class:`DispatchHandle` that the dispatcher can iterate
      without knowing anything about the underlying transport or format.

    **Subprocess ownership** — The driver owns the subprocess lifecycle.
    The dispatcher NEVER calls ``proc.kill()`` or ``proc.wait()`` directly;
    all process management is encapsulated here.  The dispatcher only calls
    ``handle.events()``, ``handle.wait()``, and ``driver.teardown()``.

    **Parsing ownership** — Different hosts emit different output formats
    (``stream-json`` for Codex/Antigravity/Cursor; plain text for Gemini;
    no output at all for ``SelfHostDriver``).  The driver is the only place
    that knows the format, so parsing lives exclusively in the driver.

    **Context injection** (C1-D5) — :meth:`init` accepts an optional
    ``context`` dict for driver-specific runtime injections.  For example,
    ``SelfHostDriver`` (C4) expects ``context={"tools_registry": {...}}``.
    Drivers MUST silently ignore any context keys they do not recognise —
    this preserves Liskov substitutability at the call-site.

    Implementing a driver::

        class MyDriver(HostDriver):
            def init(self, provider_config, context=None):
                self._base_url = provider_config["url"]
                # Silently ignore unknown context keys:
                # self._token = (context or {}).get("token")  # optional

            def dispatch(self, command_id, args, env):
                proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE)
                return DispatchHandle(
                    _events_fn=lambda: self._parse(proc.stdout),
                    _wait_fn=lambda: self._finish(proc),
                )

        driver = MyDriver()
        driver.init({"url": "http://localhost"})
        handle = driver.dispatch("z-ask", ["--model", "opus"], os.environ.copy())
        for event in handle.events():
            print(event)
        result = handle.wait()
        driver.teardown()
    """

    @abc.abstractmethod
    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Initialise the driver with provider configuration.

        Called once by the dispatcher before the first :meth:`dispatch` call.
        Drivers MUST NOT start subprocesses here; use :meth:`dispatch` for
        that.  ``init`` is the place to validate ``provider_config`` fields,
        open persistent connections (if applicable), and store any runtime
        injections from ``context``.

        **Context injection (C1-D5)** — ``context`` carries driver-specific
        runtime injections that cannot be expressed in ``provider_config`` (a
        static, serialisable dict).  ``SelfHostDriver`` uses
        ``context={"tools_registry": {...}}`` to receive the live tool
        registry from the calling process.  Other drivers MUST silently ignore
        context keys they do not recognise — callers are not required to tailor
        context to each driver.

        Args:
            provider_config: The provider block from ``.z-harness/providers.json``
                (or equivalent) for this driver instance.  Contains at minimum
                ``"host"`` and ``"args_template"`` keys; may contain driver-specific
                keys (``"url"``, ``"model"``, ``"auth_env"``, …).
            context: Optional dict for runtime injections that cannot be
                expressed as static configuration.  Drivers must ignore unknown
                keys without raising.  Defaults to ``None`` (equivalent to
                empty dict).

        Returns:
            ``None``.  Any initialisation error should raise, not return a
            status code.
        """

    @abc.abstractmethod
    def dispatch(
        self,
        command_id: str,
        args: list[str],
        env: dict,
    ) -> DispatchHandle:
        """Launch the command and return a handle for streaming its output.

        The dispatcher composes ``args`` as::

            args = provider_config["args_template"] + caller_args

        …before calling this method, so ``args`` is already the final flat
        argv ready to pass to ``subprocess.Popen`` (or equivalent).

        **Subprocess ownership** — The driver owns the subprocess.  Start it
        here; do not kill or wait on it outside of the returned
        :class:`DispatchHandle`.

        **Parsing ownership** — The driver owns output parsing.  Translate
        whatever format this host emits (``stream-json``, plain text, SDK
        callbacks, …) into normalised z-harness event dicts inside
        ``DispatchHandle._events_fn``.

        Args:
            command_id: The command identifier (e.g. ``"z-ask"``), kebab-case,
                matching the ``id`` field in ``command.schema.json``.  Useful
                for drivers that route commands to different endpoints.
            args: Final flat argv, ready to hand to ``subprocess.Popen``.
                Composed by the dispatcher; the driver must not re-compose it.
            env: Full environment mapping to pass to the subprocess.  Prepared
                by ``runtime.dispatch.env`` (CLAUDECODE override, auth_env
                injection, etc.).

        Returns:
            A :class:`DispatchHandle` whose ``events()`` iterator yields
            parsed event dicts and whose ``wait()`` method blocks until the
            subprocess exits, returning a
            :class:`~runtime.dispatch.result.DispatchResult`.
        """

    def teardown(self) -> None:
        """Clean up any resources held by the driver.

        Called by the dispatcher after :meth:`DispatchHandle.wait` returns,
        regardless of success or failure.  The default implementation is a
        no-op; override when the driver holds persistent resources (open
        sockets, thread pools, SDK sessions, …) that must be released after
        each dispatch cycle.

        Drivers must not raise from ``teardown``; log and swallow any cleanup
        errors so the dispatcher can proceed normally.
        """
