# Phase 1 — Context summary

## Wiring (verified from source)

**Phase 9 (z-implement-all) and Phase 7 (z-review-all) call `run-memory-review.sh`:**
- `scripts/run-memory-review.sh "$RUN" "<implement-all|review-all>"`
- Exit 0 always. Stdout line 1 = `STATUS: …`. Lines 2-4 (when ready) = absolute paths to cumulative diff, SPEC.md, TAGS.txt.

**Current STATUS vocabulary** ([scripts/run-memory-review.sh](scripts/run-memory-review.sh)):
| STATUS | Trigger | Currently logged as |
|---|---|---|
| `ready` | All gates passed | (no event from helper) |
| `skipped missing_args` | `<2` args | **NOTHING** |
| `skipped no_plan_dir` | `Z_HARNESS_PLAN_DIR` unset | **NOTHING** |
| `skipped empty_diff` | `git diff --quiet` true | `phase_end` w/ `skip_reason` |
| `skipped all_tasks_skipped` | `grep -c '[x]' TASKS.md == 0` AND parent == implement-all | `phase_end` w/ `skip_reason` |
| `skipped tags_missing` | `docs/llm/TAGS.txt` absent | `review_agent_failed` (semantically wrong) |

Plus orchestrator-side post-dispatch states:
- `review_agent_failed` (agent timeout / non-zero / dispatch error)
- `review_agent_malformed` (parse failure on agent return)
- Agent returned `[]` (0 candidates)
- Agent returned 1-3 candidates → `memory_candidates_ready` push-notify + user gate

## Mapping to Codex four-state taxonomy

| Terminal state | Subsumes |
|---|---|
| `not_applicable` | `empty_diff`, `all_tasks_skipped` — legitimately no signal |
| `skipped_broken_context` | `no_plan_dir`, `tags_missing`, `missing_args`, plus future env-propagation failures |
| `ran_empty` | Agent dispatched OK, returned `[]` after analyzing |
| `needs_user` | Agent returned ≥1 candidate (current `memory_candidates_ready` path) |

Orthogonal failure states (don't collapse into the 4-state) that still need clean events:
- `review_agent_failed` — agent didn't run cleanly
- `review_agent_malformed` — agent ran but output was unparseable

## /z-debug post-mortem (real gap)

[skills/z-debug/SKILL.md:417-459](skills/z-debug/SKILL.md) writes a `## Post-mortem` section to DEBUG.md (single file, not separate). Structure: Summary / Timeline / Root cause / Fix / Why we didn't catch it / Action items / Confidence. Mandatory. The post-mortem can invoke `/z-mr-review` and seed `test-followups.md`, but it **never dispatches review-agent** — so the highest-signal z-harness phase produces zero memory candidates.

Adding it requires:
1. New `parent_command: debug` accepted by `run-memory-review.sh` and `agents/review-agent.md`.
2. New `run-memory-review.sh` skip-condition appropriate for /z-debug (e.g., don't require TASKS.md `[x]` count).
3. Phase 9b in [skills/z-debug/SKILL.md](skills/z-debug/SKILL.md) after the post-mortem section is written: dispatch review-agent with DEBUG.md + cumulative.diff + the hypothesis posterior table as additional inputs.

## /z-improve (no gap, needs smoke-test)

[skills/z-improve/SKILL.md:163-209](skills/z-improve/SKILL.md) calls `/z-suggest-memory` directly with `concept_hints` derived from touched file paths. Salience is intentionally conservative: "**Default to Cancel** unless a genuinely novel anti-pattern surfaced." This is the right policy. The wiring is correct; just needs an end-to-end test that the dispatch fires when the retro completes.

## qt-bot deployment (remote-only)

`/Users/zeke/dev/qt-bot/` does not exist on this host. Verification must use the
`qt-bot-remote` skill at implementation time to check whether
`docs/llm/INDEX.json` + `docs/llm/TAGS.txt` exist under `~/dev/qt-bot/` on zeke-pc.
If absent, recommend running `/z-init-docs` on the remote.

## Env propagation surface area

`run-memory-review.sh` reads:
- `Z_HARNESS_PLAN_DIR` (required; controls BASE resolution)
- `ANTIGRAVITY_PLUGIN_ROOT` / `CLAUDE_PLUGIN_ROOT` (for log-event.sh path)

The orchestrator calls into it from Phase 9 / Phase 7. Need to verify these are
exported before the helper invocation, not assumed inherited.

## What this Phase did NOT cover (acknowledged gaps)

- Whether the candidate-generation prompt in [agents/review-agent.md](agents/review-agent.md)
  has bias toward Haiku-conservatism (Gemini "Haiku trap") — out of scope per
  Codex framing; revisit only if instrumentation shows the agent is firing and
  returning empty.
- Whether `/z-stats` Phase 4b correctly surfaces the new four-state events for
  human inspection — in scope as a verification task.
