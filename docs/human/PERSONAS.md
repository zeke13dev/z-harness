# PERSONAS — Persona System Guide

> Last updated: 2026-05-28

## Overview

A **persona** is a saved prompt-prefix preset that gets prepended to a role's
task prompt at dispatch time.  Persona, model, and runtime are **orthogonal
axes** — each is configured independently, not bundled together.

- **Persona** — what behavioral tone and context the agent has (prompt prefix).
- **Model** — which model to use (e.g. `gpt-5-codex`, `gemini-2.5-pro`).
- **Runtime** — which CLI provider executes the call (e.g. `codex-cli`, `gemini-cli`).

You can mix any combination: a Gemini-tuned persona body with the `codex-cli`
runtime and any model string your CLI accepts.

See [PROVIDERS.md](PROVIDERS.md) for the runtime registry that describes how
each CLI is invoked.

---

## Persona file format

Persona files are plain Markdown with an optional YAML frontmatter block.

```markdown
---
name: codex-default-reviewer
description: Default Codex reviewer persona — adversarial, blockers/majors only.
compatible_roles: [reviewer]
contract: review-verdict
---

You are an adversarial code reviewer.  Your job is to find blockers and major
issues only — do not report style nits or minor suggestions.

Return your verdict in this exact structure:
VERDICT: PASS | FAIL | BLOCKED
...
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique identifier.  Must match `^[a-z0-9-]+$` (kebab-case; no dots or slashes). |
| `description` | no | Human-readable summary shown by `/z-personas list`. |
| `compatible_roles` | no | Soft hint: list of roles this persona is designed for.  A mismatch emits a `persona_compat_warning` event but does not block. |
| `contract` | no | Expected output structure: `freeform`, `review-verdict`, or `strict-json`.  When the bound role declares an `expected_contract`, a mismatch here is a hard failure at startup. |

### Body

Everything below the closing `---` is the prompt prefix.  It is prepended
verbatim before the role's task prompt at dispatch time.  No interpolation in
v1 — the body is treated as a static string.

---

## Layered storage and precedence

Personas are discovered from three layers in ascending priority (last wins per
name):

| Layer | Path | Priority |
|-------|------|----------|
| Builtin (shipped with harness) | `personas/builtin/` | Lowest |
| User-global | `~/.config/z-harness/personas/` | Middle |
| Repo-local | `<repo>/.z-harness/personas/` | Highest |

When the same `name` appears in more than one layer, the highest-priority layer
wins and z-harness emits a `persona_shadowed` event (once per process per
name):

```
[personas] persona_shadowed: codex-default-reviewer — repo overrides user-global
```

Run `/z-personas where <name>` to see all layers that define a persona and
which one won.

---

## TOML binding

Bind a persona (plus model and runtime) to a specific (command, role) pair in
your `config.toml`:

```toml
# Per-command binding — takes effect only for /z-plan
[roles.z_plan.consultant_primary]
persona  = "my-custom-consultant"
model    = "gpt-5-codex"
runtime  = "codex-cli"

# Default binding — applies to any command not listed above
[roles.default.consultant_primary]
persona  = "codex-default-consultant"
model    = ""              # empty string = use provider's default_model
runtime  = "codex-cli"

[roles.default.consultant_secondary]
persona  = "gemini-default-consultant"
runtime  = "gemini-cli"

[roles.default.reviewer]
persona  = "codex-default-reviewer"
runtime  = "codex-cli"
```

### Key rules

- Command names use underscores in TOML (`z_plan` not `/z-plan`).  `/z-personas`
  translates back to slash-form on output.
- All three fields (`persona`, `model`, `runtime`) are optional within a
  `[roles.*.*]` table — set only what you want to override.
- Per-field merge: when a repo TOML sets `model` and a global TOML sets
  `persona`, the merged binding has both.

### Resolution order

At dispatch time, each axis (persona, model, runtime) is resolved independently
in this priority:

1. **Per-Agent() / Dispatcher.run() kwargs** — explicit call-site override.
2. **`[roles.<command>.<role>]` in config.toml** — command-scoped binding.
3. **`[roles.default.<role>]` in config.toml** — cross-command default.
4. **Legacy `providers.json` `roles` mapping** — backward-compat fallback (emits `legacy_provider_roles_used`).
5. **Error** — halt with actionable message.

---

## Per-Agent() override kwargs

Command authors can override any axis dynamically at the call site without
touching config files.  Pass keyword arguments to `Agent()` or
`Dispatcher.run()`:

```python
# Override persona and model for a single dispatch
agent = Agent(
    subagent_type="consultant",
    description="Deep-dive review of auth module",
    prompt=task_prompt,
    # Persona / model / runtime overrides:
    persona="my-security-consultant",
    model="o3",
    runtime="codex-cli",
)
```

The three optional kwargs are:

| Kwarg | Description |
|-------|-------------|
| `persona` | Name of a persona from any layer (builtin, user-global, or repo). |
| `model` | Model string passed to the CLI.  Overrides config and provider defaults. |
| `runtime` | Provider name from the registry (e.g. `codex-cli`, `gemini-cli`). |

When any override is active, z-harness emits a `persona_override_used` event
recording both the override value and what the config default would have been.

---

## `/z-personas` discovery command

`/z-personas` is the interactive tool for exploring the persona system.

| Invocation | What it does |
|------------|-------------|
| `/z-personas` | Equivalent to `/z-personas roles` (default). |
| `/z-personas list` | All personas across all layers with their source. |
| `/z-personas roles` | All roles with bound persona/model/runtime per command. |
| `/z-personas validate` | Run schema checks; verify contract compatibility for all default bindings. |
| `/z-personas where <name>` | Show the load-order chain for a persona name (all layers, winner marked). |

Example output of `/z-personas roles`:

```
/z-plan
  consultant_primary  → persona: codex-default-consultant  model: gpt-5-codex  runtime: codex-cli  (source: roles.default)
  consultant_secondary→ persona: gemini-default-consultant  model: gemini-2.5-pro  runtime: gemini-cli  (source: roles.default)
  reviewer            → persona: codex-default-reviewer    model: gpt-5-codex  runtime: codex-cli  (source: roles.default)
