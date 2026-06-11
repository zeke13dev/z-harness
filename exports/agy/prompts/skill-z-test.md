---
description: "Dual-source semantic test-case planner. ERROR_POINTS.json (empirical regression hardening from review findings) + INVARIANTS.json (preventive coverage from declared design truths). Reads SPEC.md + PLAN.md + TASKS.md for an existing plan, risk-rank..."
role: skill
---

<!-- NO_SESSION_GUARD -->
**Session persistence required.** This pipeline spans multiple phases, dispatches subagents, and may need to resume after a pause. If you are running in `--no-session` mode (session is not persisted to disk), stop immediately and tell the user: "`/z-test` requires a persistent session. Please restart pi without `--no-session`." Then halt. Do not proceed.

## Invariant schema reference

`/z-test` consumes invariants from `docs/INVARIANTS.json` (the canonical per-repo invariant store). Each invariant entry is validated against `docs/schemas/invariant.schema.json` (JSON Schema draft-2020-12).

### INVARIANTS.json top-level structure

```json
{
  "version": 1,
  "generated_at": "<ISO-8601>",
  "invariants": [ ... ]
}
```

- `version`: integer, always `1` for v1 format.
- `generated_at`: ISO-8601 timestamp of last generation.
- `invariants`: array of invariant entry objects.

### Invariant entry fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `id` | yes | string `inv_NNN` | Stable kebab-case ID, zero-padded 3-digit sequential. Never reused. |
| `description` | yes | string (1-500) | One-sentence system-level behavioral truth. |
| `tags` | yes | string[] (≥1) | Controlled tags from `docs/llm/TAGS.txt`. See tags table. |
| `failure_class` | yes | string (1-300) | Domain-term description of the bug this invariant prevents. |
| `fixture_schema` | no | object (≥1 property) | Optional JSON Schema shape for test fixture data. |
| `fixture_defaults` | no | object | Optional default fixture values. Only valid when `fixture_schema` is present. |
| `severity` | yes | `blocker` \| `major` \| `minor` | `blocker` = PR gate fail, `major` = PR gate warn, `minor` = informational. |
| `source_files` | yes | string[] (1-50) | Source paths this invariant derives from, relative to repo root. |
| `last_updated` | yes | ISO-8601 string | Timestamp of last modification. |
| `source` | yes | `spec` \| `plan` \| `user-concern` \| `code-review` \| `axiom-derived` | Provenance. |
| `sighting_count` | no (default 0) | integer ≥ 0 | How many review runs have matched this invariant's failure_class. |
| `last_sighting` | no | ISO-8601 or null | Timestamp of most recent sighting. null if never sighted. |
| `anchor_module` | no | string or null | Repo-relative path to primary violation module. null if never sighted. |

### Controlled tags (from docs/llm/TAGS.txt)

`correctness`, `perf`, `data-quality`, `schema`, `time-window`, `units`, `api-boundary`, `retry-loop`, `race-condition`, `dependency`, `deprecation`, `lossy-default`, `ux`, `observability`, `compliance`

---

## Error points schema reference

`/z-test` also consumes error points from `docs/ERROR_POINTS.json` (empirical failure registry). Each entry is validated against `docs/schemas/error_points.schema.json`.

### ERROR_POINTS.json top-level structure

```json
{
  "version": 1,
  "generated_at": "<ISO-8601>",
  "error_points": [ ... ]
}
```

