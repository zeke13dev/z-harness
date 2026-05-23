MODE: bundled-decisions

## Context: z-harness feature proposal — /z-brainstorm and /z-research

This is a bundled-decisions consultation for 4 architecture decisions on a new z-harness feature that adds two opt-in slash commands (`/z-brainstorm` and `/z-research`) that produce pre-plan exploration artifacts feeding into `/z-plan`.

**Existing harness context:**
- Slash commands live as paired files: `commands/<name>.md` (entrypoint) + `skills/<name>/SKILL.md` (implementation).
- Consultant subagents (`codex-consultant`, `gemini-consultant`) are multi-mode with a `MODE: <name>` discriminator.
- `/z-plan` is the heavyweight planner (multi-phase: premise → exploration → decisions → cross-LLM consult → SPEC/PLAN/TASKS).
- `/z-plan-light` is the lightweight FIX.md variant; consultants reuse modes across commands.
- Artifacts live in run archives at `z-harness/<slug>/` where multiple related artifacts can coexist (e.g., FIX.md + SPEC.md in the same slug dir).

---

## 4 Consult-Flagged Decisions

### D1. Artifact contract: distinct files vs unified PRECONTEXT.md

**Decision:** What file(s) do `/z-brainstorm` and `/z-research` write, and how does `/z-plan` consume them?

**Options:**
- **A. Distinct artifacts:** `BRAINSTORM.md` and `RESEARCH.md` are separate files with separate schemas. `/z-plan` Phase 0 detects each independently. Tradeoff: clean separation of concerns; `/z-plan` learns 2 schemas; can't trivially compose into one file if both commands ran.
- **B. Unified `PRECONTEXT.md`:** one file with `mode: brainstorm | research | both` header and a common section taxonomy. Tradeoff: one parser; chaining = append a section; risk of awkward "N/A" sections when only one mode ran.
- **C. Distinct files PLUS a manifest:** `BRAINSTORM.md` + `RESEARCH.md` + a tiny `precontext.manifest.json` listing which exist and their freshness. Tradeoff: fixes "did the user actually run both?" detection but adds a third file.

**Tentative call:** **A**. Genuinely different artifact shapes (list of framings vs terrain map); `/z-plan` learning two simple shapes is easier than maintaining a forced-unification schema.

**Consult reason:** wire format / public API boundary between commands; reversibility >1 hr (touching both producers and consumer).

---

### D2. Should Claude be one of the 3 ideators in /z-brainstorm?

**Decision:** Composition of the default 3-ideator brainstorm set.

**Options:**
- **A. Claude + Codex + Gemini** (3 model vendors). Tradeoff: maximum vendor diversity; orchestrator-is-Claude has slight self-bias risk in synthesis.
- **B. Codex + Gemini + Claude-Haiku** (Claude only as a *different model tier*, not as Claude-Sonnet). Tradeoff: removes same-model-as-orchestrator bias; Haiku may produce thinner framings (diversity ≠ quality variance).
- **C. Codex + Gemini + Codex-with-different-prompt** (no Claude ideator at all). Tradeoff: fully removes self-bias; 2-vendor diversity not 3.
- **D. Claude (fresh subagent context) + Codex + Gemini**, with the orchestrator's synthesis explicitly told to flag-and-weight against picking Claude's framing. Tradeoff: keeps full diversity, adds explicit anti-bias guardrail.

**Tentative call:** **D**. Claude in a fresh subagent context is materially different from main-thread Claude; the synthesis-bias risk is real but procedural (add a "flag if you're picking the Claude framing — justify against the others" check).

**Consult reason:** affects the core feature behavior; tendentially hard to retrofit later if v1 ships with the wrong shape.

---

### D4. Slug derivation across the chain

**Decision:** When `/z-research`, `/z-brainstorm`, and `/z-plan` are chained, do they share a slug dir or each get their own?

