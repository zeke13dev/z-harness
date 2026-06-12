# Multi IDE Exports

> Last updated: 2026-06-11
> Covers source: runtime/drivers/cursor/export.py, runtime/drivers/codex/export.py, runtime/drivers/antigravity/export.py, runtime/drivers/pi/export.py, scripts/audit-tarball.sh, commands/z-export.md, exports/cursor/CAPABILITIES.md, exports/codex/CAPABILITIES.md, exports/agy/CAPABILITIES.md, exports/pi/CAPABILITIES.md

## Overview

The multi-IDE export pipeline translates z-harness source files (`commands/`, `agents/`, `skills/`, `personas/`) into target-specific files under `exports/`. Cursor receives `.cursor/rules/*.mdc` and `.cursor/personas/*.mdc`. Codex CLI receives `prompts/*.md` plus a consolidated `AGENTS.md`. Antigravity receives `.agent/workflows`, `.agent/rules`, `.agent/skills`, `.agent/personas/`, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`. pi (https://pi.dev) receives agent `.md` files, prompts, a vendored subagent extension, and an `AGENTS.md` index — see `docs/human/pi-export.md` for the full pi target documentation. Persona export is performed per-target after the main adapter runs, using `runtime/drivers/<target>/persona_export.py`.

The legacy adapter scripts (`scripts/export-{cursor,codex,agy}.py`) have been **removed** as of v0.2.0. The runtime drivers under `runtime/drivers/<target>/export.py` are the current path. The `/z-export` command (`python3 -m z_harness_cli export --host <target>`) is the user-facing entry point. pi is an export-only target; it has no adapter, is not a launch/inject host, and runs through `runtime/drivers/pi/export.py` (imported directly, not via `--host`).

## Key entry points

<!-- AUTO-START: entry-points -->
- `runtime/drivers/cursor/export.py` — `export` — Emit and validate Cursor `.mdc` rules; append `-skill` suffix on ID collision.
- `runtime/drivers/codex/export.py` — `export` — Emit Codex prompts and `AGENTS.md`; validate prompts.
- `runtime/drivers/antigravity/export.py` — `export` — Emit and validate all agy surfaces: workflows, rules, skills, prompts, manifest, CAPABILITIES.md, README.md.
- `runtime/drivers/pi/export.py` — `export` — Emit pi agent files, prompts, vendored subagent extension, and AGENTS.md index (export-only; no adapter host).
- `scripts/audit-tarball.sh:90` — `_audit_fail` — Exit 1 immediately when a forbidden tarball pattern is matched.
- `scripts/audit-tarball.sh:98` — `_check_pattern` — Search tarball listing for one forbidden pattern (fixed-string or regex).
- `commands/z-export.md:10` — `/z-export` — Entry point: `python3 -m z_harness_cli export --host <target>` for cursor/codex/antigravity; pi export runs via direct import of `runtime.drivers.pi.export`.
- `runtime/drivers/cursor/persona_export.py` — `export_persona` — Write persona as `.cursor/personas/<name>.mdc` (context-injection rule; not native to Cursor).
- `runtime/drivers/antigravity/persona_export.py` — `export_persona` — Write persona as `.agent/personas/<name>.md` (native agy persona format).
- `runtime/drivers/codex/persona_export.py` — `export_persona` — Write persona for Codex CLI target.
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `commands` — export adapters enumerate command markdown files; `/z-export` and `/z-where` are both commands and are themselves exported. `/z-where` is a read-only active-plan registry query added in T005.
- `agents` — adapters enumerate agent definitions; `scope-extractor` (added in T008) is a Haiku subagent that reads plan artifacts and emits JSON scope for the active-plan registry — it is exported like all other agents.
- `skills` — adapters enumerate `skills/*/SKILL.md`; Cursor and Codex render them as rule/prompt files; agy also emits native `.agent/skills/<id>/SKILL.md` directories.
- `personas-and-roles` — persona files under `personas/builtin/` and `personas/user/` are exported after the main adapter via `runtime/drivers/<target>/persona_export.py`. Antigravity is the only native target; Cursor uses a glob-matched context-injection rule.
- `scripts` — `audit-tarball.sh` remains the export safety gate for packaged artifacts. The legacy per-target `scripts/export-*.py` scripts have been removed.
- `runtime-drivers` — `runtime/drivers/<target>/export.py` is the current export path for all four targets.

## Edge cases / gotchas

- The legacy adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) have been removed. Use `runtime/drivers/<target>/export.py` directly or via `python3 -m z_harness_cli export --host <target>`.
- Tarball exclusion policy lives in `scripts/audit-tarball.sh`, not in the export drivers.
- Codex does not emit one prompt per agent. Agents are consolidated into `exports/codex/AGENTS.md` because Codex CLI has no native subagent dispatch.
- Antigravity emits the most surfaces: workflows, rules, native skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- Unsupported constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`, `SubagentCreate(...)`) are replaced line-by-line with target-specific comments — never silently dropped.
- When a skill ID collides with a command ID, both Cursor and Codex adapters append a `-skill` suffix to the export filename to prevent overwriting the command file.
- `agy-plugin.yaml` is a z-harness convention manifest; Antigravity does not read it natively.
- `_ALWAYS_ON_AGENTS` in `runtime/drivers/antigravity/export.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`; all other agents get `model_decision` trigger.
- Antigravity workflow bodies have an ~12,000 character limit; several z-harness commands exceed it.
- pi is an export-only target: it has no adapter, is not a launch/inject host, and does not support `--host pi` via the CLI. Its export runs through `runtime/drivers/pi/export.py` via direct import.
- The tarball allowlist for legacy `exports/` subdirs has a `REMOVE-AT: v<next-minor>` marker in `audit-tarball.sh` — must be removed when the transition window closes.
- Cursor has no native persona mechanism; personas are exported as `alwaysApply: true` glob-matched `.mdc` rules under `.cursor/personas/`.
- `/z-export` itself performs no direct file I/O; all writes are delegated to the adapter scripts and the `persona_export.py` modules.
- pi is a separate export target with its own exporter (`runtime/drivers/pi/export.py`), its own assets (`scripts/pi_assets/`), and its own capabilities doc (`exports/pi/CAPABILITIES.md`). Unlike Cursor/Codex/agy, pi uses a vendored subagent extension for fan-out dispatch. See `docs/human/pi-export.md`. pi is export-only: no adapter, no launch/inject host support.
- Subagent YAML dispatch bug (resolved 2026-06-08): pi's frontmatter.js parser could fail on unquoted colons in YAML description values (triggered by "subagent `tasks: [...]`" in explore.md). Three-layer fix: pi runtime patch + source quoting in pi_assets + `_yaml_quote` in export-pi.py for all generated agents. Fully resolved.

## Examples

- `python3 -m z_harness_cli export --host cursor` — regenerates `exports/cursor/.cursor/rules/*.mdc`.
- `python3 -m z_harness_cli export --host codex` — regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md`.
- `python3 -m z_harness_cli export --host antigravity` — regenerates workflows, rules, skills, prompts, manifest, `CAPABILITIES.md`, and `README.md` under `exports/agy/`.
- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('exports/pi'))"` — regenerates the full `exports/pi/` tree (pi is export-only; no `--host pi` CLI flag).
- `python3 -m z_harness_cli export --host all` — runs all three adapter-host targets sequentially.
- `bash scripts/audit-tarball.sh myexport.tar.gz` — verifies a tarball contains no forbidden paths before distribution.
