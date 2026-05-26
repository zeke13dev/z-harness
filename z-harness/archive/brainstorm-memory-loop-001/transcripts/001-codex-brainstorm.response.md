**Framing**

Treat memories as a post-run artifact, not a side quest. After `/z-review-all` and `/z-implement-all`, the harness should produce a small "learning diff" alongside code diffs: what changed, what almost went wrong, what decisions should not be reopened, and what should be retrieved next time. The user should approve persistence, but the system should make skipping an intentional act.

**Core hypothesis**

The best mechanism is a mandatory-but-lightweight retro gate at the end of major commands:

1. Generate `RUN_RETRO.md` automatically from telemetry, review retries, failures, doc drift, task deltas, and human overrides.
2. Ask a memory-candidate agent to emit 0-3 proposed `/z-suggest-memory` calls, each classified as:
   - `mistake-prevention`
   - `decision-rationale`
   - `workflow-improvement`
   - `retrieval-gap`
3. Default action should change from global **Cancel** to per-candidate **Skip**, with a required reason only when skipping all candidates after a nontrivial run.
4. Persist rejected candidates to `$RUN_DIR/memory-candidates.jsonl`, so skipped learning is auditable without polluting committed docs.
5. Feed accepted memories back into `INDEX.json` and `MEMORIES-FLAT.md` immediately, then run a retrieval smoke test: "would doc-fetcher find this for the concepts that triggered it?"

The Hermes-inspired angle should be reward shaping around memory utility, not autonomous memory writes. Add a simple bandit/RL-ish loop where memories get implicit rewards when later retrieved before a successful fix, review catch, or avoided retry, and negative signals when retrieved but ignored, contradicted, or associated with churn. Start with deterministic scoring before claiming RL.

**Risks**

The biggest risk is memory spam. If every run creates a lesson, retrieval quality collapses and users stop trusting the system. The gate needs a harsh novelty filter: no memory unless it prevents a plausible future mistake or preserves a decision likely to be re-litigated.

Second risk: false authority. A memory can outlive the facts that made it true. Every memory should carry `source_run`, `source_files`, `valid_until` or `stale_if`, and maybe `confidence`. Drift detection should apply to memories too, not just concept docs.

Third risk: annoying the user. A post-run gate that blocks completion with verbose prose will get bypassed. The prompt should be compact: "2 memory candidates from this run" with accept/edit/skip controls. Full retro details live in the run directory.

Fourth risk: overfitting to agent behavior. If memories mostly encode "the last model made this mistake," they may become brittle when the agent stack changes. Prefer repo-specific invariants and harness-process lessons over model-specific quirks.

Fifth risk: pretending Hermes-style RL is already validated here. Use the idea as inspiration: reward memory retrievals based on downstream usefulness. Do not import architecture claims without verifying Hermes' actual implementation.

**Plan implications**

Add a new post-run phase to both `/z-review-all` and `/z-implement-all`: `phase_memory_retro`.

Create a script, likely `scripts/run-retro.sh`, that consumes `$RUN_DIR/events.jsonl`, task outcomes, review retries, doc drift events, and final status. It should write `RUN_RETRO.md` and `memory-candidates.jsonl`.

Add a `memory-scout` or extend `doc-fetcher` with a write-candidate mode. It should never write memories directly; it only proposes structured candidates for `/z-suggest-memory`.

Change `/z-suggest-memory` ergonomics: keep explicit approval, but support batch review, edit-before-save, and skip reasons. Keep default Cancel for standalone use, but post-run batch mode can default each item to Skip while making "skip all" visible.

Add memory telemetry:
`memory_candidate_created`, `memory_candidate_accepted`, `memory_candidate_skipped`, `memory_retrieved`, `memory_used`, `memory_stale`, `memory_contradicted`.

Add a lightweight utility score to memory JSON or a sidecar index:
`retrieval_count`, `accepted_use_count`, `ignored_count`, `last_used`, `staleness_score`.

For `/z-review-all` Phase 3.7, include memory retrieval before compaction: doc-fetcher should fetch relevant memories for repeated review failures, prior rejected fixes, and known repo hazards before summarizing context.

For `z-debug`, make the Phase 9 memory call explicit in the spec: after post-mortem, force a memory-candidate pass over root cause, missed signal, and prevention.

**What would change my mind**

If users frequently skip all candidates even after high-signal failures, the gate is too noisy or badly timed.

If accepted memories are rarely retrieved later, the schema or indexing is wrong.

If retrieved memories do not change agent behavior, the problem is not persistence; it is prompt integration and task routing.

If stale or contradictory memories cause wrong fixes, memory expiration and drift detection need to come before any RL-style scoring.

If Hermes' actual long-term memory work shows a substantially different mechanism, especially one with strong empirical results, I would reframe this around their verified loop rather than a local reward-scored retrieval system.
