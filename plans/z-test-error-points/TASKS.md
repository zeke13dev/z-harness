# TASKS: z-test dual-source redesign

<!-- TASK ORDER: schema infrastructure first (no behavior change), then data flow (z-review-all writes), then consumer (z-test reads), then cleanup -->

---

## T001 — Create error_points.schema.json + update invariant.schema.json

**Files:**
- `docs/schemas/error_points.schema.json` (NEW)
- `docs/schemas/invariant.schema.json` (EDIT)

**Description:**
Create the JSON Schema for ERROR_POINTS.json and add three optional fields to the existing invariant schema.

**error_points.schema.json:**
- JSON Schema draft-2020-12.
- Top-level: `version` (int, 1), `generated_at` (ISO-8601), `error_points` (array).
- Per-entry required fields: `ep_id` (pattern `ep_NNN`), `pattern` (1-500 chars), `pattern_signature` (16-char hex string), `anchor_module` (non-empty string), `failure_class` (1-300 chars), `severity` (enum: blocker|major|minor), `frequency` (int ≥ 1), `first_seen` (ISO-8601), `last_seen` (ISO-8601), `sightings` (array, min 1, max 20), `novelty_score` (number 0.0-1.0), `tests_targeting` (array of string), `archived` (boolean).
- Optional fields: `last_test_pass` (ISO-8601 or null), `last_test_fail` (ISO-8601 or null), `archived_at` (ISO-8601 or null, required when archived=true).

**invariant.schema.json:**
- Add `sighting_count` property: `{"type": "integer", "minimum": 0, "default": 0}`.
- Add `last_sighting` property: `{"type": ["string", "null"], "format": "date-time", "default": null}`.
- Add `anchor_module` property: `{"type": ["string", "null"], "default": null}`.
- Do NOT add to `required` array — backward-compatible.
- Keep `additionalProperties: false` (the new fields are whitelisted properties).

**Acceptance:**
- [ ] `docs/schemas/error_points.schema.json` exists and passes JSON Schema meta-validation (valid JSON, draft-2020-12 structure).
- [ ] `docs/schemas/invariant.schema.json` includes the three new fields as optional properties.
- [ ] Existing `docs/INVARIANTS.json` entries (without the new fields) validate against the updated schema.
- [ ] No required fields added to invariant schema.

**Invariants:**  
None (schema-only task).
**Tests:** TEST-006 (atomic write — see TESTS.md)

---

## T002 — Create validate-error-points.py + update validate-invariants.py

**Files:**
- `scripts/validate-error-points.py` (NEW)
- `scripts/validate-invariants.py` (EDIT)

**Description:**
Create a validation script for ERROR_POINTS.json and update the existing invariant validator to accept the three new optional fields.

**validate-error-points.py:**
- Mirror the structure of `scripts/validate-invariants.py` (same argparse pattern, same exit codes, same constraint-rule approach).
- Load `docs/schemas/error_points.schema.json` for structural validation.
- Constraint rules (exit code 2):
  - `ep_id` uniqueness across all entries.
  - `pattern_signature` is exactly 16 hex chars.
  - `frequency ≥ 1` for non-archived entries.
  - `sightings` array is non-empty for non-archived entries.
  - `last_seen ≥ first_seen`.
  - `severity` in {blocker, major, minor}.
  - `archived` entries must have `archived_at`; active entries must NOT have `archived_at`.
  - `novelty_score` must equal `1 / (1 + frequency)`.
- Support `--file` mode (validate ERROR_POINTS.json).
- Support `--fixture` + `--schema` mode (validate a fixture against a schema, for TESTS.md fixture validation — same as invariant validator).
- Exit codes: 0=valid, 1=schema error, 2=constraint violation, 3=I/O error.

**validate-invariants.py:**
- Accept `sighting_count`, `last_sighting`, `anchor_module` as valid optional fields (no constraint errors for their absence or presence).
- If `sighting_count` is present, validate it is integer ≥ 0.
- If `last_sighting` is present and non-null, validate it is valid ISO-8601.
- No other changes — all existing constraint rules unchanged.

**Acceptance:**
- [ ] `scripts/validate-error-points.py --file docs/ERROR_POINTS.json` exits 0 when ERROR_POINTS.json is valid (after T003 creates it).
- [ ] `scripts/validate-error-points.py --file <path>` catches constraint violations (duplicate ep_id, missing fields, bad severity, etc.) and exits 2.
- [ ] `scripts/validate-error-points.py --fixture <json> --schema <json>` validates fixtures against schemas (reuses invariant fixture validation logic).
- [ ] `scripts/validate-invariants.py --file docs/INVARIANTS.json` exits 0 on current INVARIANTS.json (no regressions).
- [ ] Existing invariants with the new fields validate correctly.
- [ ] Both scripts are chmod +x.

