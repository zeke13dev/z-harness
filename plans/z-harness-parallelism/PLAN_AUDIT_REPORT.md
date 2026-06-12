# Plan Audit Report — z-harness-parallelism

- **Date (UTC):** 2026-06-12T19:10Z
- **Slug:** z-harness-parallelism
- **Run ID:** 20260612T190214Z-z-harness-parallelism-audit-plan
- **Method:** direct codebase reality-check (Phase 1) + design audit (Phase 2) + adversarial cross-LLM review (Phase 3, consultant-primary + consultant-secondary) + one-reason-might-be-wrong gate (Phase 4).
- **Scope reviewed:** SPEC.md, PLAN.md, TASKS.md (15 tasks T001–T015) against `scripts/generate-workstreams.py`, `scripts/hermes-execute.py`, `scripts/hermes/{schema,config}.py`, `scripts/active-plan-registry.py`, `agents/scope-extractor.md`, `docs/human/hermes-integration-v1.md`.

---

## Summary

The plan is **structurally sound and well-sequenced** — the de-risking order (fix compile bug → build scope data → labels → config → sequential scheduler → conflict partition → poll decouple → concurrency flip → cross-plan → docs → e2e) is correct, the TASKS DAG is acyclic with 15 tasks and no dangling deps, and the decisions (worktree write-safety, `depends_on`-authoritative scheduling, fail-safe serialization) are the right ones. The baseline-reality claims it rests on are **all verified true** (compile bug, sequential loop, hardcoded `parallel_group`/`file_conflicts`).

However, the audit surfaced **one consensus blocker** that makes the headline feature (within-plan file-conflict safety) inert as written, and **several majors** centered on concurrency-primitive correctness that the plan's own test strategy will not catch. None require re-planning from scratch; all are addressable via `/z-amend` to specific tasks.

**Headline:** the within-plan conflict-safety layer (T002/T003/T008/D5) depends on a per-workstream `scope.json` artifact that **z-plan never persists** and whose **claimed task-attributed shape does not exist**. Left as-is, `scope_unknown` is always true → `file_conflicts` always empty → T008 always serializes (or, depending on how the gap is read, never serializes). The cross-plan scope data (T011), by contrast, genuinely exists and is adequate.

- **Findings:** 16 | **Blockers:** 1 | **Majors:** 8 | **Minors:** 6 | **Refuted/Demoted by gate:** 2 (reported for transparency, not counted).

---

## reality-check — Reality Check findings (all verified against the codebase)

| Claim in plan | Verified? | Evidence |
|---|---|---|
| `generate-workstreams.py` does not compile, IndentationError ~357 | **TRUE** | `python3 -m py_compile` → `IndentationError: unexpected indent, line 357`. Root cause is sharper than described: `def _task_sort_key` (line 349) is pasted **into the middle of** the `for i, tasks in enumerate(final_workstreams)` loop body (line 346), splitting it — lines 356–369 are the orphaned remainder. T001's fix ("move to module scope") is correct and sufficient. |
| `parallel_group` hardcoded `None` in all three builders | **TRUE (with nuance)** | `build_from_split:534` and `build_from_light:682` emit `"parallel_group": None`. `build_from_flat:621` does **not emit the key at all** (defaults to `None` via schema). T004 must add it to flat, not just flip a literal. |
| `build_from_flat` emits `file_conflicts = []` | **TRUE** | line 646 (comment 645). `build_from_split` also at 538. |
| `hermes-execute.py` topo-sorts then runs a sequential loop; never reads `parallel_group`/`file_conflicts` | **TRUE** | `exec_order` built 176–190; `for ws_id in exec_order:` at 194; `poll_session` synchronous at 258; grep confirms `parallel_group`/`file_conflicts` never referenced in the file. 413 lines total. |
| `derive_severity()`, `validate_workstreams()`, `assign_depths()` exist and are reusable | **TRUE** | lines 501, 54, 198. |
| `scope-extractor` agent + `active-plan-registry.py` already provide structured scope | **PARTLY TRUE — see Blocker B1** | scope-extractor emits `[{path,confidence,reason}]`; registry stores it plan-level. Neither is task-attributed, and the plan-dir `scope.json` is never persisted. |
| New files don't clash | **TRUE** | all six proposed new files (`tests/test_generate_workstreams.py`, `tests/test_hermes_execute.py`, `scripts/hermes/cross_plan.py`, `tests/test_hermes_cross_plan.py`, `tests/test_hermes_e2e.py`, `tests/test_hermes_config.py`) are absent. |
| TASKS DAG acyclic, root T001, no missing deps | **TRUE** | programmatic check: 15 tasks, no cycle, every `Depends on` ref resolves. |
| Four worked DAG examples in `hermes-integration-v1.md` (T001 fixtures) | **TRUE** | lines 161–182: linear chain, fan-out, two independent chains, deep fork — each with an expected workstream decomposition. (They give task-set decompositions, not full `merge_order` JSON — see M9.) |

