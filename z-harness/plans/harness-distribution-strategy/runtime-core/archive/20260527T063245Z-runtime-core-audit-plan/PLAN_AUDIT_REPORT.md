# Plan Audit Report — harness-distribution-strategy / C1 runtime-core

- **Date (UTC):** 2026-05-27T06:32Z
- **Slug:** harness-distribution-strategy/runtime-core
- **Run ID:** 20260527T063245Z-runtime-core-audit-plan
- **Audit scope:** SPEC.md (101 lines), PLAN.md (120 lines), TASKS.md (197 lines, 16 tasks)
- **Findings:** 16 (3 BLOCKER, 5 MAJOR, 8 MINOR) after pushback filter

## Summary

C1's plan is structurally sound: schemas-first, then scaffold, then dispatcher, then compat shim, then tests. The phases are right; the cluster scope is right; the schema choices (JSON Schema Draft 7, Python ABCs, dataclasses) are reasonable.

However, three contract-level decisions are either unresolved or self-contradictory and would deadlock implementation if shipped as-is. The most urgent is the dispatcher↔driver lifecycle ownership conflict (B1): T012 says the dispatcher parses stream-json from the driver's stdout, while T007 says the driver returns a finished `DispatchResult`. These cannot both be true. The other two BLOCKERs (output-format drift in existing providers.json; args_template composition unspecified) are similar contract gaps. None require rethinking the architecture — they require deciding which side of an ambiguity to land on, then propagating the choice to T007/T012/SPEC invariants.

Five MAJOR findings concern accommodating C4's `SelfHostDriver` need (the C1↔C4 dependency flagged in SHARED-CONCERNS A4), the markdown↔JSON schema mismatch for `commands/z-*.md`, missing defensive invariants for secrets in event payloads, and two specific test-coverage gaps for known-fragile areas (malformed stream lines, SIGKILL escalation).

The 8 MINOR findings are dead-code / YAGNI cleanups and acceptance-criteria specificity (kebab-case pattern, timestamp format, missing-script error message).

**Recommendation:** Run `/z-amend` on C1 to fix the 3 BLOCKERs + 5 MAJORs before any C2-C4 implementation reaches C1's interface. The MINORs can be addressed in the same amend pass at low cost.

## Reality Check findings (Phase 1)

All MUST-EXIST-NOW references verified:
- `scripts/resolve-provider.py` ✓
- `scripts/log-event.sh` ✓ (does NOT emit `schema_version` — compat shim correctly adds it)
- `.z-harness/providers.json` ✓ (shape: `version: 1`, `roles`, `providers` map; two providers — `gemini`, `codex`)
- `runtime/` tree does NOT exist (clean to create)

Drift findings folded into the Actionable Recommendations section below as B2, B3, M2.

## Design & Style findings (Phase 2)

Detailed write-up in `archive/<RUN>/phase2-design.md`. Headline items folded into B1, M1, M3, M4, m1, m2, m3, m8 below.

## Adversarial Consult findings

Both consultants strongly converged on B1, B2, B3, M1, M3, M4, m1, m3 (compat.py earlier). Codex added M5 (move backward-compat test from T014 to T006), m4 (T001 kebab pattern), m5 (T004 timestamp pattern), m6 (T013 missing-script error), m7 (T015 missing env-var negative case). Gemini added the v2 notes on concurrent writes and stdout_events memory growth.

Transcripts archived under `archive/20260527T063245Z-runtime-core-audit-plan/transcripts/`.

## Consensus vs Disagreement

- **Strong consensus** (BLOCKER from both): B1 (lifecycle ownership), B2 (output-format drift), B3 (args composition).
- **Strong consensus** (MAJOR from both): M1 (SelfHostDriver init), M3 (secrets-in-logs), M4 (test gaps for malformed stream + SIGKILL).
- **One consultant added**: M2 (markdown/JSON shape — Phase 1 also flagged), M5 (backward-compat test placement — Codex only).
- **Neither consultant contested** any Phase 1 / Phase 2 finding under "one reason this might be wrong" pushback.

## Pushback applied (findings demoted / dropped)

- **Demoted F2.10 → MINOR (m3):** Phase 2 had it as MAJOR; on reflection, Phase D (compat.py) order vs Phase C (dispatcher) is preference, not a correctness blocker. The dispatcher can stand up without compat.py initially.
- **Demoted F1.3 → documentation note (not in findings):** Inconsistency between providers.json's top-level `version` and other schemas' `schema_version` is intentional backward-compat with an existing file. SPEC should NOTE the discrepancy; it's not a defect to fix.
- **Dropped F2.13 (concurrent writes) and F2.6 (unbounded stdout_events):** Both consultants agreed these are v2 risks. Acknowledged in the SPEC's Risks section; not actionable in C1 v1.

---

## Actionable Recommendations

### BLOCKER (gate C1 implementation until resolved)

