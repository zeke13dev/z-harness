# multi-ide-exports

> Last updated: 2026-06-11
> Covers source: runtime/drivers/_export_utils.py, runtime/drivers/cursor/export.py, runtime/drivers/codex/export.py, runtime/drivers/antigravity/export.py, runtime/drivers/pi/export.py, z_harness_cli/adapters/base.py, z_harness_cli/adapters/cursor.py, z_harness_cli/adapters/codex.py, z_harness_cli/adapters/antigravity.py, commands/z-export.md, docs/human/MULTI-IDE.md

## Overview

The multi-IDE export pipeline translates z-harness source files (`commands/`, `agents/`, `skills/`, `personas/`) into target-specific layouts under `exports/`. Each export target has a dedicated driver at `runtime/drivers/<target>/export.py` that exposes a uniform `export(repo_root, export_root, *, options=None) -> ExportResult` signature. The canonical `ExportResult` dataclass (`dest`, `files`, `fidelity`, `warnings`) is defined in `runtime/drivers/_export_utils.py` and re-exported from `z_harness_cli/adapters/base.py` so CLI-layer code never imports upward into the runtime layer.

The four targets are Cursor (`fidelity="flattened"`, `.cursor/rules/*.mdc`), Codex CLI (`fidelity="flattened"`, `prompts/*.md` + `AGENTS.md`), Antigravity/agy (`fidelity="high"`, `.agent/` native layout + flat `prompts/`), and pi (`fidelity="high"`, `agents/`, `prompts/`, vendored subagent extension). pi is an export-only target with no adapter, HostDriver, or launch/inject support. For Cursor, Codex, and agy, each `z_harness_cli/adapters/<host>.py` adapter's `export_payload()` method calls the runtime `export()` then optionally runs the persona export loop; non-empty runtime warnings are raised as `RuntimeError` (legacy hard-gate). Shared utilities (`enumerate_sources`, `inline_includes`, `output_path_for`, `validate_capabilities`, `run_self_test`) all live in `_export_utils.py`.

## Key entry points

- `runtime/drivers/_export_utils.py:43` — `ExportResult` — Canonical export result dataclass owned by the runtime; never import from anywhere else in the runtime layer.
- `runtime/drivers/_export_utils.py:297` — `enumerate_sources` — Collect commands, agents, and skills from repo root into a kind-keyed dict.
- `runtime/drivers/_export_utils.py:373` — `output_path_for` — Compute conventional output path for `cursor` or `codex` targets (agy is intentionally absent).
- `runtime/drivers/_export_utils.py:227` — `inline_includes` — Expand `<!-- include: path -->` markers; `base_dir` accepted but unused (resolution is always relative to `repo_root`).
- `runtime/drivers/_export_utils.py:429` — `run_self_test` — Verify fragment include expansion against the run-brief finalize marker.
- `runtime/drivers/cursor/export.py:148` — `export` — Emit and validate Cursor `.mdc` rules; appends `-skill` suffix on command/skill ID collision.
- `runtime/drivers/codex/export.py:185` — `export` — Emit Codex prompts and consolidated `AGENTS.md`; validate prompts.
- `runtime/drivers/antigravity/export.py:564` — `export` — Emit all agy surfaces: workflows, rules, skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, `README.md`.
- `runtime/drivers/pi/export.py:395` — `export` — Emit pi agent files, prompts, vendored subagent extension, and `AGENTS.md` index (export-only target).
- `z_harness_cli/adapters/base.py:189` — `HostAdapter.export_payload` — Protocol method: delegate to runtime `export()`, run persona loop, merge into one `ExportResult`; raise `RuntimeError` on non-empty runtime warnings.
- `z_harness_cli/adapters/cursor.py:214` — `CursorAdapter.export_payload` — Two-stage export: runtime cursor driver then `persona_export` loop; raises `RuntimeError` on validation errors.
- `z_harness_cli/adapters/codex.py:243` — `CodexAdapter.export_payload` — Two-stage export: runtime codex driver then `persona_export` loop; raises `RuntimeError` on validation errors.
- `z_harness_cli/adapters/antigravity.py:207` — `AntigravityAdapter.export_payload` — Two-stage export: runtime agy driver then `persona_export` loop; raises `RuntimeError` on validation errors.
- `commands/z-export.md:10` — `/z-export` — User-facing entry point: `python3 -m z_harness_cli export --host <target>` for cursor/codex/agy; pi runs via direct import of `runtime.drivers.pi.export`.

