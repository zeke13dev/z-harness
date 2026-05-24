# PLAN-LAYOUT — Plan Directory Layout and Migration Guide

> Last updated: 2026-05-24

## Overview

Plan output is namespaced under `z-harness/plans/<slug>/`. This is the
canonical layout since the portable-harness restructure. The legacy path
(`z-harness/<slug>/`) is supported as a read-only fallback so existing plans
continue to work without immediate migration.

---

## Canonical layout

```
z-harness/
└── plans/
    └── <slug>/
        ├── SPEC.md
        ├── PLAN.md
        ├── TASKS.md
        ├── TESTS.md              (if /z-test was run)
        ├── BRAINSTORM.md         (if /z-brainstorm was run)
        ├── RESEARCH.md           (if /z-research was run)
        ├── archive/
        │   └── <run-id>/
        │       └── events.jsonl
        └── improvements/
```

---

## Z_HARNESS_PLANS_DIR override

The plans root directory can be overridden with the `Z_HARNESS_PLANS_DIR`
environment variable:

```bash
Z_HARNESS_PLANS_DIR=/tmp/my-plans /z-plan my-task
```

When set, the variable is used verbatim — no normalization or relative
expansion. This is the recommended way to isolate plans in CI or test
environments.

Default (variable unset): `z-harness/plans`

---

## Dual-read fallback

All commands try the new path first. If the new path does not exist, they fall
back to the legacy path and emit a one-line warning:

```
[plan-path] WARNING: using legacy path z-harness/<slug>/ — run:
  bash scripts/migrate-plan-layout.sh <slug>
```

This fallback is read-only: commands never write new artifacts to the legacy
path. Once a plan has been migrated, the fallback warning disappears.

The `scripts/plan-path.sh` helper exposes two functions used by all commands:

```bash
plan_dir <slug>         # echoes ${Z_HARNESS_PLANS_DIR:-z-harness/plans}/<slug>
legacy_plan_dir <slug>  # echoes z-harness/<slug>
```

---

## Migrating existing plans

### Single slug

```bash
bash scripts/migrate-plan-layout.sh my-slug
```

This moves `z-harness/my-slug/` to `z-harness/plans/my-slug/`. The operation
is idempotent: if the plan is already at the new path, the script exits with
a success message and does nothing.

### All plans at once

```bash
bash scripts/migrate-plan-layout.sh --all
```

Scans `z-harness/` for any subdirectory that contains `PLAN.md`, `SPEC.md`,
or `TASKS.md` at its root and migrates each one.

### Dry run

```bash
bash scripts/migrate-plan-layout.sh --dry-run my-slug
bash scripts/migrate-plan-layout.sh --all --dry-run
```

Prints what would be moved without making any changes. Combine with `--all`
to preview a bulk migration.

### Safety

- The script refuses to overwrite an existing directory at the new path. If
  `z-harness/plans/<slug>/` already exists and is non-empty, it exits with an
  error showing the diff.
- Nothing inside the moved files is rewritten — path construction is
  runtime-resolved via `Z_HARNESS_PLANS_DIR`.
- A `migration_done` event per slug is logged to `z-harness/metrics.jsonl`.

---

## Summary of affected commands

Every command that constructs plan-relative paths uses `scripts/plan-path.sh`.
The affected list includes: `z-plan`, `z-plan-light`, `z-plan-split`,
`z-amend`, `z-implement-all`, `z-implement-next`, `z-debug`, `z-fix`,
`z-improve`, `z-research`, `z-brainstorm`, `z-audit`, `z-test`,
`z-maintain-docs`, `z-mr-review`, `z-style-init`, `z-stats`, `z-review-all`,
`z-do`, `z-skill-fix`, `z-init-docs`.

Scripts that also respect `Z_HARNESS_PLANS_DIR`: `scripts/log-event.sh`,
`scripts/log-phase.sh`.
