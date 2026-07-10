# Host Capabilities Matrix

> Last updated: 2026-07-05 (Codex export partial; OMP parity gate remains resolved)
> Covers source: z_harness_cli/adapters/base.py, z_harness_cli/adapters/registry.py, z_harness_cli/adapters/claude.py, z_harness_cli/adapters/antigravity.py, z_harness_cli/adapters/cursor.py, z_harness_cli/adapters/codex.py, z_harness_cli/adapters/omp.py, z_harness_cli/adapters/omp_parity_gate.py, runtime/drivers/codex/probe.py, runtime/drivers/omp/export.py, runtime/drivers/omp/subprocess_driver.py, runtime/drivers/windsurf/export.py, runtime/drivers/kiro/export.py, runtime/drivers/cline/export.py, runtime/drivers/copilot/export.py, .omp/config.yml

## Overview

The capabilities matrix describes how completely z-harness features work on each supported host. There are three categories of hosts:

> **Not to be confused with model-routing host families.** This document's "host" is the
> adapter/export host selected by `z_harness_cli/adapters/registry.py::detect_all()` / an
> explicit `--host` flag (for `launch`/`export`/`doctor`). A separate, unrelated mechanism —
> `scripts/detect-host.sh` / `Z_HARNESS_HOST`, which powers `model_classes`' host-keyed
> `(model, effort)` resolution in `[model_routing]` — happens to use the same host-id vocabulary
> (`claude`/`pi`/`codex`/`cursor`/`antigravity`) but is looked up independently and collapses to
> just two model *families*: `claude` and `omp` (every other id). See
> [config.md — host-aware model classes](config.md#the-knobs-models-model_classes-and-model_routing-sections)
> for that mechanism.

**Native adapter hosts** (Claude Code) — these have a `HostAdapter`, native launch/inject support, export support, and per-command capability evidence. **Claude Code is the ground-truth parity target**: an OMP command may become `native` only when its observable adapter, export, dispatch, event, gate, and cleanup behavior matches the Claude Code reference for that command family.

**Adapter/export hosts** (OMP native for 4 families, Antigravity/agy, Cursor, Codex CLI) — these have a `HostAdapter` class in `z_harness_cli/adapters/`, can be launched/injected, and are registered in the adapter registry. Each is assigned a **fidelity tier** and per-command tiers that tell callers whether a given `/z-*` command runs natively, in degraded mode, or is blocked entirely. OMP's parity gate (T009) has resolved: `OmpAdapter.fidelity_tier` and OMP `ExportResult.fidelity` are now `native`, and four command families — `/z-execute`, `/z-consult`, `/z-gate`, `/z-panel` — are promoted to `native`. All remaining OMP command families stay `degraded` (not blocked) until further parity evidence is added. Claude Code remains the ground-truth parity target.

**Export-only hosts** (Windsurf, Kiro, Cline, Copilot, and legacy pi) — these have a runtime export driver in `runtime/drivers/<host>/export.py` but **no HostAdapter, no adapter-registry entry, and no launch/inject support**. They can only be used via `/z-export` or the runtime CLI. They are not in the `COMMAND_CAPABILITY_MATRIX` and will never be.

The `COMMAND_CAPABILITY_MATRIX` dict in `base.py` is populated at import time by each adapter's `register_command_tiers()` call; `command_tier(host, cmd)` provides fail-safe O(1) lookup (unknown = blocked).

The adapters also declare static `Capabilities` flags covering MCP support, trust-prompt behavior, cwd-override support, and cleanup strategy. These flags drive injection and launch decisions in the CLI commands (`launch.py`, `export.py`, `doctor.py`). The canonical type for export results, `ExportResult`, is owned by `runtime/drivers/_export_utils.py` and re-exported from `z_harness_cli/adapters/base.py` to preserve one-way layering — callers must import it from `base`, never from the runtime package directly.

OMP is tracked here as a first-class host whose native claims are bounded by the parity gate (T009, `z_harness_cli/adapters/omp_parity_gate.py`). The three synchronized surfaces — `OmpAdapter.fidelity_tier`, `ExportResult.fidelity` from the OMP exporter, and `COMMAND_CAPABILITY_MATRIX["omp"]` — all read from the gate. Command families in `PARITY_EVIDENCE` promote to `native` only when their T008 test class is importable; removing that class immediately downgrades the family.

Codex is tracked as a first-class host with explicit probe-backed surface separation. The checked-in adapter path is still the Codex CLI path and remains flattened; export fidelity is partial because the runtime exporter emits native `SKILL.md`, custom-agent TOML, plugin manifest, `AGENTS.md` reference, and MCP config artifacts. `runtime/drivers/codex/probe.py` emits `codex_capabilities` fields for app/plugin multi-agent support, CLI-visible agent support, AskUser/gate support, and event-frame support. Codex app/plugin capability and Codex CLI capability must not be conflated; command-family claims require the relevant probe fields plus later parity evidence.

Drift verification for this contract refresh (2026-07-05): `omp_adapter_fidelity()` still returns `"native"` (all 4 PARITY_EVIDENCE entries resolve); OMP command tiers remain `native` for `/z-execute`, `/z-consult`, `/z-gate`, `/z-panel` and `degraded` for all others. Codex gate state is `adapter=flattened`, `export=partial`, native subagent primitive `false`; app/plugin multi-agent evidence is separate from Codex CLI agent, AskUser/gate, and event-frame evidence.

## Key entry points

- `z_harness_cli/adapters/base.py:276` — `COMMAND_CAPABILITY_MATRIX` — nested dict populated at adapter import time; shape `{host_name: {command_id: CommandTier}}`
- `z_harness_cli/adapters/base.py:302` — `register_command_tiers` — called by each adapter module at import; raises `ValueError` if any `KNOWN_COMMANDS` entry is missing
- `z_harness_cli/adapters/base.py:320` — `command_tier` — O(1) lookup; returns `"blocked"` for unknown host or command (fail-safe)
- `z_harness_cli/adapters/base.py:52` — `Capabilities` — frozen dataclass; static per-host flags
- `z_harness_cli/adapters/base.py:42` — `ExportResult` re-export — canonical import location; sourced from `runtime.drivers._export_utils`
- `z_harness_cli/adapters/omp_parity_gate.py` — `omp_adapter_fidelity`, `omp_command_tier`, `omp_export_fidelity` — single source of truth for OMP fidelity and command tiers; keyed off T008 test class presence (T009 gate). Removing a T008 class immediately downgrades the corresponding family.
- `z_harness_cli/adapters/registry.py:84` — `detect_all` — probes all five adapters including OMP; returns `(adapter, DetectResult)` pairs in canonical order
- `z_harness_cli/adapters/registry.py:110` — `select` — host resolution with optional Rich interactive picker; raises `UnknownHostError` / `NoHostInstalledError`
- `z_harness_cli/adapters/claude.py:107` — `ClaudeAdapter` — native-fidelity adapter; `export_payload` is persona-only (native plugin handles skills natively)
- `z_harness_cli/adapters/antigravity.py:154` — `AntigravityAdapter` — high-fidelity adapter; `export_payload` runs two-stage pipeline (runtime + personas)
- `z_harness_cli/adapters/cursor.py:161` — `CursorAdapter` — flattened adapter; `export_payload` runs two-stage pipeline producing native `.cursor/skills/<id>/SKILL.md` files plus one generated always-apply `.cursor/rules/z-harness-skills.mdc` index and AGENT `.mdc` rule files
- `z_harness_cli/adapters/codex.py:182` — `CodexAdapter` — gate-driven adapter with flattened default; `export_payload` runs two-stage pipeline producing `skills/<id>/SKILL.md`, `.codex/agents/<id>.toml`, `.codex-plugin/plugin.json`, `AGENTS.md`, MCP config, and persona prompts
- `runtime/drivers/codex/probe.py` — `ProbeResults.codex_capabilities` / `CodexCapabilityContract` — evidence-backed Codex surface contract: app/plugin multi-agent support, CLI-visible agent support, AskUser/gate support, event-frame support, and `support_tier`
- `z_harness_cli/adapters/omp.py:109` — `OmpAdapter` — OMP host adapter; fidelity tier and command tiers read from the parity gate (T009 complete). `fidelity_tier` returns `"native"` now that all four T008 evidence entries resolve; four command families are `native`; all others `degraded`.
- `runtime/drivers/omp/export.py:199` — `export` — Emit OMP package/discovery layout under `.omp/z-harness/` plus `.omp/config.yml`; returns `ExportResult(fidelity="native")` after T009; must not call `runtime/drivers/pi/export.py`.
- `runtime/drivers/omp/subprocess_driver.py` — `OmpHostDriver` — Native OMP dispatch driver: frozen argv/prompt-transport/event/session/model contract; dispatch path is separate from `scripts/omp-consult.sh`.

## How it interacts with others

- `multi-ide-exports` — the runtime drivers (`runtime/drivers/<host>/export.py`) that Stage 1 of `export_payload` delegates to live in this concept; adapters call into them but never import upward from them
- `z_harness_cli/commands/launch.py` — calls `select()` then `adapter.inject()` / `adapter.launch()` / `adapter.cleanup()`
- `z_harness_cli/commands/export.py` — calls `select()` or looks up by `--host`, then `adapter.export_payload(dest)`
- `z_harness_cli/commands/doctor.py` — uses `detect_all()` and `command_tier()` to report per-host status
- `z_harness_cli/mcp/server.py` — imports `ClaudeAdapter` for native-host MCP registration path
- `runtime.drivers.select_driver("omp")` — resolves the `OmpHostDriver`; native dispatch is live after T007/T009. Native OMP execution must not call `scripts/omp-consult.sh` or any pi export prompt-render helpers.

## Export pipeline (per adapter)

### ClaudeAdapter — persona-only
`export_payload` delegates only to `runtime/drivers/claude/persona_export.py::export_persona()` for each file in `personas/`. Skills are handled natively by the installed Claude Code plugin (reading directly from `skills/<id>/SKILL.md`), not exported to files. Result: `ExportResult(fidelity="native")`.

### AntigravityAdapter, CursorAdapter, CodexAdapter — two-stage pipeline
All three follow the same two-stage structure:

**Stage 1 — runtime export (skills, agents, and target-specific artifacts)**
Calls `runtime/drivers/<host>/export.py::export(harness_root, dest)`. If the result has non-empty `warnings`, a `RuntimeError` is raised immediately (legacy hard-gate — the caller sees a failure signal rather than a silent downgrade). Written ids are collected to enable collision detection.

**Stage 2 — persona export loop**
For each `personas/*.md` file, checks that the persona stem does not collide with a Stage-1 exported id (raises `RuntimeError` on collision — MINOR-6). Calls `runtime/drivers/<host>/persona_export.py::export_persona(persona_file, dest)`.

Both stages' file lists are merged into a single `ExportResult`. The fidelity field matches the host's declared tier for Antigravity/Cursor (`"high"` / `"flattened"`); Codex reads export fidelity from `codex_parity_gate` and currently reports `"partial"` while the adapter tier remains `"flattened"`.

### OmpAdapter — native OMP package export (T009 complete)
`export_payload` delegates to `runtime/drivers/omp/export.py::export(harness_root, dest)`, which writes `.omp/config.yml` plus the `.omp/z-harness/` package (`manifest.yml`, `skills/`, `rules/`, `prompts/`, `agents/`, `profiles/`). The runtime exporter returns `ExportResult(fidelity="native")` after T009. `OmpAdapter.fidelity_tier` is now `"native"`. Four command families are `native` (`/z-execute`, `/z-consult`, `/z-gate`, `/z-panel`); all remaining families are `degraded`. This path is not `scripts/omp-consult.sh`; the consult shim remains provider compatibility only.

### Export layouts

All export artifacts are generated on demand and never committed. `skills/` is the only committed source tier.

| Host | Skills / rules | Agents | Personas / profiles |
|------|----------------|--------|---------------------|
| claude | (native plugin reads `skills/<id>/SKILL.md`) | (native plugin) | `<dest>/personas/<name>.md` |
| omp (native adapter/export; 4 native command families) | `<dest>/.omp/z-harness/skills/<id>/SKILL.md`; `<dest>/.omp/z-harness/rules/<id>.md`; `<dest>/.omp/z-harness/prompts/<id>.md`; package manifest under `<dest>/.omp/z-harness/manifest.yml` | `<dest>/.omp/z-harness/agents/<id>.md` with OMP-native metadata, no pi line rewrites | `<dest>/.omp/z-harness/profiles/<name>.yml`; `.omp/config.yml` preserved as-is (project AGENTS suppression kept); discovery via `OMP_PLUGIN_ROOT` |
| antigravity | `.agent/skills/<id>/SKILL.md` | `.agent/workflows/<id>.md`, `.agent/rules/z-harness-<id>.md`, `prompts/<id>.md` | `<dest>/.agent/personas/<name>.md` |
| cursor | `.cursor/skills/<id>/SKILL.md` (verbatim, no transliteration) + `.cursor/rules/z-harness-skills.mdc` (index, always-apply) | `.cursor/rules/<id>.mdc` | `<dest>/.cursor/personas/<name>.mdc` |
| codex (adapter flattened; export partial) | `skills/<id>/SKILL.md` plus `.codex-plugin/plugin.json` and `mcp_config.json` | `.codex/agents/<id>.toml` plus `AGENTS.md` fallback/reference | `<dest>/prompts/personas/<name>.md` |

## Fidelity tiers

| Tier | Meaning |
|------|---------|
| `native` | Full orchestration. All `/z-*` commands run identically to the Claude Code reference. Multi-agent dispatch (subagents, panels, consults, gates) works. |
| `partial` | Adapter/export support implemented but parity not yet proven. Retained as a tier for future candidate hosts; OMP has since advanced to `native` via T009. |
| `high` | Native skill/persona loading, single-agent only. Multi-agent commands (`/z-execute`, `/z-panel`, `/z-consult`, `/z-gate`) degrade to single-agent transliteration (present, not blocked). All other `/z-*` commands run at native fidelity. |
| `flattened` | Transliterated rules, single-agent only. All single-agent `/z-*` commands run in degraded mode. Multi-agent commands are **blocked**. |
| `curated` | **Export-only.** Curated rule/steering files emitted per-command with host-specific frontmatter. No adapter, no launch/inject. `/z-export` only. |
| `pointer` | **Export-only.** Single pointer/instructions file. No adapter, no launch/inject. `/z-export` only. |

OMP's adapter and export fidelity are now `native` (T009 complete). **Only** the four families with T008 parity evidence — `/z-execute`, `/z-consult`, `/z-gate`, `/z-panel` — are `native`. All other families are `degraded`. Promoting any additional family requires adding a corresponding entry to `PARITY_EVIDENCE` in `omp_parity_gate.py` and a matching T008 test class.

## Codex capability probe contract

`runtime/drivers/codex/probe.py` writes the legacy session-resume and cross-env collision fields unchanged, plus a nested `codex_capabilities` contract. Each capability field has `status` (`supported`, `unsupported`, or `unknown`), `surface`, and concise `evidence`. The `support_tier` is a summary classification only; it does not promote command tiers by itself.

| Probe field | Surface | Evidence source | Claim boundary |
|-------------|---------|-----------------|----------------|
| `app_plugin_multi_agent_support` | Codex app/plugin | `codex features list` row for `multi_agent` | Indicates app/plugin multi-agent availability only; it is not proof that `codex exec` exposes CLI agent dispatch. |
| `cli_visible_agent_support` | Codex CLI | `codex exec --help` agent/subagent flags or commands | Required before treating Codex CLI as a candidate for native subagent dispatch. |
| `ask_user_gate_support` | Codex CLI | `codex exec --help` AskUser/gate/approval markers | Required before mapping z-harness gates onto Codex CLI. |
| `event_frame_support` | Codex CLI stream | `codex exec --help` `--json`/JSONL/event-frame output | Required before preserving native Codex event frames in the runtime driver. |
| `support_tier` | Derived | The four fields above | One of `unknown`, `flattened_cli`, `cli_partial`, `cli_native_candidate`, `app_plugin_multi_agent_cli_degraded`, or `full_native_candidate`. |

The current Codex adapter matrix still describes the shipped CLI adapter tier. A probe result of `app_plugin_multi_agent_cli_degraded` means the app/plugin surface has multi-agent evidence while the CLI surface remains degraded; a `cli_native_candidate` or `full_native_candidate` result still needs later parity-gate evidence plus a `CodexDriver.dispatch_native_subagent` hook before command families can be promoted.

## Adapter hosts — fidelity and capabilities

| Host | Binary | Fidelity | `project_mcp` | `user_mcp` | `trust_prompt` | `cwd_override` | cleanup |
|------|--------|----------|---------------|------------|----------------|----------------|---------|
| Claude Code | `claude` | `native` | true | true | false | true | ephemeral |
| OMP | `omp` | `native` (T009; 4 native families: z-execute/z-consult/z-gate/z-panel; all others degraded) | false | false | false | false | ephemeral |
| Antigravity | `agy` | `high` | false | false | false | false | ephemeral |
| Cursor | `cursor-agent` | `flattened` | true | true | true | false | ephemeral |
| Codex CLI | `codex` | `flattened` adapter; `partial` export (probe `support_tier` is separate evidence) | true | false | false | false | ephemeral |

## Export-only hosts

These hosts have no HostAdapter and are **not registered in the adapter registry**. `registry.select(<host>)` raises `UnknownHostError` for them. They cannot be launched or injected — only exported via `/z-export` or direct runtime-driver import.

| Host | Fidelity | Export layout | Structural rule |
|------|----------|---------------|-----------------|
| pi | `high` export fidelity, but export-only | `agents/`, `prompts/`, `AGENTS.md`, vendored `extensions/subagent/` | Compatibility export only; no HostAdapter, HostDriver, launch/inject, or native OMP parity claim |
| Windsurf | `curated` | `.windsurf/rules/<id>.md` | YAML frontmatter with `trigger` key required |
| Kiro | `curated` | `.kiro/steering/<id>.md` | YAML frontmatter with `inclusion` key required |
| Cline | `pointer` | `.clinerules/z-harness.md` (1 file) | Plain markdown, non-empty body |
| Copilot | `pointer` | `.github/copilot-instructions.md` (1 file) | Plain markdown, non-empty body |

## Command-tier grid

| Command family | claude | omp (T009 resolved) | antigravity | cursor | codex | Notes |
|----------------|--------|---------------------|-------------|--------|-------|-------|
| `/z-execute` (task orchestration) | native | **native** | degraded | blocked | blocked | Proven by T008: TestSubagentFanOutParity + TestMultiAgentCommandPath. |
| `/z-consult` (consultant roles) | native | **native** | degraded | blocked | blocked | Proven by T008: TestConsultantDispatchIsolation. `scripts/omp-consult.sh` is provider-compatibility only — not native dispatch. |
| `/z-gate` (user gates / AskUser) | native | **native** | degraded | blocked | blocked | Proven by T008: TestAskUserGateParity. |
| `/z-panel` (multi-agent panels) | native | **native** | degraded | blocked | blocked | Proven by T008: TestSubagentFanOutParity (shared fan-out evidence with z-execute). |
| Planning/audit/debug (`/z-plan`, `/z-brainstorm`, `/z-audit`, `/z-test`, `/z-review-all`) | native | degraded | degraded | blocked | degraded | No T008 evidence yet; runs in degraded mode. To promote, add PARITY_EVIDENCE entry + T008 class. |
| Export/doctor/detect (`/z-export`, `/z-doctor`, registry selection) | native | degraded (export fidelity = native) | native | degraded | degraded | `select(host="omp")`, `doctor`, and `ExportResult.fidelity` agree. Command tier stays `degraded` pending behavior evidence. |
| Single-agent local commands (`/z-status`, `/z-fix`, `/z-update`, etc.) | native | degraded | native | degraded | degraded | No T008 evidence yet; runs in degraded mode. |

Unknown or unmapped OMP command families default to `degraded`. A command family is promoted only when a T008 test class is added to `PARITY_EVIDENCE` in `omp_parity_gate.py` for that family; removing a T008 class immediately downgrades the family.

Multi-agent commands require subagent dispatch. Claude Code provides the reference implementation, and OMP command families are promoted only where its parity gate has evidence. The `high`-tier Antigravity host supports the underlying skills natively but lacks subagent dispatch, so those commands fall back to single-agent transliteration (degraded, not blocked). The Codex column is the Codex CLI adapter tier: app/plugin multi-agent evidence and custom-agent export do not promote CLI command families unless CLI-visible agent, AskUser/gate, event-frame, parity evidence, and the runtime driver hook also exist.

## Environment injection

On `ephemeral` injection, each adapter sets the host-appropriate plugin-root env var:

| Host | Env var injected |
|------|-----------------|
| claude | `CLAUDE_PLUGIN_ROOT` |
| omp | `OMP_PLUGIN_ROOT` pointing at the session-scoped OMP package root; optional profile/model values are passed as explicit argv/config fields, never logged as full env dumps |
| antigravity | `ANTIGRAVITY_PLUGIN_ROOT` |
| cursor | `CLAUDE_PLUGIN_ROOT` |
| codex | `CLAUDE_PLUGIN_ROOT` |

The repo's checked-in `.omp/config.yml` deliberately keeps `skills.enableAgentsProject: false` so OMP does not auto-load the large root `AGENTS.md`. Native OMP support preserves that outcome: z-harness **does not modify `.omp/config.yml`**. Discovery comes from `OMP_PLUGIN_ROOT` pointing at the session-scoped `.omp/z-harness/` package (written by `inject()` as a gitignored `session.yml`). For export, `python3 -m z_harness_cli export --host omp` writes the full `.omp/z-harness/` package layout without touching `.omp/config.yml`.

## MCP registration (codex and cursor)

Both Codex and Cursor declare `supports_project_mcp=True`. The Codex adapter registers the z-harness MCP server in `~/.codex/config.toml` via `runtime.drivers.codex.mcp.ensure_mcp_registered()`. This write is **global and persistent** — not reversed on ephemeral cleanup. Explicit removal only via `z-harness doctor --clear-mcp`. The Cursor adapter writes `.cursor/mcp.json` (project-scoped) and optionally `~/.cursor/mcp.json` (user-scoped).

## OMP native dispatch contract (T009 complete)

Native OMP dispatch is live (`OmpHostDriver`, T007). This is the frozen runtime-driver contract, separate from the `scripts/omp-consult.sh` shim:

- **argv**: `omp -p --model <provider/model> [--profile <profile>] [--session <session-id>] <prompt>` for non-interactive command dispatch; interactive launch uses `omp` rooted in the requested project directory with `OMP_PLUGIN_ROOT` set. The driver rejects an empty or whitespace-only prompt before spawning.
- **prompt transport**: prompt text is passed as the final positional argument because current `omp` print mode ignores piped stdin. The driver owns quoting/argument boundaries and must not shell-concatenate prompts.
- **rules/session/profile/model**: native command mode keeps rules enabled through the explicit package root, preserves or resumes the supplied OMP session id when one is requested, passes profile/model selections explicitly, and redacts profile/model/OAuth-derived values from telemetry. Consult compatibility remains the only path that uses `--no-rules --no-session`.
- **output**: final assistant text is exposed as the command result `stdout`; stderr is preserved separately; non-zero exit or empty required output becomes an error result with the OMP exit code and a bounded stderr summary.
- **events**: the driver normalizes host events into ordered JSON objects with `{driver:"omp", command_id, session_id, sequence, kind, payload}`. Required kinds are `dispatch_start`, `prompt_submitted`, `assistant_delta`, `tool_start`, `tool_end`, `subagent_start`, `subagent_end`, `ask_user`, `final_result`, and `dispatch_end`. Payloads enumerate fields explicitly and never include full env/config dumps, OAuth tokens, or raw model credential material.
- **mapping**: OMP AskUser prompts map to z-harness user gates; OMP subagent/tool events map to the same orchestration semantics that Claude Code emits. Missing event support blocks promotion of the affected command family.

## OMP parity gate (T009 — resolved)

The gate is implemented in `z_harness_cli/adapters/omp_parity_gate.py` (`PARITY_EVIDENCE` dict). It controls three surfaces simultaneously:

1. `OmpAdapter.fidelity_tier` (via `omp_adapter_fidelity()`).
2. `runtime.drivers.omp.export.export(...).fidelity` (via `omp_export_fidelity()`).
3. `COMMAND_CAPABILITY_MATRIX["omp"]` per-command (via `omp_command_tier()`).

T009 is complete: all four `PARITY_EVIDENCE` entries resolve (T008 test classes are importable), so surfaces 1 and 2 return `"native"`. Command families in `PARITY_EVIDENCE` return `"native"`; families in `DEGRADED_FAMILIES` or unlisted families return `"degraded"`; a family listed in `PARITY_EVIDENCE` whose test class is missing (broken evidence) returns `"blocked"`.

Verification commands (all must pass):
```bash
python3 -m pytest tests/adapters/test_omp_adapter.py tests/drivers/test_omp_export_driver.py runtime/tests/test_omp_driver.py runtime/tests/test_omp_parity.py runtime/tests/test_omp_export.py tests/conformance/test_strict.py -q
```

## Edge cases / gotchas

- `ClaudeAdapter.export_payload` is persona-only; it does NOT run Stage 1 runtime export. Skills are handled by the installed plugin reading `skills/<id>/SKILL.md` natively — exporting them to files is not done and not needed on the native host.
- Non-empty `warnings` from Stage 1 (runtime export) raise `RuntimeError` immediately — this is the legacy hard-gate. Adapters do not silently downgrade or skip validation errors.
- Persona-name collision with a Stage-1 exported id also raises `RuntimeError` (MINOR-6 invariant). The collision domain differs by host: antigravity checks `workflows/rules/skills` stems, cursor checks `.cursor/rules/` stems, codex checks `prompts/` stems.
- `ExportResult` must be imported from `z_harness_cli.adapters.base`, not from `runtime.drivers._export_utils` directly. `base.py` re-exports it as the canonical public surface; importing from runtime breaks the one-way layering rule.
- `cursor` and the Codex CLI adapter both currently resolve to adapter `fidelity=flattened` by default but differ in MCP surface: cursor has `supports_user_mcp=True`, codex does not. Codex export fidelity is partial, and app/plugin multi-agent evidence lives in `ProbeResults.codex_capabilities`; neither should be substituted for CLI command parity.
- `antigravity` injects `ANTIGRAVITY_PLUGIN_ROOT`; all three other adapters inject `CLAUDE_PLUGIN_ROOT`.
- Codex MCP registration is global (`~/.codex/config.toml`) and survives session cleanup; explicit removal only via `z-harness doctor --clear-mcp`.
- `cursor` has `needs_trust_prompt=True` — `inject()` must not assume non-interactive startup; the PTY must surface the approval prompt to the user.
- Canonical adapter order in registry: `claude` (native) > `antigravity` (high) > `cursor` (flattened) > `codex` (gate-driven, flattened default) > `omp` (native adapter; last in order). This order governs the Rich picker display and `select()` tie-breaking.
- `register_command_tiers()` raises `ValueError` at import time if any `KNOWN_COMMANDS` entry is missing from the declared tiers — misconfigured adapters fail fast.
- OMP support is not the legacy pi export path. It must not use `runtime/drivers/pi/export.py`, pi prompt rewrites, `scripts/pi_assets/`, or the vendored pi subagent extension.
- OMP support is not OMP consult-provider compatibility. `scripts/omp-consult.sh` exists only to adapt provider-registry stdin prompts into `omp -p --no-session --no-rules --model ... <prompt>` for consultant roles.
- `.omp/config.yml` remains intentionally small and suppresses project AGENTS autoloading; OMP discovery must be explicit through the plugin package root.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/capabilities-matrix.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
