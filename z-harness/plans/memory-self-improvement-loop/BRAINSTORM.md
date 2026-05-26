---
artifact: brainstorm
slug: memory-self-improvement-loop
generated_at: 2026-05-25T21:10:00Z
command: /z-brainstorm
input_hash: d210ec313aec1552
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: gpt-5.5
  gemini: gemini-2.5-pro
status: complete
chosen_framing: pending
---

# Brainstorm — memory-self-improvement-loop

## Framing: claude

### Framing
The problem is not memory volume — it is memory placement. Both the write gate (Cancel-by-default) and the read gate (doc-fetcher on demand) treat memory as an optional library consulted before execution. The correct mental model is closer to a type system: memories are invariant assertions the agent must satisfy or explicitly contradict. The self-improvement loop then becomes a **contract enforcement mechanism**, not a documentation tool. The gap is not that users forget to write memories; it is that nothing in the run lifecycle asks them to verify or refute existing ones.

### Core hypothesis
Change the default memory experience from "push a memory when you remember to" to "contradict a memory or the run never fully closes." After `/z-implement-all` or `/z-review-all`, a `retro-gater` subagent runs automatically, reads `MEMORIES-FLAT.md`, and asks one question per relevant memory: "Did this run confirm, refute, or update this assertion?" Confirmations are free (single keypress). Refutations are routed to `/z-suggest-memory` with evidence pre-filled. The gate also proposes 1–2 novel candidates extracted from `events.jsonl` — candidate extraction is automated, promotion is not. Critically, the gate is **non-skippable without logging a skip event**: the "dismiss" path exists, but it writes `retro_skipped` to `events.jsonl` with the count of unverified memories, making accumulated debt visible in `/z-improve` analysis and `/z-stats` dashboards.

### Risks
- Confirmation theater: the user hits confirm on every memory without reading, making the gate worthless while creating false confidence in memory validity.
- Memory creep: once memories are framed as contracts, the system will attract over-specified invariants that constrain future plans too tightly, degenerating into a bureaucratic checklist.
- Skip-event shame-debt is paternalistic if the debt counter grows large on legitimate one-off runs (e.g. quick hotfixes where full retro is disproportionate).
- Touched-concept filter failure: if the concept-narrowing from `cumulative.stat` does not reduce the memory set to under ~3 questions, the gate becomes as onerous as full `/z-improve`.

### Plan implications
- New `agents/retro-gater.md` (Haiku-tier, lightweight), called from the finalize phase of `/z-implement-all` and after Phase 6 of `/z-review-all`.
- Reads `MEMORIES-FLAT.md` filtered by tags/concepts touched in the run (derived from `cumulative.stat` or task `Files:` lists).
- `AskUserQuestion` per relevant memory: Confirmed / Refuted (spawn `/z-suggest-memory --edit`) / Not applicable.
- Novel candidates from `events.jsonl` go to `.z/memory-candidates/` queue (not committed docs).
- `retro_skipped` event added to `scripts/log-event.sh` schema; integrated into `/z-improve` Phase 2 friction signals.
- `/z-stats` surfaces skip-debt count.

### What would change my mind
- If `/z-review-all` Phase 4 consultants (Gemini/Codex) consistently surface findings that contradict existing memories, the contract-enforcement model is wrong — memories are not reliable enough to act as invariants and the gate enforces false confidence.
- If skip rates exceed 70% across runs, the gate is tax not value and should be made optional.
- If the touched-concept filter cannot narrow memories to under 3 questions on average, the ergonomic premise fails and a different UX (e.g. batch periodic review) would be superior.

---

## Framing: codex

### Framing
The memory loop should not be treated as "documentation after work." It should be treated as a reward signal and state update after high-cost agent activity.

Right now z-harness has a strong implementation loop and a weak learning loop. `/z-suggest-memory` is safe, explicit, and schema-backed, but its default is non-persistence. That is good for avoiding junk memory, but bad for compounding improvement. The system effectively forgets unless the user performs an extra approval action at the exact moment they are least likely to want more process.

