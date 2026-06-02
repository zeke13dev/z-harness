# Multi IDE Exports

> Last updated: 2026-06-02
> Covers source: scripts/export-common.py, scripts/export-cursor.py, scripts/export-codex.py, scripts/export-agy.py, scripts/audit-tarball.sh, commands/z-export.md, exports/cursor/CAPABILITIES.md, exports/codex/CAPABILITIES.md, exports/agy/CAPABILITIES.md

## Overview

The multi-IDE export pipeline translates z-harness source files (`commands/`, `agents/`, `skills/`, `personas/`) into target-specific files under `exports/`. Cursor receives `.cursor/rules/*.mdc` and `.cursor/personas/*.mdc`. Codex CLI receives `prompts/*.md` plus a consolidated `AGENTS.md`. Antigravity receives `.agent/workflows`, `.agent/rules`, `.agent/skills`, `.agent/personas/`, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`. Persona export is performed per-target after the main adapter runs, using `runtime/drivers/<target>/persona_export.py`.

The adapter scripts (`scripts/export-{cursor,codex,agy}.py`) are **deprecated** and frozen at v0.1.0 (C6-D1 — remove after v0.2.0). Each emits a deprecation WARNING to stderr when run directly. The runtime-based workflow under `runtime/drivers/` is the forward path. The `/z-export` command remains the user-facing wrapper; it runs the legacy adapters sequentially and then invokes persona export per target via the runtime driver modules.

## Key entry points

- `scripts/export-common.py:108` — `enumerate_sources` — Collect commands, agents, and skills from the repo root.
- `scripts/export-common.py:135` — `validate_capabilities` — Require Supported, Unsupported, and Notes sections.
- `scripts/export-common.py:182` — `output_path_for` — Compute Cursor, Codex, and agy conventional output paths.
- `scripts/export-cursor.py:67` — `_rewrite_body` — Replace unsupported call sites with a Cursor limitation comment.
- `scripts/export-cursor.py:97` — `_render_mdc` — Render one command, agent, or skill as a Cursor `.mdc` rule.
- `scripts/export-cursor.py:180` — `main` — Emit and validate Cursor `.mdc` rules; append `-skill` suffix on ID collision.
- `scripts/export-codex.py:91` — `_rewrite_body` — Replace unsupported call sites with a Codex limitation comment.
- `scripts/export-codex.py:118` — `_render_prompt` — Render command or skill as Codex prompt with `# /<id>` header.
- `scripts/export-codex.py:141` — `_render_agents_md` — Consolidate all agents into a single `AGENTS.md`.
- `scripts/export-codex.py:230` — `main` — Emit Codex prompts and `AGENTS.md`; validate prompts.
- `scripts/export-agy.py:72` — `_rewrite_body` — Replace unsupported call sites with an Antigravity limitation comment.
- `scripts/export-agy.py:94` — `_render_workflow` — Render commands as `.agent/workflows/<id>.md`.
- `scripts/export-agy.py:131` — `_render_rule` — Render agents as `.agent/rules/z-harness-<id>.md`.
- `scripts/export-agy.py:156` — `_render_skill` — Render skills as `.agent/skills/<id>/SKILL.md`.
- `scripts/export-agy.py:178` — `_render_prompt` — Render flat agy prompt files for commands, agents, and skills.
- `scripts/export-agy.py:208` — `_build_manifest` — Generate the `agy-plugin.yaml` export manifest.
- `scripts/export-agy.py:560` — `main` — Emit and validate all agy surfaces: workflows, rules, skills, prompts, manifest, CAPABILITIES.md, README.md.
- `scripts/audit-tarball.sh:90` — `_audit_fail` — Exit 1 immediately when a forbidden tarball pattern is matched.
- `scripts/audit-tarball.sh:98` — `_check_pattern` — Search tarball listing for one forbidden pattern (fixed-string or regex).
- `commands/z-export.md:10` — `/z-export` — Parse `--target`, run adapters sequentially (Phase 2), then export personas per target (Phase 2b).
- `runtime/drivers/cursor/persona_export.py` — `export_persona` — Write persona as `.cursor/personas/<name>.mdc` (context-injection rule; not native to Cursor).
- `runtime/drivers/antigravity/persona_export.py` — `export_persona` — Write persona as `.agent/personas/<name>.md` (native agy persona format).
- `runtime/drivers/codex/persona_export.py` — `export_persona` — Write persona for Codex CLI target.

