---
artifact: brainstorm
slug: z-fix-hypothesis-driven
generated_at: 2026-05-24T05:53:33Z
command: /z-brainstorm i'm thinking of editing the idea of z-fix to be more like cursor's where the framework is identify a bunch of hypothesis -> test each hypothesis -> determine which one worked / iterate again. i want to be more disciplined so we have a fhigher chance that z-fix actually debugs/fixes issues. i still want to take advantage of the multi-llm idea of this project
input_hash: ef488e6932c6da25
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: codex
---

## Framing: claude

### Framing
The gap in current `/z-debug` is serial, low-N testing with no discrimination discipline. Fix: front-load a hypothesis-generation burst (N=5–8), design a discriminating test per hypothesis (one that **confirms if true AND refutes if false**), then run them in batch. Move the multi-LLM advantage **from the fix phase to the hypothesis-generation phase** — Claude, Codex, Gemini each generate independently, then the orchestrator merges and de-dupes.

### Core hypothesis
Introduce a mandatory `HYPOTHESES.md` registry with a strict schema: `{ claim, test, expected-if-true, expected-if-false, actual result, status: ACTIVE | CONFIRMED | ELIMINATED }`. You **cannot enter the fix phase** until every hypothesis has an entry filled in. LLM hypothesis generation happens independently per model before any cross-contamination, then orchestrator merges.

### Risks
- **False confirmation at scale.** At N=8, a single positive test result confirms a hypothesis is *consistent with* observed evidence — it does not prove root cause. This failure mode grows more dangerous as N grows, because the orchestrator is more likely to mistake "first to be supported" for "true."
- Schema rigidity may make the command feel heavyweight for trivial bugs.

### Plan implications
`<missing>` (ideator returned a meta-synthesis instead of a clean five-section block; this section was not recoverable)

### What would change my mind
`<missing>` (same — not recoverable from the meta-synthesis return)

---

## Framing: codex

### Framing
Make `/z-debug` less like a linear "debug then fix" workflow and more like an **evidence ledger**. The unit of progress shifts from "try an experiment" to `hypothesis → discriminating test → observed result → score update → eliminated/kept/refined`. That ledger is mandatory, explicit, and append-only. A run succeeds only when the final root cause is traceable through eliminated alternatives — not merely when a plausible fix passes tests. Multi-LLM moves from "ask two models what they think" to **adversarial structured roles**: one model generates, one attacks and asks what would falsify, orchestrator builds the matrix, then both rescore independently from real observations.

### Core hypothesis
`/z-debug` should become a **hypothesis tournament**. Require an initial pool of 6–10 hypotheses, grouped by failure class (input/state, boundary/time/order, integration contract, persistence/cache, concurrency/race, environment/config, recent-regression). Each row carries `{ prediction-if-true, prediction-if-false, cheapest discriminating test, expected signal strength, test cost, blast radius, parallel-safe? }`. Run a first batch of cheap tests **before touching production code** — the goal is not to prove the winner but to kill weak branches fast. Simple integer scoring (`+3/+1/0/-1/-3`), not Bayes theater; eliminate at ≤ −3, deepen at ≥ +3, refine inconclusive. Fix phase only opens when one hypothesis has both the strongest score AND a concrete causal mechanism explaining all known evidence.

### Risks
- **Ceremony.** A 10-row matrix for every small bug makes the command slower than ordinary engineering judgment.
- **False precision** from point scores — must distinguish "observed" vs "inferred," "test passed" vs "hypothesis supported."
- **Parallel test pollution.** Experiments that mutate state/logs/caches need explicit safety labels; parallelism without that creates misleading evidence.
- **Overfitting to available tests.** The cheapest test may be non-discriminating (same result under multiple hypotheses). Framework must reject such tests.
- **Multi-LLM convergence.** Same context + same framing → superficially diverse but structurally similar hypotheses. Consult prompts must assign roles, not ask both for "debug hypotheses."

