# Tasks for rewrite-z-test-invariants

**Plan:** rewrite-z-test-invariants
**SPEC.md:** ./SPEC.md
**PLAN.md:** ./PLAN.md

---

## T001 — Define INVARIANTS.json schema + constant
**Status:** [x]
**Complexity:** low
**Files:** `skills/z-test/SKILL.md` (add schema constant section), new: `docs/schemas/invariant.schema.json`
**Dependencies:** none
**Description:** Define the 10-field invariant entry schema as a JSON Schema file (`docs/schemas/invariant.schema.json`) following the existing `docs/schemas/axiom.schema.json` pattern. Define the top-level `docs/INVARIANTS.json` structure (version, generated_at, invariants[]). Document the schema in SPEC.md-style detail within the /z-test skill for implementer reference.

**Acceptance:**
- `docs/schemas/invariant.schema.json` exists and validates against JSON Schema draft-2020-12
- Schema defines: id (string, kebab-case), description (string), tags (array, subset of TAGS.txt), failure_class (string), fixture_schema (optional object, JSON Schema), fixture_defaults (optional object), severity (enum: blocker|major|minor), source_files (array of strings), last_updated (ISO 8601), source (enum: spec|plan|user-concern|code-review|axiom-derived)
- Self-validation: the schema file validates against the JSON Schema meta-schema
- Schema docs appear in /z-test skill for implementer consumption

---

## T002 — Implement invariant validation logic
**Status:** [x]
**Complexity:** medium
**Files:** `scripts/validate-invariants.py` (new), `skills/z-test/SKILL.md` (Phase 4 fixture validation)
**Dependencies:** T001
**Description:** Create a Python validation script that validates INVARIANTS.json against the schema. Validates: id uniqueness, tags subset of TAGS.txt, fixture_schema validates fixture_defaults when both present, fixture_schema has >=1 non-trivial constraint, severity is valid enum. Used by /z-init-docs (on write), /z-test (on load), and /z-maintain-docs (on staleness scan). Also implements /z-test Phase 4 fixture validation: for each TESTS.md entry's `fixture:` field, validate against the invariant's fixture_schema.

**Acceptance:**
- `scripts/validate-invariants.py --file docs/INVARIANTS.json` exits 0 on valid, non-zero with specific error on invalid
- Detects duplicate IDs, invalid tags, mismatched fixture_schema/fixture_defaults
- Returns distinct exit codes: 0=valid, 1=schema error, 2=constraint violation, 3=IO error
- Integrated into /z-test Phase 4 for fixture validation against invariant schemas

---

## T003 — Add --invariants flag to /z-init-docs
**Status:** [x]
**Complexity:** medium
**Files:** `skills/z-init-docs/SKILL.md`
**Dependencies:** T001, T002
**Description:** Extend /z-init-docs with a new "Invariant discovery" phase, gated on `--invariants` flag. Scan all discovery paths for SPEC.md files (active plans at `z-harness/*/SPEC.md`, archived runs at `z-harness/*/archive/*/SPEC.md`, repo plans at `plans/*/SPEC.md`, state-dir plans via `plan-path.sh base_dir`) for `**INVARIANT:**`, `**MUST:**`, `**MUST NOT:**`, `**DANGER:**` lines. Idempotent: if INVARIANTS.json already exists, scan only for NEW durable invariants (not present by ID or description fuzzy match).

**Acceptance:**
- `/z-init-docs --invariants` scans all SPEC.md files in the plan archive
- Extracts invariant-like lines using the same pattern as /z-test Phase 1
- Passes candidates to durability heuristic (T004)
- Fails gracefully with "no candidates found" when no SPEC.md files exist
- Idempotent: re-running doesn't duplicate existing entries

---

