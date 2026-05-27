# PLAN — postmortem-memory-nudge

## Goal

Make the existing z-harness memory-review pipeline legible. Today it fires
Phase 9 / Phase 7 silently, has inconsistent event emission, mis-classifies
`tags_missing` as agent failure, and `no_plan_dir` / `missing_args` emit
nothing at all. As a result MEMORIES-FLAT.md has been empty for the entire
lifetime of the repo. Per the Codex framing from BRAINSTORM.md, instrument
before redesign.

In the same shipping wave, close the `/z-debug` ↔ `/z-suggest-memory` gap:
post-mortems are the densest memory signal in the harness and currently
produce zero candidates.

## Decisions (with rationale)

See [phase3-decisions-final.md](archive/20260527T045853Z-postmortem-memory-nudge/phase3-decisions-final.md)
for the full record of the 5 consult-flagged decisions, the cross-LLM
verdict, and the mandatory "one reason it might be wrong" pushback per
decision.

Headline:
- **D1** — terminal-state classification lives in `run-memory-review.sh`.
- **D2** — new `memory_review_terminal` event (not overload `phase_end`).
- **D3** — fix the `tags_missing` mis-classification.
- **D5** — wire `/z-debug` Phase 9b → review-agent (gated on `status: shipped`).
- **D7** — add optional `debug_md_path` to agent input contract.
- **D11** — push-notify on `skipped_broken_context`, deduped per
  `(slug, skip_reason)`, honors `Z_HARNESS_NOTIFY=off`.

## Non-goals

- No new `/z-postmortem` skill.
- No model upgrade for review-agent (Haiku → Sonnet).
- No auto-run policy change.
- No retroactive event migration.
- No candidate UX redesign.

## Approved shortcuts

None. Both consultants endorsed the robust solution everywhere.

## Phases

### Phase A — Helper script (D1, D2, D3, D4, D6)
Extend `scripts/run-memory-review.sh` to:
- Accept `parent_command: debug` with new skip condition `debug_not_shipped`.
- Emit a single `memory_review_terminal` event at every exit path.
- Map STATUS values to the 4-state taxonomy.
- Emit DEBUG.md path on stdout line 4 when `parent_command: debug` and
  `STATUS: ready`.
- Stop emitting `review_agent_failed` for `tags_missing`.

### Phase B — Agent input contract (D7)
Update `agents/review-agent.md`:
- Add optional `debug_md_path` field.
- Add `debug` to `parent_command` enum.
- Document the "primary artifact by parent_command" rule.
- Add the `parent_command: debug` candidate-generation guidance
  (filter for generalizable invariants).

### Phase C — Orchestrator wiring (D11)
Update `skills/z-implement-all/SKILL.md` Phase 9 and
`skills/z-review-all/SKILL.md` Phase 7:
- After agent dispatch, emit `memory_review_terminal` with `state:
  ran_empty` (agent returned `[]`) or `state: needs_user` (≥1 candidate).
- After the user-gate loop, emit a final `memory_review_terminal` with the
  `accepted` count.
- Implement push-notify-on-broken-context with dedup per
  `(slug, skip_reason)` and `Z_HARNESS_NOTIFY=off` honoring.

### Phase D — `/z-debug` Phase 10 memory-review step (D5)
Insert a memory-review step inside Phase 10 of `skills/z-debug/SKILL.md`
(and mirror in `commands/z-debug.md`), only on the `status: shipped`
finalize branch. (Earlier "Phase 9b" plan was rejected in Phase 7 review:
DEBUG.md has no YAML frontmatter, so the grep-based gate didn't work.)
- Clear `$BASE/.notify-dedup-session` at top of Phase 10.
- Call helper with `parent_command: debug`. Parse with `mapfile`.
- Dispatch review-agent with `parent_command: debug` and `debug_md_path`
  set from stdout line 5.
- Run the AskUserQuestion loop with source `incident:debug-<slug>-<RUN>`.

### Phase E — `/z-stats` consumer (D10)
Update `skills/z-stats/SKILL.md` Phase 4b:
- Read `memory_review_terminal` events.
- Group by terminal state across last 10 runs.
- Read both old and new event shapes (back-compat for runs predating this
  change).

### Phase F — Verification (D8, D9)
- qt-bot-remote check: confirm `docs/llm/INDEX.json` + `TAGS.txt` exist on
  zeke-pc. If absent, recommend `/z-init-docs` on remote.
- `/z-improve` smoke test: run `/z-improve postmortem-memory-nudge` on
  this very slug after the implementation finishes. Confirm a
  `suggest_memory_called` event lands.

## Phase ordering and dependencies

```
A (helper) ──┐
             ├─→ C (orchestrator) ──┐
B (agent) ───┘                      ├─→ E (z-stats consumer)
                                    │
A + B ──→ D (z-debug Phase 9b) ─────┘

Phase F (verification) — after all of A–E ship
```

## DRY / KISS / SOLID

- **DRY:** One helper, one event, one consumer pattern reused across three
  parent_command values.
- **KISS:** Flat 4-state enum. No new skill, no new model, no new policy.
  Existing helper extended in place rather than forked.
- **SOLID:** Helper owns skip-classification, orchestrator owns
  post-dispatch state, agent owns candidate generation, `/z-stats` owns
  aggregation. Each module has one reason to change.

## Risk register (carried from consult)

| Risk | Mitigation | Where addressed |
|---|---|---|
| Helper-script argument creep | Refuse logic beyond skip + classify | SPEC §`run-memory-review.sh` |
| `/z-stats` orphaned event consumer | Ship E in this plan | Phase E |
| /z-debug noise from speculative post-mortems | Gate on `status: shipped` | Phase D |
| Agent prompt complexity for spec-vs-debug | Explicit "primary by parent_command" rule | Phase B |
| Notification fatigue on broken_context | Dedup per (slug, skip_reason); `Z_HARNESS_NOTIFY=off` honored | Phase C |
