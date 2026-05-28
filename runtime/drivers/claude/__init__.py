"""
runtime.drivers.claude
======================

Host drivers for the Claude Code / Claude CLI family.

Exports
-------
SelfHostDriver
    In-process HostDriver for use when z-harness runs inside Claude Code.
    Delegates to in-process tool primitives rather than spawning a subprocess.

DriverInitError
    Raised by SelfHostDriver.__init__ when the host is not Claude Code
    (CLAUDECODE env var absent) and force=True was not passed.

SubprocessClaudeDriver
    HostDriver that spawns ``claude -p --bare`` as a child process.
    Used when another host wants to delegate work to Claude as a subprocess.
"""

from runtime.drivers.claude.self_host_driver import DriverInitError, SelfHostDriver
from runtime.drivers.claude.subprocess_driver import SubprocessClaudeDriver

__all__ = [
    "SelfHostDriver",
    "DriverInitError",
    "SubprocessClaudeDriver",
]