A distinct framing: make memory capture a **run artifact first**, and a **persisted memory second**.

Instead of asking "should we write a memory?", every major run should produce a structured retro packet:
- candidate lessons
- repeated failure modes
- decisions reaffirmed / overturned
- unresolved uncertainty
- agent/tool friction
- proposed memory deltas
- confidence and evidence links

Persistence can remain explicit, but the act of producing the candidate learning becomes unavoidable for `/z-review-all` and `/z-implement-all`. This separates two concerns: "Did the system notice what happened?" (automatic) from "Should this become durable memory?" (user-controlled).

### Core hypothesis
The best mechanism is a **memory credit assignment layer** modeled loosely on Hermes-style long-term memory RL: runs generate candidate memories, future runs reveal whether those memories were useful, and the harness updates their weight, routing, or promotion status.

Concrete mechanisms:

1. **Run-local Memory Episode** — after `/z-review-all` and `/z-implement-all`, always write a non-committed episode artifact (e.g. `.z/episodes/2026-05-25T...json`) containing task IDs touched, failures, review findings, fixes needed, user corrections, and candidate memories. This is evidence, not a memory yet.

2. **Soft Auto-Invoke `/z-improve`** — after a major run, emit a blocking-but-light gate: "Retro packet created / 3 candidate memories found." Choices: `Review now`, `Defer`, `Dismiss`. Default = `Defer`, not `Dismiss`. Skipping is visible and records debt.

3. **Deferred Memory Queue** — `.z/memory-candidates/` with schema: `claim`, `why_it_matters`, `evidence`, `scope`, `risk_if_wrong`, `suggested_retrieval_queries`, `expires_or_review_after`, `confidence`, `source_runs`. `/z-suggest-memory` remains the only promotion path to committed `docs/llm/*.json`.

4. **Multi-Run Synthesis** — new `/z-synthesize-memories` reads episodes and candidates, groups repeated patterns ("same bug class in 3 runs", "same decision re-litigated twice"), and surfaces signal vs noise.

5. **Memory Reward Tracking** — telemetry events: `memory_candidate_generated`, `memory_persisted`, `memory_retrieved`, `memory_used_in_plan`, `memory_prevented_rework`, `memory_contradicted`, `memory_stale`, `memory_ignored`. Offline scores: retrieval frequency, downstream citation rate, relation to avoided review failures, user acceptance rate.

6. **Memory Tiers** — Episode (raw, automatic) → Candidate (proposed, semi-automatic) → Repo memory (committed `docs/llm/*.json`, explicit) → Global memory (user/process preferences) → Negative memory (known-bad approaches, rejected designs).

7. **Pre-Consult Memory Injection** — `/z-review-all` Phase 3.7 should bundle relevant committed memories, unresolved candidates, prior review failures in same files, and negative memories for rejected approaches into the consultant prompt.

8. **Vendor-Diverse Retro Panel** — for high-value runs: one agent extracts tactical lessons, one extracts process lessons, one extracts architectural decisions, one adversarially rejects low-value candidates.

### Risks
- Memory spam: every run produces polished-sounding "lessons," retrieval gets worse, future agents overfit to stale advice.
- False causality: a retrieved memory before a successful run does not mean it helped; agents must cite which memory changed an action, not just which appeared in context.
- Annoying the user: if every major command ends with another full workflow, users route around it.
- Repo pollution: committed `docs/llm/*.json` should stay deliberate; auto-written candidates are fine, committed entries should keep explicit approval.
- Global memory leakage: `~/.claude/.../MEMORY.md` is outside repo review; should store user/process preferences, not repo-specific facts needing versioning.
- Hermes cargo-culting: the RL mechanism needs verification against actual paper/code before naming anything "Hermes-compatible."