## How it interacts with others

- `commands` — `enumerate_sources` walks `commands/*.md`; `/z-export` is itself a command and is exported.
- `agents` — `enumerate_sources` walks `agents/*.md`; all agents including `scope-extractor` are exported.
- `skills` — `enumerate_sources` walks `skills/*/SKILL.md`; Cursor and Codex render as rule/prompt files; agy emits native `.agent/skills/<id>/SKILL.md` directories.
- `personas-and-roles` — After the main runtime export, each adapter's `export_payload()` runs the persona loop via `runtime/drivers/<target>/persona_export.py`. agy is the only native persona target; Cursor uses glob-matched `alwaysApply: true` `.mdc` rules.
- `runtime-drivers` — `runtime/drivers/_export_utils.py` is the shared foundation; each target's `export.py` imports from it and never from `z_harness_cli`.
- `scripts` — `audit-tarball.sh` remains the export safety gate for packaged artifacts; the legacy `scripts/export-*.py` scripts have been removed.

## Edge cases / gotchas

- The legacy adapter scripts (`export-common.py`, `export-cursor.py`, `export-codex.py`, `export-agy.py`) have been **removed**. The runtime drivers at `runtime/drivers/<target>/export.py` are the only current path.
- `output_path_for` in `_export_utils.py` intentionally omits `agy` from `_TARGET_CONVENTIONS` — the agy exporter owns its own dual layout and cannot be expressed as a single output path.
- Non-empty `warnings` from the runtime `export()` call are raised as `RuntimeError` by every adapter's `export_payload()` — the legacy hard-gate is preserved.
- When a skill ID collides with a command ID both Cursor and Codex append a `-skill` suffix to the export filename; agy uses a `skill-` prefix on flat prompt filenames to avoid collisions.
- Codex consolidates all agents into a single `AGENTS.md`; no per-agent prompt files are emitted.
- Antigravity emits the most surfaces: workflows, rules, native skills, flat prompts, `agy-plugin.yaml`, `CAPABILITIES.md`, and `README.md`.
- `_ALWAYS_ON_AGENTS` in `runtime/drivers/antigravity/export.py` hard-codes `implementer`, `reviewer`, `auditor`, `mr-reviewer`, `remote-runner`; all other agents get `model_decision` trigger.
- Antigravity workflow bodies have an ~12,000 character limit; several z-harness commands exceed it.
- `agy-plugin.yaml` is a z-harness convention manifest; Antigravity does not read it natively.
- pi is export-only: no adapter, no `HostDriver`, no `--host pi` CLI flag. Its export runs through `runtime/drivers/pi/export.py` via direct import. pi asset files (CAPABILITIES.md, AGENTS.preamble.md, explore.md, extensions/) live under `scripts/pi_assets/`.
- pi injects a prompt-defense block after `<!-- PROMPT_DEFENSE_MARKER -->` in exported agent files and as a post-heading fallback in prompt files.
- `inline_includes` accepts `base_dir` for API symmetry with SPEC call sites but does not use it — resolution is always relative to `repo_root`.
- Cursor personas are exported as `alwaysApply: true` `.mdc` rules under `.cursor/personas/` (not a native Cursor persona mechanism).
- `z_harness_cli/adapters/base.py` re-exports `ExportResult` from `runtime.drivers._export_utils`; CLI-layer code must import from `base`, not from the runtime module directly.
- pi model mapping: `haiku` → `deepseek-v4-flash`, `sonnet`/`opus` → `deepseek-v4-pro`.

## Examples

- `python3 -m z_harness_cli export --host cursor` — regenerates `exports/cursor/.cursor/rules/*.mdc`.
- `python3 -m z_harness_cli export --host codex` — regenerates `exports/codex/prompts/*.md` and `exports/codex/AGENTS.md`.
- `python3 -m z_harness_cli export --host antigravity` — regenerates workflows, rules, skills, prompts, manifest, `CAPABILITIES.md`, and `README.md` under `exports/agy/`.
- `python3 -c "from runtime.drivers.pi.export import export; from pathlib import Path; export(Path('.'), Path('exports/pi'))"` — regenerates the full `exports/pi/` tree.
- `python3 -m z_harness_cli export --host all` — runs all three adapter-host targets (cursor, codex, agy) sequentially.
- `bash scripts/audit-tarball.sh myexport.tar.gz` — verifies a tarball contains no forbidden paths before distribution.
