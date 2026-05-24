# Decisions — plan-decompose  (re-framed as `/z-plan-split`)

Shape locked (Phase 2.5): pre-emptive scope splitter. Main thread proposes narrow scopes, user confirms, N parallel `cluster-planner` subagents produce one focused /z-plan-equivalent each, light reconciliation, exit. Reconciliation is secondary.

## D1. Split identification — how are narrow scopes named?

- **A.** User passes `--clusters="a,b,c"` flag explicitly.
- **B.** Main thread proposes 2-6 narrow scopes from the topic; user confirms/edits via `AskUserQuestion` with one-line previews. *(tentative — default)*
- **C.** B with A as override when `--clusters=` is passed.

Lean: **C**. Not consult-flagged.

## D2. `cluster-planner` agent — what phases does it run?

- **A.** Premise check + write SPEC/PLAN/TASKS only. No decision gate, no consult, no plan review. Fastest, weakest.
- **B.** A + light decision gate: if a non-obvious decision surfaces, return `STATUS: decision_needed` and let main thread handle sequentially. No per-leaf consult. *(tentative)*
- **C.** B + per-leaf cross-LLM consult on consult-flagged decisions.
- **D.** Mirror full /z-plan phases.

Lean: **B**. **Consult-flagged.** Narrow scope = few decisions; cross-LLM consult per leaf multiplies cost. Concern: a leaf might unilaterally make a wrong call on a borderline-non-obvious decision; root reconciliation may not catch it. Cross-LLM input on whether B is safe enough, or whether a per-leaf consult is worth the cost on borderline-complex leaves.

## D3. Reconciliation depth — what does main thread produce after leaves complete?

- **A.** File-path overlap only → write `SHARED-CONCERNS.md` listing detected overlaps as observations; do not auto-write a `shared/` plan. User can run `/z-plan --slug=<root>/shared/` manually if needed. *(tentative — keeps reconciliation passive)*
- **B.** File-overlap → auto-generate `shared/SPEC.md + shared/TASKS.md` scaffold (empty acceptance criteria); user fills via /z-plan later or marks acceptable as-is.
- **C.** File-overlap + cross-LLM semantic pass on all leaf SPECs.

Lean: **A**. **Consult-flagged.** Risk: if shared concerns are real and substantial, a passive note may not be enough. User has to know to act on it. Cross-LLM input on whether to push reconciliation toward active rewrites (B/C) or keep it as a flag-don't-fix observer.

## D4. Sub-plan failure semantics — if 1 of N leaves fails?

- **A.** Halt all, surface failure, user retries that cluster. *(tentative — matches /z-brainstorm 1/3-fail logic at lower threshold)*
- **B.** Continue with completed leaves, mark failed in manifest.
- **C.** Auto-retry once before halting.

Lean: **A**. Not consult-flagged.

## D5. Decision-gate propagation — if one leaf returns `STATUS: decision_needed`?

- **A.** Halt all leaves; sync point on user input. Loses concurrency.
- **B.** Halt only the affected leaf; sibling leaves continue. Main thread surfaces the gate to user via `AskUserQuestion` and re-spawns the affected leaf when resolved. *(tentative)*
- **C.** Defer all decision gates until all leaves complete; present as a batch to user.

Lean: **B**. Not consult-flagged. Cross-leaf concurrency preserved; the user resolves one gate while three other planners are still working.

## D6. Manifest format

- **A.** Top-level `z-harness/<root>/MANIFEST.md` listing clusters + paths + status (proposed | planning | done | failed).
- **B.** + `RUN-ORDER.md` defining explicit dep ordering between clusters for `/z-implement-all`.
- **C.** Both (one file).

Lean: **C**. Single `MANIFEST.md` with both listing and run-order section. Not consult-flagged.

## D7. `/z-implement-all` extension — how does it walk the nested tree?

- **A.** Existing slug-discovery extended: when it sees `z-harness/<slug>/MANIFEST.md`, recurse one level and walk clusters in MANIFEST run-order. *(tentative)*
- **B.** New `/z-implement-tree` command; existing `/z-implement-all` unchanged.
- **C.** Don't extend; user runs `/z-implement-all` per-cluster manually.

Lean: **A**. **Consult-flagged.** Risk: `/z-implement-all` is already complex; one more discovery rule is non-trivial. /z-implement-all's hard rules (skip markers, parallel batching, MAX_ATTEMPTS) interact with nested-slug walking in ways that need thought. Cross-LLM input on whether A or B has lower risk of behavioral regression.

## D8. Command naming — `/z-plan-split`

Locked at Phase 2.5 user gate. Not consult-flagged.

## D9. Input forms — v1 scope

- **A.** `/z-plan-split <topic>` (free-text only) for v1. *(tentative)*
- **B.** + `--from-audit=<slug>` + `--from-brainstorm=<slug>` flags in v1.

Lean: **A**. Not consult-flagged. v1 covers the common case; flag-based input chains are v2 (matches /z-brainstorm/research v1 simplicity).

## D10. Re-run on existing root slug

Existing slug dir prompt: overwrite / abort. (Drop "append" per T003 cycle 2 precedent.) Not consult-flagged.

## Summary

- 3 consult-flagged: **D2** (cluster-planner phases), **D3** (reconciliation depth), **D7** (/z-implement-all extension).
- 7 not consult-flagged: D1, D4, D5, D6, D8, D9, D10.
