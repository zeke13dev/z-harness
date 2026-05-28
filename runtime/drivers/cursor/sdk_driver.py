"""
runtime.drivers.cursor.sdk_driver
==================================

Stub implementation of the Cursor SDK-tier HostDriver.

This class is intentionally **not implemented** in v1. Decision C4-D3 in
PLAN.md (cluster C4, driver-claude-cursor) designates the ``@cursor/sdk``
SDK tier as a v2 milestone because the package is in public beta (released
2026-04-29) and adding it as a v1 dependency would escalate complexity per
the dependency rubric.

See v2 milestone: @cursor/sdk (public beta 2026-04-29).
Use :class:`~runtime.drivers.cursor.cli_driver.CursorCLIDriver` for v1.

This module does **not** import ``@cursor/sdk`` at the module level.  The
package may be absent in v1 environments and its absence must not prevent
importing this stub.
"""

from __future__ import annotations

from runtime.dispatch.driver import DispatchHandle, HostDriver

_NOT_IMPLEMENTED_MSG = (
    "CursorSDKDriver is not implemented in v1. "
    "See v2 milestone: @cursor/sdk (public beta 2026-04-29). "
    "Use CursorCLIDriver for v1."
)


class CursorSDKDriver(HostDriver):
    """Stub Cursor SDK-tier driver.  All methods raise :exc:`NotImplementedError`.

    Implements the :class:`~runtime.dispatch.driver.HostDriver` protocol so
    the class is importable and type-checkable, but every method body raises
    ``NotImplementedError`` to make it unambiguous that no SDK functionality
    is available in v1.

    This stub exists to satisfy PLAN.md C4-D3: CLI-only in v1; SDK stubbed
    (NotImplementedError).  When ``@cursor/sdk`` exits beta, the v2 task can
    replace this file with a full implementation without touching the CLI
    driver or the package ``__init__``.

    References:
        - PLAN.md decision C4-D3 (cluster C4, driver-claude-cursor)
        - v2 milestone: @cursor/sdk (public beta 2026-04-29)
    """

    def init(
        self,
        provider_config: dict,
        context: dict | None = None,
    ) -> None:
        """Not implemented in v1.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def dispatch(
        self,
        command_id: str,
        args: list[str],
        env: dict,
    ) -> DispatchHandle:
        """Not implemented in v1.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def teardown(self) -> None:
        """Not implemented in v1.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
