# Providers Registry

> Last updated: 2026-07-09
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, skills/z-providers-discover/SKILL.md, docs/human/PROVIDERS.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh, .z-harness/providers.json

## Overview

The providers registry is the runtime dispatch layer for external LLM CLIs. It describes provider entries (command, arguments, stdin behavior, timeout, model label, optional model argument template, optional model environment variable, default model) and role bindings for consultant and reviewer agents. It does not choose personas or decide which command needs review; it only resolves a role to an executable invocation descriptor.

Resolution has three binding paths. If `Z_HARNESS_CONSULT=off` is set for `consultant_primary`, `consultant_secondary`, or `reviewer`, `scripts/resolve-provider.py` returns the plaintext sentinel `none` before loading provider config. Otherwise `[roles.<command>.<role>].runtime` then `[roles.default.<role>].runtime` from `config.toml` are the preferred external-provider override layers; legacy `[models.<role>]` provider selectors remain as a compatibility fallback; if all are absent, the legacy `providers.json.roles` map is used. Global and repo provider files merge per key, v1 registries are upgraded in memory to v2, aliases map old provider names to canonical names, and consultant-primary/secondary distinctness is enforced after alias canonicalization across TOML and legacy paths.

OMP provider entries (`omp-antigravity-pro`, `omp-codex`, `omp-cursor-terra`, `omp-cursor-sol`) are consult-provider compatibility, not native OMP host support. `omp-gemini` remains an alias for the Antigravity-backed Gemini 3.1 Pro provider, while direct `gemini-cli` remains available only as an explicitly named direct provider or as an explicit fallback command. OMP entries resolve through `scripts/omp-consult.sh`, which adapts the registry's stdin prompt contract to `omp -p --no-session --no-rules --model ... <prompt>`. Native OMP host dispatch must bypass this shim and use the `OmpHostDriver` contract instead.

As of the host-aware-model-tiers plan (T007), this repo's default role bindings are `consultant_primary = omp-antigravity-pro`, `consultant_secondary = omp-cursor-sol` (`cursor/gpt-5.6-sol-medium`), and `reviewer = omp-cursor-terra` (`cursor/gpt-5.6-terra-medium`) — both `gpt-5.6-*` models resolve only via the `cursor` omp provider, so `cursor` auth readiness gates those two roles (see `_auth_backend_for` → `"OMP OAuth / Cursor"` in `scripts/resolve-provider.py`).

## Key entry points

- `scripts/resolve-provider.sh:1` — thin wrapper used by reviewer and consultant agents.
- `scripts/resolve-provider.py:710` — `main()` — consult-off sentinel, config load/merge, TOML role-runtime override, legacy `[models]` fallback, legacy providers map fallback, JSON descriptor output.
- `scripts/resolve-provider.py:678` — `_resolve_role_runtime_override()` — reads `roles.<command>.<role>.runtime` and `roles.default.<role>.runtime` so external provider roles stay separate from native model classes.
- `scripts/resolve-provider.py:691` — `_resolve_models_override()` — compatibility path for older `models.<role>` provider selectors; validates provider availability and compose-argv preconditions.
- `scripts/resolve-provider.py:386` — `resolve()` — legacy role-to-provider lookup using `providers.json.roles`, aliases, PATH checks, and `compose_argv()`.
- `scripts/resolve-provider.py:227` — `merge_with_shadow()` — per-key merge of global and repo providers/roles/aliases; emits de-duplicated `provider_shadowed` telemetry.
- `scripts/resolve-provider.py:458` — `compose_argv()` — renders `{model}` in `model_arg_template`; legacy providers with null template return `args_template` unchanged.
- `scripts/discover-providers.py:58` — `discover()` — probes PATH for known CLIs and returns a proposed v1 registry; it never writes files.
- `skills/z-providers-discover/SKILL.md:1` — user-facing discovery command wrapper for generating provider suggestions.
- `runtime/compat.py:15` — Python runtime wrapper around `resolve-provider.py`.
- `runtime/contract/provider.schema.json:1` — Draft 7 schema for `.z-harness/providers.json`, accepting versions 1 and 2 and optional runtime-contract fields.
- `scripts/log-providers.sh:34` — handles the `none` sentinel before JSON parsing and emits provider-resolution summary telemetry.
- `.z-harness/providers.json:1` — repo-local v2 provider registry; this repo currently binds `consultant_primary` to `omp-antigravity-pro`, `consultant_secondary` to `omp-cursor-sol`, and `reviewer` to `omp-cursor-terra`, with `omp-gemini` as a compatibility alias for `omp-antigravity-pro`.
- `scripts/omp-consult.sh:1` — `omp-consult.sh` — Compatibility adapter for provider-registry consult calls; reads prompt from stdin, invokes `omp -p --no-session --no-rules --model <provider/model> <prompt>`, and optionally falls back to a native vendor CLI.

## How it interacts with others

- `config` — `[roles.<command>.<role>].runtime` / `[roles.default.<role>].runtime` are the preferred external provider binding overrides above legacy `[models.<role>]` and `providers.json.roles`.
- `reviewer-capture` — reviewer/consultant agents use provider resolution to decide whether Codex file-based capture applies.
- `personas-and-roles` — persona contract validation is separate from provider resolution; the provider registry supplies only the runtime axis.
- `subagent-telemetry` — provider dispatch agents log prompt/response sizes after the resolved CLI returns.
- `capabilities-matrix` — keeps OMP consult-provider compatibility separate from first-class OMP host fidelity. Consultant provider entries do not imply `OmpAdapter` support or `COMMAND_CAPABILITY_MATRIX["omp"]` native tiers.

## Edge cases / gotchas

- `Z_HARNESS_CONSULT=off` short-circuits config loading and consultant distinctness; consumers must handle `none` as a sentinel, not JSON.
- `_resolve_role_runtime_override()` enforces consultant-primary/secondary distinctness for TOML runtime bindings; `_resolve_models_override()` does the same for the legacy compatibility path.
- `model_arg_template` requires `default_model` for safe TOML overrides; otherwise override resolution refuses that provider.
- `.z-harness/providers.json` keeps direct CLI providers (`*-cli`) separate from OMP consult providers; aliases provide backward compatibility and telemetry (`omp-gemini` → `omp-antigravity-pro`, `gemini` → `gemini-cli`).
- The JSON schema permits some future runtime fields, but `resolve-provider.py` still resolves only CLI providers.
- `discover-providers.py` intentionally emits v1-style names; the resolver upgrades v1 registries in memory.
- Do not reuse `scripts/omp-consult.sh` for native OMP command dispatch. Its `--no-rules --no-session` flags are intentional for advisory consults inside this repo, where OMP would otherwise auto-load a large root `AGENTS.md`; native OMP uses explicit `.omp/z-harness/` discovery and session/rules/profile/model handling.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/providers-registry.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_No memories recorded yet._

## Examples

```toml
[roles.default.consultant_primary]
runtime = "omp-antigravity-pro"

[roles.default.consultant_secondary]
runtime = "omp-cursor-sol"

[roles.default.reviewer]
runtime = "omp-cursor-terra"
```

```bash
Z_HARNESS_CONSULT=off /z-plan "small local change"
# provider resolution returns: none
```
