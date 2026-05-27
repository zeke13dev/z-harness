# Phase 1 scaffolding — postmortem-memory-nudge

## Topic
Look into how the memory system is working (both in this repo `z-harness` and in
the consuming repo `qt-bot`). Decide whether we should have a post-mortem
analysis that is either (a) always run, or (b) nudged, after every
`/z-implement-all` run. Make sure the relevant skills actually nudge the user
toward authoring memory / running a retro instead of letting it die silently.

## Doc-fetcher synthesis (z-harness memory + retro)

Two-tier doc system:
- `docs/llm/INDEX.json` + per-concept `<slug>.json` (LLM tier, structured)
- `docs/llm/MEMORIES-FLAT.md` (denormalized, ripgrep-friendly index)
- `docs/llm/TAGS.txt` (controlled vocabulary; allows free-form extension)
- `/z-suggest-memory` is the **only** memory-mutation path.

Post-run review loop (already implemented):
- `/z-implement-all` Phase 9 and `/z-review-all` Phase 7 both call
  `scripts/run-memory-review.sh`.
- Skip-conditions: empty diff OR zero completed tasks → silent skip, no
  push-notify.
- Otherwise dispatch a Haiku `review-agent` subagent. It scans
  `events.jsonl` + cumulative diff for 4 signal types:
  mistake-prevention, decision-rationale, workflow-improvement, retrieval-gap.
- Returns 0-3 candidates; cap is hard. Orchestrator loops per candidate via
  `AskUserQuestion` (Accept / Refine / Defer / Reject).
- Accept → invokes `/z-suggest-memory --from-candidate-json` with source
  prefixed `incident:<RUN_ID>`. Orchestrator NEVER writes memory directly.
- All failure paths in Phase 9 are SILENT skips — no halt, no retry, often no
  push-notify (e.g. malformed output gets a push-notify, but missing
  TAGS.txt / parse failure get silent skip).

Key files:
- agents/review-agent.md
- scripts/run-memory-review.sh
- skills/z-implement-all/SKILL.md  (Phase 9, lines ~588-783)
- skills/z-review-all/SKILL.md     (Phase 7)
- skills/z-improve/SKILL.md:163-211 (different flow — applies edits to
  z-harness repo itself, derives concept_hints, calls /z-suggest-memory)

## Empirical signal (THIS REPO, right now)

`docs/llm/MEMORIES-FLAT.md` is **2 lines** — just the header comment. Zero
memories have ever been written via this pipeline despite the
infrastructure existing. The pipeline is wired but the artifact is empty.

User's global auto-memory at `~/.claude/projects/.../memory/MEMORY.md` does
have ~7 entries — but those came from the *generic Claude Code auto-memory*
system, not from the z-harness `/z-suggest-memory` flow. Two parallel memory
systems exist; the z-harness one is dormant.

## Empirical signal (QT-BOT)

`/Users/zeke/dev/qt-bot/` does not exist on this host — qt-bot is operated
remotely (zeke-pc per global CLAUDE.md). No `docs/llm/INDEX.json` deployed
there means the post-run memory review will hard-skip on z-harness runs
against qt-bot (run-memory-review.sh requires TAGS.txt + INDEX.json).
Whether `/z-init-docs` has been run on the remote qt-bot is unverified
from this host.

## Constraints / invariants worth preserving

- Cheap by default: Haiku review-agent, hard 3-candidate cap, silent skip on
  empty-diff / zero-tasks (cost guard).
- Strict write boundary: only `/z-suggest-memory` mutates memory. The
  orchestrator just relays candidates → user decision → skill call.
- Free-form tag extension allowed but discouraged. TAGS.txt is the seed.
- Notification policy is `approval_only` by default — most events are
  intentionally silent.
- `/z-improve` is opt-in, never auto-fired. It's distinct from Phase 9: it
  retros the *harness itself* (commands, agents, scripts), not the
  implementation diff.

## What the user is implicitly asking

1. The infrastructure exists but isn't producing memories. Why?
2. Should the post-mortem step be (a) **always automatic**, (b) **always
   nudge the user**, or (c) **stay opt-in** (status quo)?
3. The nudge — when it does fire — is currently embedded in Phase 9 of
   /z-implement-all. Is it visible enough? Is the wording compelling enough?
   Should the skills push harder?
4. Is `/z-improve` (harness retro) being conflated with Phase 9 (memory
   retro)? Should there be a third explicit `/z-postmortem` skill?

## No RESEARCH.md ingested for this run.