### Plan implications
Phase redesign:
- **P1** problem statement (unchanged).
- **P2** repro + **evidence inventory** (symptoms, logs, failing tests, changed files, recent commits, env facts, unknowns).
- **P3** hypothesis generation — 6–10, explicitly diverse by failure class.
- **P4** **adversarial consult** — Codex + Gemini don't just rank; they add missing hypotheses, challenge weak ones, propose falsifying tests.
- **P5** test matrix construction — discriminating test written for every hypothesis **before** anything runs.
- **P6** batch isolation — safe independent tests in parallel, unsafe serially; record result per row.
- **P7** scoring loop — update ledger, eliminate/refine/deepen; hard cap "2 broad rounds + 1 deep round" instead of "3 cycles."
- **P8** fix gate — no fix until winning hypothesis explains the repro AND eliminated alternatives are documented.
- **P9** fix implementation via `/z-plan-light`; prompt receives the evidence ledger, not just root-cause summary.
- **P10** verification + post-mortem — at least one regression test tied to the winning hypothesis, plus one sanity check that the top eliminated alternative wasn't accidentally fixed by coincidence.

New artifact `DEBUG.md` / `FIX.md` with: Evidence Inventory, Hypothesis Pool, Discriminating Test Matrix, Experiment Log, Score Updates, Root Cause, Fix Plan, Verification, Post-mortem.

### What would change my mind
- Most real `/z-debug` cases are small obvious regressions where a 6–10 pool is drag, not discipline.
- Multi-LLM consults can't reliably produce genuinely different hypotheses (mostly duplicate) → drop to one local matrix + one adversarial pass.
- Users treat scoring numbers as truth → simplify to labels (`supported / contradicted / inconclusive / falsified`).
- Repo's test env is stateful enough that parallel experiments routinely contaminate evidence → drop parallelism.
- Primary failure mode is actually weak fix implementation, not bad diagnosis → put rigor in `/z-plan-light` and review, not hypothesis phase.

---

## Framing: gemini

### Framing
The current `/z-debug` pipeline operates sequentially and relies heavily on LLM intuition ("guess and check") — like a developer trying to remember what went wrong, rather than a scientist methodically eliminating variables. To get Cursor-like reliability, shift the framework from **verification** (prove an idea right) to strict **falsification** (prove it wrong). A persistent written probability state plus adversarial multi-LLM roles lets us run a "binary search" on the bug's root cause, eliminating entire classes of failure with single targeted tests.

### Core hypothesis
A formally tracked Bayesian-style **Diagnostic Matrix** coupled with adversarial multi-LLM roles will drastically increase fix success rates. Mechanics:
- **Divergent generation** — LLMs are prompted to generate *mutually exclusive* hypotheses (if Claude suspects data corruption, Gemini is forced to assume the data is perfect and hypothesize a rendering flaw). Yields 5–10 distinct hypotheses.
- **Adversarial falsification design** — for the top hypotheses, LLMs are asked: *"What is the cheapest, read-only command or script that will definitively DISPROVE this hypothesis?"* — not "how do we fix it."
- **The artifact `DEBUG_MATRIX.md`** — a literal file: `[Hypothesis] | [P(Truth)] | [Discriminating Test] | [Actual Result] | [Status: Active/Eliminated]`.
- **Execution loop** — tests batched; read-only/non-mutating run in parallel. Matrix updated with real results, eliminated rows struck out, probabilities updated until one root cause survives.

### Risks
- **Test design failure.** LLMs notoriously struggle to write truly discriminating read-only tests — may suggest abstract actions ("inspect the database") rather than executable scripts, stalling the loop.
- **State mutation & pollution.** A test that writes to the DB can't be parallel-safe; failed teardown pollutes the env for subsequent hypotheses.
- **Context exhaustion.** 10 hypotheses × bash scripts × stdout/stderr × multiple turns can blow the context window.
- **Overhead for trivial bugs.** A Bayesian matrix to fix a 15-second syntax error is a UX disaster.

### Plan implications
- **State management:** literal `DEBUG_MATRIX.md` file writing/updating step; CLI agent parses the file rather than relying on conversation history alone.
- **Consultant role expansion:** add new modes `generate-orthogonal` (forces divergence) and `design-falsifier` (writes negative tests) to `codex-consultant` and `gemini-consultant`.
- **Testing infrastructure:** safe test-runner sub-phase preferring ephemeral/dry-run executions to prevent state pollution.
- **Triage gate:** complexity-classifier early in the pipeline — if reproduction immediately isolates the bug to a single line with ≥95% confidence, **bypass the matrix entirely** and jump to the fix phase.

