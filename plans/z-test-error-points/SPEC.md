# SPEC: z-test dual-source redesign

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | plans/z-test-error-points/BRAINSTORM.md | 2026-06-10T21:54:14Z |
| TASK.md | plans/z-test-error-points/TASK.md | 2026-06-10 |

---

## Overview

Replace z-test's current invariant-only approach with a **dual-source** architecture: ERROR_POINTS.json (empirical regression hardening from review findings) + INVARIANTS.json (preventive coverage from declared design truths), with a configurable interleave ratio. The default interleave is 70% error-points-driven / 30% invariant-driven, tunable via `--mode`.

### Architecture

Two data sources feed z-test:

1. **ERROR_POINTS.json** — empirical failure registry. Accumulates from every `/z-review-all` run. Entries carry frequency counters, last-sighting timestamps, AND pattern signatures (AST hashes / module-path similarity). Drives regression-hardening tests.

2. **INVARIANTS.json** — declared design truths. Augmented with `sighting_count`, `last_sighting`, `anchor_module`. Existing Phase 5.5 Haiku subagent both extracts NEW invariant candidates AND matches findings against EXISTING invariants to increment counters. Drives preventive-coverage tests.

Neither source is "fallback." They serve different testing goals and interleave at a configurable ratio.

---

## 1. ERROR_POINTS.json — new artifact

### Path

`docs/ERROR_POINTS.json`

### Schema

```json
{
  "version": 1,
  "generated_at": "<ISO-8601>",
  "error_points": [ ... ]
}
```

Each entry:

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `ep_id` | yes | string `ep_NNN` | Stable zero-padded 3-digit sequential ID. Never reused. |
| `pattern` | yes | string (1-500) | One-line description of the failure pattern. Domain terms, not code terms. |
| `pattern_signature` | yes | string | Deterministic hash of abstracted failure shape. Computed from: module-path prefix + error-type tag + finding-class name (lowercased, punctuation-stripped). Used for deterministic pre-LLM matching. |
| `anchor_module` | yes | string | Repo-relative path to primary module implicated (from finding evidence). May span modules later; this is the first-sighting module. |
| `failure_class` | yes | string (1-300) | Domain-term bug description (mirrors INVARIANTS.json convention). |
| `severity` | yes | `blocker` \| `major` \| `minor` | From the finding's severity. |
| `frequency` | yes | integer ≥ 1 | How many review runs have sighted this pattern. Capped at 1 increment per review run (rate-limiting). |
| `first_seen` | yes | ISO-8601 | Generation timestamp of the review run that first sighted this pattern. |
| `last_seen` | yes | ISO-8601 | Generation timestamp of the most recent sighting. |
| `sightings` | yes | array of `{run_id, finding_id, module_path}` | Ordered list of sightings, newest first. Max 20 entries (ring-buffer). |
| `novelty_score` | yes | float 0.0–1.0 | `1 / (1 + frequency)`. High-frequency patterns have low novelty; rare patterns get boosted in ranking. |
| `staleness_score` | auto | float ≥ 0 | Computed at z-test load time: `days_since_last_seen × code_churn_in_anchor_module`. Not persisted — computed fresh each run. |
| `last_test_pass` | no | ISO-8601 or null | Timestamp of most recent test pass targeting this error point. null if never tested. |
| `last_test_fail` | no | ISO-8601 or null | Timestamp of most recent test failure. null if never failed. |
| `tests_targeting` | yes | array of string | List of TEST-NNN IDs from TESTS.md that target this error point. Populated by z-test Phase 6 cross-linking. |
| `archived` | yes | boolean | Default false. True when pruned (tests_targeting > 0 AND no sightings in N review runs). Archived entries resurrect if pattern reappears. |
| `archived_at` | no | ISO-8601 or null | When archived. |

### Pattern signature computation (deterministic)

The `pattern_signature` is a stable hash computed BEFORE any LLM classification:

