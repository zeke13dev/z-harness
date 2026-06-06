"""z_harness_cli.adapters — HostAdapter protocol and supporting types.

Each concrete adapter lives in its own module (claude.py, cursor.py,
codex.py, antigravity.py).  This package exposes the public contract.
"""

from z_harness_cli.adapters.base import (
    COMMAND_CAPABILITY_MATRIX,
    Capabilities,
    CommandTier,
    DetectResult,
    ExportResult,
    FidelityTier,
    HostAdapter,
    Injection,
    command_tier,
)

__all__ = [
    "Capabilities",
    "COMMAND_CAPABILITY_MATRIX",
    "CommandTier",
    "DetectResult",
    "ExportResult",
    "FidelityTier",
    "HostAdapter",
    "Injection",
    "command_tier",
]
