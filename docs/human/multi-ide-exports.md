# multi-ide-exports

> Last updated: 2026-06-24
> Covers source: runtime/drivers/_export_utils.py, runtime/drivers/cursor/export.py, runtime/drivers/codex/export.py, runtime/drivers/antigravity/export.py, runtime/drivers/pi/export.py, runtime/drivers/omp/export.py, z_harness_cli/adapters/base.py, z_harness_cli/adapters/cursor.py, z_harness_cli/adapters/codex.py, z_harness_cli/adapters/antigravity.py, z_harness_cli/adapters/omp.py, skills/z-export/SKILL.md, .omp/config.yml

## Overview

The multi-IDE export pipeline translates z-harness source files (`skills/<id>/SKILL.md`, `agents/`, and `personas/builtin/`) into target-specific layouts. Runtime drivers still accept arbitrary `export_root` values, but `/z-export` now writes the canonical mirrors under `exports/<target>/` sequentially for every requested target. `skills/` is the only hand-authored committed source tier. Each export target has a dedicated driver at `runtime/drivers/<target>/export.py` that exposes a uniform `export(repo_root, export_root, *, options=None) -> ExportResult` signature. The canonical `ExportResult` dataclass (`dest`, `files`, `fidelity`, `warnings`) is defined in `runtime/drivers/_export_utils.py` and re-exported from `z_harness_cli/adapters/base.py` so CLI-layer code does not import upward from runtime internals.

The current shipped targets are Cursor (`fidelity="flattened"`, native `.cursor/skills/<id>/SKILL.md` + one generated always-apply `.cursor/rules/z-harness-skills.mdc` index), Codex CLI (`fidelity="flattened"`, native `skills/<id>/SKILL.md` under the export root), Antigravity/agy (`fidelity="high"`, `.agent/skills/<id>/SKILL.md` native layout + flat `prompts/`), OMP (`fidelity="partial"`, `.omp/config.yml` plus `.omp/z-harness/{manifest.yml,skills,rules,prompts,agents,profiles}`), and pi (`fidelity="high"`, `agents/`, `prompts/`, vendored subagent extension). pi is an export-only target with no adapter, HostDriver, or launch/inject support.

OMP export is an implemented first-class host path, not a pi export variant and not native parity. It emits an OMP package/discovery layout under `.omp/z-harness/`, returns `ExportResult.fidelity="partial"` in lockstep with `OmpAdapter.fidelity_tier`, and cannot claim `native` until the capabilities parity gate proves Claude Code-equivalent behavior for adapter, export, command tiers, launch, dispatch, events, and gates. Multi-agent commands remain blocked and single-agent commands degraded until that T009/native parity evidence exists. For Cursor, Codex, agy, and OMP, each `z_harness_cli/adapters/<host>.py` adapter's `export_payload()` delegates to the runtime `export()` for skills and agents; Cursor/Codex/agy then run a persona loop, while OMP writes profiles from the OMP exporter. To refresh the canonical mirrors, run `/z-export` or `python3 -m z_harness_cli export --host <host>`.

## Key entry points

