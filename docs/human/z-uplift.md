# /z-uplift

> Last updated: 2026-05-27
> Covers source: commands/z-uplift.md, skills/z-uplift/SKILL.md

## Overview

`/z-uplift` is a bulk codebase quality uplift command for repos adopting z-harness or undergoing periodic cleanup. It decomposes the repository into components (Cargo workspace members, Python packages, JS workspaces, or top-level directories), runs a repo-wide cross-cutting pass to surface global issues (duplicated abstractions, style drift, dead code at module boundaries), dispatches per-component audits across `correctness`, `cleanliness`, and `design` dimensions, and produces per-component `TASKS.md` files that `/z-implement-all --tasks=` can directly consume.

The command is resumable: it writes a `MANIFEST.md` at `z-harness/plans/<slug>/MANIFEST.md` (see Setup at `commands/z-uplift.md:65`) that tracks each component's state (`pending`, `auditing`, `audited`, `implementing`, `done`, `bailed`, `skipped`). Re-invoking `/z-uplift` with no flags resumes at the next non-terminal state. Phase 5 (`commands/z-uplift.md:2428`) drives sequential per-component implementation behind AskUser gates. It prints the `/z-implement-all --tasks=` command and marks each component `[i] implementing` in MANIFEST, then exits so you run the command yourself. This is a deliberate two-step handoff — `/z-uplift` does not invoke `/z-implement-all` automatically — giving you full control over which components to implement, skip, or defer before resuming.

## Key entry points

| Phase | Line | Purpose |
|-------|------|---------|
| Setup | `commands/z-uplift.md:65` | Derive uplift slug, resolve plan dir, pick run ID, log run_start, doc-staleness gate |
| STYLE.md gate | `commands/z-uplift.md:434` | Require STYLE.md at repo root; halt and recommend /z-style-init if missing unless --no-style |
| Phase 0 | `commands/z-uplift.md:519` | Premise check — one-paragraph goal confirmation |
| Phase 1 | `commands/z-uplift.md:559` | Decomposition — auto-detect components, write COMPONENTS.md, AskUser gate; slug collision resolver loops with no-progress sanity counter; `SLUG_RE` validates custom slugs as `^[a-z0-9]+(?:-[a-z0-9]+)*$` |
| Phase 2 | `commands/z-uplift.md:1076` | Cross-cutting pass — parallel consultant dispatches, output CROSS-CUTTING.md; parser emits `cross_cutting_findings_dropped` for non-G/C/R bullets; Step 6 inserts synthetic row as `[a] audited` using atomic write |
| Phase 3 | `commands/z-uplift.md:1619` | Per-component audits — parallel per-dimension, CRIT_HIGH parser handles `### [CRITICAL]` headers structurally, `git grep` guarded against empty OTHER_COMP_PATHS, auto-bail check, REPORT.md + TASKS.md |
| Phase 4 | `commands/z-uplift.md:2282` | Review gate — aggregated queue summary, AskUser continue/abort; cross-cutting-first ordering callout printed if synthetic row is present |
| Phase 5 | `commands/z-uplift.md:2428` | Sequential implement — two-step handoff; prints command, marks `[i]`, exits for user |
| Phase 6 | `commands/z-uplift.md:2808` | Finalize — log run_end, push-notify, recommend /z-maintain-docs |

## How it interacts with others

- `/z-audit` — z-uplift uses the same auditor primitives as /z-audit but applies them across every component; /z-audit is for single-component targeted passes
- `/z-implement-all` — consumed by Phase 5; z-uplift prints the `--tasks=` invocation but does not call it automatically
- `/z-mr-review` — complementary tool for branch-diff review; z-uplift is for full-repo decomposition, not diffs
- `/z-style-init` — prerequisite gate; z-uplift halts and recommends /z-style-init when STYLE.md is absent
- `/z-maintain-docs` — Phase 6 recommends /z-maintain-docs when any task carries a `**DOCS:**` line

## When to use `/z-uplift` vs `/z-audit` vs `/z-mr-review`

Use `/z-uplift` when you want a full-codebase quality pass — for example, when a legacy repo first adopts z-harness, before a major release, or as a quarterly cleanup routine. It is intentionally more expensive than `/z-audit` because it covers every component and includes a cross-cutting Phase 2 pass that finds issues spanning component boundaries.

Use `/z-audit <target>` instead when you already know which component needs attention and want a focused, single-component audit with the same auditor primitives.

Use `/z-mr-review` when your concern is branch-diff quality before merging — it reviews the diff against `STYLE.md` and is unrelated to full-repo decomposition.

Both `/z-audit` and `/z-mr-review` remain the right tools for their respective scopes; `/z-uplift` does not replace them.

## STYLE.md prerequisite and MANIFEST states

`/z-uplift` requires a `STYLE.md` at the repo root (the same prerequisite as `/z-mr-review`). If `STYLE.md` is absent, the STYLE.md gate at `commands/z-uplift.md:434` halts and recommends running `/z-style-init` first. Pass `--no-style` to proceed without it; the cleanliness and design auditors will fall back to a generic rubric and will not cite STYLE rule IDs.

MANIFEST states:
- `[ ] pending` — not yet started
- `[~] auditing` — audit dispatch in progress (detectable on interrupt)
- `[a] audited` — REPORT.md + TASKS.md exist and reviewer gate passed; also the state the synthetic `<slug>-cross-cutting` row is written with at Phase 2 Step 6
- `[i] implementing` — Phase 5 has printed the `/z-implement-all` command and exited; waiting for user to run it
- `[!] bailed: <reason>` — exceeded auto-bail threshold (>30 total findings OR >10 CRIT-HIGH); excluded from implement queue — use `--retry-bailed` to re-attempt, or run `/z-plan` on the component individually
- `[x] done` — terminal; implementation complete
- `[s] skipped` — terminal; user-skipped at AskUser gate

