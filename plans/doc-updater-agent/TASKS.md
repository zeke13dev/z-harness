# TASKS: doc-updater-agent

> Generated: 2026-06-09
> Plan: doc-updater-agent
> Status: ready

---

## Phase A: Foundation — Scripts + Agent Definitions

### T001 — `scripts/append-tier2-context.py`

- **Files:** `scripts/append-tier2-context.py` (new)
- **Deps:** None
- **Status:** [ ]
- **Complexity:** medium

Create the incremental context accumulation script.

**Acceptance criteria:**
- Accepts `--phase` (plan|implement|review), `--field` (decisions|consultant_findings|tried_and_failed|deviations|breaking_changes|review_patterns|gaps|human_overrides), `--json` (payload)
- Reads `$Z_HARNESS_PLAN_DIR/tier2-context.json`, creates if absent with skeleton schema
- Appends payload to named array field; validates JSON schema per field type
- **Dedup (F2 fix):** Uses `--upsert` mode — if entry with same `task` (for implement fields) or `id` (for decisions) exists, replaces; otherwise appends
- **Amend-aware (F3 fix):** Accepts `--mark-amended` flag that appends `{"event": "plan_amended", "timestamp": "..."}` marker
- Atomic write (tmp file + `os.replace`)
- Exit codes: 0=success, 1=schema validation failure, 2=write error
- Tests: unit test for each --field type, upsert behavior, schema validation rejection

---

### T002 — `scripts/reconcile-tier1-staged.py`

- **Files:** `scripts/reconcile-tier1-staged.py` (new)
- **Deps:** None
- **Status:** [ ]
- **Complexity:** medium

Create the Tier 1 staged update reconciliation script.

**Acceptance criteria:**
- Scans `$Z_HARNESS_PLAN_DIR/tier1-staged/` for concept directories
- For each concept: reads `human.md` and `llm.json` from both staged and `docs/` paths
- Merges AUTO-START/AUTO-END sections: staged version replaces current version within delimiters
- Preserves everything outside delimiters in human docs
- For LLM JSON: updates `entry_points`, `source_file`/`source_files`, `last_updated`; preserves `depends_on`, `consumed_by`, `summary`, `confidence`, `memories`, `invariants`, `gotchas`
- Latest-wins for overlapping staged updates (same concept touched by multiple tasks)
- Updates `docs/llm/INDEX.json`: `last_updated` timestamp + `source_files` for each touched concept
- Runs `scripts/regenerate-memories-flat.py` after all concepts updated
- `--dry-run` flag: show diffs, don't write
- Exit codes: 0=success, 1=merge conflict, 2=write error
- Tests: merge with no conflicts, merge with overlapping updates (latest-wins), dry-run output format

---

### T003 — `agents/tier1-doc-updater.md`

- **Files:** `agents/tier1-doc-updater.md` (new)
- **Deps:** None
- **Status:** [ ]
- **Complexity:** medium

Define the Tier 1 mechanical doc sync Flash subagent.

**Acceptance criteria:**
- Model pinned to Flash
- Inputs documented: task diff, INDEX.json path, plan dir path
- Reverse-lookup flow: `git diff --name-only` → grep INDEX.json source_files → concept slugs
- Machine-truth update table: maps diff signals (new fn, removed fn, changed signature, new export, config key change) → doc fields
- AUTO-START/AUTO-END delimiter awareness: only writes between markers
- Skips documented: visibility changes, reorderings, prose descriptions, docstring bodies, README content
- Output to `tier1-staged/<concept>/human.md` and `llm.json` — NEVER writes to `docs/` directly
- Return contract: STATUS, CONCEPTS_TOUCHED, DRIFT_WARNINGS
- Preserves memories[] — never creates, edits, or removes memory entries
- Idempotent: re-running on same diff produces identical output

**Template sections to update:**
- `<!-- AUTO-START: entry-points -->` — function signatures, file paths, line numbers
- `<!-- AUTO-START: exports -->` — public export lists
- `<!-- AUTO-START: config-table -->` — config key rows (key, type, default, values)

---

### T004 — `commands/z-doc-rationale.md` (Tier 2 command)

