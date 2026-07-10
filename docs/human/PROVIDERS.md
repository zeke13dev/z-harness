# PROVIDERS — Runtime Registry Guide

> Last updated: 2026-07-09
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, skills/z-providers-discover/SKILL.md, docs/human/PROVIDERS.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh, .z-harness/providers.json, scripts/omp-consult.sh

## Overview

z-harness uses a **provider registry** to describe how each LLM CLI is
invoked — the executable name, argument template, model flag format, and
timeout. A provider is a runtime descriptor only; it does not dictate which
persona to use or which model to select.

Those choices live in the **role-binding layer**. See
[PERSONAS.md](PERSONAS.md) for how persona, model, and runtime are bound to
roles per command. Resolution walks four layers in priority order: the
`Z_HARNESS_CONSULT=off` sentinel short-circuit, `config.toml`
`[roles.<command>.<role>].runtime` / `[roles.default.<role>].runtime`
overrides, the legacy `[models.<role>]` provider selector, and finally the
legacy `providers.json.roles` map. Every resolved provider is preflighted
(PATH check, argv/model composition, auth readiness) before its descriptor is
returned.

## Key entry points

- `scripts/resolve-provider.sh:1` — `resolve-provider.sh` — thin wrapper (`exec python3 resolve-provider.py "$@"`) used by reviewer/consultant agents.
- `scripts/resolve-provider.py:899` — `main()` — consult-off sentinel, config load/merge/validate, TOML role-runtime override, legacy `[models]` fallback, legacy `providers.json.roles` fallback, JSON descriptor output.
- `scripts/resolve-provider.py:867` — `_resolve_role_runtime_override()` — reads `[roles.<command>.<role>].runtime` then `[roles.default.<role>].runtime`; the preferred external-provider binding surface.
- `scripts/resolve-provider.py:880` — `_resolve_models_override()` — legacy `[models.<role>]` compatibility path; validates provider existence and the `compose_argv` precondition.
- `scripts/resolve-provider.py:397` — `resolve()` — legacy `providers.json.roles` lookup with alias substitution, PATH check, and preflight.
- `scripts/resolve-provider.py:239` — `merge_with_shadow()` — per-key merge of global (`~/.config/z-harness/providers.json`) and repo (`.z-harness/providers.json`) providers/roles/aliases sections; emits de-duplicated `provider_shadowed` telemetry.
- `scripts/resolve-provider.py:469` — `compose_argv()` — renders `{model}` in `model_arg_template`; `null` template (v1/legacy) returns `args_template` unchanged.
- `scripts/resolve-provider.py:604` — `_preflight_provider()` — validates command-on-PATH, argv/model composition, and OMP auth readiness (`omp token <provider>`); emits `provider_preflight_ok`/`provider_preflight_failed`.
- `scripts/resolve-provider.py:801` — `_peek_consultant_provider()` — resolves the peer consultant's canonical provider (checking TOML override, then `[models]`, then legacy roles) without emitting alias telemetry, used to enforce the distinctness invariant.
- `scripts/discover-providers.py:58` — `discover()` — probes PATH for known CLIs (`codex`, `gemini`, `claude`, `ollama`, `agy`, `gpt`) and returns a proposed **v1** registry; never writes files.
- `skills/z-providers-discover/SKILL.md:1` — `/z-providers-discover` — interactive discovery + role-binding + atomic write command.
- `runtime/compat.py:15` — `resolve_provider()` — Python runtime wrapper that shells out to `resolve-provider.py`.
- `runtime/contract/provider.schema.json:1` — `ProviderRegistry` — draft-07 schema for `.z-harness/providers.json`, accepting versions 1 (deprecated) and 2, `kind` enum `["cli","sdk"]` (resolver only handles `"cli"`).
- `scripts/log-providers.sh:34` — none-sentinel guard — handles the plaintext `none` before any JSON parse and emits `provider_resolution_skipped`.
- `.z-harness/providers.json:1` — repo-local v2 registry; this repo binds `consultant_primary`→`omp-antigravity-pro`, `consultant_secondary`→`omp-codex`, `reviewer`→`codex-cli`.
- `scripts/omp-consult.sh:1` — stdin→arg adapter for `omp`; also classifies auth-vs-session failures and drives an explicit `--fallback` native CLI only after auth preflight succeeds.

## How it interacts with others

