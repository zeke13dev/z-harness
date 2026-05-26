# Shipped — lookup-subagent

Run: 20260524T201705Z-review
Disposition: **Fix the blocker + amend SPEC; accept remaining Prong B gaps as deferred scope.**

## Fixes applied this run

1. **BLOCKER (drift):** `docs/llm/lookup-contract.json` L8 — refused-response invariant rewritten to match the agent file's actual format (`Refused: <category> — <detail>` as the first `## Answer` line, with category ∈ {mutation_blocked, out_of_scope, auth_missing}).
2. **SPEC amendment §File 1:** illustrative JSON updated to use the canonical `key_invariants`/`key_files`/`related_concepts` shape with a SCHEMA NOTE explaining the post-review correction.
3. **SPEC amendment §File 4b:** required-fields list rewritten to use the canonical schema; gotchas/prompt-injection notes folded into `key_invariants` / `summary` per actual repo convention.

## Accepted as deferred scope (Prong B gaps, not blockers)

These do not break the current implementation. They are worth addressing if/when the agents see real traffic, but are not gating ship:

- **Confidence-scale `medium` undefined in SPEC §File 2 step 9.** Definition lives only in human-tier doc. If `medium` is used inconsistently across agents in the future, amend SPEC.
- **Cache-vs-source freshness precedence.** SPEC says stale cache → `confidence: low`, but doesn't specify whether a fresh fetch supersedes a stale cache. Behavior: agents should prefer fresh fetches; this is an implementer convention not currently load-bearing.
- **qt-market-lookup deployment caveat.** Staged file is NOT dispatchable until T011 (REMOTE-skipped) substitutes `<KALSHI_CLIENT>` and `<PAPER_ENV_VAR>`. Noted here so the user remembers when they re-engage with the qt-bot side.
- **Commands-truncation vs 3 KB cap conflict.** Already user-accepted in Phase 5 (escape via raw-artifact pointer). SPEC could be clearer; deferred.
- **Agent lifecycle underspecified.** No dispatch-syntax / force-fresh / retry-budget rules. These are emergent properties — defer until usage demands.

## Minor items left as-is

- INDEX `lookup-contract` entry's `source_files` lists only `agents/external-lookup.md`; consultants disagreed on whether to add `docs/llm/lookup-contract.json` (self-reference). Left as-is per Gemini's pragmatic argument.
- Cache-key normalization, GC policy, doc-fetcher discovery keywords — all deferred until usage data justifies.

## Status

- All [x] tasks in TASKS.md remain valid.
- T011 / T012 remain REMOTE-skipped — invoke `qt-bot-remote` from a clean session when ready to deposit qt-market-lookup.
- Plan considered **SHIPPED** (z-harness side). qt-bot side awaits manual deposit.

## Recommended next

- `/z-maintain-docs` — refresh `docs/llm/INDEX.json` `last_updated` markers if needed (the two new concepts are already fresh as of 2026-05-24).
- For qt-bot deposit: `qt-bot-remote` skill with `z-harness/plans/lookup-subagent/staging/qt-market-lookup.md` as input.
