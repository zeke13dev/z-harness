# Bundled Decisions Consultation: `/z-plan-split` Command

## Mode
Bundled decisions consultation for a new z-harness slash command `/z-plan-split`.

## Context

**What is `/z-plan-split`?**
A pre-emptive scope splitter that catches "the topic is too big for one /z-plan" BEFORE /z-plan starts.

Main thread flow:
1. User: `/z-plan-split <topic>`
2. Main thread proposes 2-6 narrow scopes via AskUserQuestion
3. User confirms or edits scope boundaries
4. N parallel `cluster-planner` subagents each produce a full SPEC/PLAN/TASKS for one scope
5. Main thread light reconciliation (file-overlap detection)
6. Write MANIFEST, exit

**Existing patterns in z-harness:**
- `/z-plan` (9 phases: premise → exploration → decisions → consult → SPEC/PLAN → review → TASKS → finalize → archive): runs against one task from premise to deliverables, with cross-LLM consult on borderline decisions
- `/z-brainstorm` (3 parallel ideators, 1 anti-bias check): cheap pre-planning, no decision gates, no per-leaf consult
- `/z-implement-all` (parallelized task dispatch, skip markers, hard attempt/wall-clock caps, halt on blockers)

**Subagents available:**
- `cluster-planner` (new; variant of z-plan)
- `spec-precheck` (existing; lightweight syntax/consistency check)
- `codex-consultant` (existing; cross-LLM consult on flagged decisions)
- `codex-reviewer` (existing; code review + SPEC compliance)
- `remote-runner` (existing; remote task execution)

---

## Decision 1: D2 — `cluster-planner` phases

### The options
- **A:** Premise check + write SPEC/PLAN/TASKS only. No decision gate, no consult. (Fastest, weakest.)
- **B:** A + light decision gate: if non-obvious decision surfaces, return `STATUS: decision_needed` and let main thread handle. No per-leaf consult. (Tentative.)
- **C:** B + per-leaf cross-LLM consult on consult-flagged decisions.
- **D:** Mirror full /z-plan phases.

### The concern
Narrow scopes typically have 0-1 non-obvious decisions. But a leaf might unilaterally make a wrong call on a borderline decision; root reconciliation won't catch it.

### Constraint context
- `/z-brainstorm` uses N=3 parallel cheap ideators (no decision gates, no consult) — cost target ≤200K tokens total
- `/z-plan` runs ONE task end-to-end with cross-LLM consult for flagged decisions (expensive but rigorous)
- `/z-implement-all` caps attempts (MAX_ATTEMPTS=2) and has hard skip markers to catch unrecoverable failures early
- Narrow scope = reduced surface area, but `cluster-planner` is still a full spec-to-tasks pipeline

### Your reasoning should address
1. Is decision-gating (B) enough to catch wrong calls, or does a leaf need per-leaf consult (C)?
2. Cost: how many parallel `cluster-planner` runs × decision gate cost vs. per-leaf consult cost?
3. Precedent: `/z-brainstorm` skips decisions entirely for cheap parallelism; `/z-plan` does full consult serially. Where does `/z-plan-split` fit?
4. Risk: what happens if a leaf returns decision_needed, main thread resolves it, but the leaf was wrong about its scope — does reconciliation catch that?

---

## Decision 2: D3 — Reconciliation depth

### The options
- **A:** File-overlap only → write `SHARED-CONCERNS.md` as observations; do not auto-write `shared/` plan. User runs `/z-plan --slug=<root>/shared/` manually if needed. (Tentative; passive observer.)
- **B:** File-overlap → auto-generate `shared/SPEC.md + shared/TASKS.md` scaffold (empty acceptance criteria); user fills via /z-plan later or marks acceptable as-is.
- **C:** B + cross-LLM semantic pass on all leaf SPECs.

### The concern
If shared concerns are real and substantial, a passive note may not be enough. User has to know to act on it.

### Constraint context
- `/z-plan` is single-scope: one SPEC/PLAN/TASKS per run
- `/z-implement-all` detects file-overlap between concurrent tasks and defers one; no reconciliation (assumes single TASKS.md)
- `/z-plan-split` produces N leaf SPECs that may touch overlapping files (e.g., both define schema migrations, both touch a shared config module)
- Main thread is already light (no code generation, just orchestration)