### Plan implications
- Add `scripts/log-retro-episode.sh` or `scripts/create-retro-episode.ts`.
- Extend `/z-implement-all` and `/z-review-all` final phases to always emit an episode artifact.
- Add lightweight post-run gate that creates memory candidates without persisting committed memories.
- Add `docs/llm/_candidates/` or `.z/memory-candidates/` with schema validation.
- Add `scripts/synthesize-memory-candidates.*` to cluster multi-run patterns.
- Extend telemetry with memory lifecycle events.
- Extend doc-fetcher to search candidate summaries during planning/review (labeled as unapproved).
- Add pre-consult memory bundle to `/z-review-all` Phase 3.7.
- Add memory scorecard to `.z/memory-metrics.json`.
- Add negative-memory support to schema as a first-class `kind`.

### What would change my mind
- Back away from automatic candidate generation if fewer than 20% of candidates get accepted or accepted memories are rarely retrieved.
- Favor stronger auto-persistence if acceptance is consistently high, candidates are narrow and evidence-backed, and review failures measurably drop.
- Deprioritize Hermes-style scoring if the repo does not produce enough repeated task volume for credit assignment to be meaningful.
- Move more memory into global `MEMORY.md` if most friction is about user preferences rather than repo-specific technical facts.
- Make the retro gate non-blocking if users start abandoning major commands because the post-run phase feels like process tax.

---

## Framing: gemini

### Framing
The current memory architecture treats documentation as a static library to be "pulled" by the agent (doc-fetcher). To move toward a Hermes-style long-term memory, we must treat every `/z-implement-all` and `/z-review-all` run as a training episode. Memory is not just "facts about the code," but "trajectories of the agent" — capturing where the plan diverged from reality (pivots), what reviews were rejected (failed paths), and which decisions were terminal. We are transitioning from a **Documentation Harness** to an **Experience Engine**.

### Core hypothesis
We can significantly reduce decision re-litigation by implementing a **Shadow Memory** layer that automatically records "Differential Trajectories" (Plan vs. Outcome) without requiring immediate user approval. By automatically labeling every run with an **Outcome Tag** (e.g., `SUCCESS`, `FAIL:SPEC_DRIFT`, `FAIL:REVIEW_LOOP`) and caching the resulting "Reasoning Deltas" in a local `pending/` directory, we create a dense reinforcement signal. These pending memories can be injected into the `doc-fetcher` search space as "Experience Buffers," allowing the agent to "remember" why a specific architectural path was previously abandoned in an earlier session, even if a formal document hasn't been authored yet.

### Risks
- Timid Agent Syndrome: if the agent over-indexes on a single failure (e.g. a flaky test or transient environment issue), it may become "allergic" to valid paths, refusing complex implementations because a Shadow Memory suggests they are high-risk.
- Trajectory Pollution: low-signal noise from trivial runs (e.g. small documentation fixes) could dilute high-signal Differential Memories, causing doc-fetcher to waste context on irrelevant history.
- Prompt Sensitivity to Failure: injecting "Negative Examples" (what not to do) can confuse LLMs, causing them to hallucinate the failure mode into the new implementation.

### Plan implications
- **Mandatory Outcome Hook**: modify `/z-implement-all` and `/z-review-all` to execute a `trajectory-labeler.md` subagent upon completion (or halt). This agent compares initial `SPEC.md` against final `archive/events.jsonl` to generate a 1-paragraph "Differential Memory."
- **Soft-Auto-Retro**: replace the generic "Do you want to run /z-improve?" prompt with a "Review Draft Memories" UI. The agent presents 2-3 pre-authored memories derived from the run's pivots; the user only needs to hit Confirm or Edit — reducing friction vs. authoring from scratch.
- **Experience-Aware Doc-Fetcher**: update `doc-fetcher` to prioritize searching the `pending/` (Shadow Memory) directory when a query matches a previous plan's slug, bridging the gap between sessions before formal `docs/llm/` promotion.
- **Hermes-style Reasoning Log**: standardize `cross_task_notes` and `decisions-late.md` to include "Reasoning traces" explicitly formatted for potential DPO (Direct Preference Optimization) training of future internal models.

