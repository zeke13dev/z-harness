# Decisions — C1 runtime-core

Run: 20260527T050549Z-harness-distribution-strategy

## Resolved (unilateral)

- C1-D1, json-schema-draft7, JSON Schema Draft 7 chosen for widest validator toolchain compat across Python/TS/Rust without requiring a 2020-12 capable validator; every schema file (.schema.json) is self-contained and version-stamped.
- C1-D2, provider-declares-auth-env, auth_env declared in provider.json schema (each provider entry names the env-var holding its API key); dispatcher reads it and injects into subprocess env before driver.init(); drivers receive a pre-resolved env dict and never re-read global env.
- C1-D3, python-abc-driver-interface, HostDriver is a Python ABC (abstract base class) in runtime/dispatch/driver.py; Python is the current harness scripting language; TypeScript driver tiers (C4 Cursor SDK) are out of C1 scope and will adapt to this ABC's documented method contract.
