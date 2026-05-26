# PLAN — memory-self-improve-loop (v1 Hermes-inspired auto-review-agent)

## Goal

Replace manual `/z-improve` invocation with an automatic post-run review-agent that proposes 0–3 candidate memories per major run, surfaces them via batched accept/skip prompts, and routes accepted candidates through `/z-suggest-memory`. Make automatic memory capture the default outcome; preserve `/z-suggest-memory` as the sole authoring contract.

## Decisions (with rationale)

- **Agent name / model**: `agents/review-agent.md`, Haiku tier. Matches existing project memory `feedback-subagent-model-selection` (Haiku for read-and-synthesize; Sonnet/Opus only when interpretation is load-bearing). Candidate output is small (≤3 candidates × ~280 chars each).
- **Lifecycle placement**: new phase appended to `/z-implement-all` Finalize and `/z-review-all` Phase 6, both AFTER the existing primary-deliverable push-notify. A second push-notify (`memory_candidates_ready`) fires only when candidates > 0. Preserves the user contract that the existing push-notify means "run done."
- **Candidate schema**: aligned 1:1 with `/z-suggest-memory` memory-object fields + a `candidate_kind` enum (mistake-prevention / decision-rationale / workflow-improvement / retrieval-gap) carried for v2 friction analysis. Coupling between schemas is documented in SPEC.md.
- **Skip-conditions**: skip if `empty_diff OR all_tasks_skipped`. Halted runs are NOT skipped — they are high-signal.
- **Failure mode**: soft-skip on agent failure or malformed output. Failure surfaces in a louder push-notify with hint + in `/z-stats` Phase 4 (recent halts). Never blocks the parent command's primary deliverable.
- **Tool whitelist**: subagent has Read/Grep/Glob/Bash for inputs only — NO write capability. Returns candidates as a single fenced ```json block; orchestrator parses + writes the JSONL + dispatches `/z-suggest-memory` per user accept.
- **Batch UX**: sequential `AskUserQuestion` per candidate (max 3), 4 options (Accept / Edit / Skip-with-reason / Skip-all-remaining).
- **Per-run storage**: `$RUN_DIR/memory-candidates.jsonl`. No global aggregator in v1.
- **Telemetry**: new `review_agent_call` event using existing `subagent_model`/`subagent_input_tokens`/`subagent_output_tokens` field names so `/z-stats` Phase 3 picks it up without modification. Phase 4 of `/z-stats` gets an additional jq filter for `review_agent_failed` / `review_agent_malformed`. New Phase 4b lists recent `review_agent_call` events.

## Non-goals (v1)

Listed explicitly so a future reader sees the boundary:
- No utility scoring sidecar (retrieval_count, helpful_count, trust_score, asymmetric updates).
- No retrieval smoke-test ("does doc-fetcher find this back?").
- No friction-trigger drafting (the kind Gemini's brainstorm framing proposed).
- No confirm/refute on existing memories (the kind Claude's brainstorm framing proposed).
- No Atropos / RL training (not portable to Claude-API-only stack).
- No auto-acceptance for trusted slugs.
- No retry on review-agent failure (one shot, soft-skip).
- No per-call wall-clock timeout (Agent infrastructure limitation; ctrl-c is the escape).

## Approved shortcuts (with cost)

User pre-approved all six via the scoped framing acceptance:

1. **No utility scoring sidecar** → cannot tell empirically which memories are useful. v2 trigger: "memories feel like they don't pay off" (judgment-based, not telemetry-based).
2. **No retrieval smoke-test** → silent doc-index mismatches possible (memory exists but isn't retrievable for the concept it claims). v2 trigger: discovered miss during a planning run.
3. **No friction-trigger drafting** → end-of-command capture only. Misses signals that wanted to be remembered mid-run. v2 trigger: noticing repeated mid-run mistakes that end-of-run capture missed.
4. **No existing-memory verification** → stale memories silently mislead. v2 trigger: a planning run that acted on a wrong memory.
5. **No Atropos / RL** → not portable; zero opportunity cost.
6. **No auto-accept** → every accepted candidate requires user click. Slows accept-flow if user is rapidly approving obvious candidates. v2 trigger: user fatigue feedback.

## Ordered phases

1. **Agent file + helper script** — create `agents/review-agent.md` and `scripts/run-memory-review.sh`. No callers yet; both are inert.
2. **Wire into /z-implement-all** — add Phase 9 + dispatch + parse + batch UX. End-to-end testable on a no-op TASKS.md.
3. **Wire into /z-review-all** — add Phase 7 (the new one) mirroring the same structure.
4. **Sync skill files** — propagate the two command additions to `skills/z-implement-all/SKILL.md` and `skills/z-review-all/SKILL.md`.
5. **Telemetry surface in /z-stats** — extend Phase 4 jq filters; add Phase 4b for recent review_agent_call events.
6. **Documentation tier** — `docs/human/review-agent.md`, `docs/llm/review-agent.json`, INDEX.json update.
7. **Multi-IDE export** — run export scripts so `exports/{agy,codex,cursor}/` propagate.

## DRY / KISS / SOLID compliance

- **DRY**: `scripts/run-memory-review.sh` factors out skip-conditions + path resolution so both command files just call the helper. Schema aligned with `/z-suggest-memory` so no translation layer.
- **KISS**: one new agent file, one helper script, two phase additions, one new event kind, one new push-notify kind. Six explicit v1 deferrals keep scope honest.
- **SOLID**: review-agent reasons but does not write (single responsibility). Orchestrator owns writes. `/z-suggest-memory` remains sole authoring path. `/z-stats` owns telemetry surfacing.

## Risks not fully mitigated

- **Cost**: Hermes claims prefix-cache makes the fork cheap; under Claude API that doesn't transfer (TTL + exact-prefix). We measure cost per dispatch but have no automatic shutoff if cost balloons. Mitigation: `/z-stats` surfaces token spend; user can manually disable by deleting `agents/review-agent.md` or adding an env-var bypass (v2).
- **Candidate quality at Haiku tier**: an unverified assumption. If empirical accept-rate is poor we promote to Sonnet in a v2 amendment — telemetry already in place (`review_agent_call.candidates_emitted` vs `accepted` counter).
- **Consultant outage during this plan**: SPEC.md Phase 3 self-critique-only state is documented; re-consult in a future `/z-amend` once Gemini/Codex quotas reset.
