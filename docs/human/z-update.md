# z-update

> Last updated: 2026-06-24
> Covers source: install.sh, scripts/bundle-plugin.sh, scripts/version.sh, skills/z-update/SKILL.md, docs/human/INSTALL.md

## Overview

`/z-update` refreshes an installed z-harness plugin in place. It locates the plugin root from environment variables or known install paths, classifies the install as `symlink`, `runtime`, or `tarball`, captures the old version stamp, runs the appropriate update path, captures the new version stamp, and emits a `harness_updated` event. It is explicit user-triggered maintenance; there is no automatic background update.

Symlink mode treats a symlink or git worktree as a live clone and runs `git pull --ff-only` after a dirty-tree preflight. Tarball and runtime modes use a download/extract/atomic-swap flow. Runtime mode is an extracted plugin containing `runtime/`; replacing the whole plugin dir updates `runtime/drivers/` along with commands, agents, skills, and scripts. The command also nudges legacy export-layout installs and refreshes Codex/Claude Code plugin caches after a symlink update so host plugin caches do not remain pinned to an old commit.

## Key entry points

- `skills/z-update/SKILL.md:10` — `/z-update` skill; plugin-root discovery, mode detection, update path, cache refresh, and telemetry.
- `skills/z-update/SKILL.md:64` — legacy layout detection: `exports/codex`, `exports/agy`, or `exports/cursor` without `runtime/` emits a migration nudge but does not block update.
- `skills/z-update/SKILL.md:204` — Codex cache refresh: reruns `codex plugin add z-harness@personal` after symlink update when marketplace metadata exists.
- `skills/z-update/SKILL.md:213` — Claude Code cache refresh: resolves installed `z-harness@<marketplace>`, updates marketplace, updates plugin cache, and verifies cached SHA against repo HEAD.
- `install.sh:126` — `install_claude_symlink()` — creates the Claude Code plugin symlink to a live repo.
- `install.sh:151` — `write_codex_marketplace()` — writes/updates the Codex personal marketplace entry.
- `install.sh:191` — `install_codex_symlink()` — creates the Codex plugin symlink and registers the plugin when Codex is available.
- `install.sh:225` — `install_legacy_exporters()` — deprecated transition path for frozen exporters when `--legacy` is passed.
- `install.sh:264` — `extract_tarball_to()` — downloads, extracts, handles single-top-dir tarballs, and atomically moves into place.
- `install.sh:305` / `install.sh:319` — tarball installers for Claude Code and Codex.
- `install.sh:341` / `install.sh:368` — target dispatch for repo and tarball installs.
- `scripts/bundle-plugin.sh:1` — builds distributable tarballs and deletes the tarball if audit fails.
- `scripts/version.sh:1` — emits version JSON with git SHA/dirty/branch/tag or non-git sentinel values.
- `docs/human/INSTALL.md:1` — installation guide for first-time installs and migration context.

## How it interacts with others

- `scripts/version.sh` — old/new version stamps for `harness_updated`.
- `scripts/log-event.sh` — `migration_nudge` and `harness_updated` events.
- Host plugin caches — Claude Code and Codex may load from extracted caches, not directly from the live repo, so cache refresh is part of successful symlink updates.
- Release packaging — tarball/runtime mode depends on tarballs produced by the bundle/audit pipeline.

## Edge cases / gotchas

- Dirty symlink worktrees abort before `git pull`; `/z-update` never stashes, resets, or force-merges.
- A git directory inside an extracted tarball would be classified as symlink mode because git worktree detection wins.
- The default tarball URL is a placeholder; tarball/runtime update requires `Z_HARNESS_RELEASE_URL` to point at a real release artifact.
- Runtime mode uses the same atomic full-directory swap as tarball mode; there is no separate runtime/drivers patch step.
- Claude Code cache refresh can silently no-op if the marketplace ref or version does not advance, so the command compares cached commit SHA with repo HEAD and warns if still stale.
- If `.claude-plugin/plugin.json` pins an explicit version, releases must bump it; omitting the version lets commit SHA invalidate the cache automatically.
- `install.sh --legacy` is deprecated and available only as a short transition path.
- `bundle-plugin.sh` excludes plans, archives, improvements, distribution outputs, repo-local providers, and legacy export trees from release tarballs.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-update.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
/z-update
Z_HARNESS_RELEASE_URL=https://releases.example.invalid/z-harness.tar.gz /z-update
bash install.sh --target=all
bash scripts/bundle-plugin.sh
```
