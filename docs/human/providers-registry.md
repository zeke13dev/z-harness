# Providers Registry

> Last updated: 2026-05-28
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, commands/z-providers-discover.md, docs/human/PROVIDERS.md, runtime/compat.py, runtime/contract/provider.schema.json, scripts/log-providers.sh

## Overview

The providers registry is the mechanism z-harness uses to route consultant and reviewer dispatches to any CLI-addressable LLM. Providers are named CLI programs defined in a JSON configuration file; roles (`consultant_primary`, `consultant_secondary`, `reviewer`) map the three logical dispatch slots to named provider entries. The resolver enforces schema validation, in-memory v1→v2 upgrade, and PATH checks before returning a descriptor that commands use to invoke the provider. A `compose_argv()` helper takes a resolved descriptor and an effective model string and builds the final argv list, handling `{model}` substitution in `model_arg_template`.

Two config scopes exist: a user-global file at `~/.config/z-harness/providers.json` (or `$XDG_CONFIG_HOME/z-harness/providers.json`) and a repo-local file at `.z-harness/providers.json`. Merge is per-key with repo winning across `providers`, `roles`, and `aliases` sections; any key that shadows a global entry emits a `provider_shadowed` stderr warning and JSONL event. Schema version 1 configs are automatically upgraded in-memory to version 2 (which adds `model_arg_template`, `model_env_var`, `default_model`, and `aliases` support) without touching the file on disk. A JSON Schema at `runtime/contract/provider.schema.json` formally defines the format, and `runtime/compat.py` exposes `resolve_provider()` as the Python API for the runtime dispatch layer.

## Key entry points

- `scripts/resolve-provider.sh:1` — `resolve-provider.sh` — thin bash wrapper; single entrypoint for all command/agent dispatch sites
- `scripts/resolve-provider.py:412` — `main()` — loads configs, merges, validates, checks PATH, enforces consultant invariant, prints JSON descriptor
- `scripts/resolve-provider.py:165` — `load_configs()` — locates and loads global + repo JSON; validates schema version; runs v1→v2 upgrade
- `scripts/resolve-provider.py:59` — `_upgrade_v1_to_v2()` — in-memory upgrade of v1 registries to v2; adds null fields and emits `provider_schema_v1_upgraded` event (memoized per process per path)
- `scripts/resolve-provider.py:222` — `merge_with_shadow()` — per-key merge of global + repo configs across `providers`, `roles`, `aliases` with shadow detection and event emission
- `scripts/resolve-provider.py:288` — `resolve()` — role→provider→command lookup with PATH presence check
- `scripts/resolve-provider.py:340` — `check_consultant_distinctness()` — invariant: `consultant_primary != consultant_secondary`
- `scripts/resolve-provider.py:361` — `compose_argv()` — builds full argv from descriptor + effective model; renders `{model}` in `model_arg_template`; raises `ValueError` if no model can be resolved
- `scripts/discover-providers.py:58` — `discover()` — probes PATH for known CLIs; returns proposed `providers.json` dict (never writes)
- `scripts/log-providers.sh:1` — `log-providers.sh` — resolves all three roles, prints summary line, emits `provider_resolved` events
- `runtime/compat.py:15` — `resolve_provider()` — Python API wrapper around `resolve-provider.py` for runtime dispatch layer
- `runtime/contract/provider.schema.json:1` — `ProviderRegistry` — JSON Schema Draft 7 for `.z-harness/providers.json`; accepts version 1 and 2; permits `kind=cli|sdk`

## How it interacts with others

- `agents` — `consultant-primary.md`, `consultant-secondary.md`, and `reviewer.md` call `resolve-provider.sh` to determine which CLI to invoke; role binding flows from this registry
- `commands` — every command that dispatches a consultant or reviewer calls `scripts/log-providers.sh` at startup, which invokes `resolve-provider.sh` per role
- `scripts` — `log-event.sh` is called by `resolve-provider.py` on shadow/upgrade events and by `log-providers.sh` per resolved role
- `runtime/dispatch` — `runtime/compat.py:resolve_provider()` is the Python API consumed by the dispatch layer; `runtime/tests/test_compat_providers.py` validates live configs against the schema

## Edge cases / gotchas

- `consultant_primary` and `consultant_secondary` must resolve to distinct provider names — the resolver exits with code 1 if they collide. This check runs at resolution time, not at write time.
- Schema version must be `1` or `2`; any other value (including `null` or a missing field) causes exit 2. Version 1 is upgraded in-memory to version 2 automatically; `provider_schema_v1_upgraded` is emitted once per (process, file path).
- The resolver validates every provider entry in the merged config on every call — not just the entry being resolved. A bad entry for an unrelated provider blocks all resolutions.
- Shadow de-duplication uses a stamp file keyed on `os.getppid()` so the warning fires only once per parent process tree, not once per subshell invocation.
- `discover-providers.py` never writes any files — it only prints a proposed JSON. All writes go through `/z-providers-discover` which requires an explicit user confirmation step.
- The schema at `runtime/contract/provider.schema.json` permits `kind: "sdk"` and optional `auth_env`, `session_resumable`, and `allow_cross_vendor_env` fields, but `resolve-provider.py` validates only `kind: "cli"` — SDK entries pass schema validation but cause exit 2 if actually resolved.
- `compose_argv()` raises `ValueError` (not exit) when both `effective_model` and `provider_dict["default_model"]` are empty or null — callers must handle this exception.
- Setting `Z_HARNESS_REPO_PROVIDERS` to any path overrides the git-discovered repo config path entirely, which is useful in CI and test fixtures.
- The `aliases` section (v2 only) is merged per-key like `providers` and `roles`, but is not used by `resolve()` itself — it is informational for tooling that performs provider renames.

## Examples

- Minimal invocation: `bash scripts/resolve-provider.sh consultant_primary` — prints JSON descriptor to stdout.
- Discovery: `python3 scripts/discover-providers.py` — prints proposed `providers.json` based on current PATH.
- Argv composition: `compose_argv(descriptor, "claude-opus-4-7")` — returns `args_template` extended with rendered `model_arg_template`.
- Runtime Python: `from runtime.compat import resolve_provider; d = resolve_provider("reviewer", "/path/to/repo")`
