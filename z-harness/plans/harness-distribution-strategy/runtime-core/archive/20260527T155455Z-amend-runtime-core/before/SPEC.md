---
artifact: spec
cluster_id: C1
cluster_name: runtime-core
root_slug: harness-distribution-strategy
run_id: 20260527T050549Z-harness-distribution-strategy
schema_version: 1
generated_at: 2026-05-27T05:05:49Z
---

# SPEC — C1: runtime-core

## Overview

The runtime-core cluster defines the canonical wire-level contracts that every
z-harness driver, command, and event speaks, and implements the in-process
dispatcher that consumes those contracts. It owns the `runtime/` source tree
(two sub-trees: `runtime/contract/` for schema definitions and
`runtime/dispatch/` for the dispatcher + driver interface). No host-specific
code lives here. No user-facing command body lives here. No install or
distribution logic lives here. When any downstream cluster (C2-C6) needs to
dispatch a command, validate an event, or resolve a provider, it imports from
`runtime/`.

## Surface — files this cluster owns

```
runtime/
  contract/
    command.schema.json        # command wire schema (kebab-id, frontmatter, body)
    agent.schema.json          # agent wire schema (name, model, tools, triggers)
    provider.schema.json       # provider schema (extends .z-harness/providers.json shape)
    event.schema.json          # event JSONL schema (versioned, schema_version field)
    skill.schema.json          # skill wire schema
  dispatch/
    __init__.py
    driver.py                  # HostDriver ABC
    dispatcher.py              # subprocess driver primitives + stream-json parser
    env.py                     # env hygiene: CLAUDECODE="" override, auth_env injection
    result.py                  # DispatchResult dataclass
    timeout.py                 # timeout + reap policy
    session.py                 # optional session-id resumption helpers
  __init__.py
  validate.py                  # JSON Schema validator wrapper (jsonschema lib)
  compat.py                    # shim: today's resolve-provider.py + log-event.sh bridge
```

The existing scripts `scripts/resolve-provider.py` and `scripts/log-event.sh`
are NOT modified. `runtime/compat.py` wraps them so C2-C5 drivers can call
runtime APIs without the shim layer being visible.

## Non-goals

- No host-specific driver code. C2 owns `runtime/drivers/codex/`, C3 owns
  `runtime/drivers/antigravity/`, C4 owns `runtime/drivers/claude_cursor/`.
  The `HostDriver` ABC defined here is the only driver artifact in C1 scope.
- No user-facing command `.md` files. Those remain in `commands/`. The command
  schema validates them; it does not replace them.
- No install, distribution, or update logic. That is C6 scope.
- No conformance test suite. That is C5 scope.
- No migration of existing commands to new schema. That is C6 scope.
- No changes to `scripts/resolve-provider.py` or `scripts/log-event.sh`.

## Invariants

1. Every schema file is valid JSON Schema Draft 7 and contains a
   `"$schema": "http://json-schema.org/draft-07/schema#"` declaration plus a
   top-level `"schema_version"` field (integer, starting at 1).
2. Every event emitted via the dispatcher carries `schema_version: 1` and all
   fields required by `event.schema.json`.
3. `HostDriver.dispatch()` never inherits the caller's full environment
   unmodified. `env.py` always applies: (a) `CLAUDECODE=""` override,
   (b) provider `auth_env` injection, (c) strip of any variables in
   `ENV_STRIP_LIST` (to be defined; initially empty).
4. `provider.schema.json` is backward-compatible with the shape of the
   existing `.z-harness/providers.json` (version 1). No migration of existing
   config files is required by C1.
5. `runtime/compat.py` must keep `scripts/resolve-provider.py` and
   `scripts/log-event.sh` working unchanged. If compat.py imports either
   script, it does so via subprocess (not import hacks), preserving their
   independent execution path.
6. The `runtime/` package carries no new mandatory external dependencies beyond
   the Python standard library and `jsonschema`. Adding any other dependency is
   an escalatable decision (rubric trigger b).

## Telemetry / events

C1 does not own the run-level telemetry events (`run_start`, `run_end`). It
owns:

- `dispatch_start` / `dispatch_end` — bracketing events emitted by
  `dispatcher.py` on every `HostDriver.dispatch()` call. Payload fields:
  `driver`, `command_id`, `session_id` (nullable), `wall_ms` (end only),
  `exit_code` (end only), `is_error` (end only).
- `schema_validation_error` — emitted by `validate.py` when a schema check
  fails at runtime (not just at CI time). Payload: `schema`, `path`,
  `message`.

All events are appended to the run's `events.jsonl` via the existing
`log-event.sh` path (via `runtime/compat.py`).
