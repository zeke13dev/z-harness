"""Per-host ``HostAdapter`` implementations for the session-watchdog daemon.

``base.py`` defines the four-capability ``HostAdapter`` contract; this package
holds one module per babysat host (``claude`` here; ``codex``/``omp`` follow
at level 1 — see ``runtime/watchdog/HOST_MECHANICS.md``). Re-exported here for
convenience so callers can write ``from runtime.watchdog.adapters import
ClaudeAdapter`` instead of reaching into the submodule.
"""

from __future__ import annotations

from runtime.watchdog.adapters.base import ContextReading, HostAdapter
from runtime.watchdog.adapters.claude import ClaudeAdapter
from runtime.watchdog.adapters.codex import CodexAdapter
from runtime.watchdog.adapters.omp import OmpAdapter

__all__ = ["HostAdapter", "ContextReading", "ClaudeAdapter", "CodexAdapter", "OmpAdapter"]
