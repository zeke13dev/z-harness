# Host Capabilities Matrix

> Last updated: 2026-06-16
> Covers source: z_harness_cli/adapters/base.py, z_harness_cli/adapters/registry.py, z_harness_cli/adapters/claude.py, z_harness_cli/adapters/antigravity.py, z_harness_cli/adapters/cursor.py, z_harness_cli/adapters/codex.py, runtime/drivers/windsurf/export.py, runtime/drivers/kiro/export.py, runtime/drivers/cline/export.py, runtime/drivers/copilot/export.py

## Overview

The capabilities matrix describes how completely z-harness features work on each supported host. There are two categories of hosts:

**Adapter hosts** (Claude Code, Antigravity/agy, Cursor, Codex CLI) — these have a `HostAdapter` class in `z_harness_cli/adapters/`, can be launched/injected, and are registered in the adapter registry. Each is assigned a **fidelity tier** and per-command tiers that tell callers whether a given `/z-*` command runs natively, in degraded mode, or is blocked entirely.

**Export-only hosts** (Windsurf, Kiro, Cline, Copilot) — these have a runtime export driver in `runtime/drivers/<host>/export.py` but **no HostAdapter, no adapter-registry entry, and no launch/inject support**. They can only be used via `/z-export` or the runtime CLI. They are not in the `COMMAND_CAPABILITY_MATRIX` and will never be.

The `COMMAND_CAPABILITY_MATRIX` dict in `base.py` is populated at import time by each adapter's `register_command_tiers()` call; `command_tier(host, cmd)` provides fail-safe O(1) lookup (unknown = blocked).

The adapters also declare static `Capabilities` flags covering MCP support, trust-prompt behavior, cwd-override support, and cleanup strategy. These flags drive injection and launch decisions in the CLI commands (`launch.py`, `export.py`, `doctor.py`). The canonical type for export results, `ExportResult`, is owned by `runtime/drivers/_export_utils.py` and re-exported from `z_harness_cli/adapters/base.py` to preserve one-way layering — callers must import it from `base`, never from the runtime package directly.

## Key entry points

- `z_harness_cli/adapters/base.py:276` — `COMMAND_CAPABILITY_MATRIX` — nested dict populated at adapter import time; shape `{host_name: {command_id: CommandTier}}`
- `z_harness_cli/adapters/base.py:302` — `register_command_tiers` — called by each adapter module at import; raises `ValueError` if any `KNOWN_COMMANDS` entry is missing
- `z_harness_cli/adapters/base.py:320` — `command_tier` — O(1) lookup; returns `"blocked"` for unknown host or command (fail-safe)
- `z_harness_cli/adapters/base.py:52` — `Capabilities` — frozen dataclass; static per-host flags
- `z_harness_cli/adapters/base.py:42` — `ExportResult` re-export — canonical import location; sourced from `runtime.drivers._export_utils`
- `z_harness_cli/adapters/registry.py:84` — `detect_all` — probes all four adapters; returns `(adapter, DetectResult)` pairs in canonical order
- `z_harness_cli/adapters/registry.py:110` — `select` — host resolution with optional Rich interactive picker; raises `UnknownHostError` / `NoHostInstalledError`
- `z_harness_cli/adapters/claude.py:107` — `ClaudeAdapter` — native-fidelity adapter; `export_payload` is persona-only (native plugin handles commands/skills)
- `z_harness_cli/adapters/antigravity.py:154` — `AntigravityAdapter` — high-fidelity adapter; `export_payload` runs two-stage pipeline (runtime + personas)
- `z_harness_cli/adapters/cursor.py:161` — `CursorAdapter` — flattened adapter; `export_payload` runs two-stage pipeline producing `.mdc` rule files
- `z_harness_cli/adapters/codex.py:182` — `CodexAdapter` — flattened adapter; `export_payload` runs two-stage pipeline producing `prompts/` flat files

## How it interacts with others