- `config` (config.toml) — `[roles.<command>.<role>].runtime` / `[roles.default.<role>].runtime` are the preferred external-provider binding overrides, above legacy `[models.<role>]` and `providers.json.roles`.
- `reviewer-capture` / `agents` (`consultant-primary.md`, `consultant-secondary.md`, `reviewer.md`, `pre-reviewer.md`, `self-reviewer.md`) — call `resolve-provider.sh` (or `runtime/compat.py:resolve_provider`) to get the invocation descriptor for their role; `self-reviewer` never calls it (native self-review path when `runtime.consult=off`).
- `personas-and-roles` — persona/model contract validation is a separate axis from provider resolution; the registry supplies only the runtime (command/argv/auth) axis.
- `commands` (`/z-plan`, `/z-execute`, `/z-brainstorm`, `/z-test-prune`, `/z-debug`, `/z-mr-review`, `/z-research`, `/z-review-all`, `/z-uplift`) — call `scripts/log-providers.sh` at start-up for a one-line resolution summary and `provider_resolved`/`provider_resolution_skipped` telemetry.
- `runtime/dispatch/dispatcher.py` and `z_harness_cli/mcp/server.py` / `z_harness_cli/env_bundle.py` — additional native-runtime and MCP-surface callers of provider resolution outside the shell-script agents.
- `capabilities-matrix` — keeps OMP consult-provider compatibility (`omp-antigravity-pro`, `omp-codex`) separate from first-class OMP host fidelity; consultant provider entries do not imply `OmpAdapter` support or native command-family tiers.

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
| `providers.<name>.kind` | yes | Must be `"cli"` (resolver-validated). Schema also permits `"sdk"`, but `resolve-provider.py` exits 2 if it is ever resolved. |
| `providers.<name>.command` | yes | Executable name on `PATH`. |
| `providers.<name>.args_template` | yes | Positional args passed to the command. |
| `providers.<name>.stdin` | yes | If `true`, the prompt is piped to the command's stdin. |
| `providers.<name>.model_arg_template` | no | Arg fragment appended for model selection.  Use `{model}` as placeholder.  Example: `["--model", "{model}"]`.  Set to `null` to use legacy mode (model embedded in `args_template`). |
| `providers.<name>.model_env_var` | no | If set, the effective model is also injected as this env var into the subprocess.  Ignored when `model_arg_template` is present. |
| `providers.<name>.default_model` | no | Model used when the binding supplies an empty string for model.  `null` means no fallback; resolver halts if no model is resolved. |
| `providers.<name>.timeout_s` | no | Seconds before the CLI call is killed (default 300). |
| `providers.<name>.model_label` | no | Human-readable display name (used in logs/summaries). |
| `providers.<name>.auth_env` | no | Env var name holding SDK-tier auth (only relevant for `kind="sdk"`); never logs the value. |
| `aliases` | no | Map of old provider names to new names.  Resolved at lookup time; emits `provider_alias_used` once per (run, alias). |

### `roles` map — legacy fallback only

`providers.json` may still contain a `roles` map for backward compatibility.
**This is no longer the canonical place to bind roles.**  External provider
roles are bound separately from native model classes through the TOML runtime
axis. Command-specific bindings win over defaults:

```toml
[roles.z_plan.consultant_primary]
runtime = "omp-antigravity-pro"

[roles.default.consultant_primary]
runtime = "omp-antigravity-pro"
```

`[models.*]` provider selectors are still accepted as a lower-priority
compatibility path, but new config should use `[roles.*.*].runtime`.  When
`providers.json` `roles` is the only binding present, z-harness uses it and
emits a `legacy_provider_roles_used` event as a reminder to migrate.

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
runs (lines 910-913 of `scripts/resolve-provider.py`, inside `main()`).  The
resolver skips both steps entirely for any off-mode role.

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
[providers] consultant_primary=omp-antigravity-pro(Antigravity Gemini 3.1 Pro)  consultant_secondary=omp-codex(gpt-5.5)  reviewer=codex-cli(gpt-5-codex)
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

OMP provider entries that call `scripts/omp-consult.sh` are compatibility wrappers for consultant/reviewer roles only. The current default external consult arms are `omp-antigravity-pro` for Antigravity-backed Gemini 3.1 Pro and `omp-codex` for OMP Codex GPT-5.5. The legacy name `omp-gemini` remains an alias for `omp-antigravity-pro`.

