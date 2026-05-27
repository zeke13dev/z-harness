# SPEC — C2: driver-codex

## Overview

This cluster implements the CLI-tier HostDriver for Codex CLI within the host-neutral z-harness runtime. It owns `runtime/drivers/codex/`, which replaces the Codex dispatch path currently spread across `scripts/resolve-provider.py` and `scripts/export-codex.py`. The driver invokes `codex exec -` with `--output-format stream-json`, parses JSONL from stdout, resolves auth via a three-step env-var precedence chain, and exposes a clean driver interface that the C1 dispatcher calls. An optional SDK tier (direct `openai` SDK import) is deferred to v2 and is explicitly out of scope here.

## Surface

Files owned by this cluster:

- `runtime/drivers/codex/__init__.py` — package marker
- `runtime/drivers/codex/driver.py` — main HostDriver implementation (subprocess invocation, stream parsing, error handling)
- `runtime/drivers/codex/auth.py` — auth resolution: CODEX_API_KEY → OPENAI_API_KEY via model_providers → ~/.codex/auth.json keyring check
- `runtime/drivers/codex/stream.py` — stream-json JSONL parser (frame-by-frame, handles `is_error` field, handles hang/SIGSEGV recovery)
- `runtime/drivers/codex/mcp.py` — MCP registration helper (wraps `codex mcp add`)
- `runtime/drivers/codex/probe.py` — early probe tasks: session-resumption flag detection, cross-env collision smoke test
- `tests/drivers/test_codex_driver.py` — unit tests for driver, auth, and stream modules
- `tests/drivers/test_codex_probe.py` — integration probe smoke tests (skipped if codex not on PATH)

Schema ownership: provider.schema.json lives in C1 (`runtime/contract/provider.schema.json`). This driver reads and validates only the Codex-relevant fields at runtime; it does NOT define its own schema file.

## Non-goals

- Schema definition: all field DEFINITIONS (auth_strategy, mcp_config_path, session_timeout_s, and all other Codex-specific fields) live in C1's `runtime/contract/provider.schema.json`. C2 reads but does not own schema.
- Runtime contract (dispatcher, HostDriver interface, provider.schema.json): that is C1.
- Other host drivers (Antigravity, Claude-Cursor): C3 and C4.
- Conformance harness: C5.
- Shipping / install: C6.
- SDK tier (openai SDK direct import bypassing codex CLI): deferred to v2.
- TUI/pty wrapping: never needed; codex exec - is machine-readable.
- Body rewriting (Agent/Skill comment substitution from export-codex.py): that legacy logic is NOT carried forward into the new driver.

## Invariants

1. The driver MUST NOT write any file outside `runtime/drivers/codex/` and `tests/drivers/test_codex_*.py` during normal operation.
2. Auth resolution MUST follow the documented precedence (CODEX_API_KEY → OPENAI_API_KEY workaround → ~/.codex/auth.json) and MUST surface a clear AuthResolutionError if no path yields a usable credential.
3. Stream parsing MUST handle: normal completion, `is_error: true` frames, empty stdout (hang), and non-zero exit codes (SIGSEGV, crash). Every abnormal path raises a typed exception; nothing is silently swallowed.
4. The driver MUST NOT pass ANTHROPIC_API_KEY or CLAUDE_API_KEY into the codex subprocess env unless explicitly instructed by the provider config. Cross-vendor env-var pollution is a correctness invariant.
5. MCP registration via `codex mcp add` is a one-time user-config operation; the driver MUST NOT re-register on every invocation. Registration is idempotent (check-then-skip).
6. The subprocess MUST be killed and reaped if it exceeds session_timeout_s. No zombie processes.
7. All tests that require codex on PATH MUST be decorated with a skip guard so CI without codex installed passes cleanly.

## Telemetry / events

The driver emits the following events via the standard z-harness log-event mechanism (same sink as existing `scripts/log-phase.sh`):

- `codex_driver_invoke` — fired on each subprocess launch (fields: provider_name, auth_strategy, model_label)
- `codex_driver_complete` — fired on clean completion (fields: exit_code, frames_parsed, elapsed_ms)
- `codex_driver_error` — fired on any error path (fields: error_kind, exit_code, elapsed_ms)
- `codex_auth_resolved` — fired once per auth resolution (fields: strategy_used: "codex_api_key"|"openai_api_key_workaround"|"auth_json")
- `codex_env_collision_detected` — fired if cross-vendor env-var smoke test detects ANTHROPIC_API_KEY present alongside OPENAI_API_KEY (informational, not fatal)
