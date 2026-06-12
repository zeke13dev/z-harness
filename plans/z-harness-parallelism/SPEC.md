# SPEC — z-harness true parallelism

Activate the dormant Hermes orchestration layer into a working parallel executor across three fronts: (1) within-plan DAG activation, (2) cross-plan orchestration, (3) lock / file-conflict safety. The scaffolding largely exists but is broken or sequential; this is **activation + repair**, not greenfield.

> **Plan dir note.** This `plans/z-harness-parallelism/` copy is the human-facing artifact requested for this task. The live z-harness run resolves `$Z_HARNESS_PLAN_DIR` to the external state base; both hold identical SPEC/PLAN/TASKS content.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| MAP.md | — | n/a |
| BRAINSTORM.md | — | n/a |
| RESEARCH.md | — | n/a |
| GRILL.md | — | n/a |

none — fresh /z-plan run grounded by direct reads of `scripts/hermes-execute.py`, `scripts/generate-workstreams.py`, `scripts/hermes/schema.py`, and `docs/human/hermes-integration-v1.md`.

## Baseline reality (verified)

- `scripts/generate-workstreams.py` **does not compile** — `IndentationError` at line 357: `def _task_sort_key` is mis-pasted into the body of `run_5rule_algorithm`'s final `for` loop. Zero tests reference it. The flat `/z-plan` → `workstreams.json` path is dead.
- `parallel_group` is hardcoded `None` in all three builders (`build_from_flat`, `build_from_split`, `build_from_light`). The 5-rule algorithm computes depth-levels and parent-splits but never labels parallel groups.
- `scripts/hermes-execute.py` builds a correct topological `exec_order` (lines 165-190) then runs it through a **plain sequential `for ws_id in exec_order:` loop** (line 194) — one `await`-blocked workstream at a time. `parallel_group` is never read; `file_conflicts` is never read.
- Each workstream runs in its own `git worktree` on a shared base commit; merge is sequential per `merge_order` and already conflict-aware.
- Flat `/z-plan` emits `file_conflicts: []` — no within-plan conflict data exists for flat plans.
- `scripts/active-plan-registry.py` already tracks concurrent plans with per-plan file scope; `scripts/plan-claim.sh` already does slug-level claim locks; `scope-extractor` agent already emits structured per-file scope at plan time.

## Invariants

- **INV-1 (worktree write-safety):** concurrent workstreams write to isolated worktrees; the working tree is never shared. File conflicts are a *merge-time* concern, not a write-time one.
- **INV-2 (depends_on is authoritative for scheduling):** a workstream is eligible to start iff every id in its `depends_on` has reached `done`. `parallel_group` is a derived label, never the scheduling gate.
- **INV-3 (merge_order is authoritative for merge sequence):** merges remain sequential and conflict-aware regardless of execution concurrency.
- **INV-4 (fail-safe serialization):** when conflict/scope information is missing, low-confidence, or `serialize_all` is set, the orchestrator serializes rather than parallelizes. Silent blind parallelism is forbidden.
- **INV-5 (cap=1 ≡ legacy sequential):** with `max_parallel_workstreams=1` the new scheduler must be behaviorally equivalent to today's sequential loop (same completion/merge order outcomes).
- **INV-6 (deadlock-free cross-plan locking):** plan-claim locks across slugs are always acquired in a single deterministic order (sorted slug ascending).
- **INV-7 (forward-compatible protocol):** `protocol` stays the version pin; new fields are additive; orchestrators ignore unknown fields.

---

## File: `scripts/generate-workstreams.py`

### Surface / changes

1. **Compile fix.** Move `_task_sort_key` to module scope (above `run_5rule_algorithm`). No behavior change to the sort.
2. **`parallel_group` population.** During workstream-object construction in `run_5rule_algorithm`, compute each workstream's **DAG depth** = longest path from a root in the *workstream* `depends_on` graph. Assign `parallel_group = f"level-{depth}"`. Because depth is the longest path, two workstreams sharing a depth can never have a transitive `depends_on` between them → Rule 7 (`validate_workstreams`) passes by construction. Validate before emit (existing call site).
3. **Structured `file_conflicts` for flat plans.** Replace `file_conflicts = []` in `build_from_flat` with a derivation from **per-task `**Files:**` lines in TASKS.md** — the same source `scope-extractor` parses (amended per audit B1; see note below):
   - For each task block, extract comma-separated path tokens from its `**Files:**` line, stripping annotation suffixes (`(new)`, backticks, glob descriptions) using the existing `scope-extractor` token rules (do not write a second normalizer).
   - Map task → workstream (already known from the 5-rule result); union task paths per workstream; for each path touched by ≥2 workstreams, emit `{file, workstreams[], severity}` via the existing `derive_severity()`.
   - **Any task block missing a parseable `**Files:**` line** → overlap detection would be blind → leave `file_conflicts: []` AND set a new top-level boolean `scope_unknown: true` in the manifest. Never silently treat "no data" as "no conflicts."
   - **Audit B1 rationale:** the original design read a `<plan-dir>/scope.json` "the same shape `scope-extractor` emits and `update-scope` consumes." That artifact is never persisted (z-plan writes `scope-extractor` output to a temp file, pipes it to `update-scope`, and discards it) and its flat `{path,confidence,reason}` shape carries no task attribution. Parsing TASKS.md `**Files:**` lines directly keeps task→path attribution and removes the dead cross-artifact dependency.
