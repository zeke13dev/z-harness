"""
runtime/drivers/windsurf — Windsurf export-only driver package.

Export-only asymmetry
---------------------
Windsurf is an EXPORT-ONLY target.  There is no HostAdapter, HostDriver, or
adapter-registry entry for this package.  This package owns only the export
pipeline: it reads from the z-harness source tree and writes
``.windsurf/rules/*.md`` files to *export_root*.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Imported from :mod:`runtime.drivers.windsurf.export`.
"""

from runtime.drivers.windsurf.export import export

__all__ = ["export"]
