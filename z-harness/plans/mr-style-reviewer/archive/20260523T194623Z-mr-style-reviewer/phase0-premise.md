# Phase 0 — Premise check

**Inputs:** BRAINSTORM.md (status: complete, chosen_framing: claude+hybrid). No RESEARCH.md.

## The premise

Build two standalone slash commands (`/z-mr-review` + `/z-style-init`) and one reviewer agent (`mr-reviewer.md`) in the z-harness plugin. `/z-mr-review` runs a multi-agent (Claude + Codex + Gemini) diff review wearing a "Senior Nitpicker" persona, against a mandatory project-local `STYLE.md`, and emits findings ranked P0–P4 in five categories. The user triages — the reviewer never blocks. `/z-style-init` is a Capture-first interactive flow that grounds STYLE.md in the project's most idiomatic existing files.

## Premise check

1. **Does it solve the underlying problem?** The stated problem is that AI agents (and humans) produce sloppy code — excess defensive code, repetitive tests, abstraction drift, hygiene rot — and the existing `codex-reviewer` / `/z-review-all` pipeline only catches *correctness* bugs. The proposed split is sound: correctness and quality are different review jobs with different prompts, different acceptable false-positive rates, and different blocking semantics. **Accepted.**

2. **Will multi-LLM review of *style* actually work?** This is the genuine risk. Style is judgment, not deterministic, and each model has its own taste bias (Claude verbose, Codex terse, Gemini opinionated). Three judges with three different style preferences could produce a noise-heavy union of taste wars. **Mitigations baked into the chosen framing:** (a) P0–P4 ranking means user triages; nothing auto-applies. (b) STYLE.md is the shared rubric all three judges anchor against, reducing per-model drift. (c) BRAINSTORM.md surfaces this and lists falsifiability thresholds (>30% rejection rate → noise generator, retire). **Accept with risk-flag.**

3. **Materially better paths not considered?**
   - **Hook on `/z-implement-all`** rather than a separate command. User explicitly chose suggested-after (quality first, correctness second). Suggested-after preserves the explicit verb without coupling the pipelines. Accepted.
   - **Re-use `codex-reviewer` machinery** instead of a new agent. Rejected: input contract differs (full branch diff vs per-task), prompt focus differs (assume-correctness vs find-bugs), and the persona/scope are different. A new agent is cheaper than overloading the old one.
   - **Make this a `/z-audit --dimension=style --rubric=STYLE.md`** extension. Already rejected in brainstorm — diff-as-MR vs static-component-audit is the load-bearing distinction. Accepted.

## Conclusion

Premise accepted. The goal: ship two commands + one agent + a STYLE.md authoring flow, with P0–P4 user-triage UX, mandatory STYLE.md, multi-LLM Nitpicker review, output as TASKS.md-compatible artifact that `/z-implement-*` can pick up. Risk-flag: cross-LLM style review noise — keep falsifiability thresholds visible in SPEC.md so we know when to retire.
