MODE: bundled-decisions

## Context: Splitting /z-debug into /z-fix + /z-debug with hypothesis tournament

**User's task:** Refactor the existing `/z-debug` command into two lighter-weight paths:
- `/z-fix` — for users who already have a diagnosis and just need a structured way to fix + review
- `/z-debug` (refactored) — for hypothesis-driven investigation using a cross-LLM tournament

Full brainstorm and decision log at: z-harness/z-fix-hypothesis-driven/BRAINSTORM.md (user-facing design intent is in "User choice" section).

---

## Five consult-flagged decisions

**D2: How to present hypothesis-posterior evolution?**
- Options:
  1. New MATRIX.md (markdown table with 5 priors × 5 likelihoods → ordinal posterior cells)
  2. Extend existing ISOLATION.md (append posterior table at end of cycles)
  3. Unified DEBUG.md (combine everything: hypotheses + isolation + posteriors in one long doc)
  4. MD + JSON sidecar (markdown + structured JSON for programmatic access)
- Tentative pick: **New MATRIX.md (markdown only)**
- Rationale: Clean separation of concerns; ISOLATION.md stays "experiment transcript," MATRIX.md becomes the "hypothesis scoreboard"

**D3: Posterior calculation rule (given prior + likelihood evidence)**
- Context: Prior is one of 5 buckets (very_low, low, medium, high, very_high). Each LLM round generates a likelihood (strongly_falsified, falsified, inconclusive, supported, strongly_supported). We need a deterministic rule to update the prior.
- Options proposed:
  1. **Tentative: "strongly_falsified always eliminates; strongly_supported promotes prior by 2 buckets; inconclusive preserves prior but caps below very_high"**
  2. Linear interpolation (all evidence weighted equally across a 0–1 scale)
  3. Bayesian (posterior ∝ likelihood × prior; normalize across all remaining hypotheses)
  4. Tournament winner takes all (discard all others after first strongly_supported)
  5. Strict consensus (all LLMs must agree to move posterior)

**D4: Cross-LLM tournament cardinality and checkpoint**
- Orchestrator Claude + Codex + Gemini (3 total), with **orchestrator writes generation block to checkpoint BEFORE dispatching parallel LLM calls** (can resume if a call fails)
- Alternative: 2 LLMs (e.g., Codex + Gemini, drop orchestrator); or Claude as final judge (all 3 generate, then Claude picks winner)
- Tentative pick: **3 LLMs with orchestrator checkpoint**
- Rationale: Maximize coverage; checkpoint pattern mirrors /z-plan's parallel consult pattern

**D5: Consultant agent mode signatures**
- New modes needed for hypothesis generation/refinement across rounds
- Options:
  1. Two new modes: `generate-hypotheses-round1` + `generate-hypotheses-round2-adversarial` (explicit phase names, input shapes differ)
  2. One parameterized mode: `hypothesis-tournament` (single mode, parametrized by round number + role)
  3. Reuse existing `debug-hypotheses` mode (currently shaped for Phase 4 of /z-debug; would need extension)
- Tentative pick: **Two new modes**
- Rationale: Clear phase separation; input/output shapes are sufficiently different to justify separate modes

**D8: Post-mortem requirement after /z-fix**
- Context: /z-debug (Phase 7) has a mandatory post-mortem with preventative action items. /z-fix is lighter.
- Options:
  1. Required (mandatory for every /z-fix, like /z-debug)
  2. Optional default-off (user can opt-in with `--postmortem` flag)
  3. Not required (remove entirely from /z-fix)
- Tentative pick: **Optional default-off**
- Rationale: /z-fix is targeted at users who already have confidence in the diagnosis; post-mortem overhead doesn't scale to a 10-min fix target. But offer it for edge cases.

---

## Relevant code snippets from existing tools

### /z-debug Phase 4 (current cross-LLM consult for hypotheses):
Lines 136–151 of /Users/zeke/dev/z-harness/commands/z-debug.md show how both Codex + Gemini are called in parallel with `debug-hypotheses` mode:

```
Agent(
  subagent_type="gemini-consultant",
  description="Debug hypotheses consult (Gemini) for <slug>",
  prompt="MODE: debug-hypotheses\n\nProblem (verbatim from PROBLEM.md):\n<content>\n\nEvidence (verbatim from EVIDENCE.md):\n<content>\n\nMy ranked hypotheses:\n<list of 2-3 from Phase 3>\n\nRelevant code (quoted with file:line):\n<short snippets>\n\nAsk: (a) which hypothesis do you find most plausible and why? (b) any hypotheses I missed? (c) for the top hypothesis, what's the cheapest experiment to confirm/refute? Be concrete."
)
Agent(
  subagent_type="codex-consultant",
  description="Debug hypotheses consult (Codex) for <slug>",
  prompt="MODE: debug-hypotheses\n\n<same prompt body>"
)
```

Return format (from agents/gemini-consultant.md and agents/codex-consultant.md):
- Both return using standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt)
- They do NOT return raw blocks (that's only for `brainstorm` and `research-review` modes)

### /z-plan-light Phase 3 (cross-LLM consult for single decision):
Lines 74–89 show the light-mode consult pattern:

```
Agent(
  subagent_type="gemini-consultant",
  description="Light-fix consult (Gemini) for <slug>",
  prompt="MODE: light-fix\n\nProblem: <1-paragraph>\nContext: <1-paragraph>\nKey decision: <statement>\nCandidate options (if any): <list with one-line tradeoffs>\nRelevant code snippets:\n<short quoted code with file:line markers>\n\nAsk: recommend an option with reasoning. Identify tradeoffs. Flag anything I haven't considered. Be concise — this is a single small fix, not a feature."
)
```

Both return using the standard wrapper.

### Current consultant modes (from agents/gemini-consultant.md lines 21–38):

Already supported:
- `bundled-decisions` (multiple decisions, interactions flagged)
- `plan-review`
- `light-fix` (single decision, concise)
- `debug-hypotheses` (problem + evidence + ranked hypotheses → top hypothesis + experiments)
- `brainstorm` (returns raw five-section block)
- `research-review` (returns raw three-section block)
- `doc-audit`
- `test-cases`
- `mr-review`

---

## Key interaction: D3 ↔ D4 (posterior buckets depend on tournament cardinality)

**D3's tentative rule:** "strongly_falsified always eliminates; strongly_supported promotes by 2 buckets; inconclusive preserves but caps below very_high"

**D4's cardinality:** 3 LLMs (Codex + Gemini + Orchestrator)

**Interaction risk:** The posterior rule assumes we may have 1, 2, or 3 likelihood signals from the same round. If D4 picks 2 LLMs, the rule may need adjustment (e.g., what if one says "strongly_supported" and the other says "inconclusive"? majority? consensus?). If we pick "Claude as judge" (3 generate, Claude synthesizes), the rule becomes "Claude's synthesis → likelihood," collapsing the cardinality benefit.

Current tentative picks are **consistent** (3 LLMs each vote independently; D3 rule handles disagreement via the "intermediate" buckets), but D5's choice of "two new modes" DOES depend on the assumption that Rounds 1 and 2 have **materially different** consultant inputs (e.g., Round 1 sees initial evidence; Round 2 sees prior hypotheses + isolation results). If D4 picks "Claude as judge," the modes might collapse into one.

---

## Ask

For each of the five consult-flagged decisions, recommend a pick with reasoning, tradeoffs, and missed considerations. Flag decision interactions (especially D3↔D4, but also D2↔D5 if relevant — the posterior matrix format might constrain which modes make sense).

**Constraints to consider:**
- /z-debug target is ≤30 min wall time; tournament + isolation loops should not balloon that.
- /z-fix target is ≤10 min; lighter weight than /z-debug by design.
- Existing consultant modes already support `debug-hypotheses`; adding new modes is cheap (just extend agents/gemini-consultant.md + agents/codex-consultant.md).
- The "checkpoint before parallel dispatch" pattern (D4) is already used in /z-plan Phase 3 (orchestrator writes initial synthesis, then spawns consults).
- ISOLATION.md cycles are capped at 3 (per /z-debug Phase 5); a MATRIX.md appended per cycle may be verbose if all 3 cycles run.
- /z-plan already has settled on "two modes per decision type" (light-fix + plan-review for different phases), so D5's "two modes" is not unprecedented.
