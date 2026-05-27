# Decisions — C4 (driver-claude-cursor)
# run-id: 20260527T050549Z-harness-distribution-strategy

## Resolved unilaterally

- C4-D1, dual-mode (SelfHostDriver + SubprocessClaudeDriver), SelfHostDriver for in-process/plugin case; SubprocessClaudeDriver for cross-host spawning case — both are needed and not mutually exclusive; separating them keeps each simple
- C4-D2, env-detect with --driver override, auto-detect CLAUDECODE env var to select SelfHostDriver; explicit --driver flag overrides — minimal friction for the common case; escape hatch for edge cases
- C4-D3, CLI-only in v1 for Cursor, cursor-agent -p CLI tier ships in v1; @cursor/sdk SDK tier stubbed with NotImplementedError + TODO; REST API is v2 non-goal — SDK is public beta (2026-04-29), adding a beta TypeScript SDK dependency escalates per rubric rule (b); CLI tier is sufficient for v1 conformance tests
- C4-D4, namespaced MCP key "z-harness" + runtime assertion, use "z-harness" as the MCP config key name; add runtime assertion that verifies the key name at registration time; document in SPEC that renaming breaks CVE-2025-54136 mitigation — the trust anchor is the key name, not the command; a stable, distinctive name is the only mitigation available without vendor patch
