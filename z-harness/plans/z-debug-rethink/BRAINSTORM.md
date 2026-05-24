---
artifact: brainstorm
slug: z-debug-rethink
generated_at: 2026-05-24T05:55:59Z
command: /z-brainstorm
input_hash: bc78a4efe1c358cf
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
chosen_framing: pending
---

## Framing: claude

### Framing

The core failure mode of current `/z-debug` is **serial, low-N hypothesis testing with no discrimination discipline**. You generate 2-3 hypotheses, rank them once, run one experiment per cycle, and hope the ranking was right. Cursor-style debugging breaks this by front-loading a hypothesis *generation burst* (N=5-8), then designing a **discriminating test** for each — one that confirms if true AND refutes if false — and running them in a batch before any code changes. The hypothesis that survives the most tests becomes the root cause; the others are formally eliminated and logged. The multi-LLM advantage here is not in the fix phase (where it already lives) but in the **hypothesis generation phase**: Claude, Codex, and Gemini each propose hypotheses independently, then the union is de-duped and scored, giving you a wider hypothesis space with less anchoring bias from any single model.

### Core hypothesis

The reason `/z-debug` underperforms is that it collapses **hypothesis enumeration**, **experiment design**, and **execution** into a single loosely-structured cycle, making it easy to skip steps under time pressure. The fix is a **Hypothesis Registry** — a structured artifact (`HYPOTHESES.md`) that for every candidate records: the claim, the discriminating test, expected outcome if true, expected outcome if false, and eventually the actual result + elimination reason. This registry is the forcing function: you cannot move to the fix phase until every hypothesis has either a `CONFIRMED` or `ELIMINATED` entry. The multi-LLM angle: dispatch Codex and Gemini independently to generate hypotheses *before* Claude sees the problem, then merge all three lists to get maximum coverage. Disagreements in hypothesis ranking are surfaced explicitly, not silently resolved by the orchestrator's prior.

### Risks

- **Wall-time blowout.** Going from 2-3 serial experiments to 5-8 parallel ones sounds faster but the *setup* cost per hypothesis (designing a discriminating test) is non-trivial. For simple bugs, this overhead drowns the signal. Need a "light" vs "full" mode, or auto-detection of complexity.
- **Parallel test interference.** Running 5+ experiments simultaneously can corrupt shared state (DB, filesystem, network mock). The registry pattern assumes tests are independent; in practice they often aren't. Need an explicit "interference check" gate before parallel dispatch.
- **Hypothesis explosion at the LLM seam.** Three LLMs each generating 3-5 hypotheses gives you 9-15 candidates before de-dup. De-duplication itself requires semantic reasoning, not just string matching. If this step is lossy, you get duplicate experiments or missed merges.
- **False confirmation.** A discriminating test that confirms a hypothesis doesn't prove root cause — it proves the hypothesis is *consistent with* the evidence. The current pipeline has the same flaw but it's less dangerous when N is small. At N=8, a false confirmation early in the batch can misdirect the fix.
- **Scope creep into /z-plan territory.** A rigorous multi-hypothesis registry process is essentially a mini scientific method. For bugs that are genuinely localized, this is overkill and will push users to bypass the command entirely.

### Plan implications

- Rename the command `/z-fix` or keep `/z-debug` — either way, the *architecture* needs a new core artifact: `HYPOTHESES.md` with a mandatory schema (claim, test, expected-if-true, expected-if-false, actual-result, status: ACTIVE | CONFIRMED | ELIMINATED).
- Phase 3 becomes: **multi-LLM hypothesis burst** — dispatch Claude (inline), Codex, Gemini each to generate hypotheses independently with no cross-contamination, then merge and de-dup.
- Phase 4 becomes: **discriminating test design** — for each surviving hypothesis, design the cheapest test that would confirm OR refute (not just probe).
- Phase 5 becomes: **batch experiment execution** — run all non-interfering tests in parallel; serialize interfering ones with explicit ordering.
- New Phase 5b: **scoring + elimination** — update the registry; any hypothesis without a clear CONFIRMED requires a reason for ELIMINATED.
- The existing auto-bail thresholds (>5 files, >3 cycles) still apply but the cycle count should reset on a new hypothesis batch.
- A `--fast` flag that collapses back to the current 2-3 hypothesis flow for obviously localized bugs.

