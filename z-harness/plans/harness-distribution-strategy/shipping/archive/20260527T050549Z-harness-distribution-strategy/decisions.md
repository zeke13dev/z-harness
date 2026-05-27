# Cluster C6 Decisions

## Resolved

- C6-D1, one-minor-version, export-*.py and pre-migration commands print a deprecation warning for one minor version then are removed in the following release; audit-tarball.sh keeps legacy paths in allowlist for that one minor version; install.sh keeps a --legacy flag scoped to one minor version removed thereafter; commands/z-update.md emits a one-time migration nudge when it detects legacy install layout.

## Resolved late (re-spawn)

- C6-D1 was escalated and resolved by orchestrator before initial SPEC/PLAN/TASKS were written. Resolution baked into plan on this re-spawn pass.