### What would change my mind
If the "Experience Buffer" significantly increases token latency for `doc-fetcher` without a measurable decrease in "Plan Revision Cycles," the complexity is unjustified. Furthermore, if "Shadow Memories" lead to "Reasoning Inconsistency" (where the agent contradicts itself because it over-weights a specific previous failure over current code reality), we should revert to a strictly human-vetted documentation model.

---

## Anti-bias check

**Section 1 — Framing:**
- Claude frames memory as a **contract/invariant** to be confirmed or contradicted.
- Codex frames memory as a **run artifact** (evidence first, persistence second) — separating observation from promotion.
- Gemini frames memory as an **Experience Engine** — trajectories and training episodes, Hermes-style.

Divergence: Claude and Codex both emphasize making the post-run loop non-skippable, but differ in mechanism (per-memory verification vs. structured retro packet). Gemini uniquely emphasizes Plan vs. Outcome differentials and Outcome Tags.

Winner by section: Codex wins Framing — the "observation automatic, promotion user-controlled" split is the sharpest articulation of the skip problem and maps most directly to the harness's existing architecture. Gemini wins on the Hermes-specific angle (DPO reasoning log, Experience Buffer). Claude wins on the existing-memory verification angle (confirm/refute gate) which neither peer surfaced. No Claude-favoring calls here — Claude's framing is genuinely distinct but narrower than Codex's.

**Section 2 — Core hypothesis:**
- Claude: retro-gater subagent that forces confirm/refute of existing memories per run.
- Codex: multi-mechanism credit assignment (episode artifacts, candidate queue, reward tracking, memory tiers, synthesis command, pre-consult injection).
- Gemini: Shadow Memory layer with Outcome Tags + Experience Buffers injected into doc-fetcher.

Codex wins on breadth and concreteness — it proposes 8 mechanisms with specific artifact paths. Claude wins on the one thing Codex doesn't emphasize: what to do with existing memories already in the system (the confirm/refute loop). Gemini is distinct in proposing Outcome Tags as a first-class concept, which neither peer has; this is the sharpest Hermes-proximate mechanism.

**Section 3 — Risks:**
- All three identified memory spam / noise as a risk.
- Codex uniquely identified "false causality" (retrieval ≠ use), global memory leakage, and Hermes cargo-culting.
- Claude uniquely identified confirmation theater and memory creep into over-specified invariants.
- Gemini uniquely identified "Timid Agent Syndrome" (allergy to valid paths) and prompt sensitivity to negative examples.

No ideator dominated — the risk sets are complementary.

**Section 4 — Plan implications:**
- Codex is most concrete: lists 10 specific file/script changes.
- Claude is concrete about the single new agent (retro-gater) and its integration points.
- Gemini is most architectural: trajectory-labeler subagent, DPO reasoning log format.

No single ideator dominates; the plans compose well.

**Section 5 — What would change my mind:**
- Codex: quantitative thresholds (20% acceptance, retrieval rate).
- Claude: skip rate > 70%, consultant contradiction of existing memories.
- Gemini: token latency in doc-fetcher, reasoning inconsistency.

All three are concrete. Codex provides the most measurable triggers.

**Anti-bias verdict:** The orchestrator (running on Claude) is *not* picking Claude as the overall winner. The synthesized recommendation below favors Codex's architecture (episodic capture + candidate queue + credit assignment) as the most implementable foundation, with Claude's confirm/refute gate as a complement for existing memories, and Gemini's Outcome Tag system as the Hermes-specific hook.

---

## Orchestrator recommendation

**Codex framing** provides the most complete and composable architecture — episode artifacts, candidate queue, memory tiers, reward tracking, and pre-consult injection give z-harness a roadmap that doesn't require rewriting existing primitives, only adding layers. Codex's "observation automatic, promotion user-controlled" split preserves the Cancel-default safety contract of `/z-suggest-memory` while making forgetting visible. The Claude confirm/refute gate should be incorporated as a sub-mechanism for existing memories (it fills the gap Codex doesn't address). Gemini's Outcome Tags are the most concrete Hermes-proximate mechanism and should be a first-class event.