- **Files:** `commands/z-doc-rationale.md` (new), `skills/z-doc-rationale/SKILL.md` (new)
- **Deps:** T001 (append-tier2-context.py)
- **Status:** [ ]
- **Complexity:** high
- **DOCS:** tier2-doc-rationale

Define the Tier 2 `/z-doc-rationale` command.

**Acceptance criteria:**
- Reads `$Z_HARNESS_PLAN_DIR/tier2-context.json`
- Aborts if `finalized: false` with clear message
- Spawns Pro subagent to produce: ADRs from `decisions[]` where `adr_worthy: true`, `rationale.md`, `migration-guide.md`
- Gap-fill flow: detects `gaps[]` with `status: missing`; presents ONLY gaps to user (not full review)
- Gap prompt: "Why [override]? (press Enter to skip)" — skippable
- Writes finals to `$Z_HARNESS_PLAN_DIR/tier2/ADR-NNN-<title>.md`, `rationale.md`, `migration-guide.md`
- Appends `<!-- AUTO-START: design-decisions -->` section with ADR links to affected concept docs
- Confidence caveat on tried-and-failed: per-entry source attribution, overall banner
- **Caveat format (F6 fix):** Uses existing doc conventions (blockquote style matching `> Last updated:` header), not emoji banners
- Memoizes: if tier2-context.json hash unchanged since last run, skip regeneration
- ADR numbering: reads `docs/adr/` directory, finds max N, allocates N+1 sequentially

**Required sections in command definition:**
- Setup (slug discovery, archive dir, claim acquire, register)
- Phase 1: Read + validate tier2-context.json
- Phase 2: Spawn Pro subagent for draft generation
- Phase 3: Gap-fill conversation
- Phase 4: Write finals + cross-link
- Phase 5: Finalize (deregister, push notification)

---

## Phase B: Implementer + Reviewer Contract Extensions

### T005 — `agents/implementer.md` — Extended return contract

- **Files:** `agents/implementer.md` (modify)
- **Deps:** None
- **Status:** [ ]
- **Complexity:** low
- **DOCS:** implementer

Add RATIONALE, TRIED, DEVIATIONS fields to implementer return contract.

**Acceptance criteria:**
- Fields added after SUMMARY section in return block format
- `RATIONALE:` (required) — 1-3 sentences explaining why chosen approach
- `TRIED:` (optional) — markdown list of `approach — failure reason`
- `DEVIATIONS:` (optional) — markdown list of `deviation — reason`
- Field contract documented: required/optional, validated by, used for
- Example in agent spec updated to include new fields
- Common-critique self-check: add "RATIONALE is present and matches implementation" check
- Backward compatible: existing returns without these fields still parse (fields default to empty/absent)

---

### T006 — `agents/reviewer.md` — Extended validation scope

- **Files:** `agents/reviewer.md` (modify)
- **Deps:** T005 (implementer contract)
- **Status:** [ ]
- **Complexity:** low
- **DOCS:** reviewer

Add DEVIATIONS validation, RATIONALE plausibility check, and TRIED consistency check to reviewer brief.

**Acceptance criteria:**
- New sections in reviewer prompt (additive, not replacing existing):
  - `### DEVIATIONS validation` — verify each claimed deviation against git diff
  - `### RATIONALE plausibility` — check code matches stated rationale (plausibility, not correctness)
  - `### TRIED consistency` (optional, if TRIED present) — flag gross inconsistencies (e.g., "TRIED says tokio but code still imports tokio")
- TRIED consistency findings reported as MINOR only (reviewer cannot validate dead-code claims)
- Findings use existing severity buckets (Blockers/Major/Minor)
- No changes to return format
- Test: reviewer correctly flags a fabricated DEVIATION that doesn't match diff as MAJOR

---

## Phase C: Orchestrator Integration — z-implement-all

### T007 — Tier 1 dispatch per task (z-implement-all main loop)

- **Files:** `skills/z-implement-all/SKILL.md` (modify), `exports/pi/prompts/z-implement-all.md` (modify if exists)
- **Deps:** T001, T002, T003
- **Status:** [ ]
- **Complexity:** high

Add Tier 1 doc sync dispatch after each task's reviewer passes.

