"""
runtime/drivers/cline — Cline export-only driver package.

Export-only asymmetry
---------------------
Cline is an EXPORT-ONLY target.  There is no HostAdapter, HostDriver, or
adapter-registry entry for this package.  This package owns only the export
pipeline: it reads from the z-harness source tree and writes
``.clinerules/`` markdown files to *export_root*.

Default strategy: ``pointer``
-----------------------------
Cline loads **all** ``.clinerules/`` files into context on every prompt.
Emitting the full 100+ rule set would bloat every prompt unacceptably.
The default strategy therefore emits a **single** pointer / capabilities doc
that describes z-harness and how to invoke it.  Users may opt into
``curated`` or ``full`` via ``config.toml [export] strategy``.

Public surface
--------------
export(repo_root, export_root, *, options=None) -> ExportResult
    Imported from :mod:`runtime.drivers.cline.export`.
"""

from runtime.drivers.cline.export import export

__all__ = ["export"]
