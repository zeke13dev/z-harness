# Multi IDE Exports

> Last updated: 2026-05-25
> Covers source: scripts/export-common.py, scripts/export-cursor.py, scripts/export-codex.py, scripts/export-agy.py, scripts/audit-tarball.sh, commands/z-export.md, docs/human/MULTI-IDE.md, exports/cursor/CAPABILITIES.md, exports/codex/CAPABILITIES.md, exports/agy/CAPABILITIES.md

## Overview

The multi-IDE export pipeline translates the z-harness source of truth from `commands/`, `agents/`, and `skills/` into target-specific files under `exports/`. Cursor receives `.cursor/rules/*.mdc`, Codex CLI receives `prompts/*.md` plus a consolidated `AGENTS.md`, and Antigravity receives `.agent/workflows`, `.agent/rules`, `.agent/skills`, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.

The pipeline is intentionally mechanical. `scripts/export-common.py` enumerates source files, validates the minimal `CAPABILITIES.md` schema, and computes conventional target paths; each adapter rewrites unsupported Claude Code constructs into explicit comments, writes its target tree, and validates the emitted files. The `/z-export` command is the user-facing wrapper that selects one target or all three and runs the adapters sequentially.

## Key entry points

- `scripts/export-common.py:107` — `enumerate_sources` — Collect commands, agents, and skills from the repo root.
- `scripts/export-common.py:134` — `validate_capabilities` — Require Supported, Unsupported, and Notes sections.
- `scripts/export-common.py:181` — `output_path_for` — Compute Cursor, Codex, and agy conventional output paths.
- `scripts/export-cursor.py:66` — `_rewrite_body` — Replace unsupported call sites with a Cursor limitation comment.
- `scripts/export-cursor.py:96` — `_render_mdc` — Render one command, agent, or skill as a Cursor `.mdc` rule.
- `scripts/export-cursor.py:179` — `main` — Emit and validate Cursor `.mdc` rules.
- `scripts/export-codex.py:90` — `_rewrite_body` — Replace unsupported call sites with a Codex limitation comment.
- `scripts/export-codex.py:117` — `_render_prompt` — Render command and skill prompt files.
- `scripts/export-codex.py:140` — `_render_agents_md` — Consolidate all agents into `AGENTS.md`.
- `scripts/export-codex.py:229` — `main` — Emit Codex prompts plus `AGENTS.md` and validate prompts.
- `scripts/export-agy.py:71` — `_rewrite_body` — Replace unsupported call sites with an Antigravity limitation comment.
- `scripts/export-agy.py:93` — `_render_workflow` — Render commands as `.agent/workflows/<id>.md`.
- `scripts/export-agy.py:130` — `_render_rule` — Render agents as `.agent/rules/z-harness-<id>.md`.
- `scripts/export-agy.py:155` — `_render_skill` — Render skills as `.agent/skills/<id>/SKILL.md`.
- `scripts/export-agy.py:177` — `_render_prompt` — Render flat agy prompt files for commands, agents, and skills.
- `scripts/export-agy.py:207` — `_build_manifest` — Generate the z-harness `agy-plugin.yaml` manifest.
- `scripts/export-agy.py:559` — `main` — Emit and validate agy workflows, rules, skills, prompts, manifest, capabilities, and README.
- `scripts/audit-tarball.sh:75` — `_audit_fail` — Fail immediately when a forbidden tarball entry is detected.
- `scripts/audit-tarball.sh:83` — `_check_pattern` — Search a tarball listing for one forbidden pattern.
- `commands/z-export.md:10` — `/z-export` — Parse `--target`, run adapters sequentially, and report per-target status.

## How it interacts with others

- `commands` — export adapters enumerate command markdown files, and `/z-export` is itself the command wrapper for the pipeline.
- `agents` — export adapters enumerate agent definitions; Cursor emits one rule per agent, Codex consolidates agents into `AGENTS.md`, and agy emits both rules and flat prompts.
- `skills` — export adapters enumerate `skills/*/SKILL.md`; Cursor and Codex render them as rule/prompt files, while agy also emits native `.agent/skills/<id>/SKILL.md` directories.
- `scripts` — the adapters are standalone Python scripts with a shared `export-common.py`; `audit-tarball.sh` is the export safety gate for packaged artifacts.

## Edge cases / gotchas

- `scripts/export-common.py` does not apply the tarball exclusion policy; the sensitive-path gate lives in `scripts/audit-tarball.sh`.
- Codex does not emit one prompt per agent. Agents are consolidated into `exports/codex/AGENTS.md` because Codex CLI has no native subagent dispatch.
- Antigravity emits multiple surfaces for the same source: workflows for commands, rules for agents, native skills for skills, flat prompts for all three, plus `agy-plugin.yaml`.
- Unsupported constructs are replaced line-by-line with target-specific comments. They should not disappear silently.
- `commands/z-export.md` says the command itself performs no direct file I/O; writes are delegated to the adapter scripts.
- The export tree now includes regenerated planning surfaces such as `planning-router` and `z-audit-plan` wherever those source files exist.

## Examples

- `python3 scripts/export-cursor.py` regenerates `exports/cursor/.cursor/rules/*.mdc`.
- `python3 scripts/export-codex.py` regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md`.
- `python3 scripts/export-agy.py` regenerates `.agent/workflows`, `.agent/rules`, `.agent/skills`, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md` under `exports/agy/`.
- `/z-export --target=all` runs the three adapters sequentially and continues past individual target failures so each target reports `OK` or `FAILED`.
