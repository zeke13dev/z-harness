"""Compatibility wrapper for the shared release-surface contract.

The canonical implementation lives in :mod:`runtime.release_surface` so runtime
export drivers and the CLI consume the same neutral module without importing up
from runtime into ``z_harness_cli``.
"""

from __future__ import annotations

import sys
from runtime import release_surface as _shared_release_surface

if __name__ == "__main__":
    raise SystemExit(_shared_release_surface.main())

sys.modules[__name__] = _shared_release_surface