---

## design-check — Design & Style findings

### BLOCKER

**B1 — Within-plan `scope.json` is never written, and its claimed shape does not exist (T002, T003, D5; SPEC §`generate-workstreams.py` items 3–4).**
Consensus: both consultants independently confirmed.
- **Never persisted.** `commands/z-plan.md:945–959` dispatches `scope-extractor`, writes the JSON to a **temp file** (`$SCOPE_JSON`), pipes it straight into `active-plan-registry.py update-scope`, and discards it. No task writes `<plan-dir>/scope.json`. T002 ("Read optional `<plan-dir>/scope.json`") therefore reads a file that never exists → T002's "absent ⇒ graceful empty" branch always fires → T003 always sets `scope_unknown: true` → `file_conflicts` always empty for flat plans → T008's partition is driven entirely by the `scope_unknown`/`serialize_all` fail-safe, never by real per-file conflict data. The marquee within-plan conflict-safety feature is inert as designed.
- **Shape mismatch.** SPEC line 46 claims `scope.json` is `{task, paths[]}` or `{path, workstream_hint}`, "the same shape `scope-extractor` emits and `update-scope` consumes." Both halves are false: `agents/scope-extractor.md` emits a **flat** `[{path, confidence, reason}]` with **no task key**; `active-plan-registry.py update-scope` consumes that same flat shape (`[{path,confidence,reason}]`, registry.py:48). The task→workstream→paths mapping T002/T003 require is not derivable from this output except by parsing the free-text `reason` field (which only *sometimes* embeds `Txxx`, and the mechanical fallback emits `"reason":"mechanical fallback"` with no task at all).
- **Recommendation (pick one, amend before T002/T003):**
  1. Add a task *before* T002 that persists `scope-extractor` output to `<plan-dir>/scope.json` in z-plan's Phase 8 hook, **and** extend `scope-extractor` to emit a `task_id` per entry (it already accepts an optional `task_id:` input and reads per-task `**Files:**` lines — the attribution exists internally, it's just flattened on emit); or
  2. Pivot T002/T003 to derive per-workstream scope by re-parsing each task's `**Files:**` line from TASKS.md directly (the same source scope-extractor uses), dropping the `scope.json` dependency entirely. This is the most DRY option and removes a fragile cross-artifact handoff.
- Note the asymmetry to preserve in the amend: **cross-plan scope (T011) is fine** — it needs only plan-level intersection, and `registry.record.scope` provides exactly that.

### MAJOR

**M1 — Semaphore lifetime is under-specified; "acquired around session spawn" does not bound live sessions (T010; SPEC §hermes-execute item 5).**
SPEC line 98 says the `asyncio.Semaphore(max_parallel_workstreams)` is "acquired around session spawn." If released after spawn (a sub-second operation), N workstreams all spawn then all run live — the cap bounds spawn rate, not concurrency. To bound *live* sessions the semaphore must be held for the whole `run_workstream` lifetime (spawn → monitor → merge). **This is the single most insidious finding:** the plan's only parity test is cap=1 (T010 acceptance, INV-5), and cap=1 never exercises the contended-semaphore path, so a wrong placement passes every test and silently removes the concurrency bound at cap>1. **Recommendation:** reword SPEC/T010 to "acquire at the start of `run_workstream`, release at the end, via `async with sem:`"; add a cap=2-with-3-ready-workstreams test asserting ≤2 live sessions at any instant.