- `multi-ide-exports` — the runtime drivers (`runtime/drivers/<host>/export.py`) that Stage 1 of `export_payload` delegates to live in this concept; adapters call into them but never import upward from them
- `z_harness_cli/commands/launch.py` — calls `select()` then `adapter.inject()` / `adapter.launch()` / `adapter.cleanup()`
- `z_harness_cli/commands/export.py` — calls `select()` or looks up by `--host`, then `adapter.export_payload(dest)`
- `z_harness_cli/commands/doctor.py` — uses `detect_all()` and `command_tier()` to report per-host status
- `z_harness_cli/mcp/server.py` — imports `ClaudeAdapter` for native-host MCP registration path

## Export pipeline (per adapter)

### ClaudeAdapter — persona-only
`export_payload` delegates only to `runtime/drivers/claude/persona_export.py::export_persona()` for each file in `personas/`. Commands, agents, and skills are handled natively by the installed Claude Code plugin, not exported to files. Result: `ExportResult(fidelity="native")`.

### AntigravityAdapter, CursorAdapter, CodexAdapter — two-stage pipeline
All three follow the same two-stage structure:

**Stage 1 — runtime export (commands, agents, skills)**
Calls `runtime/drivers/<host>/export.py::export(harness_root, dest)`. If the result has non-empty `warnings`, a `RuntimeError` is raised immediately (legacy hard-gate — the caller sees a failure signal rather than a silent downgrade). Written ids are collected to enable collision detection.

**Stage 2 — persona export loop**
For each `personas/*.md` file, checks that the persona stem does not collide with a Stage-1 exported id (raises `RuntimeError` on collision — MINOR-6). Calls `runtime/drivers/<host>/persona_export.py::export_persona(persona_file, dest)`.

Both stages' file lists are merged into a single `ExportResult`. The fidelity field matches the host's declared tier (`"high"` for antigravity, `"flattened"` for cursor/codex).

### Export layouts

| Host | Commands/skills | Personas |
|------|----------------|---------|
| claude | (native plugin) | `<dest>/personas/<name>.md` |
| antigravity | `.agent/workflows/<id>.md`, `.agent/rules/z-harness-<id>.md`, `.agent/skills/<id>/SKILL.md`, `prompts/<id>.md` | `<dest>/.agent/personas/<name>.md` |
| cursor | `.cursor/rules/<id>.mdc` | `<dest>/.cursor/personas/<name>.mdc` |
| codex | `prompts/<id>.md`, `AGENTS.md` | `<dest>/prompts/personas/<name>.md` |

## Fidelity tiers

| Tier | Meaning |
|------|---------|
| `native` | Full orchestration. All `/z-*` commands run identically to the Claude Code reference. Multi-agent dispatch (subagents, panels, consults, gates) works. |
| `high` | Native skill/persona loading, single-agent only. Multi-agent commands (`/z-implement-all`, `/z-panel`, `/z-consult`, `/z-gate`) degrade to single-agent transliteration (present, not blocked). All other `/z-*` commands run at native fidelity. |
| `flattened` | Transliterated rules, single-agent only. All single-agent `/z-*` commands run in degraded mode. Multi-agent commands are **blocked**. |
| `curated` | **Export-only.** Curated rule/steering files emitted per-command with host-specific frontmatter. No adapter, no launch/inject. `/z-export` only. |
| `pointer` | **Export-only.** Single pointer/instructions file. No adapter, no launch/inject. `/z-export` only. |

## Adapter hosts — fidelity and capabilities

| Host | Binary | Fidelity | `project_mcp` | `user_mcp` | `trust_prompt` | `cwd_override` | cleanup |
|------|--------|----------|---------------|------------|----------------|----------------|---------|
| Claude Code | `claude` | `native` | true | true | false | true | ephemeral |
| Antigravity | `agy` | `high` | false | false | false | false | ephemeral |
| Cursor | `cursor-agent` | `flattened` | true | true | true | false | ephemeral |
| Codex CLI | `codex` | `flattened` | true | false | false | false | ephemeral |

## Export-only hosts

These hosts have no HostAdapter and are **not registered in the adapter registry**. `registry.select(<host>)` raises `UnknownHostError` for them. They cannot be launched or injected — only exported via `/z-export` or `python -m runtime.drivers.<host>.export`.