#### B1 — Dispatcher↔driver lifecycle ownership (T007 + T012 contradiction)
- **Where:** TASKS.md T007 acceptance vs T012 acceptance.
- **Evidence:** T007 says `HostDriver.dispatch(command_id, args, env) -> DispatchResult` (final result). T012 says `Dispatcher.run()` parses stream-json line-by-line from "the driver's stdout" after calling `driver.dispatch()`. These cannot both be true.
- **Resolution choices:**
  1. **Driver owns the subprocess** — `dispatch()` becomes a generator yielding events and returning the final result; `Dispatcher.run()` consumes the generator. Driver does its own stream-json parsing.
  2. **Dispatcher owns the subprocess** — driver becomes a config provider: `dispatch_config(command_id, args, env) -> (argv: list, env: dict)`; dispatcher does the subprocess launch + parsing.
  3. **Richer return type** — `dispatch()` returns a `DispatchHandle` exposing a `stdout` stream + a `wait()` for final result.
- **Recommendation:** Pick (1) — driver yields events. This puts stream-json parsing in the driver where it belongs (different drivers will have different formats — Cursor SDK driver returns events via its own SDK generator, not stream-json). Also fixes B2 as a side-effect.
- **Action:** Add a new C1-D4 decision row to PLAN.md; update T007 + T012 acceptance to match the chosen option.

#### B2 — Output-format drift in `.z-harness/providers.json`
- **Where:** T012 acceptance mandates `--output-format stream-json` JSONL parsing.
- **Evidence:** Existing `gemini` provider uses `["-p", "-", "--approval-mode", "plan", "--output-format", "text"]`; `codex` uses `["exec", "-"]` with no explicit format. The dispatcher's stream-json parser will get plain text and produce zero events / wrong `is_error`.
- **Conflict:** SPEC invariant #4 mandates backward-compat with the existing providers.json. T012 mandates stream-json. Both cannot hold without either modifying existing providers.json (breaks invariant) or changing T012 (current spec).
- **Resolution:** If B1 is fixed to option (1) "driver owns subprocess + parsing," the dispatcher no longer parses stream-json — drivers do, and each driver knows its own output format. B2 dissolves naturally.
- **If B1 picks option (2) or (3):** add a `output_format` field to provider.schema.json with values `stream-json | text | none`; dispatcher branches on it. Costs schema complexity + branching code.

#### B3 — `args_template` → `args` composition unspecified
- **Where:** T007 `dispatch(command_id, args, env)`, T012 `Dispatcher.run(..., args, provider_config, ...)`. Neither says where `args` comes from.
- **Evidence:** Existing provider entries carry `args_template: list[str]` (e.g. `["exec", "-"]`). The dispatcher receives `args` and `provider_config` — but spec doesn't say `dispatcher composes args = args_template + caller_args`, or `caller pre-composes`, or `driver composes from provider_config`.
- **Recommendation:** Add to SPEC a new "Wire contracts" section (or extend the existing Surface section): "Dispatcher.run() composes final argv as `provider_config['args_template'] + caller_args` and passes the composed list to `HostDriver.dispatch()`. The driver receives a flat list ready to hand to subprocess.Popen." Document in T007's HostDriver.dispatch() docstring and add a T015 test that asserts composition order.

### MAJOR (high-impact; fix before C4 starts)

#### M1 — `HostDriver.init()` doesn't accommodate C4's `SelfHostDriver`
- **Where:** T007 acceptance + SHARED-CONCERNS.md item A4.
- **Evidence:** C4's `SelfHostDriver` needs a tool-call injection point so in-process primitives (Read/Edit/Bash/Agent) can be bound at init time. T007 only specifies `init(provider_config: dict)`.
- **Recommendation:** Widen T007 acceptance: `init(provider_config: dict, context: dict | None = None) -> None`. Drivers ignore `context` keys they don't recognize. Document that `context` is the channel for driver-specific runtime injections (tool registries, parent-session handles, etc.) so the interface stays stable as new driver classes need new injections. Add a T015 test that instantiates a mock SelfHostDriver subclass with a `context={"tools_registry": {...}}` arg.

#### M2 — `command.schema.json` validates JSON but commands are markdown+YAML
- **Where:** T001 acceptance + SPEC.md non-goals ("No user-facing command .md files").
- **Evidence:** T001 specifies JSON Schema for `{id, description, argument_hint, body, schema_version}` objects. Real commands are `.md` files with YAML frontmatter. SPEC says .md format stays. The schema as-written can't validate a `.md` file directly.
- **Recommendation:** Clarify in SPEC: "command.schema.json validates the *parsed JSON projection* of `commands/z-*.md` — frontmatter (YAML→dict) merged with `body` (the markdown body as a string), plus an `id` derived from the filename (kebab-case, sans `.md`). C1 does not provide the .md→projection parser; C6 or a separate utility does." Update T001 acceptance fixture to be a JSON projection example, not a raw .md.

#### M3 — No defensive invariant against secrets in event payloads
- **Where:** SPEC.md Invariants + T009 (env.py) + T015 (tests).
- **Evidence:** `build_env()` returns a dict containing `auth_env` secret values. SPEC enumerates `dispatch_start`/`dispatch_end` payload fields exhaustively (good — no env field). But future events / future code refactors could accidentally serialize the env dict.
- **Recommendation:** Add SPEC Invariant #7: "Event payloads MUST NOT include any value from the output dict of `build_env()`. The env dict itself is never loggable; `dispatcher.py` MUST NOT pass the env dict to `log_event()` under any circumstances." Add a T015 test: deliberately attempt to log an env dict via a mocked `log_event` call and assert the secret string does not appear in the captured payload.

