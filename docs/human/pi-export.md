# pi Export

> Last updated: 2026-06-24
> Covers source: runtime/drivers/pi/__init__.py, runtime/drivers/pi/export.py, scripts/pi_assets/AGENTS.preamble.md, scripts/pi_assets/CAPABILITIES.md, scripts/pi_assets/README.md, scripts/pi_assets/agents/explore.md, scripts/pi_assets/extensions/subagent/index.ts, scripts/pi_assets/extensions/subagent/agents.ts, scripts/pi_assets/extensions/subagent/VENDOR.md, scripts/lint-frontmatter.sh, Makefile

## Overview

The pi export builds resources for [pi](https://pi.dev) — a coding agent harness that z-harness itself runs inside. Unlike the Cursor/Codex/agy exports, pi has no native subagent dispatch primitive. Fan-out runs through pi's **subagent extension**, which this export vendors under the selected export root, for example `temp/exports/pi/extensions/subagent/`. pi is **export-only**: there is no adapter, HostDriver, or launch/inject host. The export pipeline lives entirely in `runtime/drivers/pi/export.py`, invoked directly via `from runtime.drivers.pi.export import export`.

The export tree has two classes of output:
- **Generated** from z-harness source (`agents/` and `skills/`; the legacy `commands` source key stays empty for compatibility): agent files (`agents/<id>.md`), prompt files (`prompts/<id>.md`), and the `AGENTS.md` index. `skills/<id>/SKILL.md` is the hand-authored command/skill source tier; pi renders those skills as prompts.
- **Copied verbatim** from `scripts/pi_assets/`: the `explore` agent (pi-only; no z-harness source), the subagent extension (`index.ts`, `agents.ts`), the AGENTS preamble, `CAPABILITIES.md`, and `README.md`.

The explore agent is the headline fan-out agent. It is read-only, returns `path:line` conclusions, and is designed for parallel dispatch via pi's `subagent { "tasks": [...] }` syntax.

## Boundary with OMP native support

pi export and OMP support are deliberately separate. pi remains an **export-only** compatibility target: no adapter registry entry, no HostDriver, no `--host pi`, no launch/inject cleanup, and no native session/rules/profile/model dispatch contract. OMP is a **first-class native host** (T009 complete): `OmpAdapter` with native fidelity, `OmpHostDriver` for native dispatch (T007), `.omp/z-harness/` package/discovery layout, and four native command families (z-execute, z-consult, z-gate, z-panel). All remaining OMP families are `degraded`. Claude Code is the OMP parity ground truth.

The two paths must not share prompt rewrites. OMP export must not call `runtime/drivers/pi/export.py`, `_replacement_for_line`, pi prompt-defense injection, `scripts/pi_assets/`, or the vendored `extensions/subagent/` bridge. OMP consult-provider compatibility is separate again: `scripts/omp-consult.sh` uses `omp -p --no-session --no-rules --model ... <prompt>` only to adapt provider-registry stdin prompts for advisory consultant roles. OMP native command dispatch (T007) keeps rules/session semantics and is proven at Claude-Code parity for four families (T009).

## Asset path resolution (MINOR-7)

`scripts/pi_assets/` is resolved via `__file__`-relative logic inside `export.py`, not by hard-coded paths. The module walks up three levels from `runtime/drivers/pi/export.py` to the repo root, then descends into `scripts/pi_assets/`. This makes the module importable standalone without `z_harness_cli` present. If the caller passes a `repo_root` that differs from the one inferred via `__file__`, the function prefers `repo_root / "scripts" / "pi_assets"` and falls back to the `__file__`-relative path only if that directory does not exist.

## Prompt defense injection

The export pipeline automatically injects a **prompt defense** block into exported agent files. When a source agent's body contains a `<!-- PROMPT_DEFENSE_MARKER -->` sentinel comment, `export.py` inserts the defense boilerplate immediately after that marker line with a `<!-- PROMPT_DEFENSE_INJECTED -->` tag alongside it.

Injection is **idempotent** — if `<!-- PROMPT_DEFENSE_INJECTED -->` is already present in the body, the export skips re-injection. If no sentinel marker exists in the source agent body, no injection occurs for agents; for prompts, the defense is injected after the heading as a fallback.

## Model tier mapping

Agent model tiers are mapped to DeepSeek-specific models on export. The mapping is:

| Semantic tier | DeepSeek model      |
|---------------|---------------------|
| haiku         | deepseek-v4-flash   |
| sonnet        | deepseek-v4-pro     |
| opus          | deepseek-v4-pro     |

Agents without a model tier in their frontmatter inherit pi's configured default.

## Key entry points

- `runtime/drivers/pi/export.py:360` — `export` — Public entry point: `export(repo_root, export_root, *, options=None) -> ExportResult`. Enumerates z-harness sources, renders agents/prompts with pi-normalized frontmatter, copies pi-only assets, writes `AGENTS.md`, validates all outputs. Returns `ExportResult(dest, files, fidelity="high", warnings)`.
- `runtime/drivers/pi/__init__.py:1` — package — Re-exports `export` from `runtime.drivers.pi.export`; documents the export-only asymmetry (no adapter, no HostDriver, no launch/inject host).
- `runtime/drivers/pi/export.py:85` — `_TOOL_MAP` — Maps Claude Code/z-harness tool names to pi tool names (`Glob` → `find`).
- `runtime/drivers/pi/export.py:97` — `_TOOL_UNSUPPORTED` — Tools dropped from agent allowlists on export (agent, task, webfetch, websearch, notebookedit, enterplanmode, exitplanmode, todowrite, multiedit).
- `runtime/drivers/pi/export.py:146` — `_replacement_for_line` — Rewrites single `Agent(subagent_type="X")` lines to `subagent { "agent": "X" }` hints, `Skill("z-foo")` lines to skill-run hints, and unsupported `AskUserQuestion()`/`TaskCreate()`/`SubagentCreate()`/`EnterPlanMode()`/`ExitPlanMode()` call lines to inline-handling hints. Also handles `AskUserQuestion` prose references via `_ASKUSER_PROSE_RE`.
- `runtime/drivers/pi/export.py:193` — `_yaml_quote` — Quotes YAML frontmatter values that contain colons, brackets, hashes, or quotes to prevent parsing failures in pi's YAML frontmatter parser.
- `runtime/drivers/pi/export.py:223` — `_render_agent` — Renders a z-harness agent as a pi agent `.md` file with pipelined `_yaml_quote` on descriptions, semantic model tier mapping (haiku→flash, sonnet/opus→pro), and `_TOOL_MAP` normalization on tools.
- `runtime/drivers/pi/export.py:295` — `_validate_frontmatter_yaml` — Post-export YAML validation pass. Re-validates every generated and copied agent file with `yaml.safe_load()` (strict YAML 1.2 parser). Silently skips if PyYAML is not available.
- `scripts/lint-frontmatter.sh:1` — `lint-frontmatter.sh` — Standalone lint script. Scans `agents/`, `skills/`, `personas/`, `scripts/pi_assets/`, and any legacy/back-compat command files for `.md` files with YAML frontmatter and validates each with a strict YAML 1.2 parser. Requires PyYAML; skips gracefully if unavailable.
- `Makefile:74` — `lint-frontmatter` target — `make lint-frontmatter` invokes `scripts/lint-frontmatter.sh`. Wired into CI at `.github/workflows/tests.yml:49`.
- `scripts/pi_assets/AGENTS.preamble.md:1` — `AGENTS.preamble.md` — Fan-out rule preamble appended to `AGENTS.md`; encodes "doc-fetcher first, explore for gaps" discipline.
- `scripts/pi_assets/agents/explore.md:1` — `explore.md` — pi-only fan-out recon agent definition with YAML frontmatter.
- `scripts/pi_assets/extensions/subagent/index.ts:1` — `index.ts` — pi subagent extension entry point; registers the `subagent` tool and handles agent discovery from `~/.pi/agent/agents/*.md`.

## How it interacts with others

- `multi-ide-exports` — pi is a separate export target from Cursor/Codex/agy. It has its own driver (`runtime/drivers/pi/export.py`), its own assets (`scripts/pi_assets/`), and its own capabilities doc. pi is export-only: no adapter, no `--host pi`, not a launch/inject host.
- `skills` — `export()` enumerates `skills/*/SKILL.md` as pi prompt files. the legacy `commands` source key remains only as an empty compatibility field.
- `agents` — `export()` enumerates all z-harness agent definitions and renders them as pi agent files with normalized frontmatter. The `explore` agent is pi-only and lives in `scripts/pi_assets/`.
- `export-utils` — `export.py` imports `ExportResult`, `_parse_frontmatter`, `enumerate_sources`, `validate_capabilities` from `runtime/drivers/_export_utils.py`. `enumerate_sources` returns `commands: []` when the legacy legacy command source directory is absent, while `skills/` drives prompt generation in the current tree.
- `test-export-golden` — golden snapshot tests drive `runtime.drivers.pi.export` directly via dynamic import in `runtime/tests/test_export_golden.py`.
- `capabilities-matrix` — marks pi as export-only and OMP as a first-class native host (T009); Claude Code is the OMP ground-truth parity target; pi is not a stepping stone to OMP native fidelity.
- `.omp/config.yml` — belongs to OMP sessions, not pi export. Its `skills.enableAgentsProject: false` setting prevents OMP from auto-loading this repo's large root `AGENTS.md`; OMP package discovery must use an explicit package root instead.

## YAML frontmatter defense layers (four layers)

pi's YAML frontmatter parser historically could fail on unquoted colons in `description` values. Four defense layers protect against this:

1. **pi runtime** — `quoteUnquotedColonValues()` + catch-and-retry in `frontmatter.js` (pi-side patch).
2. **Source quoting** — `scripts/pi_assets/agents/explore.md` description is quoted at source.
3. **Export-time quoting** — `_yaml_quote` in `export.py` quotes any `description` containing `:`, `[`, `]`, `{`, `}`, `#`, `"`, `'`, or leading/trailing whitespace for all generated agent files.
4. **Post-export validation** — `_validate_frontmatter_yaml` re-validates every generated and copied agent file with a strict YAML 1.2 parser after the custom regex parser passes.

Additionally, `scripts/lint-frontmatter.sh` provides source-tree-level lint before export, wired into CI.

## CI wiring

`make lint-frontmatter` is wired into CI at `.github/workflows/tests.yml:49`. Every PR is gated on valid YAML frontmatter. Golden snapshot tests for pi (`test_pi_golden`) run via `runtime/tests/test_export_golden.py`.

## Edge cases / gotchas

- pi is **export-only** — there is no adapter, no `--host pi`, no subprocess/SDK tier. The z-harness runtime cannot launch pi or inject sessions into it.
- pi has no native subagent dispatch. Fan-out works through the vendored `extensions/subagent/` extension, which spawns isolated `pi` child processes.
- `skills/` is the source for prompts. the legacy command source directory is absent in the current tree and remains only as an empty back-compat source key so export drivers do not KeyError.
- Asset resolution is `__file__`-relative (MINOR-7). The module is standalone-importable without `z_harness_cli`. If you move `export.py` without moving `scripts/pi_assets/`, the fallback path inferred from `__file__` will break.
- `_validate_frontmatter_yaml` silently skips if PyYAML is not installed (import error fallback). The export succeeds but the strict YAML gate is bypassed.
- Multi-line `Agent()`/`Skill()` call rewrites are line-based. Only the line containing `Agent(` / `Skill(` is rewritten; argument lines on following lines are left in place.
- Agents are discovered from `~/.pi/agent/agents/*.md` — this is NOT a pi package resource type. Even though z-harness installs as a pi package, agents must be symlinked into the discovery directory separately.
- Do not infer OMP behavior from pi export behavior. pi's line rewrites and vendored subagent extension are compatibility mechanisms for pi only; OMP command dispatch has its own frozen argv/prompt/output/event/session/profile/rules/model contract and is now native (T007/T009).
- The subagent extension must be refreshed after pi upgrades; see `extensions/subagent/VENDOR.md`.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/pi-export.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

- **2026-06-08 bugfix** ([pi-export](#)) — Subagent YAML dispatch bug resolved. pi's YAML frontmatter parser (dist/utils/frontmatter.js) could fail to parse agent .md files when the description field contained an unquoted colon (triggered by 'subagent `tasks: [...]`' in explore.md). Three-layer defense applied: (1) pi runtime patched with quoteUnquotedColonValues() + catch-and-retry in frontmatter.js; (2) scripts/pi_assets/agents/explore.md description quoted at source; (3) the generated pi agent description is quoted when exported from source. Additionally, runtime/drivers/pi/export.py:193 _yaml_quote already prevents this for all generated agent files by quoting any description containing regex [:[]{}#"']. _(tags: pi-export, yaml, frontmatter, bugfix)_

- **2026-06-08 infra** ([pi-export](#)) — Post-review YAML validation hardening. Three additions: (1) runtime/drivers/pi/export.py:295 _validate_frontmatter_yaml() re-validates every generated/copied agent file with yaml.safe_load() — strict YAML 1.2 parser — after the custom regex frontmatter parser passes; imports yaml with silent skip fallback. (2) scripts/lint-frontmatter.sh scans agents/, skills/, personas/, scripts/pi_assets/ for .md frontmatter and validates with strict YAML 1.2 parser; wired into make lint-frontmatter. (3) Two infra issues posted: runtime/drivers/pi/export.py copied assets bypass _yaml_quote (only generated agents get quoting), and make lint-frontmatter is not wired into CI (.github/workflows/tests.yml). The CI gap means frontmatter regressions can land on main undetected until the next export. _(tags: pi-export, yaml, frontmatter, validation, ci, infra)_

## Examples

- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('temp/exports/pi'))"` — regenerates the full `temp/exports/pi/` tree with all four YAML defense layers.
- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('/tmp/pi-test'))"` — exports to a non-default output directory.
- `/z-export --target=pi` — invokes the pi export via the z-harness command wrapper (pi is export-only; no adapter host).
- `make lint-frontmatter` — validates YAML frontmatter across all source `.md` files (agents, skills, personas, pi_assets).
- `bash scripts/lint-frontmatter.sh` — runs the standalone lint directly.
