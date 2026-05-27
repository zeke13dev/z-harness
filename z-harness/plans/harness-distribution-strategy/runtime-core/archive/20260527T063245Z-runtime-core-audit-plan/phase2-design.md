# Phase 2 — Design & Best-Practices Audit (C1 runtime-core)

## SOLID / DRY / KISS findings

### F2.1 (MAJOR) — Dispatcher.run() signature contradicts HostDriver.dispatch()
- **T007** declares `HostDriver.dispatch(command_id, args, env) -> DispatchResult`. The driver returns a *final* `DispatchResult`.
- **T012** says `Dispatcher.run()` calls `driver.dispatch()` AND parses stream-json from "the driver's stdout" line-by-line AND applies `TimeoutReaper` around the call.
- These are mutually incompatible: if `dispatch()` returns the final `DispatchResult`, the dispatcher never sees a stream — only the finished result. Conversely, if the dispatcher parses a live stream, then `dispatch()` cannot return the final `DispatchResult` directly; it must yield or hand back an iterable / subprocess handle.
- **Root cause:** unclear ownership of subprocess lifecycle. Either (a) the driver owns the subprocess and yields events (then `dispatch` returns an iterator + has separate `wait_result` method), (b) the driver only *configures* the subprocess (returns argv + env) and the dispatcher does the launching/parsing (then `dispatch` is the wrong name), or (c) the driver returns both a stream-handle AND a final result via a richer return type.
- **SOLID-SRP impact:** mixing parsing into the dispatcher couples it to one specific output format (stream-json) — when Cursor SDK driver later returns events via its own SDK generator, the dispatcher's stream-json parser will be wrong. The parser belongs in the *driver*.

### F2.2 (MAJOR) — `HostDriver.init(provider_config: dict)` doesn't accommodate SelfHostDriver
- SHARED-CONCERNS.md item A4 already flags this: C4's SelfHostDriver needs a "tool-call injection point" so in-process primitives (Read/Edit/Bash/Agent) can be bound at init time.
- T007 acceptance only allows `init(provider_config: dict)`. SelfHostDriver would have no way to receive the in-process tool registry.
- Either (a) `init` takes a richer context object that drivers ignore fields they don't need, (b) C1 introduces a `SelfHostDriver` subclass with an extended init, or (c) drivers can override init with additional kwargs (Python liberty, but breaks Liskov substitution at the call-site type-checker level).
- C4's plan resolved this with its own `SelfHostDriver` class but didn't propose how the BASE class accommodates it — this gap surfaces at C4-T002 if not fixed in C1 first.

### F2.3 (MINOR) — `ENV_STRIP_LIST` is a defined-but-empty hook
- SPEC invariant #3: env.py applies "(c) strip of any variables in `ENV_STRIP_LIST` (to be defined; initially empty)."
- An empty list is YAGNI — the slot is defined for future use but unused. Either give it a real initial value (e.g. strip `ANTHROPIC_API_KEY` when calling a Codex driver to prevent cross-vendor confusion) or drop the empty list and add it when a real need surfaces.

### F2.4 (MINOR) — `session.py` is mostly dead code in v1
- T011 implements `generate_session_id` (UUID4), `assert_uuid_format`, and `resume_session` (raises NotImplementedError).
- T012 acceptance does NOT call any of these. No driver in C2/C3/C4 has `session_resumable: true` in v1 either (per RESEARCH.md, session resumption is an open question).
- The file exists, has tests (T015 asserts the NotImplementedError), but is not called by anything else in v1.
- Either (a) defer session.py entirely to v2 (drop T011 and the corresponding test branch), or (b) accept the dead code as forward-looking. Lean toward (a): KISS.

### F2.5 (MINOR) — T011 hard-blocks T012 unnecessarily
- T012 Depends on T011, but T012's acceptance does not reference any function from session.py.
- This forces sequential implementation when they're independent. Drop T011 from T012's deps.

### F2.6 (MINOR) — `DispatchResult.stdout_events: list[dict]` unbounded growth
- For a long-running command (e.g. `/z-implement-all` spawning many subagents and emitting hundreds of events), `stdout_events` accumulates all parsed JSONL lines in memory.
- Probably fine for v1 (events are small, command dispatch is per-command not per-multi-hour-run). But the dispatcher should NOT be the place that aggregates events for long-lived dispatches — the long-lived run already streams via log-event.sh into events.jsonl. Double-storage in `stdout_events` + jsonl is wasteful.
- Acceptable for v1; flag as a "revisit when first long-dispatch hits memory issues."

