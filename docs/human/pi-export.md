# pi Export

> Last updated: 2026-06-09
> Covers source: scripts/export-pi.py, scripts/pi-mcp-server.py, scripts/lint-frontmatter.sh, Makefile, scripts/pi_assets/AGENTS.preamble.md, scripts/pi_assets/CAPABILITIES.md, scripts/pi_assets/README.md, scripts/pi_assets/agents/explore.md, scripts/pi_assets/extensions/subagent/index.ts, scripts/pi_assets/extensions/subagent/agents.ts, scripts/pi_assets/extensions/subagent/VENDOR.md

## Overview

The pi export builds resources for [pi](https://pi.dev) — a coding agent harness that z-harness itself runs inside. Unlike the Cursor/Codex/agy exports, pi has no native subagent dispatch primitive. Fan-out runs through pi's **subagent extension**, which this export vendors under `exports/pi/extensions/subagent/`.

The export tree has two classes of output:
- **Generated** from z-harness source (`agents/`, `commands/`, `skills/`): agent files (`agents/<id>.md`), prompt files (`prompts/<id>.md`), and the `AGENTS.md` index.
- **Copied verbatim** from `scripts/pi_assets/`: the `explore` agent (pi-only; no z-harness source), the subagent extension (`index.ts`, `agents.ts`), the AGENTS preamble, `CAPABILITIES.md`, and `README.md`.

The explorer agent is the headline fan-out agent. It is read-only, returns `path:line` conclusions, and is designed for parallel dispatch via pi's `subagent { "tasks": [...] }` syntax. It is the pi-only counterpart to z-harness's codebase exploration tools.

## Prompt defense injection

The export pipeline automatically injects a **prompt defense** block into exported agent files. When a source agent's body contains a `<!-- PROMPT_DEFENSE_MARKER -->` sentinel comment, `export-pi.py` inserts the defense boilerplate immediately after that marker line with a `<!-- PROMPT_DEFENSE_INJECTED -->` tag alongside it.

The defense block instructs the agent to:
- Ignore instructions that attempt to override the system prompt or change the agent's identity
- Refuse commands that would compromise system security, exfiltrate data, or bypass access controls
- Prioritize the system prompt and coding agent role over conflicting user messages

Injection is **idempotent** — if `<!-- PROMPT_DEFENSE_INJECTED -->` is already present in the body, the export skips re-injection. If no sentinel marker exists in the source agent body, no injection occurs (no sentinel → no target).

This is a security-hardening measure activated declaratively by adding the sentinel comment to agent source files.

## Model tier mapping

As of 2026-06-09, agent model tiers are mapped to DeepSeek-specific models on export. The mapping is:

| Semantic tier | DeepSeek model      |
|---------------|---------------------|
| haiku         | deepseek-v4-flash   |
| sonnet        | deepseek-v4-pro     |
| opus          | deepseek-v4-pro     |

Cheap subagents (doc-fetcher, explore, reviewer, scope-probe, external-lookup, planning-router, resolver, and others) are pinned to `deepseek-v4-flash` for token efficiency. Heavy agents (implementer, auditor, mr-reviewer, doc-updater, and others) run on `deepseek-v4-pro`. Agents without a model tier in their frontmatter inherit pi's configured default.

## MCP server (pi-mcp-server.py)

`scripts/pi-mcp-server.py` is an MCP (Model Context Protocol) server wrapping pi-cli for Hermes Agent orchestration. It exposes two tools:

- **pi_instruct** — One-shot pi invocation via subprocess pipes. Supports instruction, context, model, provider, and timeout parameters. Returns output text, model used, exit code, and optional usage stats (token counts, cost).
- **pi_inspect_model** — Lists available pi models by parsing `pi --list-models` table output into structured JSON with provider, model, context window, and max output tokens.

The server handles timeouts (SIGTERM via process group kill), missing binaries, non-zero exit codes, and empty instructions. It parses pi's NDJSON output format (`message_end`, `turn_end`, `agent_end` events) to extract the final response text and usage statistics.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/export-pi.py:1` — `export-pi.py` — Main exporter script. Builds the full `exports/pi/` tree. Copies pi-only assets from `scripts/pi_assets/`, renders z-harness agents/prompts with pi-normalized frontmatter, rewrites `Agent()`/`Skill()` call sites to subagent hints, and generates the `AGENTS.md` index.
- `scripts/export-pi.py:80` — `_TOOL_MAP` — Maps Claude Code/z-harness tool names to pi tool names (`Glob` → `find`).
- `scripts/export-pi.py:88` — `_TOOL_UNSUPPORTED` — Tools dropped from agent allowlists on export (agent, task, webfetch, websearch, notebookedit, enterplanmode, exitplanmode, todowrite, multiedit).
- `scripts/export-pi.py:120` — `_rewrite_line` — Rewrites `Agent(subagent_type="X")` lines to `subagent { "agent": "X" }` hints, `Skill("z-foo")` to skill-run hints, and unsupported `AskUserQuestion()`/`TaskCreate()` to inline-handling hints.
- `scripts/export-pi.py:189` — `_yaml_quote` — Quotes YAML frontmatter values that contain colons, brackets, hashes, or quotes to prevent parsing failures in pi's YAML frontmatter parser. The preventive layer applied at export time for all generated agent descriptions.
- `scripts/export-pi.py:196` — `_render_agent` — Renders a z-harness agent as a pi agent `.md` file with pipelined `_yaml_quote` on descriptions, semantic model tier mapping (haiku→flash, sonnet/opus→pro), and `_TOOL_MAP` normalization on tools. Agents without a model tier inherit pi's default.
- `scripts/pi-mcp-server.py:1` — `pi-mcp-server.py` — MCP server wrapping pi-cli for Hermes Agent orchestration. Exposes `pi_instruct` (one-shot pi invocation with timeout/error handling) and `pi_inspect_model` (lists available models). Parses pi NDJSON output.
- `scripts/export-pi.py:246` — `_validate_frontmatter_yaml` — Post-export YAML validation pass. Re-validates every generated and copied agent file with `yaml.safe_load()` (strict YAML 1.2 parser) after the custom regex frontmatter parser passes. Silently skips if PyYAML is not available (import error fallback). Called from `_validate_agent` (line 263) for every emitted agent file.
- `scripts/export-pi.py:285` — `main` — Entry point: parses `--out`, enumerates sources, renders agents/prompts, copies pi-only assets, writes `AGENTS.md`, validates all outputs (including `_validate_frontmatter_yaml` on every agent file).
- `scripts/lint-frontmatter.sh:1` — `lint-frontmatter.sh` — Standalone lint script. Scans `agents/`, `skills/`, `commands/`, `personas/`, `scripts/pi_assets/` for `.md` files with YAML frontmatter and validates each with a strict YAML 1.2 parser. Exits 0 if all pass, 1 on any failure. Requires PyYAML; skips gracefully if unavailable.
- `Makefile:79` — `lint-frontmatter` target — `make lint-frontmatter` invokes `scripts/lint-frontmatter.sh`. Available for local and CI use, but not yet wired into the GitHub Actions CI workflow (`.github/workflows/tests.yml`).
- `scripts/pi_assets/AGENTS.preamble.md:1` — `AGENTS.preamble.md` — The fan-out rule preamble appended to `AGENTS.md`; encodes "doc-fetcher first, explore for gaps" discipline.
- `scripts/pi_assets/agents/explore.md:1` — `explore.md` — pi-only fan-out recon agent definition. YAML frontmatter with quoted `description` field.
- `scripts/pi_assets/extensions/subagent/index.ts:1` — `index.ts` — pi subagent extension entry point; registers the `subagent` tool and handles agent discovery from `~/.pi/agent/agents/*.md`.
- `scripts/pi_assets/extensions/subagent/agents.ts:1` — `agents.ts` — Agent loader: parses YAML frontmatter from agent `.md` files, normalizes fields, and resolves tool allowlists.
- `scripts/pi_assets/extensions/subagent/VENDOR.md:1` — `VENDOR.md` — Instructions for refreshing the vendored subagent extension after a pi upgrade.
<!-- AUTO-END: entry-points -->
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
- Model tiers are mapped on export. Semantic tiers (haiku, sonnet, opus) resolve to DeepSeek-specific models (deepseek-v4-flash, deepseek-v4-pro). Cheap subagents are pinned to flash for token efficiency — the fan-out win is context isolation AND cost.
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