Do not treat `omp-antigravity-pro`/`omp-codex`-style provider bindings as evidence for OMP native command dispatch or OMP export parity. Current OMP adapter/export support uses `z_harness_cli/adapters/omp.py` plus `runtime/drivers/omp/export.py`, reports native adapter/export fidelity, and bounds command-family native claims to the capabilities parity matrix: `/z-execute`, `/z-consult`, `/z-gate`, and `/z-panel` are native with T008 evidence; other families remain degraded until promoted by parity evidence. Direct `gemini-cli` remains available as an explicitly named direct provider or as an explicit fallback command inside an OMP provider entry; it is not the Gemini-labeled OMP consult provider.

Similarly, `codex-cli` provider entries invoke the external Codex CLI for provider roles only. They are not evidence for native Codex z-harness command orchestration. Current Codex support is split: export fidelity is partial because native skills/custom agents/MCP artifacts are emitted, while the CLI adapter remains flattened and multi-agent command families remain blocked until native runtime primitive and driver-hook evidence exists.

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
   also null, the resolver halts with an actionable error (`ValueError` inside
   `compose_argv`, converted to a `provider_preflight_failed` exit by the caller).


### Provider preflight and auth classification

Before a provider descriptor is returned or dispatched, z-harness preflights
(`_preflight_provider`, `scripts/resolve-provider.py:604`):

1. the role binding resolves to a defined provider;
2. the provider command is available on `PATH`;
3. `args_template + model_arg_template` can compose a concrete argv/model; and
4. auth is ready when the provider declares a checkable backend.

OMP consult providers are classified by the model prefix in `args_template`:

| Provider | Model prefix | Auth backend |
|----------|--------------|--------------|
| `omp-antigravity-pro` | `google-antigravity/...` | OMP OAuth / Antigravity |
| `omp-codex` | `openai-codex/...` | OMP OAuth / Codex |

OMP auth readiness is checked with `omp token <provider>` and never logs token
values. If auth is missing, resolution/dispatch fails loudly with the role,
provider, attempted model, auth backend, and a re-auth hint. Capturing browser
login links is handled by the later re-auth assistance flow; preflight only
classifies readiness and stops before dispatch.

Explicit native fallbacks in `omp-consult.sh --fallback ...` are used only after
OMP auth preflight succeeds and the OMP model call itself produces no usable
output. Auth failures do not fall back silently. `omp-consult.sh` also
pattern-matches stderr for auth/session-failure phrasing (`_is_omp_auth_or_session_failure`)
so an expired OMP session fails loud with a re-auth hint instead of silently
degrading to the native fallback.

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

No file changes required for existing v1 configs. The upgrade is memoized
per (process, file path) so loading both a v1 global and a v1 repo config
emits `provider_schema_v1_upgraded` at most once per file.

---

## Provider naming

Current canonical direct-CLI names use a `-cli` suffix to distinguish the CLI
runtime from the model family. OMP consult providers use explicit backend names
when the label would otherwise imply a direct vendor CLI:

| Canonical name | Command | Replaces / compatibility name |
|----------------|---------|-------------------------------|
| `codex-cli` | `codex` | `codex` (v1) |
| `gemini-cli` | `gemini` | `gemini` (v1); direct Gemini CLI only |
| `claude-cli` | `claude` | `claude` (v1) |
| `cursor-cli` | `cursor-agent` | `cursor` (v1); only shipped provider besides `agy-cli` with a non-null `model_arg_template` |
| `agy-cli` | `agy` | `agy` (v1) |
| `omp-antigravity-pro` | `omp-consult.sh` | `omp-gemini` |

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
      "model_label": "Direct Gemini CLI"
    },
    "omp-antigravity-pro": {
      "kind": "cli",
      "command": "omp-consult.sh",
      "args_template": ["google-antigravity/gemini-3.1-pro", "--fallback", "gemini", "-p", "-", "--approval-mode", "plan", "--output-format", "text"],
      "stdin": true,
      "timeout_s": 300,
      "model_label": "Antigravity Gemini 3.1 Pro",
      "model_arg_template": null,
      "model_env_var": null,
      "default_model": null
    }
  },
  "aliases": {
    "codex": "codex-cli",
    "gemini": "gemini-cli",
    "omp-gemini": "omp-antigravity-pro"
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
4. Bind a role in `config.toml` with `[roles.<command>.<role>]` or `[roles.default.<role>]` and `runtime = "<name>"`.
   See [PERSONAS.md — TOML binding](PERSONAS.md#toml-binding).

Example wrapper skeleton:

```bash
#!/usr/bin/env bash
# my-llm-wrapper — reads prompt from stdin, writes response to stdout
PROMPT="$(cat)"
my-llm-api call --prompt "$PROMPT"
```

---

## Edge cases / gotchas

- `Z_HARNESS_CONSULT=off` bypasses config loading and the distinctness check entirely — setting it is sufficient; no `providers.json` change needed.
- `log-providers.sh` checks for `none` at line 34 **before** calling any Python JSON parse — receiving `none` unguarded would otherwise crash `json.load`.
- Schema at `runtime/contract/provider.schema.json` permits `kind="sdk"` and optional `auth_env`/`session_resumable`/`allow_cross_vendor_env`, but `resolve-provider.py` validates only `kind="cli"` — an SDK entry passes schema but causes exit 2 if resolved.
- `Z_HARNESS_REPO_PROVIDERS` overrides the repo config path entirely, bypassing git-based discovery of the repo root.
- The shadow de-dup stamp file is keyed on `os.getppid()`, not PID — the warning fires once per parent process tree, not once per subshell.
- A role with no bound provider halts immediately with an actionable error pointing at `/z-providers-discover`.
- A CLI missing from `PATH` causes exit 1 even if the config entry is otherwise valid.
- `discover-providers.py` still emits `version: 1` and old-style names (`codex`, `gemini`, `claude`, `ollama`, `agy`, `gpt`) — intentional; the resolver upgrades v1 registries transparently in memory.
- `resolve()` unconditionally passes `is_legacy=True` when resolving from `providers.json.roles`, so `legacy_provider_roles_used` fires on every lookup through that path, alias or not; when an alias is also matched, both `legacy_provider_roles_used` and `provider_alias_used` fire for one resolution.
- `cursor-cli` and `agy-cli` are the only shipped providers with a non-null `model_arg_template` (`["--model", "{model}"]`) and a `default_model` set; every other shipped provider uses `null` `model_arg_template` (v1/legacy mode).
- Do not use `omp-antigravity-pro`/`omp-codex` provider dispatch success as evidence of OMP native host parity — provider dispatch tests only cover consultant compatibility, not `OmpHostDriver`.

---

## Error messages

| Message | Cause | Fix |
|---------|-------|-----|
| `[providers] provider_preflight_failed: role=<r> ... role is unbound` | No runtime bound for role | Add a `[roles.<command>.<r>]` or `[roles.default.<r>]` entry to `config.toml`, or run `/z-providers-discover`. |
| `[providers] provider_preflight_failed: role=<r>, provider=<p> ... command=<c> not on PATH` | CLI missing from shell `PATH` | Install the CLI or update `PATH`. |
| `[providers] schema version must be 1 or 2` | `version` field wrong or missing | Set `"version": 2` in your config. |
| `[providers] consultant_primary and consultant_secondary must resolve to DISTINCT providers` | Both consultant roles point to the same provider | Bind them to different providers. |
| `[providers] provider_preflight_failed ... argv/model composition failed` | `model_arg_template` present but no model resolved, `default_model` is null | Set `default_model` in the provider or bind a model in `config.toml`. |
| `[providers] provider_preflight_failed ... auth not ready for openai-codex/google-antigravity` | OMP OAuth token is missing or expired | Run `omp`, then `/login` for the named provider; retry after `omp token <provider>` succeeds. |

---

## Run-start observability

Every command that dispatches a consultant or reviewer calls
`scripts/log-providers.sh` at start-up.  It prints a one-line summary:

```
[providers] consultant_primary=omp-antigravity-pro(Antigravity Gemini 3.1 Pro)  consultant_secondary=omp-codex(gpt-5.5)  reviewer=codex-cli(gpt-5-codex)
```

…and emits a `provider_resolved` event per role to `metrics.jsonl`. Provider
resolution and runtime dispatch also emit `provider_preflight_ok` or
`provider_preflight_failed`. If an explicit OMP native fallback is actually
used, `omp-consult.sh` emits `provider_fallback_used` with role, provider,
attempted model, auth backend, and fallback provider; token values, env values,
and stderr dumps are never logged.

For full role resolution details (including persona and model), see the
`persona_bound` and `model_resolved` events documented in
[PERSONAS.md — Telemetry events](PERSONAS.md#telemetry-events).

## Examples

```toml
[roles.default.consultant_primary]
runtime = "omp-antigravity-pro"

[roles.default.consultant_secondary]
runtime = "omp-codex"

[roles.default.reviewer]
runtime = "codex-cli"
```

```bash
Z_HARNESS_CONSULT=off /z-plan "small local change"
# provider resolution returns: none
```
