# Decisions — memory-self-improve-loop (v1 review-agent)

Inputs: BRAINSTORM.md (Codex framing, scoped), RESEARCH.md (Hermes mechanism map), doc-fetcher synthesis (insertion points, /z-suggest-memory CLI contract, /z-stats event schema).

---

## D1. Agent name + file location

- **Options:**
  - `agents/review-agent.md` — matches user request; generic enough to extend
  - `agents/memory-reviewer.md` — descriptive but collides semantically with existing `reviewer.md` (Codex code-reviewer)
  - `agents/retro-agent.md` — closer to "retrospective" framing
- **Tentative call:** `agents/review-agent.md` (user explicitly named it).
- **Consult?** No — naming under user authority; collision risk with `reviewer.md` is minor (different file, distinct frontmatter description).
- **Trigger:** none — obvious-from-existing-convention.

## D2. Subagent model

- **Options:**
  - Haiku — matches Hermes "background fork is cheap" intent + cap of 3 candidates (small output budget)
  - Sonnet — better candidate quality, but ~10x cost per invocation
- **Tentative call:** Haiku. The candidate output is small (≤3 candidates × ~120 char text each = trivial); input is events.jsonl + diff + SPEC.md slice which Haiku handles. If candidate quality is poor empirically, upgrade in v2.
- **Consult?** No — mirrors established pattern (doc-fetcher, complexity-classifier are Haiku; implementer/reviewer are Sonnet/Opus). Aligned with project memory `feedback-subagent-model-selection`.
- **Trigger:** none.

## D3. Lifecycle integration — WHERE to fire (CONSULT)

- **Options for /z-implement-all:**
  - (a) Inside Finalize block, BEFORE the push-notify (lines 499-605, after task-counts summary)
  - (b) NEW phase 9 after Finalize, BEFORE push-notify
  - (c) Inside push-notify path — surface candidates as the push-notification body
- **Options for /z-review-all:**
  - (d) After Phase 6 promote-findings, BEFORE `.review_state.json` cleanup
  - (e) After Phase 6, AFTER cleanup, BEFORE push-notify
  - (f) Inside Phase 6 itself — fold review findings INTO candidate memories
