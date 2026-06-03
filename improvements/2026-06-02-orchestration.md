# Z-harness retro: orchestration

**Run:** z-harness/archive/orchestration
**Date:** 2026-06-02
**Status:** draft — under discussion

## Run summary
A long `/z-implement-all` orchestration spanning the deepswe-pier and persona-rotation slugs. It paused once for a context checkpoint (5/17 done), completed 17/17, then **halted** on `repo_not_quiesced` (30 uncommitted files, foundation uncommitted) before fixups brought it to 21/21 and a clean final gate (foundation_commit 7c8d09a, all suites green). The end state was healthy; the halt was a mid-run interruption rather than a pre-flight catch.

## Friction observed
- **Reactive quiescence halt** — `run_halt {reason: "repo_not_quiesced", uncommitted_files: 30, foundation_uncommitted: true}`. Implementation was already underway across 17 tasks when the un-quiesced/uncommitted-foundation condition halted the run. `grep` finds no `quiesce` / `foundation` / `uncommitted` pre-flight in `commands/z-implement-all.md` or `scripts/` — the condition is discovered reactively, not gated up front. This matches the prior lesson that the foundation must be committed before implementers run (else parallel edits clobber state).

## Proposed improvements

### Proposal 5: Foundation-quiescence pre-flight gate in `/z-implement-all`
- **Symptom:** Run halted partway with 30 uncommitted files and an uncommitted foundation.
- **Edit target:** `commands/z-implement-all.md` — add a Phase 0 pre-flight before any implementer dispatch.
- **Proposed change:** Before dispatching the first implementer, run `git status --porcelain`. If the worktree is dirty or the foundation commit is absent, present an AskUserQuestion gate: commit the foundation now / proceed anyway (record acknowledgment) / abort. Emit a `quiescence_precheck` event with the disposition.
- **Why this helps:** Converts a mid-run halt (work already spent across many tasks) into a cheap up-front decision, and codifies the "commit foundation first" discipline that is currently tribal knowledge.
- **Risk:** False positives on intentionally-dirty trees (e.g. multi-session work in progress) — hence an AskUser gate with a "proceed anyway" arm, not a hard fail. Must not auto-commit or auto-stage; the user owns the commit.

## Discussion log
- **P5 (foundation-quiescence pre-flight):** User accepted. Applied. Confirmed in code that no quiescence/foundation pre-flight existed (`grep` of `commands/z-implement-all.md` + `scripts/` empty), so the `repo_not_quiesced` halt was purely reactive. Added a fresh-start-only Setup step (gate skips on resume, where uncommitted in-progress work is expected).

## Decisions
- **P5 — ACCEPTED, applied.** `commands/z-implement-all.md` Setup step 8 (foundation-quiescence pre-flight). AskUser gate (commit / proceed / abort), never auto-commits, emits `quiescence_precheck`. Diff: `improvement-4.diff`.

**Status:** complete