## T004 — Implement durability heuristic + candidate proposal
**Status:** [x]
**Complexity:** medium
**Files:** `skills/z-init-docs/SKILL.md` (invariant discovery phase), `scripts/validate-invariants.py` (optional: heuristic logic)
**Dependencies:** T003
**Description:** Implement the durability heuristic: a candidate invariant from SPEC.md is "durable" if (a) it appears in >=2 plans across different slugs, OR (b) it references cross-module contracts (source_files from multiple directories, or uses "system"/"cross-cutting"/"cross-module" language). Durable candidates are proposed as INVARIANTS.json entries with auto-assigned stable IDs, auto-classified tags from TAGS.txt, and `source: spec`. Non-durable candidates are logged but not proposed.

**Acceptance:**
- Durability heuristic correctly classifies multi-plan invariants as durable
- Cross-module detection: invariant that references files in >=2 distinct top-level directories is durable
- Auto-assigned IDs use `inv_<NNN>` format with zero-padded sequential numbering
- Auto-classified tags: keyword match against TAGS.txt (e.g., "fee" → correctness, "time" → time-window)
- Non-durable candidates are logged to the archive for human review

---

## T005 — Generate INVARIANTS.md + update INDEX.json
**Status:** [x]
**Complexity:** low
**Files:** `skills/z-init-docs/SKILL.md` (invariant discovery phase), `docs/llm/INDEX.json` (add invariants entry)
**Dependencies:** T004
**Description:** After writing INVARIANTS.json (T004's candidate proposal accepted by user), generate a human-readable `docs/INVARIANTS.md` Markdown rendering. Each invariant is rendered as a section with id, description, tags, severity, failure class, source files, source provenance. Add an invariants entry to `docs/llm/INDEX.json` so doc-fetcher can discover it. Follow the same regeneration pattern as MEMORIES-FLAT.md.

**Acceptance:**
- `docs/INVARIANTS.md` is generated from INVARIANTS.json, one section per invariant
- Markdown is human-readable (no raw JSON embedded)
- INDEX.json updated with: `{"slug": "invariants", "source_files": ["docs/INVARIANTS.json"], "last_updated": "<iso>", "confidence": "high", "summary": "System-level behavioral invariants"}`
- Regeneration is idempotent (same JSON → same MD)
- Atomic write via tmpfile + flush + fsync + os.replace()

---

## T006 — Rewrite /z-test Phases 0-2 (Discovery → Draft)
**Status:** [x]
**Complexity:** high
**Files:** `skills/z-test/SKILL.md`
**Dependencies:** T001
**Description:** Rewrite /z-test's Phase 0 (Discovery), Phase 1 (Load invariants + risk-rank), and Phase 2 (Draft behavioral test cases).
- Phase 0: Load INVARIANTS.json if exists; warn if absent. Discover plan via slug. Require SPEC+PLAN+TASKS.
- Phase 1: Load invariants from INVARIANTS.json. Extract SPEC.md invariants for fallback. For each task: explicit `**Invariants:**` annotation match, then fuzzy tag match as discovery hint. Risk-rank tasks. Ask user bug-class concerns.
- Phase 2: Draft behavioral test entries with new v2 fields (invariant_id, invariant_description, layer, fixture). Every assertion names a specific failure class. Cap at ~25 drafts. Anti-rubber-stamp check on each.

**Acceptance:**
- Phase 0 falls back gracefully when INVARIANTS.json is absent (warn, use SPEC.md only)
- Phase 1 correctly matches explicit `**Invariants:** inv_001, inv_003` annotations
- Phase 1 fuzzy matching suggests additional invariants, doesn't auto-bind
- Phase 2 entries have all v2 fields: invariant_id, invariant (optional), invariant_description, layer, fixture, assertion naming failure class
- Draft count capped at 25, preferring mandatory over optional

---

## T007 — Rewrite /z-test Phases 3-4 (Cross-LLM consult + Synthesize)
**Status:** [x]
**Complexity:** high
**Files:** `skills/z-test/SKILL.md`
**Dependencies:** T006
**Description:** Rewrite /z-test's Phase 3 (evolved cross-LLM consult) and Phase 4 (synthesize with fixture validation).
- Phase 3: Extend consultant prompts with INVARIANTS.json verbatim. Add questions: "Which INVARIANTS.json invariants have no test?", "Which fixture values would expose a violation?" Same per-draft critique + trivial-drop detection.
- Phase 4: Merge consultant returns. Apply per-draft verdicts. Validate each entry's `fixture:` against its invariant's `fixture_schema` using T002's validation logic. For uncovered invariants, propose draft entries for Phase 5 approval.

**Acceptance:**
- Consultant prompts include INVARIANTS.json verbatim
- New coverage-gap question identifies uncovered invariants
- Phase 4 fixture validation rejects entries whose fixture doesn't satisfy the schema
- Uncovered block/major invariants flagged for user approval
- Track n_dropped_by_consult, n_added_by_consult, n_strengthened as before

---

## T008 — Rewrite /z-test Phases 5-8 (Approve → Finalize)
**Status:** [x]
**Complexity:** medium
**Files:** `skills/z-test/SKILL.md`
**Dependencies:** T007
**Description:** Rewrite /z-test's Phase 5 (Present + approve), Phase 6 (Write TESTS.md v2), Phase 7 (Cross-link), Phase 8 (Finalize).
- Phase 5: Add uncovered-invariant count to approval gate. Same accept/edit/abandon options.
- Phase 6: Write TESTS.md with `**Version:** 2` frontmatter, `**Invariants file:**`, `**Covered invariants:**`, `**Uncovered invariants (blocker/major):**` header fields. Each TEST-NNN block uses v2 format.
- Phase 7: Cross-link into TASKS.md (same merge semantics).
- Phase 8: Finalize with uncovered-invariant counts in event.

**Acceptance:**
- TESTS.md v2 written with version frontmatter + covered/uncovered invariant lists
- TEST-NNN blocks have v2 fields (invariant_id, invariant_description, layer, fixture)
- v1 TEST-NNN blocks from legacy mode have no version field (backward compat)
- Cross-link merge preserves existing `**Tests:**` entries
- Finalize event includes uncovered_invariant_count

---

## T009 — Update commands/z-test.md + .agent artifacts
**Status:** [x]
**Complexity:** low
**Files:** `commands/z-test.md`, `.agent/workflows/z-test.md`
**Dependencies:** T008
**Description:** Update the command frontmatter and description to reflect the new system-level invariant test scope. Update runtime contract conformance table. Copy updated files to .agent/ directory.

**Acceptance:**
- `commands/z-test.md` description updated: "System-level invariant test planner..."
- Frontmatter: `version: 2`
- Runtime contract table updated for new phases
- `.agent/workflows/z-test.md` matches commands/z-test.md

---

## T010 — Update /z-implement-all for v2 TESTS.md
**Status:** [x]
**Complexity:** medium
**Files:** `skills/z-implement-all/SKILL.md`
**Dependencies:** T008
**Description:** Update the implementer subagent's TESTS.md parsing to handle version 2 format. Read frontmatter `**Version:**` field. If v2: grep `## TEST-NNN` blocks, read `**Invariant ID:**`, `**Fixture:**`, `**Layer:**`, `**Target file:**`, `**Assertion:**`. Skip `layer: full-chain` entries (implemented later). If v1 (no version): use existing parsing. Update per-task acceptance check (step 7b) to filter test execution by TEST-NNN IDs if v2.

**Acceptance:**
- Implementer correctly parses v2 TESTS.md entries with all new fields
- `layer: full-chain` entries are skipped by implementer (not implemented in task diff)
- Test code uses `**Fixture:**` values as test inputs
- v1 TESTS.md parsing unchanged (backward compatible)
- Per-task acceptance check filters to task's TEST-NNN entries

---

## T011 — Update /z-review-all for full-chain tests
**Status:** [x]
**Complexity:** medium
**Files:** `skills/z-review-all/SKILL.md`
**Dependencies:** T008
**Description:** Update /z-review-all's Phase 3.5 test-suite execution to distinguish per-task vs full-chain tests. Read TESTS.md frontmatter for `**Version:**`. If v2: run per-task tests. If full-chain test files exist (written by T017), run them and report separately as "full-chain invariant violations". If full-chain files are missing, gracefully skip with a note. If v1: run all tests (legacy).

**Acceptance:**
- Phase 3.5 reads TESTS.md version field
- v2: per-task tests executed, full-chain tests executed only if target files exist
- Missing full-chain targets: graceful skip with info-level log, no error
- Full-chain failures categorized as "invariant violations" in review output
- v1: legacy behavior unchanged

---

## T012 — Update /z-maintain-docs for INVARIANTS.json staleness
**Status:** [x]
**Complexity:** low
**Files:** `skills/z-maintain-docs/SKILL.md`
**Dependencies:** T001
**Description:** Add INVARIANTS.json to the staleness scan in /z-maintain-docs Phase 1. For each invariant entry, compare `source_files[]` max mtime to `last_updated`. Flag stale invariants. On staleness detection, dispatch doc-updater subagent with mode `invariants` to review and update affected entries. Same threshold logic as existing docs/llm/ staleness.

**Acceptance:**
- Staleness scan includes INVARIANTS.json entries
- Stale invariants flagged with `source_files` mtime comparison
- doc-updater dispatched for stale invariants in mode `invariants`
- Staleness events logged to events.jsonl

---

## T013 — Add invariant promotion nudge to /z-plan
**Status:** [x]
**Complexity:** medium
**Files:** `skills/z-plan/SKILL.md`
**Dependencies:** T001, T002
**Description:** After /z-plan Phase 6 (write SPEC.md), add an invariant promotion nudge. Gated on: (a) INVARIANTS.json exists, (b) SPEC.md contains `**INVARIANT:**` / `**MUST:**` lines not matching any existing INVARIANTS.json entry, (c) invariant appears durable (references >=2 modules or uses cross-cutting language). If all gates pass, surface via AskUserQuestion: "N SPEC.md invariants look durable. Promote to INVARIANTS.json?" Options: promote all, pick, skip.

**Acceptance:**
- Nudge only fires when all 3 gates pass
- Non-matching detection uses description fuzzy comparison against existing invariant descriptions
- Durability check uses same heuristic as T004 (multi-module or cross-cutting language)
- User-selected invariants are written to INVARIANTS.json by orchestrator
- INVARIANTS.md is regenerated after write

---

## T014 — Create scripts/invariant-check.sh
**Status:** [x]
**Complexity:** medium
**Files:** `scripts/invariant-check.sh` (new)
**Dependencies:** T008, T002
**Description:** Create a CI-friendly script that reads INVARIANTS.json + TESTS.md, runs the test suite, and exits non-zero on mandatory-invariant violations. Parse TESTS.md frontmatter for `**Covered invariants:**` and `**Uncovered invariants (blocker):**`. If uncovered blockers → exit 3 (coverage gap). Run test suite via test-runner.json. Parse output for TEST-NNN results. For each failed mandatory test → log invariant ID + failure class. Exit 0 if all pass; exit 1 if any mandatory fails.

**Acceptance:**
- Exit codes: 0=pass, 1=test failure, 3=coverage gap (uncovered blocker)
- Reads test command from test-runner.json (same as /z-implement-all)
- Parses pytest/JUnit XML output for TEST-NNN in test names
- Logs invariant violations with ID + failure class to stdout
- Works without z-harness installed (standalone shell script, only needs INVARIANTS.json + TESTS.md + test command)

---

## T015 — Add --ci flag to /z-test
**Status:** [x]
**Complexity:** low
**Files:** `skills/z-test/SKILL.md`
**Dependencies:** T008, T002
**Description:** Add `--ci` flag to /z-test. In CI mode: load INVARIANTS.json + TESTS.md, check for uncovered blocker invariants, validate all fixtures against schemas, emit machine-readable JSON summary, exit non-zero on violations. Does NOT write new TESTS.md entries (read-only validation mode). Does NOT dispatch cross-LLM consult (CI is deterministic).

**Acceptance:**
- `--ci` flag triggers read-only validation mode
- JSON summary emitted to stdout: {status, covered_invariants, uncovered_blockers, test_command}
- Exit codes: 0=all clear, 1=invariant violations, 3=coverage gap
- No TESTS.md writes, no consultant dispatch, no AskUserQuestion
- Works with test-runner.json for test command discovery

---

## T016 — Regenerate exports + finalize docs
**Status:** [x]
**Complexity:** low
**Files:** `exports/pi/prompts/z-test.md`, `exports/pi/prompts/z-test-skill.md`, `exports/codex/prompts/z-test.md`, `exports/codex/prompts/z-test-skill.md`, `exports/agy/prompts/z-test.md`, `exports/agy/prompts/skill-z-test.md`, `.agent/skills/z-test/SKILL.md`, `docs/llm/INDEX.json`
**Dependencies:** T009, T010, T011, T012, T013, T014, T015
**Description:** Regenerate all export prompts from updated skills. Update INDEX.json invariants entry. Copy updated z-test skill to .agent/skills/. Verify all exports are self-consistent (no stale references to old /z-test format).

**Acceptance:**
- All 6 export prompt files regenerated from updated skills
- `.agent/skills/z-test/SKILL.md` matches `skills/z-test/SKILL.md`
- INDEX.json invariants entry updated (or created if T005 not run)
- No stale references to old TESTS.md format (v1-only language) in exports
- Cross-references between exports are consistent

---

## Dependency graph

```
T001 ─┬─ T002 ─┬─ T003 ─ T004 ─ T005
      │         │
      │         ├─ T014
      │         └─ T015
      │
      ├─ T006 ─ T007 ─ T008 ─┬─ T009
      │                       ├─ T010 ─── T017
      │                       ├─ T011
      │                       └─ T013
      │
      └─ T012

T016 (depends on T009-T015 all complete)
T017 (depends on T010, T016)
```


## T017 — Write full-chain invariant test code
**Status:** [x]
**Complexity:** medium
**Files:** `scripts/invariant-check.sh` (extend), `skills/z-test/SKILL.md` (Phase 8 full-chain test generation)
**Dependencies:** T010, T016
**Description:** After all per-task test code is implemented (T010) and exports are finalized (T016), write the full-chain invariant test entries. For each TESTS.md entry with `**Layer:** full-chain`, generate the actual test code file at the path specified by `**Target file:**`. Each test covers the invariant's assertion end-to-end: load real fixture data, exercise the composed system path, assert the behavioral invariant holds. The test MUST be runnable by the same test runner used for per-task tests.

**Acceptance:**
- Test file exists for each `layer: full-chain` entry in TESTS.md
- Each test asserts the behavioral invariant from the entry's `**Assertion:**`
- Tests use fixture data consistent with the invariant's `fixture_schema`
- Tests are runnable via the same test command (pytest, etc.)
- Exit code 0 when all full-chain invariants hold
- Exit code 1+ with specific violation output when an invariant is violated

---

|## Implementation order

1. **T001** (schema) — no deps, foundation
2. **T002** (validation) — depends on T001
3. **Parallel:** T003+T004+T005 (bootstrap chain), T006 (z-test rewrite start), T012 (maintain-docs)
4. **T007** (consult rewrite) — depends on T006
5. **T008** (z-test finalize) — depends on T007
6. **Parallel:** T009 (commands), T010 (implement-all), T011 (review-all), T013 (z-plan nudge), T014 (CI script), T015 (--ci flag)
7. **T016** (exports) — depends on all
8. **T017** (full-chain test code) — depends on T010, T016