**Invariants:**  
None (validation-only task).
**Tests:** TEST-006 (atomic write — see TESTS.md)

---

## T003 — Create ERROR_POINTS.json with init bootstrap

**Files:**
- `docs/ERROR_POINTS.json` (NEW)

**Description:**
Create the initial ERROR_POINTS.json with an init-bootstrap scan of the codebase for bug patterns. This provides seed data so the registry isn't empty on first use.

**Procedure:**
1. Create minimal valid structure:
   ```json
   {
     "version": 1,
     "generated_at": "<current ISO-8601>",
     "error_points": []
   }
   ```
2. Run init bootstrap scan:
   - Scan `skills/`, `scripts/`, and top-level `.md` files for TODO/FIXME/HACK/XXX/BUG comments.
   - Scan `.py` and `.sh` files for empty error handlers: `except pass`, `except: pass`, `catch (e) {}`, `|| true` after commands that could fail.
   - Extract 3-word context around each hit.
   - Group hits by (normalized module prefix first 2 path segments, comment/fixme type).
   - For groups with ≥ 2 hits in same module prefix, create an error point entry:
     ```json
     {
       "ep_id": "ep_NNN",
       "pattern": "<derived from comment text or error-handler context>",
       "pattern_signature": "<sha256 of (module_prefix::norm_pattern::minor)[:16]>",
       "anchor_module": "<module path of first hit>",
       "failure_class": "<derived from pattern>",
       "severity": "minor",
       "frequency": 1,
       "first_seen": "<current ISO-8601>",
       "last_seen": "<current ISO-8601>",
       "sightings": [{"run_id": "init_bootstrap", "finding_id": "bootstrap_<N>", "module_path": "<path>"}],
       "novelty_score": 0.5,
       "last_test_pass": null,
       "last_test_fail": null,
       "tests_targeting": [],
       "archived": false
     }
     ```
   - Cap at 20 entries (hard limit for init bootstrap).
3. Validate with `python3 scripts/validate-error-points.py --file docs/ERROR_POINTS.json`. Fix any validation errors.
4. Write using atomic write discipline (tmpfile → flush → fsync → os.replace()).

**Acceptance:**
- [ ] `docs/ERROR_POINTS.json` exists and validates with exit 0.
- [ ] Contains 1-20 error point entries sourced from init bootstrap scan.
- [ ] All entries have valid `ep_id`, `pattern_signature`, `severity: minor`.
- [ ] File is valid JSON with correct top-level structure.
- [ ] Atomic write discipline followed (no partial file on disk).

**Invariants:**  
None (data creation task).
**Tests:** TEST-001 (ep_001 — error suppression), TEST-002 (ep_002 — TODO tracking), TEST-003 (ep_003 — shell assertions), TEST-006 (inv_003 — atomic write)

---

## T004 — Extend z-review-all Phase 5.5 for error point extraction + invariant matching

**Files:**
- `skills/z-review-all/SKILL.md` (EDIT)

**Description:**
Extend the existing Phase 5.5 (invariant extraction from review findings) to also:
1. Match findings against existing invariants and increment `sighting_count`/`last_sighting`/`anchor_module`.
2. Match findings against existing error points by deterministic `pattern_signature`.
3. Create new error point candidates from unmatched findings.
4. Enforce rate-limiting on writes.
5. Prune eligible error points after write.

**Changes to Phase 5.5:**

**Gate expansion:** Phase 5.5 currently gates on `docs/INVARIANTS.json` existing AND findings with severity ≥ major. Expand gate: also run if `docs/ERROR_POINTS.json` exists (for error-point matching/extraction, even if INVARIANTS.json is absent). If only ERROR_POINTS.json exists, skip invariant extraction but still do error point extraction.

**Pre-Haiku deterministic matching (orchestrator computes):**
1. For each finding with severity ≥ major, compute `pattern_signature`:
   - Extract `module_path` from finding evidence (first file path).
   - Truncate to first 3 path segments: `"/".join(module_path.split("/")[:3])`.
   - Normalize `finding_class`: lowercase, strip punctuation.
   - Compute: `sha256(f"{module_prefix}::{finding_class_norm}::{severity}")[:16]`.
