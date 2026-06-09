# Multi IDE Exports

> Last updated: 2026-05-28
> Covers source: scripts/export-common.py, scripts/export-cursor.py, scripts/export-codex.py, scripts/export-agy.py, scripts/audit-tarball.sh, commands/z-export.md, docs/human/MULTI-IDE.md, exports/cursor/CAPABILITIES.md, exports/codex/CAPABILITIES.md, exports/agy/CAPABILITIES.md

## Overview

The multi-IDE export pipeline translates the z-harness source of truth from `commands/`, `agents/`, and `skills/` into target-specific files under `exports/`. Cursor receives `.cursor/rules/*.mdc`, Codex CLI receives `prompts/*.md` plus a consolidated `AGENTS.md`, and Antigravity receives `.agent/workflows`, `.agent/rules`, `.agent/skills`, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.

**Deprecation notice.** All three per-target adapter scripts (`export-cursor.py`, `export-codex.py`, `export-agy.py`) and their shared library (`export-common.py`) are frozen at v0.1.0 and will be removed after v0.2.0 (see C6-D1). The runtime driver under `runtime/drivers/antigravity/` is the forward replacement path. The `/z-export` command wrapper and `scripts/audit-tarball.sh` remain operational during the transition window. The `exports/codex/`, `exports/agy/`, and `exports/cursor/` subdirectories are preserved in the tarball allowlist through the end of the one-minor-version transition window; all other `exports/` subdirectories are forbidden.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/export-common.py:108` — `enumerate_sources` — Collect commands, agents, and skills from the repo root into a kind-keyed dict.
- `scripts/export-common.py:135` — `validate_capabilities` — Require `## Supported`, `## Unsupported`, and `## Notes` sections in CAPABILITIES.md.
- `scripts/export-common.py:182` — `output_path_for` — Compute the conventional output path for a given target, kind, and id.
- `scripts/export-cursor.py:67` — `_rewrite_body` — Replace Agent/Skill/tool-schema call sites with a Cursor limitation comment.
- `scripts/export-cursor.py:97` — `_render_mdc` — Render one source entry as a Cursor `.mdc` rule with YAML frontmatter.
- `scripts/export-cursor.py:180` — `main` — Build command-ID set, emit and validate Cursor `.mdc` rules, append `-skill` suffix on collision.
- `scripts/export-codex.py:91` — `_rewrite_body` — Replace unsupported call sites with a Codex limitation comment.
- `scripts/export-codex.py:118` — `_render_prompt` — Render a command or skill as a Codex prompt with a `# /<id>` header.
- `scripts/export-codex.py:141` — `_render_agents_md` — Consolidate all agents into a single `AGENTS.md`.
- `scripts/export-codex.py:230` — `main` — Emit Codex prompts and `AGENTS.md`, append `-skill` suffix on collision.
- `scripts/export-agy.py:72` — `_rewrite_body` — Replace unsupported call sites with an Antigravity limitation comment.
- `scripts/export-agy.py:94` — `_render_workflow` — Render a command as an Antigravity workflow `.md` (description frontmatter, 250-char limit).
- `scripts/export-agy.py:131` — `_render_rule` — Render an agent as an Antigravity rule `.md` with `always_on` or `model_decision` trigger.
- `scripts/export-agy.py:156` — `_render_skill` — Render a skill as a native Antigravity `SKILL.md` under `.agent/skills/<id>/SKILL.md`.
- `scripts/export-agy.py:178` — `_render_prompt` — Render a flat agy prompt with `description` and `role` frontmatter.
- `scripts/export-agy.py:208` — `_build_manifest` — Generate the `agy-plugin.yaml` export manifest (z-harness convention only, not read by agy natively).
- `scripts/export-agy.py:560` — `main` — Emit and validate all agy surfaces: workflows, rules, skills, prompts, manifest, CAPABILITIES.md, and README.md.
- `scripts/audit-tarball.sh:87` — `_audit_fail` — Exit 1 immediately when a forbidden tarball pattern is matched.
- `scripts/audit-tarball.sh:95` — `_check_pattern` — Search a tarball listing for one forbidden pattern (fixed-string or regex).
- `commands/z-export.md:10` — `/z-export` — Parse `--target`, run adapters sequentially, report OK/FAILED per target.
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `commands` — export adapters enumerate command markdown files; `/z-export` is itself the command wrapper for the pipeline.
- `agents` — export adapters enumerate agent definitions; Cursor emits one rule per agent, Codex consolidates agents into `AGENTS.md`, and agy emits both rules and flat prompts.
- `skills` — export adapters enumerate `skills/*/SKILL.md`; Cursor and Codex render them as rule/prompt files, while agy also emits native `.agent/skills/<id>/SKILL.md` directories.
- `scripts` — the adapters are standalone Python scripts sharing `export-common.py` loaded via `importlib`; `audit-tarball.sh` is the export safety gate for packaged artifacts.
- `runtime` — `runtime/drivers/antigravity/` is the forward replacement for the deprecated per-target adapter scripts.

## Edge cases / gotchas

- All four adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) are deprecated and frozen at v0.1.0; running them emits a `WARNING` to stderr about upcoming removal. Use the runtime driver instead.
- `export-common.py` does not enforce tarball exclusion policy; that gate lives exclusively in `audit-tarball.sh`.
- Codex does not emit one prompt per agent. Agents are consolidated into `exports/codex/AGENTS.md` because Codex CLI has no native subagent dispatch.
- Antigravity emits the most surfaces per source: workflows for commands, rules for agents, native `.agent/skills/<id>/SKILL.md` for skills, flat prompts for all three, plus `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- Unsupported constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`, `SubagentCreate(...)`) are replaced line-by-line with target-specific HTML comments; they are never silently dropped.
- `/z-export` itself performs no file I/O; all writes are delegated to the adapter scripts.
- When a skill ID collides with a command ID, both Cursor and Codex adapters append a `-skill` suffix to the export filename to prevent overwrite (e.g., `z-plan-skill.mdc`).
- `_ALWAYS_ON_AGENTS` in `export-agy.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, and `remote-runner` as always-on rules; all other agent IDs receive `model_decision`.
- `agy-plugin.yaml` is a z-harness convention manifest only; Antigravity does not read it natively.
- Antigravity workflow bodies have an approximately 12,000-character limit; several z-harness commands exceed it.
- `export-common.py` is loaded via `importlib` in each adapter because the hyphen in the filename prevents direct Python import.
- The tarball allowlist permits `exports/codex/`, `exports/agy/`, and `exports/cursor/` through the transition window; all other `exports/` subdirectories are forbidden.

## Examples

- `python3 scripts/export-cursor.py` regenerates `exports/cursor/.cursor/rules/*.mdc` (deprecated; use runtime driver).
- `python3 scripts/export-codex.py` regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md` (deprecated; use runtime driver).
- `python3 scripts/export-agy.py` regenerates workflows, rules, skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md` under `exports/agy/` (deprecated; use runtime driver).
- `/z-export --target=all` runs the three adapters sequentially and continues past individual target failures so each target reports `OK` or `FAILED`.
- `bash scripts/audit-tarball.sh myexport.tar.gz` verifies a tarball contains no forbidden paths before distribution.