## Performance / resources

### F2.7 (MINOR) — Subprocess-per-resolve in compat.py
- Every `resolve_provider()` call shells out to `python3 scripts/resolve-provider.py <role>`. Python interpreter cold-start ~80-120ms. For a single command dispatch this is fine; for /z-implement-all's 6+ subagents (each potentially resolving providers) this is 500ms-720ms of cumulative cold-start.
- v2 fix would be: import scripts/resolve-provider.py as a Python module. The subprocess path was chosen to avoid coupling per Decision C1's approved shortcut. Acceptable v1 tradeoff.

## Security / validation

### F2.8 (MAJOR) — No validation that `auth_env` env-var values aren't logged
- `dispatch_start` payload spec: `driver, command_id, session_id, wall_ms, exit_code, is_error`. No env. ✓ OK by spec.
- But T009's `build_env` returns a dict with secrets in it. If any future event payload (or schema_validation_error event) accidentally serializes the env dict, secrets leak into events.jsonl.
- Recommend adding a SPEC invariant: "Event payloads MUST NOT include any value from build_env's output dict, and the env dict itself must never appear in any logged payload." Plus a test in T015 that calls a deliberate misuse and asserts the secret doesn't appear in any logged event.

### F2.9 (MINOR) — `validate.py` silently trusts schema files at load time
- T006 acceptance: "loads the named schema from `runtime/contract/<schema_name>.schema.json`". No validation that the schema file ITSELF is valid JSON Schema Draft 7 at load time — only T014 validates each schema against the meta-schema as a test.
- If a schema file is corrupted (manual edit + commit), validate.py will silently fail with cryptic jsonschema errors at runtime. Add: validate.py loads the meta-schema once and validates each contract schema on first load (cached). Test catches it; production catches it too.

## Defensive bloat / over-engineering

### F2.10 (MINOR) — compat.py exists at all
- Acknowledged shortcut in PLAN. Real cost: every C2-C5 driver call goes through 2 process boundaries (Python → bash → Python script). Acceptable for v1 transition; just flag for sunset alongside C6's adapter freeze.

## Test coverage gaps

### F2.11 (MAJOR) — T015 lacks malformed-stream-line test
- RESEARCH.md called out stream-json parser fragility as a documented failure mode (e.g. `--output-format stream-json` requires `--verbose` to surface intermediate tool events; without it, minimal payload).
- T012 acceptance: "Non-JSON lines are collected in `stderr`."
- T015 acceptance does NOT include a test where the driver returns: (a) valid JSON line, (b) malformed line (truncated JSON), (c) valid JSON line. The dispatcher must keep parsing past the malformed line and the third line must end up in stdout_events.
- Add to T015 acceptance: malformed-stream-line interleaving test.

### F2.12 (MAJOR) — T015 doesn't test TimeoutReaper SIGKILL path
- T015 acceptance: "TimeoutReaper sends SIGTERM on timeout (use a subprocess that sleeps forever; assert it is reaped within 6s)."
- Tests SIGTERM. Doesn't test the SIGKILL escalation (after SIGTERM, wait 5s, SIGKILL if still alive). Spec T010 mandates SIGKILL escalation but T015 doesn't verify it.
- Add: subprocess that ignores SIGTERM (trap it); assert SIGKILL fires and process is reaped within 11s.

### F2.13 (MINOR) — T016 doesn't test concurrent log_event writes
- `log-event.sh` appends to events.jsonl. If multiple dispatchers run concurrently (multi-cluster /z-implement-all in v2), interleaved appends could corrupt events.jsonl.
- T013 doesn't address atomicity; T016 doesn't test concurrent writes.
- v1 dispatcher is single-threaded per process, so this is probably fine. Flag as a v2 risk only.

## Style alignment with existing repo

- The repo's existing Python (scripts/resolve-provider.py) uses `subprocess.run` patterns, no dataclasses, prints JSON. C1 introduces dataclasses, ABCs, jsonschema. This is a style shift — bigger surface than what exists. Document that runtime/ is the new canonical Python style.

## Phase ordering observation

- Phase A (5 schemas) → Phase B (scaffold) → Phase C (dispatcher) → Phase D (compat) → Phase E (tests).
- Risk: Phase D (compat.py) is the integration point with the existing harness. It's last but is the most likely to surface integration issues. Consider moving compat.py earlier (after Phase B) so integration issues surface before dispatcher implementation locks in assumptions.