4. **`scope_unknown` field.** New top-level manifest field (default `false`). `true` whenever per-workstream scope could not be established — i.e. a flat plan in which one or more task blocks have no parseable `**Files:**` line (split plan with no SHARED-CONCERNS overlap data likewise sets it). No `scope.json` is read.

### Behavior / edge cases

- Generator must `python3 -m py_compile` cleanly (regression guard for the original bug).
- Idempotent: unchanged inputs → byte-identical output (existing contract); new fields are deterministic.
- Cycle detection unchanged (`CycleError` → `partial_tree: true`, empty workstreams).
- `build_from_split` and `build_from_light`: also populate `parallel_group` via the same depth rule (split is currently linear so all become distinct levels; light is single ws = `level-0`).

### Tests (characterization-first)

- Characterization tests for all four worked examples in `hermes-integration-v1.md` (linear chain, fan-out, two independent chains, deep fork) — written BEFORE the parallel_group/file_conflicts changes, asserting current `depends_on`/`merge_order` output, then extended to assert `parallel_group` labels.
- `file_conflicts` derivation: two workstreams whose tasks' `**Files:**` lines name the same path → expected severity; a task block with no parseable `**Files:**` line → `scope_unknown: true`, empty conflicts.

---

## File: `scripts/hermes/schema.py`

### Surface / changes

- `WorkstreamsManifest`: add `scope_unknown: bool = False`. Parse in `parse_workstreams_json`; validate in `validate_manifest` (boolean type only).
- `Workstream.parallel_group`: docstring no longer says "V1: always None."
- No breaking change to existing fields. `validate_manifest` Rule 7 unchanged (already enforces parallel_group independence; now exercised with populated labels).

---

## File: `scripts/hermes/config.py`

### Surface / changes

- **Extend the existing `ConcurrencyConfig`** (audit M3) — `config.py` already defines `ConcurrencyConfig(max_parallel_sessions=3)`, wired into `load_config` and env-overridable via `HERMES_MAX_PARALLEL`, but dormant (never read by the executor). Do NOT add a second `Concurrency` dataclass.
- Reconcile naming: `max_parallel_workstreams` is the canonical "live sessions" knob — rename `max_parallel_sessions`→`max_parallel_workstreams` (updating the `HERMES_MAX_PARALLEL` binding and the `load_config` block at config.py:90/120), or keep one authoritative field aliased. Add `max_parallel_plans: int = 1`, `serialize_all: bool = False`, `serialize_high_severity: bool = True` to the same dataclass.
- **Flip the default from 3 to 1** so defaults reproduce today's sequential behavior (INV-5); document the default change. Wire through the existing `timeouts`/`retry`/`paths` env/file precedence pattern.

### Tests

- Defaults present; env/file override path; cap=1 is the default.

---

## File: `scripts/hermes-execute.py`

The core activation. Refactor in layered, individually-shippable steps.

### Surface / changes

1. **Extract `async def run_workstream(ws, state, config, ...) -> str`** — the entire per-workstream body (worktree create/reuse → spawn → monitor → merge) lifted out of the `for` loop verbatim, returning terminal status (`done` / `failed` / `skipped`). Pure refactor; behavior identical (INV-5).
2. **Level-aware scheduler.** Replace the single `exec_order` loop with a loop over **dependency levels**: repeatedly compute the set of workstreams whose `depends_on` are all `done`, run that level, advance. Source of truth = `depends_on` (INV-2), not `parallel_group`.
3. **Conflict-aware partition.** Within a ready level, partition into sub-batches such that no two workstreams in the same sub-batch share a `file_conflicts` entry whose `severity == "high"` (gated by `config.serialize_high_severity`). If `manifest.scope_unknown` or `config.serialize_all`, the partition is fully serial (batch size 1) — INV-4.
4. **Decouple monitoring.** Wrap the synchronous `poll_session(wt_path)` in `await asyncio.to_thread(poll_session, wt_path)` so a slow/stalled poll on one worktree cannot block sibling monitors. Each workstream's monitor is its own coroutine.
5. **Concurrency activation.** Run each sub-batch via `asyncio.gather(*[run_workstream(w) ...], return_exceptions=True)`, bounded by `asyncio.Semaphore(config.concurrency.max_parallel_workstreams)` **held for the full `run_workstream` lifetime via `async with sem:` (spawn → monitor → merge)** — NOT released right after spawn (audit M1: a spawn-only acquire bounds spawn rate, not live sessions, so all ready workstreams go live at once; and cap=1 — the only parity test — never exercises a contended semaphore, so a spawn-only placement passes every test while silently removing the bound at cap>1). `return_exceptions=True` so one crash doesn't cancel siblings; exceptions map to `status=failed`. cap=1 ⇒ exactly one live session ⇒ sequential (INV-5).
6. **Git GC safety.** Before spawning concurrent sessions, set `gc.auto=0` (and `GIT_OPTIONAL_LOCKS=0` in the spawn env) for the duration of the run to avoid concurrent auto-gc against the shared object store; restore on exit.
7. **Merge stays sequential.** After a level completes, merge its done workstreams in `merge_order` sequence (unchanged conflict handling). Cross-level ordering preserved.

