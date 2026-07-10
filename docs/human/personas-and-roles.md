# personas-and-roles

> Last updated: 2026-07-09
> Covers source: scripts/resolve-persona.py, scripts/resolve-persona.sh, runtime/contract/persona.schema.json, personas/README.md, personas/builtin/codex-default-consultant.md, personas/builtin/gemini-default-consultant.md, skills/z-personas/SKILL.md, runtime/drivers/_persona_utils.py, runtime/drivers/antigravity/persona_export.py, runtime/drivers/cursor/persona_export.py, runtime/drivers/codex/persona_export.py, runtime/drivers/claude/persona_export.py, z_harness_cli/adapters/antigravity.py, z_harness_cli/adapters/cursor.py, z_harness_cli/adapters/codex.py, z_harness_cli/adapters/claude.py

## Overview

The persona system gives z-harness the ability to shape an agent's behavior by prepending a saved prompt prefix before each role invocation. A persona is a Markdown file with a YAML frontmatter block (`name`, `description`, optional `compatible_roles`, optional `contract`). Personas are orthogonal to model and runtime: you bind all three axes independently per `(command, role)` in your TOML config. The registry loads from three layers in priority order — builtin (`personas/builtin/`), user-global (`~/.config/z-harness/personas/`), repo-local (`<repo>/.z-harness/personas/`) — with the last (highest-priority) layer winning per name.

The feature also drives the persona-rotation experiment, which randomizes which persona is dispatched to implementer, reviewer, consultant, ideator, and audit_persona roles to measure behavioral diversity. Seven roles are registered in `_ROLE_REGISTRY` (the single source of truth). The builtin pool ships 30 personas; two special sentinels exist: `boring-anchor` (the stable control) and `no-persona` (a null/vanilla baseline that has no file on disk). The `/z-personas` slash command provides read-only inspection of the registry and current bindings. `experiment.persona_rotation` currently defaults to `true` in `scripts/config.py`, so the rotation system is active by default unless a repo or env layer overrides it.

## Key entry points

- `scripts/resolve-persona.py:88` — `_ROLE_REGISTRY` — maps role names to expected contracts; 7 roles; single source of truth for known roles
- `scripts/resolve-persona.py:554` — `cmd_list_personas` — prints JSON array of `{name, source_layer, path}` (winner per name only); emits `persona_shadowed` on collisions
- `scripts/resolve-persona.py:594` — `cmd_where` — prints all layer paths defining a named persona; exits 1 if not found
- `scripts/resolve-persona.py:931` — `cmd_resolve` — resolves persona/model/runtime triple for `(command, role)` from merged TOML config; emits chimera event when axes come from two or more layers
- `scripts/resolve-persona.py:993` — `cmd_list_bindings` — walks all configured commands/roles and prints a JSON tree; accepts `--command` filter
- `scripts/resolve-persona.py:1040` — `cmd_validate` — validates all bound personas exist, compatible_roles are known, contract matches role's expected_contract; exits 1 on any violation
- `scripts/resolve-persona.py:1137` — `cmd_read` — prints frontmatter and body of the winning persona file for a given name
- `scripts/resolve-persona.py:1208` — `_enumerate_role_compatible_personas` — returns role-compatible winning-layer personas; filters out `no-persona.md` disk files; boring-anchor bypasses checks
- `scripts/resolve-persona.py:1185` — `_BORING_ANCHOR_NAME` — string constant `'boring-anchor'`; in random pool; also forced on cadence
- `scripts/resolve-persona.py:1367` — `_NO_PERSONA_NAME` — string constant `'no-persona'`; null baseline sentinel with no disk file
- `scripts/resolve-persona.py:1379` — `cmd_random_for_role` — draws uniformly random persona for a role (pool includes boring-anchor and no-persona); emits `persona_random_selected`
- `scripts/resolve-persona.py:1491` — `cmd_random_distinct_for_role` — draws up to N distinct personas without replacement (excludes boring-anchor and no-persona); backs `/z-brainstorm` ideator diversity
- `scripts/resolve-persona.py:1608` — `cmd_forced_control` — returns forced-control arm (`boring-anchor` or `no-persona`) tagged `selection_source=forced_control`
- `scripts/resolve-persona.py:1768` — `cmd_control_counter` — atomically increments the per-repo cadence counter in `.z-harness/.persona-control-counter` (flock-guarded)
- `scripts/resolve-persona.py:537` — `_detect_and_emit_shadows` — emits `persona_shadowed` once per (process, name) for each name defined in more than one layer
- `scripts/resolve-persona.py:775` — `_emit_persona_binding_chimera` — emits `persona_binding_chimera` once per (process, command, role) when axes come from two or more config layers
- `runtime/drivers/_persona_utils.py:28` — `parse_persona_file` — stdlib-only frontmatter parser shared by all four per-target `persona_export.py` modules
- `runtime/drivers/_persona_utils.py:76` — `build_portability_header` — builds the portability comment block prepended to all exported persona files
- `runtime/drivers/antigravity/persona_export.py:36` — `export_persona` — exports to `<root>/.agent/personas/<name>.md` (NATIVE — agy reads directly)
- `runtime/drivers/cursor/persona_export.py:48` — `export_persona` — exports to `.cursor/personas/<name>.mdc`; NOT NATIVE; body injected as system-prompt prefix via glob rule
- `runtime/drivers/codex/persona_export.py:37` — `export_persona` — exports to `prompts/personas/<name>.md`; NOT NATIVE; orchestrator concatenates as system-prompt prefix
- `runtime/drivers/claude/persona_export.py:38` — `export_persona` — exports to `personas/<name>.md`; NOT NATIVE; injected as system-prompt prefix by Claude subagent dispatcher
- `z_harness_cli/adapters/antigravity.py:207` — `AntigravityAdapter.export_payload` — globs `personas/builtin/*.md` and calls `export_persona` per file; raises on persona-name collision with workflow ids
- `z_harness_cli/adapters/cursor.py:214` — `CursorAdapter.export_payload` — globs `personas/builtin/*.md` and calls cursor `export_persona` per file; raises on collision with rule ids
- `z_harness_cli/adapters/codex.py:259` — `CodexAdapter.export_payload` — globs `personas/builtin/*.md` and calls codex `export_persona` per file; raises on collision with prompt ids in the flat `prompts/` namespace; fidelity comes from `codex_parity_gate`
- `z_harness_cli/adapters/claude.py:160` — `ClaudeAdapter.export_payload` — globs `personas/builtin/*.md` and calls claude `export_persona`; returns ExportResult with fidelity=native