### Error point entry fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `ep_id` | yes | string `ep_NNN` | Stable zero-padded 3-digit sequential ID. Never reused. |
| `pattern` | yes | string (1-500) | One-line description of the failure pattern. |
| `pattern_signature` | yes | string (16 hex) | Deterministic hash for matching (sha256 of module_prefix::norm_class::severity). |
| `anchor_module` | yes | string | Repo-relative path to primary module implicated. |
| `failure_class` | yes | string (1-300) | Domain-term bug description. |
| `severity` | yes | `blocker` \| `major` \| `minor` | From finding's severity. |
| `frequency` | yes | integer ≥ 1 | How many review runs have sighted this pattern. Capped at +1 per run. |
| `first_seen` | yes | ISO-8601 | When first sighted. |
| `last_seen` | yes | ISO-8601 | Most recent sighting. |
| `sightings` | yes | array (1-20) | Ordered list of sightings, newest first. Ring-buffer. |
| `novelty_score` | yes | float 0.0–1.0 | `1 / (1 + frequency)`. High-freq = low novelty. |
| `staleness_score` | auto | float ≥ 0 | Computed at load time: days_since_last_seen × code_churn. Not persisted. |
| `last_test_pass` | no | ISO-8601 or null | Most recent test pass timestamp. |
| `last_test_fail` | no | ISO-8601 or null | Most recent test failure timestamp. |
| `tests_targeting` | yes | array of string | TEST-NNN IDs targeting this error point. |
| `archived` | yes | boolean | True when pruned. |
| `archived_at` | no | ISO-8601 or null | When archived. null for active entries. |

---

You are running **z-harness `/z-test`** — the dual-source semantic test-case planner. This is an **optional planning-time step** between `/z-plan` and `/z-implement-all`. It does NOT write or run any test code. It produces a structured `TESTS.md` artifact that the implementer subagent reads alongside TASKS.md.

**Modes:**
- `--mode dual` (default) — loads both ERROR_POINTS.json and INVARIANTS.json. Interleaves test drafts at configured ratio.
- `--mode error-points` — loads only ERROR_POINTS.json. Pure regression-hardening tests.
- `--mode invariant` — loads only INVARIANTS.json. Legacy behavior (preserved for backward compatibility).
- `--ratio N:M` — interleave ratio for dual mode. Default `70:30` (error-points:invariant). Every 10 slots: 7 from error points, 3 from invariants.

## Setup

### Phase 0 — Discovery

**Parse mode flags:**
- `--mode`: `dual` (default), `error-points`, `invariant`.
- `--ratio N:M`: only meaningful in dual mode. Validate: N, M must be integers > 0, sum must be > 0.
- In `--mode error-points`, ratio is forced to 100:0.
- In `--mode invariant`, ratio is forced to 0:100.

**Load registries based on mode:**

| Mode | Load ERROR_POINTS.json? | Load INVARIANTS.json? |
|------|------------------------|----------------------|
| `dual` | yes | yes |
| `error-points` | yes | no |
| `invariant` | no | yes |

**ERROR_POINTS.json loading (if mode requires it):**
- If `docs/ERROR_POINTS.json` exists: load it. Parse `version`, `generated_at`, `error_points[]`. Filter out archived entries (`archived: true`). If ALL entries are archived, emit warning: "All error points archived — no error-point-driven tests will be drafted. Consider waiting for fresh review runs."
- If `docs/ERROR_POINTS.json` is **absent**:
  - `--mode error-points`: abort with "No ERROR_POINTS.json found — run /z-review-all to seed the error point registry."
  - `--mode dual`: emit warning: "No ERROR_POINTS.json found. Falling back to invariant-only for this run." Continue in invariant-only mode.

**INVARIANTS.json loading (if mode requires it):**
- If `docs/INVARIANTS.json` exists: load it. Parse `version`, `generated_at`, `invariants[]`. Each entry has `id`, `description`, `tags`, `failure_class`, optional `fixture_schema`/`fixture_defaults`, `severity`, `source_files`, `last_updated`, `source`, `sighting_count` (0 if absent), `last_sighting` (null if absent), `anchor_module` (null if absent).
- If `docs/INVARIANTS.json` is **absent**:
  - `--mode invariant`: emit warning: "No INVARIANTS.json found — run /z-init-docs --invariants to bootstrap. Continuing with SPEC.md invariants only (legacy mode)."
  - `--mode dual` AND ERROR_POINTS.json exists: emit warning: "No INVARIANTS.json found. Falling back to error-points-only for this run." Continue in error-points-only mode.
  - `--mode dual` AND ERROR_POINTS.json also absent: abort with "No test sources available — run /z-review-all to seed ERROR_POINTS.json, or /z-init-docs --invariants to bootstrap INVARIANTS.json."

**Staleness check.** For each invariant, compare `source_files[]` max mtime to `last_updated`. For ERROR_POINTS.json, compare entries' `last_seen` to current date. Warn user on stale sources.

