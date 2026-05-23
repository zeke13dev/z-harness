# TASKS — brainstorm-and-research

## Phase A — Foundations

- [ ] **T001 — Add MODE: brainstorm + MODE: research-review to codex-consultant**
  - **Files:** `/Users/zeke/dev/z-harness/agents/codex-consultant.md`
  - **Depends:** none
  - **Acceptance:**
    - `## Modes` section gains two new entries (brainstorm, research-review) following the existing pattern.
    - Brainstorm-mode entry specifies: caller provides topic + scaffolding; agent returns 5 sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind); does NOT use the standard return wrapper.
    - Research-review-mode entry specifies: caller provides research-note draft + question + scaffolding; agent returns gaps / errors / missing constraints; explicitly forbidden to recommend an approach; does NOT use the standard return wrapper.
    - Existing modes unchanged.
  - **DOCS:** none (z-harness has no `docs/llm/INDEX.json`).
  - **Complexity:** low

- [ ] **T002 — Add MODE: brainstorm + MODE: research-review to gemini-consultant**
  - **Files:** `/Users/zeke/dev/z-harness/agents/gemini-consultant.md`
  - **Depends:** none (parallelizable with T001)
  - **Acceptance:** same shape as T001, mirrored for the gemini-consultant file.
  - **Complexity:** low

## Phase B — /z-brainstorm command

- [ ] **T003 — Create /z-brainstorm command + skill mirror**
  - **Files:**
    - `/Users/zeke/dev/z-harness/commands/z-brainstorm.md` (new)
    - `/Users/zeke/dev/z-harness/skills/z-brainstorm/SKILL.md` (new)
  - **Depends:** T001, T002
  - **Acceptance:**
    - Both files exist; `diff` between them shows only `name:` frontmatter line and leading-blank-line differences.
    - Setup section handles: slug derivation (auto from topic OR `--slug=X` flag); existing-slug-dir prompt (overwrite / append-to-new-run / abort); export `Z_HARNESS_SLUG`; pick RUN; mkdir; version stamp; `log-event.sh brainstorm_run_start`.
    - Phase 1 (Scaffolding): doc-fetcher dispatch if `docs/llm/INDEX.json` exists; optional Explore behind `Z_HARNESS_BRAINSTORM_EXPLORE=1`; RESEARCH.md ingestion (full inline if ≤20 KB, extractive summary if larger, summary stored to `archive/<run>/research-summary-for-brainstorm.md`).
    - Phase 2: ONE message with three parallel `Agent()` calls — Claude (`subagent_type="general-purpose", model="sonnet"`), Codex (`codex-consultant`, `MODE: brainstorm`), Gemini (`gemini-consultant`, `MODE: brainstorm`). All three get IDENTICAL scaffolding payload (no read-by-reference asymmetry).
    - Phase 3: parse 3 returns; record `<missing>` for malformed sections; write BRAINSTORM.md with YAML frontmatter (artifact, slug, generated_at UTC, command, input_hash per spec algorithm, depends_on, ideators); apply mandatory anti-bias check (section-by-section comparison with explicit Claude-wins justification rule); orchestrator recommendation with one-line rationale; AskUserQuestion with previews — option per framing + Restart + Abandon.
    - Phase 4: persist user choice into BRAINSTORM.md; `log-event.sh brainstorm_run_end`; push-notify with next-step recommendation.
    - Ideator failure handling: 1/3 fail → proceed; 2/3 fail → AskUserQuestion retry/proceed-with-1/abandon; 3/3 fail → hard halt with `total_ideator_failure` event.
    - Restart flow: archives existing BRAINSTORM.md to `archive/<run>/BRAINSTORM.md.previous-<N>`, fresh RUN.
    - Abandon flow: sets frontmatter `status: abandoned`, exits.
    - Cost guardrail: ≤200K tokens target; log warning if exceeded.
    - Negative-case integration acceptance: brainstorm on slug with existing RESEARCH.md correctly inlines it; brainstorm on slug with existing BRAINSTORM.md prompts user.
  - **DOCS:** none
  - **Complexity:** high

## Phase C — /z-research command