**M2 — `derive_severity` returns "high" only for special config/lock paths, so T008 guards almost no real conflicts (T008; `generate-workstreams.py:501`).**
`derive_severity(file_path, workstream_count)` returns "high" only when the path matches `HIGH_SEVERITY_RE`/`HIGH_SEVERITY_NAMES` (sql/migration/schema/toml/yaml/proto, Dockerfile, Makefile, lockfiles); "medium" requires `workstream_count >= 3`. Two workstreams editing the same ordinary `foo.py` → **"low"** → T008 ("no two workstreams in a sub-batch share a *HIGH*-severity entry") co-batches them → they collide at merge. The plan treats this as merge-time-safe (INV-1/INV-3, sequential conflict-aware merge), which is *correct for safety* — but it means T008's partitioning provides essentially **zero** avoidance for the common case (ordinary same-file overlap), contradicting the implied value of "conflict-aware partition." **Recommendation:** either (a) have T008 serialize on `medium`+`high` (not high-only), or (b) bump severity to ≥medium whenever ≥2 workstreams share *any* non-trivial source path, or (c) explicitly document that same-file overlaps are intentionally deferred to merge and T008 only protects structurally-shared declarative files — and right-size the task's stated value accordingly.

**M3 — Config concurrency knob collision; `ConcurrencyConfig` already exists (T006; `config.py:23–25,90,120`).**
`config.py` already defines `ConcurrencyConfig(max_parallel_sessions=3)`, wired into `load_config` and env-overridable via `HERMES_MAX_PARALLEL` — but **dormant** (never read by the sequential executor). T006 proposes a *new* `Concurrency` dataclass with `max_parallel_workstreams=1` and `max_parallel_plans=1`, with no mention of the existing one. Two overlapping dataclasses, two names for "live sessions," and a **default conflict** (existing 3 vs proposed 1 — INV-5 wants 1). **Recommendation:** extend the existing `ConcurrencyConfig` in place (add `max_parallel_workstreams`, `max_parallel_plans`, `serialize_all`, `serialize_high_severity`); decide whether `max_parallel_sessions` is the same concept as `max_parallel_workstreams` and deprecate one; flip the default to 1 and document the contract change (incl. the `HERMES_MAX_PARALLEL` env name).

**M4 — Cross-plan global merge mutex is in-process only; not actually global (T013; SPEC §cross-plan).**
SPEC line 128 specifies "a single in-process lock." That serializes merges *within one super-orchestrator process* but not across two independent orchestrators, nor against a concurrent plain `hermes-execute.py --slug X` run merging into the same base. The slug-level `plan-claim.sh` locks (T012) prevent two runs of the *same* slug, but not two *different* slugs (or a cross-plan run + a single-plan run) merging to the shared base concurrently. **Recommendation:** back the merge mutex with a filesystem lock (`flock` on a per-repo `.git/z-harness-merge.lock`, or reuse `plan-claim.sh`/`sink-lock.sh` on a reserved "merge" key) so it holds across processes.

**M5 — Cross-plan conflict graph is a stale snapshot, and "low-confidence" is undefined (T011, T012; SPEC §cross-plan).**
`build_plan_conflict_graph` reads the registry once. A plan registering between graph-build and scheduling is invisible → two conflicting plans may be co-scheduled. Separately, the fail-safe rule "either plan is `scope_unknown`/**low-confidence** ⇒ serialize" never defines low-confidence; `scope-extractor` confidence is per-path (`explicit|inferred|broad|unknown`) with no aggregation rule given. **Recommendation:** rebuild (or re-check) the conflict graph immediately before each plan starts, not once; define "low-confidence" concretely (e.g., any path with confidence weaker than `explicit`, or any `unknown`/empty entry ⇒ treat plan as `scope_unknown`).

