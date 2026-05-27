# Phase 0 — Premise check

## Source artifacts
- BRAINSTORM.md (chosen_framing: codex)
- Empirical verification this turn:
  - `docs/llm/MEMORIES-FLAT.md` → still 2 header lines, 0 memories
  - `commands/z-debug.md` + `skills/z-debug/SKILL.md` → no `/z-suggest-memory` invocation
  - `skills/z-improve/SKILL.md:163-211` → confirmed call to `/z-suggest-memory`
  - qt-bot lives on `zeke-pc` remote; deployment unverifiable from this host

## Refined premise

The Codex framing (instrument before redesign) is accepted. One brainstorm claim
needed sharpening:

> Gemini called `/z-debug` ↔ `/z-suggest-memory` "vaporware integration."

That's half-right:

- `/z-improve` is genuinely wired (line 163-211 dispatch). Just needs a smoke
  test that the dispatch actually executes when the retro runs.
- `/z-debug` is the real gap. Its Post-mortem section (Phase 9, mandatory) is
  rich — writes action items, optionally invokes `/z-mr-review` for
  preventative-finding promotion, optionally seeds `test-followups.md` — but
  never proposes memory candidates. The post-mortem is the single highest-signal
  z-harness phase per token spent (the user is already reflecting on what went
  wrong), and currently produces zero memories.

## What this plan will deliver

Carried forward from BRAINSTORM (Codex framing):
1. Phase 9 four-state terminal taxonomy + structured telemetry events for each.
2. Audit env propagation across Phase 9 dispatch boundaries.
3. Verify qt-bot remote has `docs/llm/INDEX.json` + `TAGS.txt` (via
   qt-bot-remote skill at implementation time).
4. Reconciled scope from this premise check:
   - Wire `/z-debug` Post-mortem to dispatch the `review-agent` (or a thin
     equivalent) so action-items become memory candidates.
   - Add a smoke-test path for `/z-improve` → `/z-suggest-memory` to confirm
     the existing integration fires end-to-end.

## What this plan will NOT deliver (carried from BRAINSTORM)

- Auto-run-on-every-run policy change.
- Standalone `/z-postmortem` skill (Gemini suggestion, rejected).
- Haiku→Sonnet model upgrade for review-agent (Gemini suggestion, deferred —
  only revisit if instrumentation shows the agent is reaching execution and
  producing zero candidates).
- Memory-candidate UX redesign (deferred to data).

## Premise accepted.
