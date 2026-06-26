# PROVIDERS — Runtime Registry Guide

> Last updated: 2026-06-24
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, commands/z-providers-discover.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh, scripts/omp-consult.sh, .z-harness/providers.json

## Overview

z-harness uses a **provider registry** to describe how each LLM CLI is
invoked — the executable name, argument template, model flag format, and
timeout.  A provider is a runtime descriptor only; it does not dictate which
persona to use or which model to select.

Those choices live in the **role-binding layer**.  See
[PERSONAS.md](PERSONAS.md) for how persona, model, and runtime are bound to
roles per command.

---

## Config file locations + precedence

| Priority | Path | Wins on |
|----------|------|---------|
| Repo-local (higher) | `<repo>/.z-harness/providers.json` | Any key present in this file |
| User-global (lower) | `~/.config/z-harness/providers.json` | All other keys |

Merge is **per-key**, not whole-file.  If both files define `providers.codex-cli`,
the repo file wins for that key only.  All other providers come from the global
file.

Whenever a repo key shadows a global key, z-harness prints a warning to stderr:

```
[providers] provider_shadowed: providers.codex-cli — repo (.z-harness/providers.json) overrides global (~/.config/z-harness/providers.json)
```

…and emits a `provider_shadowed` event to `metrics.jsonl`.

### Testability env override

Set `Z_HARNESS_REPO_PROVIDERS=/path/to/fixture.json` to point the resolver at
any file instead of the actual repo config.  Useful in CI or test scripts.

---

## Schema (version 2)

```json
{
  "version": 2,
  "providers": {
    "<name>": {
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
    "consultant_primary": "<provider-name>"
  },
  "aliases": {
    "codex":  "codex-cli",
    "gemini": "gemini-cli",
    "claude": "claude-cli"
  }
}
```

### Field reference

| Field | Required | Description |
|-------|----------|-------------|
| `version` | yes | `2` is current.  `1` is accepted and upgraded in-memory (see below). |
| `providers.<name>.kind` | yes | Must be `"cli"` (only kind supported). |
| `providers.<name>.command` | yes | Executable name on `PATH`. |
| `providers.<name>.args_template` | yes | Positional args passed to the command. |
| `providers.<name>.stdin` | yes | If `true`, the prompt is piped to the command's stdin. |
| `providers.<name>.model_arg_template` | no | Arg fragment appended for model selection.  Use `{model}` as placeholder.  Example: `["--model", "{model}"]`.  Set to `null` to use legacy mode (model embedded in `args_template`). |
| `providers.<name>.model_env_var` | no | If set, the effective model is also injected as this env var into the subprocess.  Ignored when `model_arg_template` is present. |
| `providers.<name>.default_model` | no | Model used when the binding supplies an empty string for model.  `null` means no fallback; resolver halts if no model is resolved. |
| `providers.<name>.timeout_s` | no | Seconds before the CLI call is killed (default 300). |
| `providers.<name>.model_label` | no | Human-readable display name (used in logs/summaries). |
| `aliases` | no | Map of old provider names to new names.  Resolved at lookup time; emits `provider_alias_used` once per (run, alias). |

### `roles` map — legacy fallback only

