# Late-resolved decisions — driver-codex (C2)

## C2-D1 — Provider schema ownership
Resolved by user: **c1-owns-schema**. C1 (runtime-core) defines the canonical HostDriver provider entry shape, including any Codex-specific fields (auth_strategy, mcp_config_path, session_timeout_s). C2 reads and validates only the fields it needs at runtime. Rationale: single source of truth, simpler conformance import (C5 imports one schema), consistent with C1's design that already plans the canonical provider.schema.json.
