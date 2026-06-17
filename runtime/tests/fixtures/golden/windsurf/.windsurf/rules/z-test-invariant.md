---
trigger: model_decision
description: "Archived invariant-only z-test. Invoke via /z-test --mode invariant. This is the legacy invariant-first test-case planner preserved for backward compatibility and reference."
---

> **ARCHIVED.** This is the archived invariant-only z-test skill. It is invoked via `/z-test --mode invariant`. The canonical z-test skill is at `skills/z-test/SKILL.md` (dual-source: ERROR_POINTS.json + INVARIANTS.json). This file is preserved for reference and for the invariant-only mode implementation.
>
> All behavior described below is the legacy invariant-only behavior. For the current dual-source pipeline, see `skills/z-test/SKILL.md`.

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
| `tags` | yes | string[] (≥1) | Controlled tags from `docs/llm/TAGS.txt`. See tags table below. |
| `failure_class` | yes | string (1-300) | Domain-term description of the bug this invariant prevents. |
| `fixture_schema` | no | object (≥1 property) | Optional JSON Schema shape for test fixture data. If present, must have ≥1 non-trivial constraint. |
| `fixture_defaults` | no | object | Optional default fixture values. Only valid when `fixture_schema` is present. |
| `severity` | yes | `blocker` \| `major` \| `minor` | `blocker` = PR gate fail, `major` = PR gate warn, `minor` = informational. |
| `source_files` | yes | string[] (1-50) | Source paths this invariant derives from, relative to repo root. |
| `last_updated` | yes | ISO-8601 string | Timestamp of last modification. Compared to source_files max mtime for staleness. |
| `source` | yes | `spec` \| `plan` \| `user-concern` \| `code-review` \| `axiom-derived` | Provenance of this invariant. |

### Controlled tags (from docs/llm/TAGS.txt)

`correctness`, `perf`, `data-quality`, `schema`, `time-window`, `units`, `api-boundary`, `retry-loop`, `race-condition`, `dependency`, `deprecation`, `lossy-default`, `ux`, `observability`, `compliance`

### Fixture schema constraints

When `fixture_schema` is present:
- It must be a valid JSON Schema object with `minProperties: 1`
- It must contain at least one non-trivial constraint (e.g. `minItems: 1`, `minimum: 1`, `not: {const: 0}`, `required: [...]`)
- If `fixture_defaults` is present, it must validate against `fixture_schema`
- The validation is performed by `scripts/validate-invariants.py` at write time and by `/z-test` Phase 4 at load time

### Atomic write discipline

All writes to INVARIANTS.json follow: tmpfile → flush → fsync → os.replace(). Same as `docs/llm/` write discipline. No partial writes.

---

You are running **z-harness `/z-test`** — the semantic test-case planner. This is an **optional planning-time step** between `/z-plan` and `/z-implement-all`. It does NOT write or run any test code. It produces a structured `TESTS.md` artifact that the implementer subagent reads alongside TASKS.md, so tests get implemented in the same diff as the code they exercise.

## Setup

### Phase 0 — Discovery

**Load INVARIANTS.json.** If the repo has `docs/INVARIANTS.json`, load it into memory. Parse the top-level structure: `version`, `generated_at`, `invariants[]`. Each invariant entry has `id`, `description`, `tags[]`, `failure_class`, optional `fixture_schema`/`fixture_defaults`, `severity`, `source_files[]`, `last_updated`, `source`.

If INVARIANTS.json is **absent**: emit a warning: "No INVARIANTS.json found — run `/z-init-docs --invariants` to bootstrap. Continuing with SPEC.md invariants only (legacy mode)." In legacy mode, the TESTS.md output will use version 1 format (no invariant IDs, no fixture data).

**Staleness check.** For each invariant in INVARIANTS.json, compare `source_files[]` max mtime to `last_updated`. If any invariant is stale (mtime > last_updated), warn the user: "K stale invariants may be outdated." Offer: continue / skip stale invariants / abort. Skipped invariants are excluded from Phase 1 matching.

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

**`--ci` flag.** If `--ci` is passed, switch to read-only CI validation mode: load INVARIANTS.json + TESTS.md, check for uncovered blocker invariants, validate all fixtures against schemas, emit machine-readable JSON summary to stdout, exit non-zero on violations. Do NOT write new TESTS.md entries, do NOT dispatch cross-LLM consult, do NOT ask user questions. See CI mode section at the end of this skill.

Pick run id `RRUN=$(date -u +%Y%m%dT%H%M%SZ)-test`. `mkdir -p $BASE/archive/$RRUN/transcripts`.