**M6 — Cross-plan locks can expire mid-run; no heartbeat refresh specified (T012; `plan-claim.sh:56`).**
`plan-claim.sh` `DEFAULT_TTL_SECONDS=2700` (45 min). T012 acquires each slug's claim "in sorted order" and "release[s] all on any failure" but specifies no heartbeat. A cross-plan run with serialized conflicting plans can easily exceed 45 min, expiring a held claim mid-execution and letting a peer take over a slug that's still running. **Recommendation:** T012/T013 must run a background heartbeat loop refreshing every held claim (`plan-claim.sh heartbeat`) at an interval well under the TTL, for the full duration each plan is live.

**M7 — T001 acceptance contradicts itself: there is no "current" output to characterize (T001; SPEC §tests).**
T001 says "Write characterization tests … asserting **current** `depends_on` + `merge_order` output." The generator currently **crashes**, so there is no current output. The authoritative expected values are the doc's worked examples (lines 161–182). **Recommendation:** reword acceptance to: "after the compile fix, running the four worked-example TASKS.md fixtures through the generator reproduces the doc's documented decompositions exactly; pin those as goldens." State explicitly that the doc examples — not pre-fix behavior — are the source of truth (and reconcile if the fixed generator diverges from the doc).

**M8 — T007 golden-parity test constructability is unproven (T007; SPEC §tests).**
T007 ("high" complexity) bundles a verbatim `run_workstream` extraction *and* a behavioral level-scheduler change, with acceptance "behavior-parity vs a captured sequential golden (mocked session/worktree/merge)." The monitor is an inline `while True: asyncio.sleep(5)` loop over real worktree/session state; it is non-obvious how to capture a deterministic golden without either real sessions (slow, needs a repo) or mocking the entire monitor control flow (couples the test to implementation). **Recommendation:** pin the mock boundary in the SPEC (replace `run_workstream`'s session-to-done await with a fake terminal-status injector; assert the *sequence* of spawn/merge calls and their order), and build a 3-workstream toy proof before committing T007. Consider splitting T007 into "extract (pure refactor, parity test)" and "level scheduler (new behavior test)."

---

## adversarial — Adversarial Consult findings (minors)

**m1 — `merge_order` vs recovery reorder is unspecified (INV-3; SPEC §hermes-execute item 7).** Merges stay sequential per `merge_order`, but a crash/retry in an earlier level could let a later-`merge_order` workstream become mergeable first on resume. Document the invariant: no workstream merges before a `merge_order` predecessor, even across retries; add a recovery test.

**m2 — `assign_depths` reuse trap in T004 (T004; `generate-workstreams.py:198`).** The math is sound — longest-path depth provably yields same-level mutual independence (if B depends on A, `lp(B) ≥ lp(A)+1`), so Rule-7-by-construction holds — **and** the plan already specifies *workstream*-level longest-path. The risk is purely implementational: the existing `assign_depths` computes **task**-level depths; silently reusing it to label workstreams would be unsound. Add an explicit note: "write a new `assign_ws_depths(ws_objects)`; do not reuse the task-level `assign_depths`," plus a test with a cross-workstream edge (W1={T1,T2}, W2={T3,T4}, T2→T4) asserting distinct levels.

**m3 — `scope_unknown` semantics ambiguous for split/light plans (T003; SPEC line 49).** `build_from_split` already derives `file_conflicts` from SHARED-CONCERNS.md, so split plans have conflict data but no per-task scope. Define whether `scope_unknown` means "no per-workstream scope" (then split should set it, even with conflicts) or "no conflict data at all" (then split is always false). Clarify in SPEC.

**m4 — T008 partition algorithm is unspecified (T008).** Partitioning workstreams so no sub-batch shares a high-severity edge is graph coloring; greedy order changes the result. Pin a deterministic rule: "iterate workstreams in `depends_on` topological order; place each in the first existing batch with no conflicting member, else a new batch." Add the chain-conflict test case.

**m5 — T015 determinism claim needs a precondition (T015).** "cap>1 final tree == cap=1 final tree" holds only if the per-task work is itself deterministic (no timestamps/random data in outputs). Reword to assert equality of the **git tree hash** under a deterministic-task precondition; commit metadata (authored_date) may legitimately differ.

**m6 — Poll decoupling doesn't bound a hung poll (T009).** `await asyncio.to_thread(poll_session, …)` moves the blocking call off the event loop but a hung poll still ties up a thread-pool worker indefinitely. Wrap in `asyncio.wait_for(..., timeout=poll_interval)` and map timeout → a "stalled" status so siblings stay responsive.

---

## Consensus vs Disagreement

- **Consensus (both consultants + reality-check):** B1 (scope.json broken), M3 (config knob collision), M2 (severity under-protection). These are the highest-confidence findings — independently reached.
- **Cross-confirmed concurrency primitives:** M1 (semaphore lifetime), M6 (lock TTL), M8/M7 (test constructability/contradiction) — each raised by at least one consultant and confirmed against source.
- **Outliers worth manual scrutiny:** M4 (in-process merge mutex) assumes you care about *cross-process* concurrency; if z-harness only ever runs one orchestrator per repo at a time, this degrades to a MINOR. M5 (graph staleness) is partly mitigated by the slug claim-locks already in T012.

### Refuted / demoted by the one-reason-might-be-wrong gate (reported for transparency)

- **REFUTED — "partial_tree cycle path is dead code" (consultant-primary).** Claim was that empty `workstreams` + empty `merge_order` fail Rule 3 (permutation). Verified directly: `validate_manifest` on an empty manifest returns `[]` (no errors) — `set() == set()`. The cycle→empty path is valid. Dropped.
- **DEMOTED BLOCKER→MINOR — "depth-notion collision" (consultant-secondary).** The asserted unsoundness (same-level workstreams with hidden deps) cannot occur under longest-path depth (proven above), and the plan already specifies ws-level depth. Only the implementation trap survives, captured as **m2**.

---

## Actionable Recommendations

**Must-fix before implementation starts (amend via `/z-amend`):**
1. **B1** — Resolve the scope-data chain: either persist a task-attributed `<plan-dir>/scope.json` (and extend `scope-extractor` to emit `task_id`), or pivot T002/T003 to parse `**Files:**` lines from TASKS.md directly. Add the missing task. *Without this, T002/T003/T008/D5 ship inert.*
2. **M1** — Specify semaphore held for `run_workstream` lifetime (`async with sem:`); add a >cap-ready-workstreams concurrency-bound test (cap=1 alone cannot catch a wrong placement).
3. **M3** — Reconcile T006 with the existing `ConcurrencyConfig`/`HERMES_MAX_PARALLEL` (extend, don't duplicate; flip default to 1; document).

**Fix before the relevant task:**
4. **M2** — Decide T008's severity policy (serialize ≥medium, or bump overlap severity, or explicitly document merge-time-only and right-size the task).
5. **M7** — Reword T001 acceptance (doc examples are the source of truth, not nonexistent "current" output).
6. **M8** — Pin T007's mock boundary and prove a toy parity test; consider splitting extract vs scheduler.
7. **M4/M5/M6** — Cross-plan hardening: filesystem-backed merge lock; rebuild conflict graph per-plan-start + define "low-confidence"; background claim-heartbeat loop under the 2700s TTL.

**Clarify in SPEC/TASKS (low effort):**
8. **m1–m6** — merge_order-vs-recovery invariant; `assign_ws_depths` note; `scope_unknown` split/light semantics; T008 deterministic coloring rule; T015 git-tree-hash + determinism precondition; T009 `wait_for` poll timeout.

**Overall:** proceed to `/z-amend` to fold B1 + M1 + M3 (the three that change task shape) into the plan, then the remaining majors/minors as spec clarifications. No full re-plan needed — the architecture and sequencing are sound; the gaps are in the scope-data plumbing and three concurrency-primitive details whose correctness the current test plan would not surface.
