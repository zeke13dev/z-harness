# Providers Registry

> Last updated: 2026-06-19
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, commands/z-providers-discover.md, docs/human/PROVIDERS.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh, .z-harness/providers.json

## Overview

The providers registry describes how each LLM CLI is invoked — the executable name, argument template, model flag format, and timeout. A provider is a runtime invocation descriptor only; it does not determine which persona to use or which model to select. Those concerns live in the role-binding layer (`config.toml [roles]` or `config.toml [models]` sections).

Resolution has a three-tier priority order. When `Z_HARNESS_CONSULT=off` is set, the resolver immediately returns the plaintext sentinel `none` for consultant/reviewer roles without loading any config file. Otherwise, if `config.toml [models.<role>]` is set it overrides the providers.json roles map. The legacy `providers.json.roles` map is the fallback for any role not covered by the TOML section. The resolver validates every provider entry on every call — not just the one being resolved — and checks that consultant_primary and consultant_secondary are distinct (enforced across both TOML and legacy binding paths).

## Key entry points

- `scripts/resolve-provider.sh:1` — `resolve-provider.sh` — Thin bash wrapper; the single entry point for all consultant/reviewer dispatch sites.
- `scripts/resolve-provider.py:634` — `main` — Loads configs, checks `Z_HARNESS_CONSULT=off` sentinel, invokes `_resolve_models_override` (TOML path), then falls back to `resolve()` (legacy path); prints JSON descriptor or `none`.
- `scripts/resolve-provider.py:555` — `_resolve_models_override` — Reads `config.py get models.<role>`; on a hit, looks up the named provider in the merged map, checks compose_argv precondition, enforces consultant distinctness, returns descriptor. Returns `None` on miss (silent fallback).
- `scripts/resolve-provider.py:539` — `_peek_consultant_provider` — Returns the provider a consultant role would resolve to (TOML override first, then legacy roles) without exiting; used by `_resolve_models_override` for cross-path distinctness enforcement.
- `scripts/resolve-provider.py:522` — `_check_compose_argv_precondition` — Guards compose_argv: when `model_arg_template` is non-null, `default_model` must also be set for a safe [models] override lookup.
- `scripts/resolve-provider.py:359` — `resolve` — Role→provider→command lookup via the legacy roles map with alias substitution and PATH check; exits 1 if unresolvable.
- `scripts/resolve-provider.py:170` — `load_configs` — Locates and loads global + repo JSON; validates schema version; runs v1→v2 in-memory upgrade.
- `scripts/resolve-provider.py:227` — `merge_with_shadow` — Per-key merge of global + repo configs across providers/roles/aliases; emits `provider_shadowed` events for shadowed keys.
- `scripts/resolve-provider.py:443` — `compose_argv` — Builds full argv from descriptor + effective_model; renders `{model}` in `model_arg_template`; raises ValueError if no model can be resolved; returns `args_template` immediately when `model_arg_template` is null (v1 legacy mode).
- `scripts/resolve-provider.py:64` — `_upgrade_v1_to_v2` — In-memory v1→v2 upgrade: adds `model_arg_template`/`model_env_var`/`default_model` as nulls; emits `provider_schema_v1_upgraded` memoized per (process, file path).
- `scripts/resolve-provider.py:422` — `check_consultant_distinctness` — Invariant: consultant_primary != consultant_secondary on the legacy path; exits 1 on collision.
- `scripts/resolve-provider.py:331` — `_apply_aliases` — Substitutes old provider name with canonical via aliases map; emits `provider_alias_used` (memoized per process+old-name).
- `scripts/resolve-provider.py:112` — `_validate_provider_entry` — Validates all required fields for a single provider entry; exits 2 on any field violation.
- `scripts/discover-providers.py:58` — `discover` — Probes PATH for known CLIs; returns proposed v1 providers.json dict. Never writes.
- `scripts/log-providers.sh:34` — `none-sentinel-guard` — Detects `none` sentinel before JSON parse; emits `provider_resolution_skipped` event; appends `role=skipped(consult=off)` to summary.
- `runtime/compat.py:15` — `resolve_provider` — Python API wrapper around `resolve-provider.py` for the runtime dispatch layer.
- `runtime/contract/provider.schema.json:1` — `ProviderRegistry` — JSON Schema Draft 7 for `.z-harness/providers.json`; accepts version 1 and 2; permits `kind=cli|sdk`; includes `allow_cross_vendor_env` field.

