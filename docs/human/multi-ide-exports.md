# Multi IDE Exports

> Last updated: 2026-05-27
> Covers source: scripts/export-common.py, scripts/export-cursor.py, scripts/export-codex.py, scripts/export-agy.py, scripts/audit-tarball.sh, commands/z-export.md, exports/cursor/CAPABILITIES.md, exports/codex/CAPABILITIES.md, exports/agy/CAPABILITIES.md

## Overview

The multi-IDE export pipeline translates the z-harness source of truth — `commands/`, `agents/`, and `skills/` — into target-specific file trees under `exports/`. Cursor receives `.cursor/rules/*.mdc` (one per command, agent, and skill). Codex CLI receives `prompts/*.md` (one per command and skill) plus a consolidated `AGENTS.md` that documents all agent roles. Antigravity (agy) receives `.agent/workflows/*.md` (commands), `.agent/rules/*.md` (agents), `.agent/skills/*/SKILL.md` (skills as native workspace skills), flat prompts for all three source kinds, an `agy-plugin.yaml` manifest, a `CAPABILITIES.md`, and a `README.md`.

The pipeline is intentionally mechanical. `scripts/export-common.py` provides the shared library: frontmatter parsing, source enumeration across the three kinds, `CAPABILITIES.md` schema validation, and conventional output-path computation. Each per-target adapter (`export-cursor.py`, `export-codex.py`, `export-agy.py`) rewrites Anthropic-specific constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`) into target-specific limitation comments, writes the target tree, and validates every emitted file before reporting its summary count. The `/z-export` slash command is the user-facing entry point: it parses `--target=<cursor|codex|agy|all>`, runs the selected adapters sequentially via `python3 scripts/export-<target>.py`, and prints per-target `OK` or `FAILED` lines regardless of individual failures.

## Key entry points

- `scripts/export-common.py:107` — `enumerate_sources` — Collect commands, agents, and skills from the repo root into a dict keyed by kind.
- `scripts/export-common.py:134` — `validate_capabilities` — Require `## Supported`, `## Unsupported`, and `## Notes` sections in a CAPABILITIES.md file.
- `scripts/export-common.py:181` — `output_path_for` — Compute the conventional output path for a given target, kind, and id.
- `scripts/export-cursor.py:66` — `_rewrite_body` — Replace `Agent(...)`, `Skill(...)`, and tool-schema call sites with a Cursor limitation comment.
- `scripts/export-cursor.py:96` — `_render_mdc` — Render one source entry as a Cursor `.mdc` rule with YAML frontmatter.
- `scripts/export-cursor.py:179` — `main` — Build command-ID set for collision detection, emit and validate Cursor `.mdc` rules, validate `CAPABILITIES.md` if present.
- `scripts/export-codex.py:90` — `_rewrite_body` — Replace unsupported call sites with a Codex limitation comment.
- `scripts/export-codex.py:117` — `_render_prompt` — Render a command or skill as a Codex prompt file with a `# /<id>` header.
- `scripts/export-codex.py:140` — `_render_agents_md` — Consolidate all agents into a single `AGENTS.md`.
- `scripts/export-codex.py:229` — `main` — Build command-ID set for collision detection, emit Codex prompts and `AGENTS.md`, validate all emitted files.
- `scripts/export-agy.py:71` — `_rewrite_body` — Replace unsupported call sites with an Antigravity limitation comment; also strips Anthropic XML tags.
- `scripts/export-agy.py:93` — `_render_workflow` — Render a command as an Antigravity workflow `.md` (description frontmatter, 250-char limit).
- `scripts/export-agy.py:130` — `_render_rule` — Render an agent as an Antigravity rule `.md` (trigger: always_on or model_decision).
- `scripts/export-agy.py:155` — `_render_skill` — Render a skill as an Antigravity native `SKILL.md` (name + description frontmatter) under `.agent/skills/<id>/SKILL.md`.
- `scripts/export-agy.py:177` — `_render_prompt` — Render flat agy prompt files with description and role frontmatter.
- `scripts/export-agy.py:207` — `_build_manifest` — Generate the `agy-plugin.yaml` export manifest (z-harness convention; not read by agy natively).
- `scripts/export-agy.py:559` — `main` — Emit and validate all agy surfaces: workflows, rules, skills, flat prompts, manifest, CAPABILITIES.md, README.md.
- `scripts/audit-tarball.sh:75` — `_audit_fail` — Immediately exit 1 when a forbidden pattern is matched in the tarball listing.
- `scripts/audit-tarball.sh:83` — `_check_pattern` — Search the tarball listing for one forbidden pattern (fixed-string or regex).
- `commands/z-export.md:10` — `/z-export` — Parse `--target`, run adapters sequentially, report per-target OK/FAILED, continue past failures.