- [ ] **T004 — Create /z-research command + skill mirror**
  - **Files:**
    - `/Users/zeke/dev/z-harness/commands/z-research.md` (new)
    - `/Users/zeke/dev/z-harness/skills/z-research/SKILL.md` (new)
  - **Depends:** T001, T002
  - **Acceptance:**
    - Both files exist; diff shows only `name:` + blank-line differences.
    - Setup mirrors `/z-brainstorm` Setup, but `log-event.sh research_run_start`.
    - Phase 0 (cost-confirmation gate): AskUserQuestion with proceed / reduce-to-1-Explore / abandon. Log user's pick.
    - Phase 1: doc-fetcher dispatch if INDEX.json exists (one call).
    - Phase 2: up to 3 parallel Explore subagents on distinct facets (or 1 if user reduced). Hard cap 3; no env override in v1.
    - Phase 3: write `archive/<run>/research-draft.md` with mandatory sections: Findings (with file:line citations), Constraints discovered, Open questions, No-recommendation (mandatory, non-deletable).
    - Phase 4: bundled cross-LLM critique (`MODE: research-review` on both codex-consultant and gemini-consultant), parallel dispatch.
    - Phase 5: revise draft based on critiques; record consultant feedback in RESEARCH.md `Cross-LLM review notes` section; note filled/unfilled gaps.
    - Phase 6: write final `RESEARCH.md` with YAML frontmatter (artifact, slug, generated_at, command, input_hash, depends_on=none, explore_calls). `log-event.sh research_run_end`. Push-notify with next-step.
    - Findings without file:line citations are demoted to Open questions (invariant).
    - If orchestrator is tempted to recommend an approach, log `research_temptation` event and proceed without recommending.
    - Cost guardrail: ≤2M tokens target; log warning if exceeded.
    - Known v1 limitation documented in command file: no per-Explore wall-clock timeout (Agent() doesn't expose timeout knob).
  - **DOCS:** none
  - **Complexity:** high

## Phase D — /z-plan integration

- [ ] **T005 — Update /z-plan + skill mirror for precontext detection**
  - **Files:**
    - `/Users/zeke/dev/z-harness/commands/z-plan.md`
    - `/Users/zeke/dev/z-harness/skills/z-plan/SKILL.md`
  - **Depends:** none (can run in parallel with T003/T004)
  - **Note:** Setup step 10 and Phase 0 inject reference have been pre-applied to both files. This task verifies the existing edits are correct AND completes the remaining pieces.
  - **Acceptance:**
    - Setup step 10 exists (already in working tree) — verify it specifies: precontext artifact detection, freshness check on RESEARCH.md citations via the broadened regex from SPEC, conflict surfacing between BRAINSTORM and RESEARCH, deleted-source detection.
    - Phase 0 prose: explicitly references "if BRAINSTORM/RESEARCH were detected in Setup step 10, inject their content here" (already pre-applied — verify present).
    - **NEW** Phase 1 boundary tightening: "if RESEARCH.md is non-stale AND covers ≥1 distinct facet of the task, doc-fetcher and Explore become optional."
    - **NEW** Phase 6 SPEC.md template additions: SPEC.md template gains `## Planning Inputs` section listing which precontext artifacts contributed (paths + generated_at), or "none — fresh /z-plan run."
    - **NEW** Setup step 1 (slug collision handling) update: distinguish precontext-only slug dir (continuation, no prompt) from finished-plan dir (collision, prompt as today).
    - Diff between commands/z-plan.md and skills/z-plan/SKILL.md remains within prior tolerances (only frontmatter + blank-line differences).
    - Negative-case acceptance: precontext-only dir treated as continuation; finished-plan dir prompts user; stale-source warning fires; unfinalized brainstorm recommends re-run.
  - **DOCS:** none
  - **Complexity:** medium

## Phase E — Documentation

- [ ] **T006 — Update README with new commands**
  - **Files:** `/Users/zeke/dev/z-harness/README.md`
  - **Depends:** T003, T004, T005
  - **Acceptance:**
    - New section / entry documenting `/z-brainstorm` and `/z-research` purposes + when to use each.
    - Example chain: `/z-research → /z-brainstorm → /z-plan` documented for the murky-problem use case.
    - Env vars documented: `Z_HARNESS_BRAINSTORM_EXPLORE`.
    - New event types listed (brainstorm_run_*, research_run_*, ideator_failed, etc.) in the "Layout" or telemetry section if such exists.
    - Known v1 limitations noted: no subagent wall-clock timeout; no doc-fetcher caching across precontext + plan runs.
  - **DOCS:** none
  - **Complexity:** low