2. Look up `pattern_signature` in existing ERROR_POINTS.json entries (active AND archived).
3. For deterministic matches on active entries: increment `frequency` (capped: max +1 per run), append to `sightings[]` (ring-buffer: keep newest 20), update `last_seen`.
4. For deterministic matches on archived entries: resurrect (`archived: false`, `archived_at: null`, frequency reset to 1, new sighting appended).
5. Findings without deterministic matches → pass to Haiku for LLM matching.

**Haiku subagent prompt augmentation:**
Add to existing prompt:
- Existing error points (for fuzzy matching): `ep_id`, `pattern`, `pattern_signature`, `anchor_module`, `failure_class`, `frequency`.
- Existing invariants (for matching): `id`, `description`, `failure_class`, `sighting_count`, `last_sighting`.
- Findings already deterministically matched are EXCLUDED from the prompt (Haiku only sees unmatched findings).

Haiku returns three output arrays (up from current one):
1. `invariant_matches`: `{finding_ref, invariant_id, match_type: "llm"}` — the orchestrator applies the same increment rules as deterministic.
2. `invariant_candidates`: unchanged from current — new invariant proposals.
3. `error_point_candidates`: `{finding_ref, pattern, failure_class, severity}` — new error point proposals.

**Write processing (orchestrator after Haiku returns):**
1. Apply invariant matches: increment `sighting_count` (max +1 per invariant per run), update `last_sighting`, set `anchor_module` from finding's module_path.
2. For error point candidates:
   - Check `pattern_signature` against existing (non-matched) error points (Haiku may propose a candidate that matches an entry deterministically — deduplicate).
   - Cap new entries at `Z_HARNESS_ERROR_POINT_MAX_NEW` (default 10). Overflow candidates logged to `error-point-overflow.log`.
   - Assign `ep_id` sequentially.
   - Compute `novelty_score = 1 / (1 + frequency)` (= 0.5 for new entries with frequency=1).
3. Validate updated ERROR_POINTS.json with `scripts/validate-error-points.py`.
4. Atomic write both registries.

**Pruning (after all writes):**
1. Scan ERROR_POINTS.json for entries where:
   - `tests_targeting` has ≥ 1 entry
   - `last_seen` is older than `Z_HARNESS_ERROR_POINT_PRUNE_DAYS` (default 90 days)
   - `frequency ≤ Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ` (default 3)
2. For eligible entries: set `archived: true`, `archived_at: <now>`.
3. Log pruned count.

**Hard rule preservation:** Phase 5.5 failure must still NOT halt z-review-all. All error-point operations (match, extract, prune, write) are soft phases — log and continue on error.

**Rate-limiting constants:**
- `Z_HARNESS_ERROR_POINT_MAX_NEW` = 10
- `Z_HARNESS_ERROR_POINT_PRUNE_DAYS` = 90
- `Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ` = 3
- `SIGHTINGS_RING_BUFFER_MAX` = 20
- `INIT_BOOTSTRAP_MAX_ENTRIES` = 20

