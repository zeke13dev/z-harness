# Phase 0 — Premise accepted

**Goal as understood:** Restructure the current `/z-debug` command into two separate user-facing commands that mirror this codebase's existing `/z-plan` vs `/z-plan-light` split:

- `/z-fix` — light, user-already-has-diagnosis path. Single sanity-check consult, implement via `/z-plan-light` machinery, non-negotiable Codex review.
- `/z-debug` — heavy hypothesis-tournament path. Two rounds of adversarial multi-LLM hypothesis generation, consensus-first ranking with forced outlier carve-out, discriminating-test matrix, discrete Bayesian ordinal scoring, 3-5 isolation rounds, fix-gate requires (highest posterior AND causal mechanism explains all evidence).

Each command has an early gate to recommend the *other* command when scope feels wrong. No auto-routing under the hood.

**Underlying problem:** today's `/z-debug` has to be both light enough for trivial bugs and rigorous enough for hard ones, which compromises both. The split removes that tension. The user is also gesturing at Cursor's "agent debugging" pattern — the hypothesis-tournament mechanics directly operationalize that.

**Premise not contested:**
- BRAINSTORM.md is `status: complete` with `chosen_framing: codex` and a fully-elaborated User choice section that names every mechanic.
- All three ideators agreed today's `/z-debug` is loose; risks were named and folded into the User choice (false confirmation at scale, parallel-test pollution, false precision from scoring, context exhaustion, multi-LLM groupthink, ceremony for trivial bugs).
- The codebase already has the split pattern (`/z-plan` vs `/z-plan-light`) so this is a known shape, not novel architecture.

Proceeding to Phase 1.
