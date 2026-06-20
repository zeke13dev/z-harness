# setup

> Last updated: 2026-06-19
> Covers source: scripts/setup.py, scripts/setup.sh, commands/z-setup.md, docs/human/SETUP.md

## Overview

The `setup` concept is the single-entry-point configuration cockpit for z-harness. It provides four modes of operation: `inspect` (read-only view of all resolved configuration surfaces), `wizard` (interactive concern-grouped flow that walks the user through each section), `apply` (one-shot posture preset bootstrap), `explain` (per-key resolution detail), and `status` (compact one-line summary). All writes are delegated to `scripts/config.py set`; `setup.py` itself never writes TOML directly except via that subprocess.

The concept spans eight configuration surfaces: global TOML (`~/.config/z-harness/config.toml`), repo TOML (`.z-harness/config.toml`), env-only knobs, `providers.json`, personas directories, `docs/llm/INDEX.json`, routing-preference memories in `docs/llm/*.json`, and posture presets hardcoded in `POSTURE_PRESETS`. Config precedence (highest wins): env > repo TOML > global TOML > defaults. The `/z-setup` skill in `commands/z-setup.md` is the slash-command surface; it shells out to `scripts/setup.py` and uses `AskUserQuestion` for the apply confirmation gate.

## Key entry points

- `scripts/setup.py:1913` — `main` — Top-level CLI entry; dispatches to `cmd_inspect`, `cmd_wizard`, `cmd_apply`, `cmd_explain`, or `cmd_status` based on parsed subcommand
- `scripts/setup.py:439` — `cmd_inspect` — Inspect subcommand; delegates to `--json`, `--flat`, or concern-grouped view; always read-only
- `scripts/setup.py:455` — `_cmd_inspect_json` — Machine-parseable JSON output of all resolved config keys with `source`, `strength`, and `persistence_class`
- `scripts/setup.py:572` — `_cmd_inspect_flat` — Flat `key=value` with source column (git-config style); `--flat` flag
- `scripts/setup.py:634` — `_cmd_inspect_grouped` — Default concern-grouped inspect view; 8 sections: notifications, workflow, overnight, providers, personas, docs, memories, axioms
- `scripts/setup.py:1525` — `cmd_wizard` — Guided concern-grouped flow; `--scope` limits to one section; emits `wizard_section_start`/`wizard_section_end` events
- `scripts/setup.py:1597` — `cmd_apply` — One-shot posture-preset bootstrap; computes diff, confirms, writes keys via `config.py set`; emits `setup_apply_done`
- `scripts/setup.py:1700` — `cmd_explain` — Pure pass-through to `scripts/config.py explain <key>`
- `scripts/setup.py:1719` — `_detect_posture` — Heuristically identifies which posture the current config matches; returns preset name, `"none"`, or `"custom"`
- `scripts/setup.py:1766` — `cmd_status` — Compact one-line summary: `posture=<name>, providers=<bound|none>, docs=<initialized|missing>, prefs=<N> standing`
- `scripts/setup.py:42` — `_inspect_all_json` — Core read helper: calls `config.py inspect-all --json` and parses JSON; used by inspect, wizard, apply, and status
- `scripts/setup.py:268` — `POSTURE_PRESETS` — Hardcoded dict of posture name -> `{toml: {key: value}, env: {VAR: value}}`; three presets: `interactive`, `overnight`, `ci-batch`
- `scripts/setup.py:308` — `_compute_posture_diff` — Computes diff between posture target and current effective config; returns `will_change`, `unchanged`, `env_to_emit`
- `scripts/setup.py:1303` — `_wizard_axioms` — Axioms wizard section: configure `axioms.*` TOML keys, install kernel-pointer in `~/.claude/CLAUDE.md`, offer `.gitignore` entries
- `scripts/setup.py:1122` — `_install_kernel_pointer` — Idempotently install the canonical `<!-- z-harness-kernel-pointer BEGIN/END -->` block into CLAUDE.md; shows diff on mismatch; collapses duplicate blocks
- `scripts/setup.py:1219` — `_ensure_gitignore_entry` — Idempotently add a single entry to `.gitignore`; returns `added|already_present|error:<msg>`
- `scripts/setup.sh:1` — `setup.sh` — Thin bash wrapper: `exec python3 setup.py "$@"`
- `commands/z-setup.md:1` — `/z-setup` — Slash-command surface; parses invocation form, shells out to `setup.py`, uses `AskUserQuestion` for apply confirmation