- **Tentative call:** (a) and (e) — keep Finalize/Phase 6 outputs unchanged, add a single new phase block immediately before push-notify in each. Cleanup runs first so review-agent never sees stale `.review_state.json`. Phase block name: `phase_memory_review` (consistent with Codex framing's `phase_memory_retro` but renamed to match z-harness "review" vocabulary).
- **Consult?** **YES.** This is the highest-blast-radius integration call. Wrong placement breaks user-facing UX of both major commands. Wire-format / lifecycle decision.
- **Trigger:** Cross-module (two commands), affects user-facing ordering, public-surface (the order users see notifications and prompts).

## D4. Candidate JSONL schema (CONSULT)

- **Options:**
  - (a) Minimal: `{claim, concept_slug, tags[], evidence[]}` where `evidence` is array of `"file:line"` strings
  - (b) Aligned with `/z-suggest-memory` memory object: `{type, text, tags[], source, date, expires_or_review_after, suggested_concept_slug, evidence_citations[]}`
  - (c) Codex-framing inspired: add `candidate_kind: "mistake-prevention" | "decision-rationale" | "workflow-improvement" | "retrieval-gap"`
- **Tentative call:** (b) + add `candidate_kind` from (c). Rationale: aligning with `/z-suggest-memory`'s memory object means the orchestrator can pipe candidates straight through to `/z-suggest-memory --source <prefix:ref>` (it has a `--source` flag and pre-supply path that bypasses Phase 3d collection — confirmed in doc-fetcher synthesis). `candidate_kind` is non-load-bearing metadata for v2 friction analysis but cheap to include now. `source` field for v1 = `incident:<run_id>` to match the existing prefix-regex `^(incident:|spec:|debug:|human_review:).*$`.
- **Consult?** **YES.** Schema is a wire format consumed by both review-agent (writer) and orchestrator (reader → /z-suggest-memory caller). Cheap to add fields now; expensive to change later if any candidate file format gets committed/audited.
- **Trigger:** Wire format, persistence (JSONL), reversibility cost if schema changes mid-flight.

## D5. memory-candidates.jsonl location

- **Options:**
  - (a) `$RUN_DIR/memory-candidates.jsonl` (per-run, ephemeral with run archive)
  - (b) `$BASE/memory-candidates.jsonl` (per-plan, appended across runs of same plan)
  - (c) Global `z-harness/memory-candidates.jsonl` (cross-plan rolling log)
- **Tentative call:** (a). Matches `$RUN_DIR/events.jsonl` convention (per-run). v2 can add a global aggregator if cross-run analysis is needed. Append (not overwrite) inside the same run if review-agent fires for both implement-all and review-all in the same session (different RUN values, different files — collision impossible).
- **Consult?** No — follows existing $RUN_DIR convention.
- **Trigger:** none.

## D6. Batch UX — one AskUser per candidate vs single batched

- **Options:**
  - (a) Single `AskUserQuestion` with multi-select per-candidate (1 question, N options × 3 actions = combinatorial blow-up)
  - (b) N sequential `AskUserQuestion` calls (one per candidate, 4 options each: Accept / Edit / Skip / Skip-all-remaining)
  - (c) Single `AskUserQuestion` with `multiSelect: true` listing candidates as checkboxes ("which to accept?") + follow-up for skip reasons
- **Tentative call:** (b) — N sequential. Max N=3 candidates, so worst case 3 prompts. Each prompt is small, fits AskUserQuestion's max-4-options cleanly (Accept / Edit / Skip / Skip-all-remaining). "Skip-all-remaining" exit lets a uninterested user bail after the first prompt without seeing the rest.
- **Consult?** No — N≤3 makes the UX choice essentially trivial; sequential is the simplest readable pattern.
- **Trigger:** none.

## D7. Skip-conditions — when to NOT fire the review-agent (CONSULT)

- **Options:**
  - (a) Always fire (waste cost on empty runs but predictable)
  - (b) Skip if `done_tasks == 0`, `all_skipped`, `halted_early_for_blocker`
  - (c) Skip if cumulative diff is empty (`git diff <base>..HEAD` returns nothing)
  - (d) Skip if `events.jsonl` has fewer than N events (proxy for "trivial run")
- **Tentative call:** (b) + (c). Skip if: zero tasks done, ALL tasks skipped, run halted before any task completed, OR cumulative diff is empty. This eliminates the obvious "nothing happened, nothing to remember" cases. Threshold (d) is unnecessary noise — if diff is non-empty something happened.
- **Consult?** **YES.** Skip-policy directly controls how often the agent fires → cost amplifier (could 2-3x review-agent invocations vs. conservative skip). Also user-trust: if it fires on every trivial run and produces zero candidates, users will start ignoring the prompt.
- **Trigger:** Cost-bearing decision under user concern (we explicitly committed to measuring cost). UX trust signal.

## D8. Failure-mode policy (CONSULT)

- **Options:**
  - (a) Hard-halt: if review-agent errors/times-out, halt the parent command (block push-notify)
  - (b) Soft-skip: log `review_agent_failed` event, push-notify with "memory review skipped due to <reason>", proceed to finalize normally
  - (c) Retry once with same prompt then soft-skip
- **Tentative call:** (b). The parent command's primary deliverable (TASKS.md status, REVIEW-TASKS.md) is already complete by the time the review-agent fires — a failed memory review must not block the user from seeing that result. v1 deliberately ships without retry to keep the cost story simple ("at most one Haiku call per major command").
- **Consult?** **YES.** Failure-mode is a contract; choosing wrong here makes the agent infrastructure unreliable or expensive. The (a) → (b) flip is a one-way door if users rely on the halt behavior.
- **Trigger:** Concurrency / failure-handling contract. Reversibility.

## D9. Tool-whitelist enforcement (CONSULT)

- **Options:**
  - (a) Declarative-only: `tools: Bash, Read` in the agent's frontmatter, with prompt instructing it to ONLY call `/z-suggest-memory --dry-run` to validate then return candidates as plain text (orchestrator handles actual writes)
  - (b) Declarative tools: `Bash, Read, Edit` and trust the prompt to constrain behavior
  - (c) Subagent writes directly via Bash invocation of `/z-suggest-memory` — orchestrator gives credentials/context
- **Tentative call:** (a). Mirror Hermes's "fork can only call memory + skills tools" by giving the subagent NO write capability — it returns candidates as structured plain text on stdout, orchestrator parses + writes the JSONL + dispatches `/z-suggest-memory` itself per user accept. This is the cleanest separation: subagent reasons about what to remember; orchestrator owns all writes (matches our project memory `feedback-subagent-model-selection`'s spirit + maintains `/z-suggest-memory` as sole-authoring contract).
- **Consult?** **YES.** Security boundary — wrong choice here lets a Haiku subagent silently mutate `docs/llm/` outside `/z-suggest-memory`'s schema validation. Same risk Hermes's `mark_agent_created` provenance is designed to mitigate, and we have a stricter contract (sole-authoring path) we shouldn't undermine.
- **Trigger:** Security / authoring contract. Public-surface guarantee (`/z-suggest-memory` is the sole writer).

