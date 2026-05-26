# Phase 3 — Decisions final (self-critique only)

**Cross-LLM consultation: both consultants failed (session_limit on Gemini and Codex CLIs).** Proceeding with orchestrator-only self-critique per the "one concrete reason it might be wrong" rule. User has accepted the risk by saying "continue".

---

## D3 — Lifecycle integration (new `phase_memory_review` before push-notify)

**One reason this might be wrong:** Putting the review-agent BEFORE push-notify means the user's "main run complete" notification is delayed by however long the Haiku call takes (estimated 10-30s with model + I/O). If a user is multitasking and expects the push-notify to be the "run is done" signal, the delay changes the contract. Mitigation: keep the existing push-notify in place at its current spot; add a SECOND push-notify after the review-agent for "candidates ready" (only when candidates > 0). Two push-notifies on a useful run, one (existing) on a trivial run.

**Verdict:** Hold the placement decision (new phase after Finalize / after Phase 6 cleanup), but split push-notify into two events:
- Existing push-notify fires immediately when primary deliverable is complete (unchanged user contract).
- New `memory_candidates_ready` push-notify fires only if review-agent produced ≥1 candidate.

This is a refinement, not a reversal. Updating D3.

## D4 — Candidate JSONL schema (align with /z-suggest-memory memory object + candidate_kind enum)

**One reason this might be wrong:** Tying the wire format to `/z-suggest-memory`'s schema means any change to `/z-suggest-memory` requires a coordinated change to the review-agent. We're coupling two contracts together. Could decouple by giving the candidate file its own minimal schema and translating at the orchestrator-handoff boundary.

**Counter-reason:** The translation layer is exactly the kind of premature abstraction the global rules warn against. `/z-suggest-memory`'s schema is already stable (15-tag controlled set, three explicit modes, validated source-prefix regex). If it changes, the review-agent's prompt likely needs an update anyway. Direct alignment is the simpler choice.

**Verdict:** Keep the decision. Add an explicit note in SPEC.md: "candidates schema follows /z-suggest-memory; any change to either must update the other." This is a known coupling, not a hidden one.

## D7 — Skip-conditions (zero done / all skipped / halted early / empty diff)

**One reason this might be wrong:** "Halted early" is a meaningful learning event — if the run halted because a task hit a blocker, that's exactly the kind of thing we want a memory about ("when X, Y blocks"). Skipping on halt loses signal.

**Verdict:** Revise. Skip if zero diff OR all-tasks-skipped. Do NOT skip on halt — halted runs are high-signal. Add `halt_reason` to the events.jsonl slice the review-agent reads so it can synthesize a halt-specific candidate. Updating D7.

## D8 — Failure-mode (soft-skip on review-agent failure)

**One reason this might be wrong:** Silent skip means a misconfigured review-agent could go undetected for many runs. If user installs a bad agents/review-agent.md and never sees an error, they'll wonder why memories never get suggested.

**Verdict:** Soft-skip is right, but the push-notify on failure should be louder: include a literal `"action: check agents/review-agent.md or run /z-stats to see recent review_agent_failed events"` hint. Also: add `/z-stats` Phase 4 entry to surface `review_agent_failed` events alongside other halts. Updating D8.

## D9 — Tool-whitelist enforcement (subagent returns plain text; orchestrator writes)

**One reason this might be wrong:** Plain-text return parsing is fragile. If the Haiku subagent returns a malformed candidate block (wrong delimiters, extra prose, missing required field), the orchestrator has to either reject the whole batch or partial-parse. Hermes uses tool calls which give it structured payloads automatically.

**Counter-reason:** Hermes's tool-call route requires the subagent to have write capability (the tool IS the write). Our entire reason for the plain-text route is that we DON'T want the subagent to write. Bash-based JSON parsing of a fenced JSON block is well-trodden territory. Mitigation: require the agent to emit a single fenced ```json block with a list of candidate objects; orchestrator parses with `python3 -c 'json.loads(...)'`. Reject the whole batch on parse failure, log `review_agent_malformed`, soft-skip per D8.

**Verdict:** Keep the decision. Spec the wire format precisely (single fenced ```json block, array of objects matching D4 schema). Updating D9 with this constraint.

---

## Refined decisions (after self-critique)

- **D3 refined:** New phase fires AFTER existing push-notify in both commands. A second push-notify (`memory_candidates_ready`) fires only if candidates > 0. Existing push-notify timing unchanged.
- **D4:** Confirmed; document coupling in SPEC.md.
- **D7 refined:** Skip-conditions are now just `empty_diff OR all_tasks_skipped`. Removed "halted early" — halted runs ARE high-signal.
- **D8 refined:** Soft-skip with explicit hint in push-notify and `/z-stats` Phase 4 surfacing.
- **D9 refined:** Subagent must emit a single fenced ```json block; orchestrator parses with python json.loads; reject whole batch + log `review_agent_malformed` on parse failure.

## Shortcuts inherited from v1 scope (per BRAINSTORM/RESEARCH user-approved framing)

These are explicit shortcuts the user accepted upfront — listing for SPEC.md/PLAN.md visibility:

1. **No utility scoring sidecar** (retrieval_count / helpful_count / trust_score). Robust alternative: full sidecar with asymmetric trust updates. Cost of shortcut: cannot tell empirically whether accepted memories are ever useful → v2 work is gated on "feels like memories aren't paying off" rather than telemetry.
2. **No retrieval smoke-test** (would doc-fetcher find the new memory back?). Robust alternative: spawn a doc-fetcher call after accept and verify hit. Cost: silent doc-index mismatches where a memory exists but is not retrievable for the concept it claims.
3. **No friction-trigger drafting**. Robust alternative: monitor events.jsonl for retry-loops, trigger draft mid-run. Cost: only end-of-command capture; misses signal that wants to be remembered before user has moved on.
4. **No existing-memory verification** (confirm/refute on prior memories). Robust alternative: in addition to new candidates, present "this run touched concept X — is memory Y still true?" gates. Cost: memories never get re-validated; stale memories silently mislead.
5. **No Atropos / RL anything**. Cost: zero. (Not portable to Claude-API stack.)
6. **No auto-acceptance for trusted slugs**. Cost: every accepted candidate requires user click; if user has a "yes obviously" slug, no fast-path.

User has explicitly approved all six.

## Consultant outage note

Both Gemini and Codex CLIs returned `session_limit` at Phase 3 dispatch (logged: two `consultant_failed` events). Re-running Phase 3 will not work until quotas reset (4pm America/Los_Angeles). User chose to continue; proceeding to Phase 4-6 with orchestrator self-critique as the sole input. SPEC.md / PLAN.md will note this gap explicitly so a future `/z-amend` can re-consult if needed.
