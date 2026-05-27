# Phase 1 — Context

## Doc-fetcher synthesis (key facts)

### Existing providers.json loader (the precedent to mimic)
- `scripts/resolve-provider.py` lines 96–289 + thin `resolve-provider.sh` wrapper (lines 1–4).
- Layer order: built-in / role registry → `$XDG_CONFIG_HOME/z-harness/providers.json` (global) → `$Z_HARNESS_REPO_PROVIDERS` env override or `<repo>/.z-harness/providers.json` (repo-local, detected via `git rev-parse --show-toplevel` with cwd fallback).
- Repo wins **per-key** over global (not whole-file).
- Per-key shadows emit a `provider_shadowed` event (`log-event.sh`) + stderr warning, de-duped via PPID-keyed temp stamp.
- Schema validates `version: 1`; non-matching exits 2.
- CLI presence check via `shutil.which` is **late-stage** (only on dispatch, not at config load).

### Z_HARNESS_NOTIFY current state
- **Documented but never read.** `grep -r "Z_HARNESS_NOTIFY" scripts/ skills/ commands/` returns empty.
- Mentioned in README.md, skill docs, and command docs as future behavior; not implemented.
- **Implication:** Migrating `Z_HARNESS_NOTIFY → notify.level` is also the first implementation of the gate. The slice 1 work includes a `PushNotification` suppression wrapper (small — one helper script or a python config.py subcommand `should-notify`).

### Shared shell prelude
- **None.** Each command/skill sources scripts piecemeal with absolute paths via `$ANTIGRAVITY_PLUGIN_ROOT` / `$CLAUDE_PLUGIN_ROOT`.
- Common pattern in every command: version.sh → log-event.sh → mkdir dirs.
- Loader integration point: add a `config.py export-env --for <command>` line near the existing version.sh / log-event.sh lines in any migrated command. No shared prelude to refactor.

### Event emission shape
- `scripts/log-event.sh` lines 30–105 — accepts kind + JSON payload, validates JSON (else wraps as `{"raw": ...}`), appends to per-run `events.jsonl` + repo-wide `metrics.jsonl` via `flock`.
- No schema validation on event kinds — kind/payload contracts are by convention.

## Key files for SPEC
- `scripts/resolve-provider.py:96-289` — pattern to copy for layering + shadow events.
- `scripts/resolve-provider.sh:1-4` — thin wrapper pattern.
- `scripts/log-event.sh:30-105` — event emission API.
- `scripts/version.sh:1-40` — invoked at command setup; emits JSON.
- `commands/z-plan.md`, `commands/z-brainstorm.md`, `commands/z-implement-all.md` — reference Z_HARNESS_NOTIFY in docs only.
- `README.md` — slim target.
- `docs/llm/INDEX.json` — wire `config-design` concept here.

## Open questions for decisions doc
1. TOML parser dependency — Python 3.11+ ships `tomllib`; what's our minimum supported Python? (impacts whether we need a `tomli` fallback)
2. Defaults source-of-truth location — module constant in `scripts/config.py`, or separate `scripts/config_defaults.toml` shipped in the plugin?
3. `ensure-defaults` write target — user-global only (per BRAINSTORM "auto-write only to user-global"), or also offer `--init-repo` to seed repo-local?
4. Event de-dup — copy providers.json PPID-keyed temp stamp pattern, or just emit `config_resolved` once per command run?
5. How do migrated commands check `notify.level`? `config.py should-notify` subcommand returning exit 0/1, or `export-env` setting `Z_HARNESS_NOTIFY_LEVEL` for shell test?
6. `docs.always_apply` semantics — does `true` force doc-fetcher even when a command currently skips it (e.g. /z-do), or just remove the skip option from light flows?
