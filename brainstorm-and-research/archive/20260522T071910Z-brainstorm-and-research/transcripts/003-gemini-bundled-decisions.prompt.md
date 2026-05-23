MODE: bundled-decisions

TASK: Review 4 consult-flagged decisions for a new z-harness feature (alpha: `/z-brainstorm` and `/z-research` opt-in slash commands).

BACKGROUND:

The z-harness is a planning/implementation orchestration framework. New slash commands are paired:
- `commands/<name>.md` (entry point for slash command, calls subagents)
- `skills/<name>/SKILL.md` (orchestration logic)

Consultant subagents (codex-consultant, gemini-consultant) are multi-mode, discriminated by MODE: <name> prefix. Modes are fully isolated — different return shapes, different prompting.

The heavyweight `/z-plan` pipeline is 9+ phases:
- Phase 0: Premise check
- Phase 1: Exploration (2-tier: doc-fetcher Haiku first, then Explore for gaps; capped at 3 Explores per run)
- Phase 2: Decisions document (enumerate all decisions, flag consult-worthy ones)
- Phase 3: Cross-LLM consult (Codex + Gemini on all consult-flagged decisions)
- Phase 4-9: SPEC/PLAN/TASKS authoring and review

Each plan gets a slug: `z-harness/<slug>/`. All outputs accumulate under that slug: `SPEC.md`, `PLAN.md`, `TASKS.md`, `archive/<run-id>/`.

---

FULL DECISIONS ARTIFACT (from /Users/zeke/dev/z-harness/brainstorm-and-research/archive/20260522T071910Z-brainstorm-and-research/decisions.md):

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

EXISTING HARNESS PATTERNS (for context):

1. Consultant subagents (codex-consultant.md, gemini-consultant.md) declare MODE: at the top of the caller's prompt. Each mode has its own return shape, prompt structure, and archive naming.

2. The z-plan.md command shows the artifact and integration pattern:
   - Artifacts are namespaced by slug: `z-harness/<slug>/`
   - Multiple outputs coexist in same slug (Phase 0 through Phase 9 outputs)
   - Phases checkpoint to `archive/<run-id>/<phase>.md` for resumability
   - Events are logged to `archive/<run-id>/events.jsonl`

3. The two-tier docs (docs/llm/INDEX.json + docs/llm/<concept>.json) are read by doc-fetcher (Haiku) in Phase 1, never by the main orchestrator thread.

4. Subagents that can't Read repo files by path (Codex, Gemini consultants) must receive their context inline in the prompt.

---

CONSTRAINTS & CONVENTIONS:

- DRY: `/z-plan-light` (lightweight FIX.md variant) and `/z-plan` (heavyweight SPEC/PLAN/TASKS) already coexist in the same `z-harness/<slug>/` directory without collision or confusion.
- Wire-format stability: once a schema ships, changing it downstream forces work everywhere (Phase 0 detection, Phase 3 synthesis, Phase 7 review).
- Subagent context limits: Codex and Gemini consultants have no repo Read capability; they need context inlined. Claude ideators in fresh subagent context can Read, but inlining is more reliable for consistency.
- Token economy: RESEARCH.md can grow unbounded; capping at 20 KB and summarizing on overflow is a reasonable guardrail.
- Chaining UX: users will naturally invoke `/z-brainstorm`, then `/z-research`, then `/z-plan` in sequence. The slug should be the same across all three (ergonomic); downstream commands must find upstream artifacts with minimal friction.

---

ASKS:

For each of the 4 consult-flagged decisions, I need:

1. **Recommendation:** which option (A/B/C/D)?
2. **Reasoning:** why that option?
3. **Tradeoffs / risks:** what downsides or edge cases?
4. **Anything missed?** any options or considerations the decisions doc overlooked?
5. **Interactions across decisions:** does your choice on (say) D2 affect how you'd recommend D5? Flag all such dependencies.

---

END PROMPT
