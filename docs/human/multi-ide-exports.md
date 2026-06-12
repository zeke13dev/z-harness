# Multi IDE Exports

> Last updated: 2026-06-11
> Covers source: runtime/drivers/cursor/export.py, runtime/drivers/codex/export.py, runtime/drivers/antigravity/export.py, runtime/drivers/pi/export.py, scripts/audit-tarball.sh, commands/z-export.md, docs/human/MULTI-IDE.md, exports/cursor/CAPABILITIES.md, exports/codex/CAPABILITIES.md, exports/agy/CAPABILITIES.md

## Overview

The multi-IDE export pipeline translates the z-harness source of truth from `commands/`, `agents/`, and `skills/` into target-specific files under `exports/`. Cursor receives `.cursor/rules/*.mdc`, Codex CLI receives `prompts/*.md` plus a consolidated `AGENTS.md`, and Antigravity receives `.agent/workflows`, `.agent/rules`, `.agent/skills`, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.

The legacy per-target adapter scripts (`export-cursor.py`, `export-codex.py`, `export-agy.py`) and their shared library (`export-common.py`) have been **removed** as of v0.2.0. The runtime drivers under `runtime/drivers/<target>/export.py` are the current path. Use `python3 -m z_harness_cli export --host <target>` for cursor/codex/antigravity. pi is an export-only target with no adapter host; its export runs via direct import of `runtime.drivers.pi.export`. The `/z-export` command wrapper and `scripts/audit-tarball.sh` remain operational.

## Key entry points

<!-- AUTO-START: entry-points -->
- `runtime/drivers/cursor/export.py` — `export` — Emit and validate Cursor `.mdc` rules; append `-skill` suffix on ID collision.
- `runtime/drivers/codex/export.py` — `export` — Emit Codex prompts and `AGENTS.md`; append `-skill` suffix on collision.
- `runtime/drivers/antigravity/export.py` — `export` — Emit and validate all agy surfaces: workflows, rules, skills, prompts, manifest, CAPABILITIES.md, and README.md.
- `runtime/drivers/pi/export.py` — `export` — Emit pi agent files, prompts, vendored subagent extension, and AGENTS.md (export-only; no adapter host).
- `scripts/audit-tarball.sh:87` — `_audit_fail` — Exit 1 immediately when a forbidden tarball pattern is matched.
- `scripts/audit-tarball.sh:95` — `_check_pattern` — Search a tarball listing for one forbidden pattern (fixed-string or regex).
- `commands/z-export.md:10` — `/z-export` — Entry point: `python3 -m z_harness_cli export --host <target>` for cursor/codex/antigravity; pi runs via direct import.
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `commands` — export adapters enumerate command markdown files; `/z-export` is itself the command wrapper for the pipeline.
- `agents` — export adapters enumerate agent definitions; Cursor emits one rule per agent, Codex consolidates agents into `AGENTS.md`, and agy emits both rules and flat prompts.
- `skills` — export adapters enumerate `skills/*/SKILL.md`; Cursor and Codex render them as rule/prompt files, while agy also emits native `.agent/skills/<id>/SKILL.md` directories.
- `scripts` — `audit-tarball.sh` is the export safety gate for packaged artifacts. The legacy `scripts/export-*.py` scripts have been removed.
- `runtime` — `runtime/drivers/<target>/export.py` is the current export implementation for all four targets (cursor, codex, antigravity, pi).

## Edge cases / gotchas

- The legacy adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) have been removed. Use `python3 -m z_harness_cli export --host <target>` or import `runtime.drivers.<target>.export` directly.
- Tarball exclusion policy lives exclusively in `scripts/audit-tarball.sh`, not in the export drivers.
- Codex does not emit one prompt per agent. Agents are consolidated into `exports/codex/AGENTS.md` because Codex CLI has no native subagent dispatch.
- Antigravity emits the most surfaces per source: workflows for commands, rules for agents, native `.agent/skills/<id>/SKILL.md` for skills, flat prompts for all three, plus `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- Unsupported constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`, `SubagentCreate(...)`) are replaced line-by-line with target-specific HTML comments; they are never silently dropped.
- `/z-export` itself performs no file I/O; all writes are delegated to the runtime driver modules.
- pi is an export-only target: no adapter, not a launch/inject host. Its export runs via `runtime/drivers/pi/export.py` imported directly, not via `--host pi`.
- When a skill ID collides with a command ID, both Cursor and Codex adapters append a `-skill` suffix to the export filename to prevent overwrite (e.g., `z-plan-skill.mdc`).
- `_ALWAYS_ON_AGENTS` in `runtime/drivers/antigravity/export.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, and `remote-runner` as always-on rules; all other agent IDs receive `model_decision`.
- `agy-plugin.yaml` is a z-harness convention manifest only; Antigravity does not read it natively.
- Antigravity workflow bodies have an approximately 12,000-character limit; several z-harness commands exceed it.
- The tarball allowlist permits `exports/codex/`, `exports/agy/`, `exports/cursor/`, and `exports/pi/`; all other `exports/` subdirectories are forbidden.

## Examples

- `python3 -m z_harness_cli export --host cursor` — regenerates `exports/cursor/.cursor/rules/*.mdc`.
- `python3 -m z_harness_cli export --host codex` — regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md`.
- `python3 -m z_harness_cli export --host antigravity` — regenerates workflows, rules, skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md` under `exports/agy/`.
- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('exports/pi'))"` — regenerates the full `exports/pi/` tree (pi is export-only; no `--host pi` flag).
- `python3 -m z_harness_cli export --host all` — runs all three adapter-host targets sequentially.
- `bash scripts/audit-tarball.sh myexport.tar.gz` — verifies a tarball contains no forbidden paths before distribution.
