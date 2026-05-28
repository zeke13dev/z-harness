# Providers Registry

> Last updated: 2026-05-28
> Covers source: scripts/resolve-provider.py, scripts/resolve-provider.sh, scripts/discover-providers.py, commands/z-providers-discover.md, docs/human/PROVIDERS.md

## Overview

The providers registry is the mechanism z-harness uses to route consultant and reviewer dispatches to any CLI-addressable (or SDK-addressable) LLM. Providers are named CLI programs defined in a JSON configuration file; roles (`consultant_primary`, `consultant_secondary`, `reviewer`) map the three logical dispatch slots to named provider entries. The resolver enforces schema validation and PATH checks before returning a descriptor that commands use to invoke the provider.

Two config scopes exist: a user-global file at `~/.config/z-harness/providers.json` (or `$XDG_CONFIG_HOME/z-harness/providers.json`) and a repo-local file at `.z-harness/providers.json`. Merge is per-key with repo winning; any key that shadows a global entry emits a `provider_shadowed` stderr warning and JSONL event. A formal JSON Schema at `runtime/contract/provider.schema.json` (schema version 1) now backs all validation, and `runtime/compat.py` exposes `resolve_provider()` as a Python API for the runtime dispatch layer.

## Key entry points

- `scripts/resolve-provider.sh:1` — `resolve-provider.sh` — thin bash wrapper; single entrypoint for all command/agent dispatch sites
- `scripts/resolve-provider.py:262` — `main()` — loads configs, merges, validates, checks PATH, enforces consultant invariant, prints JSON descriptor
- `scripts/resolve-provider.py:96` — `load_configs()` — locates and loads global + repo JSON, validates schema version
- `scripts/resolve-provider.py:131` — `merge_with_shadow()` — per-key merge with shadow detection and event emission
- `scripts/resolve-provider.py:193` — `resolve()` — role→provider→command lookup with PATH check
- `scripts/resolve-provider.py:242` — `check_consultant_distinctness()` — invariant: `consultant_primary ≠ consultant_secondary`
- `scripts/discover-providers.py:58` — `discover()` — probes PATH for known CLIs, returns proposed `providers.json` (never writes)
- `scripts/log-providers.sh:1` — `log-providers.sh` — resolves all three roles, prints summary line, emits `provider_resolved` events
- `runtime/compat.py:15` — `resolve_provider()` — Python wrapper around `resolve-provider.py` for use by runtime dispatch
- `runtime/contract/provider.schema.json:1` — `ProviderRegistry` schema — JSON Schema Draft 7 for `.z-harness/providers.json`
- `commands/z-providers-discover.md:1` — `/z-providers-discover` — interactive slash command: probe → propose → bind roles → atomic write

## How it interacts with others

- `agents` — `consultant-primary.md`, `consultant-secondary.md`, and `reviewer.md` agent definitions call `resolve-provider.sh` to determine which CLI to invoke; role binding flows from this registry
- `commands` — every command that dispatches a consultant or reviewer calls `scripts/log-providers.sh` at startup, which invokes `resolve-provider.sh` per role
- `scripts` — `log-event.sh` is called by `resolve-provider.py` on shadow events and by `log-providers.sh` per resolved role
- `runtime/dispatch` — `runtime/compat.py:resolve_provider()` is the Python API surface consumed by the dispatch layer; `runtime/tests/test_compat_providers.py` validates the live `.z-harness/providers.json` against the schema

## Edge cases / gotchas

- `consultant_primary` and `consultant_secondary` must resolve to distinct provider names — the resolver exits with code 1 if they collide. This check runs at resolution time, not at write time.
- Schema version must equal exactly `1`; the resolver exits with code 2 on any other value, including `null` or a missing field.
- The resolver validates every provider entry in the merged config on every call — not just the entry being resolved. A bad entry for an unrelated provider will block all resolutions.
- Shadow de-duplication uses a stamp file keyed on `os.getppid()` so the warning fires only once per parent process tree, not once per subshell invocation.
- `discover-providers.py` never writes any files — it only prints a proposed JSON. All writes go through `/z-providers-discover` which requires an explicit user confirmation step.
- The schema at `runtime/contract/provider.schema.json` now permits `kind: "sdk"` and optional `auth_env` / `session_resumable` fields, but `resolve-provider.py` currently validates only `kind: "cli"`. SDK entries pass schema validation but will cause the Python resolver to exit 2 if resolved directly.
- Setting `Z_HARNESS_REPO_PROVIDERS` to any path overrides the auto-discovered repo config path, which is useful in CI and test fixtures.

## Examples

- Minimal invocation: `bash scripts/resolve-provider.sh consultant_primary` — prints JSON descriptor to stdout.
- Discovery: `python3 scripts/discover-providers.py` — prints proposed `providers.json` based on current PATH.
- Runtime Python: `from runtime.compat import resolve_provider; d = resolve_provider("reviewer", "/path/to/repo")`