**Acceptance criteria:**
- Insert after main loop step 7 (reviewer outcome) when no blockers, no majors
- **Diff capture (F5 fix):** Capture per-task diff at implementer return time — use the same diff the reviewer sees, not `git diff HEAD~1`. If reviewer already has the diff, reuse it.
- Spawn `tier1-doc-updater` (Flash) subagent with: task diff, INDEX.json path, plan dir path
- Parse return: STATUS, CONCEPTS_TOUCHED, DRIFT_WARNINGS
- DRIFT_WARNINGS: log `doc_drift` event per affected slug via `log-event.sh`
- Tier 1 failure: non-fatal — log `tier1_failed` event, continue to next task
- Log `tier1_complete` event with concepts_touched count
- Concurrency: Tier 1 runs in same track as reviewer (sequential within task, parallel across tracks)

---

### T008 — tier2-context.json accumulation (implement phase)

- **Files:** `skills/z-implement-all/SKILL.md` (modify)
- **Deps:** T001, T005
- **Status:** [ ]
- **Complexity:** medium

Accumulate per-task tried_and_failed, deviations, and breaking_changes into tier2-context.json.

**Acceptance criteria:**
- After implementer returns and before reviewer dispatch:
  - Parse RATIONALE from return
  - If TRIED non-empty: call `append-tier2-context.py --phase implement --field tried_and_failed` with parsed entries
  - If DEVIATIONS non-empty: call `append-tier2-context.py --phase implement --field deviations` with parsed entries
- After reviewer validates DEVIATIONS: append `reviewer_validated: true` to deviations entries
- Breaking change detection: derive from implementer's FILES_CHANGED and diff — detect changed public API signatures (function signature delta in public modules)
  - If breaking changes detected: call `append-tier2-context.py --phase implement --field breaking_changes`
- Use `--upsert` flag to handle task re-runs (dedup by TASK_ID)
- Non-fatal: append failure logs `tier2_append_failed` event, continues

---

### T009 — Human override capture (z-implement-all decision gates)

- **Files:** `skills/z-implement-all/SKILL.md` (modify)
- **Deps:** T001
- **Status:** [ ]
- **Complexity:** low

Capture human override reasons at z-implement-all decision gates.

**Acceptance criteria:**
- At each AskUserQuestion gate where the human overrides the orchestrator's recommendation:
  - Present follow-up: "Why [choice] over [recommended]? (press Enter to skip)"
  - If reason provided: call `append-tier2-context.py --phase implement --field human_overrides` with decision_id, override, reason
  - If Enter pressed (no reason): skip capture; gap will be detected at finalization
- Gates to instrument:
  - Blocked task decision (user chooses to continue vs halt)
  - Decision-needed path (user chooses approach)
  - Compaction breakpoint continuation (user chooses to continue vs pause)
- Log `human_override_captured` event on capture; `human_override_skipped` on skip

---

### T010 — Tier 1 reconciliation in Finalize

- **Files:** `skills/z-implement-all/SKILL.md` (modify)
- **Deps:** T002, T007
- **Status:** [ ]
- **Complexity:** low

Add Tier 1 reconciliation step in z-implement-all Finalize phase.

**Acceptance criteria:**
- After all tasks complete, before deregister:
  - If `tier1-staged/` has content: run `scripts/reconcile-tier1-staged.py`
  - On success: log `tier1_reconciled` event with concept count
  - On failure: halt reconciliation; log `tier1_reconcile_failed` event; surface conflict to user
- Reconciliation runs even if some Tier 1 tasks failed (partial reconciliation of successful tasks)
- Dry-run option: if `Z_HARNESS_TIER1_DRY_RUN=1`, run with `--dry-run`

---

## Phase D: Orchestrator Integration — z-plan

### T011 — tier2-context.json initialization (z-plan Phase 3)

- **Files:** `skills/z-plan/SKILL.md` (modify)
- **Deps:** T001
- **Status:** [ ]
- **Complexity:** medium

Initialize tier2-context.json during z-plan Phase 3 (consultant synthesis).

**Acceptance criteria:**
- After writing `phase3-decisions-final.md`:
  - Call `append-tier2-context.py --phase plan --field decisions` with synthesized decisions
  - Call `append-tier2-context.py --phase plan --field consultant_findings` with per-arm findings + dispositions
  - Set `spec_summary` from Phase 0 premise summary
  - Set `plan_summary` from approved decisions overview
