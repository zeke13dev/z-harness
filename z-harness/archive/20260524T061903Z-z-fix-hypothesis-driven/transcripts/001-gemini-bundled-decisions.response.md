Ripgrep is not available. Falling back to GrepTool.
Here are the recommendations for the five consult-flagged decisions, formatted for the `bundled-decisions` mode.

## D2: Presentation of hypothesis-posterior evolution

**Recommendation:** Single unified `DEBUG.md` (combining hypotheses, isolation logs, and posteriors).
**Reasoning:** While the tentative pick suggested a separate `MATRIX.md`, your brainstorm's User Choice explicitly settled on a "Single `DEBUG.md` with sections: Problem, Evidence Inventory, Hypothesis Pool, Test Matrix, Experiment Log, Score Updates..." A unified file acts as a continuous evidence ledger. This prevents context fragmentation when the LLM must eventually write a causal mechanism that explains *all* evidence.
**Tradeoffs:** The file will grow significantly, risking context window exhaustion over the 3–5 cycles of a heavy `/z-debug` run.
**Additional considerations (D2 ↔ D5 Interaction):** If using a unified `DEBUG.md`, the orchestrator must surgically extract just the "Test Matrix" and "Score Updates" sections when feeding context to the Round 2 adversarial mode (D5), rather than passing the entire file, to mitigate context bloat.

## D3: Posterior calculation rule

**Recommendation:** Adopt the tentative pick ("strongly_falsified eliminates; strongly_supported promotes by 2 buckets; inconclusive preserves but caps below very_high"), but enforce it via a fixed deterministic lookup table.
**Reasoning:** This rule perfectly enforces the strict falsification requirement (one strong refutation kills the hypothesis permanently) while forcing hypotheses with low priors to accrue multiple confirming tests before crossing the threshold (`very_high`) required to open the fix gate.
**Tradeoffs:** A correct hypothesis that started with a low prior will require multiple test cycles to reach `very_high`, increasing the wall-clock time of the run.
**Additional considerations (D3 ↔ D4 Interaction):** The prompt notes, "Each LLM round generates a likelihood." If D4 dictates 3 LLMs, having 3 LLMs independently interpret a test result creates a consensus bottleneck. I strongly recommend that **only the orchestrator** interprets the raw test execution output to assign the single likelihood bucket. The 3 LLMs (D4) establish the *prior* (via overlap count in Round 1); the orchestrator alone evaluates the test output to set the likelihood, avoiding D3/D4 deadlock.

## D4: Cross-LLM tournament cardinality and checkpoint

**Recommendation:** 3 LLMs (Claude, Codex, Gemini) with orchestrator checkpoint before parallel dispatch.
**Reasoning:** The brainstorm's prior calculation (`3 overlap → high prior, 2 → med, 1 → low`) fundamentally depends on exactly 3 LLMs. Reducing cardinality to 2 destroys the 'medium' prior bucket and breaks the distribution. The checkpoint is structurally sound and protects against API flakes during the expensive generation bursts.
**Tradeoffs:** Higher API token consumption and increased latency compared to a single-LLM approach.
**Additional considerations:** As mandated by the brainstorm, you must ensure the orchestrator always tests the top 1–2 outlier hypotheses (overlap=1) early to prevent LLM groupthink from permanently burying correct but unconventional diagnoses.

## D5: Consultant agent mode signatures

**Recommendation:** Two new modes (`generate-hypotheses-round1` and `generate-hypotheses-round2-adversarial`).
**Reasoning:** The inputs and objectives for these phases are materially different. Round 1 requires zero cross-contamination. Round 2 requires the orchestrator to inject the Round 1 lists and explicitly instruct the LLMs to hunt for orthogonality and critique test discriminability. A single parameterized mode would dilute these strict behavioral boundaries and complicate the prompt.
**Tradeoffs:** Adds slight boilerplate to the consultant markdown files, but this is a low-cost, one-time maintenance burden.
**Additional considerations:** The Round 2 adversarial prompt must explicitly forbid the consultant from just "agreeing" with the other lists; it must structurally mandate the proposal of a failure class absent from the provided context.

## D8: Post-mortem requirement after /z-fix

**Recommendation:** Optional default-off.
**Reasoning:** `/z-fix` is explicitly designed as the lightweight, <10-minute path for when the user already has a high-confidence diagnosis. Enforcing a post-mortem adds unnecessary ceremony that violates the core value proposition of a fast-track fix.
**Tradeoffs:** You lose automatic preventative action items for simple bugs unless the user explicitly opts in.
**Additional considerations:** Provide a `--postmortem` CLI flag for opt-in. Alternatively, if the `/z-fix` implementation phase takes more than 2 attempts to pass tests, the orchestrator could auto-suggest running a post-mortem to investigate why the "simple" fix was harder than expected.