`providers.json` may still contain a `roles` map for backward compatibility.
**This is no longer the canonical place to bind roles.**  The preferred
approach is `[roles.*.*]` tables in `config.toml` — see
[PERSONAS.md — TOML binding](PERSONAS.md#toml-binding).

When `providers.json` `roles` is the only binding present, z-harness uses it
and emits a `legacy_provider_roles_used` event as a reminder to migrate.  The
TOML binding always takes precedence if both exist.

---

## Disabling providers: Z_HARNESS_CONSULT=off

Set `Z_HARNESS_CONSULT=off` to run all commands in **single-model mode**.
When this variable is set, `resolve-provider.py` returns the plaintext
sentinel `none` (not JSON) and exits 0 for the three roles that would
normally require a separate external model:

- `consultant_primary`
- `consultant_secondary`
- `reviewer`

The `none` sentinel is detected **before** any config file is loaded and
**before** the `consultant_primary != consultant_secondary` distinctness check
runs (lines 514-517 of `scripts/resolve-provider.py`).  The resolver skips
both steps entirely for any off-mode role.

### What consumers do on `none`

Consumers that receive the `none` sentinel must not attempt JSON parsing.
Their behavior by role:

| Role | Consumer | Behavior on `none` |
|------|----------|--------------------|
| `consultant_primary` | `/z-plan` Phase 3 | Skips the external consult entirely; logs `{"phase":3,"reason":"Z_HARNESS_CONSULT=off"}` |
| `consultant_secondary` | `/z-plan` Phase 7 | Skips the external consult entirely; logs `{"phase":7,"reason":"Z_HARNESS_CONSULT=off"}` |
| `reviewer` | `/z-execute` review gate | Replaces external reviewer with a same-model self-review (`self-reviewer` agent subagent) |

The `self-reviewer` agent (`agents/self-reviewer.md`) is a read-only
inspection agent.  It produces the same response shape as the standard
reviewer (blockers/majors/minors) but never calls `resolve-provider.sh` or
any external CLI.

### Observability

`scripts/log-providers.sh` checks for the `none` sentinel before any JSON
parse (line 34).  On `none`, it appends `${ROLE}=skipped(consult=off)` to the
summary line and emits a `provider_resolution_skipped` event with payload
`{"role": "<role>", "reason": "Z_HARNESS_CONSULT=off"}`.

Normal summary (consult on):
```
[providers] consultant_primary=gemini-cli(gemini-2.5-pro)  consultant_secondary=codex-cli(gpt-5-codex)  reviewer=codex-cli(gpt-5-codex)
```

Single-model summary (consult off):
```
[providers] consultant_primary=skipped(consult=off)  consultant_secondary=skipped(consult=off)  reviewer=skipped(consult=off)
```

### When to use

`Z_HARNESS_CONSULT=off` is intended for:

- Local quick-turnaround runs where you do not want to pay for two model calls.
- CI pipelines that have access to only one model credential.
- Debugging command logic without triggering external provider bindings.

Leave `Z_HARNESS_CONSULT` unset (or set to `on`) for normal multi-model operation.

### OMP consult-provider compatibility

OMP provider entries that call `scripts/omp-consult.sh` are compatibility wrappers for consultant/reviewer roles only. The wrapper adapts provider-registry prompt handling to `omp -p --no-session --no-rules --model ... <prompt>` and remains separate from OMP adapter/export support and future native command dispatch.

Do not treat `omp-gemini`/`omp-codex`-style provider bindings as evidence for OMP native command dispatch or OMP export parity. Current partial OMP support uses `z_harness_cli/adapters/omp.py` plus `runtime/drivers/omp/export.py`, reports partial fidelity, blocks multi-agent commands, and keeps single-agent commands degraded until the T009/native parity gate.

---

## argv composition

Final argv is built as:

```
args_template + render(model_arg_template, model=effective_model)
```

Rules:
1. `{model}` in any element of `model_arg_template` is replaced with `effective_model`.
2. When `model_arg_template` is `null` or absent, no model arg is appended
   (legacy mode — the model must already be embedded in `args_template`).
3. When `model_env_var` is set and `model_arg_template` is absent, the env var
   is also injected into the subprocess environment.
4. Empty `effective_model` string → use `default_model`.  If `default_model` is
   also null, the resolver halts with an actionable error.

---

## Version 1 → 2 upgrade

Schema v1 files keep working.  At load time, v1 providers are upgraded
in-memory:

| v1 | v2 equivalent |
|----|---------------|
| *(missing)* `model_arg_template` | `null` (legacy mode) |
| *(missing)* `model_env_var` | `null` |
| *(missing)* `default_model` | `null` |
| *(missing)* `aliases` | `{}` |

No file changes required for existing v1 configs.

---

## Provider naming

Current canonical names use a `-cli` suffix to distinguish the CLI runtime
from the model family:

| Canonical name | Command | Replaces |
|----------------|---------|---------|
| `codex-cli` | `codex` | `codex` (v1) |
| `gemini-cli` | `gemini` | `gemini` (v1) |
| `claude-cli` | `claude` | `claude` (v1) |

Old names continue to work via the `aliases` map.  Each use emits a
one-time `provider_alias_used` deprecation event.  To migrate old names
atomically, run:

```
/z-config migrate
```

This rewrites old provider names to canonical names in-place across your
config files.

---

## Minimal example (v2)

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
      "stdin": true,
      "timeout_s": 300,
      "model_label": "Codex CLI"
    },
    "gemini-cli": {
      "kind": "cli",
      "command": "gemini",
      "args_template": ["-p", "@-", "--approval-mode", "plan", "--output-format", "text"],
      "model_arg_template": ["--model", "{model}"],
      "model_env_var": null,
      "default_model": "gemini-2.5-pro",
      "stdin": false,
      "timeout_s": 240,
      "model_label": "Gemini CLI"
    }
  },
  "aliases": {
    "codex":  "codex-cli",
    "gemini": "gemini-cli"
  }
}
```

Role binding is configured separately in `config.toml` — see
[PERSONAS.md — TOML binding](PERSONAS.md#toml-binding).

---

## Discovery command

Run `/z-providers-discover` to auto-detect installed LLM CLIs and generate a
starter `providers.json`.  The command probes your `PATH` for `codex`,
`gemini`, `claude`, `ollama`, `agy`, and `gpt`; shows the proposed config; and
asks which roles to bind before writing.

For CLIs not in the auto-detect list, add them manually following the schema
above.

---

## Adding a custom CLI provider

1. Write a wrapper script that reads the prompt from stdin (or a named arg) and
   prints the response to stdout.  Exit 0 on success, nonzero on failure.
2. Put it on your `PATH` (or supply an absolute path as `command`).
3. Add a stanza under `providers` in your `~/.config/z-harness/providers.json`.
4. Bind a role in `config.toml` via `[roles.default.<role>] runtime = "<name>"`.
   See [PERSONAS.md — TOML binding](PERSONAS.md#toml-binding).

Example wrapper skeleton:

```bash
#!/usr/bin/env bash
# my-llm-wrapper — reads prompt from stdin, writes response to stdout
PROMPT="$(cat)"
my-llm-api call --prompt "$PROMPT"
```

---

## Error messages

| Message | Cause | Fix |
|---------|-------|-----|
| `[providers] role=<r> unbound — run /z-providers-discover` | No runtime bound for role | Add a `[roles.default.<r>]` entry to `config.toml` or run `/z-providers-discover`. |
| `[providers] role=<r>, provider=<p>, command=<c> not on PATH` | CLI missing from shell `PATH` | Install the CLI or update `PATH`. |
| `[providers] schema version must be 1 or 2` | `version` field wrong or missing | Set `"version": 2` in your config. |
| `[providers] consultant_primary and consultant_secondary must resolve to DISTINCT providers` | Both consultant roles point to the same provider | Bind them to different providers. |
| `[providers] no model resolved for provider <p>` | `model_arg_template` present but no model resolved, `default_model` is null | Set `default_model` in the provider or bind a model in `config.toml`. |

---

## Run-start observability

Every command that dispatches a consultant or reviewer calls
`scripts/log-providers.sh` at start-up.  It prints a one-line summary:

```
[providers] consultant_primary=codex-cli(gpt-5-codex)  consultant_secondary=gemini-cli(gemini-2.5-pro)  reviewer=codex-cli(gpt-5-codex)
```

…and emits a `provider_resolved` event per role to `metrics.jsonl`.

For full role resolution details (including persona and model), see the
`persona_bound` and `model_resolved` events documented in
[PERSONAS.md — Telemetry events](PERSONAS.md#telemetry-events).
