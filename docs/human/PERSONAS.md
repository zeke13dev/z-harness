# Personas and Roles

> Last updated: 2026-06-03
> Covers source: scripts/resolve-persona.py, scripts/resolve-persona.sh, runtime/contract/persona.schema.json, personas/README.md, personas/builtin/codex-default-consultant.md, personas/builtin/codex-default-reviewer.md, personas/builtin/gemini-default-consultant.md, commands/z-personas.md, skills/z-personas/SKILL.md, runtime/drivers/_persona_utils.py, runtime/drivers/antigravity/persona_export.py, runtime/drivers/cursor/persona_export.py, runtime/drivers/codex/persona_export.py, runtime/drivers/claude/persona_export.py, runtime/contract/event.schema.json, docs/human/PERSONAS.md

## Overview

A **persona** is a saved prompt-prefix preset that gets prepended to a role's task prompt at dispatch time. Persona, model, and runtime are **orthogonal axes** — each is configured independently, not bundled together. Personas are discovered from three layers in ascending priority (builtin < user-global < repo-local), with the last definition winning per name. The full concept spans the registry loader (`scripts/resolve-persona.py`), a contract schema (`runtime/contract/persona.schema.json`), per-target export adapters under `runtime/drivers/*/persona_export.py`, and the `/z-personas` command/skill surface for interactive inspection.

