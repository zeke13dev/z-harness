"""z_harness_cli — packaging CLI for z-harness (install, export, launch, doctor, update)."""

from __future__ import annotations

import json
import os
import subprocess
from importlib.metadata import PackageNotFoundError, version


def _version_from_version_sh() -> str | None:
    """Run scripts/version.sh and parse the z_harness_version field."""
    # Locate version.sh relative to the package: walk up from this file.
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", "scripts", "version.sh"),
        os.path.join(here, "..", "version.sh"),
    ]
    for script in candidates:
        script = os.path.normpath(script)
        if os.path.isfile(script):
            try:
                result = subprocess.run(
                    ["bash", script],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    data = json.loads(result.stdout.strip())
                    ver = data.get("z_harness_version")
                    if ver and ver not in ("unknown", "non-git"):
                        return ver
            except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
                pass
    return None


def _resolve_version() -> str:
    # 1. Try package metadata (set at wheel-build time via dynamic version).
    try:
        return version("z-harness")
    except PackageNotFoundError:
        pass
    # 2. Try version.sh at runtime (development / editable installs).
    v = _version_from_version_sh()
    if v:
        return v
    # 3. Static fallback.
    return "0.0.0.dev0"


__version__: str = _resolve_version()