**Version stamp + log run start:**
```bash
VERSION_BLOB="$(bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/version.sh")"
START_PAYLOAD="$(python3 -c '
import json, sys
v = json.loads(sys.argv[1]); v["slug"] = sys.argv[2]
print(json.dumps(v))
' "$VERSION_BLOB" "$Z_HARNESS_SLUG")"
bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_start "$START_PAYLOAD"
```

Notification policy: see [docs/human/config.md](docs/human/config.md) (notify.level key).

## Phase 1 — Load invariants + risk-rank

Read `$BASE/SPEC.md`, `$BASE/PLAN.md`, `$BASE/TASKS.md`.

### 1a. Load invariants

**Primary source: INVARIANTS.json.** If loaded in Phase 0, all invariants are available for matching. Each invariant carries: `id`, `description`, `tags[]`, `failure_class`, `severity` (blocker|major|minor), optional `fixture_schema` and `fixture_defaults`.

**Fallback source: SPEC.md invariant lines.** Also extract from SPEC.md every line of these shapes for invariants not yet in INVARIANTS.json:
- `**INVARIANT:**` — explicit invariant declaration
- `**MUST:**` — mandatory behavioral constraint
- `**MUST NOT:**` — prohibited behavior
- `**DANGER:**` — danger-zone constraint
- Numeric/quantitative assertions ("must be ≤ X", "exactly N", "monotone in Y")
- Equality/identity claims about cross-module contracts ("strategy reads field X written by Y")

SPEC-only invariants are treated as candidate test seeds with lower traceability (no stable ID). When drafted into TESTS.md, they use the optional `invariant:` field (free-text quote) instead of the stable `invariant_id:`.

### 1b. Match invariants to tasks

For each task in TASKS.md:

1. **Explicit annotation match (primary).** If the task block has a `**Invariants:** inv_001, inv_003` line → direct binding. The listed IDs are definitively assigned to this task. No fuzzy matching needed.

2. **Fuzzy tag match (discovery hint).** If no explicit `**Invariants:**` line:
   - Scan the task's `Description:` and acceptance criteria for tag keywords from INVARIANTS.json entries' `tags[]`.
   - Also check description substring overlap with invariant `description` text.
   - Present any fuzzy matches as **suggestions** to the user — do NOT auto-bind. The user confirms or rejects in Phase 5.
   - Fuzzy matching weights: exact tag match (high), description substring (medium), same-module source_files overlap (low).

### 1c. Risk-rank tasks

For each task in TASKS.md, score risk on three axes:

- **Domain criticality.** Does this task touch critical domain concerns? Factor in matched invariants' `severity` — block-invariant coverage is mandatory, major is recommended.
- **Surface area.** Count files in the task's `Files:` block; count acceptance criteria; flag presence of `**DANGER:**` / `**INVARIANT:**` / `**MUST:**` tags in SPEC.md for any file the task touches.
- **Test-gap signal.** Acceptance criteria worded as "behavior X" without a numeric / type-shape / observable check are the worst case — the implementer can pass them without writing anything that proves correctness. Also factor: tasks with 0 matched invariants have a test-gap (no known behavioral contract to validate).

Output a ranked list (high → low):
- **High risk** → mandatory test coverage required.
- **Medium risk** → recommended.
- **Low risk** → optional.

### 1d. User concerns

`AskUserQuestion` (free-text):
- "What specific bug classes worry you most for this plan?"

Each user concern becomes an explicit test target in Phase 2 (`seed: user-concern`).

Save the ranked list + matched invariants + user concerns to `$BASE/archive/$RRUN/phase1-risk.md`.

## Phase 2 — Draft behavioral test cases

For each high-risk task and each matched invariant and each user concern, draft a candidate test entry using the **v2 format**:

```
- id: TEST-001
  task: T007                                    # link to TASKS.md entry (null if cross-task)
  invariant_id: inv_001                          # NEW — stable ID from INVARIANTS.json
  invariant: "Fees are never silently dropped"   # RETAINED — optional, for SPEC-only invariants (omit if invariant_id present)
  invariant_description: "Feed processing must preserve all fee fields"  # NEW — one-line human-readable
  test_name: feed_fee_preservation               # short snake_case
  target_file: tests/test_feed_processor.py      # abs path in repo-native location
  failure_class: "Silent fee drop — feed processes but fee field is zeroed or absent"  # domain-term bug description
  layer: per-task                                # NEW — per-task | full-chain
  fixture:                                       # NEW — inline JSON satisfying fixture_schema
    feed_records: [{"price": 100.0, "fee": 0.5}]
    expected_fees: {"total": 0.5}
  assertion: "assert feed_output.total_fees == 0.5 for input with fee 0.5"  # concrete observable check
  seed: spec | plan | task-risk | user-concern
  mandatory: yes | no
```

