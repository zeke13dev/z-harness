# Final review — lookup-subagent
Run: 20260524T201705Z-review
Base ref: 380aca6
Diff stats: 8 files, 580 insertions, 1 deletion

## Prong A — Implementation drift

### Severity: blocker
- **[both]** Refusal-format mismatch between canonical contract and agents.
  - `docs/llm/lookup-contract.json` L8 says refused responses MUST include a `reason:` line in the body.
  - `agents/external-lookup.md` L42 and `docs/human/lookup-contract.md` L68 specify the format as: first `## Answer` line = `` `Refused: <category> — <detail>` ``.
  - Since `lookup-contract.json` is the canonical contract (per SPEC §File 2), this drift means the canonical doc misdescribes the actual envelope. Fix: amend `lookup-contract.json` L8 to match the agent file's format.
  - **Why this might be wrong:** the JSON's `reason:` wording could be read as "the body must contain reason information" (which the `Refused: <cat>` line does). But a reader looking only at the canonical contract would not know the exact line format — drift exists, severity stands.

### Severity: minor
- **[both]** INDEX.json `lookup-contract` entry has `source_files: ["agents/external-lookup.md"]` only — Codex points out SPEC §File 4 implies it should also list `docs/llm/lookup-contract.json`. Gemini argues self-reference is circular and the implementation is pragmatically correct.
  - **Recommendation:** leave as-is; if anything, amend SPEC.

## Prong B — Spec gaps

### Severity: major (spec should be amended; implementation may stand)
- **[gemini]** Confidence-scale `medium` used in agent code but never defined in SPEC §File 2 step 9 — only described in human-tier doc. SPEC should define all three levels canonically.
- **[codex]** Cache-vs-source freshness precedence ambiguous: SPEC §File 2 step 6 says stale cache (>24h) → `confidence: low`, but doesn't say whether a fresh fetch overrides a stale cache, nor how to score "fresh retrieval of stale-source content."
- **[codex]** qt-market-lookup deployment precondition: SPEC reads as if the staged file is dispatchable, but it has unresolved `<KALSHI_CLIENT>` / `<PAPER_ENV_VAR>` placeholders. T011 (REMOTE-skipped) is a hard prereq. SPEC should explicitly state qt-market-lookup is non-deployable until placeholders resolved.
- **[codex]** Commands-truncation conflict: SPEC says `commands:` is verbatim, never truncated, but the 3 KB cap can force truncation. SPEC has an escape via raw-artifact pointer but the rule isn't unambiguous. User already accepted this risk in Phase 5 — SPEC should record that explicitly so future readers don't re-litigate.
- **[codex]** Agent lifecycle underspecified: SPEC does not define dispatch syntax (how main thread invokes the agent), force-fresh behavior (caller bypassing cache), retry budget (how many fallback attempts after WebFetch + WebSearch fail), nor what triggers `STATUS: partial` vs giving up.

### Severity: minor (worth noting for future plans)
- **[both]** SPEC §File 4b documents the per-concept JSON schema as `key_concepts`/`invariants`/`gotchas`/`source_files`, but the actual repo convention (confirmed via `providers-registry.json`) is `key_invariants`/`key_files`/`related_concepts`. T001 retry already corrected the implementation. SPEC §File 4b should be amended to reflect repo reality so the next planner doesn't repeat the mistake.
- **[codex]** Cache-key collision: SPEC defines normalized cache key as `sha256(lowercase + whitespace-collapse)`. Two distinct queries can collide; either accept by design or namespace (`lookup-cache/v1/<sha256>.raw`).
- **[codex]** Cache expiry / GC: no policy defined.
- **[gemini]** Cache staleness check is best-effort: SPEC §File 2 step 6 assumes the agent can stat cache files, but Haiku may not have access to a persistent shared cache across invocations. Fallback: mark `medium` if age unknown.
- **[gemini]** doc-fetcher discovery: the new concept JSONs lack a `discovery_keywords` (or equivalent) field; relies on slug match only.

## Consensus vs disagreement

- **Both flagged (high confidence):**
  - Refusal-format mismatch (BLOCKER).
  - SPEC §File 4b documenting the wrong schema shape.
  - INDEX `source_files` discrepancy (minor; consultants disagree on whether it matters).

- **Only one flagged (worth manual scrutiny):**
  - Gemini-only: confidence-scale `medium` definition, cache-mtime accessibility, doc-fetcher discovery keywords.
  - Codex-only: cache-vs-source freshness precedence, command-truncation conflict, qt-market-lookup deployment caveat, agent-lifecycle underspecification, cache-key collision/GC.
