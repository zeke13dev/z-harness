---
artifact: brainstorm
slug: z-test-error-points
generated_at: "2026-06-10T21:54:14Z"
command: /z-brainstorm z-test error-points redesign
input_hash: 45053a53db4e9e46
depends_on: [BRAINSTORM.md]
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
ideator_personas:
  claude: cut-it-half
  codex: anti-consensus-surgeon
  gemini: physics-reductionist
status: complete
chosen_framing: codex
---

# BRAINSTORM: z-test error-points redesign

## Framing: Claude

### Framing
The BRAINSTORM.md describes an ERROR_POINTS.json that accumulates real failure patterns and feeds them into `z-test`. But we already have this. INVARIANTS.json already has `failure_class` fields — domain-term bug descriptions. `z-review-all` Phase 5.5 already extracts invariant candidates from findings. The only thing missing is the **frequency counter** and **spatial anchoring**. So the proposal doesn't add a new system — it adds two columns to an existing table. Frame it as "augment INVARIANTS.json with frequency + spatial anchor" rather than "build ERROR_POINTS.json from scratch." The whole new artifact, new schema, new pipeline — delete half of it. What actually matters: (a) persist which invariants break and how often, (b) weight test generation by those frequencies. Everything else — the three seed sources, the pruning algorithm, the separate archive — is decoration that can wait until we have data proving it's needed.

### Core hypothesis
The invariant-first approach fails because it's static: it tests what we *declare* matters, not what *proves* to matter. But the fix isn't a parallel system. The fix is to make INVARIANTS.json *alive* — give it a heartbeat. Add `sighting_count` and `last_sighting` and `anchor_module` to the existing invariant entries. Let Phase 5.5 increment counters on matched invariants instead of only proposing new ones. Let `z-test` Phase 1 weight by `severity × sighting_count` instead of domain criticality. New invariants start at count=0 and get tested at baseline priority; high-count invariants jump the queue. One schema change, one Phase 5.5 behavior change, one Phase 1 ranking change. Three small changes accomplish everything the proposal aims for without a new artifact, new LLM subagent (the similarity classifier), new pruning rules, or new archive semantics.

### Risks
- The proposal's cheap-LLM similarity classifier is a new failure mode: false matches merge unrelated bugs into one error point, poisoning the frequency counter. False negatives create duplicate entries that dilute the signal.
- Spatial anchoring at module granularity is too coarse for cross-cutting patterns (e.g. "time-window boundary errors" that span five modules). The anchor becomes misleading — tests target the wrong file.
- Three seed sources with priority ordering creates a cold-start cliff: until enough review runs accumulate, ERROR_POINTS.json is seeded from codebase scans and invariants, producing a distribution that doesn't match real failure patterns. Users distrust it, disable it, and we've built a ghost town.
- The `tests_targeting` counter creates a perverse incentive: once a test exists, the error point prunes away even if the test is weak. The count says "covered" but reality says "still breaking."

### Plan implications
- Delete the ERROR_POINTS.json artifact entirely. Add `sighting_count`, `last_sighting`, `anchor_module` fields to INVARIANTS.json schema.
- Phase 5.5 of z-review-all: after extracting new invariant candidates, also match each finding against existing invariants by `failure_class` similarity. On match, increment `sighting_count`. This uses the SAME Haiku subagent already dispatched — no new subagent.
- Phase 1 of z-test: replace domain-criticality ranking with `severity × log(1 + sighting_count)`. Log-dampening prevents one hot invariant from monopolizing every test slot.
- Skip the codebase init bootstrap — cold start with sighting_count=0 is fine; invariants still get tested at baseline priority. Real data accumulates within 2-3 review runs.
- Skip the pruning system. If an invariant stops breaking, its sighting_count stabilizes and it naturally falls in priority. No need to delete working data.
- Archive `z-test` → `z-test-invariant` still makes sense: it's a behavior change to the skill, not a schema change.

### What would change my mind
- If review findings have fundamentally different structure from invariant `failure_class` entries (e.g. findings are "file X line Y has bug Z" while invariants are "the system must never Q"), then simple matching fails and a separate registry IS needed.
- If we observe that Phase 5.5 invariant extraction is too slow/expensive to also do matching, then the cheap-LLM classifier subagent becomes the right path.
- If sighting_count on invariants creates confusion between "this is a design truth" and "this is an observed failure" — and users need them cleanly separated — then a separate ERROR_POINTS.json with clear semantics is justified.

## Framing: Codex

