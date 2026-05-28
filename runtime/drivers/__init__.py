"""
runtime/drivers — host-driver implementations and driver selection for z-harness provider backends.

Each sub-package implements a HostDriver for a specific CLI or SDK backend.
Currently implemented:

- claude:  SelfHostDriver (in-process) and SubprocessClaudeDriver (subprocess)
- cursor:  CursorCLIDriver (subprocess); CursorSDKDriver stubbed (v2 milestone)
- codex:   Codex CLI driver (runtime/drivers/codex/)

Public surface
--------------
select_driver(host, driver_override=None) -> HostDriver instance
    Factory function that auto-detects the appropriate driver for a given host,
    with optional explicit override via driver_override.

DriverNotFoundError
    Raised when host is unknown or unsupported.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from runtime.drivers.claude.env_hygiene import detect_self_hosted
from runtime.drivers.claude.self_host_driver import SelfHostDriver
from runtime.drivers.claude.subprocess_driver import SubprocessClaudeDriver
from runtime.drivers.cursor.cli_driver import CursorCLIDriver

try:
    from runtime.compat import log_event as _log_event
except ImportError:
    _log_event = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class DriverNotFoundError(Exception):
    """Raised by select_driver when the requested host or driver is unknown.

    This is the C1-level exception for driver lookup failures.  Callers
    should catch this to present a user-friendly error before aborting.
    """


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def select_driver(
    host: str,
    driver_override: str | None = None,
) -> object:
    """Select and return the appropriate HostDriver for the given host.

    Parameters
    ----------
    host:
        The provider host identifier.  Supported values: ``"claude"``,
        ``"cursor"``.  Any other value raises :class:`DriverNotFoundError`.
    driver_override:
        Optional explicit driver selection.  When provided, bypasses
        auto-detection and uses the specified driver directly.

        Supported overrides:

        - ``"claude-self"`` — force :class:`SelfHostDriver` regardless of
          env detection (useful when CLAUDECODE is not set but the caller
          knows the context).
        - ``"cursor-sdk"`` — raises :exc:`NotImplementedError` immediately
          (CursorSDKDriver is a v2 milestone; @cursor/sdk is in public beta).

    Returns
    -------
    HostDriver instance (concrete subclass of HostDriver)

    Raises
    ------
    DriverNotFoundError:
        If *host* is not a known provider.
    NotImplementedError:
        If ``driver_override="cursor-sdk"`` is requested (v2 milestone).
    """
    if host == "claude":
        detection_method: str
        driver_instance: object

        if driver_override == "claude-self" or detect_self_hosted():
            detection_method = "override" if driver_override == "claude-self" else "env"
            driver_instance = SelfHostDriver(force=True)
        else:
            detection_method = "env"
            driver_instance = SubprocessClaudeDriver()

        _emit_driver_selected(
            driver_class=type(driver_instance).__name__,
            host=host,
            detection_method=detection_method,
        )
        return driver_instance

    elif host == "cursor":
        if driver_override == "cursor-sdk":
            raise NotImplementedError(
                "CursorSDKDriver is not implemented in v1. "
                "See v2 milestone: @cursor/sdk (public beta 2026-04-29). "
                "Use CursorCLIDriver (driver_override='cursor-cli') or "
                "omit driver_override for the default CLI driver."
            )

        driver_instance = CursorCLIDriver()
        _emit_driver_selected(
            driver_class="CursorCLIDriver",
            host=host,
            detection_method="default",
        )
        return driver_instance

    else:
        raise DriverNotFoundError(
            f"Unknown host {host!r}. Supported hosts: 'claude', 'cursor'."
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _emit_driver_selected(
    driver_class: str,
    host: str,
    detection_method: str,
) -> None:
    """Emit driver_selected telemetry event; fire-and-forget."""
    if _log_event is None:
        return
    try:
        _log_event(
            run_id="select-driver",
            kind="driver_selected",
            payload={
                "driver_class": driver_class,
                "host": host,
                "detection_method": detection_method,
            },
            repo_root="",
        )
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(
            f"[drivers] WARNING: driver_selected telemetry failed: {exc}",
            file=sys.stderr,
        )