### What would change my mind
- Empirical runs show multi-LLM generation produces highly overlapping hypotheses → forced divergence is artificial and yields hallucinatory filler.
- LLMs structurally can't write zero-side-effect test scripts → test runner breaks the local workspace.
- Telemetry shows the primary agent's first hypothesis in current `/z-debug` is already correct >80% of the time → matrix + falsification loop is a solution in search of a problem.

---

## Anti-bias check

Section-by-section. Orchestrator is Claude, so each pick that favors the Claude ideator gets explicit justification.

| Section | Winner | Reason |
|---|---|---|
| **Framing** | Codex | "Evidence ledger / unit-of-progress shifts to `hypothesis → test → result → score → status`" is the sharpest single sentence describing the change. Gemini's "verification → falsification" is good and similar; Claude's "front-load generation, move multi-LLM to generation phase" is narrower and is essentially a subset of Codex's frame. |
| **Core hypothesis** | Codex (with one borrow from Gemini) | Codex spells out failure-class taxonomy, simple integer scoring (rejecting Bayes theater), explicit fix-gate ("strongest score AND concrete causal mechanism explaining all evidence") — most operationalizable. Gemini's *adversarial role differentiation* (Claude generates, Codex critiques discriminability, Gemini proposes overlooked alternatives) is a unique addition Codex doesn't have, and should be folded in. Claude's HYPOTHESES.md schema is good but a subset. |
| **Risks** | **Claude** (genuine win, with Codex close second) | **Justification for picking Claude (the same vendor as the orchestrator):** Only Claude's risk section explicitly names "false confirmation at scale" as a distinct failure mode — a positive test result is *consistent with* a hypothesis, not proof of root cause, and this gets worse as N grows. Codex and Gemini both flag related issues (overfitting to available tests, test design failure) but neither isolates this epistemological trap as its own named risk. Codex's "ceremony" and "false precision" risks are also strong and genuinely complementary. |
| **Plan implications** | Codex | Most concrete and immediately actionable: 10-phase rewrite with named artifact sections, "2 broad + 1 deep" replacing "3 cycles," explicit safety-label on parallel tests, regression test tied to winning hypothesis. Gemini's `generate-orthogonal` and `design-falsifier` new consultant modes are a unique contribution worth folding in. |
| **What would change my mind** | Three-way tie | Each adds one unique falsifier. Codex: "weak fixes not weak diagnosis is the real failure mode." Gemini: "first-hypothesis-already-correct >80%." Claude: `<missing>`. |

**Net:** Codex framing is the strongest skeleton. Gemini's adversarial role differentiation (per-LLM stance) and `design-falsifier` consultant mode should be folded in. Claude's "false confirmation at scale" risk should be a first-class entry in any planning doc that comes out of this.

## Orchestrator recommendation

**Codex framing**, with Gemini's per-LLM adversarial role differentiation and Claude's false-confirmation risk folded in. Rationale: evidence-ledger framing maps cleanly onto an artifact-first pipeline that this codebase already knows how to build (DECISIONS.md, SPEC.md, FIX.md), and the simple `+3/+1/0/−1/−3` scoring sidesteps the over-engineered Bayes failure mode that Gemini's version flirts with.

---

## User choice

Hybrid framing built on the Codex skeleton with the strongest mechanics from Gemini and the strongest risk-naming from Claude. User chose to fold in everything they liked, then layered two structural decisions on top: (a) **split** the command into `/z-fix` (light) and `/z-debug` (heavy) — matches this codebase's `/z-plan` vs `/z-plan-light` split and the user's "explicit commands over auto-detected modes" preference; (b) each command **recommends the other** when scope feels wrong, but no auto-routing / auto-escalation under the hood.

### Command split

- **`/z-fix`** — light path. User already has a diagnosis. Pipeline: capture problem + repro, single LLM sanity-check consult (*does this cause explain all observed symptoms?*), implement via existing `/z-plan-light` machinery, **non-negotiable Codex review**. ~4 phases. Early gate: if scope feels wrong (multiple unknowns, no clear hypothesis), exit with `"this looks like 3+ unknowns — recommend /z-debug"`.
- **`/z-debug`** — heavy hypothesis-tournament path. User does not yet know what's wrong. Early gate: if user already has a hypothesis they're confident in, exit with `"diagnosis is already in hand — recommend /z-fix"`.

### `/z-debug` pipeline (heavy)