## Notification policy

Push-notification behavior throughout `/z-uplift` is governed by the `notify.level` config key (TOML key), which resolves to the `Z_HARNESS_NOTIFY_LEVEL` environment variable. There is no standalone `Z_HARNESS_NOTIFY` variable. See [docs/human/config.md](docs/human/config.md) for the full config reference, file locations, and the CLI (`scripts/config.sh get notify.level`).

| `notify.level` value | Behavior |
|----------------------|----------|
| `off` | All push-notifications silenced |
| `approval_only` (default) | Notifies on `approval` and `error` events only |
| `all` | Notifies on every `approval`, `phase_end`, and `error` event |

`/z-uplift` emits push-notifications at: decomposition completion (Phase 1 Step 5), review gate (Phase 4), and run finalization (Phase 6). These fire only when `notify.level` permits. Setup Step 4 reads this value via `eval "$(scripts/config.sh export-env)"` before any notifications are attempted.

## Edge cases / gotchas

- **Bail thresholds.** Auto-bail fires when a single component has >30 total audit findings OR >10 CRIT-HIGH findings. The CRIT_HIGH parser is structural: it recognises `### [CRITICAL]` / `### [HIGH]` headers, inline bullet tags (`- F-NNN [CRITICAL]`), and `Severity: CRITICAL` key-value fields. Bailed components are excluded from the implement queue and are not retried unless `--retry-bailed` is explicitly passed. When a component bails, `/z-uplift` runs `git grep` to surface potential dependents — but only when `OTHER_COMP_PATHS` is non-empty (guard added to prevent `git grep` receiving no path arguments).
- **Polyglot detection.** Auto-detection walks manifest files (Cargo.toml, pyproject.toml, package.json) to identify workspace members. It misses unconventional layouts. Use `--components=<file>` (a newline-separated list of component paths) as the escape hatch.
- **Phase 5 two-step handoff.** Phase 5 does NOT invoke `/z-implement-all` automatically. It prints the command, marks the component `[i] implementing` in MANIFEST, and exits. You run the command. When done, re-invoke `/z-uplift` to advance to the next component.
- **Cross-cutting skip.** Pass `--cross-cutting=skip` to omit Phase 2 entirely. Default is ON. Skipping saves significant time but misses global-task issues that cut across component boundaries.
- **Performance dimension.** The `perf` audit dimension is excluded by default to bound cost. Pass `--dimensions=correctness,cleanliness,design,perf` to include it.
- **Slug collision.** Two components with the identical basename trigger an AskUser at Phase 1 for disambiguation. The resolver loops until all collisions are cleared; a no-progress sanity counter aborts after 3 stalled iterations to prevent infinite loops. Custom slugs are validated against `^[a-z0-9]+(?:-[a-z0-9]+)*$` before being applied.
- **Cross-cutting row ordering.** The synthetic `<slug>-cross-cutting` component is inserted first in MANIFEST (as `[a] audited`) so that global-task API changes land before per-component cleanup. Phase 4 prints a callout when this row is present. Phase 5 always processes it first regardless of physical table position.
- **Cross-cutting parser drops.** The Phase 2 merge parser emits a `cross_cutting_findings_dropped` telemetry event for any bullets in consultant output that do not match the strict `G-NNN` / `C-NNN` / `R-NNN` prefix pattern. Watch for this in run logs if finding counts seem low.
- **Atomic MANIFEST writes.** All MANIFEST mutations use `os.replace(tmp, path)` (write to `.tmp` then rename) to prevent partial-write corruption on interrupt.
- **Phase telemetry.** Every phase records `T0` at entry and emits `phase_end` with `wall_ms` and `user_wait_ms` at exit. User wait time is tracked via `user_wait_start` / `user_wait_end` event pairs bracketing each `AskUserQuestion` call.
- **Doc-staleness gate.** Setup Step 5 checks `docs/llm/INDEX.json` staleness across all concepts before Phase 0. If more than 20% are stale (configurable via `$Z_HARNESS_DOC_STALENESS_THRESHOLD`), the user is prompted to switch to `/z-maintain-docs`, continue with stale docs, or abandon. The gate does NOT auto-invoke `/z-maintain-docs`.
- **Notification config var.** The correct environment variable for notification control is `Z_HARNESS_NOTIFY_LEVEL` (maps to `notify.level` in TOML). There is no standalone `Z_HARNESS_NOTIFY` variable. Setting `Z_HARNESS_NOTIFY` has no effect.

## Examples

```
# Full uplift on current repo (interactive, all phases)
/z-uplift

# Resume after interrupt (no flags needed — reads MANIFEST)
/z-uplift

# Skip the cross-cutting pass to speed up a known-clean repo
/z-uplift --cross-cutting=skip

# Proceed even if STYLE.md is absent
/z-uplift --no-style

# Re-attempt a previously bailed component
/z-uplift --retry-bailed

# Limit to specific components listed in a file
/z-uplift --components=my-components.txt

# Include an extra component not auto-detected
/z-uplift --component path/to/extra-component

# Re-run audit for a single component only
/z-uplift --refresh-component my-component-slug

# Include the perf dimension
/z-uplift --dimensions=correctness,cleanliness,design,perf
```
