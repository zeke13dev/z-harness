# TASKS — z-fix-hypothesis-driven

Ordered phases match PLAN.md. Status `[ ]` = pending, `[x]` = done. Each task fits a fresh implementer context.

---

## Phase A — Consultant agent mode additions (gating phase)

### T001 — Add two new modes to `agents/codex-consultant.md`
**Files touched:** `agents/codex-consultant.md`
**Dependencies:** none
**Acceptance:**
- [ ] Two new bullets added to the `## Modes` list: `generate-hypotheses-round1` and `generate-hypotheses-round2-adversarial`, per SPEC's exact wording.
- [ ] `generate-hypotheses-round1` description specifies Round-1 schema: `claim`, `prediction_if_true`, `prediction_if_false`, `discriminating_test`, `test_cost` (free|cheap|medium|expensive), `parallel_safe` (bool), `reasoning`. Tagged `schema_version: hypothesis_round1_v1`. Returns RAW (no wrapper).
- [ ] `generate-hypotheses-round2-adversarial` description specifies two ordered markdown tables (NEW + CRITIQUES) with the exact column schemas from SPEC. `critique_type` controlled vocabulary listed. `false_parallel_safe` rows must cite specific mutation. Tagged `schema_version: hypothesis_round2_v1`. Returns RAW. Prompt MUST explicitly forbid agreement-only returns.
- [ ] Corresponding "Ask" template entries added in the building-the-prompt section.
- [ ] "Returning to the caller" section updated to note both new modes return RAW.
- [ ] Existing `debug-hypotheses` mode unchanged.

**Complexity:** medium
**DOCS:** agents

