---
artifact: brainstorm
slug: memory-self-improve-loop
generated_at: 2026-05-25T20:56:03Z
command: /z-brainstorm (memory in self-improvement loop + Hermes RL inspiration)
input_hash: c9a8b3f2d1e5f471
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
handoff: /z-research on Nous Research Hermes Agent (github.com/NousResearch/hermes-agent) — Atropos RL mechanism, FTS5 memory, Skill Documents, and portability to z-harness docs/llm + MEMORIES-FLAT stack. User wants experimental research-flavored direction; framing pick deferred until research returns.
notes:
  - Claude ideator returned an out-of-spec format (synthesized three vendor framings instead of one). The block it labeled "Claude — Memory as Contract" is used here as Claude's framing; its predictions of Codex/Gemini output were discarded and the real Codex and Gemini agents were dispatched separately.
---

## Framing: Claude — "Memory as Contract"

### Framing
The gap isn't that users forget to write memories — nothing in the run lifecycle asks them to verify or refute existing ones. Treat memories as invariant assertions: the run lifecycle should enforce "contradict a memory or the run never fully closes."

### Core hypothesis
A `retro-gater` subagent (Haiku-tier) runs after every `/z-implement-all` or `/z-review-all`. It reads `MEMORIES-FLAT.md` narrowed to concepts touched in the run (from `cumulative.stat`), then asks per relevant memory: **Confirmed / Refuted / Not applicable**. Refutations route to `/z-suggest-memory --edit` with evidence pre-filled. 1–2 novel candidates are extracted from `events.jsonl` automatically; promotion is not. The gate is **non-skippable without logging `retro_skipped`** — the skip event makes accumulated debt visible in `/z-improve` and `/z-stats`.

### Risks
- Confirmation theater (user rubber-stamps without reading).
- Memory creep into over-specified invariants.
- Skip-debt counter becoming paternalistic on legitimate one-off runs.
- Touched-concept filter failure (too many memories shown).

### Plan implications
- New `agents/retro-gater.md` (Haiku).
- Integration into finalize phases of `/z-implement-all` and `/z-review-all`.
- New `retro_skipped` event in log schema.
- `/z-stats` skip-debt counter surfacing accumulated unverified runs.

