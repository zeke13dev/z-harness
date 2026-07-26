"""Fail closed when Hatch is asked to package an ambient source checkout.

Public wheels are assembled by ``scripts/assemble-release.py`` from the
positive release surface.  A generic Hatch build from a Git checkout would
bypass that boundary and can include force-included development files.
"""

from __future__ import annotations

from pathlib import Path

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ModuleNotFoundError:  # pragma: no cover - Hatch supplies this in builds.
    class BuildHookInterface:  # type: ignore[no-redef]
        """Small test-time stand-in when Hatch is not a runtime dependency."""


class CustomBuildHook(BuildHookInterface):
    """Reject non-canonical wheel construction before Hatch collects files."""

    def initialize(self, version: str, build_data: dict[str, object]) -> None:
        del build_data
        if version == "standard" and (Path(self.root) / ".git").exists():
            raise RuntimeError(
                "direct checkout builds are disabled; use "
                "scripts/assemble-release.py to build from the canonical release stage"
            )
