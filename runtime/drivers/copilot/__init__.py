"""
runtime/drivers/copilot — GitHub Copilot export-only driver package.

Export-only asymmetry
---------------------
GitHub Copilot is an EXPORT-ONLY target.  There is no HostAdapter, HostDriver,
or adapter-registry entry for this package.  This package owns only the export
pipeline: it reads from the z-harness source tree and writes a single
``.github/copilot-instructions.md`` file to *export_root*.

GitHub Copilot reads exactly one file — ``.github/copilot-instructions.md`` —
at the repository level.  The strategy is therefore effectively ``pointer``
regardless of the configured export strategy: all z-harness capabilities are
consolidated into that single file.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Imported from :mod:`runtime.drivers.copilot.export`.
"""

from runtime.drivers.copilot.export import export

__all__ = ["export"]