### Your reasoning should address
1. What does "file-overlap" mean here? Same file in two leaf SPEC "Files:" blocks, or semantic overlap (both touch version numbers)?
2. If passive (A), how does user know to reconcile? Will they miss overlaps because SHARED-CONCERNS.md is just a note?
3. If active scaffold (B), what does "empty acceptance criteria" mean — does it block /z-implement-all until filled?
4. Cost: is cross-LLM semantic pass (C) worth the overhead, or does careful (B) catch 90% of issues?
5. Precedent: `/z-brainstorm` has no reconciliation (cheap). `/z-plan` doesn't parallelize scopes. `/z-implement-all` halts on conflict. Should `/z-plan-split` lean passive or active?

---

## Decision 3: D7 — `/z-implement-all` extension

### The options
- **A:** Extend existing slug-discovery: when `/z-implement-all` sees `z-harness/<slug>/MANIFEST.md`, recurse one level and walk clusters in MANIFEST run-order. (Tentative.)
- **B:** New `/z-implement-tree` command; `/z-implement-all` unchanged.
- **C:** Don't extend; user runs `/z-implement-all` per-cluster manually.

### The concern
`/z-implement-all` is already complex: skip markers, parallel batching (N=3 tasks), MAX_ATTEMPTS caps, halt taxonomy, per-task precheck/review. One more discovery rule (nested slug + MANIFEST) is non-trivial.

### Constraint context
- `/z-implement-all` current flow:
  - Enumerate `z-harness/*/TASKS.md` (or legacy `z-harness/TASKS.md`)
  - One candidate → use it; multiple → ask user; zero → abort
  - Read TASKS.md once, iterate: pick eligible task → precheck → implement → review → mark done
  - Hard caps: MAX_ATTEMPTS=2, MAX_TASK_WALL_MS=45min, MAX_BATCH_STALL_MS=30min, MAX_DISTINCT_HALTS=3
  - Skip markers: REMOTE, REMOTE-ONLY, qt-bot-remote, manually, after <N>h/d/w, wall-clock, **SKIP: …**
- If `/z-plan-split` produces `z-harness/<root>/MANIFEST.md` + `z-harness/<root>/<cluster1>/TASKS.md` + `z-harness/<root>/<cluster2>/TASKS.md`, how should `/z-implement-all` consume it?

### Your reasoning should address
1. Scope explosion: if user nests `/z-plan-split` on a `/z-plan-split` result (meta-split), does (A) handle arbitrary depth or just one level?
2. Manifest format: is a MANIFEST entry enough to locate and validate a leaf's SPEC/PLAN/TASKS, or will orchestrator burn tokens discovering them?
3. Run-order dependency: MANIFEST has explicit run-order between clusters (B from decisions.md D6). Does (A) need to parse and enforce that, or is it advisory?
4. Skip marker interaction: does MANIFEST have skip markers, or only leaf TASKS.md? If both, which wins?
5. Precedent: `/z-implement-all` already de-dupes file conflicts (see parallel batching rule 2). Is cluster-level file-conflict dedup needed on top, or is task-level enough?
6. Cost: slug-discovery already enumerates `z-harness/*/`, so checking for MANIFEST.md is cheap. But one-level recursion + manifest parsing + run-order enforcement adds state. Is (A) worth it vs. (B/C)?

---

## Cross-decision interactions to flag

**D2 → D3:** If cluster-planner returns decision_needed (D2-B), main thread waits for user input. Does this decision get archived in SHARED-CONCERNS.md for visibility, or is it only recorded in the cluster's local decision log?

**D3 → D7:** If main thread auto-generates shared/SPEC.md + shared/TASKS.md (D3-B), does `/z-implement-all` (D7) see it as a pseudo-cluster and try to implement it? Or is shared/ explicitly marked skip?

**D2 + D3:** If D2=A (no decision gates) and D3=A (passive reconciliation), does the system rely entirely on user diligence to review SHARED-CONCERNS.md and MANIFEST before running `/z-implement-all`? Or should there be an interstitial `/z-plan-split-review` step?

**D7 + existing z-implement-all:** If a cluster fails (D4-A halt semantics), does `/z-implement-all` (D7-A) halt the parent run or just that cluster's tasks?

---

## Ask

For each consult-flagged decision (D2, D3, D7):
1. Recommend an option with reasoning
2. Tradeoffs and risks
3. Missed considerations
4. Interactions with other decisions

Keep recommendations concise (2-4 sentences per decision).
