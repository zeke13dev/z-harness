# Phase 0 — Premise check

## Inputs ingested
- BRAINSTORM.md (Codex framing chosen, then heavily scoped for v1)
- RESEARCH.md (Hermes mechanism map; Atropos not portable, background-review fork is)
- User-confirmed scoped framing (5 explicit out-of-scope items deferred to gated v2 plans)

## Premise validation

**Does this solve the underlying problem?** Yes. The user's stated pain is (a) `/z-improve` is opt-in and rarely fired → memories don't get written, and (b) decisions get re-litigated. Auto-firing a review-agent at end-of-major-runs addresses (a) directly. (b) is partially addressed (new memories will accrue) but the verification-of-existing-memories angle is explicitly out of scope for v1 (Claude framing, deferred).

**Will the proposed approach work?** Yes — Hermes demonstrates the pattern in production (`/tmp/hermes-agent/agent/background_review.py:45-148` `_SKILL_REVIEW_PROMPT` + tool-whitelisted fork + `mark_agent_created` provenance). Porting requires no novel mechanism; the adaptations are (i) trigger at end-of-command instead of turn-count nudge (because our commands are short-lived) and (ii) route writes through `/z-suggest-memory` instead of direct file writes (because that's our sole authoring contract).

**Materially better path?** Considered: drop the new agent entirely and just auto-invoke `/z-improve` at end-of-run. Rejected because `/z-improve` is heavyweight (Phase 1-8 retro analysis) and would force a user prompt on every run regardless of whether there's anything memory-worthy. The review-agent is headless when no candidates exist — zero user friction in the empty-candidate case.

**One concern flagged to user:** Cost. Hermes's "prefix cache makes the fork cheap" claim does not transfer to Claude API (TTL + exact-prefix). Each end-of-run dispatches a fresh Haiku subagent. Per-run cost must be measured (token-spend telemetry, surfaced in /z-stats) — already in v1 scope.

## Premise accepted

Goal taken to be: ship a v1 auto-review-agent + memory-candidates batch UX that makes post-run memory capture the default outcome (not the opt-in afterthought), without requiring users to remember to type `/z-improve`. Scope is intentionally narrow so we have empirical signal on whether the pattern works before investing in v2 mechanisms (utility scoring, retrieval smoke-test, asymmetric trust, friction triggers, existing-memory verification).