| Host | Fidelity | Export layout | Structural rule |
|------|----------|---------------|-----------------|
| Windsurf | `curated` | `.windsurf/rules/<id>.md` | YAML frontmatter with `trigger` key required |
| Kiro | `curated` | `.kiro/steering/<id>.md` | YAML frontmatter with `inclusion` key required |
| Cline | `pointer` | `.clinerules/z-harness.md` (1 file) | Plain markdown, non-empty body |
| Copilot | `pointer` | `.github/copilot-instructions.md` (1 file) | Plain markdown, non-empty body |

## Command-tier grid

| Command | claude | antigravity | cursor | codex |
|---------|--------|-------------|--------|-------|
| `/z-implement-all` | native | degraded | blocked | blocked |
| `/z-panel` | native | degraded | blocked | blocked |
| `/z-consult` | native | degraded | blocked | blocked |
| `/z-gate` | native | degraded | blocked | blocked |
| All other `/z-*` | native | native | degraded | degraded |

Multi-agent commands require subagent dispatch; only the `native`-tier Claude Code host provides it. The `high`-tier Antigravity host supports the underlying skills natively but lacks subagent dispatch, so those commands fall back to single-agent transliteration (degraded, not blocked).

## Environment injection

On `ephemeral` injection, each adapter sets the host-appropriate plugin-root env var:

| Host | Env var injected |
|------|-----------------|
| claude | `CLAUDE_PLUGIN_ROOT` |
| antigravity | `ANTIGRAVITY_PLUGIN_ROOT` |
| cursor | `CLAUDE_PLUGIN_ROOT` |
| codex | `CLAUDE_PLUGIN_ROOT` |

## MCP registration (codex and cursor)

Both Codex and Cursor declare `supports_project_mcp=True`. The Codex adapter registers the z-harness MCP server in `~/.codex/config.toml` via `runtime.drivers.codex.mcp.ensure_mcp_registered()`. This write is **global and persistent** — not reversed on ephemeral cleanup. Explicit removal only via `z-harness doctor --clear-mcp`. The Cursor adapter writes `.cursor/mcp.json` (project-scoped) and optionally `~/.cursor/mcp.json` (user-scoped).

## Edge cases / gotchas

- `ClaudeAdapter.export_payload` is persona-only; it does NOT run Stage 1 runtime export. Commands/skills are handled by the installed plugin — exporting them to files is not done and not needed on the native host.
- Non-empty `warnings` from Stage 1 (runtime export) raise `RuntimeError` immediately — this is the legacy hard-gate. Adapters do not silently downgrade or skip validation errors.
- Persona-name collision with a Stage-1 exported id also raises `RuntimeError` (MINOR-6 invariant). The collision domain differs by host: antigravity checks `workflows/rules/skills` stems, cursor checks `.cursor/rules/` stems, codex checks `prompts/` stems.
- `ExportResult` must be imported from `z_harness_cli.adapters.base`, not from `runtime.drivers._export_utils` directly. `base.py` re-exports it as the canonical public surface; importing from runtime breaks the one-way layering rule.
- `cursor` and `codex` both have `fidelity=flattened` but differ in MCP surface: cursor has `supports_user_mcp=True`, codex does not.
- `antigravity` injects `ANTIGRAVITY_PLUGIN_ROOT`; all three other adapters inject `CLAUDE_PLUGIN_ROOT`.
- Codex MCP registration is global (`~/.codex/config.toml`) and survives session cleanup; explicit removal only via `z-harness doctor --clear-mcp`.
- `cursor` has `needs_trust_prompt=True` — `inject()` must not assume non-interactive startup; the PTY must surface the approval prompt to the user.
- Canonical adapter order in registry: `claude` (native) > `antigravity` (high) > `cursor` (flattened) > `codex` (flattened). This order governs the Rich picker display and `select()` tie-breaking.
- `register_command_tiers()` raises `ValueError` at import time if any `KNOWN_COMMANDS` entry is missing from the declared tiers — misconfigured adapters fail fast.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/capabilities-matrix.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