**Discover plan.** Same slug discovery as `/z-implement-all` Setup:

1. Enumerate `$Z_HARNESS_PLAN_DIR/` subdirs containing a `TASKS.md`; also check legacy flat `z-harness/TASKS.md`.
2. If `--slug <slug>` arg → use it.
3. Single candidate → use it; export `Z_HARNESS_SLUG=<slug>` and `Z_HARNESS_PLAN_DIR=$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/plan-path.sh" resolve_plan_path "$Z_HARNESS_SLUG")`.
4. Multiple → `AskUserQuestion` to pick.
5. Zero → tell user "no plan found — run `/z-plan` first"; abort.

Set `$BASE = $Z_HARNESS_PLAN_DIR` (or `z-harness` for legacy).

**Require SPEC.md + PLAN.md + TASKS.md.** Abort with "incomplete plan; run /z-plan to completion first" if any of the three is missing.

**Implementation-underway warning.** If TASKS.md already has any `[x]` rows, `AskUserQuestion`:
- "Continue — add tests that will retroactively constrain in-flight tasks"
- "Abort — wait until implementation is complete, then run /z-test after /z-review-all"

**`--ci` flag.** If `--ci` is passed, switch to read-only CI validation mode (see CI mode section at end of this skill).

Pick run id `RRUN=$(date -u +%Y%m%dT%H%M%SZ)-test`. `mkdir -p $BASE/archive/$RRUN/transcripts`.

**Version stamp + log run start:**
```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]; v["mode"] = sys.argv[3]
print(json.dumps(v))
' "$VERSION_BLOB" "$Z_HARNESS_SLUG" "<mode>")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_start "$START_PAYLOAD"
```

Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Phase 1 — Load + risk-rank (dual-source)

Read `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`.

### 1a. Load error points (if mode includes error-points)

**Compute staleness for ranking.** For each active error point:
- `days_since_last = (now - last_seen).days`
- `code_churn` = estimate: count git log changes to `anchor_module` since `last_seen` (or default 1.0 if git unavailable).
- `staleness_score = days_since_last × code_churn`

**Compute ranking score:**
```
rank_score = (severity_weight × novelty_score) - (staleness_factor × staleness_score)
```
- `severity_weight`: blocker=3, major=2, minor=1
- `novelty_score`: `1 / (1 + frequency)` (from ERROR_POINTS.json)
- `staleness_factor`: default 0.1 (tunable)

**Output:** ranked list of hot error points (highest rank_score first).

### 1b. Load invariants (if mode includes invariants)

**Primary source: INVARIANTS.json.** If loaded in Phase 0, all invariants are available. Each invariant carries: `id`, `description`, `tags[]`, `failure_class`, `severity`, optional `fixture_schema`, `sighting_count` (0 if absent), `last_sighting`, `anchor_module`.

**Fallback source: SPEC.md invariant lines.** Also extract from SPEC.md every line of these shapes for invariants not yet in INVARIANTS.json:
- `**INVARIANT:**`, `**MUST:**`, `**MUST NOT:**`, `**DANGER:**`
- Numeric/quantitative assertions
- Equality/identity claims about cross-module contracts

**Rank invariants by:** `severity_weight × log(1 + sighting_count)`
- `severity_weight`: blocker=3, major=2, minor=1
- `log(1 + sighting_count)`: log-dampening prevents one hot invariant from monopolizing slots. NB: `log(1 + 0) = 0`, so unsighted invariants rank at 0 — but they still get tested at baseline via interleave (Phase 1c).
- For invariants without `sighting_count` (legacy entries): treat as 0.

**Output:** ranked list of invariants (highest rank_score first).

### 1c. Interleave (dual mode only)

Take the top `N` from error-point ranking and top `M` from invariant ranking, where N:M matches the configured ratio. For default 70:30 with 10 slots:
- `N = floor(10 × 70 / 100) = 7`
- `M = 10 - 7 = 3`