## D10. Token-spend event shape

- **Options:**
  - (a) Reuse `phase_end` with phase name `memory_review` carrying `subagent_input_tokens`/`subagent_output_tokens`
  - (b) New event `review_agent_call` with `subagent_model: "haiku"`, `subagent_input_tokens`, `subagent_output_tokens`, `candidates_emitted`, `accepted`, `skipped`, `edited`
  - (c) Both (a) for /z-stats Phase 2 (wall time) AND (b) for /z-stats Phase 3 (token spend)
- **Tentative call:** (c). `/z-stats` Phase 2 already groups by `kind | endswith("_end")` so `phase_end` with `phase: "memory_review"` slots in automatically. `/z-stats` Phase 3 groups by `subagent_model` — emit `review_agent_call` with the same field names (`subagent_model`, `subagent_input_tokens`, `subagent_output_tokens`) so it shows up in the existing table without /z-stats changes.
- **Consult?** No — event shape is mechanical, mirrors existing conventions.
- **Trigger:** none.

## D11. Candidate count cap

- **Options:** 0-3 (Hermes-like, conservative), 0-5 (more breadth), unbounded with hard timeout
- **Tentative call:** 0-3. Matches scope spec; forces the agent to rank/select (signal of quality). v2 can lift if data shows ceiling-bound.
- **Consult?** No.
- **Trigger:** none.

## D12. Stale-candidate handling on re-run

- **Options:** Overwrite existing `memory-candidates.jsonl` (different RUN = different file, never collides); append within run (impossible — review-agent fires once per command run)
- **Tentative call:** N/A — per-run file makes this a non-question.
- **Consult?** No.
- **Trigger:** none.

## D13. Cumulative-diff base reference

- **Options:**
  - (a) `git merge-base HEAD origin/main` — diff against main branch base
  - (b) Pre-implement-all snapshot ref (would require capturing SHA at /z-implement-all phase 0)
  - (c) `HEAD~N` heuristic
- **Tentative call:** (a). The branch base is the most semantically meaningful "what changed during this plan." If the user is on main directly, fallback to `HEAD~5` then truncate to 200 lines. Existing convention check: doc-fetcher synthesis didn't surface an existing diff-collection pattern; need a Read of one /z-implement-all phase to confirm whether base ref is already captured — if so, reuse it.
- **Consult?** No — small enough call; if (a) is wrong we'll catch it during implementation.
- **Trigger:** none.

---

## Summary

**Consult-flagged (5/5 — at cap):**
- D3. Lifecycle integration (where to fire in both commands)
- D4. Candidate JSONL schema
- D7. Skip-conditions
- D8. Failure-mode policy
- D9. Tool-whitelist enforcement strategy

**User gate:** flip any consult flag, override any tentative call, kill scope. ≤5 consult-flagged is at the cap.