- Initialize skeleton if tier2-context.json doesn't exist
- Non-fatal: failure logs `tier2_init_failed` event; tier2-context.json just won't exist for this run

---

### T012 — Human override capture (z-plan Phase 5)

- **Files:** `skills/z-plan/SKILL.md` (modify)
- **Deps:** T001, T011
- **Status:** [ ]
- **Complexity:** low

Capture human override reasons during z-plan Phase 5 approval.

**Acceptance criteria:**
- At the Phase 5 approval gate, after user overrides any decision:
  - Present follow-up: "Why [override] over [recommended]? (press Enter to skip)"
  - If reason provided: call `append-tier2-context.py --phase plan --field human_overrides` with decision_id, override, reason
  - If Enter pressed: skip capture
- Log `human_override_captured` or `human_override_skipped` event
- Also update tier2-context.json decisions[].human_override and .human_reason fields via append script

---

## Phase E: Orchestrator Integration — z-review-all

### T013 — review_patterns accumulation (z-review-all Phase 5)

- **Files:** `commands/z-review-all.md` (modify)
- **Deps:** T001
- **Status:** [ ]
- **Complexity:** medium

Append aggregate review patterns to tier2-context.json during z-review-all findings aggregation.

**Acceptance criteria:**
- After building `findings.md` in Phase 5:
  - Extract aggregate patterns: themes that appear across both consultant returns, consensus/disagreement signals
  - Call `append-tier2-context.py --phase review --field review_patterns` with extracted patterns
- Pattern format: `{"pattern": "...", "source": "consultant-primary|consultant-secondary|consensus", "finding": "...", "recommendation": "..."}`
- Non-fatal: failure logs event, continues

---

### T014 — Tier 2 significance gate + recommendation (z-review-all Finalize)

- **Files:** `commands/z-review-all.md` (modify)
- **Deps:** T001, T008, T013
- **Status:** [ ]
- **Complexity:** medium

Finalize tier2-context.json and apply three-signal OR gate for Tier 2 recommendation.

**Acceptance criteria:**
- After Phase 6 (REVIEW-TASKS.md), before Finalize:
  - Mark tier2-context.json `finalized: true` with current timestamp
  - Detect gaps: iterate human_overrides with missing `reason`, mark as `status: missing`
  - Write gaps[] to tier2-context.json
- Three-signal OR gate evaluation:
  - Signal 1: `consultant_findings[]` non-empty → fires
  - Signal 2: `breaking_changes[]` non-empty → fires
  - Signal 3: `deviations[]` non-empty → fires
- If any signal fires:
  - Push notification: "Pipeline complete. N breaking changes, M plan deviations. Run /z-doc-rationale."
  - Add `/z-doc-rationale` to post-pipeline recommendations
- If no signals fire:
  - "Pipeline complete. No significant design decisions. Tier 2 skipped."
  - No /z-doc-rationale in recommendations
- Archive copy of tier2-context.json written to `archive/$RUN/tier2-context.json`

---

## Phase F: Docs + Bootstrap

### T015 — AUTO-START/AUTO-END marker migration

- **Files:** `scripts/add-doc-markers.py` (new), multiple `docs/human/*.md` (modify)
- **Deps:** T003 (marker format defined)
- **Status:** [ ]
- **Complexity:** low

Add delimiter markers to existing human-tier docs.

**Acceptance criteria:**
- Script scans `docs/human/*.md` for concepts with machine-truth sections
- For each concept doc:
  - Detects `## Key entry points` section → wraps list items in `<!-- AUTO-START: entry-points -->` / `<!-- AUTO-END: entry-points -->`
  - Detects `## Public API` or equivalent → wraps in `<!-- AUTO-START: exports -->` / `<!-- AUTO-END: exports -->`
  - Detects config tables (if present) → wraps in `<!-- AUTO-START: config-table -->` / `<!-- AUTO-END: config-table -->`
- Adds no markers if section not present or unparseable
- `--dry-run` flag: shows diffs, doesn't write
- Idempotent: running twice on same file produces no changes on second run
- Handles concepts already marked without double-wrapping

---

### T016 — Update `docs/llm/INDEX.json`

- **Files:** `docs/llm/INDEX.json` (modify)
- **Deps:** T003, T004
- **Status:** [ ]
- **Complexity:** low