Interleave round-robin: distribute slots proportionally. Example for 7:3 with 10 slots:
```
Slot 1: ep_rank[0] (error-point)
Slot 2: ep_rank[1] (error-point)
Slot 3: invariant_rank[0] (invariant)
Slot 4: ep_rank[2] (error-point)
Slot 5: ep_rank[3] (error-point)
Slot 6: invariant_rank[1] (invariant)
Slot 7: ep_rank[4] (error-point)
Slot 8: ep_rank[5] (error-point)
Slot 9: invariant_rank[2] (invariant)
Slot 10: ep_rank[6] (error-point)
```

This merged list is the test-generation priority for Phase 2.

**In non-dual modes:** use the single source's ranked list directly (no interleaving).

### 1d. Match to tasks

For each entry in the priority list (error point or invariant), match to tasks in TASKS.md:

**Error point → task matching:**
1. **Module overlap (primary).** If the error point's `anchor_module` overlaps with any file in the task's `Files:` block (substring match on path segments) → direct binding.
2. **Failure class similarity (fuzzy).** If no file overlap, compare the error point's `failure_class` to the task's `Description:` text. Substring match → candidate binding (lower confidence).

**Invariant → task matching:**
1. **Explicit annotation match (primary).** If the task block has a `**Invariants:** inv_001, inv_003` line → direct binding.
2. **Fuzzy tag match (discovery hint).** If no explicit `**Invariants:**` line:
   - Scan the task's `Description:` for tag keywords from the invariant's `tags[]`.
   - Check description substring overlap with invariant `description` and `failure_class`.
   - Check `anchor_module` overlap with task `Files:` (same as error-point matching).

### 1e. Risk-rank tasks

For each task in TASKS.md, score risk on three axes:

- **Domain criticality.** Does this task touch critical domain concerns? Factor in matched invariants' `severity` — blocker invariant coverage is mandatory, major is recommended.
- **Surface area.** Count files in the task's `Files:` block; count acceptance criteria; flag presence of `**DANGER:**` / `**INVARIANT:**` / `**MUST:**` tags in SPEC.md for any file the task touches.
- **Test-gap signal.** Acceptance criteria worded as "behavior X" without a numeric / type-shape / observable check are the worst case. Also factor: tasks with 0 matched error points AND 0 matched invariants have a test-gap.

Output a ranked list (high → low):
- **High risk** → mandatory test coverage required.
- **Medium risk** → recommended.
- **Low risk** → optional.

### 1f. User concerns

`AskUserQuestion` (free-text):
- "What specific bug classes worry you most for this plan?"

Each user concern becomes an explicit test target in Phase 2 (`seed: user-concern`).

Save the ranked list + matched sources + user concerns to `$BASE/archive/$RRUN/phase1-risk.md`.

## Phase 2 — Draft behavioral test cases (dual-source)

For each entry in the merged priority list (error points + invariants interleaved), AND for each user concern, AND for each high-risk task, draft a candidate test entry using the **v2+dual format**:

### Error-point-driven test entry format

```
- id: TEST-NNN
  task: Txxx                                    # link to TASKS.md entry
  error_point_id: ep_NNN                        # NEW — stable ID from ERROR_POINTS.json
  error_point_pattern: "Time-window off-by-one in fill module"  # NEW — one-line pattern
  failure_class: "Bar boundary inclusivity — window includes look-ahead bar"
  layer: per-task | full-chain
  target_file: tests/test_fill.py
  fixture:                                      # inline JSON satisfying fixture constraints
    bars: [{"time": "09:30", "price": 100}, {"time": "09:31", "price": 101}]
    window_start: "09:30"
  assertion: "assert window_end < last_bar.time (no look-ahead)"  # concrete observable check
  seed: error-point
  mandatory: yes | no
```

### Invariant-driven test entry format (unchanged v2)

```
- id: TEST-NNN
  task: Txxx
  invariant_id: inv_NNN
  invariant_description: "Feed processing must preserve all fee fields"
  failure_class: "Silent fee drop — feed processes but fee field is zeroed or absent"
  layer: per-task | full-chain
  target_file: tests/test_feed_processor.py
  fixture:
    feed_records: [{"price": 100.0, "fee": 0.5}]
    expected_fees: {"total": 0.5}
  assertion: "assert feed_output.total_fees == 0.5 for input with fee 0.5"
  seed: spec | plan | task-risk | user-concern
  mandatory: yes | no
```

