# pi Export

> Last updated: 2026-06-08
> Covers source: scripts/export-pi.py, scripts/lint-frontmatter.sh, Makefile, scripts/pi_assets/AGENTS.preamble.md, scripts/pi_assets/CAPABILITIES.md, scripts/pi_assets/README.md, scripts/pi_assets/agents/explore.md, scripts/pi_assets/extensions/subagent/index.ts, scripts/pi_assets/extensions/subagent/agents.ts, scripts/pi_assets/extensions/subagent/VENDOR.md

## Overview

The pi export builds resources for [pi](https://pi.dev) — a coding agent harness that z-harness itself runs inside. Unlike the Cursor/Codex/agy exports, pi has no native subagent dispatch primitive. Fan-out runs through pi's **subagent extension**, which this export vendors under `exports/pi/extensions/subagent/`.

The export tree has two classes of output:
- **Generated** from z-harness source (`agents/`, `commands/`, `skills/`): agent files (`agents/<id>.md`), prompt files (`prompts/<id>.md`), and the `AGENTS.md` index.
- **Copied verbatim** from `scripts/pi_assets/`: the `explore` agent (pi-only; no z-harness source), the subagent extension (`index.ts`, `agents.ts`), the AGENTS preamble, `CAPABILITIES.md`, and `README.md`.

The explorer agent is the headline fan-out agent. It is read-only, returns `path:line` conclusions, and is designed for parallel dispatch via pi's `subagent { "tasks": [...] }` syntax. It is the pi-only counterpart to z-harness's codebase exploration tools.

## Key entry points

- `scripts/export-pi.py:1` — `export-pi.py` — Main exporter script. Builds the full `exports/pi/` tree. Copies pi-only assets from `scripts/pi_assets/`, renders z-harness agents/prompts with pi-normalized frontmatter, rewrites `Agent()`/`Skill()` call sites to subagent hints, and generates the `AGENTS.md` index.
- `scripts/export-pi.py:80` — `_TOOL_MAP` — Maps Claude Code/z-harness tool names to pi tool names (`Glob` → `find`).
- `scripts/export-pi.py:88` — `_TOOL_UNSUPPORTED` — Tools dropped from agent allowlists on export (agent, task, webfetch, websearch, notebookedit, enterplanmode, exitplanmode, todowrite, multiedit).
- `scripts/export-pi.py:120` — `_rewrite_line` — Rewrites `Agent(subagent_type="X")` lines to `subagent { "agent": "X" }` hints, `Skill("z-foo")` to skill-run hints, and unsupported `AskUserQuestion()`/`TaskCreate()` to inline-handling hints.
- `scripts/export-pi.py:189` — `_yaml_quote` — Quotes YAML frontmatter values that contain colons, brackets, hashes, or quotes to prevent parsing failures in pi's YAML frontmatter parser. The preventive layer applied at export time for all generated agent descriptions.
- `scripts/export-pi.py:196` — `_render_agent` — Renders a z-harness agent as a pi agent `.md` file with pipelined `_yaml_quote` on descriptions and `_TOOL_MAP` normalization on tools. Model is intentionally omitted.
- `scripts/export-pi.py:246` — `_validate_frontmatter_yaml` — Post-export YAML validation pass. Re-validates every generated and copied agent file with `yaml.safe_load()` (strict YAML 1.2 parser) after the custom regex frontmatter parser passes. Silently skips if PyYAML is not available (import error fallback). Called from `_validate_agent` (line 263) for every emitted agent file.
- `scripts/export-pi.py:285` — `main` — Entry point: parses `--out`, enumerates sources, renders agents/prompts, copies pi-only assets, writes `AGENTS.md`, validates all outputs (including `_validate_frontmatter_yaml` on every agent file).
- `scripts/lint-frontmatter.sh:1` — `lint-frontmatter.sh` — Standalone lint script. Scans `agents/`, `skills/`, `commands/`, `personas/`, `scripts/pi_assets/` for `.md` files with YAML frontmatter and validates each with a strict YAML 1.2 parser. Exits 0 if all pass, 1 on any failure. Requires PyYAML; skips gracefully if unavailable.
- `Makefile:79` — `lint-frontmatter` target — `make lint-frontmatter` invokes `scripts/lint-frontmatter.sh`. Available for local and CI use, but not yet wired into the GitHub Actions CI workflow (`.github/workflows/tests.yml`).
- `scripts/pi_assets/AGENTS.preamble.md:1` — `AGENTS.preamble.md` — The fan-out rule preamble appended to `AGENTS.md`; encodes "doc-fetcher first, explore for gaps" discipline.
- `scripts/pi_assets/agents/explore.md:1` — `explore.md` — pi-only fan-out recon agent definition. YAML frontmatter with quoted `description` field.
- `scripts/pi_assets/extensions/subagent/index.ts:1` — `index.ts` — pi subagent extension entry point; registers the `subagent` tool and handles agent discovery from `~/.pi/agent/agents/*.md`.
- `scripts/pi_assets/extensions/subagent/agents.ts:1` — `agents.ts` — Agent loader: parses YAML frontmatter from agent `.md` files, normalizes fields, and resolves tool allowlists.
- `scripts/pi_assets/extensions/subagent/VENDOR.md:1` — `VENDOR.md` — Instructions for refreshing the vendored subagent extension after a pi upgrade.

## How it interacts with others

- `commands` — export-pi.py enumerates command markdown files; `/z-export --target=pi` is the export command.
- `agents` — export-pi.py enumerates all z-harness agent definitions and renders them as pi agent files with normalized frontmatter. The `explore` agent is pi-only (no z-harness source) and lives in `scripts/pi_assets/`.
- `skills` — export-pi.py enumerates `skills/*/SKILL.md` and renders them as pi prompt files. `Skill()` call sites are rewritten to `/z-foo` skill hints. z-harness is also installed as a pi package so its skills auto-surface natively.
- `multi-ide-exports` — pi is a separate export target from Cursor/Codex/agy. It has its own exporter (`scripts/export-pi.py`), its own assets (`scripts/pi_assets/`), and its own capabilities doc (`exports/pi/CAPABILITIES.md`). The pi exporter is not deprecated and does not use the runtime/drivers/ replacement path.
- `scripts` — export-pi.py is a standalone Python script. It imports `export-common.py` via importlib for `enumerate_sources` and `validate_capabilities`. `scripts/lint-frontmatter.sh` is the standalone lint companion. Both are wired into `make lint-frontmatter`.

## YAML frontmatter defense layers (four layers)

pi's YAML frontmatter parser (`dist/utils/frontmatter.js`) historically could fail on unquoted colons in `description` values (e.g., `file:line`, `tasks: [...]`). Four defense layers now protect against this:

1. **pi runtime** — `quoteUnquotedColonValues()` + catch-and-retry in `frontmatter.js` (pi-side patch).
2. **Source quoting** — `scripts/pi_assets/agents/explore.md` description is quoted at source.
3. **Export-time quoting** — `export-pi.py`'s `_yaml_quote` function (line 189) quotes any `description` containing `:`, `[`, `]`, `{`, `}`, `#`, `"`, `'`, or leading/trailing whitespace for all generated agent files.
4. **Post-export validation** — `_validate_frontmatter_yaml` (line 246) re-validates every generated and copied agent file with a strict YAML 1.2 parser after the custom regex parser passes. Catches any YAML that the quoting layer missed.

Additionally, `scripts/lint-frontmatter.sh` provides a standalone, source-tree-level lint that validates frontmatter across all relevant directories before export.

## CI wiring recommendation

`make lint-frontmatter` exists but is **not wired into CI** (`.github/workflows/tests.yml`). Recommend adding it as a step alongside the existing `make lint` call so every PR is gated on valid YAML frontmatter. Without this, frontmatter regressions (unquoted colons introduced in new agent/skill/command descriptions) are only caught at export time, not at commit time.

## Edge cases / gotchas

- **Four-layer YAML defense.** See "YAML frontmatter defense layers" above. Layer 4 (`_validate_frontmatter_yaml`) + the standalone lint script provide belt-and-suspenders protection against frontmatter parse failures.
- pi has no native subagent dispatch. Fan-out works through the vendored `extensions/subagent/` extension, which spawns isolated `pi` child processes.
- Model pinning is dropped on export. pi agents inherit pi's configured default model. In a deepseek-only setup there is no cheap Haiku tier — the fan-out win is context isolation, not cost.
- Multi-line call rewrites are line-based. Only the line containing `Agent(` / `Skill(` is rewritten; argument lines on following lines are left in place.
- Agents are discovered from `~/.pi/agent/agents/*.md` — this is NOT a pi package resource type. Even though z-harness installs as a pi package, agents must be symlinked into the discovery directory separately.
- The subagent extension must be refreshed after pi upgrades; see `extensions/subagent/VENDOR.md`.
- `_validate_frontmatter_yaml` silently skips if PyYAML is not available (import error fallback). The export succeeds but the strict YAML gate is bypassed. Install PyYAML (`pip install pyyaml`) for full defense.
- `scripts/lint-frontmatter.sh` similarly requires PyYAML; exits with a descriptive "SKIP" message if unavailable.
- **CI gap.** `make lint-frontmatter` is not wired into CI — frontmatter regressions can land on `main` without being caught until the next export. Wire it into `.github/workflows/tests.yml`.

## Examples

- `python3 scripts/export-pi.py` — regenerates the full `exports/pi/` tree with all four YAML defense layers.
- `python3 scripts/export-pi.py --out /tmp/pi-test` — exports to a non-default output directory.
- `/z-export --target=pi` — invokes the pi export via the z-harness command wrapper.
- `make lint-frontmatter` — validates YAML frontmatter across all source `.md` files (agents, skills, commands, personas, pi_assets).
- `bash scripts/lint-frontmatter.sh` — runs the standalone lint directly.
