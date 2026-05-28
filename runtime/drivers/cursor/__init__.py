"""
runtime/drivers/cursor — Cursor HostDriver package.

This package implements the HostDriver tiers for the Cursor backend within
the host-neutral z-harness runtime. It owns:

- cli_driver.py  : CLI-tier HostDriver implementation (cursor-agent -p
                   subprocess, stream-json output parsing, CURSOR_API_KEY auth)
- sdk_driver.py  : SDK-tier stub (raises NotImplementedError; v2 milestone)

Public entry points:

    from runtime.drivers.cursor import CursorCLIDriver
    from runtime.drivers.cursor import CursorSDKDriver
    from runtime.drivers.cursor import DriverConfigError, DriverInitError
"""

from runtime.drivers.cursor.cli_driver import (
    CursorCLIDriver,
    DriverConfigError,
    DriverInitError,
)
from runtime.drivers.cursor.sdk_driver import CursorSDKDriver

__all__ = ["CursorCLIDriver", "CursorSDKDriver", "DriverConfigError", "DriverInitError"]