### What would change my mind

- Evidence that the hypothesis-generation step is already the bottleneck (i.e., the current 2-3 hypotheses are always sufficient and the real failure is in experiment quality, not enumeration breadth) — in which case the better fix is improving *test design* per hypothesis, not increasing N.
- User feedback that the command is already too heavyweight and a heavier process would get bypassed in favor of ad-hoc debugging — the right solution might be a lighter forced-discipline prompt rather than a full registry.
- A pattern where the bugs hitting `/z-debug` are reliably architectural (better suited for `/z-plan`) rather than localized — suggesting the real gap is better triage at intake, not a better hypothesis loop.

---

## Framing: codex

### Framing

`/z-debug` should stop feeling like "structured debugging" and start feeling like a small experimental science loop.

The current shape still has a hidden sequential bias: rank hypotheses, pick one, test, loop. Cursor-style debugging works better because it treats uncertainty as the primary object. The artifact should not be "we investigated X"; it should be a visible hypothesis table where every row has:

- Claim
- Prediction
- Discriminating test
- Result
- Confidence delta
- Status: alive / weakened / refuted / confirmed / needs new test

The key shift is from "find the likely cause" to "reduce the search space aggressively."

### Core hypothesis

The right redesign is a **Hypothesis Tournament**.

At the start of `/z-debug`, generate a larger hypothesis set (5-8) across distinct failure classes:

- environment/config
- state/input shape
- dependency/API contract
- ordering/timing
- persistence/cache
- UI/rendering
- regression from recent diff
- test/repro flaw

Then require each hypothesis to include one discriminating test before any debugging starts. A test only qualifies if it can meaningfully distinguish that hypothesis from at least one other plausible hypothesis.

Multi-LLM should be used less as "ask for advice" and more as **adversarial experimental design**:

- Claude proposes hypotheses and tests.
- Codex critiques test discriminability and implementation feasibility.
- Gemini proposes overlooked hypotheses and alternative explanations.
- Orchestrator merges, deduplicates, and scores.

The loop becomes:
1. Build hypothesis matrix.
2. Design tests.
3. Batch cheap tests first.
4. Score evidence.
5. Drop refuted branches.
6. Generate second-round hypotheses only from remaining ambiguity.
7. Fix only after confidence crosses a threshold or one hypothesis clearly dominates.

### Risks

- **Ritualization into bureaucracy.** If every small bug requires an eight-row matrix and three consultants, `/z-debug` becomes too heavy and people avoid it.
- **False precision.** Confidence scores can look scientific while still being vibes. The framework should force qualitative labels plus evidence, not pretend exact probabilities are meaningful.
- **Test explosion cost model.** Some hypotheses are cheap to test, others require invasive instrumentation. The command needs a cost model: free (inspect logs, grep, run existing tests) / cheap (add temporary logging, run targeted test) / medium (write repro test, isolate dependency) / expensive (build harness, bisect, instrument subsystem).
- **LLM convergence.** If all consultants see the same framing, they may generate superficially different but semantically identical hypotheses. The prompts should intentionally assign different stances, not just ask all models the same question.

### Plan implications

`ISOLATION.md` should become `HYPOTHESES.md` or contain a required hypothesis ledger:

```md
# Hypothesis Ledger

| ID | Hypothesis | Prediction | Test | Cost | Result | Delta | Status |
|----|------------|------------|------|------|--------|-------|--------|
| H1 | ... | ... | ... | cheap | ... | down | refuted |
```

New sub-phases:

- **P3a: Hypothesis Generation** — Generate 5-8 hypotheses across failure classes.
- **P3b: Test Design** — Require one discriminating test per hypothesis.
- **P3c: Multi-LLM Challenge** — Consultants critique missing hypotheses, weak tests, and premature convergence.
- **P4: Batch Evidence** — Run all cheap/parallel tests before choosing a branch.
- **P5: Evidence Update** — Score results, eliminate hypotheses, decide whether to iterate or fix.