**Acceptance:**
- [ ] Phase 5.5 gates on INVARIANTS.json OR ERROR_POINTS.json existing.
- [ ] Deterministic pattern_signature matching runs BEFORE Haiku dispatch (zero token cost).
- [ ] Haiku prompt includes existing error points + invariants for fuzzy matching.
- [ ] `sighting_count` increments capped at +1 per invariant per review run.
- [ ] `frequency` increments capped at +1 per error point per review run.
- [ ] New error point entries capped at 10 per review run.
- [ ] Pruning logic checks tests_targeting + last_seen age + frequency cap.
- [ ] Archived error points with matching pattern_signature resurrect.
- [ ] All error-point operations are soft phases (failure doesn't block review pipeline).
- [ ] Updated ERROR_POINTS.json validated after write.
- [ ] Phase 5.5 section in SKILL.md is readable and follows existing style conventions.

**Invariants:**  
- inv_003: INVARIANTS.json write must be atomic (ERROR_POINTS.json follows same discipline).
- inv_004: Phase 5.5 must NOT halt z-review-all pipeline.
- inv_007: All plan artifacts must follow atomic write discipline.
**Tests:** TEST-007 (inv_004 — pipeline resilience), TEST-008 (inv_005 — consultant dispatch)

---

## T005 — Rewrite z-test SKILL.md for dual-source pipeline

**Files:**
- `skills/z-test/SKILL.md` (REWRITE)

**Description:**
Full rewrite of the z-test skill to support dual-source test generation with three modes (`--mode dual` default, `--mode error-points`, `--mode invariant`). The rewrite preserves the existing Phase 0-8 pipeline shape but generalizes each phase to handle one or both data sources.

**Changes by phase:**

**Pre-Setup: Mode flag parsing**
- Parse `--mode` flag: `dual` (default), `error-points`, `invariant`.
- Parse `--ratio N:M` (only meaningful in dual mode; default 70:30).
- Validate: ratio components must be integers > 0, sum must be > 0. For `--mode error-points`, ratio is forced to 100:0. For `--mode invariant`, ratio is forced to 0:100.

**Phase 0 — Discovery (dual-source)**
- Load `docs/ERROR_POINTS.json` if `--mode error-points` or `dual`. Graceful degradation if absent: warning + fallback to invariant-only.
- Load `docs/INVARIANTS.json` if `--mode invariant` or `dual`. Graceful degradation if absent: warning + fallback to error-points-only (or abort if both absent).
- Staleness check on both files.
- Discover plan slug (unchanged).

**Phase 1 — Dual-source load + risk-rank**
- **1a.** Load error points: filter out archived. Compute `staleness_score = days_since_last_seen × code_churn_in_anchor_module`. Rank by `(severity_weight × novelty_score) - (staleness_factor × staleness_score)`. severity_weight: blocker=3, major=2, minor=1. staleness_factor defaults to 0.1.
- **1b.** Load invariants: rank by `severity_weight × log(1 + sighting_count)`. Unchanged from current but with new weight formula.
- **1c.** Interleave: take top N from error-point ranking and top M from invariant ranking where N:M matches ratio. Interleave round-robin (ep, ep, inv for 2:1; ep, ep, inv, ep, ep, inv, ep for 7:3, etc.).
- **1d.** Match to tasks by `anchor_module` overlap (error points) and tag+description overlap (invariants).
- **1e.** User concerns (unchanged).

**Phase 2 — Draft behavioral test cases (dual-source)**
- For each entry in the merged priority list, draft either an error-point-driven or invariant-driven test entry.
- v2 format extended with `error_point_id`, `error_point_pattern` fields (optional; present only for error-point entries).
- Fixture derivation: for error-point entries, if the error point has fixture constraints from sightings, derive fixture data from the finding's evidence.
- Draft cap: ~25 entries. Within mandatory, prefer error-point entries with high novelty_score + low staleness_score, then uncovered blocker invariants, then user concerns.

**Phase 2.5 — Adversarial counterexamples**
- Now covers both error-point and invariant entries.
- Gate unchanged (INVARIANTS.json with fixture_schema + catch_rate < 80%).
- For error-point entries without fixture_schema, adversary uses the error point's `failure_class` and `pattern` to generate adversarial scenarios.

**Phase 3 — Bundled cross-LLM consult**
- Consultants receive BOTH ERROR_POINTS.json AND INVARIANTS.json verbatim (if available for the mode).
- Prompt asks for per-draft critique, uncovered error points, uncovered invariants, and coverage gaps.
- If one source is absent (due to mode flag), consultants work with what's available.

**Phase 4 — Synthesize**
- Merge + dedupe + verdict application (unchanged).
- Cross-source dedupe: if an error-point entry and an invariant entry share the same `failure_class` and `target_file`, merge into one entry with BOTH `error_point_id` AND `invariant_id`.

**Phase 5 — Present + approve**
- Dual-source counts: "E error-point-driven + I invariant-driven tests drafted."
- Invariant-uncovered-blocker presentation unchanged.

**Phase 6 — Write TESTS.md (v2+dual format)**
- Version: 2.
- New header fields: `**Error points file:**`, `**Invariants file:**`, `**Interleave ratio:**`.
- New per-entry fields: `**Error point ID:**`, `**Error point pattern:**` (optional; present only for error-point entries).
- Fixture format unchanged (YAML-friendly key-value pairs).
- After writing TESTS.md, update ERROR_POINTS.json: for each error-point-driven TEST-NNN entry, append the TEST-NNN ID to the corresponding error point's `tests_targeting` array. Validate ERROR_POINTS.json after write.

**Phase 7 — Cross-link into TASKS.md**
- Unchanged from current (append `**Tests:** TEST-NNN, ...` to task blocks).
- Cross-task and full-chain tests handled same as current.

**Phase 8 — Finalize**
- Unchanged but includes dual-source counts in the push-notify.

**Graceful degradation rules:**
| Condition | Mode | Behavior |
|-----------|------|----------|
| ERROR_POINTS.json absent | dual | Warning. Fall back to invariant-only for this run. |
| INVARIANTS.json absent | dual | Warning. Fall back to error-points-only. SPEC.md invariants used as fallback seed (legacy mode). |
| Both registries absent | any | Abort with guidance message. |
| ERROR_POINTS.json absent | error-points | Abort with "no error point registry — run /z-review-all to seed." |
| INVARIANTS.json absent | invariant | Fall back to legacy mode (SPEC.md invariants only). |
| All error points archived | dual | Warning. Fall back to invariant-only. |

**Acceptance:**
- [ ] `--mode dual` loads both registries, interleaves at configured ratio.
- [ ] `--mode error-points` loads only ERROR_POINTS.json, produces error-point-only TESTS.md.
- [ ] `--mode invariant` loads only INVARIANTS.json, produces invariant-only TESTS.md (legacy behavior preserved).
- [ ] `--ratio N:M` controls interleave proportion in dual mode.
- [ ] Graceful degradation for absent registries works for all mode combinations.
- [ ] Cross-source deduplication merges overlapping error-point and invariant entries.
- [ ] TESTS.md includes dual-source header fields when both sources are present.
- [ ] ERROR_POINTS.json `tests_targeting` is updated after TESTS.md write.
- [ ] Phase 3 consultants receive both sources (when available).
- [ ] Phase 2.5 adversarial generation covers both entry types.
- [ ] All existing behavioral rules and hard rules preserved (non-trivial tests, invariant coverage, cross-LLM consult, no emojis, fixture validation, etc.).
- [ ] All existing Phase 0-8 pipeline phases present and functional.
- [ ] CI mode (`--ci`) updated to check both registries.

**Invariants:**  
- inv_001: Every test must exercise a behavioral invariant, not just function-call correctness.
- inv_002: Adversarial fixtures must be structurally valid against fixture_schema.
- inv_005: Cross-LLM consultant subagents must be dispatched in bundled mode.
- inv_007: TESTS.md must follow atomic write discipline.
**Tests:** TEST-004 (inv_001 — behavioral invariant check), TEST-005 (inv_002 — fixture validation), TEST-008 (inv_005 — consultant dispatch)

---

## T006 — Archive z-test → z-test-invariant + update AGENTS.md

**Files:**
- `skills/z-test-invariant/SKILL.md` (NEW — copy of current z-test SKILL.md with updated frontmatter)
- `skills/z-test/SKILL.md` (NO CHANGE — already rewritten by T005)
- `AGENTS.md` (EDIT)

**Description:**
Create the z-test-invariant skill archive and update the AGENTS.md routing table entry.

**z-test-invariant creation:**
1. Copy the current `skills/z-test/SKILL.md` (the invariant-only version, NOT the T005 rewrite) to `skills/z-test-invariant/SKILL.md`.
2. Update the frontmatter:
   ```yaml
   ---
   name: z-test-invariant
   description: Archived invariant-only z-test. Invoke via /z-test --mode invariant.
   argument-hint: "[--slug <slug>] (legacy)"
   origin: z-harness-core (archived)
   tags: [testing, invariants, archived]
   ---
   ```
3. Add a note at the top of the SKILL.md body: "This is the archived invariant-only z-test skill. It is invoked via `/z-test --mode invariant`. The canonical z-test skill is at `skills/z-test/SKILL.md` (dual-source). This file is preserved for reference and for the invariant-only mode implementation."
4. Keep the rest of the file unchanged — it's the historical reference.

**AGENTS.md update:**
- Find the z-test entry in the routing table (~line 179).
- Replace current description with:
  ```
  - **`/z-test`** — Dual-source semantic test-case planner. ERROR_POINTS.json
    (empirical regression hardening from review findings) + INVARIANTS.json
    (preventive coverage from declared design truths). Reads SPEC/PLAN/TASKS,
    drafts non-trivial test cases, cross-LLM consult, writes TESTS.md.
    Modes: --mode dual (default), invariant, error-points.
  ```

**Acceptance:**
- [ ] `skills/z-test-invariant/SKILL.md` exists with updated frontmatter and archival note.
- [ ] File content matches the pre-T005 z-test SKILL.md (the invariant-only version).
- [ ] AGENTS.md routing table z-test entry updated with dual-source description.
- [ ] No other AGENTS.md entries accidentally modified.

**Invariants:**  
None (documentation-only task).
