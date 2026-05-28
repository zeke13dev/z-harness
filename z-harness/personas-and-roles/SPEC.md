# SPEC — personas-and-roles (v1)

## Overview

Add a "persona" abstraction layer that lets users author saved prompt-prefix presets and bind them, alongside independent model and runtime choices, to logical roles (`consultant_primary`, `consultant_secondary`, `reviewer`) per command. Persona, model, and runtime are **orthogonal axes** — not bundled. The existing `providers.json` registry survives as the runtime/CLI descriptor layer; model is extracted as a first-class field; new TOML bindings live under `[roles.<command>.<role>]` in z-harness `config.toml`. Per-Agent()/Dispatcher.run() override kwargs allow orchestrator-driven dynamic selection without an LLM classifier (deferred to v2).

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/personas-and-roles/BRAINSTORM.md | 2026-05-28T17:25:00Z |
| RESEARCH.md | n/a (not produced) | n/a |

## Goals

1. Author saved persona presets as `.md` files with prompt-prefix bodies.
2. Bind persona + model + runtime independently per (command, role) in TOML.
3. Resolution order: per-Agent() override → `[roles.<command>.<role>]` → `[roles.default.<role>]` → legacy `providers.json` `roles` → error.
4. Provider registry survives as runtime layer; schema bumps v1 → v2 (extract `model`, add `model_arg_template`, `model_env_var`, `default_model`).
5. Provider names rename: `codex` → `codex-cli`, `gemini` → `gemini-cli`, etc., with backward-compat aliases for one minor version.
6. Stale agent files (`codex-consultant.md`, `gemini-consultant.md`, `codex-reviewer.md`) migrate to `personas/builtin/*.md`; old files deleted.
7. Multi-IDE export of personas (Cursor, Codex CLI, agy) — implemented via `runtime/drivers/antigravity/` forward path, not by extending deprecated adapter scripts.
8. `/z-personas` discovery command lists roles, personas, current bindings.

## Non-goals (v1)

- Native-agent migration (`agents/implementer.md` etc.) — separate plan.
- LLM-driven persona auto-selection — v2.
- `prompt_template` / `{TASK_PROMPT}` interpolation in persona bodies — v2 if real personas demand it.
- Fix `kind: "sdk"` schema/impl gap — approved shortcut, orthogonal scope.

---

## File-by-file spec

### A. New: persona registry

#### A1. `personas/builtin/<name>.md`

Files shipped with the harness. Frontmatter:

```yaml
---
name: codex-default-reviewer
description: Default Codex reviewer persona — adversarial, blockers/majors only.
compatible_roles: [reviewer]            # optional; soft warning if mismatched
contract: review-verdict                 # optional; freeform|review-verdict|strict-json
---
```

Body = prompt prefix (markdown). Prepended verbatim before the role's task prompt at dispatch time. No model, no runtime in frontmatter.

**Invariants:**
- `name` matches `^[a-z0-9-]+$` (kebab-case, no dots/slashes).
- `compatible_roles` is a soft hint — bind-time mismatch emits `persona_compat_warning` event, does not block.
- `contract` is **enforced at bind time when the role declares an expected contract** — e.g. the `reviewer` role's existing parser expects PASS/FAIL/BLOCKED, so it declares `expected_contract: review-verdict`. Binding a `contract: freeform` persona to `reviewer` fails at startup with an actionable error. Roles without a declared expected contract accept any persona contract (advisory only).

**Edge cases:**
- Persona file missing → resolver exits with actionable error pointing at `/z-personas`.
- Persona name collision across layers → last layer in load order wins per name; emit `persona_shadowed` event.

#### A2. `personas/README.md`

Authoring guide. Layered storage explained: `personas/builtin/` (shipped) < `~/.config/z-harness/personas/` (user-global) < `<repo>/.z-harness/personas/` (repo). Last wins per name.

#### A3. `scripts/resolve-persona.py`

New script. Subcommands:

- `resolve <command> <role>` — print JSON envelope `{persona, model, runtime, source: override|roles_command|roles_default|providers_legacy|none, persona_body_path}`.
- `list-personas` — JSON array of all discovered personas across the three layers with their source layer.
- `list-bindings [--command <c>]` — JSON tree of current effective bindings.
- `validate` — sanity-check schema of all personas; check `compatible_roles` against known role names; check `contract` against role's `expected_contract` for all default bindings.
- `read <name>` — print persona name, frontmatter, full body (debugging aid). Returns the winning-layer version.
- `where <name>` — print the load-order chain showing all layers that define `<name>` (not just the winner). Useful for understanding shadowing.

