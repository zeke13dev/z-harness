# PLAN — C2: driver-codex

## Goal

C2 replaces the ad-hoc Codex dispatch path in `scripts/resolve-provider.py` and `scripts/export-codex.py` with a structured HostDriver module at `runtime/drivers/codex/`. The driver owns subprocess invocation (`codex exec -` with `--output-format stream-json`), JSONL stream parsing, a three-step auth resolution chain, cross-env smoke testing, and one-time MCP registration. It satisfies C1's HostDriver interface and is validated by the C5 conformance harness. SDK-tier (openai direct) is deferred to v2. Schema ownership stays in C1 per decision C2-D1.

## Decisions

| ID | Question | Chosen option | Rationale |
|----|----------|---------------|-----------|
| C2-D1 | Who owns provider.schema.json fields for Codex-specific params? | c1-owns-schema | Single source of truth; C5 imports one schema; consistent with C1's planned provider.schema.json. C2 reads/validates only the fields it needs at runtime. (Resolved by orchestrator re-spawn.) |
| C2-D2 | How to handle OPENAI_API_KEY when CODEX_API_KEY is absent? | model_providers_workaround | Documented workaround for codex#5212; inject a custom model_providers stanza into ~/.codex/config.toml only when CODEX_API_KEY is absent and OPENAI_API_KEY is present. Auth step emits codex_auth_resolved with strategy. |
| C2-D3 | Auth resolution for ~/.codex/auth.json ChatGPT OAuth token? | read-only check, no injection | Read the file to confirm credential exists and surface AuthResolutionError if missing; do not attempt to inject the OAuth token into the subprocess env (it is a keyring secret, not an env-var). |
| C2-D4 | Session resumption: does codex exec accept a session-id flag? | probe-first, no assumption | The probe task (T004) runs `codex exec --help` and a dry-run to check for session flags before any session-resumption logic is written. If the flag does not exist, log and skip that feature. |

## Non-goals (v1)

- openai SDK direct import (SDK tier, v2 only)
- TUI / pty wrapping
- Body rewriting / limitation-comment substitution from the legacy exporter
- Schema field definitions (C1 owns provider.schema.json)
- Any driver other than Codex (C3, C4)
- Conformance harness itself (C5)
- Shipping / install (C6)

## Approved shortcuts

- None. The driver is the primary correctness surface for Codex; no quality shortcuts taken.

## Phases

### Phase A — Foundation (auth + subprocess skeleton)

Establish the package structure, implement auth resolution, and build a minimal subprocess invocation that can run `codex exec -` with a trivial prompt. Auth module must pass unit tests without requiring codex on PATH (mock subprocess).

Tasks: T001, T002

### Phase B — Stream parsing + error handling

Implement the JSONL stream parser for `--output-format stream-json`. Handle all abnormal exit paths: `is_error: true` frames, empty stdout hang, non-zero exit code, SIGSEGV. Add timeout/kill logic. Tests cover all abnormal paths via mocked subprocess output.

Tasks: T003

### Phase C — Probes

Run early probe tasks to determine: (a) whether `codex exec` accepts a session-id flag; (b) whether cross-vendor env-var collision (ANTHROPIC_API_KEY + OPENAI_API_KEY in parent env) causes any codex failure. Probe results are recorded in `runtime/drivers/codex/probe_results.json` and gate later features.

Tasks: T004

### Phase D — MCP registration helper

Implement the idempotent `codex mcp add` wrapper. Reads mcp_config_path from the provider config entry (field defined in C1's schema). Checks whether the server is already registered before invoking. Emits appropriate telemetry.

Tasks: T005

### Phase E — Integration + cleanup

Wire the driver into C1's HostDriver interface (depends on C1 defining that interface). Write integration tests that invoke the full driver against a real `codex exec -` subprocess (skipped if codex not on PATH). Validate telemetry events fire correctly.

Tasks: T006, T007

## Risks

- **Session resumption unknown**: codex exec session-id flag is unverified. If it does not exist, any caller that depends on session continuity will need a workaround. Probe task (T004) surfaces this early.
- **~/.codex/config.toml mutation**: the OPENAI_API_KEY model_providers workaround writes to user config. Must be idempotent and must not corrupt existing config. Needs a backup-and-restore pattern in tests.
- **Cross-env collision is subtle**: if the parent process has ANTHROPIC_API_KEY set, codex ignores it — but if it has OPENAI_API_KEY set and the user also has CODEX_API_KEY set, the precedence is ambiguous per codex#5212. Smoke test (T004) should capture the actual behavior.
- **JSONL format coupling**: `--output-format stream-json` frame schema is not versioned by OpenAI. If codex updates the frame schema, the parser breaks silently. Mitigation: use a lenient parser that surfaces unknown keys rather than crashing.
- **subprocess startup latency**: ~1-2s per invocation. This is a known constraint, not a bug. Document in driver docstring; callers should not assume sub-second response.

## DRY / KISS / SOLID applied

- **DRY**: auth resolution logic lives only in `auth.py`; nothing in `driver.py` re-implements credential lookup.
- **KISS**: stream.py is a line-by-line JSONL parser; no event-loop framework. The simplest thing that handles all documented frame types.
- **SOLID (single responsibility)**: auth, stream, mcp, and probe are separate modules; driver.py only orchestrates them. Each can be tested independently.
- **SOLID (dependency inversion)**: driver.py depends on the C1-defined HostDriver interface; it does not import C1 internals beyond that interface.