### Field rules

- `error_point_id`, `error_point_pattern`: present ONLY for error-point-driven entries. Omitted for invariant-driven entries.
- `invariant_id`, `invariant_description`: present ONLY for invariant-driven entries. Omitted for error-point-driven entries.
- `fixture`: derived from the error point's sightings evidence (for error-point entries) or from the invariant's `fixture_defaults` + `fixture_schema` (for invariant entries).

**Behavioral assertion discipline:**
- Assert composed behavior: "output.total_fees == input.sum(fee)" not "process_feed() was called"
- Assert invariants hold across module boundaries
- Every assertion must name a specific failure class in domain terms
- Assertions must be observable (numeric, type-shape, or invariant on output)

**Non-trivial failure class checklist:**
- Sign/direction errors, schema/feature mismatches, off-by-one in time/rolling windows
- Stale-data usage, cross-module contract drift, quantity/price unit confusion
- State-machine invariants, bounds (empty/single-element/NaN propagation)

**Fixture derivation.** For entries with `invariant_id` whose invariant has `fixture_schema`: use `fixture_defaults` as starting point. For error-point entries: derive fixture from the error point's `failure_class` and sightings context.

**Anti-rubber-stamp rule.** For each draft, internally note "one reason this test might be useless." If you can't articulate why, sharpen the assertion.

**Draft ordering.** Within mandatory: prefer error-point entries with high `novelty_score` + low `staleness_score`, then uncovered blocker invariants, then user concerns, then high-risk tasks.

**Draft cap:** ~25 entries total.

Save to `$BASE/archive/$RRUN/phase2-drafts.md`.

## Phase 2.5 — Adversarial counterexample generation

**Gate:** Only runs if both conditions are met:
1. `docs/INVARIANTS.json` exists with at least one invariant that has a `fixture_schema`.
2. The falsification test from Phase B found a real gap (`catch_rate < 80%`). If `catch_rate >= 80%` or no falsification test was run, skip this phase.

Covers BOTH error-point-driven and invariant-driven entries. For error-point entries without `fixture_schema`, the adversary uses the error point's `failure_class` and `pattern` to generate adversarial scenarios.

Procedure unchanged from prior version — dispatch `test-adversary` subagent, annotate drafts with `adversarial_scenario`, `adversarial_fixture`, `expected_violation_found`.

**Hard rule:** Phase 2.5 failure MUST NOT block Phase 3.

## Phase 3 — Bundled cross-LLM consult (mode `test-cases`)

Spawn **both** consultants in parallel. The prompt body varies by mode:

**Dual mode prompt:**
```
MODE: test-cases (dual-source)

SPEC.md (verbatim): ...
PLAN.md (verbatim): ...
TASKS.md (verbatim): ...

ERROR_POINTS.json (loaded if present; note if absent):
<verbatim contents or 'ABSENT'>

INVARIANTS.json (loaded if present; note if absent):
<verbatim contents or 'ABSENT'>

My draft test cases (Phase 2, dual-source):
<contents of phase2-drafts.md>

User-stated concerns:
<from Phase 1f>

Source files referenced by the drafts (read these for real types/signatures):
<list of abs paths>

Ask:
1. Per-draft critique (keep | strengthen | drop) — for both error-point and invariant entries.
2. Which error points (by ep_id) do not yet have a test entry? Propose drafts.
3. Which invariants (by id) are uncovered? Propose drafts.
4. What dangerous bug classes specific to this domain are not covered by my drafts?
5. Flag any draft that is mechanically trivial (asserts what the implementation already does).
6. Identify any draft whose target_file is in the wrong place (framework convention mismatch).
7. Identify any invariant-entry mismatch: does any draft claim to cover an invariant but doesn't test the described behavior?

Return structured: per-draft critique, NEW test entries for uncovered error points, NEW test entries for uncovered invariants, fixture suggestions.
```

**Error-points-only mode:** Omit INVARIANTS.json section. Ask for error-point-only coverage.

**Invariant-only mode:** Omit ERROR_POINTS.json section. This is the legacy prompt (unchanged).

Both transcripts archive themselves under `$BASE/archive/$RRUN/transcripts/`.

## Phase 4 — Synthesize