```

---

## Builtin personas

Three personas ship with the harness under `personas/builtin/`:

| Name | Compatible roles | Contract |
|------|-----------------|----------|
| `codex-default-consultant` | `consultant_primary`, `consultant_secondary` | `freeform` |
| `gemini-default-consultant` | `consultant_primary`, `consultant_secondary` | `freeform` |
| `codex-default-reviewer` | `reviewer` | `review-verdict` |

These form the default bindings used when no TOML overrides are present.

---

## Troubleshooting

### `persona_binding_chimera` event

This event fires when a single binding's three axes (persona, model, runtime)
resolve from two or more different layers:

```
[personas] persona_binding_chimera: command=z_plan role=consultant_primary
  persona → roles.z_plan (repo TOML)
  model   → roles.default (global TOML)
  runtime → roles.default (global TOML)
```

A chimera is **not an error** — resolution still proceeds.  It is a soft
observability signal so you can spot unintended pairings (e.g. a
Gemini-tuned persona body paired with the `codex-cli` runtime).

**To resolve:** either consolidate all three axes into the same
`[roles.<command>.<role>]` table, or verify the pairing is intentional.

### `persona_shadowed` debug

When a persona name exists in more than one layer, only the highest-priority
layer is used.  To see all layers:

```
/z-personas where my-custom-consultant
```

Output:

```
my-custom-consultant
  [1] personas/builtin/my-custom-consultant.md      (builtin)
  [2] ~/.config/z-harness/personas/my-custom-consultant.md  (user-global) ← winner
```

If your edits to a repo-local persona seem to have no effect, check whether
a user-global or builtin definition is shadowing it.

### Persona not found

If dispatch halts with:

```
[personas] persona X not found in any layer; check /z-personas list
```

The persona name in your TOML binding does not match any `.md` file across all
three layers.  Run `/z-personas list` to see what is available and check for
typos in `name` frontmatter vs. the binding string.

### Contract mismatch at startup

```
[personas] contract mismatch: role=reviewer expects contract=review-verdict but persona=my-persona declares contract=freeform
```

The `reviewer` role requires a structured `PASS/FAIL/BLOCKED` output format.
Either switch to a persona with `contract: review-verdict`, or author a new
persona with the correct contract declaration.

---

## Authoring a custom persona

1. Create `<repo>/.z-harness/personas/<your-name>.md`.
2. Add frontmatter with at least `name: <your-name>`.
3. Write the prompt prefix in the body.
4. Bind it in `config.toml`:
   ```toml
   [roles.default.consultant_primary]
   persona = "<your-name>"
   ```
5. Run `/z-personas validate` to check for contract/compat issues.

---

## Telemetry events

| Event | Fired when |
|-------|-----------|
| `persona_bound` | Each dispatch: records `{command, role, persona, model, runtime, source}`. |
| `persona_override_used` | A per-Agent() kwarg overrides a config default. |
| `persona_compat_warning` | A persona is bound to a role not in its `compatible_roles`. |
| `persona_shadowed` | A persona name is defined in more than one layer (once per process per name). |
| `persona_binding_chimera` | A binding's three axes resolve from ≥2 different config layers. |
| `legacy_provider_roles_used` | Resolution falls back to `providers.json` `roles` map. |
| `model_resolved` | Records `{command, role, source, model, runtime}` at dispatch. |