1. Extract from the finding: `module_path` (first file in evidence), `finding_class` (the review finding's class label), `finding_severity`.
2. Normalize: lowercase all fields. Strip punctuation from `finding_class`. Truncate `module_path` to first 3 path segments (e.g., `skills/z-test/SKILL.md` → `skills/z-test`).
3. Compute: `sha256(f"{module_prefix}::{finding_class_norm}::{severity}")[:16]` — 16-char hex digest.

This is deterministic and cheap — no LLM call needed. Used as the primary matching key: if a new finding's signature matches an existing error point's signature → same error point (increment frequency). Non-matching signatures fall through to LLM classification for fuzzy matching.

### Write rate-limiting

- An error point's `frequency` increments at most **once per review run**, even if multiple findings share its pattern signature. The `sightings[]` array captures individual sightings; `frequency` is the run-level aggregation.
- Cap new error points per review run at `Z_HARNESS_ERROR_POINT_MAX_NEW` (default 10). Overflow findings (those that would create entries beyond the cap) are logged to `error-point-overflow.log` and dropped for that run. They may match on future runs.

### Pruning → Archive

An error point is pruned (archived) when ALL of:
1. `tests_targeting` has ≥ 1 entry (at least one test was written)
2. `last_seen` is older than `Z_HARNESS_ERROR_POINT_PRUNE_DAYS` (default 90 days)
3. `frequency ≤ Z_HARNESS_ERROR_POINT_PRUNE_MAX_FREQ` (default 3 — don't prune hot patterns)

Archived error points set `archived: true` and `archived_at: <now>`. They are excluded from z-test test generation BUT their pattern_signature remains in the matching index. If a new finding matches an archived pattern signature → `archived: false`, `archived_at: null`, frequency reset to 1, sightings reset to the new finding only. The archived error point **resurrects**.

### Init bootstrap (first-run scan)

On first creation of ERROR_POINTS.json (file absent), run a codebase scan for bug patterns:

1. Scan source files for: `TODO`, `FIXME`, `HACK`, `XXX`, `BUG` comments.
2. Scan for common error-handler patterns: `.unwrap()`, `panic!`, `except pass`, `catch (e) {}` (empty catch blocks).
3. Extract 3-word context around each hit.
4. Group hits by (normalized module prefix, comment/fixme type).
5. For groups with ≥ 2 hits in same module prefix, create a low-confidence (`severity: minor`) error point entry with `pattern` derived from the comment text and `source: init_scan`.

This seeding prevents a complete cold start. As real review runs accumulate, init-scan entries are naturally displaced by higher-severity, higher-frequency entries.

---

## 2. INVARIANTS.json augmentation

### Schema changes

Add three new fields to each invariant entry:

| Field | Required | Type | Default | Description |
|-------|----------|------|---------|-------------|
| `sighting_count` | no (default 0) | integer ≥ 0 | 0 | How many review runs have produced findings matching this invariant's `failure_class`. |
| `last_sighting` | no | ISO-8601 or null | null | Timestamp of most recent sighting. |
| `anchor_module` | no | string or null | null | Repo-relative path to primary module where this invariant was violated. null if invariant was declared (not observed). |

These are optional fields with defaults — backward-compatible with existing INVARIANTS.json entries.

### Schema file

Update `docs/schemas/invariant.schema.json`:
- Add `sighting_count` property: `{"type": "integer", "minimum": 0, "default": 0}`
- Add `last_sighting` property: `{"type": ["string", "null"], "format": "date-time", "default": null}`
- Add `anchor_module` property: `{"type": ["string", "null"], "default": null}`
- Update `additionalProperties: false` → `additionalProperties: false` (keep it; these are whitelisted)
- Do NOT add to `required` array — backward-compatible

### Validation update

`scripts/validate-invariants.py` must:
1. Accept the new fields as valid (they're in schema, not required)
2. Validate that `sighting_count` is ≥ 0 if present
3. Validate that `last_sighting` is valid ISO-8601 if present and non-null
4. No changes needed for fixture validation logic

### z-review-all Phase 5.5 extension

Current Phase 5.5: Haiku subagent extracts NEW invariant candidates from findings.

Extended Phase 5.5: Same single Haiku dispatch does TWO things:

**Step A — Match findings against existing invariants** (deterministic, then LLM fallback):
1. For each finding with severity ≥ major, compute a `match_key` from `finding_class` (lowercased, punctuation-stripped).
2. For each existing invariant, compute the same from `failure_class`.
3. If `match_key` exact-match → deterministic match. Increment `sighting_count` and update `last_sighting` + `anchor_module`.
4. If no exact match, run substring overlap: if finding_class substrings overlap ≥ 50% with invariant failure_class → candidate match. Present to Haiku for confirmation/rejection.
5. If no match at all → finding is new; falls through to existing Step B (candidate extraction).

**Step B — Extract NEW invariant candidates** (unchanged from current):
1. For findings WITHOUT a covering invariant, draft candidate entries.
2. User approval gate unchanged.

**Matching increment rule:** `sighting_count` increments at most once per invariant per review run (rate-limiting). If 3 findings match the same invariant in one run, `sighting_count` increments by 1, not 3.

---

## 3. z-test SKILL.md — full rewrite

### Mode flags

```
/z-test [--slug <slug>] [--mode error-points|invariant|dual] [--ratio <N:M>]
```

- `--mode error-points` — only ERROR_POINTS.json. No invariants. Tests are pure regression hardening.
- `--mode invariant` — only INVARIANTS.json. This is the legacy behavior. Equivalent to current z-test.
- `--mode dual` (default) — both sources, interleaved at configured ratio.
- `--ratio <N:M>` — interleave ratio for dual mode. Default `70:30` (error-points:invariant). Means every 10 test slots, 7 come from error points, 3 from invariants.

### Rewritten pipeline (dual mode)

#### Phase 0 — Discovery

Load BOTH `docs/ERROR_POINTS.json` AND `docs/INVARIANTS.json`. If ERROR_POINTS.json is absent, emit a non-blocking warning: "No ERROR_POINTS.json — error-point-driven tests will be empty. Consider running /z-review-all to seed the registry." Fall back to invariant-only behavior for this run (graceful degradation).

Staleness check on both files (compare mtime to generated_at).

Discover plan slug same as current. Require SPEC.md + PLAN.md + TASKS.md.

#### Phase 1 — Dual-source load + risk-rank

**1a. Load error points.** From ERROR_POINTS.json:
- Filter out archived entries (`archived: true`).
- Compute `staleness_score` for each: `days_since_last_seen × code_churn_in_anchor_module`.
- Rank by: `(severity_weight × novelty_score) - (staleness_factor × staleness_score)`.
- severity_weight: blocker=3, major=2, minor=1.
- novelty_score: `1 / (1 + frequency)`.
- staleness_factor: `Z_HARNESS_ERROR_POINT_STALENESS_FACTOR` (default 0.1).
- Output: ranked list of hot error points.

**1b. Load invariants.** From INVARIANTS.json:
- Rank by `severity × log(1 + sighting_count)` (log-dampening from Claude).
- severity_weight: blocker=3, major=2, minor=1.
- sighting_count=0 invariants still get tested at baseline priority.
- Output: ranked list of uncovered invariants.

**1c. Merge into interleaved priority list.** For dual mode:
1. Take top N from error-point ranking and top M from invariant ranking where `N:M` matches the configured ratio.
2. Interleave: pick from each source in round-robin fashion, respecting ratio. E.g., at 70:30 with 10 slots: [ep1, ep2, inv1, ep3, ep4, inv2, ep5, ep6, inv3, ep7].
3. This merged list is the test-generation priority.

**1d. Match to tasks.** Same logic as current Phase 1b but for both sources: error points match tasks by `anchor_module` overlap with task `Files:`; invariants match by tag + description.

**1e. User concerns.** Unchanged.

#### Phase 2 — Draft behavioral test cases (dual-source)

For each entry in the merged priority list:

**Error-point-driven test entries** (v2 format with error-point fields):
```
- id: TEST-NNN
  task: Txxx
  error_point_id: ep_NNN
  error_point_pattern: "Time-window off-by-one in fill module"
  failure_class: "..."
  layer: per-task
  target_file: tests/test_xxx.py
  fixture: {...}
  assertion: "..."
  seed: error-point
  mandatory: yes
```

**Invariant-driven test entries** (v2 format, unchanged from current):
```
- id: TEST-NNN
  task: Txxx
  invariant_id: inv_NNN
  invariant_description: "..."
  failure_class: "..."
  layer: per-task
  target_file: tests/test_xxx.py
  fixture: {...}
  assertion: "..."
  seed: spec | plan | task-risk | user-concern
  mandatory: yes
```

**Draft cap:** ~25 entries total. Within mandatory: prefer error-point entries with high `novelty_score` + low `staleness_score`, then uncovered blocker invariants, then user concerns.

#### Phase 2.5 — Adversarial counterexamples

Unchanged from current, but now also covers error-point-driven entries. For error-point entries, the adversary gets the error_point's `pattern`, `failure_class`, and any `fixture_schema` or `fixture_defaults` present.

#### Phase 3 — Bundled cross-LLM consult

Consultants receive BOTH ERROR_POINTS.json AND INVARIANTS.json verbatim. Their prompt asks:
1. Per-draft critique (keep/strengthen/drop) — for both error-point and invariant entries.
2. Which error points (by `ep_id`) do not yet have a test entry? Propose drafts.
3. Which INVARIANTS.json invariants (by `id`) are uncovered? Propose drafts.
4. What dangerous bug classes are not covered?
5. Flag trivial drafts.
6. Identify target file placement issues.

If ERROR_POINTS.json is absent, consultants work in invariant-only mode (graceful degradation).

#### Phase 4 — Synthesize

Same merge + dedupe + verdict application as current. Additionally:
- Cross-source dedupe: if an error-point-driven test and an invariant-driven test test the same `failure_class` and `target_file`, dedupe into a single entry with BOTH `error_point_id` AND `invariant_id` linked.

#### Phase 5 — Present + approve

Unchanged presentation but includes dual-source counts:
- "E error-point-driven + I invariant-driven tests drafted."
- Error-point entries shown with their ep_id and pattern.
- Invariant entries shown with their inv_id and description.

#### Phase 6 — Write TESTS.md (v2+dual format)

New fields in TESTS.md header:
```
**Error points file:** docs/ERROR_POINTS.json
**Invariants file:** docs/INVARIANTS.json
**Interleave ratio:** 70:30
```

New test entry format adds optional `**Error point ID:**` and `**Error point pattern:**` fields:

```markdown
## TEST-001  (covers T007)
**Error point ID:** ep_003
**Error point pattern:** Time-window off-by-one in fill module
**Failure class:** Bar boundary inclusivity — rolling window includes look-ahead bar
**Layer:** per-task
**Target file:** tests/test_fill.py
**Fixture:**
  bars: [{time: "09:30", price: 100}, {time: "09:31", price: 101}]
  window_start: "09:30"
**Assertion:** window_end < last_bar.time (no look-ahead)
**Seed:** error-point
**Mandatory:** yes
```

#### Phase 7 — Cross-link into TASKS.md

Unchanged from current — appends `**Tests:** TEST-001, TEST-004` to task blocks.

**Additionally:** For error-point-driven test entries, after writing TESTS.md, update the corresponding error point's `tests_targeting` array in ERROR_POINTS.json to include the new TEST-NNN IDs.

#### Phase 8 — Finalize

Unchanged but includes dual-source counts.

### Mode-specific behavior

| Mode | Phase 0 loads | Phase 1 ranks | Phase 2 drafts | Phase 3 consult prompt |
|------|-------------|-------------|--------------|----------------------|
| `error-points` | ERROR_POINTS.json only | Error points only | Error-point entries only | Error-point context only |
| `invariant` | INVARIANTS.json only | Invariants only (legacy) | Invariant entries only | Invariant context only (legacy behavior) |
| `dual` | BOTH | Merged interleaved | Both interleaved | Both sources |

---

## 4. z-review-all SKILL.md — Phase 5.5 extension

### Current state

Phase 5.5 dispatches a Haiku subagent to extract NEW invariant candidates from findings. No matching against existing invariants. No error point extraction.

### Required changes

**Phase 5.5 extended** — same single Haiku dispatch, augmented prompt. The subagent now receives:

1. **Existing invariants** (for matching) — `id`, `description`, `failure_class`, `sighting_count`, `last_sighting`.
2. **Existing error points** (for matching) — `ep_id`, `pattern`, `pattern_signature`, `anchor_module`, `failure_class`, `frequency`.
3. **Review findings** (severity ≥ major).

The subagent returns TWO output arrays:
1. `invariant_matches` — findings that match existing invariants. Each: `{finding_ref, invariant_id, match_type: "deterministic" | "llm"}`.
2. `invariant_candidates` — new invariant candidates (unchanged from current).
3. `error_point_matches` — findings that match existing error points by pattern_signature (deterministic) or by LLM classification.
4. `error_point_candidates` — new error point candidates from unmatched findings.

**Processing order:**
1. Deterministic pattern_signature matching (no LLM — orchestrator computes signature for each finding, looks up in existing ERROR_POINTS.json).
2. LLM-based invariant matching (Haiku checks finding_class similarity to existing invariant failure_class).
3. New error point extraction (Haiku creates candidates for findings that matched neither).
4. New invariant extraction (unchanged from current, for findings without covering invariants).

**Rate-limiting enforcement at write time:**
- `sighting_count` on invariants: max +1 per invariant per run.
- `frequency` on error points: max +1 per error point per run.
- New error points per run: capped at `Z_HARNESS_ERROR_POINT_MAX_NEW` (default 10).

**Archived resurrection:** Before creating a new error point candidate, check if its `pattern_signature` matches an archived error point. If yes, resurrect it instead.

**Error point pruning:** After all writes, scan ERROR_POINTS.json for entries eligible for pruning (see pruning rules above). Archive eligible entries. Log pruned count.

**Renamed Phase 5.5 → Phase 5.5+5.6 or keep as single Phase 5.5:**
Keep as single Phase 5.5 — the Haiku subagent already handles invariant extraction; extending its prompt to also handle error points is a single dispatch, not two. The orchestrator pre-computes deterministic matches before the Haiku call to reduce LLM work.

---

## 5. Validation scripts

### scripts/validate-error-points.py (NEW)

```bash
python3 scripts/validate-error-points.py --file docs/ERROR_POINTS.json
```

Validates ERROR_POINTS.json against `docs/schemas/error_points.schema.json`.

Exit codes:
- 0: valid
- 1: schema error
- 2: constraint violation (id uniqueness, frequency ≥ 1, sightings array non-empty for active entries, etc.)
- 3: I/O error

Constraint rules:
- ep_id uniqueness across all entries
- pattern_signature is a 16-char hex string
- frequency ≥ 1 for non-archived entries
- sightings array is non-empty for non-archived entries
- last_seen ≥ first_seen
- severity in {blocker, major, minor}
- archived entries must have archived_at
- active entries must NOT have archived_at

### scripts/validate-invariants.py (UPDATED)

Update to accept new fields (sighting_count, last_sighting, anchor_module) in schema. See INVARIANTS.json augmentation section above.

### docs/schemas/error_points.schema.json (NEW)

JSON Schema draft-2020-12 for ERROR_POINTS.json top-level structure and per-entry validation.

---

## 6. Archive: z-test → z-test-invariant

### What gets archived

The current `skills/z-test/SKILL.md` is renamed to `skills/z-test-invariant/SKILL.md`. The z-test-invariant skill is a mode, not a separate command.

### How it's invoked

No separate `/z-test-invariant` command. The `--mode invariant` flag on `/z-test` invokes the invariant-only path, which is the legacy behavior.

The archive preserves the original SKILL.md for reference and for the invariant-only mode's implementation. The new dual-source z-test SKILL.md shares ~60% of its Phase 0/1/2/3/4/5/6/7/8 structure — the mode flag changes which data sources are loaded and how ranking/interleaving works, not the overall pipeline shape.

### Skill description update

In the skill registry (AGENTS.md, skill YAML frontmatter), update z-test's description:

Before:
> Semantic test-case planner. Reads SPEC.md + PLAN.md + TASKS.md for an existing plan, risk-ranks the tasks, drafts non-trivial test cases...

After:
> Semantic test-case planner. Dual-source: ERROR_POINTS.json (empirical regression hardening) + INVARIANTS.json (preventive coverage). Reads SPEC/PLAN/TASKS, risk-ranks tasks, drafts non-trivial test cases, cross-LLM consult, writes TESTS.md. Modes: --mode dual (default), invariant, error-points.

---

## 7. AGENTS.md update

### Routing table description update

Current line (~line 179):
```
- **`/z-test`** — Semantic test-case planner. Reads SPEC/PLAN/TASKS, drafts
  test cases for real semantic bugs, cross-LLM consult, writes TESTS.md.
```

Replace with:
```
- **`/z-test`** — Dual-source semantic test-case planner. ERROR_POINTS.json
  (empirical regression hardening from review findings) + INVARIANTS.json
  (preventive coverage from declared design truths). Reads SPEC/PLAN/TASKS,
  drafts non-trivial test cases, cross-LLM consult, writes TESTS.md.
  Modes: --mode dual (default), invariant, error-points.
```

---

## 8. Key invariants

**INVARIANT: ERROR_POINTS.json is write-rate-limited.** No error point's `frequency` increments more than once per review run. No more than `Z_HARNESS_ERROR_POINT_MAX_NEW` new error points are created per review run.

**INVARIANT: Pattern signatures are deterministic.** The `pattern_signature` field is computed BEFORE any LLM call — it is a pure function of `module_prefix`, `finding_class`, and `severity`. It does not depend on LLM output.

**INVARIANT: Phase 5.5 failure must not block z-review-all.** Both invariant extraction and error-point extraction are soft phases. On failure, log and continue. The review pipeline is the priority.

**INVARIANT: Atomic writes for both registries.** ERROR_POINTS.json and INVARIANTS.json both follow: tmpfile → flush → fsync → os.replace(). No partial files on disk.

**INVARIANT: Archived error points can resurrect.** An archived error point whose `pattern_signature` matches a new finding is un-archived, frequency reset to 1, and re-enters active rotation.

**MUST: Both sources are testable independently.** `--mode error-points` and `--mode invariant` each produce valid TESTS.md output with the other source absent. The system degrades gracefully.

**MUST: Cross-source deduplication.** If an error-point-driven test and an invariant-driven test overlap (same failure_class + target_file), they are merged into a single entry with both sources linked.

---

## 9. Edge cases and error handling

| Scenario | Behavior |
|----------|----------|
| ERROR_POINTS.json absent | Warning. Fall back to invariant-only for this run. No error. |
| ERROR_POINTS.json empty | Same as absent — warning, fall back. |
| INVARIANTS.json absent | Warning. Fall back to error-points-only for this run. SPEC.md invariants used as fallback seed (legacy mode). |
| Both registries absent | Abort with "no test sources available — run /z-review-all to seed ERROR_POINTS.json, or /z-init-docs --invariants to bootstrap INVARIANTS.json." |
| ERROR_POINTS.json malformed | Validate-and-abort. Show path + error. |
| Pattern signature collision | Two different error points with same signature → constraint violation. Validate catches this. |
| Archived error point resurrection loop | Max 3 resurrections per error point. On 4th resurrection, set severity to minor (treat as low-signal). |
| All error points archived | Warning. Fall back to invariant-only. |
| Ratio 0:100 (pure invariant) | Same as --mode invariant. |
| Ratio 100:0 (pure error-points) | Same as --mode error-points. |
| Init bootstrap on large codebase | Timeout at 30s. Log partial results. No blocking. |