When both consultants return:

1. **Merge** orchestrator drafts + Gemini additions + Codex additions. Dedupe by `test_name` + `target_file`.
2. **Apply per-draft verdicts.** If both LLMs said "drop, trivial" → drop. If both said "strengthen", apply stronger assertion. If exactly one said drop → keep but flag for user.
3. **Cross-source dedupe.** If an error-point-driven entry and an invariant-driven entry test the same `failure_class` AND `target_file`, merge into a single entry with BOTH `error_point_id` AND `invariant_id` linked. Keep the strongest assertion and fixture from both.
4. **Apply additions.** For each NEW entry an LLM proposed, run anti-rubber-stamp check. Drop pure rubber-stamps.
5. **Cross-LLM disagreement.** Surface disagreements to user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.
6. **Fixture validation.** For entries with `invariant_id` and `fixture:`, validate against the invariant's `fixture_schema`:
   ```bash
   python3 scripts/validate-invariants.py --fixture <entry_fixture_json_file> --schema <tmp_schema_file>
   ```
   For error-point entries with fixtures, validate against any applicable schema.
7. **Uncovered invariants.** Check which INVARIANTS.json invariants have zero test entries. For uncovered **blocker** or **major** invariants, propose draft in Phase 5 approval list.
8. **Uncovered error points.** Check which high-severity (blocker/major) error points have zero test entries. Flag for user.

Track counts:
- `n_dropped_by_consult`, `n_added_by_consult`, `n_strengthened`
- `n_fixture_validation_failures`
- `n_uncovered_blockers` (invariants), `n_uncovered_majors` (invariants)
- `n_uncovered_ep_blockers` (error points), `n_uncovered_ep_majors` (error points)
- `n_cross_source_merged` (entries deduped across sources)

Save to `$BASE/archive/$RRUN/phase4-synthesis.md`.

## Phase 5 — Present + approve

Send `PushNotification` (if policy != `off`): "Test plan ready for review."

Present dual-source counts via `AskUserQuestion`:
- "E error-point-driven + I invariant-driven tests drafted (M cross-source merged). Cross-LLM dropped D trivial drafts; added A coverage gaps."
- "U invariants have no test coverage (B blockers, MJ majors)."
- "V error points have no test coverage (EB blockers, EM majors)."

List uncovered blockers explicitly:
- "Uncovered invariant blockers: inv_012 (description), inv_015 (description)"
- "Uncovered error-point blockers: ep_007 (pattern)"

Options:
- **Accept all** — write all entries into TESTS.md.
- **Accept mandatory + recommended only** — drop optional tier.
- **Edit subset** — per-test `AskUserQuestion`: keep / drop / modify (free-text).
- **Abandon** — log `test_plan_end` with `status: abandoned`; exit.

**Fixture-scaffolding gate.** For any accepted test whose `fixture:` field requires non-trivial new test infrastructure, get separate explicit approval.

## Phase 6 — Write TESTS.md (v2+dual format)

Write `$BASE/TESTS.md` in **v2+dual format**:

```markdown
# Tests for <slug>

**Run:** <RRUN>
**Version:** 2
**Status:** drafted (awaiting /z-implement-all)
**Invariants file:** docs/INVARIANTS.json
**Error points file:** docs/ERROR_POINTS.json
**Interleave ratio:** <N:M or "n/a">
**Plugin version:** <z_harness_version>
**Cross-LLM consensus:** <agree | gemini-only-N | codex-only-N | user-overrode-N>
**Counts:** <M> mandatory, <R> recommended, <O> optional
**Cross-LLM delta:** dropped <D> trivial, added <A> gaps, strengthened <S>
**Cross-source merged:** <MERGED> entries merged (error-point + invariant overlap)
**Covered invariants:** inv_001, inv_003, inv_007
**Uncovered invariants (blocker):** inv_012
**Uncovered invariants (major):** inv_005, inv_009
**Covered error points:** ep_001, ep_003
**Uncovered error points (blocker):** ep_007
**Uncovered error points (major):** ep_004

## TEST-001  (covers T007)
**Invariant ID:** inv_001
**Invariant description:** Feed processing must preserve all fee fields
**Failure class:** Silent fee drop — feed processes but fee field is zeroed or absent
**Layer:** per-task
**Target file:** tests/test_feed_processor.py
**Fixture:**
  feed_records: [{"price": 100.0, "fee": 0.5}]
  expected_fees: {"total": 0.5}
**Assertion:** assert feed_output.total_fees == 0.5 for input with fee 0.5
**Seed:** spec
**Mandatory:** yes

## TEST-002  (covers T009)
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

**Header fields (new in v2+dual):**
- `**Error points file:**` — path to ERROR_POINTS.json.
- `**Interleave ratio:**` — the ratio used (or "n/a" for non-dual modes).
- `**Cross-source merged:**` — count of entries merged across sources.
- `**Covered error points:**` — ep_IDs with test entries.
- `**Uncovered error points (blocker/major):**` — error points without coverage.

**Per-entry fields (new):**
- `**Error point ID:**` — ep_NNN (present only for error-point-driven entries).
- `**Error point pattern:**` — one-line pattern (present only for error-point-driven entries).

**After writing TESTS.md, update ERROR_POINTS.json tests_targeting:**
For each TEST-NNN entry that is error-point-driven (has `error_point_id`):
1. Find the corresponding error point in ERROR_POINTS.json.
2. Append the TEST-NNN ID to its `tests_targeting` array (if not already present).
3. Write ERROR_POINTS.json atomically.
4. Validate: `python3 scripts/validate-error-points.py --file docs/ERROR_POINTS.json`.

**In invariant-only mode (legacy):** write TESTS.md without error-point fields and without updating ERROR_POINTS.json. This is backward-compatible.

**In error-points-only mode:** write TESTS.md without invariant fields. Version is still 2.

Each TEST-NNN block must be parseable. Use stable IDs even if gaps from user drops.

## Phase 7 — Cross-link into TASKS.md

For each task `Txxx` referenced by one or more TEST-NNN entries, append under that task's block in TASKS.md:

```
**Tests:** TEST-001, TEST-004  (see TESTS.md)
```

Placement: directly after the task's `Acceptance:` block, before any `**REMOTE_VERIFY:**` or `**DOCS:**` line.

If a task already has a `**Tests:**` line from a prior `/z-test` invocation, **merge IDs** — never overwrite. Sort merged list.

**Cross-task tests** (entries with `task: null`) and **full-chain tests** (entries with `**Layer:** full-chain`) are not linked into TASKS.md. They get implemented separately.

## Phase 8 — Finalize

1. Copy TESTS.md into `$BASE/archive/$RRUN/`.
2. Log dual-source finalize:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_end \
     "$(printf '{"status":"drafted","n_mandatory":%d,"n_recommended":%d,"n_optional":%d,"n_dropped_by_consult":%d,"n_added_by_consult":%d,"n_strengthened":%d,"n_cross_task":%d,"n_full_chain":%d,"uncovered_invariant_count":%d,"uncovered_blocker_count":%d,"uncovered_ep_blocker_count":%d,"n_cross_source_merged":%d,"mode":"%s","ratio":"%s"}' \
        "$M" "$R" "$O" "$D" "$A" "$S" "$X" "$FC" "$UI" "$UB" "$UEB" "$CSM" "<mode>" "<ratio>")"
   ```
3. Push-notify:
   ```
   Test plan complete. <M> mandatory + <R> recommended + <O> optional tests drafted.
   <E> error-point-driven + <I> invariant-driven (<CSM> cross-source merged).
   Cross-LLM dropped <D> trivial drafts; added <A> coverage gaps.
   <UI> invariants and <UE> error points have no test coverage.
   <FC> full-chain tests deferred to post-implementation.

   Recommended next:
     /z-implement-all   — implements tasks AND their linked TESTS.md entries together
   ```
4. Brief user summary: what was drafted, error-point vs invariant split, cross-source merges, uncovered blocker counts, how many full-chain tests deferred.

### Full-chain test code generation

After all per-task implementation is complete (via `/z-implement-all`):

For each `**Layer:** full-chain` entry in TESTS.md, generate the actual test code file at the `**Target file:**` path. This step runs AFTER all tasks are implemented.