### What would change my mind
- Consultant findings that contradict existing memories (proving they're not reliable as invariants).
- Skip rate > 70% across real-world runs.
- Touched-concept filter can't narrow to under 3 questions in typical runs.

---

## Framing: Codex — "Observation Automatic, Promotion User-Controlled"

### Framing
Treat memories as a post-run artifact, not a side quest. After `/z-review-all` and `/z-implement-all`, the harness should produce a small **learning diff** alongside code diffs: what changed, what almost went wrong, what decisions should not be reopened, and what should be retrieved next time. The user should approve persistence, but the system should make skipping an **intentional act**.

### Core hypothesis
A mandatory-but-lightweight retro gate at the end of major commands:

1. Generate `RUN_RETRO.md` automatically from telemetry, review retries, failures, doc drift, task deltas, and human overrides.
2. A memory-candidate agent emits 0–3 proposed `/z-suggest-memory` calls, each classified as: `mistake-prevention`, `decision-rationale`, `workflow-improvement`, `retrieval-gap`.
3. Change default action from global **Cancel** to per-candidate **Skip**, with a required reason only when skipping all candidates after a nontrivial run.
4. Persist rejected candidates to `$RUN_DIR/memory-candidates.jsonl` — skipped learning auditable without polluting committed docs.
5. Feed accepted memories back into `INDEX.json` and `MEMORIES-FLAT.md` immediately, then run a **retrieval smoke test**: would doc-fetcher find this for the concepts that triggered it?

Hermes angle: reward shaping around memory **utility**, not autonomous writes. Bandit/RL-ish loop where memories get implicit rewards when later retrieved before a successful fix, review catch, or avoided retry — negative signals when retrieved but ignored, contradicted, or associated with churn. Start with deterministic scoring before claiming RL.

### Risks
- **Memory spam.** If every run creates a lesson, retrieval quality collapses and users stop trusting the system. Needs a harsh novelty filter.
- **False authority.** A memory outlives the facts that made it true. Every memory should carry `source_run`, `source_files`, `valid_until` / `stale_if`, `confidence`. Drift detection should apply to memories, not just concept docs.
- **User annoyance.** A post-run gate that blocks completion with verbose prose will get bypassed. Compact prompt; full retro details in run directory.
- **Overfitting to agent behavior.** Memories that mostly encode "the last model made this mistake" become brittle when the agent stack changes. Prefer repo-specific invariants and harness-process lessons over model-specific quirks.
- **Pretending Hermes-style RL is validated here.** Use as inspiration; do not import architecture claims without verifying Hermes' actual implementation.

### Plan implications
- New post-run phase `phase_memory_retro` on both `/z-review-all` and `/z-implement-all`.
- `scripts/run-retro.sh` — consumes `events.jsonl`, task outcomes, review retries, doc drift, final status → writes `RUN_RETRO.md` and `memory-candidates.jsonl`.
- New `memory-scout` subagent (or extend `doc-fetcher` with write-candidate mode); proposes structured candidates only, never writes.
- `/z-suggest-memory` ergonomics: batch review, edit-before-save, skip reasons; post-run batch mode defaults each item to Skip while making "skip all" visible.
- Telemetry events: `memory_candidate_created`, `memory_candidate_accepted`, `memory_candidate_skipped`, `memory_retrieved`, `memory_used`, `memory_stale`, `memory_contradicted`.
- Memory utility sidecar index: `retrieval_count`, `accepted_use_count`, `ignored_count`, `last_used`, `staleness_score`.
- `/z-review-all` Phase 3.7: doc-fetcher fetches relevant memories for repeated review failures, prior rejected fixes, and known repo hazards **before** summarizing context.
- `/z-debug` Phase 9: make memory call explicit in the spec — force memory-candidate pass over root cause, missed signal, prevention.

### What would change my mind
- Users frequently skip all candidates after high-signal failures → gate is too noisy or badly timed.
- Accepted memories rarely retrieved later → schema or indexing is wrong.
- Retrieved memories don't change agent behavior → problem is prompt integration, not persistence.
- Stale or contradictory memories cause wrong fixes → memory expiration / drift detection must come before any RL-style scoring.
- Hermes' actual implementation shows a substantially different mechanism with strong empirical results → reframe around their verified loop.

---

## Framing: Gemini — "Continuous RL: Friction Signals as Negative Reward"

### Framing
Shift the paradigm from "Memory as an Active Interruption" to "Memory as Continuous Reinforcement Learning." Instead of relying on the user to manually invoke `/z-improve` or `/z-suggest-memory`, the harness should treat the execution lifecycle — specifically review rejections and implementation retries — as an RL environment. By monitoring negative reward signals (errors, linters, rejected MRs), the harness can passively formulate policy updates (draft memories) in the background and present them as a low-friction "Commit these lessons?" summary at the end of the run.

### Core hypothesis
Hook into existing telemetry (`events.jsonl`) to detect friction (e.g., `task_review_retry`, test failures in `z-implement-all`). Mimic an RL update phase by automatically spinning off a background task to draft a structured memory. Surface these pre-computed, high-context drafts at the very end of `/z-review-all` or `/z-implement-all` as a simple **Approve/Reject batch**. Drastically increases capture rate of long-term behavioral fixes without mid-task interruption.

### Risks
- **Alert/review fatigue.** If the system synthesizes a memory for every trivial syntax error, users develop muscle memory to blindly reject the post-run batch.
- **Misattribution of root cause (hallucinated lessons).** LLM drafting may incorrectly correlate a fix to the wrong architectural rule — pollutes `docs/llm/*.json` with actively harmful constraints that derail future `doc-fetcher` runs.
- **Tag dilution.** Auto-generated drafts might overuse or incorrectly apply the controlled `TAGS.txt` seed, making downstream retrieval less precise.

### Plan implications
- Modify `commands/z-implement-all.md` and `commands/z-review-all.md`. At loop completion, evaluate telemetry. If friction thresholds met (e.g., `retry_count > 0`), invoke a new post-run **Phase X: Auto-Retro**.
- New `--draft-batch` / `--auto-retro` flag on `/z-suggest-memory` — runs non-interactively based on the run's event log, compiling a proposed list of memories.
- Final output of a complex run becomes a reviewable diff of proposed memories. Default action remains Cancel/Reject to ensure quality, but cognitive load reduced to read-and-approve.
- Formally spec the missing Phase 9 of `commands/z-debug.md` to push its post-mortem context into the same drafting pipeline.

### What would change my mind
- Telemetry shows users reject >80% of auto-drafted memories → signal-to-noise too poor; abandon RL-mimicry of auto-drafting and instead enforce a hard manual prompt: *"You had 3 retries. What did we learn? (Leave blank to skip)"*
- Background synthesis adds >15–20s to end of a run.

---

## Anti-bias check

**Framing.** Gemini's RL-reframing is the boldest *reframe* but is more rhetorical than operational. Codex's "skipping is an intentional act" + learning diff is the sharpest *actionable* framing. Claude's "verify existing memories, not just write new ones" is the most *unique* contribution — neither Codex nor Gemini explicitly addresses memory-as-invariant verification. **Codex wins on operational clarity; Claude wins the novelty axis.** (Not Claude-favoring on overall framing; Claude's contribution is narrower but orthogonal.)