Auto-bail criteria should expand beyond "3 isolation cycles" to include: no hypothesis confidence above threshold after 2 rounds; all remaining tests are expensive; root cause spans more than expected module boundary.

The fix phase should require a final statement: "Root cause accepted because: H3 predicted A, B, C. Tests T3.1 and T3.2 matched. H1/H2/H5 were refuted by X."

### What would change my mind

- If most `/z-debug` failures are caused by insufficient reproduction rather than weak hypothesis discipline, the redesign should focus on repro hardening rather than hypothesis matrices.
- If logs show real fixes usually emerge within the first one or two hypotheses, expanding N may be wasteful — the better move is stricter discriminating tests for the top 3.
- If multi-LLM consults mostly duplicate the orchestrator's ideas, move them later: let the local agent generate the matrix first, then use other models only to attack it.
- If users find confidence scoring annoying or performative, replace numeric scoring with a simpler lifecycle: alive / weakened / refuted / leading / confirmed.

---

## Framing: gemini

### Framing

The current `/z-debug` pipeline, while structured, relies too heavily on a linear "guess and check" approach driven by the primary LLM's initial intuition. By treating debugging as a sequential path rather than a scientific process of elimination, we risk falling into rabbit holes or applying hallucinated fixes. To dramatically increase the success rate, we must transition to a rigorous **"generate, isolate, eliminate"** framework (inspired by Cursor's methodologies), treating debugging as an empirical science powered by a Bayesian multi-LLM engine.

### Core hypothesis

If we enforce a strict separation between hypothesis generation and test execution, and require our multi-LLM fleet (Claude, Codex, Gemini) to independently generate a wide matrix of hypotheses *and specific discriminating tests* (tests designed to exclusively prove or disprove a single hypothesis), we can execute these tests in batch/parallel. This scientific elimination process will drastically reduce time-to-fix, eliminate "shotgun debugging," and leverage the diversity of the LLMs to cover blind spots the primary orchestrator might miss.

### Risks

- **State Pollution.** Running multiple diagnostic tests in parallel or rapid sequence could corrupt local workspace state, leading to false negatives/positives if tests are not perfectly isolated or stateless.
- **Discriminating Test Difficulty.** LLMs may struggle to write tests that are truly *discriminating*. They might generate overlapping tests that fail to definitively isolate a single root cause, leading to ambiguous results matrices.
- **Execution Overhead.** Wall-clock time required to compile, spin up environments, and run a batch of 5-10 tests could exceed the 30-minute target if not carefully parallelized or mocked.
- **Combinatorial Explosion.** Asking three LLMs for 3-5 hypotheses each yields up to 15 hypotheses. Managing deduplication and synthesis of this matrix without overwhelming the context window is technically challenging.

### Plan implications

- **Phase 3 (Hypothesize) Overhaul:** LLMs must output a structured tuple: `[Hypothesis, Discriminating Test Script, Expected Result]`.
- **Phase 4 (Consult) Shift:** Cross-LLM consultation must focus on deduplicating hypotheses and validating *quality of tests*, rather than just ranking hypotheses.
- **Phase 5 (Isolate) Overhaul:** Becomes a "Batch Execution Engine." Instead of picking one hypothesis and running an experiment, run all validated discriminating tests, score the results matrix, and mathematically eliminate invalid hypotheses before looping back or proceeding to fix.
- **Artifact Changes:** `ISOLATION.md` must be replaced or augmented with a strict `HYPOTHESIS_MATRIX.md` tracking the lifecycle (Generated → Tested → Eliminated/Confirmed) of every idea.

### What would change my mind

- If overhead of writing and executing multiple diagnostic tests consistently takes longer than simply asking the LLM to write a speculative fix and running the existing test suite.
- If the multi-LLM setup consistently generates identical hypotheses, proving that querying Codex and Gemini alongside Claude yields no actual diversity in root-cause analysis.
- If workspace state pollution during parallel test execution proves too complex to manage without implementing full containerized sandboxing for every test run.

