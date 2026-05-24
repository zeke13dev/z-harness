## (1) Framing

The key change is to make `/z-debug` less like a linear "debug then fix" workflow and more like an evidence ledger.

Today's pipeline has hypothesis-driven moments, but the unit of progress is still "try an experiment." The revised unit should be:

`hypothesis -> discriminating test -> observed result -> score update -> eliminated/kept/refined`

That ledger should be mandatory, explicit, and append-only. A debug run succeeds only when the final root cause is traceable through eliminated alternatives, not merely when a plausible fix passes tests.

The multi-LLM angle should not be "ask two models what they think." It should be adversarial and structured:

- One model generates broad hypotheses.
- One model attacks them and asks what evidence would falsify each.
- The orchestrator converts that into a test matrix.
- After evidence comes back, both models independently rescore the matrix.
- The orchestrator resolves disagreement based on actual observations, not model confidence.

## (2) Core hypothesis

`/z-debug` should become a hypothesis tournament.

Instead of 2-3 ranked hypotheses, require an initial pool of 6-10 hypotheses, grouped by failure class:

- input/state assumptions
- boundary/time/order issues
- integration/API contract mismatch
- persistence/cache/session issues
- concurrency/race/lifecycle issues
- environment/config/tooling issues
- recent-regression candidates

Each hypothesis must include:

- prediction if true
- prediction if false
- cheapest discriminating test
- expected signal strength
- test cost
- blast radius
- whether it can run in parallel

Then run a first batch of cheap tests before touching production code. The goal is not to prove the winner immediately; it is to kill off weak branches quickly.

Use a simple scoring model, not elaborate Bayes theater:

```text
+3 strong supporting evidence
+1 weak supporting evidence
 0 inconclusive
-1 weak contradictory evidence
-3 strong falsifying evidence
```

After each batch:

- eliminate hypotheses at `<= -3`
- deepen hypotheses at `>= +3`
- refine or split inconclusive hypotheses
- require a written reason before keeping any hypothesis with no supporting evidence

The fix phase only opens when one hypothesis has both:

- strongest score
- a concrete causal mechanism explaining all known evidence

## (3) Risks

The biggest risk is ceremony. If every small bug requires a 10-row matrix, `/z-debug` becomes slower than ordinary engineering judgment.

The second risk is false precision. Point scores can make weak evidence feel rigorous. The framework must distinguish "observed" from "inferred," and "test passed" from "hypothesis supported."

The third risk is parallel test pollution. Some debugging experiments mutate state, logs, caches, fixtures, or local data. Parallelism needs a safety label, otherwise the framework can create misleading evidence.

The fourth risk is overfitting to available tests. The easiest tests may be cheap but nondiscriminating. The command should reject tests that would produce the same result under multiple hypotheses.

The fifth risk is multi-LLM convergence. If Codex and Gemini see the same context and same framing, they may produce superficially diverse but structurally similar hypotheses. The consult prompts should deliberately assign roles, not just ask both for "debug hypotheses."

## (4) Plan implications

The current phases would change materially:

P1 stays: problem statement.

P2 becomes: repro + evidence inventory. Capture symptoms, logs, failing tests, changed files, recent commits, environment facts, and unknowns.

P3 becomes: hypothesis generation. Produce 6-10 hypotheses, explicitly diverse by failure class.

P4 becomes: adversarial consult. Codex and Gemini do not merely rank; they must add missing hypotheses, challenge weak ones, and propose falsifying tests.

P5 becomes: test matrix construction. For every hypothesis, write the discriminating test before running anything.

P6 becomes: batch isolation. Run all safe independent tests in parallel. Run unsafe tests serially. Record result per hypothesis.

P7 becomes: scoring loop. Update the ledger, eliminate, refine, or deepen. Repeat with a hard cap such as 2 broad rounds plus 1 deep round, rather than "3 isolation cycles."

P8 becomes: fix gate. No fix until the winning hypothesis explains the repro and the eliminated alternatives are documented.

P9 becomes: fix implementation via `/z-plan-light`, but the fix prompt receives the evidence ledger, not just the root cause summary.

P10 becomes: verification and post-mortem. Verification must include at least one regression test tied directly to the winning hypothesis, plus one sanity check proving a top eliminated hypothesis was not accidentally fixed by coincidence.

The main artifact should probably be `DEBUG.md` or `FIX.md` with sections like:

```text
Evidence Inventory
Hypothesis Pool
Discriminating Test Matrix
Experiment Log
Score Updates
Root Cause
Fix Plan
Verification
Post-mortem
```

## (5) What would change my mind

I would back away from the full tournament model if most real `/z-debug` cases are small, obvious regressions where a 6-10 hypothesis pool creates drag without improving outcomes.

I would also change direction if the multi-LLM consults cannot reliably produce genuinely different hypotheses. If they mostly duplicate each other, the better move is one strong local hypothesis matrix plus a single adversarial review pass.

I would simplify the scoring system if users treat numbers as truth instead of shorthand. In that case, use labels only: `supported`, `contradicted`, `inconclusive`, `falsified`.

I would reduce parallel testing if the repo's test environment is stateful enough that parallel experiments frequently contaminate evidence.

I would keep the current `/z-debug` shape if the primary failure mode is not bad diagnosis, but weak fix implementation. In that case the rigor belongs more in `/z-plan-light` and review, not in the hypothesis phase.
