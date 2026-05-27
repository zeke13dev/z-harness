# Phase 1 Scaffolding — postmortem-memory-nudge

## Topic
z-harness memory system post-mortem: whether to auto-run or nudge user toward memory authoring after /z-implement-all, and why the existing pipeline produces zero memories.

## Doc-fetcher synthesis

Relevant z-harness concepts:

- **scripts** — `scripts/run-memory-review.sh` is the gate script; exits 0 always. Skip conditions: missing `Z_HARNESS_PLAN_DIR`, empty diff, zero completed tasks (when parent=implement-all), TAGS.txt missing. Writes `cumulative.diff` on ready path. `scripts/regenerate-memories-flat.py` atomically regenerates `MEMORIES-FLAT.md` from `docs/llm/*.json` memories arrays.

- **review-agent** (`agents/review-agent.md`) — Haiku subagent dispatched by Phase 9. Reads run events + cumulative diff + SPEC.md + INDEX.json. Proposes 0-3 candidate memories (4 signal types: mistake-prevention, decision-rationale, workflow-improvement, retrieval-gap). Returns a single fenced ```json block. Does NOT write — orchestrator owns all writes via /z-suggest-memory.

- **z-implement-all Phase 9** — Fires after Finalize push-notify, before session ends. All failure paths SILENT (no halt, no retry, silent skip). Uses AskUserQuestion per candidate with options Accept/Edit/Skip/Skip-all. Accept → dispatches z-suggest-memory --from-candidate-json with source incident:<RUN_ID>.

- **z-review-all Phase 7** — Same pattern as Phase 9 of implement-all. Uses jq for JSON construction.

- **z-suggest-memory** — Sole memory-mutation path. Validates schema, writes to `docs/llm/<slug>.json`, regenerates MEMORIES-FLAT.md. Called mandatorily from /z-debug post-mortem and /z-improve retro per description header. Can be called with --from-candidate-json.

## Known empirical state

- `docs/llm/MEMORIES-FLAT.md` is **2 lines** (header only). Zero memories written via the pipeline.
- User's GLOBAL auto-memory (`~/.claude/projects/.../MEMORY.md`) has ~7 entries from Claude Code's generic auto-memory — a parallel system not connected to z-harness.
- qt-bot operates remotely on zeke-pc; no confirmed docs/llm/INDEX.json deployed there → Phase 9 hard-skips on every qt-bot z-harness run due to missing Z_HARNESS_PLAN_DIR or TAGS.txt.

## Key architectural facts

- Phase 9 is "soft": described as firing "after the Finalize push-notify, before the session ends"
- The skip condition for `no_plan_dir` (missing `Z_HARNESS_PLAN_DIR`) is the FIRST check in run-memory-review.sh — if the env var isn't set, the whole phase silently bails.
- The `Z_HARNESS_PLAN_DIR` env var must persist from when /z-implement-all sets it all the way through Phase 9 execution.
- z-suggest-memory description says "Called mandatorily from /z-debug post-mortem and /z-improve retro" but Phase 9 is the ONLY auto-path; /z-debug has no explicit /z-suggest-memory dispatch in its command file (grep found nothing).
- /z-improve is opt-in harness retro, distinct from Phase 9's implementation retro.
- The 3-candidate cap and Haiku model are cost constraints by design.
- AskUserQuestion is the interaction model — user must be present and respond.

## Constraints to preserve
- Cheap by default (Haiku, 3-candidate cap, silent skip)
- Strict write boundary — only /z-suggest-memory mutates
- approval_only notification policy is default
- /z-improve is opt-in, retros HARNESS itself; distinct from Phase 9 which retros IMPLEMENTATION diff

## Input hash
52cc3a2678625110