---

## Anti-bias check

**Section-by-section comparison:**

**Framing:**
All three framings agree on the core diagnosis: the current pipeline is sequential and low-N, and needs a "generate a wide set, test discriminatingly, eliminate formally" loop. The differences are in emphasis: Claude focuses on the multi-LLM gap being in the generation phase (not just fix phase); Codex frames it as "treat uncertainty as the primary object" with a visible table artifact; Gemini frames it as an empirical science / Bayesian engine. *Codex wins on Framing*: its "reduce the search space aggressively" framing is the sharpest and most actionable, and its hypothesis-table artifact specification is concrete without being prescriptive. (Claude does not win this dimension — Claude's framing is accurate but slightly longer and less crisp. No justification needed for not picking Claude.)

**Core hypothesis:**
Claude proposes a Hypothesis Registry artifact as the forcing function with no-move-to-fix-without-CONFIRMED-entry. Codex proposes a Hypothesis Tournament with LLM roles differentiated (Claude generates, Codex critiques discriminability, Gemini attacks with overlooked hypotheses). Gemini proposes structured `[Hypothesis, Test Script, Expected Result]` tuples as output format from all LLMs. *Codex wins on Core hypothesis*: the role differentiation among LLMs is the boldest multi-LLM insight in this section and is unique to Codex. Claude's registry is solid but operationally weaker than Codex's adversarial framing. (Claude does not win — no justification required since Codex won by concrete differentiation.)

**Risks:**
Claude surfaces false-confirmation risk (a discriminating test confirms but doesn't prove root cause, increasingly dangerous at N=8), parallel test interference, hypothesis de-dup requiring semantic reasoning, and scope-creep. Codex surfaces false precision / confidence theater and LLM convergence (same framing = same hypotheses). Gemini surfaces combinatorial explosion context window pressure. *Claude wins on Risks*: the false-confirmation-at-scale risk is the most underappreciated failure mode and is unique to Claude's section. Codex's LLM convergence risk is also important and appears nowhere in Claude's list. **Justification for Claude winning Risks:** Claude is the only ideator to name false confirmation as a distinct failure mode from false refutation, which is the core epistemological problem with running many tests and trusting any single positive.

**Plan implications:**
All three propose a HYPOTHESIS_MATRIX or HYPOTHESES.md artifact and a batch-execution phase. Codex adds the cost-tiering sub-model (free/cheap/medium/expensive) and the auto-bail expansion beyond cycle count. Claude adds the `--fast` flag idea and per-hypothesis expected-if-true / expected-if-false fields. Gemini adds the Phase 3 output tuple format. *Codex wins on Plan implications*: the cost-tier model for test execution is the most practically useful addition missing from the other two, and the expanded auto-bail criteria are more nuanced than the current cycle count gate.

**What would change my mind:**
All three list overlapping points: if repro is the real bottleneck (not hypothesis discipline), if LLMs converge anyway, if overhead exceeds benefit. Claude uniquely raises the architectural-triage angle (better intake sorting). Codex uniquely raises: if users find scoring performative, use a lifecycle label instead of a number. Gemini uniquely raises: if parallelism requires containerized sandboxing. *Three-way tie on this section* — each adds one unique data point the others miss.

**Summary:** Codex wins Framing, Core hypothesis, and Plan implications. Claude wins Risks. Three-way tie on What would change my mind.

## Orchestrator recommendation

**Codex framing** — its adversarial multi-LLM role differentiation (generate → critique discriminability → attack with overlooked hypotheses → merge) is the sharpest operationalization of the multi-LLM advantage, and its hypothesis-as-tournament mental model maps directly to a concrete pipeline redesign without over-engineering the artifact format.

The Claude Risks section should be pulled into whichever framing advances to planning, as it surfaces the false-confirmation-at-scale and semantic-dedup risks that are absent from the Codex framing.