#### M4 — T015 test coverage gaps for known-fragile areas
- **Where:** T015 acceptance.
- **Evidence:**
  - **Malformed stream lines:** RESEARCH.md called out stream-json parser fragility. T012 says "Non-JSON lines are collected in stderr" but T015 only tests valid JSON parsing.
  - **SIGKILL escalation:** T010 spec mandates "SIGTERM, wait 5s, SIGKILL if still alive." T015 tests SIGTERM only, not SIGKILL escalation against a SIGTERM-trapping process.
- **Recommendation:** Add to T015 acceptance two cases:
  - "Malformed-stream interleaving: driver returns `{valid}\\n{truncated\\n{valid}` — assert both valid lines in `stdout_events`, truncated line in `stderr`, no crash."
  - "SIGKILL escalation: subprocess that traps SIGTERM (sh -c 'trap "" TERM; sleep 999'); assert reaped within 11s."

#### M5 — Move backward-compat test for `.z-harness/providers.json` from T014 → T006
- **Where:** T006 acceptance vs T014 acceptance.
- **Evidence:** T014 (Phase E, last) includes the test that the existing `.z-harness/providers.json` validates against the new provider.schema.json. If T003 wrote the schema too strictly, this test fails late — after T007-T013 are already implemented.
- **Recommendation:** Move this test to T006 acceptance: validate `.z-harness/providers.json` as soon as validate.py is written. Fail fast.

### MINOR

#### m1 — `ENV_STRIP_LIST` is YAGNI
- SPEC invariant #3 reserves a hook with an empty initial list. Drop it from v1; reintroduce when a concrete strip-need surfaces.

#### m2 — T011 (session.py) → T012 dependency is unnecessary
- T012 acceptance does not reference any function from session.py. Drop the dep so T012 can implement in parallel with T011 (or defer T011 to v2 entirely — its stubs are dead code in v1).

#### m3 — Phase ordering: consider doing compat.py (Phase D) after Phase B
- Integration with existing scripts/* is low-risk subprocess wrapping; surfacing integration issues before dispatcher implementation reduces rework risk.

#### m4 — T001 doesn't specify the kebab-case pattern regex
- Acceptance says `id` is "kebab-case string pattern" without giving the regex. Implementer may pick `^[a-z0-9-]+$` vs `^[a-z][a-z0-9-]*$`. Specify: `^[a-z][a-z0-9-]*$` (matches existing slug validator used in `/z-plan-split` and other commands).

#### m5 — T004 timestamp `ts` field format under-specified
- "ISO 8601 pattern" allows multiple formats. Existing repo uses UTC with `Z` suffix (e.g. `2026-05-27T05:05:49Z`). Pin: `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`.

#### m6 — T013 (compat.py) missing-script error message under-specified
- Add: "raises `FileNotFoundError` with message naming the expected path if `scripts/resolve-provider.py` is absent from `repo_root`."

#### m7 — T015 missing env-var negative test
- Add: "Test where `provider_config` specifies `auth_env: 'MISSING_VAR'` and the env-var is not set. Assert returned dict OMITS the key (not empty string)."

#### m8 — `validate.py` doesn't validate schemas at load time
- T006 acceptance only requires runtime validate(). Add: on first import, validate.py loads each schema and validates it against the Draft 7 meta-schema; caches result. Test: corrupt a schema file and assert validate.py errors with a clear message naming the offending file.

### Notes for v2 (not actionable in C1 v1)

- **N1 — Concurrent writes to events.jsonl:** log-event.sh appends without locking. Single-threaded v1 dispatcher is safe; v2 multi-dispatch could corrupt the log. Track when introducing parallel dispatch.
- **N2 — `DispatchResult.stdout_events` unbounded growth:** acceptable for per-command dispatch. Revisit if a long-lived dispatch (e.g. multi-hour `/z-implement-all`) accumulates enough events to matter.
- **N3 — Subprocess-per-resolve latency in compat.py:** ~100-300ms cold start per `resolve_provider()` call. Acceptable in v1; consider importing resolve-provider.py as a module when compat.py is sunset alongside C6.

---

## Cross-cluster ripple effects

Findings that affect more than C1:

- **B1 / B2 / M1** all touch the C1↔C2/C3/C4 interface. Fixing them in C1 first prevents driver-cluster rework.
- **M2** touches C1↔C6 boundary. Either C6 owns the .md→projection parser, or C1 ships it as a utility — decide before C6-T002 (bulk command migration).
- **M5** is internal to C1 (just reorders tests).
- All MINORs are internal to C1.

If `/z-amend` is run for C1 to address these findings, no amendment is needed to C2-C6 plans — C1's interface improvements are forward-compatible (init takes optional context; dispatcher returns events via a clearer ownership model that drivers will adopt at implementation time).