**Core hypothesis.** Codex enumerates 5 concrete mechanisms including the retrieval smoke-test (would doc-fetcher actually find this?) — a critical feedback loop neither peer mentions. Gemini's friction-trigger is sharp but is a subset of Codex's mechanism set. Claude's confirm-refute-NA on existing memories is genuinely novel. **Codex wins on breadth; Claude wins one mechanism Codex omits.** (Not Claude-favoring.)

**Risks.** Codex's 5 risks include the only mention of memory expiration (`stale_if`, `valid_until`, `confidence`) and the only warning against model-specific overfitting. Gemini uniquely surfaces **tag dilution against `TAGS.txt`** — neither Codex nor Claude noticed this. Claude's "confirmation theater" is real but Codex's "false authority" subsumes it. **Codex wins overall; Gemini wins one unique risk.** (Not Claude-favoring.)

**Plan implications.** Codex names specific files/scripts (`run-retro.sh`, `memory-scout`), a complete telemetry event list, and a utility sidecar index — most directly executable. Gemini cleanly identifies the `/z-debug` Phase 9 spec gap (Claude only mentions Phase 9 obliquely; Codex names it). Claude's `retro-gater` is one Haiku agent. **Codex wins on operational concreteness.** (Not Claude-favoring.)

**Change-my-mind.** Codex lists 5 distinct falsifiers covering acceptance rate, retrieval, behavior change, drift, and Hermes verification — the most complete. Gemini provides a concrete numeric threshold (>80% reject, >15–20s synthesis latency). Claude's "consultants contradict memories" is sharp but narrow. **Codex wins on coverage; Gemini wins on operational thresholds.** (Not Claude-favoring.)

**Summary.** Codex wins or co-wins every section on operational dimensions. Claude contributes one orthogonal mechanism (verify existing memories) absent from both peers. Gemini contributes the tag-dilution risk and the falsification thresholds. None of the section calls favor Claude, so no Claude-favoring justification is required — but Claude's "Memory as Contract" mechanism should be folded into any chosen direction because it addresses a real gap the other framings miss.

## Orchestrator recommendation

**Codex framing as the spine**, with Claude's confirm-refute-NA gate folded in as a sub-mechanism and Gemini's tag-dilution risk + numeric falsification thresholds carried forward. Codex's framing already accommodates both: the candidate-classifier can produce "verify this existing memory" candidates alongside new-memory proposals, and Gemini's thresholds become explicit acceptance criteria in `/z-plan`. The user is free to override.
