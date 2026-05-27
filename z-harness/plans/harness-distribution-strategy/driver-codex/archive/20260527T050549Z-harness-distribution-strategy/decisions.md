# Decisions log — C2 driver-codex
# run-id: 20260527T050549Z-harness-distribution-strategy

## Escalated (pending resolution)

- C2-D1, providers-entry-shape, ESCALATED — What fields does a providers.json/providers.toml entry for Codex CLI contain, and who validates them? C1 (runtime-core) owns the canonical provider schema; C2 cannot define or extend it unilaterally without a cross-cluster scope leak. Decision returned to main thread for resolution.

## Resolved late (re-spawn)

- C2-D1, c1-owns-schema, Single source of truth; C5 imports one schema; consistent with C1's planned provider.schema.json. C2 reads/validates only fields it needs at runtime; all field DEFINITIONS (including Codex-specific ones like auth_strategy / mcp_config_path / session_timeout_s) live in C1's runtime/contract/provider.schema.json.