### Behavior / edge cases

- SIGINT handler preserved; on cancel, gathered tasks are cancelled and worktrees left for recovery.
- Crash/retry/halt/pause semantics preserved per workstream (the existing monitor logic moves into `run_workstream` unchanged except for the `to_thread` wrap).
- Recovery (`attempt_recovery`) still re-reads state; already-`done` workstreams skipped; a level may be partially done on resume.
- A `failed` workstream blocks its dependents (they never become eligible) — surfaced in the final summary, not silently skipped.

### Tests

- `run_workstream` extraction: behavior-parity test vs a captured sequential golden (mocked session/worktree/merge).
- Level scheduler: deep-fork DAG schedules ws in correct level order; failed ws blocks dependents.
- Partition: HIGH-severity conflict pair never co-scheduled; `scope_unknown`/`serialize_all` ⇒ fully serial.
- Poll decoupling: one workstream with a hanging poll does not delay a sibling's progress detection beyond the poll interval.
- Concurrency: N=3 independent synthetic workstreams complete with cap=3; cap=1 reproduces sequential order. **Concurrency bound: cap=2 with ≥3 simultaneously-ready workstreams never has >2 live sessions at once (assert peak live-session count ≤ cap) — this is the test that catches a spawn-only semaphore placement.**

---

## File: cross-plan super-orchestrator (`scripts/hermes-execute.py` `--slugs` mode + helpers in `scripts/hermes/`)

### Surface / changes

- New invocation: `python3 scripts/hermes-execute.py --slugs=a,b,c` (mutually exclusive with `--slug`). Optional `--plan-set FILE` (newline/JSON list of slugs) for large sets.
- New module `scripts/hermes/cross_plan.py`:
  - `build_plan_conflict_graph(slugs) -> dict[slug, set[slug]]` — reads each plan's file scope from `active-plan-registry.py list --json` (and/or each plan's `workstreams.json` `file_conflicts`/`scope_unknown`). Two plans conflict iff their scope path-sets intersect, **or either plan has `scope_unknown`/low-confidence scope** (fail-safe, INV-4).
  - `acquire_plan_locks(slugs_sorted)` — acquires `plan-claim.sh` for each slug in **sorted ascending order** (INV-6), releasing all on any failure; returns held set.
  - Schedule: run scope-disjoint plans concurrently bounded by `max_parallel_plans`; serialize conflicting plans. Each plan internally runs the within-plan scheduler above.
- **Global merge mutex.** A single in-process lock serializes the final merge-to-base step across plans so two plans never `git merge` into the shared base concurrently (closes the cross-plan merge race the consultants flagged).

### Behavior / edge cases

- Missing registry entry for a slug ⇒ treat as `scope_unknown` ⇒ serialize against everything (fail-safe).
- A plan that fails does not abort scope-disjoint peers; its lock is released.
- Lock acquisition is deadlock-free by sorted ordering even if two super-orchestrators run.

### Tests

- Conflict graph: disjoint scopes ⇒ no edges; overlapping ⇒ edge; `scope_unknown` ⇒ edges to all.
- Lock ordering: two slug sets acquire in identical sorted order (no AB/BA deadlock).
- Scheduling: disjoint plans run concurrently (cap-bounded); overlapping serialized.
- Global merge mutex: concurrent plan completions merge one-at-a-time.

---

## File: `docs/human/hermes-integration-v1.md` (+ `docs/llm` concept)

- Bump to **v1.3**: `parallel_group` is now populated (derived level label); new `scope_unknown` manifest field; concurrency execution contract (depends_on-driven level scheduler, HIGH-severity serialization, cap config); cross-plan `--slugs` plan-set mode with registry-scope serialization and sorted-lock ordering; documented non-file shared-state limitation (ports/DB/remote sandboxes — serialize via `serialize_all`).
- Update `docs/llm/INDEX.json` + concept JSON for hermes orchestration so future `/z-plan` runs see the activated behavior.

## DRY / KISS / SOLID

- **DRY:** reuse `derive_severity()`, `validate_workstreams`/`validate_manifest`, `scope-extractor` output, `active-plan-registry.py`, and `plan-claim.sh` — no new lock or scope subsystem.
- **KISS:** depends_on is the only scheduling source of truth; `parallel_group` is a label, not a second mechanism; cap=1 collapses to the legacy path.
- **SOLID:** `run_workstream` (single responsibility) is extracted so the scheduler, partitioner, and concurrency layer compose over it; cross-plan logic lives in its own `cross_plan.py` module (open/closed — within-plan scheduler unchanged).
