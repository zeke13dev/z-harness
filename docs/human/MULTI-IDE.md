# Multi IDE Exports

> Last updated: 2026-07-05 (Codex export partial; OMP parity gate remains native)
> Covers source: runtime/drivers/cursor/export.py, runtime/drivers/codex/export.py, runtime/drivers/antigravity/export.py, runtime/drivers/pi/export.py, runtime/drivers/omp/export.py, runtime/drivers/omp/subprocess_driver.py, z_harness_cli/adapters/omp.py, z_harness_cli/adapters/omp_parity_gate.py, z_harness_cli/release_surface.py, scripts/audit-tarball.sh, scripts/pi_assets/, skills/z-export/SKILL.md, .omp/config.yml

## Overview

The public release defaults are intentionally narrow: Claude Code is the primary native plugin surface, OMP is the first-class package/export target, and Codex is a first-class parity-gated plugin/export target. Codex export fidelity is partial because native `SKILL.md`, custom-agent TOML, plugin manifest, `AGENTS.md` reference, and MCP config artifacts are emitted; runtime command orchestration remains flattened/degraded/blocked until Codex native subagent primitive and driver-hook evidence exists. The broader multi-IDE export pipeline remains in source for explicit dev/advanced use and translates z-harness source files (`skills/<id>/SKILL.md`, `agents/`, and `personas/builtin/`) into target-specific files under the requested output directory (the repo default is gitignored `temp/exports/`).

OMP is a **first-class native host** as of T009. The parity gate (`z_harness_cli/adapters/omp_parity_gate.py`) has resolved: `OmpAdapter.fidelity_tier` and `ExportResult.fidelity` are both `"native"`, and four command families — `/z-execute`, `/z-consult`, `/z-gate`, `/z-panel` — are `native`. All other command families are `degraded` (not blocked). Claude Code is the behavioral ground truth; OMP native parity is bounded to the four families with T008 evidence.

OMP export layout is a first-class OMP package under `.omp/z-harness/` with `manifest.yml`, `skills/<id>/SKILL.md`, `rules/<id>.md`, `agents/<id>.md`, and `profiles/<name>.yml`. This is not a pi export variant and must not call `runtime/drivers/pi/export.py` or pi line-rewrite helpers. The checked-in `.omp/config.yml` is never modified by z-harness — it keeps `skills.enableAgentsProject: false` to avoid auto-loading the large root `AGENTS.md`. OMP discovery uses `OMP_PLUGIN_ROOT` pointing at the session-scoped (gitignored) `.omp/z-harness/` package root.

Cursor, Antigravity, pi, Windsurf, Kiro, Cline, and Copilot remain explicit dev/advanced or export-only targets. Installed prod `setup --target all`, prod export auto-selection, and public help text must present Claude, OMP, and Codex as the release-supported defaults instead of treating every exporter as first-class.

## Key entry points

<!-- AUTO-START: entry-points -->
- `runtime/drivers/cursor/export.py` — `export` — Emit and validate Cursor `.mdc` rules; append `-skill` suffix on ID collision.
- `runtime/drivers/codex/export.py` — `export` — Emit Codex `skills/<id>/SKILL.md`, `.codex/agents/<id>.toml`, `.codex-plugin/plugin.json`, `AGENTS.md`, and MCP config; validate custom-agent TOML and optional `CAPABILITIES.md` when present.
- `runtime/drivers/antigravity/export.py` — `export` — Emit and validate all agy surfaces: workflows, rules, skills, prompts, manifest, CAPABILITIES.md, README.md.
- `runtime/drivers/pi/export.py` — `export` — Emit pi agent files, prompts, vendored subagent extension, and AGENTS.md index (export-only; no adapter host).
- `scripts/audit-tarball.sh:90` — `_audit_fail` — Exit 1 immediately when a forbidden tarball pattern is matched.
- `scripts/audit-tarball.sh:98` — `_check_pattern` — Search tarball listing for one forbidden pattern (fixed-string or regex).
- `skills/z-export/SKILL.md:11` — `/z-export` — Entry point: `python3 -m z_harness_cli export --all` for public first-class hosts; cursor/antigravity remain explicit dev/advanced `--surface dev` exports, and pi export runs via direct import of `runtime.drivers.pi.export`.
- `runtime/drivers/cursor/persona_export.py` — `export_persona` — Write persona as `.cursor/personas/<name>.mdc` (context-injection rule; not native to Cursor).
- `runtime/drivers/antigravity/persona_export.py` — `export_persona` — Write persona as `.agent/personas/<name>.md` (native agy persona format).
- `runtime/drivers/codex/persona_export.py` — `export_persona` — Write persona for Codex CLI target.
- `runtime/drivers/omp/export.py` — `export` — Write native OMP package files under `.omp/z-harness/`; returns `ExportResult(fidelity="native")` after T009; must preserve `.omp/config.yml` project-AGENTS suppression and must not reuse pi line rewrites.
- `runtime/drivers/omp/subprocess_driver.py` — `OmpHostDriver` — Native OMP dispatch: `omp -p --model <provider/model> [--profile <profile>] [--session <session-id>] <prompt>`; rejects empty prompts before spawn; normalizes OMP stdout/stderr/events into z-harness result/events; keeps session/rules/profile/model handling separate from consult mode.
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `skills` — adapters enumerate `skills/*/SKILL.md`; Cursor and Codex render them as native skill files; agy emits native `.agent/skills/<id>/SKILL.md`; OMP (native, T009) emits `.omp/z-harness/skills/<id>/SKILL.md`.
- `agents` — adapters enumerate agent definitions; pi exports them as compatibility agent files, Codex exports custom-agent TOML plus an `AGENTS.md` fallback/reference, and OMP export emits OMP package `agents/<id>.md` resources with no pi line rewrites; the 4 native OMP command families (z-execute/z-consult/z-gate/z-panel) cover multi-agent dispatch.
- `personas-and-roles` — persona files under `personas/builtin/` are exported after the main adapter via `runtime/drivers/<target>/persona_export.py` or, for OMP, profile resources under `.omp/z-harness/profiles/`.
- `capabilities-matrix` — controls adapter fidelity, export fidelity, and command tiers; OMP uses Claude Code as the parity target; Codex keeps adapter fidelity flattened while export fidelity is partial.
- `scripts` — `audit-tarball.sh` remains the export safety gate for packaged artifacts. The legacy per-target `scripts/export-*.py` scripts have been removed.
- `runtime-drivers` — `runtime/drivers/<target>/export.py` is the current export path for all current targets; `runtime/drivers/omp/export.py` provides native OMP package export (T009), while `runtime/drivers/omp/subprocess_driver.py` provides native OMP dispatch (T007); both must remain separate from pi export and `scripts/omp-consult.sh` compatibility.

