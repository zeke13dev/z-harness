# z-update

> Last updated: 2026-06-03
> Covers source: install.sh, scripts/bundle-plugin.sh, scripts/version.sh, commands/z-update.md, docs/human/INSTALL.md

## Overview

`/z-update` is a Claude Code slash command (and `z-update` skill for Codex and Antigravity) that refreshes a z-harness install in-place. It detects how the plugin was installed — as a symlink pointing at a live git clone, as a runtime install (a directory containing `runtime/` but no `.git/`), or as an extracted tarball — and takes the correct update path for each case without requiring a full reinstall. The command is intentionally explicit: there is no autoupdate mechanism. Every update must be triggered by the user, which is by design for a tool that rewrites production code.

`install.sh` is the counterpart script that performs first-time installation for Claude Code, Codex, or both simultaneously (`--target=all`). It supports symlink mode (for contributors keeping a live clone), tarball mode (for stable versioned deploys from a release URL), and a `--legacy` flag that copies frozen `scripts/export-*.py` exporters alongside the standard install. The `--legacy` flag is deprecated and will be removed in the next minor release. A `bundle-plugin.sh` script in `scripts/` produces the distributable tarballs; it uses `version.sh` to stamp the output filename and passes every output through `audit-tarball.sh` before finalizing.

## Key entry points

<!-- AUTO-START: entry-points -->
- `commands/z-update.md:1` — `z-update` — slash command definition; orchestrates plugin-root discovery, mode detection (symlink/runtime/tarball), pull or atomic-swap, legacy-layout nudge, and `harness_updated` event emission
- `install.sh:114` — `install_claude_symlink` — creates `~/.claude/plugins/z-harness@zeke-tools -> <repo>` symlink; requires `.git + commands/ + agents/ + runtime/`
- `install.sh:136` — `write_codex_marketplace` — writes or updates `~/.agents/plugins/marketplace.json` with the z-harness personal marketplace entry
- `install.sh:176` — `install_codex_symlink` — creates `~/plugins/z-harness` symlink, calls `write_codex_marketplace`, and runs `codex plugin add z-harness@personal` if `codex` is on PATH
- `install.sh:207` — `install_legacy_exporters` — copies `scripts/export-*.py` files into the tarball destination; only called when `--legacy` is passed; deprecated
- `install.sh:232` — `extract_tarball_to` — downloads a release tarball (via curl or wget), extracts it to a temp dir, handles single-top-dir tarballs, then atomically moves to the destination
- `install.sh:273` — `install_claude_tarball` — extracts tarball into Claude plugin location; optionally installs legacy exporters
- `install.sh:284` — `install_codex_tarball` — extracts tarball into Codex plugin location, calls `write_codex_marketplace`, and registers with `codex plugin add`
- `install.sh:303` — `install_target_from_repo` — dispatches `--target=claude|codex|all` to the appropriate symlink installer function
- `install.sh:330` — `install_target_from_tarball` — dispatches `--target=claude|codex|all` to the appropriate tarball installer function
- `scripts/version.sh:1` — `version.sh` — emits a JSON blob with `z_harness_version` (git short SHA), `z_harness_dirty`, `z_harness_branch`, and optionally `z_harness_tag`; resolves plugin dir via `Z_HARNESS_PLUGIN_ROOT` → `ANTIGRAVITY_PLUGIN_ROOT` → `CLAUDE_PLUGIN_ROOT` → script-relative parent; emits sentinel values (`non-git`, `unknown`) rather than failing when no git history is present
- `scripts/bundle-plugin.sh:1` — `bundle-plugin.sh` — builds `dist/z-harness-<version>.tar.gz`; excludes `.git/`, `exports/`, `z-harness/plans/`, `z-harness/archive/`, `z-harness/improvements/`, `dist/`, `.z-harness/`, `__pycache__/`, `providers.json`, and auto-detected legacy plan dirs; runs `audit-tarball.sh` and deletes the tarball on any violation
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `scripts` — `version.sh` and `bundle-plugin.sh` live in the `scripts` concept; `/z-update` shells out to `version.sh` before and after every update to stamp old/new version in the `harness_updated` event
- `commands` — `/z-update` is one of the slash commands; the plugin-root discovery order (`Z_HARNESS_PLUGIN_ROOT` → `ANTIGRAVITY_PLUGIN_ROOT` → `CLAUDE_PLUGIN_ROOT` → candidate paths) mirrors the env-var resolution pattern used across the command set
- `plan-layout-migration` — `bundle-plugin.sh`'s exclusion list was expanded during plan-layout migration; it now scans `z-harness/<slug>/` at bundle time and auto-excludes any directory containing `PLAN.md`, `SPEC.md`, or `TASKS.md`
- `multi-ide-exports` — exported Codex and Antigravity prompts in `exports/` are excluded from the distributable tarball; the `--legacy` flag provides a transition path for users depending on the frozen `export-*.py` scripts