## How it interacts with others

- `config` — `setup.py` reads all config state via `config.py inspect-all --json` (subprocess); writes via `config.py set --scope global|project`; never duplicates config logic
- `providers-registry` — `setup.py inspect` and `wizard providers` read `providers.json` via `_find_providers_json`; if roles are missing, the user is directed to run `/z-providers-discover`
- `axioms` — `_wizard_axioms` section configures `axioms.enabled`, `axioms.auto_extract_post_run`, `axioms.kernel_budget_chars`; installs the kernel-pointer block in `~/.claude/CLAUDE.md`; adds `.z-harness/axioms/` and `.z-harness/KERNEL.md` to `.gitignore`

## Edge cases / gotchas

- `_inspect_all_json` delegates to `config.py inspect-all` via subprocess; if `config.py` is unavailable or the subcommand is unregistered, it returns `None` and all subcommands fail gracefully with a warning
- Wizard sections for providers and docs are suggest-only: they detect gaps and print a tip to run `/z-providers-discover` or `/z-init-docs` but do NOT invoke those commands themselves
- The memories wizard section is read-only display only; all memory writes go through `/z-suggest-memory`
- `POSTURE_PRESETS` env vars are emitted as a shell snippet to stdout (or `--env-file`); they are never written to any config file
- `cmd_apply --yes` skips the confirmation prompt; use only in automation where user consent is established upstream
- The overnight posture snippet sets `Z_HARNESS_NO_ASK=halt`; this activates overnight mode globally for the shell session and is mutually exclusive with `Z_HARNESS_ASK_ALL=1`
- `cmd_explain` is a pure pass-through to `config.py explain`; it adds no logic of its own
- `_detect_posture` is heuristic: a config that partially matches a preset returns `"custom"`, not the preset name; it is not authoritative
- `_wizard_axioms` kernel-pointer install targets `~/.claude/CLAUDE.md` (global user file); it does NOT update per-repo CLAUDE.md files
- The axioms wizard scope surfaces four env-only knobs (`Z_HARNESS_AXIOMS_ENABLED`, `Z_HARNESS_AXIOMS_KERNEL_BUDGET_CHARS`, `Z_HARNESS_AXIOMS_EXTRACT_MIN_RECURRENCE`, `Z_HARNESS_AXIOMS_AUTO_EXTRACT_POST_RUN`) that are NOT in the core `ENV_ONLY_KNOBS` list in `config.py`; they appear only in `_SCOPE_ENV_KNOBS['axioms']`
- Wizard `--scope` values are matched lowercase; passing a capitalized scope name fails with exit code 2
- `setup.py apply --dry-run` exits 0 after printing the diff with no writes; `apply --yes` skips user confirmation
- `_install_kernel_pointer` collapses multiple duplicate marker blocks (from e.g. an interrupted prior run) into one canonical block after user confirmation

## Examples

```bash
# Inspect all surfaces (human-readable grouped view)
python3 scripts/setup.py inspect

# Flat git-config-style view
python3 scripts/setup.py inspect --flat

# Machine-parseable JSON
python3 scripts/setup.py inspect --json

# Run the full wizard
python3 scripts/setup.py wizard

# Run only the axioms section
python3 scripts/setup.py wizard --scope axioms

# Show what the overnight posture would change (no writes)
python3 scripts/setup.py apply --posture overnight --dry-run

# Apply interactive preset with confirmation
python3 scripts/setup.py apply --posture interactive

# Compact status line
python3 scripts/setup.py status
# z-harness: posture=interactive, providers=bound, docs=initialized, prefs=2 standing

# Explain a key
python3 scripts/setup.py explain notify.level
```