Output rule: stdout = JSON; diagnostics → stderr (mirrors `resolve-provider.py`).

#### A4. `scripts/resolve-persona.sh`

Thin shell wrapper: `exec python3 scripts/resolve-persona.py "$@"`.

---

### B. Provider registry v2 migration

#### B1. `providers.json` schema v2

Schema bump from `version: 1` to `version: 2`. New fields per provider:

```json
{
  "version": 2,
  "providers": {
    "codex-cli": {
      "kind": "cli",
      "command": "codex",
      "args_template": ["exec", "-"],
      "model_arg_template": ["--model", "{model}"],
      "model_env_var": null,
      "default_model": "gpt-5-codex",
      "timeout_s": 300,
      "model_label": "Codex CLI"
    }
  },
  "roles": {
    "consultant_primary": "codex-cli"
  },
  "aliases": {
    "codex": "codex-cli",
    "gemini": "gemini-cli",
    "claude": "claude-cli"
  }
}
```

**Composition (orchestrator-side):**
1. Final argv = `args_template + render(model_arg_template, model=effective_model)`.
2. `{model}` substitution: replaces literal `{model}` token in any arg string.
3. If `model_arg_template` is `null`/absent → model stays embedded in `args_template` (legacy mode); composer does NOT call `render()` and does NOT append a model arg. `render()` is never invoked with a `None` template.
4. If `model_env_var` is set → composer also sets `<env_var>=<effective_model>` in subprocess env. Composer prefers arg template if both present.
5. Empty-string model semantics: if the resolved effective model is `""` (empty string), treat as "use provider's `default_model`." Validation permits empty model values; semantic interpretation happens at composition.

**Implementation location (post-precheck correction):** `compose_argv(provider_dict, effective_model)` is a new function in `scripts/resolve-provider.py`. **`build_env` already exists at `runtime/dispatch/env.py`** with signature `build_env(provider_config, base_env=None)` handling `auth_env` + `CLAUDECODE` forwarding. T004 EXTENDS that existing function by adding an `effective_model` parameter and `model_env_var` merge logic — new signature: `build_env(provider_config, base_env=None, effective_model=None)`. Existing callers that don't pass `effective_model` keep working unchanged.

**Provider rename mechanism (post-review B1 clarification).** The rename is implemented via DUAL provider entries + aliases, NOT by deleting old entries. Specifically: `providers.json` keeps the existing `codex` / `gemini` / `claude` entries unchanged AND adds new entries named `codex-cli` / `gemini-cli` / `claude-cli` with identical `args_template` / `command` / etc. AND adds a top-level `aliases` map `{"codex": "codex-cli", "gemini": "gemini-cli", "claude": "claude-cli"}` for forward-compat (config that still references old names resolves through aliases). Default TOML bindings reference the NEW names. This means a fresh install with the shipped `providers.json` AND shipped `cmd_ensure_defaults` config works out of the box. Migrating from a legacy `providers.json` v1 file: in-memory upgrade fills the new optional fields with `null`; user runs `/z-config migrate` to rewrite their TOML config from old names to new (after which the alias path is dormant). Eventually (post-v1), old entries can be removed; aliases become deprecation-only.

**Default bindings distribution (post-review B2 clarification).** The `[roles.default.*]` TOML triples ship via `cmd_ensure_defaults` in `scripts/config.py` (NOT in a separate `.toml` template file). On first invocation of any z-harness command, the loader calls ensure-defaults which writes the default bindings into the user's global config IF the keys are absent. Existing user-authored config keys are never overwritten. This means: a fresh user gets working defaults without touching their config manually; a user with their own bindings keeps them.

**Invariants:**
- Schema v1 keeps working: `version: 1` providers are upgraded in-memory to v2 with `model_arg_template: null`, `model_env_var: null`, `default_model: null` (legacy mode).
- `aliases` mapping resolves old name → new name at lookup time; emits one-time `provider_alias_used` deprecation event per (run, alias).

#### B2. `scripts/resolve-provider.py` updates