### Framing
Every voice in the BRAINSTORM.md accepts the same unexamined premise: **that tests should target what breaks.** This sounds obvious — of course they should. But look at what this premise does: it turns the test suite into a rear-view mirror. Tests converge toward yesterday's bugs. Tomorrow's bugs — the novel failure mode, the untested edge case, the interaction between two things that have never broken together — are invisible to an error-points-driven system. The `z-test-invariant` approach has a real advantage: it tests design truths that *haven't broken yet*. Both approaches are necessary. The question isn't "which is primary" but "how do they compose."

The consensus in the BRAINSTORM.md is that invariant-first is broken and error-points should replace it. I'm cutting into that. The invariant approach isn't broken — it's incomplete. Making it the fallback ("invariant-sourced entries naturally deprioritize") throws away the one thing it does uniquely well: testing what *could* break before it does. The correct framing is **dual-source**: error points drive *regression hardening* (make sure yesterday's bugs stay fixed), invariants drive *preventive coverage* (guard design truths that haven't failed yet). Neither is primary — they serve different testing goals.

### Core hypothesis
A purely error-points-driven test system will asymptotically converge to a test suite that catches yesterday's bugs with high reliability but is blind to novel failure modes. The invariant-first approach's weakness (testing what we *think* matters) is also its strength: it encodes design knowledge that error data alone can't recover. If we deprioritize invariants to "fallback," we lose the preventive layer. The correct synthesis: ERROR_POINTS.json covers the *empirical* failure surface; INVARIANTS.json covers the *declared* failure surface. `z-test` Phase 0 loads both. Phase 1 produces two ranked lists: hot error points (for regression hardening) and uncovered blocker invariants (for preventive coverage). Phase 2 interleaves — every N error-point-driven tests, insert one invariant-driven test. The ratio (e.g. 3:1) is configurable. This gives us both rear-view and forward-looking coverage.

### Risks
- **Temporal overfit**: Error points are a lagging indicator. By the time a pattern accumulates enough frequency to get tests, the code may have already been refactored past that failure mode. The test guards a ghost.
- **Novelty blindness**: The worst bugs in any system are the ones that have never happened before. An error-points-primary system has no mechanism to generate tests for novel failure modes. Invariants fill this gap — but only if they're not deprioritized.
- **Feedback cycle decay**: If error points only accumulate from review findings, and review only catches what tests miss, then error-point coverage converges to whatever the current test suite doesn't cover — which is exactly the set of things the error-point system itself won't test for. It's a circular dependency with a shrinking frontier.
- **Similarity matching as a research problem**: Classifying "is this new finding the same error pattern as ep_003?" is genuinely hard. Review findings are natural language. Error patterns are structured. The cheap-LLM subagent will make mistakes in both directions, and those mistakes compound over time (merged error points inflate frequency; split error points dilute it).
- The archival of `z-test-invariant` as "alternate" signals that invariants are legacy. That signaling matters — new users will never discover the invariant path, and within months it will bit-rot.

### Plan implications
- Keep both artifacts: ERROR_POINTS.json (empirical, from review findings) and INVARIANTS.json (declared, from design/spec). Neither is fallback.
- `z-test` Phase 0 loads both. Phase 1 produces a merged risk ranking with a configurable interleave ratio.
- Default ratio: 70% error-points-driven, 30% invariant-driven. Tunable per-repo.
- The archival of `z-test-invariant` should be rethought: instead of "alternate," make it a **mode flag** on `z-test`: `--mode error-points` (default), `--mode invariant` (legacy), `--mode dual` (recommended). The archive is the mode, not the whole skill.
- Add a `novelty_score` to each error point: `1 / (1 + frequency)`. High-frequency points have low novelty. Low-frequency but high-severity points are interesting — they might be emerging failure modes. This partially addresses the rear-view mirror problem.

### What would change my mind
- If empirical data shows that error-points-driven tests catch >90% of novel failures too (because failure modes cluster and error points generalize), then the dual-source argument weakens. But I doubt this — novel failures by definition haven't clustered yet.
- If the overhead of dual-source loading + merged ranking + interleaving proves too complex in practice (more bugs in the test planner than bugs it catches), simplify to error-points-primary.
- If INVARIANTS.json is poorly maintained in practice (stale invariants, nobody updates them), then its signal is noise and error-points-primary is the right call. But that's a maintenance problem, not an architecture problem.

## Framing: Gemini

### Framing
Forget the JSON files, the pipelines, the phases. What actually happens when you run this system? A `z-review-all` finishes. Findings exist in a markdown file. Then — what? Some process reads those findings, classifies them, increments counters, writes to disk. Then later, `z-test` reads those counters, ranks them, generates test descriptions, writes to another markdown file. Then an implementer reads that, writes test code, runs it. The actual work — the test execution catching a real bug — is at the end of a long chain of text transformations. Every link in that chain is a place where signal decays.

The error-points proposal adds MORE links: a cheap-LLM similarity classifier, a frequency counter, a pruning rule, a fixture-scope tag system. Each link costs tokens, wall time, and introduces its own error rate. The question isn't "does this architecture make sense" — it's "does the signal gain from error-points exceed the signal loss from the extra links." That's an empirical question with a specific answer: measure it. Run 10 simulated review cycles. Count how many error-points-driven tests would have caught a real bug that invariant-driven tests would have missed. If the number is zero or near-zero, the whole apparatus is dead weight.

Reduce the problem to its simplest physical form: you have a set of past failures and a set of future failures. The question is whether past failures predict future failures well enough to justify the machinery. In most software systems, the answer is "sometimes yes, sometimes no" — it depends on whether the codebase is in steady-state (bugs cluster) or in active development (novel bugs dominate). The proposal should acknowledge this context-dependence rather than asserting error-points-primary universally.

### Core hypothesis
The value of error-points-driven testing is proportional to the **bug recurrence rate** — how often the same pattern of failure reappears after being fixed. In mature, stable codebases, recurrence is high (the same edge cases keep breaking because the underlying architecture hasn't changed). In actively developed codebases, recurrence is low (new code introduces new failure modes). The proposal's ROI depends entirely on which regime the target codebase is in. Since z-harness itself is under active development (we're using it to improve itself), the bug recurrence rate is likely LOW. The error-points system might produce tests that guard against bugs in code that no longer exists or has been substantially refactored. The cold-start problem (tension 2) isn't just about seeding — it's about whether error points go stale before they accumulate enough frequency to matter.

### Risks
- **Signal decay chain**: Each phase (review → classification → counting → ranking → drafting → implementing → running) has a loss rate. If each link preserves 80% of signal, the 6-link chain preserves only 26% (`0.8^6`). The test that actually runs may bear little relation to the original finding.
- **Classification as a bottleneck**: The cheap-LLM similarity subagent is the critical path for every review run. If it's cheap but inaccurate, error points are wrong. If it's accurate but expensive, it defeats the "cheap" premise. There's no middle ground that's both cheap AND accurate for fuzzy natural-language-to-structured-pattern matching.
- **Spatial anchoring is a lie**: Real bugs don't respect module boundaries. A "time-window off-by-one" error can manifest in the fill module, the risk calculator, or the reporting layer. Anchoring it to one module path creates a test that only catches it in one place, giving false confidence.
- **The `tests_targeting` count is a vanity metric**: Having a test that "targets" an error point doesn't mean the test actually catches the failure. It means someone wrote a test and linked it. The count goes up but the bug might still reproduce.
- Cold start + rapid code evolution = error points are stale on arrival. By the time ep_003 has 7 sightings, the module it anchors to may have been rewritten. The test targets dead code.

### Plan implications
- Add a **signal-audit phase** before building anything: run z-harness's own telemetry through a simulated error-points pipeline. Take the last 5 review runs' findings. Classify them. Count what percentage would produce a test that catches a bug the next run missed. If <10%, abort the redesign.
- Replace "spatial anchor" with **pattern signatures** — a hash of the abstract syntax tree path that caused the failure, not the file name. A pattern like "boundary comparison in any function using `TimeWindow` type" survives refactors that rename files.
- Ditch the cheap-LLM classifier for a **deterministic matching rule first**: if two findings share the same `failure_class` tag and the same module path, they're the same error point. LLM classification is the fallback for ambiguous cases, not the primary path.
- Rate-limit error-point accumulation: an error point can't increment frequency more than once per review run, even if it appears in 5 findings. This prevents a single bad deploy from flooding one error point's frequency.
- The `tests_targeting` field should be replaced with `last_test_pass` and `last_test_fail` — did the targeting test actually catch anything recently? A test that hasn't caught a bug in 10 runs isn't "targeting" anything useful.
- Name it `docs/FAILURE_REGISTRY.json`. "Error points" is a term that doesn't appear anywhere else in z-harness. "Failure registry" self-documents what it is.

### What would change my mind
- Empirical evidence: run the signal audit I described. If >30% of review findings map to prior error points that weren't caught by existing invariant-driven tests, the system has real signal. Build it.
- If the codebase stabilizes (z-harness core matures, fewer architectural changes), bug recurrence rate goes up, and the rear-view mirror becomes more useful.
- If someone demonstrates a cheap-LLM similarity classifier that achieves >90% precision/recall on finding-to-error-point matching, the classification bottleneck dissolves. Until then, I'm skeptical.
- If we add a **staleness score** to error points (days since last sighting × code churn in anchor module) and use it to downweight or auto-archive, the cold-start/staleness risk is managed.

## Anti-bias check

**Framing:** Claude wins — for design parsimony. It identifies that `failure_class` already exists as a structured analog to error points, and that two new fields plus a behavior change to Phase 5.5 accomplish the goal with zero new artifacts. Codex's dual-source framing is philosophically correct but architecturally heavier. Gemini's "measure first" framing is correct as process discipline but doesn't resolve the design question. Verdict: Claude wins on Framing for concrete design economy — the least-new-stuff approach that achieves the goal.

**Core hypothesis:** Codex wins. The insight that "tests converge toward yesterday's bugs" and "invariants guard what hasn't broken yet" identifies a genuine blind spot in the converged BRAINSTORM. The proposal says "invariant-sourced entries naturally deprioritize" — Codex correctly flags this as throwing away preventive coverage. Claude's hypothesis (extend INVARIANTS) and Gemini's (recurrence-rate dependent) don't contradict Codex but Codex's is the most falsifiable and addresses the deepest architectural question: what's the relationship between empirical and declared failure surfaces? Verdict: Codex wins on Core hypothesis — the rear-view mirror blind spot is real and unaddressed in the BRAINSTORM.

**Risks:** Gemini wins. The "signal decay chain" analysis (0.8^6 = 26%) is a quantitative framing that neither Claude nor Codex provided. The "spatial anchoring is a lie" insight directly addresses Tension 1 with a concrete alternative (pattern signatures / AST hashes). The "tests_targeting is a vanity metric" directly addresses Tension 4 with a specific alternative (last_test_pass/fail). Gemini also surfaced the cold-start + code-evolution compound risk that neither other ideator named. Verdict: Gemini wins on Risks — quantitative, concrete, and addresses every open tension with alternatives.

**Plan implications:** Split decision. Claude's plan implications are the most implementable (3 small changes, skip the heavy machinery). Codex's dual-source + mode flags is the most architecturally sound. Gemini's "signal audit first" is the right process discipline. They're complementary, not conflicting. Verdict: No single winner — each addresses different layers (implementation, architecture, process).

**What would change my mind:** Gemini wins. The specific empirical thresholds (>30% mapping, >90% classifier precision/recall) make the claim falsifiable. Claude's condition is structural (findings differ from failure_class) which is checkable but less quantitative. Codex's conditions are reasonable but softer. Verdict: Gemini wins on What would change my mind for specific, measurable thresholds.

### Blind spots surfaced (none of the three ideators caught)

1. **ERROR_POINTS.json as an attack surface**: If a malicious or buggy review run floods the registry with false error points (e.g., a bad LLM classifies every finding as a new error point), the test planner generates tests for phantom failures. There's no rate-limiting or authentication on writes to the registry.

2. **Cross-repo error points**: If multiple repos use z-harness, do error points transfer? A pattern learned in repo A might be relevant in repo B. The BRAINSTORM assumes per-repo isolation — a missed opportunity AND a risk.

3. **Error point lifecycle beyond archive**: What happens to archived error points? Do they resurrect if the pattern reappears? The BRAINSTORM says "archived" but doesn't define resurrection rules. This creates a silent failure mode.

4. **The LLM subagent as a single point of failure**: Both the similarity classifier AND the test drafter are LLM-dependent. If the same model produces both, errors compound. If they're different models, cost doubles.

## User choice

**Chosen: Codex framing** — dual-source error points + invariants with configurable interleave.

User directive: adopt the Codex dual-source framing as the primary architecture, augmented with:
- **Claude's implementation parsimony**: extend INVARIANTS.json rather than building a parallel artifact; add frequency/sighting fields to existing schema; reuse existing Phase 5.5 subagent for matching
- **Gemini's process discipline**: signal audit before building (measure bug recurrence rate from existing telemetry); deterministic matching rules first, LLM classification as fallback; pattern signatures (AST hashes) instead of fragile file-path spatial anchors; `last_test_pass`/`last_test_fail` instead of `tests_targeting` vanity metric; FAILURE_REGISTRY.json naming

This produces a synthesis: dual-source architecture (Codex) implemented minimally (Claude) with empirical validation gates (Gemini).

### Codex framing (reproduced verbatim)

Every voice in the BRAINSTORM.md accepts the same unexamined premise: **that tests should target what breaks.** This sounds obvious — of course they should. But look at what this premise does: it turns the test suite into a rear-view mirror. Tests converge toward yesterday's bugs. Tomorrow's bugs — the novel failure mode, the untested edge case, the interaction between two things that have never broken together — are invisible to an error-points-driven system. The `z-test-invariant` approach has a real advantage: it tests design truths that *haven't broken yet*. Both approaches are necessary. The question isn't "which is primary" but "how do they compose."

The consensus in the BRAINSTORM.md is that invariant-first is broken and error-points should replace it. I'm cutting into that. The invariant approach isn't broken — it's incomplete. Making it the fallback ("invariant-sourced entries naturally deprioritize") throws away the one thing it does uniquely well: testing what *could* break before it does. The correct framing is **dual-source**: error points drive *regression hardening* (make sure yesterday's bugs stay fixed), invariants drive *preventive coverage* (guard design truths that haven't failed yet). Neither is primary — they serve different testing goals.

### Core hypothesis

A purely error-points-driven test system will asymptotically converge to a test suite that catches yesterday's bugs with high reliability but is blind to novel failure modes. The invariant-first approach's weakness (testing what we *think* matters) is also its strength: it encodes design knowledge that error data alone can't recover. If we deprioritize invariants to "fallback," we lose the preventive layer. The correct synthesis: ERROR_POINTS.json covers the *empirical* failure surface; INVARIANTS.json covers the *declared* failure surface. `z-test` Phase 0 loads both. Phase 1 produces two ranked lists: hot error points (for regression hardening) and uncovered blocker invariants (for preventive coverage). Phase 2 interleaves — every N error-point-driven tests, insert one invariant-driven test. The ratio (e.g. 3:1) is configurable. This gives us both rear-view and forward-looking coverage.

### Risks

- **Temporal overfit**: Error points are a lagging indicator. By the time a pattern accumulates enough frequency to get tests, the code may have already been refactored past that failure mode. The test guards a ghost.
- **Novelty blindness**: The worst bugs in any system are the ones that have never happened before. An error-points-primary system has no mechanism to generate tests for novel failure modes. Invariants fill this gap — but only if they're not deprioritized.
- **Feedback cycle decay**: If error points only accumulate from review findings, and review only catches what tests miss, then error-point coverage converges to whatever the current test suite doesn't cover — which is exactly the set of things the error-point system itself won't test for. It's a circular dependency with a shrinking frontier.
- **Similarity matching as a research problem**: Classifying "is this new finding the same error pattern as ep_003?" is genuinely hard. Review findings are natural language. Error patterns are structured. The cheap-LLM subagent will make mistakes in both directions, and those mistakes compound over time (merged error points inflate frequency; split error points dilute it).
- The archival of `z-test-invariant` as "alternate" signals that invariants are legacy. That signaling matters — new users will never discover the invariant path, and within months it will bit-rot.

### Plan implications

- Keep both artifacts: ERROR_POINTS.json (empirical, from review findings) and INVARIANTS.json (declared, from design/spec). Neither is fallback.
- `z-test` Phase 0 loads both. Phase 1 produces a merged risk ranking with a configurable interleave ratio.
- Default ratio: 70% error-points-driven, 30% invariant-driven. Tunable per-repo.
- The archival of `z-test-invariant` should be rethought: instead of "alternate," make it a **mode flag** on `z-test`: `--mode error-points` (default), `--mode invariant` (legacy), `--mode dual` (recommended). The archive is the mode, not the whole skill.
- Add a `novelty_score` to each error point: `1 / (1 + frequency)`. High-frequency points have low novelty. Low-frequency but high-severity points are interesting — they might be emerging failure modes. This partially addresses the rear-view mirror problem.

### What would change my mind

- If empirical data shows that error-points-driven tests catch >90% of novel failures too (because failure modes cluster and error points generalize), then the dual-source argument weakens. But I doubt this — novel failures by definition haven't clustered yet.
- If the overhead of dual-source loading + merged ranking + interleaving proves too complex in practice (more bugs in the test planner than bugs it catches), simplify to error-points-primary.
- If INVARIANTS.json is poorly maintained in practice (stale invariants, nobody updates them), then its signal is noise and error-points-primary is the right call. But that's a maintenance problem, not an architecture problem.

## Orchestrator recommendation

**Recommend Codex framing** — not because it's "right" in isolation, but because it surfaces the one thing the converged BRAINSTORM missed entirely: the relationship between empirical and preventive coverage. The dual-source approach (error points for regression, invariants for prevention) with a configurable interleave ratio resolves Tension 3 correctly, and the mode-flag approach avoids signaling that invariants are legacy. Augment with Claude's implementation parsimony (extend INVARIANTS schema rather than build parallel artifact) and Gemini's process discipline (signal audit before building, deterministic matching first, pattern signatures for spatial anchoring).