## How it interacts with others

- `commands` — export adapters enumerate `commands/*.md` as their primary command source; `/z-export` is itself a command in that directory.
- `agents` — Cursor emits one rule per agent, Codex consolidates agents into `AGENTS.md`, agy emits both per-agent rules and flat prompts.
- `skills` — all three adapters handle `skills/*/SKILL.md`; agy is the only target with native skill support (`.agent/skills/<id>/SKILL.md` directories); Cursor and Codex emit skill content as `.mdc` or prompt files respectively.
- `scripts` — the adapters load `export-common.py` via `importlib` (because the hyphen makes it non-importable as a module name); `audit-tarball.sh` is the safety gate for any packaged tarball artifacts.

## Edge cases / gotchas

- When a skill ID matches an existing command ID, both Cursor and Codex adapters append a `-skill` suffix to the exported filename (e.g. a skill named `z-plan` becomes `z-plan-skill.mdc` / `z-plan-skill.md`). This prevents the skill export from silently overwriting the command export.
- `export-common.py` does not apply tarball exclusion rules. The sensitive-path gate (`providers.json`, `.z-harness/`, plan artifacts, home paths) lives entirely in `audit-tarball.sh`.
- Codex does not produce one file per agent. All agents go into a single `exports/codex/AGENTS.md` because Codex CLI has no native subagent dispatch.
- Antigravity has native skill support: skills are exported as `.agent/skills/<id>/SKILL.md` with `name` and `description` frontmatter. However, programmatic `Skill(name=...)` runtime API calls are still unsupported — only the workspace-skill definition files are emitted.
- Antigravity emits the most surfaces per source entry: one workflow + one rule (for agents) or one workflow (for commands) + native skill files + flat prompts for all kinds, plus manifest, CAPABILITIES.md, and README.md.
- Unsupported constructs are replaced line-by-line; the replacement preserves leading whitespace. They should never disappear silently.
- The `/z-export` command itself performs no direct file I/O — all writes are delegated to the adapter scripts.
- The agy adapter hard-codes a set of `_ALWAYS_ON_AGENTS` (`implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`); all others get `trigger: model_decision`.
- The `agy-plugin.yaml` manifest is a z-harness convention file, not a native Antigravity format. Antigravity does not read it.
- Antigravity workflow bodies are limited to approximately 12,000 characters; several z-harness commands exceed this limit.
- `export-common.py` is loaded via `importlib` in each adapter because the hyphen in the filename prevents direct Python import.

## Examples

- `python3 scripts/export-cursor.py` — regenerates `exports/cursor/.cursor/rules/*.mdc`.
- `python3 scripts/export-codex.py` — regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md`.
- `python3 scripts/export-agy.py` — regenerates all agy surfaces under `exports/agy/`, including native skill files at `.agent/skills/*`.
- `/z-export --target=all` — runs all three adapters sequentially; reports `OK` or `FAILED` per target.
- `scripts/audit-tarball.sh my-release.tar.gz` — checks a tarball for forbidden paths before distribution.
- A skill named `z-plan` exported by Cursor becomes `exports/cursor/.cursor/rules/z-plan-skill.mdc` when a `z-plan` command also exists.
- A skill exported by agy becomes `exports/agy/.agent/skills/<id>/SKILL.md` — a native Antigravity workspace skill directory, not just a flat prompt.
