# Providers Registry

> Last updated: 2026-06-24
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, skills/z-providers-discover/SKILL.md, docs/human/PROVIDERS.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh, .z-harness/providers.json

## Overview

The providers registry is the runtime dispatch layer for external LLM CLIs. It describes provider entries (command, arguments, stdin behavior, timeout, model label, optional model argument template, optional model environment variable, default model) and role bindings for consultant and reviewer agents. It does not choose personas or decide which command needs review; it only resolves a role to an executable invocation descriptor.

Resolution has two binding paths. If `Z_HARNESS_CONSULT=off` is set for `consultant_primary`, `consultant_secondary`, or `reviewer`, `scripts/resolve-provider.py` returns the plaintext sentinel `none` before loading config. Otherwise `[models.<role>]` from `scripts/config.py get` is the preferred override layer; if absent, the legacy `providers.json.roles` map is used. Global and repo provider files merge per key, v1 registries are upgraded in memory to v2, aliases map old provider names to canonical `-cli` names, and consultant-primary/secondary distinctness is enforced across both TOML and legacy paths.

OMP provider entries (`omp-gemini`, `omp-codex`) are consult-provider compatibility, not native OMP host support. They resolve through `scripts/omp-consult.sh`, which adapts the registry's stdin prompt contract to `omp -p --no-session --no-rules --model ... <prompt>` with native CLI fallback for advisory consultant roles. Native OMP host dispatch must bypass this shim and use the planned `OmpHostDriver` contract instead.

## Key entry points

- `scripts/resolve-provider.sh:1` — thin wrapper used by reviewer and consultant agents.
- `scripts/resolve-provider.py:634` — `main()` — consult-off sentinel, config load/merge, TOML override resolution, legacy fallback, JSON descriptor output.
- `scripts/resolve-provider.py:555` — `_resolve_models_override()` — reads `models.<role>`, validates provider availability and compose-argv preconditions, and enforces cross-path consultant distinctness.
- `scripts/resolve-provider.py:359` — `resolve()` — legacy role-to-provider lookup using `providers.json.roles`, aliases, PATH checks, and `compose_argv()`.
- `scripts/resolve-provider.py:227` — `merge_with_shadow()` — per-key merge of global and repo providers/roles/aliases; emits de-duplicated `provider_shadowed` telemetry.
- `scripts/resolve-provider.py:443` — `compose_argv()` — renders `{model}` in `model_arg_template`; legacy providers with null template return `args_template` unchanged.
- `scripts/discover-providers.py:58` — `discover()` — probes PATH for known CLIs and returns a proposed v1 registry; it never writes files.
- `skills/z-providers-discover/SKILL.md:1` — user-facing discovery command wrapper for generating provider suggestions.
- `runtime/compat.py:15` — Python runtime wrapper around `resolve-provider.py`.
- `runtime/contract/provider.schema.json:1` — Draft 7 schema for `.z-harness/providers.json`, accepting versions 1 and 2 and optional runtime-contract fields.
- `scripts/log-providers.sh:34` — handles the `none` sentinel before JSON parsing and emits provider-resolution summary telemetry.
- `.z-harness/providers.json:1` — repo-local v2 provider registry; this repo currently binds consultants to `omp-gemini`/`omp-codex` and reviewer to `codex-cli`.
- `scripts/omp-consult.sh:1` — `omp-consult.sh` — Compatibility adapter for provider-registry consult calls; reads prompt from stdin, invokes `omp -p --no-session --no-rules --model <provider/model> <prompt>`, and optionally falls back to a native vendor CLI.

## How it interacts with others

- `config` — `[models]`/`models.<role>` is the preferred binding override above legacy `providers.json.roles`.
- `reviewer-capture` — reviewer/consultant agents use provider resolution to decide whether Codex file-based capture applies.
- `personas-and-roles` — persona contract validation is separate from provider resolution; the provider registry supplies only the runtime axis.
- `subagent-telemetry` — provider dispatch agents log prompt/response sizes after the resolved CLI returns.
- `capabilities-matrix` — keeps OMP consult-provider compatibility separate from first-class OMP host fidelity. Consultant provider entries do not imply `OmpAdapter` support or `COMMAND_CAPABILITY_MATRIX["omp"]` native tiers.

## Edge cases / gotchas

- `Z_HARNESS_CONSULT=off` short-circuits config loading and consultant distinctness; consumers must handle `none` as a sentinel, not JSON.
- `_resolve_models_override()` enforces consultant-primary/secondary distinctness even when one side comes from TOML and the other from legacy `providers.json.roles`.
- `model_arg_template` requires `default_model` for safe TOML model overrides; otherwise override resolution refuses that provider.
- `.z-harness/providers.json` keeps old provider names and canonical `-cli` entries; aliases provide backward compatibility and telemetry.
- The JSON schema permits some future runtime fields, but `resolve-provider.py` still resolves only CLI providers.
- `discover-providers.py` intentionally emits v1-style names; the resolver upgrades v1 registries in memory.
- Do not reuse `scripts/omp-consult.sh` for native OMP command dispatch. Its `--no-rules --no-session` flags are intentional for advisory consults inside this repo, where OMP would otherwise auto-load a large root `AGENTS.md`; native OMP uses explicit `.omp/z-harness/` discovery and session/rules/profile/model handling.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/providers-registry.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```toml
[models]
consultant_primary = "omp-gemini"
consultant_secondary = "omp-codex"
reviewer = "codex-cli"
```

```bash
Z_HARNESS_CONSULT=off /z-plan "small local change"
# provider resolution returns: none
```
