# setup

> Last updated: 2026-06-24
> Covers source: scripts/setup.py, scripts/setup.sh, skills/z-setup/SKILL.md, docs/human/SETUP.md

## Overview

`setup` is the z-harness configuration cockpit. The public CLI entrypoint is `z-harness setup`: it detects supported harnesses, checks provider/auth CLIs, optionally installs Claude/Codex plugin targets, and points users to the next in-harness command. The in-harness `/z-setup` skill parses configuration forms and delegates all state inspection and writes to `scripts/setup.py`; the skill itself never edits configuration directly. `scripts/setup.py` supports `inspect` (default), `wizard`, `apply --posture <name>`, `explain <key>`, and `status`.

The CLI reads resolved configuration through `scripts/config.py inspect-all --json`, augments it with provider registry, persona, docs, memory, and axiom status, then renders either JSON, flat `key=value` rows, grouped human-readable sections, or a one-line status. Writes are limited to posture application and wizard final review, both performed through `config.py set`. Posture presets are hardcoded as `interactive`, `overnight`, and `ci-batch`; env-only settings are printed as shell snippets instead of being persisted.

## Key entry points

- `skills/z-setup/SKILL.md:1` — `/z-setup` command surface; parses user arguments, shells out to `scripts/setup.py`, gates posture application with `AskUserQuestion`, and emits `setup_skill_start/end`.
- `z_harness_cli/commands/setup.py:1` — public first-run setup command; detects Claude/OMP/Cursor/Codex, provider CLIs, optional posture application, and first-class Claude/Codex plugin install handoff.
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

## Edge cases / gotchas

- The `/z-setup` skill's `apply` form always runs a dry run first; a dry-run failure prevents any write.
- `cmd_apply --yes` bypasses CLI confirmation and is intended only when consent was established by the caller.
- The wizard's providers, personas, docs, and memories sections are mostly inspect/suggest surfaces; provider discovery, docs initialization, and memory authoring remain separate commands.
- `POSTURE_PRESETS` env values are emitted for the shell to source; they are not written to TOML.
- `_detect_posture()` is heuristic: partial matches return `custom`.
- Scope names are lowercase; a capitalized `--scope` value exits with a usage error.
- On macOS, robust deadline enforcement prefers GNU `timeout`/`gtimeout` from coreutils; the watchdog has a bash fallback but setup documents the dependency.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/setup.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```bash
z-harness setup --target all --dry-run
z-harness setup --target all --install
/z-setup
/z-setup wizard --scope providers
/z-setup apply --posture interactive
/z-setup status
```
