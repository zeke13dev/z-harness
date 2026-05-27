# SPEC — C6: shipping

## Overview

Cluster C6 is responsible for releasing and distributing the new host-neutral runtime. It ports all existing `commands/z-*.md` files to the C1 runtime contract (template + bulk + acceptance, not one-task-per-command), freezes the legacy per-host Python exporter scripts under the one-minor-version deprecation cadence resolved in C6-D1, and refactors `install.sh`, `commands/z-update.md`, and `scripts/audit-tarball.sh` to package and update the new runtime binary + `runtime/` tree + `drivers/` tree alongside the frozen exporters during the transition window. C6 lands after C1 (runtime contract), at least one driver (C2/C3/C4), and C5 (conformance harness).

## Surface

Files this cluster owns:

- `commands/z-*.md` — all 28 command bodies (migrated in bulk)
- `commands/z-export.md` — gets a prominent deprecation-warning phase prepended
- `commands/z-update.md` — extended with runtime-mode detection, legacy-layout nudge, and atomic-swap for binary + trees
- `scripts/export-codex.py` — freeze: add deprecation warning + dated-cutover comment
- `scripts/export-agy.py` — freeze: add deprecation warning + dated-cutover comment
- `scripts/export-cursor.py` — freeze: add deprecation warning + dated-cutover comment
- `scripts/export-common.py` — freeze: add deprecation warning + dated-cutover comment (shared lib)
- `scripts/install.sh` — refactor: add runtime + drivers packaging + `--legacy` flag
- `scripts/audit-tarball.sh` — update allowlist: add new runtime paths, keep legacy paths for one minor version

## Non-goals

- C6 does NOT implement the runtime (`runtime/`) or any driver (`drivers/`) — those are C1/C2/C3/C4.
- C6 does NOT implement the conformance harness — that is C5. Acceptance task T003 invokes C5's suite; it does not build it.
- C6 does NOT update `docs/llm/multi-ide-exports.json` inline. A follow-up `/z-maintain-docs` call is scheduled in T005 as a deferred doc-sync task.
- C6 does NOT finalize a public release URL for tarball hosting — the placeholder `Z_HARNESS_RELEASE_URL` pattern stays; hooking a real CDN is out of scope.
- C6 does NOT modify any sibling-cluster files (runtime/, drivers/, conformance/) directly.

## Invariants

1. The legacy export scripts (`export-*.py`) must remain functional during the one-minor-version transition; they print a deprecation warning to stderr but exit 0 and produce the same output as before.
2. `--legacy` flag in `install.sh` works for exactly one minor version; implementation must include a dated comment marking the removal target.
3. `audit-tarball.sh` PASS criteria must not regress: all existing forbidden-pattern checks stay; new runtime paths are added to the allowlist; legacy export paths remain in the allowlist for one minor version.
4. Every migrated command (`commands/z-*.md`) must pass `conformance-harness` on at least one driver before the acceptance task (T003) closes.
5. `commands/z-update.md` emits `harness_updated` event on every successful update (symlink, tarball, and new runtime-binary modes).
6. Migration of command bodies must not break commands that were already working on Claude Code — the template must be validated against the existing Claude Code driver before bulk migration.

## Telemetry / events

- `harness_updated` — emitted by `z-update` with `{"mode": "<symlink|tarball|runtime>", "old_version": "...", "new_version": "..."}`.
- `migration_nudge` — emitted by `z-update` when legacy install layout is detected, payload `{"layout": "legacy", "action": "nudge"}`.
