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

---

---

## Command-coverage checklist (Phase-D flip gate)

> **GATE:** The Phase-D default flip (T015 / `Z_HARNESS_EXTERNAL_DEFAULT=1`) MUST NOT
> proceed until:
>
> 1. Every checkbox in this section is checked (confirming all run-creating and
>    run-consuming commands route exclusively through `plan-path.sh` helpers), AND
> 2. `bash scripts/test_external_base_smoke.sh` passes (hermetic external-base
>    end-to-end verification).
>
> If either condition is not met, T015 is blocked. Inform the user and stop.

### What "routes through helpers" means

A command routes all paths through `plan-path.sh` helpers when every path it
constructs for plan artifacts (`TASKS.md`, `SPEC.md`, `archive/`, `active-plans/`,
`followups/`, etc.) is derived from one of the following functions (never from an
inline `z-harness/` literal):

| Helper | Returns |
|--------|---------|
| `base_dir()` / `z_harness_base()` | Resolved artifact base |
| `plan_dir <slug>` | `<base>/plans/<slug>` |
| `active_plans_dir()` | `<base>/active-plans` |
| `followups_dir()` | `<base>/followups` |
| `all_plan_slugs()` | All slugs (new layout + legacy flat) |
| `resolve_plan_path <slug>` | Existing plan dir (new → legacy dual-read) |

The audit task (T003) verified each command below against this criterion.

### Run-creating commands

- [x] **`/z-plan`** — slug discovery and plan-dir construction route through
  `plan_dir()` / `all_plan_slugs()`; register/heartbeat/deregister use
  `active_plans_dir()`. No inline `z-harness/` literals.

- [x] **`/z-plan-light`** — shares the same helper-routed plumbing as `/z-plan`;
  register/heartbeat/deregister wired to `active_plans_dir()`.

- [x] **`/z-debug`** — plan artifact paths use `plan_dir()`; registry calls use
  `active_plans_dir()`.

- [x] **`/z-do`** — plan path resolved via `resolve_plan_path()` /
  `plan_dir()`; registry register/deregister use `active_plans_dir()`.

- [x] **`/z-audit`** — reads plan artifacts via `resolve_plan_path()`;
  no inline `z-harness/` path construction.

- [x] **`/z-plan-split`** — uses `plan_dir()` for both source and target slugs;
  register/heartbeat/deregister use `active_plans_dir()`.

### Run-consuming commands

- [x] **`/z-implement-all`** — `PROJECT_SINK` constructed via `followups_dir()`;
  slug discovery via `all_plan_slugs()`; phase-0 register + scope-extract +
  overlaps + heartbeat + deregister all use `active_plans_dir()`.

- [x] **`/z-implement-next`** — single-task variant of `/z-implement-all`;
  same phase-0 register + overlap + heartbeat + deregister wiring.

- [x] **`/z-where`** — read-only query: calls `base_dir()`, `active_plans_dir()`,
  and `all_plan_slugs()`; no plan artifact writes.

- [x] **`/z-stats`** — always prints resolved base via `base_dir()` + repo-id;
  one-line active-plan count from `active_plans_dir()`. No inline literals.

### Smoke test gate

Run the hermetic end-to-end verification before flipping:

```bash
bash scripts/test_external_base_smoke.sh
```

The test exercises (under a temp external base via `Z_HARNESS_BASE_DIR`):

1. `base_dir()` resolves to the external base (not the in-repo `z-harness/`).
2. `all_plan_slugs()` discovers both new-layout (`<base>/plans/<slug>/`) and
   legacy-flat (`<base>/<slug>/`) plans.
3. `active-plan-registry.py register` lands the record under `<base>/active-plans/`.
4. Mechanical `**Files:**`-parse fallback → `update-scope` → scope stored in record.
5. `overlaps` exits 0 with no peers.
6. `list` / direct read-back confirms the record is correct.
7. **Nothing is written under the in-repo `z-harness/`** (the durability guarantee).
8. No anchor pollution at the real repo's `.git/.z-harness-base`.

---

## Active-plan registry

The external base also hosts the active-plan coordination registry. See `docs/human/active-plan-registry.md` for the full design reference, including the lockless per-run JSON registry under `<base>/active-plans/`, the scope-extractor integration, and the overlap advisory protocol.

---

## Plugin directory layout

The z-harness plugin itself is laid out as follows:

```
z-harness/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── commands/
│   └── z-*.md
├── agents/
│   └── *.md
├── scripts/
│   ├── config.py
│   ├── config.sh
│   ├── extract-dismissals.py
│   ├── log-event.sh
│   ├── log-phase.sh
│   ├── remote-sandbox-sync.sh
│   └── version.sh
├── docs/
│   ├── human/    ← human-readable reference
│   └── llm/      ← LLM-tier fast-lookup JSONs
└── README.md
```