Add new concept entries and update existing ones.

**Acceptance criteria:**
- Add `tier1-doc-updater` concept entry with source_files, summary, last_updated
- Add `tier2-doc-rationale` concept entry with source_files, summary, last_updated
- Update `implementer` entry: add RATIONALE/TRIED/DEVIATIONS to covered scope
- Update `reviewer` entry: add DEVIATIONS validation to covered scope
- Update `doc-updater` entry: add relationship note to tier1-doc-updater
- Version bump: increment `z_harness_version` or add `updated_at` timestamp

---

### T017 — Concept docs for new agents

- **Files:** `docs/human/tier1-doc-updater.md` (new), `docs/human/tier2-doc-rationale.md` (new), `docs/llm/tier1-doc-updater.json` (new), `docs/llm/tier2-doc-rationale.json` (new)
- **Deps:** T003, T004, T015
- **Status:** [ ]
- **Complexity:** medium
- **DOCS:** tier1-doc-updater, tier2-doc-rationale

Create human-tier and LLM-tier docs for the two new concepts.

**Acceptance criteria:**
- Human docs follow existing template (Overview, Key entry points with markers, How it interacts, Edge cases/gotchas)
- AUTO-START/AUTO-END markers present from creation
- LLM JSONs follow schema: concept, last_updated, source_file, confidence, entry_points, depends_on, consumed_by, invariants, gotchas, memories
- Entry points accurate with file:line references
- Depends_on / consumed_by graph consistent with existing agent ecosystem
- Memories initialized as `[]`

---

### T018 — End-to-end integration test

- **Files:** No production files; test artifacts only
- **Deps:** T001-T017
- **Status:** [ ]
- **Complexity:** high

Verify the full pipeline works end-to-end.

**Acceptance criteria:**
- Test scenario: create a small plan with 2-3 tasks that touch existing docs
- Run z-plan → verify tier2-context.json initialized with decisions
- Run z-implement-all → verify:
  - Tier 1 dispatches per task (check tier1-staged/ has output)
  - tier2-context.json has tried_and_failed/deviations per task
  - Reconciliation applies staged updates (check docs/ updated)
  - MEMORIES-FLAT.md regenerated
- Run z-review-all → verify:
  - tier2-context.json has review_patterns
  - tier2-context.json finalized
  - Significance gate fires (or not) correctly
  - /z-doc-rationale recommendation appears
- Run /z-doc-rationale → verify:
  - ADRs, rationale.md, migration-guide.md produced
  - Gap-fill conversation presents only missing gaps
  - Design-decisions cross-links added to concept docs
- Regression: run /z-maintain-docs → verify existing behavior unchanged
- Regression: run existing pipeline without doc changes → verify no breakage

---

## Task Summary

| ID | Name | Phase | Complexity | Dependencies |
|---|---|---|---|---|
| T001 | append-tier2-context.py | A: Foundation | medium | — |
| T002 | reconcile-tier1-staged.py | A: Foundation | medium | — |
| T003 | tier1-doc-updater agent | A: Foundation | medium | — |
| T004 | z-doc-rationale command | A: Foundation | high | T001 |
| T005 | implementer contract | B: Contracts | low | — |
| T006 | reviewer extension | B: Contracts | low | T005 |
| T007 | Tier 1 dispatch per task | C: z-implement-all | high | T001, T002, T003 |
| T008 | tier2-context accumulation | C: z-implement-all | medium | T001, T005 |
| T009 | human override capture (impl) | C: z-implement-all | low | T001 |
| T010 | Tier 1 reconciliation | C: z-implement-all | low | T002, T007 |
| T011 | tier2 init (z-plan) | D: z-plan | medium | T001 |
| T012 | human override capture (plan) | D: z-plan | low | T001, T011 |
| T013 | review_patterns accumulation | E: z-review-all | medium | T001 |
| T014 | Tier 2 significance gate | E: z-review-all | medium | T001, T008, T013 |
| T015 | marker migration | F: Docs | low | T003 |
| T016 | INDEX.json update | F: Docs | low | T003, T004 |
| T017 | concept docs | F: Docs | medium | T003, T004, T015 |
| T018 | E2E integration test | F: Docs | high | T001–T017 |
