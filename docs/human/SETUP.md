# setup

> Last updated: 2026-07-09
> Covers source: scripts/setup.py, scripts/setup.sh, skills/z-setup/SKILL.md, docs/human/SETUP.md

## Overview

`setup` is the z-harness configuration cockpit. The public CLI entrypoint is `z-harness setup` (`z_harness_cli/commands/setup.py`, wired via `z_harness_cli/__main__.py`): it detects supported harnesses through `z_harness_cli/release_surface.py`'s prod/dev-advanced split, checks provider/auth CLIs, optionally installs Claude/Codex plugin targets, optionally applies a posture preset, and points users to the next in-harness command. The in-harness `/z-setup` skill parses configuration forms and delegates all state inspection and writes to `scripts/setup.py`; the skill itself never edits configuration directly. `scripts/setup.py` supports `inspect` (default), `wizard`, `apply --posture <name>`, `explain <key>`, and `status`.

The CLI reads resolved configuration through `scripts/config.py inspect-all --json`, augments it with provider registry, persona, docs, memory, and axiom status, then renders either JSON, flat `key=value` rows, grouped human-readable sections, or a one-line status. Writes are limited to posture application and wizard final review, both performed through `config.py set`. Posture presets are hardcoded as `interactive`, `overnight`, and `ci-batch`; env-only settings are printed as shell snippets instead of being persisted. On the public CLI side, `z-harness setup` now gates which harnesses it surfaces by release surface: `prod` shows only Claude/OMP/Codex by default (public-release hosts), while `pi` and `cursor` are dev/advanced explicit targets that only appear when named directly or when the surface resolves to non-prod.

## Key entry points

- `skills/z-setup/SKILL.md:1` — `/z-setup` command surface; parses user arguments, shells out to `scripts/setup.py`, gates posture application with `AskUserQuestion`, and emits `setup_skill_start/end`.
- `z_harness_cli/__main__.py:53` — `setup_cmd()` — Typer command registration for `z-harness setup`; declares `--target/--host`, `--install`, `--force`, `--posture`, `--dry-run`, `--yes` and forwards to `z_harness_cli/commands/setup.py:run()`.
- `z_harness_cli/commands/setup.py:158` — `run()` — public first-run setup command; detects harnesses via `_detect_hosts()`, prints provider/auth CLI status, optionally applies a posture preset through `scripts/setup.py apply`, and optionally hands off to plugin install.
- `z_harness_cli/commands/setup.py:55` — `_detect_hosts()` — release-surface-aware harness detection; filters to public-release hosts in `prod` surface unless a dev/advanced target (`pi`, `cursor`) is explicitly selected.
- `z_harness_cli/commands/setup.py:43` — `_normalize_targets()` — resolves `--target all` / comma-separated target strings against `release_surface.setup_target_ids()`; rejects unknown targets with exit code 2.
- `scripts/setup.py:1913` — `main()` — top-level parser dispatching to inspect, wizard, apply, explain, and status handlers.
- `scripts/setup.py:42` — `_inspect_all_json()` — subprocess call to `config.py inspect-all --json`; common read path for inspect, wizard, apply, and status.
- `scripts/setup.py:439` — `cmd_inspect()` — read-only inspect entry; selects JSON, flat, or grouped output.
- `scripts/setup.py:634` — `_cmd_inspect_grouped()` — renders the concern sections: notifications, workflow, overnight, providers, personas, docs, memories, and axioms.
- `scripts/setup.py:268` — `POSTURE_PRESETS` — built-in posture targets for interactive, overnight, and CI batch usage.
- `scripts/setup.py:1525` — `cmd_wizard()` — concern-grouped guided flow; `--scope` limits to one section and wizard section events are logged.
- `scripts/setup.py:1597` — `cmd_apply()` — computes posture diff, confirms unless `--yes`, writes via `config.py set`, and emits `setup_apply_done`.
- `scripts/setup.py:1122` — `_install_kernel_pointer()` — idempotently installs the z-harness kernel-pointer marker in `~/.claude/CLAUDE.md` and collapses duplicate blocks.
- `scripts/setup.py:1219` — `_ensure_gitignore_entry()` — idempotently adds `.z-harness/axioms/` and `.z-harness/KERNEL.md` entries when the axiom wizard asks for them.
- `scripts/setup.sh:1` — thin wrapper that execs `python3 setup.py`.
- `docs/human/SETUP.md:1` — user-facing setup guide.

## How it interacts with others

- `config` — `setup.py` delegates all effective-state reads and persistent writes to `scripts/config.py`.
- `providers-registry` — inspect/status/provider wizard sections read provider bindings and direct users to `/z-providers-discover` if roles are missing.
- `docs` — docs initialization is detected by `docs/llm/INDEX.json`; setup suggests `/z-init-docs` but does not run it.
- `axioms` — the axiom wizard configures axiom keys, installs the global kernel pointer, and offers `.gitignore` entries for generated kernel files.
- `z_harness_cli/release_surface.py` (undocumented as its own concept as of this refresh) — the public `z-harness setup` command now depends on it for target enumeration (`setup_target_ids`, `explicit_setup_target_ids`), public-host filtering (`public_release_hosts`), and prod/dev-advanced surface resolution (`default_surface`); this is new since the last doc refresh and has no dedicated `docs/llm/*.json` entry yet.

## Edge cases / gotchas

- The `/z-setup` skill's `apply` form always runs a dry run first; a dry-run failure prevents any write.
- `cmd_apply --yes` bypasses CLI confirmation and is intended only when consent was established by the caller.
- The wizard's providers, personas, docs, and memories sections are mostly inspect/suggest surfaces; provider discovery, docs initialization, and memory authoring remain separate commands.
- `POSTURE_PRESETS` env values are emitted for the shell to source; they are not written to TOML.
- `_detect_posture()` is heuristic: partial matches return `custom`.
- Scope names are lowercase; a capitalized `--scope` value exits with a usage error.
- On macOS, robust deadline enforcement prefers GNU `timeout`/`gtimeout` from coreutils; the watchdog has a bash fallback but setup documents the dependency.
- `z-harness setup` (public CLI) now filters detected harnesses by release surface: in a `prod` surface only Claude/OMP/Codex are shown by default; `pi` is always export-only (no local binary probe) and `cursor`/`pi` only surface when explicitly selected via `--target` or when the surface is non-prod.
- `_run_plugin_install()` in `z_harness_cli/commands/setup.py` shells out to the `install` command module lazily (imported inside the function) to avoid import cost when `--install` is not passed.
- `run()` only calls `scripts/setup.py apply` when `--posture` is given; without it, the CLI prints the detected plan and next steps only — it never silently mutates configuration.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/setup.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
z-harness setup --target all --dry-run
z-harness setup --target all --install
z-harness setup --target pi --dry-run
/z-setup
/z-setup wizard --scope providers
/z-setup apply --posture interactive
/z-setup status
```
