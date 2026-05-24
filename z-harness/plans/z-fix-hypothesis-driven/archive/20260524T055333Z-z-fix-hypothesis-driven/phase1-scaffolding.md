# Phase 1 scaffolding — z-fix-hypothesis-driven

## Topic

Rethink z-fix (the existing `/z-debug` command) to be more rigorously Cursor-style hypothesis-driven: **generate N hypotheses → test each one → determine which worked → iterate**. Be more disciplined so the command actually fixes issues. Continue exploiting the project's multi-LLM (Claude + Codex + Gemini) advantage.

User's exact framing: *"i'm thinking of editing the idea of z-fix to be more like cursor's where the framework is identify a bunch of hypothesis -> test each hypothesis -> determine which one worked / iterate again. i want to be more disciplined so we have a fhigher chance that z-fix actually debugs/fixes issues. i still want to take advantage of the multi-llm idea of this project"*

## Doc-fetcher synthesis (current state)

### `/z-debug` (the existing "z-fix")

8-phase investigation pipeline, target <30 min wall time. Differs from `/z-plan` by starting from a known-bad symptom; strict scope; **debug without repro is prohibited**; architectural changes auto-bail to `/z-plan`.

1. **Problem statement** — clarify expected vs actual, reproducibility, timeline (`AskUserQuestion`).
2. **Reproduce + evidence** — concrete logs/errors/test failures; if no repro, halt.
3. **Hypothesize** — propose 2-3 ranked hypotheses with supporting/refuting evidence; doc-fetcher first if INDEX.json exists.
4. **Cross-LLM consult (bundled)** — Codex + Gemini in parallel, `debug-hypotheses` mode; rank hypotheses; surface disagreement.
5. **Isolate** — targeted experiments (logs, test cases, DB queries, git diffs); **cap at 3 cycles**; refuted hypotheses loop back to Phase 3.
6. **Root cause + fix** — reuses `/z-plan-light`; cross-LLM consult on fix (`light-fix` mode); implement inline; **non-negotiable Codex review**.
7. **Post-mortem** — mandatory preventative analysis (spec gap, test gap, assertion gap, monitoring gap, doc gap); convert action items to tasks.
8. **Finalize** — log + notify.

**Auto-bail triggers:** root cause spans multiple modules / architectural change / fix touches >5 files / >3 hypothesis-isolation cycles without convergence / broader design flaw.

**Key files:** `commands/z-debug.md:1–343`; artifacts in `z-harness/<slug>/` (PROBLEM.md, EVIDENCE.md, ISOLATION.md, FIX.md, POSTMORTEM.md).

**Invariants:** never debug without repro; never skip post-mortem; two separate cross-LLM consults (P4 hypotheses + P6 fix); Codex review after P6 implementation is non-negotiable.

### Multi-LLM consultation pattern

Both `codex-consultant` (Haiku → `codex exec` → ChatGPT app endpoint) and `gemini-consultant` (Haiku → `gemini -p --approval-mode plan`) are CLI proxies with identical mode sets:

- `bundled-decisions` (z-plan P3) — weigh in on DECISIONS.md.
- `plan-review` (z-plan P7) — critique SPEC + PLAN.
- `light-fix` (z-plan-light P3 / z-debug P6) — single problem + options; brief.
- **`debug-hypotheses` (z-debug P4)** — rank 2-3 hypotheses by plausibility; suggest cheapest experiment.
- `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review` — varying return shapes.

**Standard return shape** (for `debug-hypotheses`, `light-fix`, etc.):
```
## [LLM] consultation: <summary>
**Recommendation:** <pick>
**Reasoning:** <summary>
**Tradeoffs / risks flagged:** <bullets>
**Additional considerations:** <bullets>
**Raw response excerpt:** <quote>
```

**Invariants:** consultants are read-only; archive prompts+responses; **always call both in parallel** during hypothesis and fix consults; re-rank or surface disagreement.

### Hypothesis-driven debugging today

`/z-debug` IS already hypothesis-driven, but the bar is:
- "2-3 hypotheses" (small N).
- Cross-LLM consult ranks them once.
- User picks top; runs ONE experiment per cycle; cap 3 cycles.
- No explicit per-hypothesis test design, no batch parallel testing, no Bayesian update / scoring loop.

**Cursor's "agent debugging" pattern** (what the user is gesturing at): generate a broader hypothesis set up front, design discriminating tests for each, run them (potentially in parallel), update beliefs from results, iterate with surviving / new hypotheses. Discipline = make each cycle write down (a) hypothesis, (b) the test that would discriminate it, (c) the observed result, (d) what was eliminated.

## Explore findings

(skipped — `Z_HARNESS_BRAINSTORM_EXPLORE` not set)

## RESEARCH.md

(not present)

## input_hash

(computed in shell)