**Options:**
- **A. Shared slug by default.** `/z-brainstorm fix-foo` writes to `z-harness/fix-foo/BRAINSTORM.md`; subsequent `/z-plan fix-foo` reads that file and writes `SPEC.md` next to it. Chain artifacts accumulate in one dir.
- **B. Per-command slug.** Each command derives its own slug. Chaining requires the downstream command to be told where to look (e.g. `/z-plan --seed=z-harness/research-foo/RESEARCH.md fix-foo`).
- **C. Hybrid: shared slug, but each command writes to a subdir** — `z-harness/fix-foo/brainstorm/`, `z-harness/fix-foo/research/`, `z-harness/fix-foo/plan/`. Tradeoff: archive cleanliness; adds path complexity.

**Tentative call:** **A**. Matches how `/z-plan-light` and `/z-plan` already coexist (FIX.md vs SPEC.md in same slug dir is fine). Chain artifacts in one place is more discoverable.

**Consult reason:** chaining UX is a public surface; getting this wrong forces a rename later.

---

### D5. How is RESEARCH.md incorporated into /z-brainstorm ideators?

**Decision:** When `/z-brainstorm` runs with a `RESEARCH.md` present, what context does each ideator get?

**Options:**
- **A. Full inline.** Each ideator's prompt includes the entire RESEARCH.md verbatim. Tradeoff: maximum context; can blow ideator token budget on big research notes.
- **B. Summarized.** Main thread summarizes RESEARCH.md into a paragraph or two; ideators get the summary. Tradeoff: fits any size; lossy.
- **C. Findings only.** Pass only the `Findings:` section of RESEARCH.md (skip Open questions / Constraints). Tradeoff: simple to implement; might drop important constraints.
- **D. Read by reference.** Tell each ideator "RESEARCH.md is at $BASE/RESEARCH.md — Read it yourself if you need it." Tradeoff: zero context cost in the prompt; pushes context decision to each ideator; works for in-repo subagents but the Codex/Gemini consultants need it inline (they can't read the local repo by path).

**Tentative call:** **A** for Claude ideator (it can read by reference but inline is more reliable); **A** for Codex / Gemini ideators (no choice — they can't Read repo files, must be inline). Cap RESEARCH.md size — if it exceeds, say, 20 KB, fall back to **B** (summarize before passing).

**Constraint:** Codex and Gemini consultants cannot Read repo files — they must receive context inline in prompts.

**Consult reason:** directly affects feature quality and cost ceiling; default behavior of an integration point.

---

## Interaction Questions for Codex

1. **D2 ↔ D5 interaction:** If D2=D (Claude + Codex + Gemini with anti-bias guardrail), and Codex/Gemini ideators can't Read by reference (D5 constraint), does the full-inline approach (D5=A) create a meaningful cost/quality difference between Claude and the other two ideators? Should the anti-bias check flag this asymmetry?

2. **D1 ↔ D4 interaction:** If D1=A (distinct BRAINSTORM.md + RESEARCH.md) and D4=A (shared slug), does the shared slug create any ambiguity or ordering dependency when `/z-plan` Phase 0 tries to detect and consume these artifacts? (E.g., should Phase 0 read both and compose them, or is one "preferred" if both exist?)

3. **D4 specifics for downstream:** D4=A (shared slug) assumes `/z-plan` Phase 0 is taught to look for `z-harness/<slug>/BRAINSTORM.md` and `z-harness/<slug>/RESEARCH.md`. Is this a clean fit with how Phase 0 currently detects seed files?

---

## Ask

For each of the 4 consult-flagged decisions (D1, D2, D4, D5):

1. **Recommend** which option is best, with specific reasoning.
2. **Tradeoffs & risks:** what does the chosen option trade away, and what are the concrete risks?
3. **Missed considerations:** anything the decision statement missed? Edge cases, user experience, or maintenance burden?
4. **Decision interactions:** flag any interactions with the other 3 decisions. If an interaction changes the recommendation, explain.

Be specific and concrete — this is pre-implementation.