## Edge cases / gotchas

- **Three install modes.** The command classifies installs as `symlink` (plugin path is a symlink, or `git rev-parse` succeeds inside it), `runtime` (a `runtime/` subdirectory is present but no git history), or `tarball` (everything else). Symlink mode uses `git pull --ff-only`; tarball and runtime modes use the atomic swap path.
- **Runtime mode added.** The `runtime` mode is distinct from the old two-mode model. A runtime install contains `runtime/drivers/` but no `.git/`. The atomic swap replaces the full plugin dir, so the `runtime/` tree is updated wholesale.
- **Legacy layout detection.** If `exports/codex`, `exports/agy`, or `exports/cursor` exist in the plugin dir but `runtime/` does not, `/z-update` emits a `migration_nudge` telemetry event and prints a one-line prompt to re-run `install.sh`. The update still proceeds normally.
- **Plugin root discovery order.** Checks `Z_HARNESS_PLUGIN_ROOT`, then `ANTIGRAVITY_PLUGIN_ROOT`, then `CLAUDE_PLUGIN_ROOT`, then walks candidate paths (`~/plugins/z-harness`, `~/.claude/plugins/z-harness@zeke-tools`, `$(pwd)`). The first candidate with both `scripts/version.sh` and `install.sh` wins.
- **Dirty-tree abort in symlink mode.** If `git status --porcelain` is non-empty, `/z-update` prints the status and halts. The user must commit or stash before re-running.
- **`--ff-only` pull.** If the local clone has diverged (e.g. local commits exist), `git pull --ff-only` fails. `/z-update` prints the error and tells the user to resolve manually — it never force-merges or resets.
- **Tarball mode requires a real release URL.** The placeholder `https://example.com/...` in `commands/z-update.md` is not a real endpoint. If `Z_HARNESS_RELEASE_URL` is unset and the URL still points to `example.com`, `/z-update` halts and asks the user to set the variable.
- **Atomic swap rollback.** In tarball/runtime mode, the old directory is moved aside before the new one moves in. If the second `mv` fails, the old directory is restored. Either the old or new version is live at any moment — never a half-extracted state.
- **Codex cache after symlink update.** After a symlink-mode update, `/z-update` reruns `codex plugin add z-harness@personal` (if `codex` is on PATH and `~/.agents/plugins/marketplace.json` exists). A new Codex thread is still required to pick up changed skills.
- **Symlink vs. git-in-dir detection.** The command treats a path as symlink-mode if the plugin dir is itself a symlink OR if `git rev-parse --git-dir` succeeds inside it. An extracted tarball that happens to contain a `.git/` directory would be misclassified as symlink mode.
- **`--legacy` flag is deprecated.** `install.sh --legacy` copies frozen `scripts/export-*.py` files to the install destination. It is available for one minor release only and will be removed at the next minor version bump (`REMOVE-AT: v<next-minor>`). In symlink mode, `--legacy` is a no-op (the repo symlink already exposes the scripts) but still prints a deprecation notice.
- **`bundle-plugin.sh` deletes the tarball on audit failure.** If `audit-tarball.sh` finds a violation, the tarball is deleted and the script exits non-zero. No partial artifact is left behind.
- **`install.sh` `--target=all` requires both layouts.** Claude needs `.git + commands/ + agents/ + runtime/`; Codex needs `.git + .codex-plugin/plugin.json + skills/`. Both must be satisfied when `--target=all` is used.

## Examples

Symlink-mode update (standard case):

```
/z-update
# [z-update] old: {"z_harness_version":"abc1234",...}
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

Install from a tarball URL with legacy exporter transition support:

```bash
bash install.sh --target=claude --tarball=https://... --legacy
```