- Accept both `version: 1` and `version: 2`; upgrade v1 → v2 in-memory.
- `resolve(role)` return shape gains: `model_arg_template`, `model_env_var`, `default_model`.
- New function `compose_argv(provider, effective_model)` returns the full argv with model interpolated.
- Backward-compat: when caller passes the new-format provider name, resolve directly; when caller passes an alias, follow the `aliases` mapping and emit `provider_alias_used` **at most once per (run, alias)** (memoized via a process-local set keyed on alias name).
- Legacy `providers.json` `roles` fallback (resolution-order step 4 — see §D) ALSO passes the looked-up provider name through alias resolution. If the legacy entry points at an old name, both `legacy_provider_roles_used` and `provider_alias_used` fire.
- v1 upgrade rules: v1 entries lacking `args_template` (rare but possible) are upgraded with `args_template: []`; `kind` defaults to `"cli"` if absent; `model_arg_template: null`, `model_env_var: null`, `default_model: null`. The composer's null-template guard (§B1 step 3) makes this safe.

#### B3. `runtime/compat.py:resolve_provider()` updates

Same shape change as B2. Tests in `runtime/tests/test_compat_providers.py` extended for v2.

#### B4. `runtime/contract/provider.schema.json` updates

JSON Schema Draft 7 updated to:
- `version: const 2` (or `enum [1, 2]` with deprecation note on 1).
- Add optional `model_arg_template`, `model_env_var`, `default_model`.
- Add optional `aliases` top-level mapping.

---

### C. Config loader: 3-level TOML nesting

#### C1. `scripts/config.py` updates

