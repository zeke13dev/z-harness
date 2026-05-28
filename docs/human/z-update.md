# z-update

> Last updated: 2026-05-28
> Covers source: install.sh, scripts/bundle-plugin.sh, scripts/version.sh, commands/z-update.md, docs/human/INSTALL.md

## Overview

`/z-update` is a Claude Code slash command (and `z-update` Codex skill) that refreshes a z-harness install in-place. It detects how the plugin was installed — as a symlink pointing at a local git clone, as an extracted tarball, or as a runtime install (a directory containing `runtime/` but no `.git/`) — and takes the correct update path for each case without requiring a full reinstall.

The command is intentionally explicit: there is no autoupdate mechanism. Every update must be triggered by the user. This is by design for a tool that rewrites production code.

## Key entry points

- `commands/z-update.md:1` — `z-update` — slash command definition; orchestrates the full update flow from plugin-root discovery through event emission
- `install.sh:114` — `install_claude_symlink` — creates the `~/.claude/plugins/z-harness@zeke-tools` symlink; the install mode this sets up determines which update path `/z-update` later uses
- `install.sh:176` — `install_codex_symlink` — creates `~/plugins/z-harness` symlink and writes the personal marketplace entry; Codex also reruns `codex plugin add z-harness@personal` after symlink updates
- `install.sh:273` — `install_claude_tarball` — extracts a tarball into the Claude plugin location; tarball installs are later updated by `/z-update`'s atomic swap path
- `install.sh:284` — `install_codex_tarball` — extracts a tarball into the Codex plugin location and updates the marketplace JSON
- `install.sh:303` — `install_target_from_repo` — dispatches `install_claude_symlink` / `install_codex_symlink` / both based on `--target` flag
- `install.sh:330` — `install_target_from_tarball` — dispatches `install_claude_tarball` / `install_codex_tarball` / both based on `--target` flag
- `scripts/version.sh:1` — `version.sh` — emits a JSON blob with `z_harness_version` (git short SHA), `z_harness_dirty`, `z_harness_branch`, and optionally `z_harness_tag`; called before and after every update to capture old/new version for the `harness_updated` event
- `scripts/bundle-plugin.sh:1` — `bundle-plugin.sh` — builds the distributable `dist/z-harness-<version>.tar.gz`; excludes `.git/`, `exports/`, `plans/`, `archive/`, `providers.json`; runs `audit-tarball.sh` afterward and deletes the tarball on any audit violation

## How it interacts with others

- `scripts` — `version.sh` and `bundle-plugin.sh` live in the `scripts/` concept; `/z-update` shells out to `version.sh` to stamp old and new version, and `bundle-plugin.sh` produces the tarballs that the tarball update path downloads
- `commands` — `/z-update` is one entry in the broader commands concept; the plugin-root discovery logic mirrors the env-var resolution pattern used across all slash commands (`Z_HARNESS_PLUGIN_ROOT` → `ANTIGRAVITY_PLUGIN_ROOT` → `CLAUDE_PLUGIN_ROOT`)
- `plan-layout-migration` — the exclusion list in `bundle-plugin.sh` was expanded during the plan-layout migration to strip legacy `z-harness/<slug>/` plan dirs from release tarballs

## Edge cases / gotchas

- **Three install modes.** `/z-update` now classifies installs as `symlink` (the plugin path is a symlink, or `git rev-parse` succeeds inside it), `runtime` (a `runtime/` subdirectory is present but no git history), or `tarball` (everything else). Symlink mode uses `git pull --ff-only`; tarball and runtime modes use the atomic swap path.
- **Plugin root discovery order.** The command checks `Z_HARNESS_PLUGIN_ROOT`, then `ANTIGRAVITY_PLUGIN_ROOT`, then `CLAUDE_PLUGIN_ROOT`, then walks candidate paths (`~/plugins/z-harness`, `~/.claude/plugins/z-harness@zeke-tools`, `$(pwd)`). The first candidate with `scripts/version.sh` and `install.sh` wins. `version.sh` uses the same priority chain.
- **Dirty-tree abort in symlink mode.** If `git status --porcelain` is non-empty, `/z-update` prints `git status` output and halts. The user must commit or stash before re-running.
- **`--ff-only` pull.** If the local clone has diverged from the remote (e.g. local commits exist), `git pull --ff-only` fails. `/z-update` prints the error and tells the user to resolve manually — it never force-merges or resets.
- **Tarball mode requires a real release URL.** The placeholder `https://example.com/...` in `commands/z-update.md` is not a real endpoint. If `Z_HARNESS_RELEASE_URL` is unset and the URL still points to `example.com`, `/z-update` halts explicitly and asks the user to set the variable.
- **Atomic swap rollback.** In tarball/runtime mode, the old directory is moved aside before the new one moves in. If the `mv` into place fails, the old directory is restored. Either the old or new version is live at any moment — never a half-extracted state.
- **Codex cache after symlink update.** Codex snapshots plugin skills into its cache. After a symlink-mode update, `/z-update` reruns `codex plugin add z-harness@personal` (if `codex` is on PATH and `~/.agents/plugins/marketplace.json` exists) so the cache reflects the new version. A new Codex thread is required to pick up changed skills.
- **Symlink vs. git-in-dir detection.** The command treats a path as symlink-mode if the plugin dir is itself a symlink OR if running `git rev-parse --git-dir` inside it succeeds. An extracted tarball that happens to contain a `.git/` directory would be misclassified as symlink mode.
- **`bundle-plugin.sh` deletes the tarball on audit failure.** If `audit-tarball.sh` finds a violation (e.g. a `providers.json` slipped in), the tarball is deleted and the script exits non-zero. No partial artifact is left behind.
- **`--target` flag in `install.sh`.** The main dispatch in `install.sh` is now split into `install_target_from_repo` and `install_target_from_tarball`, each routing `claude`, `codex`, or `all` targets. The `--host` alias is also accepted.

## Examples

Symlink-mode update (standard case):

```
/z-update
# [z-update] old: {"z_harness_version":"abc1234",...}
# [z-update] Pulling latest from remote...
# [z-update] Updated successfully.
#   old: abc1234
#   new: def5678
```

Tarball-mode update with explicit release URL:

```bash
Z_HARNESS_RELEASE_URL=https://releases.example.com/z-harness/latest.tar.gz
/z-update
```

Building a release tarball:

```bash
bash scripts/bundle-plugin.sh
# -> dist/z-harness-v1.2.3.tar.gz (after passing audit)
```

Install for both Claude Code and Codex from a local clone:

```bash
bash install.sh --target=all
```
