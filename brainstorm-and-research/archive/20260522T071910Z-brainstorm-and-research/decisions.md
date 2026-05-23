# Decisions — brainstorm-and-research

## D1. Artifact contract: distinct files vs unified PRECONTEXT.md

**Decision:** What file(s) do `/z-brainstorm` and `/z-research` write, and how does `/z-plan` consume them?

**Options:**
- **A. Distinct artifacts:** `BRAINSTORM.md` and `RESEARCH.md` are separate files with separate schemas. `/z-plan` Phase 0 detects each independently. *Tradeoff:* clean separation of concerns; `/z-plan` learns 2 schemas; can't trivially compose into one file if both commands ran.
- **B. Unified `PRECONTEXT.md`:** one file with `mode: brainstorm | research | both` header and a common section taxonomy. *Tradeoff:* one parser; chaining = append a section; risk of awkward "N/A" sections when only one mode ran.
- **C. Distinct files PLUS a manifest:** `BRAINSTORM.md` + `RESEARCH.md` + a tiny `precontext.manifest.json` listing which exist and their freshness. *Tradeoff:* fixes "did the user actually run both?" detection but adds a third file.

**Tentative call:** **A**. Genuinely different artifact shapes (list of framings vs terrain map); `/z-plan` learning two simple shapes is easier than maintaining a forced-unification schema.

**Consult? yes** — Trigger: wire format / public API boundary between commands; reversibility >1 hr (touching both producers and consumer).

---

## D2. Should Claude be one of the 3 ideators in /z-brainstorm?

**Decision:** Composition of the default 3-ideator brainstorm set.

**Options:**
- **A. Claude + Codex + Gemini** (3 model vendors). *Tradeoff:* maximum vendor diversity; orchestrator-is-Claude has slight self-bias risk in synthesis.
- **B. Codex + Gemini + Claude-Haiku** (Claude only as a *different model tier*, not as Claude-Sonnet). *Tradeoff:* removes same-model-as-orchestrator bias; Haiku may produce thinner framings (diversity ≠ quality variance).
- **C. Codex + Gemini + Codex-with-different-prompt** (no Claude ideator at all). *Tradeoff:* fully removes self-bias; 2-vendor diversity not 3.
- **D. Claude (fresh subagent context) + Codex + Gemini**, with the orchestrator's synthesis explicitly told to flag-and-weight against picking Claude's framing. *Tradeoff:* keeps full diversity, adds explicit anti-bias guardrail.

**Tentative call:** **D**. Claude in a fresh subagent context is materially different from main-thread Claude; the synthesis-bias risk is real but procedural (add a "flag if you're picking the Claude framing — justify against the others" check).

**Consult? yes** — Trigger: affects the core feature behavior; tendentially hard to retrofit later if v1 ships with the wrong shape.

---

## D3. /z-research Explore cap

**Decision:** Hard-cap Explores at 3 (matching `/z-plan`), or allow env override?

**Options:**
- **A. Hard cap at 3.** Same as `/z-plan`. If 3 isn't enough, user chains `/z-research` with a different focal question.
- **B. Allow `Z_HARNESS_RESEARCH_EXPLORE_CAP=N` env override, default 3.** Power-user knob for deep terrain.
- **C. Default 4 (one more than `/z-plan`), allow env override.** Justification: research is the heaviest by design; 4 is the natural research cap.

**Tentative call:** **A**. Forcing focus is a feature, not a limitation. If a research question is too broad for 3 Explores, it's actually two research questions and should be chained.

**Consult? no** — Trigger: doesn't match consult criteria (no new dep, no public API change, reversible — can flip to B by editing the command file in 30 seconds).

---

## D4. Slug derivation across the chain

**Decision:** When `/z-research`, `/z-brainstorm`, and `/z-plan` are chained, do they share a slug dir or each get their own?

**Options:**
- **A. Shared slug by default.** `/z-brainstorm fix-foo` writes to `z-harness/fix-foo/BRAINSTORM.md`; subsequent `/z-plan fix-foo` reads that file and writes `SPEC.md` next to it. Chain artifacts accumulate in one dir.
- **B. Per-command slug.** Each command derives its own slug. Chaining requires the downstream command to be told where to look (e.g. `/z-plan --seed=z-harness/research-foo/RESEARCH.md fix-foo`).
- **C. Hybrid: shared slug, but each command writes to a subdir** — `z-harness/fix-foo/brainstorm/`, `z-harness/fix-foo/research/`, `z-harness/fix-foo/plan/`. *Tradeoff:* archive cleanliness; adds path complexity.

**Tentative call:** **A**. Matches how `/z-plan-light` and `/z-plan` already coexist (FIX.md vs SPEC.md in same slug dir is fine). Chain artifacts in one place is more discoverable.