## Edge cases / gotchas

- The legacy adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) have been removed. Use `runtime/drivers/<target>/export.py` directly or via `python3 -m z_harness_cli export --host <target>`.
- Tarball exclusion policy lives in `scripts/audit-tarball.sh`, not in the export drivers.
- Codex exports custom-agent definitions under `.codex/agents/` and keeps `AGENTS.md` as a fallback/reference. Current Codex CLI dispatch has no proven z-harness native subagent primitive, so command orchestration remains flattened/degraded/blocked.
- Antigravity emits the most surfaces: workflows, rules, native skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- Unsupported constructs (`Agent(...)`, `Skill(...)`, `AskUserQuestion(...)`, `TaskCreate(...)`, `SubagentCreate(...)`) are replaced line-by-line with target-specific comments — never silently dropped.
- Cursor and Codex append a `-skill` suffix if a skill ID collides with an agent ID in the export output; agy flat prompts use a `skill-` prefix to avoid collisions. Legacy command/skill collision handling is obsolete because the `commands/` source directory is gone.
- `agy-plugin.yaml` is a z-harness convention manifest; Antigravity does not read it natively.
- `_ALWAYS_ON_AGENTS` in `runtime/drivers/antigravity/export.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`; all other agents get `model_decision` trigger.
- Antigravity workflow bodies have an ~12,000 character limit; several z-harness commands exceed it.
- pi is an export-only target: it has no adapter, is not a launch/inject host, and does not support `--host pi` via the CLI. Its export runs through `runtime/drivers/pi/export.py` via direct import.
- Cursor has no native persona mechanism; personas are exported as `alwaysApply: true` glob-matched `.mdc` rules under `.cursor/personas/`.
- `/z-export` itself performs no direct file I/O; all writes are delegated to the adapter scripts and the `persona_export.py` modules.
- pi is a separate export target with its own exporter (`runtime/drivers/pi/export.py`), its own assets (`scripts/pi_assets/`), and its own capabilities source doc (`scripts/pi_assets/CAPABILITIES.md`). Unlike Cursor/Codex/agy, pi uses a vendored subagent extension for fan-out dispatch. See `docs/human/pi-export.md`. pi is export-only: no adapter, no launch/inject host support.
- OMP is a first-class native host (T009): `OmpAdapter.fidelity_tier` = `"native"`, `ExportResult.fidelity` = `"native"`, and four command families are native. OMP export is NOT pi export — it uses `.omp/z-harness/` discovery with no pi line rewrites. `.omp/config.yml` is never modified by z-harness.
- OMP native dispatch (`OmpHostDriver`, T007) is not OMP consult-provider compatibility. `scripts/omp-consult.sh` deliberately uses `--no-rules --no-session` for advisory consultant providers; native command dispatch keeps rules/session semantics and uses explicit `OMP_PLUGIN_ROOT` discovery. The two paths must not be conflated.
- Subagent YAML dispatch bug (resolved 2026-06-08): pi's frontmatter.js parser could fail on unquoted colons in YAML description values (triggered by "subagent `tasks: [...]`" in explore.md). Three-layer fix: pi runtime patch + source quoting in pi_assets + `_yaml_quote` in `runtime/drivers/pi/export.py` for all generated agents. Fully resolved.

## Examples

- `python3 -m z_harness_cli export --host omp --out temp/exports/omp --force` — native OMP export (T009); regenerates `temp/exports/omp/.omp/z-harness/` package files with `ExportResult(fidelity="native")`.
- `Z_HARNESS_RELEASE_SURFACE=prod python3 -m z_harness_cli export --all` — exports installed release-supported adapter hosts (Claude/OMP/Codex) only.
- `python3 -m z_harness_cli export --host cursor --surface dev` — explicit dev/advanced Cursor export.
- `python3 -m z_harness_cli export --host codex --surface prod` — first-class partial Codex export; runtime orchestration remains limited.
- `python3 -m z_harness_cli export --host antigravity --surface dev` — explicit dev/advanced Antigravity export.
- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('temp/exports/pi'))"` — regenerates the full `temp/exports/pi/` tree (pi is export-only; no launch/inject host support).
- `python3 -m pytest tests/adapters/test_omp_adapter.py tests/drivers/test_omp_export_driver.py runtime/tests/test_omp_driver.py runtime/tests/test_omp_parity.py runtime/tests/test_omp_export.py tests/conformance/test_strict.py -q` — run the full OMP adapter/export/runtime/orchestration test suite (all must pass).
- `bash scripts/audit-tarball.sh myexport.tar.gz` — verifies a tarball contains no forbidden paths before distribution.