- `runtime/drivers/_export_utils.py:62` — `ExportResult` — Canonical export result dataclass (dest, files, fidelity, warnings); owned by runtime, re-exported from `z_harness_cli/adapters/base.py`.
- `runtime/drivers/_export_utils.py:316` — `enumerate_sources` — Collect skills and agents from `skills/` and `agents/` into a kind-keyed dict; keeps a back-compat `commands` key (always empty) so deferred export drivers do not KeyError.
- `runtime/drivers/_export_utils.py:246` — `inline_includes` — Public alias for `expand_includes`; `base_dir` accepted but unused (resolution is always relative to `repo_root`).
- `runtime/drivers/_export_utils.py:183` — `expand_includes` — Inline `<!-- include: path -->` markers recursively; skips fenced code blocks; raises on missing fragment or cycle.
- `runtime/drivers/_export_utils.py:392` — `output_path_for` — Compute conventional output path for `cursor` or `codex` targets; `agy` intentionally absent (owns its dual layout).
- `runtime/drivers/_export_utils.py:343` — `validate_capabilities` — Require `## Supported`, `## Unsupported`, `## Notes` sections in `CAPABILITIES.md`.
- `runtime/drivers/_export_utils.py:439` — `_ALWAYS_ON_AGENTS` — Frozenset; single source of truth for `implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`; imported by agy, windsurf, kiro, and test helpers.
- `runtime/drivers/_export_utils.py:470` — `select_sources` — Pure helper: given a strategy string (`pointer`, `curated`, `full`) and enumerated sources dict, returns the filtered subset to emit.
- `runtime/drivers/_export_utils.py:538` — `resolve_strategy` — Read `export.strategy` from `scripts/config.py get` (subprocess); falls back to a driver-supplied default when config is absent.
- `runtime/drivers/_export_utils.py:605` — `run_self_test` — Verify fragment include expansion against the run-brief finalize marker.
- `runtime/drivers/cursor/export.py:180` — `export` — Emit AGENT rules as `.cursor/rules/<id>.mdc` and skills as native `.cursor/skills/<id>/SKILL.md`; write exactly one generated always-apply `.cursor/rules/z-harness-skills.mdc` index; `fidelity=flattened`.
- `runtime/drivers/codex/export.py:195` — `export` — Emit Codex prompt files and consolidated `AGENTS.md`; validate prompts; `fidelity=flattened`.
- `runtime/drivers/antigravity/export.py:564` — `export` — Emit all agy surfaces: workflows, rules, skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, `README.md`; `fidelity=high`.
- `runtime/drivers/pi/export.py:368` — `export` — Emit pi agent files, prompts, vendored subagent extension, and `AGENTS.md` index; export-only target; `fidelity=high`.
- `runtime/drivers/omp/export.py:199` — `export` — Emit OMP `.omp/config.yml` plus `.omp/z-harness/` package layout: manifest, skills, rules, prompts, agents, profiles; no pi line rewrites or `scripts/pi_assets/`; `fidelity=partial`.
- `z_harness_cli/adapters/omp.py:138` — `OmpAdapter.export_payload` — Delegates to OMP runtime export and returns partial fidelity; multi-agent commands remain blocked and single-agent commands degraded until `COMMAND_CAPABILITY_MATRIX["omp"]` reaches parity evidence.
- `z_harness_cli/adapters/base.py:42` — `ExportResult` — Re-export of runtime `ExportResult`; CLI-layer code imports from here, never from runtime directly.
- `z_harness_cli/adapters/base.py:189` — `HostAdapter.export_payload` — Protocol: delegate to runtime `export()`, run persona loop from `personas/builtin/`, merge results; raise `RuntimeError` on non-empty warnings.
- `z_harness_cli/adapters/cursor.py:214` — `CursorAdapter.export_payload` — Two-stage: cursor runtime export then persona loop; `RuntimeError` on validation errors; `fidelity=flattened`.
- `z_harness_cli/adapters/codex.py:243` — `CodexAdapter.export_payload` — Two-stage: codex runtime export then persona loop; `RuntimeError` on validation errors; `fidelity=flattened`.
- `z_harness_cli/adapters/antigravity.py:207` — `AntigravityAdapter.export_payload` — Two-stage: agy runtime export then persona loop; `RuntimeError` on validation errors; `fidelity=high`.
- `skills/z-export/SKILL.md:11` — `/z-export` — User-facing entry point; runs `python3 -m z_harness_cli export --host <host> --out exports/<target> --force` for cursor/codex/agy/omp; pi and export-only drivers run via direct import of their runtime module into `exports/<target>`.

## How it interacts with others

- `skills` — `enumerate_sources` walks `skills/*/SKILL.md`; `/z-export` is itself a skill and is exported. `skills/` is the only hand-authored committed source tier; `commands/` no longer exists as a source directory.
- `agents` — `enumerate_sources` walks `agents/*.md`; all agents including `scope-extractor` are exported.
- `personas-and-roles` — After the main runtime export, Cursor/Codex/agy adapters run the persona loop via `runtime/drivers/<target>/persona_export.py`, reading from `personas/builtin/`. OMP writes profiles under `.omp/z-harness/profiles/` from its runtime exporter. pi has no persona export.
- `runtime-drivers` — `runtime/drivers/_export_utils.py` is the shared foundation; each target's `export.py` imports from it and never from `z_harness_cli`. Export-only drivers (windsurf, kiro, cline, copilot) also use `select_sources` and `resolve_strategy` from `_export_utils.py`.
- `central-config` — `resolve_strategy` reads `export.strategy` via `python3 scripts/config.py get export.strategy`; valid values are `pointer`, `curated`, `full`.
- `scripts` — `audit-tarball.sh` remains the export safety gate for packaged artifacts. Legacy `scripts/export-*.py` scripts have been removed.
- `capabilities-matrix` — OMP export fidelity is not independent: the parity gate must synchronize `OmpAdapter.fidelity_tier`, OMP `ExportResult.fidelity`, and per-command tiers. Today those surfaces remain `partial`/blocked/degraded; Claude Code is the ground truth for promotion.

## Edge cases / gotchas