The persona system is applied across many dispatch sites: critique panels (`/z-plan`, `/z-debug`), audit dimensions (`/z-audit`), advisory consult arms (`/z-plan-light`, `/z-audit`), code-review gates (`/z-implement-all`, `/z-implement-next`, `/z-plan-light`, `/z-fix`, `/z-do`), and brainstorm ideators (`/z-brainstorm`). All convergent sites (evaluation, not generation) are governed by the NEUTRAL-AUTHORITY invariant — the neutral arm is always the decision of record, and the persona arm is advisory only. Export adapters translate each persona file to a target-specific format: native `.md` for Antigravity (`agy`), `.mdc` context-injection rules for Cursor, flat `.md` for Codex CLI, and flat `.md` for the Claude subagent target.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/resolve-persona.py:88` — `_ROLE_REGISTRY` — maps role names to expected contracts; 7 roles total; single source of truth for known roles
- `scripts/resolve-persona.py:931` — `cmd_resolve` — resolves persona/model/runtime triple for (command, role) from merged TOML config
- `scripts/resolve-persona.py:554` — `cmd_list_personas` — prints JSON array of winner-per-name personas; emits `persona_shadowed` on collisions
- `scripts/resolve-persona.py:1040` — `cmd_validate` — validates all bound personas exist, compatible_roles are known, contracts match
- `scripts/resolve-persona.py:1208` — `_enumerate_role_compatible_personas` — returns compatible personas for a role, excluding explicit ids; boring-anchor bypasses checks; filters disk `no-persona.md`
- `scripts/resolve-persona.py:1379` — `cmd_random_for_role` — draws a uniformly random persona (including boring-anchor and no-persona sentinel); emits `persona_random_selected`
- `scripts/resolve-persona.py:1491` — `cmd_random_distinct_for_role` — draws up to N distinct personas without replacement, excluding boring-anchor and no-persona; used by brainstorm and multi-arm panels
- `scripts/resolve-persona.py:1608` — `cmd_forced_control` — returns forced-control arm tagged `selection_source=forced_control`; used on Nth-attempt cadence
- `scripts/resolve-persona.py:1768` — `cmd_control_counter` — atomically increments `.z-harness/.persona-control-counter` (flock-guarded)
- `runtime/drivers/_persona_utils.py:28` — `parse_persona_file` — minimal stdlib-only frontmatter parser shared by all per-target export adapters
- `runtime/drivers/_persona_utils.py:76` — `build_portability_header` — returns a portability comment block for exported persona files
- `runtime/drivers/antigravity/persona_export.py:36` — `export_persona` — exports persona to `<root>/.agent/personas/<name>.md` (native agy support)
- `runtime/drivers/cursor/persona_export.py:48` — `export_persona` — exports persona as `.cursor/personas/<name>.mdc` context-injection rule (not native)
- `runtime/drivers/codex/persona_export.py:37` — `export_persona` — exports persona to `prompts/personas/<name>.md` for Codex CLI (not native)
- `runtime/drivers/claude/persona_export.py:38` — `export_persona` — exports persona to `personas/<name>.md` for Claude subagent target (not native)
- `runtime/dispatch/persona_prompt.py:13` — `prepend_persona` — reads persona body from `body_path`, strips frontmatter, prepends to task prompt; called by orchestrator before `Dispatcher.run()`
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `providers-registry` — runtime axis in the persona triple is resolved against the providers registry; TOML `[roles.*.*]` bindings overlap with provider config
- `config` — TOML `[roles.<command>.<role>]` and `[roles.default.<role>]` tables are the primary binding surface; `[experiment]` section controls `persona_rotation` and `control_every_n` knobs
- `scripts` — `resolve-persona.py` uses `scripts/log-event.sh` for all telemetry; `persona-stats.py` reads outcome events for analysis
- `agents` — all dispatched subagents may carry a persona-prefixed prompt; the dispatcher itself never resolves personas
- `commands` — `/z-plan`, `/z-debug`, `/z-audit`, `/z-brainstorm`, `/z-implement-all`, `/z-implement-next`, `/z-plan-light`, `/z-fix`, `/z-do` all call `resolve-persona.py` at dispatch time
- `skills` — skill variants of the above commands mirror the same persona resolution pattern; `/z-personas` skill exposes the registry read-only
- `multi-ide-exports` — `/z-export` calls the per-target `persona_export.py` adapters to translate persona files into target-specific formats

## Edge cases / gotchas

- `_shadowed_emitted` is keyed on name only (not on layer pair) — fires exactly once per process per shadowed name regardless of how many layers define it.
- `persona_binding_chimera` is keyed on `(command, role)`, not on the specific axis combination — fires only once per process per `(command, role)` pair.
- `boring-anchor` bypasses `compatible_roles` and contract checks in `_enumerate_role_compatible_personas` — it enters the pool for any role.
- `random-distinct-for-role` **excludes** `boring-anchor` and `no-persona` (diversity focus); `random-for-role` **includes** them (experiment control arms). Do not confuse the two subcommands.
- A `no-persona.md` file in any layer is silently filtered out by `_enumerate_role_compatible_personas` — only the hardcoded `_NO_PERSONA_SENTINEL` can produce a `no-persona` draw.
- `fallback_empty_pool` always returns `boring-anchor`; this is NOT a `forced_control` sample and must NOT be counted as boring-anchor baseline in analysis.
- `prepend_persona` strips YAML frontmatter using `body.find("\n---\n", 4)` from `runtime/dispatch/persona_prompt.py`; the `PERSONAS.md` docs describe a similar `"\n---\n"` approach — if the closing delimiter is missing, the entire file is treated as the body.
- Layer 3 (repo-local) path uses `git rev-parse` to find repo root; falls back to cwd if git is unavailable. `Z_HARNESS_REPO_ROOT`, `Z_HARNESS_REPO_PERSONAS_DIR`, `Z_HARNESS_BUILTIN_PERSONAS_DIR`, and `Z_HARNESS_USER_PERSONAS_DIR` all override respective layer paths for hermetic testing.
- Unknown frontmatter keys cause exit 2 — `model` and `runtime` belong in TOML config, not in the persona file. Allowed keys: `name`, `description`, `compatible_roles`, `contract`.
- `cmd_validate` checks `compatible_roles` only against known role names in `_ROLE_REGISTRY` — a `compatible_roles` entry for an unknown role is flagged as an error.
- `resolve-persona.sh` is a thin bash wrapper — all logic lives in `resolve-persona.py`; the shell script exists solely so dispatch sites do not need to know the Python path.
- Antigravity is the only native target — agy reads `persona_export.py`-produced files from `.agent/personas/` natively. Cursor, Codex CLI, and Claude targets all use workarounds (context injection, flat prepend).
- Per-target export adapters all share `_persona_utils.parse_persona_file` and `build_portability_header` from `runtime/drivers/_persona_utils.py` (stdlib-only, no PyYAML dependency).
- `/z-research` is intentionally excluded from the persona system — its three perspectives are fixed semantic lenses, not random draws.

## Examples

**Resolving a persona triple:**
```bash
python scripts/resolve-persona.py resolve z_plan consultant_primary
# → {"persona": "codex-default-consultant", "model": "", "runtime": "codex-cli",
#    "source": "roles_default", "persona_body_path": "/abs/path/..."}
```

**Drawing distinct ideator personas for `/z-brainstorm`:**
```bash
python scripts/resolve-persona.py random-distinct-for-role ideator --count=3
# Returns: JSON array of up to 3 resolve-shaped objects; shorter if pool underflows
```

**TOML binding example:**
```toml
[roles.z_plan.consultant_primary]
persona  = "my-custom-consultant"
model    = "gpt-5-codex"
runtime  = "codex-cli"

[roles.default.reviewer]
persona  = "codex-default-reviewer"
runtime  = "codex-cli"
```

**Exporting personas for the Antigravity target:**
```python
from runtime.drivers.antigravity.persona_export import export_persona
out_path = export_persona("personas/builtin/codex-default-reviewer.md", "/path/to/agy/export")
# writes: /path/to/agy/export/.agent/personas/codex-default-reviewer.md
```
