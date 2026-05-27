# Amendment: apply C1 PLAN_AUDIT_REPORT findings

**Run:** 20260527T155455Z-amend-runtime-core
**Mode:** full
**Requested change:** Apply the 3 BLOCKER + 5 MAJOR + 8 MINOR findings from `PLAN_AUDIT_REPORT.md` (audit run 20260527T063245Z-runtime-core-audit-plan). The findings are contract-sharpening, not architectural rewrites — 0 new tasks, 0 tasks removed, ~10 tasks get richer acceptance criteria, 2 new PLAN.md decisions land.

## Scope size check
- New tasks: **0** (well under 5-task threshold).
- SPEC premise: **unchanged** — same schemas, same dispatcher, same compat shim.
- ~10 of 16 tasks (~62%) have acceptance criteria edits. Most are 1-3 line additions.
- 2 new PLAN decisions (C1-D4, C1-D5) added; 1 existing PLAN risk dropped.
- Conclusion: under the "30% rewrite" hard rule. Proceed as amendment, not replan.

## Completed-task snapshot
0 `[x]` tasks. No supersede flow needed.

## What this affects

### SPEC.md
- **Invariants section** — add #7: event payloads must not include `build_env()` output values (M3). Modify #3: drop the empty `ENV_STRIP_LIST` hook (m1).
- **Surface section** — add new subsection "Wire contracts" specifying: (a) dispatcher↔driver lifecycle ownership = driver owns subprocess + parsing, dispatch() yields events and returns final result (B1); (b) `args` composition: `Dispatcher.run()` composes `provider_config['args_template'] + caller_args` before calling driver (B3); (c) `command.schema.json` validates the *parsed JSON projection* of `commands/z-*.md`, not the raw markdown (M2).
- **Non-goals** — clarify: no .md→projection parser ships in C1 (M2).
- **Telemetry/events** — affirm dispatcher emits only documented payloads; reference Invariant #7.
- Add a closing note about the `version` vs `schema_version` field-name asymmetry in providers.json (informational, intentional backward-compat — not a defect).

### PLAN.md
- **Decisions table** — add C1-D4 (driver owns subprocess + parsing, resolves B1+B2) and C1-D5 (`HostDriver.init` takes optional `context: dict | None = None` for SelfHostDriver tool-registry injection, resolves M1).
- **Approved shortcuts** — affirm session.py is deferred to v2 (was already a shortcut; now firmer).
- **Risks** — drop "ENV_STRIP_LIST hook" risk (it's gone). Add v2 risk notes for: concurrent writes to events.jsonl (N1), `DispatchResult.stdout_events` unbounded growth (N2), subprocess-per-resolve latency (N3).
- **Phases** — add note that Phase D (compat shim) MAY be implemented after Phase B if integration risk is a concern (m3 advisory, not mandatory reorder).
- New **## Amendments** section at the bottom recording date + this amendment.

### TASKS.md

**No new tasks. No tasks removed. ~10 tasks modified:**

- **T001** — Add explicit kebab-case pattern `^[a-z][a-z0-9-]*$` to acceptance + add negative fixture for leading-digit (m4).
- **T003** — Reaffirm backward-compat: existing `.z-harness/providers.json` validates (already there, no change). Add note that `version` (top-level) is the legacy field name; per-entry has no version field.
- **T004** — Add explicit timestamp regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` (UTC `Z` suffix only) (m5).
- **T006** — Move `.z-harness/providers.json` backward-compat validation from T014 → T006 (M5). Add meta-schema validation at load time with caching (m8). Add Files: `runtime/validate.py` (already there) + ensure the test runs as part of T006 not T014.
- **T007** — Major update: per C1-D4, `HostDriver.dispatch()` is now a generator-style method returning `Iterator[dict] | DispatchResult` via a `DispatchHandle` (final shape decided at implementation time — interface contract is: driver owns subprocess + stream parsing). Per C1-D5, `init(provider_config: dict, context: dict | None = None)`. Add to acceptance: a SelfHostDriver-like mock subclass instantiates with `context={"tools_registry": {...}}` and ignored context fields don't break Liskov.
- **T009** — Drop `ENV_STRIP_LIST` from acceptance (m1).
- **T010** — Clarify SIGTERM timing: "wait *exactly* 5s after SIGTERM before SIGKILL; do not SIGKILL if process exited within window."
- **T011** — Mark as **DEFERRED to v2** (struck through `[~]`). Session resumption isn't called by any v1 driver. Stub helpers remain unwritten until a driver needs them (m2 + F2.4).
- **T012** — Major update: per C1-D4, dispatcher no longer parses stream-json directly. Dispatcher: (a) composes `args` from `provider_config['args_template'] + caller_args` (B3); (b) calls `driver.dispatch()` which streams events and returns final result; (c) applies `TimeoutReaper` around the driver call; (d) emits `dispatch_start` / `dispatch_end` events. Drop "Parses --output-format stream-json JSONL from the driver's stdout" — that's driver work now. Drop T011 from deps.
- **T013** — Add to acceptance: `resolve_provider()` raises `FileNotFoundError` with path-naming message if `scripts/resolve-provider.py` is absent (m6).
- **T015** — Substantial additions: malformed-stream interleaving test (M4); SIGTERM-trapping subprocess for SIGKILL escalation (M4); env-missing negative test (m7); secret-not-in-event-payload test (M3); env.py drops the `ENV_STRIP_LIST` test branch (m1); SelfHostDriver subclass instantiation test (M1).
- **T014** — Remove backward-compat test (moved to T006 per M5). T014 keeps the schema meta-validation + valid-fixture tests only.

**Complexity re-classification:** T007 and T012 changed substantially (new generator semantics, new contract). Strip and re-stamp via classifier. T015 also grew significantly — re-stamp. T001, T004, T009, T010, T011, T013 had only minor acceptance edits; preserve existing stamps. T006 absorbed two new acceptance criteria — re-stamp. T014 shrank — re-stamp.

Tasks to re-classify: **T006, T007, T012, T014, T015** (5 tasks).

## Risk

Phase 5 consult triggers:
- **Public API / wire format change** — YES: B1 changes the `HostDriver` interface shape, which is the wire contract every other cluster (C2/C3/C4) implements.

But: this amendment **directly implements** both consultants' recommendations from the audit phase 6 hours ago (audit run 20260527T063245Z). The audit phase 3 dispatched both consultants on this exact plan, and the BLOCKER findings (B1 + B2 + B3) are their convergent recommendations. Re-consulting them on the implementation of their own recommendations is wasteful.

**Recommendation: skip Phase 5 consult.** Log the skip with explicit justification.

## Cross-cluster ripple
Per the audit report's "Cross-cluster ripple effects" section: the C1 interface improvements are forward-compatible. C2/C3/C4 don't need amendment yet — they'll consume the sharper interface at implementation time. SHARED-CONCERNS.md item A4 (SelfHostDriver init) is now resolved by C1-D5; the SHARED-CONCERNS doc should get a status update too — handle as a small Edit at the end of Phase 6.
