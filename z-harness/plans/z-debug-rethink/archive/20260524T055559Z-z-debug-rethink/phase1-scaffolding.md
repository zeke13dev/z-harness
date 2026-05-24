# Phase 1 Scaffolding — z-debug-rethink

## Topic

Rethink `/z-debug` to be more rigorously Cursor-style hypothesis-driven: generate N hypotheses, design a discriminating test per hypothesis, run tests (batch/parallel where possible), score results, iterate. Keep exploiting the multi-LLM (Claude + Codex + Gemini) advantage.

**User framing:** "i'm thinking of editing the idea of z-fix to be more like cursor's where the framework is identify a bunch of hypothesis -> test each hypothesis -> determine which one worked / iterate again. i want to be more disciplined so we have a higher chance that z-fix actually debugs/fixes issues. i still want to take advantage of the multi-llm idea of this project"

## Current /z-debug state

8-phase pipeline, <30 min wall target:
- P1: Problem statement
- P2: Reproduce + evidence (no debug without repro)
- P3: Hypothesize (2-3 ranked hypotheses)
- P4: Cross-LLM consult (Codex+Gemini parallel, `debug-hypotheses` mode, rank+surface disagreement)
- P5: Isolate (cap 3 cycles, one experiment per cycle, refuted hypotheses loop back to P3)
- P6: Root-cause + fix (reuses /z-plan-light, `light-fix` mode consult, non-negotiable Codex review)
- P7: Post-mortem (mandatory preventative analysis)
- P8: Finalize

Auto-bail: >5 files / >3 isolation cycles / multi-module / architectural → escalate to /z-plan.

Artifacts: PROBLEM.md, EVIDENCE.md, ISOLATION.md, FIX.md, POSTMORTEM.md under z-harness/<slug>/.

## Multi-LLM pattern

codex-consultant + gemini-consultant are Haiku CLI proxies. Modes include `debug-hypotheses`, `light-fix`. Standard return shape: Recommendation/Reasoning/Tradeoffs/Considerations/Raw excerpt. Always parallel for hypothesis + fix consults. Re-rank or surface disagreement.

## Gap the user is pointing at

Current /z-debug is hypothesis-driven but loose:
- Small N (2-3 hypotheses), one ranking pass
- User picks one, runs ONE experiment per cycle
- No explicit per-hypothesis discriminating-test design
- No batch/parallel test execution
- No scoring loop / Bayesian update across cycles
- No enforced write-down of (hypothesis, discriminating test, result, what was eliminated)

## Doc-fetcher synthesis

STATUS: no_docs (INDEX.json exists but no z-debug-specific concept docs found; z-debug command file read directly for scaffolding)

## Explore synthesis

Not dispatched (Z_HARNESS_BRAINSTORM_EXPLORE not set).

## RESEARCH.md

Not present.

## input_hash: bc78a4efe1c358cf