**v2 field additions (from v1):**
- `invariant_id:` — stable, machine-verifiable reference to INVARIANTS.json. Primary traceability link.
- `invariant:` — optional free-text quote. Only used for SPEC-only invariants not yet in INVARIANTS.json.
- `invariant_description:` — one-line human-readable invariant description.
- `layer:` — `per-task` (implemented with the task's production code) or `full-chain` (implemented after all tasks complete, tests end-to-end composed path).
- `fixture:` — inline JSON that satisfies the invariant's `fixture_schema` (if present). For invariants without `fixture_schema`, fixture is optional.

**Behavioral assertion discipline:**
- Assert composed behavior: "output.total_fees == input.sum(fee)" not "process_feed() was called"
- Assert invariants hold across module boundaries: "strategy.position == pipeline.position after sync"
- Every assertion must name a specific failure class in domain terms
- Assertions must be observable (numeric, type-shape, or invariant on output)

**Non-trivial failure class checklist:**
- **Sign/direction errors.** Notional sign, P&L sign, position-size sign, slippage application direction (paid vs received).
- **Schema/feature mismatches.** Strategy reads field `x` but pipeline writes `x'` — silent zero-fill or default-value bugs.
- **Off-by-one in time / rolling windows.** Bar boundary inclusivity, warmup-period truncation, look-ahead leakage.
- **Stale-data usage.** Reading a cached value that was supposed to be invalidated by an upstream event.
- **Cross-module contract drift.** Caller passes seconds, callee expects ms; caller passes contracts, callee expects notional.
- **Quantity/price unit confusion.** Cents vs dollars, contracts vs notional, bid vs mid vs ask.
- **State-machine invariants.** Forbidden transitions, idempotency violations (double-fill on retry).
- **Bounds.** Empty input, single-element input, sorted-vs-unsorted assumptions, NaN/None propagation.

**Fixture derivation.** For each entry with an `invariant_id` whose invariant has `fixture_schema`:
- Use the invariant's `fixture_defaults` as a starting point (if present).
- Override specific values to construct a test scenario that would fail if the invariant is violated.
- The fixture must validate against `fixture_schema` (checked in Phase 4).
- For `layer: full-chain` entries, fixtures represent end-to-end input data for the composed system path.

**Anti-rubber-stamp rule.** For each draft, write internally "one reason this test might be useless" (matches the `/z-plan` push-back discipline). If you can't articulate why the test could be useless, sharpen the assertion.

**Draft cap.** Cap at ~25 entries. Prefer mandatory over optional. Within mandatory, prefer: blocker invariants > user concerns > high-risk tasks.

Save the draft list to `$BASE/archive/$RRUN/phase2-drafts.md`.

## Phase 2.5 — Adversarial counterexample generation

**Gate:** Only runs if both conditions are met:
1. `docs/INVARIANTS.json` exists with at least one invariant that has a `fixture_schema`.
2. The falsification test from Phase B found a real gap (`catch_rate < 80%`). If `catch_rate >= 80%` or no falsification test was run, skip this phase entirely — the gap was an INVARIANTS.json absence problem, not an adversarial insufficiency problem.

**Catch rate source:** The `catch_rate` value comes from Phase B's falsification test (`falsification-metrics.json`). If that file is absent (no falsification test has been run), treat it as `catch_rate >= 80%` (skip adversarial).

Goal: For each invariant-test pair from Phase 2, generate adversarial input fixtures that would violate the invariant. The cross-LLM consult (Phase 3) then evaluates whether the draft test catches the adversarial scenario.

**Procedure:**

1. **Read Phase 2 drafts.** Load `$BASE/archive/$RRUN/phase2-drafts.md`. Collect every draft test entry that has an `invariant_id`.

2. **Load INVARIANTS.json.** For each unique `invariant_id`, load its `fixture_schema`, `fixture_defaults`, `failure_class`, and `tags`.

3. **Dispatch test-adversary subagent.** The subagent receives:
   - The invariant (from INVARIANTS.json): id, description, fixture_schema, fixture_defaults, failure_class, tags
   - The Phase 2 draft test entries for that invariant

   Prompt structure:
   ```
   MODE: adversarial-fixtures-for-invariant

   Read skills/z-test/test-adversary/MODEL.md for behavioral specs.

   For each invariant-test pair, generate 1 adversarial fixture:
   - Structurally valid against the invariant's fixture_schema
   - Plausible in a real system
   - Violates the invariant's behavioral constraint
   - Rated "subtle" or "sneaky" (not "obvious")

   Return JSON array.
   ```

4. **Annotate draft entries.** For each draft test entry that received an adversarial fixture, append:
   ```
   adversarial_scenario: "<one-line description>"
   adversarial_fixture: <json blob>
   adversarial_subtlety: "subtle" | "sneaky"
   expected_violation_found: "<description of what should fail>"
   realism_score: "plausible" | "edge_case" | "synthetic"
   ```

   Field mapping from `test-adversary/MODEL.md` output:
   - `adversarial_scenario` ← `adversarial_scenario`
   - `adversarial_fixture` ← `fixture`
   - `adversarial_subtlety` ← `subtlety_rating` (mapped: "obvious" → skip, "subtle" → "subtle", "sneaky" → "sneaky")
   - `expected_violation_found` ← `expected_violation`
   - `realism_score` ← `realism`

5. **Save annotated drafts.** Write to `$BASE/archive/$RRUN/phase25-adversarial.md`.

6. **Hard rule:** Phase 2.5 failure MUST NOT block Phase 3. If the subagent fails (timeout, bad JSON, crash), log the error to `$BASE/archive/$RRUN/phase25-error.log` and continue to Phase 3 with the un-annotated drafts.

## Phase 3 — Bundled cross-LLM consult (mode `test-cases`)

Spawn **both** consultants in parallel in a single message:

```
<!-- agent dispatch / skill invocation not supported in Windsurf; see CAPABILITIES.md -->
  subagent_type="consultant-primary",
  description="Test-cases consult (Gemini) for <slug>",
  prompt="MODE: test-cases\n\nSPEC.md (verbatim):\n<contents>\n\nPLAN.md (verbatim):\n<contents>\n\nTASKS.md (verbatim):\n<contents>\n\nINVARIANTS.json (verbatim — loaded from docs/INVARIANTS.json if present; if absent, note that no system invariants exist and only SPEC.md invariants are available):\n<contents of INVARIANTS.json or 'ABSENT'>\n\nMy draft test cases (Phase 2):\n<contents of phase2-drafts.md>\n\nUser-stated concerns:\n<from Phase 1 AskUserQuestion>\n\nSource files referenced by the drafts (read these for real types/signatures):\n<list of abs paths>\n\nAsk:\n1. For each draft test: is the assertion strong enough to catch a real bug, or a tautology? If weak, propose a stronger assertion (be concrete).\n2. Which INVARIANTS.json invariants (by ID) do not yet have a corresponding test entry? For each uncovered invariant, propose a draft test entry with fixture values that would expose a violation of that invariant. Prioritize blocker > major severity.\n3. Which fixture values would expose a violation of invariant X? For each invariant with a fixture_schema, suggest concrete fixture data that would cause the invariant to fail.\n4. What dangerous bug classes specific to this codebase domain are not covered by my drafts? Consider the invariant failure classes listed in INVARIANTS.json as a checklist.\n5. Flag any draft that is mechanically trivial (asserts what the implementation already obviously does) and recommend dropping it.\n6. Identify any draft whose target_file is in the wrong place (test framework convention mismatch).\n7. Identify any invariant-entry mismatch: does any draft claim to cover an invariant (via invariant_id) but the assertion doesn't actually test the invariant's described behavior?\n\nReturn structured: per-draft critique (keep | strengthen | drop), then a list of NEW test entries for uncovered invariants, then a list of fixture value suggestions for invariants that need better test data."
)
<!-- agent dispatch / skill invocation not supported in Windsurf; see CAPABILITIES.md -->
  subagent_type="consultant-secondary",
  description="Test-cases consult (Codex) for <slug>",
  prompt="MODE: test-cases\n\n<same prompt body>"
)
```

Both transcripts archive themselves under `$BASE/archive/$RRUN/transcripts/`.

**INVARIANTS.json handling:**
- If INVARIANTS.json is present and loaded: include the full file verbatim in the consultant prompt. The consultants use it to (a) identify uncovered invariants, (b) suggest fixture values that would violate each invariant, (c) cross-check that each draft's `invariant_id` actually tests the invariant's described behavior.
- If INVARIANTS.json is absent: include the note "INVARIANTS.json is ABSENT — only SPEC.md invariants are available for coverage analysis." The consultants fall back to SPEC.md invariant lines only.

## Phase 4 — Synthesize

When both return:

1. **Merge** Claude's drafts + Gemini's additions + Codex's additions. Dedupe by `test_name` + `target_file`.
2. **Apply per-draft verdicts.** For each draft Claude wrote: if both LLMs said "drop, trivial" → drop. If both said "strengthen", apply the stronger assertion. If exactly one said drop → keep but flag for user.
3. **Apply additions.** For each NEW test entry an LLM proposed, run the same anti-rubber-stamp check ("one reason this test might be useless"). Drop pure rubber-stamps.
4. **Cross-LLM disagreement.** If Gemini and Codex disagree on whether a specific draft is meaningful, surface that disagreement to the user via Phase 5 `AskUserQuestion` — do NOT silently pick one side.
5. **Fixture validation.** For each draft entry with an `invariant_id` and `fixture:` field, resolve the invariant from INVARIANTS.json. If the invariant has a `fixture_schema`, validate the entry's `fixture:` JSON against it:
   ```bash
   python3 scripts/validate-invariants.py --fixture <entry_fixture_json_file> --schema <tmp_schema_file>
   ```
   Entries whose fixture fails validation are flagged for user in Phase 5 (option: fix fixture / drop / accept with warning). Entries whose invariant has no `fixture_schema` skip validation (pure behavioral invariants don't require fixtures).
6. **Uncovered invariants.** Check which INVARIANTS.json invariants have zero corresponding test entries. For each uncovered invariant with severity `blocker` or `major`, propose a draft entry in the Phase 5 approval list. Minor uncovered invariants are informational only.

Track these counts for the Phase 8 finalize push-notify:
- `n_dropped_by_consult` — drafts both LLMs flagged as trivial
- `n_added_by_consult` — net new test entries from LLMs
- `n_strengthened` — drafts where assertion was upgraded based on LLM input
- `n_fixture_validation_failures` — entries whose fixture failed schema validation
- `n_uncovered_blockers` — blocker invariants with no test coverage
- `n_uncovered_majors` — major invariants with no test coverage

Save the synthesized list to `$BASE/archive/$RRUN/phase4-synthesis.md`.

## Phase 5 — Present + approve

Send `PushNotification` (if policy != `off`): "Test plan ready for review."

Present counts via `AskUserQuestion`:
- "<M> mandatory + <R> recommended + <O> optional tests drafted. Cross-LLM dropped <D> trivial drafts; added <A> coverage gaps. <U> invariants from INVARIANTS.json have no test coverage (<B> blockers, <MJ> majors)."

Also list any uncovered blocker invariants explicitly:
- "Uncovered blockers: inv_012 (Fees are never silently dropped), inv_015 (No look-ahead leakage)"

The user may choose to add coverage for these now or acknowledge the gap.

Options:
- **Accept all** — write all entries into TESTS.md.
- **Accept mandatory + recommended only** — drop optional tier.
- **Edit subset** — orchestrator iterates each contested test (cross-LLM disagreement, or user-concern items) via per-test `AskUserQuestion`: keep / drop / modify (free-text).
- **Abandon** — log `test_plan_end` with `status: abandoned`; exit. No TESTS.md written.

**Fixture-scaffolding gate.** For any accepted test whose `fixture:` field requires non-trivial new test infrastructure (a new fixture file, a new mock framework, a new test-data generation step), get separate explicit approval via `AskUserQuestion`. Same discipline as `/z-plan` shortcuts: building new test infra without buy-in is a scope expansion. The `fixture:` JSON itself is part of the TESTS.md entry — no separate fixture file is needed unless the data is large.

## Phase 6 — Write TESTS.md (v2 format)

Write `$BASE/TESTS.md` in **v2 format**:

```markdown
# Tests for <slug>

**Run:** <RRUN>
**Version:** 2
**Status:** drafted (awaiting /z-implement-all)
**Invariants file:** docs/INVARIANTS.json
**Plugin version:** <z_harness_version from setup>
**Cross-LLM consensus:** <agree | gemini-only-<N> | codex-only-<N> | user-overrode-<N>>
**Counts:** <M> mandatory, <R> recommended, <O> optional
**Cross-LLM delta:** dropped <D> trivial, added <A> coverage gaps, strengthened <S>
**Covered invariants:** inv_001, inv_003, inv_007
**Uncovered invariants (blocker):** inv_012
**Uncovered invariants (major):** inv_005, inv_009

## TEST-001  (covers T007)
**Invariant ID:** inv_001
**Invariant:** "Fees are never silently dropped during feed processing"
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
**Invariant ID:** inv_003
**Invariant description:** Position sync must be atomic across all modules
**Failure class:** Position drift — strategy sees stale position after pipeline update
**Layer:** full-chain
**Target file:** tests/test_position_sync.py
**Fixture:**
  initial_position: 100
  pipeline_update: +50
**Assertion:** strategy.position == 150 after pipeline.update(+50) completes
**Seed:** spec
**Mandatory:** yes
```

**v2 TESTS.md fields (per entry):**
- `**Invariant ID:**` — stable ID from INVARIANTS.json. Primary traceability link for machine verification.
- `**Invariant:**` — optional free-text quote (only for SPEC-only invariants; omit when Invariant ID present).
- `**Invariant description:**` — one-line human-readable invariant description.
- `**Failure class:**` — domain-term bug description (same as v1).
- `**Layer:**` — `per-task` (implemented in task diff) or `full-chain` (implemented after all tasks complete).
- `**Target file:**` — absolute path where test code should live.
- `**Fixture:**` — inline YAML-friendly key-value pairs (not raw JSON — implementer-friendly format).
- `**Assertion:**` — concrete observable check (same as v1).
- `**Seed:**` — provenance (spec, plan, task-risk, user-concern).
- `**Mandatory:**` — yes/no.

**v2 header fields:**
- `**Version:** 2` — distinguishes v2 from v1 TESTS.md.
- `**Invariants file:**` — path to the INVARIANTS.json file used.
- `**Covered invariants:**` — comma-separated list of invariant IDs with test entries.
- `**Uncovered invariants (blocker):**` — blocker invariants with no test coverage.
- `**Uncovered invariants (major):**` — major invariants with no test coverage.

**Legacy v1 format:** If INVARIANTS.json was absent (legacy mode from Phase 0), write TESTS.md without `**Version:** 2` and without invariant-specific fields. v1 entries omit `Invariant ID`, `Invariant description`, `Layer`, and `Fixture`. This is backward-compatible with existing consumer code.

Each TEST-NNN block must be parseable by the implementer subagent (it greps the file for `## TEST-NNN` to find its entry). Use stable IDs even if the user dropped some during Phase 5 — gaps in numbering are fine.

No SPEC.md / PLAN.md changes. TESTS.md is its own artifact.

## Phase 7 — Cross-link into TASKS.md

For each task `Txxx` referenced by one or more TEST-NNN entries, append a line under that task's block in TASKS.md:

```
**Tests:** TEST-001, TEST-004  (see TESTS.md)
```

Placement: directly after the task's `Acceptance:` block, before any `**REMOTE_VERIFY:**` or `**DOCS:**` line.

This is the signal to the implementer subagent: when implementing this task, also implement the listed TEST-NNN entries from TESTS.md in the same diff. The implementer reads TESTS.md, parses the `**Version:**` header to choose v1 or v2 parsing, grep-finds each `## TEST-NNN`, and produces the test code at the entry's `**Target file:**` path.

If a task already has a `**Tests:**` line from a prior `/z-test` invocation, **merge IDs** — never overwrite. Sort the merged list.

**Cross-task tests** (entries with `task: null`) and **full-chain tests** (entries with `**Layer:** full-chain`) are not linked into TASKS.md. They get implemented separately:
- `layer: full-chain` tests are written by T017 after all per-task implementation completes
- Cross-task tests with `task: null` are implemented as part of `/z-review-all`'s final gate

Note this in the user-facing summary in Phase 8.

## Phase 8 — Finalize

1. Copy TESTS.md into `$BASE/archive/$RRUN/`.
2. Log:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "$RRUN" test_plan_end \
     "$(printf '{"status":"drafted","n_mandatory":%d,"n_recommended":%d,"n_optional":%d,"n_dropped_by_consult":%d,"n_added_by_consult":%d,"n_strengthened":%d,"n_cross_task":%d,"n_full_chain":%d,"uncovered_invariant_count":%d,"uncovered_blocker_count":%d}' \
        "$M" "$R" "$O" "$D" "$A" "$S" "$X" "$FC" "$UI" "$UB")"
   ```
3. Push-notify (if policy != `off`):
   ```
   Test plan complete. <M> mandatory + <R> recommended + <O> optional tests drafted.
   Cross-LLM dropped <D> trivial drafts; added <A> coverage gaps.
   <FC> full-chain tests deferred to post-implementation.
   <UI> invariants have no test coverage (<UB> blockers, <UM> majors).

   Recommended next:
     /z-implement-all   — implements tasks AND their linked TESTS.md entries together
   ```
4. Brief user summary (3-5 sentences): what was drafted, what cross-LLM caught, uncovered invariant counts, how many full-chain tests are deferred, how many cross-task tests are deferred to /z-review-all.

### Full-chain test code generation

After all per-task implementation is complete (via `/z-implement-all`):

For each `**Layer:** full-chain` entry in TESTS.md, generate the actual test code file at the `**Target file:**` path. This step runs AFTER all tasks are implemented (because full-chain tests exercise the composed end-to-end path, requiring all modules to exist first).

**When to run:**
- After `/z-implement-all` completes (all per-task tests pass)
- Before `/z-review-all` Phase 3.5 runs the full test suite

**Generation procedure:**

1. Parse TESTS.md for all `## TEST-NNN` blocks with `**Layer:** full-chain`.
2. For each block:
   - Read `**Invariant ID:**`, `**Invariant description:**`, `**Target file:**`, `**Fixture:**` (inline YAML), `**Assertion:**`, `**Failure class:**`.
   - Resolve the invariant from INVARIANTS.json for `fixture_schema` validation.
   - Generate a test function at `Target file:` that:
     - Loads fixture data from the entry's `**Fixture:**` values
     - Exercises the composed system path (the end-to-end flow from input through all modules to output)
     - Asserts the behavioral invariant from `**Assertion:**`
     - On failure, reports the `**Failure class:**` and invariant ID
   - The test MUST be runnable by the same test runner used for per-task tests (discovered via test-runner.json).
3. Write the test file using atomic write (tmpfile → flush → fsync → os.replace()).
4. Validate the file compiles/parses correctly (dry-run with the test framework's syntax check).

**Test file format (example for pytest):**
```python
# Full-chain invariant test: inv_001 — Fees are never silently dropped
# Generated by /z-test Phase 8 full-chain generation
# Fixture: feed_records with fees, expected output with preserved fees

import pytest

def test_full_chain_inv_001_fee_preservation():
    """Invariant inv_001: Fees are never silently dropped during feed processing.
    Failure class: Silent fee drop — feed processes but fee field is zeroed or absent."""
    # Fixture data from TESTS.md
    feed_records = [{"price": 100.0, "fee": 0.5}]
    expected_fees = {"total": 0.5}

    # Exercise the composed system path
    from feed.processor import process_feed
    result = process_feed(feed_records)

    # Assert the behavioral invariant
    assert result.total_fees == expected_fees["total"], \
        f"inv_001 VIOLATION: expected fees {expected_fees['total']}, got {result.total_fees}"
```

**Exit codes:**
- 0: all full-chain tests generated and pass syntax check
- 1: one or more full-chain test files have syntax errors
- 2: fixture validation failure (fixture doesn't satisfy invariant's fixture_schema)

After generation, the full-chain test files are ready for execution by `/z-review-all` Phase 3.5 and `scripts/invariant-check.sh`.

## Behavioral rules

- **Invariant coverage rule:** Every test function drafted by `/z-test` must verify at least one invariant from `docs/INVARIANTS.json`. In legacy mode (INVARIANTS.json absent), use SPEC.md invariant lines as the authoritative reference. Never silently skip invariant coverage.
- **Cross-LLM consult rule:** Before finalizing any test entry, consult at least one other LLM (via Phase 3 bundled cross-LLM consult with Gemini + Codex) for adversarial edge cases. A single LLM reliably generates trivial tests; the cross-LLM step catches the bug classes it would otherwise miss. This consult is non-skippable.
- **Adversarial hardening rule:** Generate adversarial counterexamples (Phase 2.5) for every drafted test entry before advancing to cross-LLM consult. If an adversarial counterexample is found, the test entry must be strengthened or dropped. A test that repeatedly fails adversarial hardening (>=2 counterexamples after strengthening) should be dropped — it is testing the wrong invariant.
- **Review-finding awareness rule:** If review findings from prior `/z-review-all` runs on this plan mention a module, draft at least one test entry targeting the failure class from those findings. Check `$Z_HARNESS_PLAN_DIR/archive/*/findings.md` for prior review findings before drafting test entries.
- **Failure class requirement:** Every test entry in TESTS.md must be tagged with exactly one `failure_class` from the `docs/INVARIANTS.json` enum. Assertions like 'function returns' or 'no exception raised' without further constraint are rejected.

## Hard rules

- **Non-trivial tests only.** Every TESTS.md entry must name a domain-specific **failure class**. Assertions like "function returns" or "no exception raised" without further constraint are rejected. The cross-LLM consult exists precisely to catch and drop these.
- **Tests tied to invariants.** Every mandatory test must trace to (a) a quoted SPEC.md invariant, (b) a high-risk task in TASKS.md, or (c) a user-stated concern from Phase 1. No orphan tests.
- **Cross-LLM consult is non-skippable.** This is the entire point of `/z-test` — Claude alone reliably generates trivial tests; the cross-LLM step catches the bug classes it would otherwise miss.
- **No test execution.** `/z-test` is planning, not execution. The implementer writes the test code (in the same task as its production code); `/z-implement-all`'s per-task acceptance check runs it; `/z-review-all`'s final gate runs the suite.
- **No SPEC.md / PLAN.md edits.** Only writes TESTS.md and appends `**Tests:**` lines to TASKS.md.
- **No new agents dispatched.** Reuses `consultant-primary` and `consultant-secondary` only.
- **No emojis** anywhere in TESTS.md.
- **Every test must verify a behavioral invariant, not just function-call correctness.** A test that calls a function and asserts a return value without verifying a system-level property (feed connectivity, state consistency, price monotonicity, fee enforcement) is a unit test, not an invariant test. Reject it.
- **Fixture schema validation required.** Every TEST-NNN entry with `**Invariant ID:**` must have a `**Fixture:**` block. The fixture MUST conform to the invariant's `fixture_schema` in INVARIANTS.json. If the schema declares a required field, the fixture MUST include it. Cross-LLM consult validates this.
- **Coverage over perfection.** If an invariant has no matching task in the plan, record it as "Uncovered invariants (blocker)" in TESTS.md frontmatter rather than skipping it. The catch_count tracks what was covered; uncovered entries trigger CI alerts.
- **Adversarial thinking required.** For every invariant, the test fixture must include at least one adversarial variant (a realistic data point that violates the invariant). If the invariant is about atomic writes, the fixture should include a simulated partial-write scenario. If about price monotonicity, include a tick with a price drop.

## What /z-test deliberately skips

- Does not run any tests (deferred to /z-implement-all + /z-review-all).
- Does not write actual test code (the implementer subagent does, in the task's diff).
- Does not modify SPEC.md or PLAN.md (only appends `**Tests:**` to TASKS.md and creates TESTS.md).
- No implementer-subagent dispatch (all ideation in orchestrator main thread + cross-LLM consult, same model as /z-plan-light).
- No `--apply` flag — Phase 5 `AskUserQuestion` is the only write gate. The user can re-run `/z-test` later to add more tests; merge semantics in Phase 7 handle this.

---

## CI mode (`--ci` flag)

When `--ci` is passed, `/z-test` runs in **read-only validation mode**. It does NOT write new TESTS.md entries, does NOT dispatch cross-LLM consultants, and does NOT ask user questions. CI mode is deterministic and fast.

### CI mode behavior

1. **Load INVARIANTS.json + TESTS.md.** Reads the existing TESTS.md from the plan directory. Aborts with exit 4 if neither exists.
2. **Coverage check.** Parses TESTS.md frontmatter for `**Uncovered invariants (blocker):**`. If any uncovered blockers exist → exit 3 (coverage gap).
3. **Fixture validation.** For each TEST-NNN entry with `**Invariant ID:**` and `**Fixture:**`, resolve the invariant's `fixture_schema` from INVARIANTS.json and validate the fixture:
   ```bash
   python3 scripts/validate-invariants.py --fixture <fixture_json_file> --schema <schema_from_invariant>
   ```
   Failed validations are errors. If any fixture fails → exit 2 (fixture constraint violation).
4. **Test command discovery.** Read `test-runner.json` from the same directory as TESTS.md for the test command template. If absent, attempt auto-detection (cargo → `cargo test`, pyproject.toml → `pytest`, package.json → `pnpm test`).
5. **Emit JSON summary to stdout:**
   ```json
   {
     "status": "pass|fail|coverage_gap",
     "covered_invariants": ["inv_001", "inv_003"],
     "uncovered_blockers": ["inv_012"],
     "test_command": "pytest tests/ -k 'test_feed or test_fee'",
     "fixture_validation": "pass|fail",
     "fixture_failures": []
   }
   ```
6. **Exit codes:**
   - 0: all clear — no coverage gaps, all fixtures valid, tests would run
   - 1: invariant violations (use when test run is incorporated)
   - 2: fixture constraint violation
   - 3: coverage gap (uncovered blockers)
   - 4: I/O / config error (missing files, unparseable)

### CI integration example

```bash
# In CI pipeline:
/z-test --ci --slug my-plan
RC=$?
if [ $RC -eq 3 ]; then
  echo "Coverage gap: uncovered blocker invariants — add tests before merging"
  exit 1
fi

# Then run the actual tests:
./scripts/invariant-check.sh
```
