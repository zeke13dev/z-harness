# Design Review: Layered TOML Config API for z-harness

## Mode
design-review

## Context: resolve-provider.py precedent

The repo already has a working layered config mechanism for providers:

**Location strategy:** global `~/.config/z-harness/providers.json` + repo `.z-harness/providers.json`, repo wins per-key.

**Public API:** single command `scripts/resolve-provider.py <role>` that:
  - Loads both configs, validates schema once
  - Merges per-key (repo shadows global)
  - Emits JSON to stdout, exit codes for errors/unbound
  - Logs `provider_shadowed` events when repo overrides global
  - Validates cross-entry invariants (consultant_primary ≠ consultant_secondary)

**Key design wins:**
  - No subcommands — one deterministic output format per call
  - Single path-resolution logic, called by consumers
  - Metadata (which file won, whether shadowed) available to observability
  - Version field prevents schema drift; validation tight and early

## Three flagged API decisions for new config.py

### D5 — Public API surface
**Tentative:** subcommands `get <dotted.key>`, `export-env --for <command>`, `ensure-defaults`, `explain <key>`. No `should-notify` subcommand.

**Parallel consult suggestion (Gemini):** drop export-env in favor of `get` + jq, skip `explain`, use only `get` for everything.

### D7 — docs.always_apply semantics
**Tentative:** tri-state enum `"always" | "smart" (default) | "never"`. Smart = current heuristic (light flows skip, heavy always dispatch).

**Parallel consult suggestion (Gemini):** use plain bool, not tri-state.

### D9 — notify.level API and gate
**Tentative:** enum `"off" | "approval_only" | "all"`. API: `config.py should-notify --event <kind>` exits 0/1. Commands wrap PushNotification with guard.

**Parallel consult suggestion (Gemini):** drop should-notify, use `get notify.level` + shell string compare.

## Ask

For EACH decision (D5, D7, D9):
1. **One concrete reason the tentative is wrong** — a real issue it creates.
2. **Your recommendation** — which design is better.
3. **What would change your mind** — evidence that would flip the pick.

Also: critique the Gemini alternatives (get+jq, bool, get+compare). Are they better or worse for THIS codebase given the providers.json precedent?

Be brief and concrete. Treat the three decisions as a system, not in isolation.