## How it interacts with others

- `providers-registry` — TOML `[roles.*.*]` bindings in config.toml co-locate persona/model/runtime; legacy `providers.json` is fallback for runtime-only binding
- `config` — `experiment.persona_rotation` knob (default `true`) gates the entire rotation system; `experiment.control_every_n` (default 5) sets the forced-control cadence
- `commands` — persona-rotation is invoked from `/z-execute`, `/z-plan` (5-panel consult), `/z-debug`, `/z-brainstorm` (ideator arms via `random-distinct-for-role`), and `/z-audit` (per-dimension audit_persona draws)
- `multi-ide-exports` — all four CLI adapters glob `personas/builtin/*.md` and write per-target persona files via the per-target `persona_export.py` adapters during `/z-export`; the Codex adapter's export layout was refreshed 2026-07-05 (docstring-only — the glob pattern, persona output path, and collision-check semantics are unchanged)
- `agents` — downstream subagents receive the persona body prepended to their system prompt; no resolution happens inside the dispatcher

## Edge cases / gotchas

- Builtin personas live in `personas/builtin/` — the `personas/` top-level holds only `README.md`. Globbing `personas/*.md` matches zero persona files and silently exports nothing (pre-`d894f93` bug).
- `_shadowed_emitted` is keyed on name only (not on layer pair), so `persona_shadowed` fires exactly once per process per shadowed name.
- `persona_binding_chimera` is keyed on `(command, role)`, not on the specific axis combination — fires only once per process per `(command, role)` pair.
- `boring-anchor` bypasses `compatible_roles` and contract checks in `_enumerate_role_compatible_personas` — it enters the pool for any role.
- `random-distinct-for-role` EXCLUDES `boring-anchor` and `no-persona`; `random-for-role` INCLUDES them. These are different subcommands with different semantics.
- A `no-persona.md` file in any layer is silently filtered out — only the hardcoded `_NO_PERSONA_SENTINEL` can produce a no-persona draw.
- `fallback_empty_pool` always returns `boring-anchor`; this is NOT a `forced_control` sample and must NOT be counted as `boring-anchor` baseline in analysis.
- `prepend_persona` in `runtime/dispatch/persona_prompt.py` strips YAML frontmatter using `body.find('\n---\n', 4)`; if the closing delimiter is missing, the entire file including frontmatter is treated as the body.
- Layer 3 (repo-local) uses `git rev-parse` to find the repo root; falls back to cwd if git is unavailable. Env overrides `Z_HARNESS_REPO_ROOT`, `Z_HARNESS_REPO_PERSONAS_DIR`, `Z_HARNESS_BUILTIN_PERSONAS_DIR`, and `Z_HARNESS_USER_PERSONAS_DIR` allow hermetic testing.
- `resolve-persona.sh` is a thin bash wrapper — all logic lives in `resolve-persona.py`; the shell script exists solely so dispatch sites do not need to know the Python path.
- `random-for-role` exits 2 on unknown role (not in `_ROLE_REGISTRY`). Add to `_ROLE_REGISTRY` before calling.
- `/z-research` is intentionally excluded from the persona system — its three perspectives are fixed semantic lenses, not random draws.
- `parse_persona_file` in `_persona_utils.py` uses stdlib-only regex (`_FRONTMATTER_RE`) — no PyYAML dependency. All four per-target export adapters depend on it.
- Cursor export produces `.mdc` with `alwaysApply:true` and glob `**/*`; Codex export produces a flat `.md` with a `# Persona: <name>` header (no frontmatter); Claude export preserves the full frontmatter block; Antigravity preserves full frontmatter and body.
- All four CLI adapter `export_payload()` methods emit a warning and skip persona export if `personas/builtin/` is not found — they do not hard-fail.
- Unknown frontmatter keys cause exit 2; `model`, `runtime` and similar binding axes belong in TOML config, not in the persona file. Allowed keys: `name`, `description`, `compatible_roles`, `contract`.
- `experiment.persona_rotation` defaults to `true` (`scripts/config.py`); there is a pending overhaul plan (outside this doc's scope) that may remove the persona subsystem in a future revision, but as of this refresh the rotation system is live and on by default.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/personas-and-roles.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded for this concept yet._

## Examples

- List all personas in the registry: `python3 scripts/resolve-persona.py list-personas`
- Check which layers define a persona: `python3 scripts/resolve-persona.py where codex-default-consultant`
- Resolve binding for a (command, role) pair: `python3 scripts/resolve-persona.py resolve z-plan consultant_primary`
- Show all bindings: `python3 scripts/resolve-persona.py list-bindings`
- Validate all bindings and contracts: `python3 scripts/resolve-persona.py validate`
- Draw a random implementer persona: `python3 scripts/resolve-persona.py random-for-role implementer`
- Draw 3 distinct ideator personas: `python3 scripts/resolve-persona.py random-distinct-for-role ideator --count=3`
- Inspect all bindings from the slash command: `/z-personas roles`