## How it interacts with others

- `config` — `_resolve_models_override` reads `config.py get models.<role>` to determine the TOML-path binding. The `[models]` section is now the canonical role-override layer above providers.json.
- `personas-and-roles` — The persona registry uses provider resolution for the runtime axis of each binding: persona/model/runtime=provider.
- `agents` — Consultant and reviewer subagents (consultant-primary, consultant-secondary, reviewer, self-reviewer) consume the resolution output. When the sentinel is `none`, self-reviewer is used instead of an external CLI.
- `commands` — Commands that dispatch external models call `log-providers.sh` at startup for observability, then invoke `resolve-provider.sh` for actual dispatch.
- `scripts` — Depends on `log-event.sh` for telemetry events (all best-effort and non-fatal).

## Edge cases / gotchas

- `Z_HARNESS_CONSULT=off` bypasses config loading and the distinctness check entirely. Setting it is sufficient; no providers.json change is needed.
- `log-providers.sh` checks for `none` at line 34 BEFORE any JSON parse. Receiving `none` previously caused `json.load` to crash; the guard ensures a clean `provider_resolution_skipped` event instead.
- The schema at `runtime/contract/provider.schema.json` permits `kind='sdk'` and optional `auth_env`/`session_resumable`/`allow_cross_vendor_env`, but `resolve-provider.py` validates only `kind='cli'` — SDK entries pass the JSON Schema but cause exit 2 if resolved.
- `Z_HARNESS_REPO_PROVIDERS` env var overrides the repo config path entirely, bypassing git-based discovery. Used in CI and tests.
- Shadow de-dup stamp file is keyed on PPID — warning fires once per parent process tree, not once per subshell.
- `_resolve_models_override` enforces consultant distinctness across ALL combinations of TOML and legacy path, not just within the same path. `_peek_consultant_provider` checks both sources when computing the peer provider.
- `cursor-cli` and `agy-cli` are the only shipped providers with non-null `model_arg_template` and a `default_model`. All other shipped providers use null `model_arg_template` (v1 legacy mode).
- `.z-harness/providers.json` ships both old names (codex/gemini/claude/cursor/agy) and new `-cli` canonical names as first-class entries. The `aliases` map covers the same five entries for transparent backward compatibility.
- `discover-providers.py` KNOWN_CLIS still uses v1-style names and outputs `version: 1`. This is intentional — v1 output is upgraded transparently on load.
- When both `legacy_provider_roles_used` and `provider_alias_used` fire for a single resolution (old name in roles map), two distinct events are emitted.
- `_alias_used_emitted` is module-level — alias dedup survives multiple `resolve()` calls within the same process but resets on new process invocations.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/providers-registry.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded yet._

## Examples

Minimal v2 providers.json with dual-entry pattern:

```json
{
  "version": 2,
  "providers": {
    "codex-cli": {
      "kind": "cli", "command": "codex", "args_template": ["exec", "-"],
      "stdin": true, "timeout_s": 300, "model_label": "gpt-5-codex",
      "model_arg_template": null, "model_env_var": null, "default_model": null
    }
  },
  "aliases": { "codex": "codex-cli" }
}
```

TOML role binding (preferred over providers.json.roles):

```toml
[models]
consultant_primary = "gemini-cli"
consultant_secondary = "codex-cli"
reviewer = "codex-cli"
```

Disable all external consults:

```bash
Z_HARNESS_CONSULT=off /z-plan "..."
```
