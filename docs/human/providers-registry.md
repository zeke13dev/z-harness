# Providers Registry

> Last updated: 2026-06-03
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, commands/z-providers-discover.md, docs/human/PROVIDERS.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh, .z-harness/providers.json

## Overview

The providers registry is the mechanism z-harness uses to route consultant and reviewer dispatches to any CLI-addressable LLM. Providers are named CLI programs defined in a JSON configuration file; three fixed roles (`consultant_primary`, `consultant_secondary`, `reviewer`) map the logical dispatch slots to named provider entries. The resolver (`scripts/resolve-provider.py`) enforces schema validation, in-memory v1→v2 upgrade, alias substitution, and PATH checks before printing a JSON descriptor to stdout. A `compose_argv()` helper takes a resolved descriptor and an effective model string and builds the final argv list, handling `{model}` substitution in `model_arg_template`. The thin bash wrapper `scripts/resolve-provider.sh` is the single entrypoint for all dispatch sites.

As of schema v2, canonical provider names use a `-cli` suffix to distinguish the CLI runtime from the model family (`codex-cli`, `gemini-cli`, `claude-cli`, `cursor-cli`, `agy-cli`). The repo-local `.z-harness/providers.json` ships with both old names (e.g. `codex`) and new names (e.g. `codex-cli`) as first-class provider entries, plus a top-level `aliases` map for forward compatibility (`{"codex": "codex-cli", "gemini": "gemini-cli", "claude": "claude-cli", "cursor": "cursor-cli", "agy": "agy-cli"}`). Default `roles` entries in `providers.json` point to the new `-cli` names. However, `providers.json.roles` is now a **legacy fallback** — the preferred role binding mechanism is `[roles.<command>.<role>]` tables in `config.toml` (see [PERSONAS.md](PERSONAS.md#toml-binding)). When the `roles` map in `providers.json` is the active resolution path, a `legacy_provider_roles_used` event is emitted as a migration reminder. Two config scopes exist: a user-global file at `~/.config/z-harness/providers.json` and a repo-local file at `.z-harness/providers.json`; merge is per-key with repo winning across `providers`, `roles`, and `aliases` sections. Setting `Z_HARNESS_CONSULT=off` bypasses the entire resolution path and returns the plaintext sentinel `none` for all three roles before any config file is loaded.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/resolve-provider.sh:1` — `resolve-provider.sh` — thin bash wrapper; single entrypoint for all command/agent dispatch sites
- `scripts/resolve-provider.py:503` — `main()` — loads configs, merges, validates, checks PATH, enforces invariant, prints JSON descriptor or sentinel `none`
- `scripts/resolve-provider.py:498` — `_CONSULT_OFF_ROLES` — frozenset of roles that return sentinel `none` when `Z_HARNESS_CONSULT=off`: consultant_primary, consultant_secondary, reviewer
- `scripts/resolve-provider.py:170` — `load_configs()` — locates and loads global + repo JSON; validates schema version; runs v1→v2 upgrade
- `scripts/resolve-provider.py:64` — `_upgrade_v1_to_v2()` — in-memory upgrade of v1 registries to v2; adds null fields and emits `provider_schema_v1_upgraded` event (memoized per process per path)
- `scripts/resolve-provider.py:227` — `merge_with_shadow()` — per-key merge of global + repo configs across `providers`, `roles`, `aliases` with shadow detection and event emission
- `scripts/resolve-provider.py:359` — `resolve()` — role→provider→command lookup with alias substitution and PATH presence check; exits 1 if unresolvable
- `scripts/resolve-provider.py:331` — `_apply_aliases()` — checks if a provider name is an alias; substitutes canonical name and emits `provider_alias_used` (memoized); also emits `legacy_provider_roles_used` when `is_legacy=True`
- `scripts/resolve-provider.py:293` — `_emit_alias_used()` — emits `provider_alias_used` event via `log-event.sh` (best-effort, non-fatal; memoization guard lives in `_apply_aliases`)
- `scripts/resolve-provider.py:314` — `_emit_legacy_roles_used()` — emits `legacy_provider_roles_used` event when `providers.json.roles` is the active role binding path
- `scripts/resolve-provider.py:422` — `check_consultant_distinctness()` — invariant: `consultant_primary != consultant_secondary`; skipped when `Z_HARNESS_CONSULT=off`
- `scripts/resolve-provider.py:443` — `compose_argv()` — builds full argv from descriptor + effective model; renders `{model}` in `model_arg_template`; raises `ValueError` if no model can be resolved
- `scripts/resolve-provider.py:112` — `_validate_provider_entry()` — validates all required fields for a single provider entry; exits 2 on violation
- `scripts/discover-providers.py:58` — `discover()` — probes PATH for known CLIs; returns proposed `providers.json` dict as v1 (never writes)
- `scripts/log-providers.sh:34` — none-sentinel guard — detects `none` before JSON parse; emits `provider_resolution_skipped` event; appends `role=skipped(consult=off)` to summary
- `runtime/compat.py:15` — `resolve_provider()` — Python API wrapper around `resolve-provider.py` for runtime dispatch layer
- `runtime/contract/provider.schema.json:1` — `ProviderRegistry` — JSON Schema Draft 7 for `.z-harness/providers.json`; accepts version 1 and 2; permits `kind=cli|sdk`
<!-- AUTO-END: entry-points -->
## How it interacts with others

- `agents` — `consultant-primary.md`, `consultant-secondary.md`, and `reviewer.md` call `resolve-provider.sh` to determine which CLI to invoke; `self-reviewer.md` is used when `Z_HARNESS_CONSULT=off` replaces the reviewer role
- `commands` — every command that dispatches a consultant or reviewer calls `scripts/log-providers.sh` at startup, which invokes `resolve-provider.sh` per role
- `scripts` — `log-event.sh` is called by `resolve-provider.py` on shadow/upgrade/alias events and by `log-providers.sh` per resolved role
- `runtime-dispatch` — `runtime/compat.py:resolve_provider()` is the Python API consumed by the dispatch layer (`runtime/dispatch/dispatcher.py`)
- `personas-and-roles` — per-role TOML bindings under `[roles.<command>.<role>]` in `config.toml` are the preferred mechanism and take precedence over `providers.json.roles`; see PERSONAS.md for the full role-binding lifecycle

## Edge cases / gotchas

- `consultant_primary` and `consultant_secondary` must resolve to distinct provider names — the resolver exits with code 1 if they collide. This check compares the raw `roles` map values before alias substitution. The check is **skipped entirely** when `Z_HARNESS_CONSULT=off`.
- Schema version must be `1` or `2`; any other value (including `null` or a missing field) causes exit 2. Version 1 is upgraded in-memory to version 2 automatically; `provider_schema_v1_upgraded` is emitted once per (process, file path).
- The resolver validates every provider entry in the merged config on every call — not just the entry being resolved. A bad entry for an unrelated provider blocks all resolutions.
- Shadow de-duplication uses a stamp file keyed on `os.getppid()` so the warning fires only once per parent process tree, not once per subshell invocation.
- `discover-providers.py` outputs v1 format JSON (not v2). The v1 output is silently upgraded to v2 in-memory when loaded by the resolver. The script never writes any files — all writes go through `/z-providers-discover` which requires an explicit user confirmation step.
- The schema at `runtime/contract/provider.schema.json` permits `kind: "sdk"` and optional `auth_env`, `session_resumable`, and `allow_cross_vendor_env` fields, but `resolve-provider.py` validates only `kind: "cli"` — SDK entries pass schema validation but cause exit 2 if actually resolved.
- `compose_argv()` raises `ValueError` (not exit) when both `effective_model` and `provider_dict["default_model"]` are empty or null — callers must handle this exception. When `model_arg_template` is null (v1 legacy mode), `compose_argv()` returns `args_template` immediately without attempting model resolution.
- Setting `Z_HARNESS_REPO_PROVIDERS` to any path overrides the git-discovered repo config path entirely, which is useful in CI and test fixtures.
- The `aliases` section IS used by `resolve()` via `_apply_aliases` — it is not merely informational. The current aliases map covers five entries: `codex`, `gemini`, `claude`, `cursor`, and `agy` mapped to their respective `-cli` canonical names.
- The repo-local `.z-harness/providers.json` deliberately contains both old names and new `-cli` names as first-class provider entries. This dual-entry pattern ensures backward compatibility without deleting any site that has persisted old names in a user-global config.
- `providers.json.roles` is now a **legacy fallback**. The TOML `[roles.<command>.<role>]` binding always takes precedence when both exist. Using the `roles` map in `providers.json` emits `legacy_provider_roles_used`. Note that `resolve()` unconditionally passes `is_legacy=True` when resolving from the `roles` section in providers.json, so this event fires for every role lookup that comes through providers.json.roles regardless of whether an alias is also involved.
- `_alias_used_emitted` is a module-level set; alias dedup survives multiple `resolve()` calls within the same process but resets on new process invocations.
- `Z_HARNESS_CONSULT=off` bypasses config loading and the distinctness check entirely — setting it is sufficient; no providers.json change needed. The sentinel `none` is a plaintext string, not JSON; consumers must check for it before attempting JSON parsing.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/providers-registry.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded yet._

## Examples

- Minimal invocation: `bash scripts/resolve-provider.sh consultant_primary` — prints JSON descriptor to stdout.
- Consult-off mode: `Z_HARNESS_CONSULT=off bash scripts/resolve-provider.sh reviewer` — prints `none` and exits 0.
- Discovery: `python3 scripts/discover-providers.py` — prints proposed `providers.json` (v1 format) based on current PATH.
- Argv composition: `compose_argv(descriptor, "claude-opus-4-7")` — returns `args_template` extended with rendered `model_arg_template`.
- Runtime Python: `from runtime.compat import resolve_provider; d = resolve_provider("reviewer", "/path/to/repo")`
- Old-name alias: binding `roles.consultant_primary = "gemini"` in `providers.json` is silently resolved to `gemini-cli` via the `aliases` map; `provider_alias_used` and `legacy_provider_roles_used` events are both emitted.
- Cursor provider: `cursor-cli` entry uses `model_arg_template: ["--model", "{model}"]` and `default_model: "auto"` — one of the few shipped providers with model arg injection enabled.