Procedure unchanged from prior version — generate test functions, validate syntax, write atomically.

## Behavioral rules (dual-source)

- **Dual-source coverage rule:** Every test function drafted by `/z-test` must verify at least one source — an invariant from `docs/INVARIANTS.json` OR an error point from `docs/ERROR_POINTS.json`. In dual mode, coverage from both sources is the goal. In single-source modes, coverage from the available source suffices.
- **Cross-LLM consult rule:** Before finalizing any test entry, consult at least one other LLM via Phase 3 bundled cross-LLM consult (Gemini + Codex). Non-skippable.
- **Adversarial hardening rule:** Generate adversarial counterexamples (Phase 2.5) for drafted test entries before advancing to cross-LLM consult.
- **Review-finding awareness rule:** If ERROR_POINTS.json contains entries sourced from prior review findings on this plan, draft at least one test entry targeting the failure class from those error points.
- **Failure class requirement:** Every test entry must be tagged with exactly one `failure_class`. Assertions like 'function returns' or 'no exception raised' are rejected.
- **Cross-source integrity:** Error-point-driven and invariant-driven entries are NOT conflated. An entry tests what its source declares. Cross-source deduplication merges only when `failure_class` AND `target_file` both match.

## Hard rules

- **Non-trivial tests only.** Every entry must name a domain-specific `failure_class`. The cross-LLM consult catches trivial tests.
- **Tests tied to sources.** Every mandatory test must trace to (a) an ERROR_POINTS.json entry, (b) an INVARIANTS.json entry, (c) a high-risk task in TASKS.md, or (d) a user-stated concern.
- **Cross-LLM consult is non-skippable.** Claude alone reliably generates trivial tests; the cross-LLM step catches bug classes it would miss.
- **No test execution.** `/z-test` is planning, not execution.
- **No SPEC.md / PLAN.md edits.** Only writes TESTS.md and appends `**Tests:**` lines to TASKS.md, and updates ERROR_POINTS.json `tests_targeting`.
- **No emojis** anywhere in TESTS.md.
- **Every test must verify a behavioral invariant or empirical error pattern, not just function-call correctness.**
- **Fixture schema validation required.** Every entry with `**Invariant ID:**` must have a `**Fixture:**` that conforms to the invariant's `fixture_schema`.
- **Coverage over perfection.** Uncovered blockers from both sources are recorded in TESTS.md frontmatter.

## CI mode (`--ci` flag)

When `--ci` is passed, `/z-test` runs in read-only validation mode. Updated for dual-source:

### CI mode behavior

1. **Load registries.** Loads INVARIANTS.json AND ERROR_POINTS.json (if present). Aborts with exit 4 if neither exists AND no TESTS.md exists.
2. **Load TESTS.md.** Parses existing TESTS.md. Aborts with exit 4 if absent.
3. **Coverage check.** Parses TESTS.md frontmatter for:
   - `**Uncovered invariants (blocker):**` — any uncovered blockers → exit 3.
   - `**Uncovered error points (blocker):**` — any uncovered blockers → exit 3.
4. **Fixture validation.** For each TEST-NNN entry with `**Invariant ID:**` or `**Error point ID:**` and `**Fixture:**`, validate fixture against applicable schema. Failed validations → exit 2.
5. **Test command discovery.** Discover test-runner.json or auto-detect test framework.
6. **Emit JSON summary:**
   ```json
   {
     "status": "pass|fail|coverage_gap",
     "covered_invariants": ["inv_001"],
     "uncovered_blockers": ["inv_012"],
     "covered_error_points": ["ep_003"],
     "uncovered_ep_blockers": ["ep_007"],
     "test_command": "pytest tests/ -k 'test_feed or test_fee'",
     "fixture_validation": "pass|fail",
     "fixture_failures": []
   }
   ```
7. **Exit codes:** 0=clear, 2=fixture violation, 3=coverage gap, 4=I/O error.

## What /z-test deliberately skips

- Does not run any tests (deferred to /z-implement-all + /z-review-all).
- Does not write actual test code (the implementer subagent does, in the task's diff).
- Does not modify SPEC.md or PLAN.md.
- No implementer-subagent dispatch.
- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate.
