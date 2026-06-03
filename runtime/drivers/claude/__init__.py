"""
runtime.drivers.claude
======================

Host drivers for the Claude Code / Claude CLI family.

Exports
-------
SubprocessClaudeDriver
    HostDriver that spawns ``claude -p --bare`` as a child process.
    Used when another host wants to delegate work to Claude as a subprocess.

Note: SelfHostDriver and DriverInitError are tombstoned and no longer exported
here. The tombstone file ``self_host_driver.py`` is kept for import compatibility
but the class cannot be instantiated. See docs/human/runtime-dispatch.md.
"""

from runtime.drivers.claude.subprocess_driver import SubprocessClaudeDriver

__all__ = [
    "SubprocessClaudeDriver",
]
