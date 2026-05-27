# Late-resolved decisions — shipping (C6)

## C6-D1 — Legacy adapter sunset window
Resolved by user: **one-minor-version**. export-*.py and pre-migration commands print a deprecation warning for one minor version, then are removed in the following release. Plan:
- Deprecation warning text: stable, names the new runtime equivalent, links to docs.
- audit-tarball.sh keeps legacy paths in the allowlist for that one minor version.
- install.sh keeps a --legacy flag scoped to one minor version, removed thereafter.
- commands/z-update.md emits a one-time migration nudge when it detects legacy install layout.