**Consult? yes** — Trigger: chaining UX is a public surface; getting this wrong forces a rename later.

---

## D5. How is RESEARCH.md incorporated into /z-brainstorm ideators?

**Decision:** When `/z-brainstorm` runs with a `RESEARCH.md` present, what context does each ideator get?

**Options:**
- **A. Full inline.** Each ideator's prompt includes the entire RESEARCH.md verbatim. *Tradeoff:* maximum context; can blow ideator token budget on big research notes.
- **B. Summarized.** Main thread summarizes RESEARCH.md into a paragraph or two; ideators get the summary. *Tradeoff:* fits any size; lossy.
- **C. Findings only.** Pass only the `Findings:` section of RESEARCH.md (skip Open questions / Constraints). *Tradeoff:* simple to implement; might drop important constraints.
- **D. Read by reference.** Tell each ideator "RESEARCH.md is at $BASE/RESEARCH.md — Read it yourself if you need it." *Tradeoff:* zero context cost in the prompt; pushes context decision to each ideator; works for in-repo subagents but the Codex/Gemini consultants need it inline (they can't read the local repo by path).

**Tentative call:** **A** for Claude ideator (it can read by reference but inline is more reliable); **A** for Codex / Gemini ideators (no choice — they can't Read repo files, must be inline). Cap RESEARCH.md size — if it exceeds, say, 20 KB, fall back to **B** (summarize before passing).

**Consult? yes** — Trigger: directly affects feature quality and cost ceiling; default behavior of an integration point.

---

## D6. Where does the seed-artifact detection live in /z-plan?

**Decision:** Where does `/z-plan` check for `BRAINSTORM.md` / `RESEARCH.md` and integrate their content?

**Options:**
- **A. Start of Phase 0 (Premise check).** Read the artifacts at the very top; let them inform the premise statement. Phase 1 (Exploration) skips doc-fetcher/Explore if RESEARCH.md is recent and complete.
- **B. New Phase 0a "Seed-artifact ingestion"** between Setup and Phase 0. Clean separation.
- **C. Start of Phase 1.** Treat them purely as exploration scaffolding; premise check runs fresh.

**Tentative call:** **A**. The premise check itself is informed by what was already established in brainstorm (chosen framing) or research (findings). Treating them as Phase 1-only scaffolding wastes the user's prior work.

**Consult? no** — Trigger: integration mechanic, internal to /z-plan, reversible by editing the command file.

---

## D7. Should consultants get a new MODE: research-review, or reuse MODE: light-fix?

**Decision:** `/z-research` Phase 3 cross-LLM consult on the research-note draft — what mode flag?

**Options:**
- **A. New `MODE: research-review`.** Explicit purpose: "critique this research note for missing findings, wrong claims, undocumented constraints."
- **B. Reuse `MODE: light-fix`.** Repurpose the existing mode with a prompt that says "this isn't a fix, it's a research note — critique missing/wrong findings."
- **C. Use `MODE: doc-audit`.** Existing mode for evaluating whether docs accurately describe source files — closest in spirit to "critique this research note."

**Tentative call:** **A**. The consultant return shape and prompting differ: light-fix asks for a *recommendation*; research-review asks for *gaps and incorrect claims, no recommendation*. Reusing modes that mean different things invites prompt drift.

**Consult? no** — Trigger: internal subagent contract, fully reversible.

---

## D8. /z-brainstorm: synthesis recommendation vs no recommendation

**Decision:** After 3 ideators return, does the orchestrator make a *recommendation* on which framing to pick, or just present them neutrally?

**Options:**
- **A. Neutral presentation.** AskUserQuestion with N framings as options, no orchestrator recommendation. User picks blind.
- **B. Orchestrator recommends with one-line rationale.** "I'd pick Codex's framing because X; here are all 3, your call."
- **C. Cross-LLM votes.** After the 3 ideators return, do a quick consult ("which framing best fits the symptoms?") and present that as a recommendation alongside the 3 framings.

**Tentative call:** **B**. Hiding the orchestrator's read isn't honest — it has one whether or not it states it. State it explicitly, let user override. Avoid **C** for cost reasons (cross-LLM consult costs ~30s wall-clock; user can read 3 paragraphs faster than that).

**Consult? no** — Trigger: UX choice, fully reversible, no decision-interaction implications.

---

## Summary

**Consult-flagged (5 — at the cap):** D1, D2, D4, D5, D6 (correction: D6 is "no" — actual consult set is D1, D2, D4, D5. **4 consult-flagged.** Under the cap.)

**Not consulted (4):** D3, D6, D7, D8 — local mechanical decisions, easily reversed.

**Open question for user gate:** any decision you want to flip from no→yes (or vice versa)? Any options I missed? Any decisions I missed entirely?
