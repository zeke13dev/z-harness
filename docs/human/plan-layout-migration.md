# Plan Layout Migration

> Last updated: 2026-06-24
> Covers source: scripts/plan-path.sh, scripts/migrate-plan-layout.sh, scripts/log-event.sh, docs/human/PLAN-LAYOUT.md

## Overview

All z-harness plan artifacts resolve under an external artifact base directory, returned by `z_harness_base()` in `scripts/plan-path.sh`. The base follows a 5-tier fallback chain: an explicit `Z_HARNESS_BASE_DIR` env var (tier 1, escape hatch), then `$XDG_STATE_HOME/z-harness/<repo-id>` (tier 2), then `$HOME/.local/state/z-harness/<repo-id>` (tier 3), then `<git-common-dir>/z-harness` (tier 4), then `$(pwd)/z-harness` (tier 5, last resort). The external tiers are active by default (`Z_HARNESS_EXTERNAL_DEFAULT` unset equals 1), meaning plans are stored outside the repo worktree and survive a `git clean`. Set `Z_HARNESS_EXTERNAL_DEFAULT=0` to revert to the old in-repo tier-5 behavior.

Within the chosen base the directory structure is: `<base>/plans/<slug>/` for plan artifacts, `<base>/active-plans/` for the coordination registry, `<base>/active-plans/claims/` for per-slug claim lock files, `<base>/followups/` for the follow-up queue, and `<base>/metrics.jsonl` for the aggregate event log. A `<git-common-dir>/.z-harness-base` anchor file locks tiers 2-5 to a single resolved path (split-brain guard); any mismatch is a hard fatal. Tier-1 explicit `Z_HARNESS_BASE_DIR` bypasses the anchor entirely so CI and benchmark environments can relocate artifacts without conflicting with a developer machine's pre-existing anchor.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/plan-path.sh:9` — `z_harness_repo_id` — stable `<basename>-<8hex>` identifier from `git-common-dir` SHA-256; identical across all worktrees of one repo
- `scripts/plan-path.sh:52` — `_z_harness_probe_writable` — non-littering writability probe; creates and removes temp tree without side effects
- `scripts/plan-path.sh:112` — `_z_harness_anchor_write` — atomic tmpfile+rename anchor creation; validates on existing anchor, no-ops on tier-1
- `scripts/plan-path.sh:178` — `z_harness_base` — 5-tier base resolver with anchor enforcement; source-loop guard via `_Z_HARNESS_RESOLVING_BASE`
- `scripts/plan-path.sh:287` — `_z_harness_emit_base_resolved` — emits `base_resolved` event at most once per process (per-PID stamp); guarded by `_Z_HARNESS_RESOLVING_BASE` sentinel
- `scripts/plan-path.sh:317` — `z_harness_base_override` — validates and returns `Z_HARNESS_BASE_DIR` or empty; exits on non-absolute
- `scripts/plan-path.sh:331` — `base_dir` — alias for `z_harness_base`; used in diagnostics and stats
- `scripts/plan-path.sh:337` — `active_plans_dir` — returns `<base>/active-plans`; propagates `z_harness_base` failures
- `scripts/plan-path.sh:346` — `claims_dir` — returns `<base>/active-plans/claims`; holds per-slug claim lock files for the hard plan-claim mutex
- `scripts/plan-path.sh:355` — `followups_dir` — returns `<base>/followups`; propagates `z_harness_base` failures
- `scripts/plan-path.sh:375` — `plan_dir` — `<base>/plans/<slug>` with `Z_HARNESS_PLANS_DIR` override; enforces absolute constraint when `Z_HARNESS_BASE_DIR` is also set
- `scripts/plan-path.sh:413` — `legacy_plan_dir` — returns `z-harness/<slug>` (flat legacy path)
- `scripts/plan-path.sh:425` — `legacy_plan_dir_secondary` — returns `z-harness/plans/<slug>` (in-repo plans/ legacy path)
- `scripts/plan-path.sh:438` — `resolve_plan_path` — dual-read: tries new path first, then `z-harness/plans/<slug>`, then `z-harness/<slug>`; emits deprecation warning (once per parent PID)
- `scripts/plan-path.sh:482` — `all_plan_slugs` — deduplicated slugs from both new layout and legacy flat under the resolved base
- `scripts/migrate-plan-layout.sh:121` — `canonicalize_path` — resolves paths via Python3 realpath; exits on unresolvable path; prevents self-migration false-negative
- `scripts/migrate-plan-layout.sh:167` — `detect_live_runs` — queries active-plan registry for `status:running`; exits on liveness query failure
- `scripts/migrate-plan-layout.sh:283` — `emit_event` — emits `plan_migrated` event via log-event.sh if available and `Z_HARNESS_RUN_ID` is set
- `scripts/migrate-plan-layout.sh:299` — `safe_move` — copy -> byte-verify -> mtime-verify -> rm; refuse-on-conflict; idempotent
- `scripts/migrate-plan-layout.sh:370` — `merge_metrics` — dedup-append of `metrics.jsonl`; idempotent across crash/re-run
- `scripts/migrate-plan-layout.sh:485` — `migrate_plan_slug` — migrates one slug from both legacy sources to `<base>/plans/<slug>`
- `scripts/migrate-plan-layout.sh:612` — `migrate_full` — full migration: all plan slugs, archive, metrics, followups, flat TASKS.md, empty-dir cleanup
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `active-plan-registry` — `active_plans_dir()` and `claims_dir()` feed the registry's storage paths; `migrate-plan-layout.sh` calls `active-plan-registry.py list --json` for the live-run barrier before any real move
- `plan-claim` — `claims_dir()` returns the directory where per-slug claim lock files live; this is the hard mutex used by `/z-plan` and `/z-audit-plan` to prevent concurrent runs on the same slug
- `scripts` — `log-event.sh` sources `plan-path.sh` to route events and metrics under the resolved base; source-loop guard (`_Z_HARNESS_RESOLVING_BASE`) prevents infinite recursion when `z_harness_base()` tries to emit `base_resolved`
- `followup-sink` — `followups_dir()` from plan-path.sh is the canonical path for the follow-up queue; `migrate-plan-layout.sh` skips followups by default (`--with-followups` opts in) to avoid stranding in-flight locks
- `commands` — every command that constructs plan-relative paths sources or invokes `plan-path.sh` helpers; inline `z-harness/` literals are a DRY violation and fail the command-coverage audit

