---
artifact: plan
cluster_id: C1
cluster_name: runtime-core
root_slug: harness-distribution-strategy
run_id: 20260527T050549Z-harness-distribution-strategy
schema_version: 1
generated_at: 2026-05-27T05:05:49Z
---

# PLAN — C1: runtime-core

## Goal

C1 establishes the canonical foundation that the rest of the harness-distribution-strategy effort
builds on. The premise is sound: before any driver (C2-C4) can be written, there must be agreed
schemas for what a command is, what an agent is, what a provider entry looks like, and what
events look like on the wire. Concurrently, there must be a dispatcher core that C2-C4 drivers
plug into so they do not each re-implement subprocess launch, stream-json parsing, env hygiene,
and timeout/reap. This cluster produces exactly those artifacts — schemas in JSON Schema Draft 7
and a Python dispatch package — without touching host-specific code, command bodies, or the
existing adapter scripts that C6 will eventually freeze.

## Decisions

| ID    | Question                                   | Chosen option              | Rationale |
|-------|--------------------------------------------|---------------------------|-----------|
| C1-D1 | Schema language for wire contracts         | JSON Schema Draft 7        | Widest validator compat across Python/TS/Rust; no 2020-12 toolchain required; self-documenting. |
| C1-D2 | Where does auth_env resolution live?       | Declared in provider.json  | Keeps drivers stateless w.r.t. credential logic; dispatcher reads `auth_env` key and injects before spawning subprocess; no driver needs to know how to find a key. |
| C1-D3 | HostDriver interface language              | Python ABC                 | All existing harness scripts are Python; Python ABC gives IDE-checkable contracts without introducing a new language dependency; TypeScript driver tiers are C4 scope. |

## Non-goals (v1)

- No host driver implementations (C2, C3, C4).
- No command body changes or command-to-schema migration (C6).
- No install / update machinery (C6).
- No conformance test matrix (C5).
- No changes to `scripts/resolve-provider.py` or `scripts/log-event.sh`.
- No MCP server or client implementation.
- No session resumption implementation (session.py provides helper stubs only;
  full resumption is a post-v1 open question per RESEARCH.md).

## Approved shortcuts

- `runtime/compat.py` wraps the existing scripts via subprocess rather than
  refactoring them. This is intentional: it lets C2-C5 use runtime APIs
  immediately without waiting for C6 to complete the cutover.
- JSON Schema files are written by hand (not generated from Python types).
  This keeps the contract language-neutral and avoids a codegen dependency.
- `session.py` provides stub helpers (generate_session_id, assert_uuid_format)
  but does not implement full session resumption or state replay. That is
  deferred until the open question in RESEARCH.md is answered.

## Phases

### Phase A — Schema definitions (no code dependencies)

Write the five JSON Schema files under `runtime/contract/`. Each file is
self-contained. They can be reviewed and validated in isolation before any
Python code is written. Order: command → agent → provider → event → skill.

### Phase B — Dispatch package scaffold

Create `runtime/__init__.py`, `runtime/validate.py`, and the `runtime/dispatch/`
sub-package with `driver.py` (HostDriver ABC), `result.py` (DispatchResult),
`env.py` (env hygiene), and stubs for `dispatcher.py`, `timeout.py`,
`session.py`.

### Phase C — Dispatcher core implementation

Implement `dispatcher.py` (subprocess launch, stream-json parser, exit-code +
`is_error` discrimination) and `timeout.py` (timeout + reap). Instrument with
`dispatch_start` / `dispatch_end` events via `runtime/compat.py`.

### Phase D — Compat shim

Implement `runtime/compat.py`: thin wrappers around `scripts/resolve-provider.py`
and `scripts/log-event.sh` that let C2-C5 call runtime-style APIs while the
old scripts remain the canonical execution path.

### Phase E — Validation smoke test

Write a minimal pytest module (`runtime/tests/test_contract.py`) that:
- Validates the five schema files against JSON Schema meta-schema.
- Validates a sample command, agent, provider, event, and skill fixture against
  each schema.
- Verifies `HostDriver` cannot be instantiated directly.
- Verifies `env.py` strips CLAUDECODE and injects auth_env.
- Verifies `compat.py` round-trips a `resolve-provider.py` call without error.

## Risks

- **jsonschema lib version skew.** If the host Python environment has an old
  `jsonschema` (< 4.x), Draft 7 support may differ. Pin `jsonschema>=4.0` in
  runtime documentation; do not add it to any package manifest (that would
  trigger escalation rubric b).
- **CLAUDECODE="" override issue status.** RESEARCH.md cites
  `claude-agent-sdk-python#573` as open. `env.py` applies the override
  unconditionally; if Anthropic closes the issue by changing behavior, the
  override becomes a no-op rather than a break. Low risk.
- **provider.schema.json backward compat.** The existing `.z-harness/providers.json`
  uses `version: 1` and a flat `providers` map. The new schema must accept that
  shape. Adding required fields that the existing file lacks would break the
  compat invariant. Each new required field must have a default or be optional.
- **Session resumption stubs.** `session.py` stubs will mislead drivers if they
  call `resume_session()` and get a no-op silently. Stubs must raise
  `NotImplementedError` with a clear message, not return empty.

## DRY / KISS / SOLID applied

- **DRY**: `env.py` is the single place that knows about env hygiene. Drivers
  call `build_env(provider_config)` and get back a clean dict. No duplication
  across drivers.
- **KISS**: JSON Schema files over codegen or Python type annotations as the
  canonical schema. No build step required to validate a command against the
  schema.
- **SOLID (Liskov / Interface segregation)**: `HostDriver` ABC exposes exactly
  three methods (`init`, `dispatch`, `teardown`). C2-C4 implement all three.
  No method on the base class is optional except `teardown` (default no-op).