- `_KEY_RE` extended to support 3-level keys: `[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,2}`.
- Existing 2-level callers (`notify.level`, `workflow.audit_to_amend`, etc.) unaffected — same regex tolerates fewer levels.
- New section: `[roles.<command>.<role>]` with three keys: `persona`, `model`, `runtime`. All three are optional strings.
- New section: `[roles.default.<role>]` with the same shape — used as fallback layer.
- Merge semantics: **per-field, not whole-table.** When repo TOML sets `model = "opus"` and global sets `persona = "X"`, merged result has both. Same per-key precedence as today; explicit per-field for nested tables. **Chimera-warning event:** when a binding's three axes (persona, model, runtime) end up resolved from ≥2 different layers, resolve-persona emits a `persona_binding_chimera` event with the per-axis source layers — user-visible audit trail so an unintended pairing (e.g. Gemini-tuned persona + codex-cli runtime) is observable. Resolution proceeds; this is a soft warning.
- `cmd_export_env` skips `roles.*` (these aren't exported as env vars).
- `cmd_explain` traverses 3-level keys.
- VALIDATORS: new entries for `roles.<command>.<role>.persona`, `.model`, `.runtime`. Persona names validated against the registry (must exist in some layer); model + runtime validated as non-empty strings (semantic check at resolution time).

**Invariants:**
- Existing config.toml files keep working unchanged.
- Schema version stays at `schema_version: 1` (no bump needed — 3-level nesting is a loader-only change, no fields removed/renamed).
- Command keys normalized to underscore form internally: `/z-plan` → `z_plan` at lookup. **Normalization happens in `resolve-persona.py` at the call site**, NOT in the TOML parser (config.py stays a generic loader). Persona binding format documentation reflects underscore-only in TOML files. `/z-personas` discovery command translates back to slash-cmd form on output (e.g. prints `/z-plan`, not `z_plan`).

#### C2. `scripts/test_config.py` updates

New cases:
- 3-level key roundtrip (get/set/export-env/explain).
- Per-field merge across global + repo + env layers for `[roles.*.*]`.
- Command name normalization (`/z-plan` → `z_plan`).
- Backward compat: existing 2-level keys still resolve.

---

### D. Per-Agent() / Dispatcher override

**Resolution ownership (post-review B3 clarification).** The CALLER (orchestrator / Agent() call site) resolves persona+model+runtime by invoking `resolve-persona.py resolve <command> <role>`, then passes the resulting triple as `provider_config` fields plus optional override kwargs to `Dispatcher.run(persona=, model=, runtime=)`. The dispatcher does NOT call resolve-persona itself — it accepts pre-resolved provider_config and applies any explicit kwargs on top. This keeps Dispatcher.run thin and avoids subprocess overhead at dispatch time. Persona body integration: the orchestrator reads the persona body from `persona_body_path` (returned by resolve-persona) and prepends it to the role's task prompt BEFORE calling Dispatcher.run.


#### D1. `runtime/dispatch/dispatcher.py` updates

`Dispatcher.run(driver, command_id, caller_args, provider_config, session_id=None, persona=None, model=None, runtime=None)` — three new optional kwargs.

Resolution order at dispatch time:
1. Explicit kwargs (persona/model/runtime) — if set, win.
2. TOML `[roles.<command>.<role>]` — looked up via `resolve-persona`.
3. TOML `[roles.default.<role>]` — same.
4. Legacy `providers.json` `roles` mapping — emits `legacy_provider_roles_used`.
5. Error — halt with actionable message.

Effective values emitted in a new `persona_bound` event: `{command, role, persona, model, runtime, source}`.

#### D2. `agents/consultant-primary.md`, `agents/consultant-secondary.md`, `agents/reviewer.md` updates

Update prompts to describe the override surface: orchestrator can pass `persona=`, `model=`, `runtime=` at dispatch time. Examples in each file showing override use.

#### D3. Agent() call-site documentation

Add a "Persona / model / runtime overrides" subsection to `docs/human/agents.md` (or fold into the new `docs/human/PERSONAS.md`) covering the override surface for command authors.

---

### E. Default persona authorship

**Correction post-review:** `agents/codex-consultant.md`, `agents/gemini-consultant.md`, `agents/codex-reviewer.md` **do not exist** (already cleaned up in prior work — the current files are `consultant-primary.md`, `consultant-secondary.md`, `reviewer.md`, which are provider-routable role proxies, not vendor-specific personas). So this phase is NOT a file migration; it's fresh authorship.

Author three default personas under `personas/builtin/`:

- `personas/builtin/codex-default-consultant.md` — `compatible_roles: [consultant_primary, consultant_secondary]`, `contract: freeform`. Body: concise consultant prompt prefix establishing tone (skeptical, evidence-based, structured returns).
- `personas/builtin/gemini-default-consultant.md` — same shape; Gemini-tuned tone.
- `personas/builtin/codex-default-reviewer.md` — `compatible_roles: [reviewer]`, `contract: review-verdict`. Body: adversarial-reviewer prompt prefix; expects PASS/FAIL/BLOCKED structured return.

No deletions required. The existing `agents/consultant-primary.md` etc. are role-proxy docs (kept), updated in §D2.

**Default TOML bindings** (shipped alongside the personas — see also §C below):

```toml
[roles.default.consultant_primary]
persona = "codex-default-consultant"
model = ""              # empty = use provider's default_model (semantic; see §C invariants)
runtime = "codex-cli"

[roles.default.consultant_secondary]
persona = "gemini-default-consultant"
runtime = "gemini-cli"

[roles.default.reviewer]
persona = "codex-default-reviewer"
runtime = "codex-cli"
```

These ship in the same task block that authors the persona files (no ordering trap — defaults never reference a missing persona).

Default TOML bindings updated to point at these builtin personas:

```toml
[roles.default.consultant_primary]
persona = "codex-default-consultant"
model = ""              # empty = use provider's default_model
runtime = "codex-cli"

[roles.default.consultant_secondary]
persona = "gemini-default-consultant"
runtime = "gemini-cli"

[roles.default.reviewer]
persona = "codex-default-reviewer"
runtime = "codex-cli"
```

---

### F. `/z-personas` discovery command

#### F1. `commands/z-personas.md` (new)

Slash command. Subcommand-style args:
- `/z-personas list` — show all personas across layers with source.
- `/z-personas roles` — show all roles with bound persona/model/runtime per command.
- `/z-personas validate` — run `resolve-persona.py validate`.
- `/z-personas where <name>` — show which layer a persona name resolves from.

Default (no arg) → equivalent to `roles`.

#### F2. `skills/z-personas/SKILL.md` (new)

Mirrors the command. Same subcommand surface for Codex CLI / Antigravity targets.

---

### G. Multi-IDE export

Per the user's explicit non-shortcut: personas DO export in v1. The deprecated adapter scripts (`scripts/export-{common,cursor,codex,agy}.py`) must NOT be extended. Forward path: `runtime/drivers/antigravity/`.

#### G1. `runtime/drivers/antigravity/persona_export.py` (new)

Module that, given a persona file, emits the target-specific representation:
- **Antigravity (agy):** `<export-root>/.agent/personas/<name>.md` — native; agy can read these directly via a persona-aware extension point in `runtime/drivers/antigravity/`. (If agy has no native persona concept, the persona body is inlined as a system-prompt override comment, mirroring the existing "limitation comment" pattern.)
- **Cursor:** `<export-root>/.cursor/personas/<name>.mdc` — Cursor has no native persona mechanism either, so the persona body is rendered as a context-injection rule with `attach: glob: "**/*"` and an explanatory comment.
- **Codex CLI:** `<export-root>/personas/<name>.md` — flat file with `# Persona: <name>` header; the Codex orchestrator concatenates this as system prompt at consultant-dispatch time.

Each adapter records `portable: true|false` per persona in the export manifest (always true for v1 — all personas are content-only).

#### G2. `/z-export` updates

Existing command stays. New `--include=personas` flag (or implicit — include by default). Each target's adapter calls `runtime/drivers/antigravity/persona_export.py` to emit persona files alongside existing surfaces.

#### G3. `scripts/audit-tarball.sh` updates

Add `personas/` directory to the allowlist (it ships with the harness now). Existing forbidden-path rules unchanged.

---

## DRY / KISS / SOLID

- **DRY:** persona dispatch logic lives in `resolve-persona.py` only; called by both `Dispatcher.run()` and `Agent()` call sites. No duplication of resolution logic across runtimes.
- **KISS:** persona file is just a markdown file with three optional frontmatter fields. No new schema language. TOML binding is one table per (command, role).
- **SOLID:** Single Responsibility — persona file describes only behavior (prompt prefix); provider describes only runtime/CLI; model is its own axis. Open/closed — new providers / new personas / new roles added via files, no code changes.

## Edge cases and error handling

- Persona referenced in TOML doesn't exist on disk → resolver halt with "persona X not found in any layer; check /z-personas list".
- Provider referenced doesn't exist → same halt path (existing behavior, preserved).
- Both `persona` and explicit override passed → override wins; emit `persona_override_used` with both values.
- Model arg template references `{model}` but no model resolved (override unset, default_model null, args_template doesn't embed one) → halt with "no model resolved for provider X; set default_model or per-command binding".
- Three layers all define the same persona name → last layer in load order wins; emit `persona_shadowed` **once per (process, name)** via a module-local set in `resolve-persona.py`.
- Old provider name (`codex`, `gemini`, `claude` without `-cli` suffix) hardcoded in code (Python dict, bash array, agent prompt) → CI grep gate prevents merge. Gate scope: `commands/`, `skills/`, `scripts/`, `agents/`, `runtime/`. Exempt: `docs/llm/*.json` (descriptive), archived runs under `z-harness/*/archive/`, the `aliases` mapping itself in `providers.json`. Implementation: shell script under `scripts/ci-grep-gates.sh` (new), executed in CI workflow; matches `\b(codex|gemini|claude)\b` not followed by `-cli` in non-exempt paths.
- Existing TOML config that uses old names (`runtime = "codex"`) keeps working via alias resolution but emits `provider_alias_used` once per (run, alias). A `/z-config migrate` subcommand (added to `scripts/config.py`) rewrites old names to new in-place atomically; user is informed in the release notes for this slice.

## Telemetry events (new)

- `persona_bound` — `{command, role, persona, model, runtime, source}`
- `persona_override_used` — `{command, role, override_field, persona_or_model_or_runtime, original}`
- `persona_compat_warning` — `{persona, declared_roles, bound_role}`
- `persona_shadowed` — `{persona, layers, winning_layer}` (emitted once per process per name)
- `persona_binding_chimera` — `{command, role, sources: {persona: layer, model: layer, runtime: layer}}` (emitted when the three axes resolve from ≥2 layers)
- `legacy_provider_roles_used` — `{role, provider}`
- `provider_alias_used` — `{old_name, new_name}` (memoized: once per (run, alias))
- `model_resolved` — `{command, role, source: override|toml|default_model, model, runtime}`

**Collision check:** before writing TASKS.md, grep `scripts/log-event.sh` callers across the repo to confirm none of the seven new event names already exist. (Likely none do — none of the names follow existing prefixes — but mechanical check is cheap.)
