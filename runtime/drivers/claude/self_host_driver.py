"""
runtime/drivers/claude/self_host_driver.py — TOMBSTONED driver (not usable).

SelfHostDriver was an in-process HostDriver concept that would have delegated
command execution to Claude Code tool primitives (Read, Edit, Bash, Agent).
The mechanism was found to be infeasible: the required in-process C1 interface
was never defined and the approach cannot work in a subprocess-worker model.

This file is kept as a tombstone so that imports do not produce ModuleNotFoundError.
Instantiating ``SelfHostDriver`` raises ``NotImplementedError`` immediately.
``SelfHostDriver`` is **not** reachable via ``select_driver()``; it is removed
from all selectable code paths.

Doc reference: docs/human/runtime-dispatch.md — "SelfHostDriver (tombstoned)"
"""

from __future__ import annotations

from runtime.dispatch.driver import DispatchHandle, HostDriver
from runtime.dispatch.result import DispatchResult


# ---------------------------------------------------------------------------
# Public exceptions (kept for import compatibility; no longer raised normally)
# ---------------------------------------------------------------------------


class DriverInitError(Exception):
    """Legacy exception from the SelfHostDriver era.

    No longer raised in normal operation.  Kept so existing test imports
    continue to compile.  The class itself is a tombstone artifact.
    """


# ---------------------------------------------------------------------------
# SelfHostDriver — tombstoned
# ---------------------------------------------------------------------------


class SelfHostDriver(HostDriver):
    """TOMBSTONED — do not use.

    This driver is not reachable via ``select_driver()``.  Instantiation
    raises ``NotImplementedError`` immediately regardless of arguments.

    The in-process tool-primitive approach this class was designed around was
    found to be infeasible (see memory note ``project-runtime-dispatch-premise.md``).
    Use ``SubprocessClaudeDriver`` for Claude-backed dispatches instead.

    Doc reference: docs/human/runtime-dispatch.md — "SelfHostDriver (tombstoned)"
    """

    def __init__(self, *, force: bool = False) -> None:
        raise NotImplementedError(
            "SelfHostDriver is tombstoned and cannot be instantiated. "
            "Use SubprocessClaudeDriver for Claude-backed dispatches. "
            "See docs/human/runtime-dispatch.md — 'SelfHostDriver (tombstoned)'."
        )

    # ------------------------------------------------------------------
    # HostDriver ABC — all methods raise; class is non-functional
    # ------------------------------------------------------------------

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        raise NotImplementedError(
            "SelfHostDriver is tombstoned. "
            "See docs/human/runtime-dispatch.md — 'SelfHostDriver (tombstoned)'."
        )

    def dispatch(
        self,
        command_id: str,
        args: list[str],
        env: dict,
    ) -> DispatchHandle:
        raise NotImplementedError(
            "SelfHostDriver is tombstoned. "
            "See docs/human/runtime-dispatch.md — 'SelfHostDriver (tombstoned)'."
        )