## Edge cases / gotchas

- `Z_HARNESS_BASE_DIR` must be an absolute path. A relative value causes an immediate `exit 1` in `z_harness_base()` and `z_harness_base_override()`.
- When both `Z_HARNESS_BASE_DIR` and `Z_HARNESS_PLANS_DIR` are set, `Z_HARNESS_PLANS_DIR` must also be absolute, otherwise `plan_dir()` exits 1 to prevent repo-local writes that would defeat the base override guarantee.
- Tier-1 (`Z_HARNESS_BASE_DIR`) bypasses the anchor entirely — no read, no write, no validate. This is intentional: it is the CI/benchmark escape hatch. The developer's anchor is not touched.
- The `base_resolved` telemetry event is emitted at most once per process (per-PID stamp file) and only when `Z_HARNESS_RUN_ID` is set and `_Z_HARNESS_RESOLVING_BASE` is not set, preventing recursive log-event.sh invocations.
- `migrate-plan-layout.sh --dry-run` still runs the live-run barrier check and warns on active runs; the preview is always produced even when a real migration would refuse.
- `metrics.jsonl` is the only item where a non-empty target does not cause a skip: lines are dedup-appended (crash-safe: source lines already present in the target are not duplicated on re-run).
- `followups/` migration is opt-in via `--with-followups`. Default behavior is to leave it in place because the follow-up queue lock paths resolve dynamically via `followups_dir()`, so an in-repo followups directory continues to work.
- `all_plan_slugs()` excludes the infrastructure names `plans`, `archive`, `adhoc`, `followups`, `improvements`, `active-plans`, `metrics.jsonl`, and `bench`.
- The `--slug NAME` flag is required to migrate a flat `z-harness/TASKS.md` (no-slug layout); without it the file is skipped with a loud warning.
- Archiving a session worktree that still holds in-repo z-harness state permanently discards those logs. `migrate-plan-layout.sh` refuses while a run is `status:running` (invariant 8) and skips on a non-empty target. Use `rescue-worktree-state.sh` instead — it COPIES (never moves) the worktree's `plans/`, `archive/`, `improvements/`, `adhoc/`, and `metrics.jsonl` to the external base with no live-run barrier, displaced destination files are preserved as `*.pre-rescue`, and `metrics.jsonl` is dedup-appended. It never copies `active-plans/` (would create a zombie `running` record), `*.lock`, or `followups/`. Run it from inside the worktree before archiving.
- `rescue-worktree-state.sh` refuses if the resolved external base is still inside the repo (external base disabled) — it would have nowhere durable to rescue to.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/plan-layout-migration.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
# Preview full migration without changes
bash scripts/migrate-plan-layout.sh --dry-run --all

# Migrate a single plan slug
bash scripts/migrate-plan-layout.sh my-feature-slug

# Migrate everything including followups
bash scripts/migrate-plan-layout.sh --all --with-followups

# Migrate flat TASKS.md (no-slug layout) to a named slug
bash scripts/migrate-plan-layout.sh --all --slug my-old-plan

# Force an external base for CI/benchmark (bypasses anchor)
Z_HARNESS_BASE_DIR=/tmp/bench-artifacts /z-plan my-task

# Revert to in-repo layout (opt-out of external default)
Z_HARNESS_EXTERNAL_DEFAULT=0 /z-plan my-task

# Query the resolved base directory
bash scripts/plan-path.sh z_harness_base

# Get the canonical plan directory for a slug
bash scripts/plan-path.sh plan_dir my-feature-slug

# Get the claims directory (for plan-claim hard mutex)
bash scripts/plan-path.sh claims_dir

# Rescue in-repo state out to the external base BEFORE archiving a session worktree
# (run from inside the worktree; works even while a run is live)
bash scripts/rescue-worktree-state.sh --dry-run    # preview what would be copied
bash scripts/rescue-worktree-state.sh              # copy; in-repo source left intact
```