- `skills/<id>/SKILL.md` is the **only hand-authored committed source tier**. The `commands/` markdown directory has been deleted. `enumerate_sources` walks `skills/*/SKILL.md` as the primary source and keeps a back-compat `commands: []` key so pi plus the four deferred export-only drivers (copilot/kiro/windsurf/cline) do not KeyError.
- The legacy adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) have been **removed**. The runtime drivers at `runtime/drivers/<target>/export.py` are the only current path.
- `/z-export` writes the canonical `exports/<target>/` mirrors sequentially. Cursor/Codex/agy/OMP go through `python3 -m z_harness_cli export --host <host> --out exports/<target> --force`; pi/windsurf/kiro/cline/copilot inline-import their standalone runtime drivers and use `exports/<target>` as `export_root`. The lower-level CLI still supports arbitrary `--out <dest>`, and `--in-place` writes the host layout directly into the current working directory for live workspace use.
- `output_path_for` in `_export_utils.py` intentionally omits `agy` from `_TARGET_CONVENTIONS` — the agy exporter owns its own dual layout (`.agent/` + `prompts/`) and cannot be expressed as a single output path.
- Non-empty `warnings` from the runtime `export()` call are raised as `RuntimeError` by every adapter's `export_payload()` — the legacy hard-gate is preserved.
- Cursor and Codex append a `-skill` suffix if a skill ID collides with an agent ID in the export output; agy flat prompts use a `skill-` prefix to avoid collisions. (Legacy `-skill` suffix logic for command/skill collision is no longer needed since commands/ is deleted.)
- Codex consolidates all agents into a single `AGENTS.md`; no per-agent prompt files are emitted.
- Antigravity emits the most surfaces: workflows, rules, native skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- `_ALWAYS_ON_AGENTS` in `runtime/drivers/_export_utils.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`; all other agents get `model_decision` trigger. This constant is imported by the agy, windsurf, and kiro drivers.
- Antigravity workflow bodies have an ~12,000 character limit; several z-harness commands exceed it.
- `agy-plugin.yaml` is a z-harness convention manifest; Antigravity does not read it natively.
- pi is export-only: no adapter, no `HostDriver`, no `--host pi` CLI flag. Its export runs through `runtime/drivers/pi/export.py` via direct import. pi asset files (`CAPABILITIES.md`, `AGENTS.preamble.md`, `explore.md`, `extensions/`) live under `scripts/pi_assets/`.
- OMP export is separate from pi export. It writes `.omp/config.yml` plus `.omp/z-harness/manifest.yml`, `skills/<id>/SKILL.md`, `rules/<id>.md`, `prompts/<id>.md`, `agents/<id>.md`, and `profiles/<name>.yml`; it does not use `runtime/drivers/pi/export.py`, pi prompt-defense rewrites, or the vendored pi subagent extension. Its `ExportResult.fidelity` remains `partial` until native parity evidence lands.
- OMP discovery is explicit. `.omp/config.yml` keeps `skills.enableAgentsProject: false` so this repo's large root `AGENTS.md` is not auto-loaded; launch/export code points OMP at the z-harness package through `OMP_PLUGIN_ROOT` and the exported `.omp/z-harness/` package.
- OMP consult-provider compatibility (`scripts/omp-consult.sh`) is not native export or native command dispatch. That shim intentionally runs `omp -p --no-session --no-rules --model ... <prompt>` for consultant providers; native OMP command dispatch remains parity-gated and keeps rules/session semantics through the HostDriver contract.
- pi injects a prompt-defense block after `<!-- PROMPT_DEFENSE_MARKER -->` in exported agent files; falls back to after the heading line if no sentinel is found.
- pi has **no persona export**. Persona export runs only for cursor, codex, and agy.
- `inline_includes` accepts `base_dir` for API symmetry but never uses it — resolution is always relative to `repo_root` (preserved quirk from legacy `export-common.py`).
- `z_harness_cli/adapters/base.py` re-exports `ExportResult` with `__all__ = ['ExportResult']`; CLI-layer code and tests must import from `base`, not from `runtime.drivers._export_utils` directly.
- pi model mapping: `haiku` → `deepseek-v4-flash`, `sonnet`/`opus` → `deepseek-v4-pro`.
- `select_sources` and `resolve_strategy` are used by the export-only drivers (windsurf, kiro, cline, copilot) but not by cursor, codex, agy, pi, or OMP, which enumerate all sources unconditionally.

## Examples

- `python3 -m z_harness_cli export --host cursor --out /tmp/cursor-export` — generates `.cursor/skills/<id>/SKILL.md` files plus `.cursor/rules/z-harness-skills.mdc` index and agent `.mdc` rules under `/tmp/cursor-export/`.
- `python3 -m z_harness_cli export --host codex --out /tmp/codex-export` — generates `skills/<id>/SKILL.md` and `AGENTS.md` under `/tmp/codex-export/`.
- `python3 -m z_harness_cli export --host antigravity --out /tmp/agy-export` — generates `.agent/skills/<id>/SKILL.md`, workflows, rules, flat prompts, manifest, `CAPABILITIES.md`, and `README.md` under `/tmp/agy-export/`.
- `python3 -m z_harness_cli export --host omp --out exports/omp --force` — current partial-fidelity OMP export; generates `exports/omp/.omp/config.yml` plus `exports/omp/.omp/z-harness/` package files, while native command parity remains gated.
- `python3 -m z_harness_cli export --host cursor --in-place` — writes `.cursor/skills/<id>/SKILL.md` and `.cursor/rules/z-harness-skills.mdc` directly into the current working directory (live workspace install; nothing is committed).
- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('/tmp/pi-export'))"` — generates the full pi export tree into a temp directory.