### T002 — Add identical mode additions to `agents/gemini-consultant.md`
**Files touched:** `agents/gemini-consultant.md`
**Dependencies:** T001 (must be byte-for-byte mirror of T001's mode contracts; only the CLI invocation differs)
**Acceptance:**
- [ ] Both new modes added with identical text to T001's additions (mode names, schemas, Ask templates, return-shape).
- [ ] Gemini-specific CLI invocation preserved (`gemini -p ... --approval-mode plan --output-format text`).
- [ ] Existing modes unchanged.
- [ ] Spot-check: `diff <(grep -A5 'generate-hypotheses-round1' agents/codex-consultant.md) <(grep -A5 'generate-hypotheses-round1' agents/gemini-consultant.md)` — substantive content identical.

**Complexity:** low
**DOCS:** agents

---

## Phase B — `/z-fix` command + companion docs

### T003 — Create `commands/z-fix.md`
**Files touched:** `commands/z-fix.md` (NEW)
**Dependencies:** none (can run parallel to T001/T002; doesn't reference new modes)
**Acceptance:**
- [ ] Frontmatter has `description` and `argument-hint` per SPEC.
- [ ] Phases 0 through 10 present per SPEC (wrong-tool gate at Phase 0, `light-fix` consult framing focused on "does this cause explain all symptoms?", optional default-off post-mortem with auto-suggest at Phase 9 if `REVIEW_CYCLES > 1`).
- [ ] Setup steps mirror `/z-plan-light` (version stamp, log `fix_run_start`, notification policy).
- [ ] Auto-bail thresholds: >5 candidate files, >2 non-obvious decisions, cross-module impact (same as today's `/z-plan-light`).
- [ ] Hard rules section lists: never skip Codex review; never proceed past auto-bail; cross-LLM consult always emitted; no emojis; Phase 0 non-skippable.
- [ ] No mention of new round-1/round-2 modes (`/z-fix` doesn't use them).

**Complexity:** medium
**DOCS:** z-fix, commands

### T004 — Create `docs/human/z-fix.md`
**Files touched:** `docs/human/z-fix.md` (NEW)
**Dependencies:** T003
**Acceptance:**
- [ ] Overview paragraph names the use case (user-already-has-diagnosis) and what `/z-fix` is NOT for (deep diagnosis → `/z-debug`).
- [ ] Phase-by-phase walkthrough (concise).
- [ ] Decision matrix: when to pick `/z-fix` vs `/z-debug`.
- [ ] Example invocation + sample FIX.md.
- [ ] Hard rules summary.

**Complexity:** low
**DOCS:** z-fix

### T005 — Add `z-fix` entry to `docs/llm/commands.json`
**Files touched:** `docs/llm/commands.json`
**Dependencies:** T003
**Acceptance:**
- [ ] New per-concept-style entry (or augmented mode-list entry, depending on current schema) for `z-fix` with `source_file: ["commands/z-fix.md"]`, `last_updated: 2026-05-24`, `confidence: high`, `summary` per PLAN, `depends_on: ["agents", "scripts", "z-plan-light"]`.
- [ ] JSON validates (`python3 -m json.tool docs/llm/commands.json > /dev/null`).

**Complexity:** low
**DOCS:** commands

---

## Phase C — `/z-debug` rewrite + companion docs

### T006 — Rewrite `commands/z-debug.md` per SPEC
**Files touched:** `commands/z-debug.md`
**Dependencies:** T001, T002 (new modes must exist before z-debug.md can reference them)
**Acceptance:**
- [ ] Frontmatter description revised to mention hypothesis tournament + 3-LLM 2-round generation + ordinal Bayesian scoring + unified DEBUG.md + Phase 0 wrong-tool gate.
- [ ] All artifact paths consolidated into `z-harness/<slug>/DEBUG.md` (sections: Problem, Evidence Inventory, Hypothesis Pool, Test Matrix, Experiment Log, Score Updates, Eliminated Alternatives, Root Cause, Fix Plan, Verification, Post-mortem). No more separate PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM files.
- [ ] Phase 0 wrong-tool gate (recommend `/z-fix` if user already has hypothesis).
- [ ] Phase 2 captures evidence with stable `EVID-NNN` IDs.
- [ ] Phase 3a writes orchestrator checkpoint to `archive/<run>/round1-orchestrator.md` BEFORE dispatching parallel Codex+Gemini calls. Merge step assigns `H<NNN>` IDs; semantic dedup uses text-only rule.
- [ ] Phase 3b dispatches both consultants with `MODE: generate-hypotheses-round2-adversarial`; receives Problem + Evidence Inventory + Hypothesis Pool per Phase-visibility matrix. Orchestrator post-process filters: drop NEW rows duplicating pool, drop critique rows without `target_id`, drop tautological critique-cell content, drop `false_parallel_safe` critiques without cited mutation.
- [ ] Phase 4 builds Test Matrix with schema header documented at top of section.
- [ ] Phase 5 test-order rule: consensus-first + forced outlier carve-out (top 2 overlap=1 rows always tested early).
- [ ] Phase 6 cycle logic: orchestrator-only likelihood assignment; posterior lookup table embedded verbatim; cycle cap 5 (warning at 3, hard halt at 6); optional Round 3 with input restricted to claim+falsifying-test only.
- [ ] Phase 7 fix-gate has TWO hard preconditions: posterior == `very_high` AND zero `unexplained` rows in Evidence coverage table.
- [ ] Phase 9 post-mortem mandatory; existing `/z-mr-review` integration preserved.
- [ ] Auto-bail softened: multi-module / architectural / new-public-surface only; >5-files trigger DROPPED.
- [ ] Hard rules section lists: never debug without repro; never skip post-mortem; never skip Codex review on fix; always emit BOTH R1 and R2 generation consults; likelihood-assignment orchestrator-only; orchestrator R1 checkpointed before dispatch; no emojis.

**Complexity:** high
**DOCS:** z-debug, commands

### T007 — Create `docs/human/z-debug.md`
**Files touched:** `docs/human/z-debug.md` (NEW)
**Dependencies:** T006
**Acceptance:**
- [ ] Overview paragraph names the use case (unknown root cause; hypothesis tournament) and what `/z-debug` is NOT for (known cause → `/z-fix`).
- [ ] Posterior lookup table reproduced verbatim.
- [ ] Phase-visibility matrix reproduced (consultant-context-discipline table).
- [ ] Worked example: a fabricated bug, 9 hypotheses generated (3/LLM with partial overlap), Round 2 adds 2 new + drops 1 duplicate + flags 1 false-parallel-safe, Test Matrix with H001–H010, 2-cycle convergence to `very_high` posterior on H003, Evidence coverage table with zero unexplained.
- [ ] Sidebar: "Why orchestrator interprets likelihood, not consultants."
- [ ] Hard rules summary.

**Complexity:** medium
**DOCS:** z-debug

### T008 — Update `z-debug` entry in `docs/llm/commands.json`
**Files touched:** `docs/llm/commands.json`
**Dependencies:** T006
**Acceptance:**
- [ ] `last_updated` set to `2026-05-24`.
- [ ] `summary` rewritten to mention hypothesis tournament, 3-LLM 2-round generation, ordinal Bayesian scoring, unified DEBUG.md.
- [ ] JSON validates.

**Complexity:** low
**DOCS:** commands

---

## Phase C2 — Skill-form lockstep rewrite

### T009 — Rewrite `skills/z-debug/SKILL.md` to mirror new `commands/z-debug.md`
**Files touched:** `skills/z-debug/SKILL.md`
**Dependencies:** T006
**Acceptance:**
- [ ] Body content identical to `commands/z-debug.md` except for skill-specific frontmatter (which preserves the skill's `name`, `description`, etc.).
- [ ] All artifact references (PROBLEM/EVIDENCE/ISOLATION/POSTMORTEM .md) updated to `DEBUG.md ## Section` form.
- [ ] Verification check: `diff <(sed -n '/^# /,$ p' commands/z-debug.md) <(sed -n '/^# /,$ p' skills/z-debug/SKILL.md)` shows no substantive divergence.

**Complexity:** medium

---

## Phase D — Doc index refresh

### T010 — Update `docs/llm/agents.json` with new consultant modes
**Files touched:** `docs/llm/agents.json`
**Dependencies:** T001, T002
**Acceptance:**
- [ ] `codex-consultant` and `gemini-consultant` entries each list the two new modes (in whatever schema field enumerates modes — likely `entry_points` or similar).
- [ ] `last_updated` refreshed.
- [ ] JSON validates.

**Complexity:** low
**DOCS:** agents

### T011 — Add `z-fix` concept to `docs/llm/INDEX.json`; refresh affected slugs
**Files touched:** `docs/llm/INDEX.json`
**Dependencies:** T005, T008, T010
**Acceptance:**
- [ ] New top-level entry for `z-fix` slug with source_file, last_updated, confidence, summary.
- [ ] `last_updated` refreshed for `commands` and `agents` concepts.
- [ ] `generated_at` updated.
- [ ] JSON validates.

**Complexity:** low

---

## Phase E — Migration audit + dependent-command refresh

### T012 — Update `commands/z-improve.md` and `skills/z-improve/SKILL.md` references
**Files touched:** `commands/z-improve.md`, `skills/z-improve/SKILL.md`
**Dependencies:** T006
**Acceptance:**
- [ ] Line 45 (or wherever the reference lives post-edit) updated to point to `DEBUG.md ## Post-mortem` / `DEBUG.md ## Problem` instead of `POST-MORTEM.md` / `PROBLEM.md`.
- [ ] Both files updated identically.
- [ ] No other broken references introduced.

**Complexity:** low

### T013 — Update `commands/z-stats.md` references
**Files touched:** `commands/z-stats.md`
**Dependencies:** T006
**Acceptance:**
- [ ] Lines 83 and 97-99 references to `POSTMORTEM.md` action items updated to `DEBUG.md ## Post-mortem`.
- [ ] z-debug flow description in the table refreshed if it mentions the old separate-file layout.

**Complexity:** low

### T014 — Update `skills/z-suggest-memory/SKILL.md` references
**Files touched:** `skills/z-suggest-memory/SKILL.md`
**Dependencies:** T006
**Acceptance:**
- [ ] Lines 382-385 references to POSTMORTEM.md `Root cause` section and PROBLEM.md `Relevant concepts:` line updated to `DEBUG.md ## Post-mortem` / `DEBUG.md ## Problem` (with appropriate sub-section names if Phase 1 / Phase 9 of new z-debug introduce sub-sections).
- [ ] Line 223 reference to `source: debug:<run-id>` left unchanged (it's a calling-context tag, not a file path).
- [ ] `commands/z-suggest-memory.md:2` description left unchanged (conceptual reference to "/z-debug post-mortem" — no file path).

**Complexity:** low

### T015 — Refresh `README.md` cross-references
**Files touched:** `README.md`
**Dependencies:** T006, T003
**Acceptance:**
- [ ] Any `/z-debug` example or description that references PROBLEM/EVIDENCE/ISOLATION/POSTMORTEM separately is updated to DEBUG.md sections.
- [ ] `/z-fix` mentioned in the command list (alongside `/z-plan`, `/z-plan-light`, `/z-debug`, etc.).
- [ ] No broken internal links.

**Complexity:** low

---

## Phase F — Verification

### T016 — Repo-wide grep migration self-check
**Files touched:** none (verification only)
**Dependencies:** T009, T012, T013, T014, T015
**Acceptance:**
- [ ] `grep -rn -E "PROBLEM\.md|EVIDENCE\.md|ISOLATION\.md|POSTMORTEM\.md|POST-MORTEM\.md" commands/ skills/ docs/ README.md` — every remaining hit is either inside a `DEBUG.md ## Section` reference (good) OR explicitly tagged as a legacy-archive reference (good). No bare references to the standalone files remain in any non-archive code path.
- [ ] `grep -rn "/z-debug" commands/ docs/ README.md` — every hit makes sense in the new world (no orphan references to dropped phases/concepts).

**Complexity:** low

### T017 — Cross-file equivalence check (command vs skill, codex vs gemini)
**Files touched:** none (verification only)
**Dependencies:** T002, T009
**Acceptance:**
- [ ] `commands/z-debug.md` body and `skills/z-debug/SKILL.md` body are equivalent (modulo frontmatter and skill-specific metadata blocks).
- [ ] `agents/codex-consultant.md` and `agents/gemini-consultant.md` both list the two new modes with identical mode names, schemas, and Ask-template text (only CLI invocation differs).

**Complexity:** low