1. **Problem statement + repro + evidence inventory** (same as today's P1+P2).
2. **Round 1 hypothesis generation — parallel, no contamination.** Claude / Codex / Gemini each independently propose 3–5 hypotheses. No model sees the others' outputs.
3. **Round 2 — adversarial.** Each model is shown the other two's lists and asked to do BOTH:
   - **Orthogonality hunt:** what failure mode is conspicuously *absent* from these lists? What would a different debugging tradition look here?
   - **Test-quality hunt:** critique the proposed discriminating tests — which are non-discriminating (would yield the same result under multiple hypotheses)? Which mutate state and can't run in parallel?
4. **Merge** with `proposed_by: [models]` and `overlap_count: N` tags per hypothesis.
5. **Test matrix construction** — every hypothesis gets a discriminating test written *before* anything runs. Schema per row: `{ claim, proposed_by, overlap_count, prediction_if_true, prediction_if_false, discriminating_test, cost: free|cheap|medium|expensive, parallel_safe: bool, prior_bucket }`.
6. **Ranking — consensus-first with forced outlier carve-out.**
   - Tests run in order of `overlap_count` descending (consensus = high prior = test first).
   - **But always** test the top 1–2 *outlier* hypotheses (unique to a single model) regardless of overlap. Mitigates LLM groupthink — the "everyone misses X" failure mode.
7. **Batch isolation.** Parallel-safe tests run in parallel; mutating tests serial. Record per-row result.
8. **Scoring — discrete Bayesian (ordinal, not floating-point).**
   - **Prior bucket** derived from `overlap_count`: `3 → high`, `2 → med`, `1 → low`.
   - **Likelihood bucket** from test result: `strongly_falsified | weakly_falsified | inconclusive | weakly_supported | strongly_supported`.
   - **Posterior** is an ordinal bucket from the combination (`high prior × strongly_supported → very_high`, etc.) via a fixed lookup table. No probabilities are written down — buckets only. This sidesteps the LLM-calibration trap that real numerical Bayes has.
9. **Loop:** eliminate `falsified` rows, deepen `very_high` rows, refine `inconclusive` rows; spawn new hypotheses if the pool collapses. Cap **3–5 isolation rounds** (vs current 3) since this is the heavy path.
10. **Fix gate.** No fix until the winning hypothesis has BOTH (a) the highest posterior bucket AND (b) a written causal mechanism that explains every piece of evidence in the ledger. Eliminated alternatives are listed with why each was killed.
11. **Fix implementation** via existing `/z-plan-light` machinery; prompt receives the full evidence ledger, not just the root cause.
12. **Verification + post-mortem.** At least one regression test tied to the winning hypothesis, **plus one sanity check** that the top eliminated alternative wasn't accidentally fixed by coincidence. Mandatory preventative analysis (kept from today's P7).

### Auto-bail

`/z-debug` only bails to `/z-plan` for true architectural rewrites (multi-module, new public API/schema, fix touches >5 files). It does **not** bail just because it needs more rounds — that's what the heavy path is for.

### Artifact

Single `DEBUG.md` with sections: Problem, Evidence Inventory, Hypothesis Pool, Test Matrix, Experiment Log, Score Updates, Eliminated Alternatives, Root Cause, Fix Plan, Verification, Post-mortem.

### Risks carried into planning (must not be lost)

- **False confirmation at scale** (Claude): a positive test result is *consistent with* a hypothesis, not proof of root cause. The fix gate's "causal mechanism explains all evidence" requirement directly addresses this.
- **Parallel test pollution** (Codex + Gemini): mutating tests must be explicitly labeled `parallel_safe: false` and run serially.
- **False precision from scoring** (Codex + Gemini): mitigated by ordinal buckets, no floating-point.
- **Context exhaustion** (Gemini): `DEBUG.md` is the source of truth, parsed each turn — orchestrator does not rely on conversation history alone.
- **Multi-LLM convergence / groupthink** (Codex + Gemini): mitigated by Round 2 adversarial generation AND the forced outlier carve-out in ranking.
- **Ceremony for trivial bugs** (Codex): mitigated by the command split — users who know their diagnosis pick `/z-fix` and skip the entire tournament.

### New consultant modes needed

- `generate-hypotheses-round1` — independent, no context from other models.
- `generate-hypotheses-round2-adversarial` — given other models' lists, hunt for missing failure modes + critique discriminating tests.
- (Existing `debug-hypotheses` and `light-fix` modes still used for ranking and fix consult.)