## How it interacts with others

- `commands` — export adapters enumerate command markdown files; `/z-export` and `/z-where` are both commands and are themselves exported. `/z-where` is a read-only active-plan registry query added in T005.
- `agents` — adapters enumerate agent definitions; `scope-extractor` (added in T008) is a Haiku subagent that reads plan artifacts and emits JSON scope for the active-plan registry — it is exported like all other agents.
- `skills` — adapters enumerate `skills/*/SKILL.md`; Cursor and Codex render them as rule/prompt files; agy also emits native `.agent/skills/<id>/SKILL.md` directories.
- `personas-and-roles` — persona files under `personas/builtin/` and `personas/user/` are exported after the main adapter via `runtime/drivers/<target>/persona_export.py`. Antigravity is the only native target; Cursor uses a glob-matched context-injection rule.
- `scripts` — adapters are standalone Python scripts with a shared `export-common.py`; `audit-tarball.sh` is the export safety gate for packaged artifacts.
- `runtime-drivers` — the forward replacement path for the deprecated per-target scripts; currently wired into `/z-export` Phase 2b for persona export.

## Edge cases / gotchas

- All four adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) are frozen at v0.1.0 and deprecated. They warn to stderr when run as `__main__`. The deprecation marker is `C6-D1 — remove after v0.2.0`.
- `scripts/export-common.py` does not apply the tarball exclusion policy; the sensitive-path gate lives in `scripts/audit-tarball.sh`.
- Codex does not emit one prompt per agent. Agents are consolidated into `exports/codex/AGENTS.md` because Codex CLI has no native subagent dispatch.
- Antigravity emits the most surfaces: workflows, rules, native skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- Unsupported constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`, `SubagentCreate(...)`) are replaced line-by-line with target-specific comments — never silently dropped.
- When a skill ID collides with a command ID, both Cursor and Codex adapters append a `-skill` suffix to the export filename to prevent overwriting the command file.
- `agy-plugin.yaml` is a z-harness convention manifest; Antigravity does not read it natively.
- `_ALWAYS_ON_AGENTS` in `export-agy.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`; all other agents get `model_decision` trigger.
- Antigravity workflow bodies have an ~12,000 character limit; several z-harness commands exceed it.
- `export-common.py` is loaded via `importlib` in each adapter because the hyphen in its filename prevents direct Python import.
- The tarball allowlist for legacy `exports/` subdirs has a `REMOVE-AT: v<next-minor>` marker in `audit-tarball.sh` — must be removed when the transition window closes.
- Cursor has no native persona mechanism; personas are exported as `alwaysApply: true` glob-matched `.mdc` rules under `.cursor/personas/`.
- `/z-export` itself performs no direct file I/O; all writes are delegated to the adapter scripts and the `persona_export.py` modules.

## Examples

- `python3 scripts/export-cursor.py` — regenerates `exports/cursor/.cursor/rules/*.mdc` (deprecated; use runtime driver in production).
- `python3 scripts/export-codex.py` — regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md`.
- `python3 scripts/export-agy.py` — regenerates workflows, rules, skills, prompts, manifest, `CAPABILITIES.md`, and `README.md` under `exports/agy/`.
- `/z-export --target=all` — runs all three adapters sequentially, then exports personas via `runtime/drivers/<target>/persona_export.py`, and continues past individual target failures.
- `/z-export --target=cursor` — exports only the Cursor target, including cursor persona export.
