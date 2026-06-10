# PLAN: z-test dual-source redesign

## Goals

1. **Dual-source test generation.** z-test loads both ERROR_POINTS.json (empirical regression hardening) and INVARIANTS.json (preventive coverage), interleaving test drafts at a configurable ratio (default 70:30).

2. **ERROR_POINTS.json registry.** A new per-repo artifact (`docs/ERROR_POINTS.json`) that accumulates failure patterns from every `/z-review-all` run. Each entry carries a deterministic pattern signature, frequency counter, sightings log, and test-targeting links.

3. **INVARIANTS.json augmentation.** Add `sighting_count`, `last_sighting`, `anchor_module` to existing invariant entries — backward-compatible optional fields. These make INVARIANTS.json "alive" without replacing it.

4. **z-review-all integration.** Every review run automatically updates both registries via an extended Phase 5.5 subagent: matches findings against existing entries (deterministic first, then LLM), increments counters, and creates new candidates. Write-rate-limited and non-blocking.

5. **Mode flags.** `--mode dual` (default), `--mode error-points`, `--mode invariant` (legacy). Graceful degradation when one source is absent.

6. **Pruning and resurrection.** Error points with tests that haven't been sighted in 90+ days are archived (not deleted). They resurrect if the pattern reappears.

## Design decisions

### D1: ERROR_POINTS.json is a separate artifact, not folded into INVARIANTS.json

**Chosen:** Separate artifact.

**Rejected:** Claude's proposal to add frequency fields to INVARIANTS.json and skip a new artifact.

**Why:** The two registries serve different goals (empirical vs preventive) and have different lifecycles (error points prune/archive/resurrect; invariants are permanent until deprecated). Mixing them into one artifact conflates two different testing philosophies and makes the pruning/resurrection semantics confusing. A user reading INVARIANTS.json should see design truths; a user reading ERROR_POINTS.json should see failure history. The 3-field augmentation of INVARIANTS.json gives us Claude's parsimony win (heartbeat for invariants) without losing Codex's architectural clarity (separate concerns).

**Consult?** No — this is the converged premise from BRAINSTORM.md, already fully debated.

---

### D2: Deterministic pattern signature before LLM classification

**Chosen:** Compute `sha256(module_prefix::finding_class_norm::severity)[:16]` before any LLM call. Use this for primary matching. LLM fuzzy matching is fallback only.

**Rejected:** LLM-only similarity classification (the original BRAINSTORM proposal).

**Why:** Gemini's signal-decay analysis is correct: every LLM link in the chain loses signal. A deterministic hash of (module prefix, finding class, severity) costs zero tokens, takes zero wall time, and is perfectly reproducible. It catches the common case: the same bug in the same module with the same severity. The LLM fallback handles cross-module patterns (e.g., "time-window off-by-one" in different files).

**Consult?** No — deterministic-first is a performance/robustness win with no downside.

---

### D3: sightings[] ring-buffer instead of just a frequency counter

**Chosen:** Each error point carries a `sightings[]` array (max 20 entries, newest first) with `{run_id, finding_id, module_path}` for each sighting.

**Rejected:** Simple `frequency` integer only.

**Why:** A bare frequency counter loses module-path information. If an error point is "time-window off-by-one" seen 7 times in `fill.rs` and then suddenly in `report.rs`, the anchor_module should update. The ring-buffer enables that without unbounded growth.

**Consult?** No — the ring-buffer is a small implementation choice with clear benefits.

---

### D4: Rate-limiting on writes (frequency cap + new-entry cap)

**Chosen:** Max +1 frequency per error point per review run. Max `Z_HARNESS_ERROR_POINT_MAX_NEW` (default 10) new entries per run.

**Rejected:** No rate-limiting (unbounded writes).

**Why:** This prevents a single bad review run (e.g., an LLM that classifies everything as a new finding) from flooding the registry. The blind spot surfaced in the anti-bias check ("ERROR_POINTS.json as an attack surface") is addressed by write rate-limiting.

**Consult?** No — rate-limiting is a safety guardrail, not a design decision.

---

### D5: `last_test_pass` / `last_test_fail` instead of `tests_targeting` as the live signal

**Chosen:** Both fields coexist. `tests_targeting` is the list of TEST-NNN IDs (for cross-referencing). `last_test_pass` and `last_test_fail` are timestamps updated when test suites run.

**Rejected:** `tests_targeting` count alone as the signal (the original BRAINSTORM's "vanity metric").

**Why:** Gemini correctly flagged that `tests_targeting` is a vanity metric — having a test doesn't mean it works. `last_test_pass`/`last_test_fail` tells us whether the test actually caught anything. Both fields serve different readers: `tests_targeting` for traceability (which test covers this error point?), `last_test_pass`/`last_test_fail` for effectiveness (does the test catch the bug?).

**Caveat:** Updating `last_test_pass`/`last_test_fail` requires test-runner integration — the test runner must report which TEST-NNN IDs passed/failed. This is deferred to a future `/z-test-run` or CI integration. For now, these fields are written but default to null and are not updated automatically. This is noted as a shortcut (S1).

**Consult?** No — the two-field approach is strictly better. The update mechanism is deferred.

---

### D6: Dual mode is default, not error-points-primary

**Chosen:** `--mode dual` is the default. `--mode error-points` and `--mode invariant` are explicit opt-ins.

**Rejected:** Error-points as default (the original BRAINSTORM's `--mode error-points (default)`).

**Why:** Codex's framing is correct — error-points as default signals that invariants are legacy. Making dual the default communicates that both sources are first-class. Users who want pure regression hardening can opt in.

**Consult?** No — this is a signaling choice, already debated in BRAINSTORM.

---

### D7: Invariant test deprioritization uses log-dampening

**Chosen:** Invariant weight for test ranking: `severity_weight × log(1 + sighting_count)`.

**Rejected:** Linear `severity × sighting_count`.

**Why:** Claude's insight: without log-dampening, one hot invariant (sighted in 10 review runs) monopolizes every test slot. Log-dampening ensures high-sighting invariants get boosted but not unboundedly. A invariant with 0 sightings still gets tested at baseline (`severity_weight × log(1) = severity_weight`).

**Consult?** No — the math is straightforward and the dampening factor is tunable.

---

### D8: Archived error points resurrect on pattern re-match

**Chosen:** Archived error points stay in the matching index. If a new finding's `pattern_signature` matches an archived entry → `archived: false`, `archived_at: null`, frequency reset to 1, new sighting appended.

**Rejected:** Permanent archiving (cannot resurrect) or deletion.

**Why:** The original BRAINSTORM said "archived points can resurrect if pattern reappears" but didn't specify how. This mechanism is simple: the `pattern_signature` is the resurrection key. Deletion would lose the history; permanent archiving would miss recurring patterns.

**Consult?** No — resurrection-by-signature is the simplest mechanism that satisfies the requirement.

---

### D9: No cross-repo error point transfer (deferred)

**Chosen:** ERROR_POINTS.json is per-repo only. No cross-repo transfer in this plan.

**Why:** The anti-bias check surfaced cross-repo error points as a blind spot ("a missed opportunity AND a risk"). It's a real opportunity but introduces complexity: pattern signatures must be repo-agnostic, error points need a `source_repo` field, matching gets harder. This is deferred to a future plan when we have data on whether patterns transfer between repos.

**Consult?** No — this is a deliberate scope exclusion.

---

### D10: No signal audit before building (Gemini's process discipline, deferred)

**Chosen:** Skip the empirical signal audit (simulate error-point pipeline on past review runs, measure bug recurrence rate). Build first, measure after.

**Rejected:** Build nothing until empirical data proves ≥30% mapping rate.

**Why:** Gemini's "measure first" is correct process discipline but wrong for this plan. We can't measure error-point effectiveness until ERROR_POINTS.json exists and has data. The init bootstrap (TODO/FIXME scan) gives us enough seed data to start measuring immediately after the first review run. The cost of building first is low (≤10 files, mostly markdown/schema) and the learning from real usage is higher-signal than a simulation.

**Consult?** No — this is a process timing decision.

---

## Non-goals

- **No test execution.** z-test is still planning-only. Test execution remains in `/z-implement-all` and `/z-review-all`.
- **No cross-repo error points.** ERROR_POINTS.json is per-repo.
- **No automatic `last_test_pass`/`last_test_fail` updates.** Deferred to test-runner integration.
- **No INVARIANTS.json pruning.** Invariants are permanent; error points prune.
- **No new subagents.** Extended Phase 5.5 reuses the existing Haiku subagent.
- **No changes to `/z-amend` or `/z-improve`.** These commands are unaffected.
- **No changes to `/z-init-docs --invariants`.** INVARIANTS.json bootstrap is unchanged.

## Shortcuts (approved in BRAINSTORM)

### S1: `last_test_pass` / `last_test_fail` deferred integration

**Shortcut:** These fields are in the ERROR_POINTS.json schema but default to null. They are not automatically updated by test runs. A future `/z-test-run` or CI integration will populate them.

**Robust alternative:** Build a test-runner callback that parses test output, maps test names to TEST-NNN IDs, and updates ERROR_POINTS.json atomically after each test run.

**Cost of shortcut:** `staleness_score` doesn't benefit from test-effectiveness data. A stale error point with a working test looks the same as one with a broken test. Both are stale — we just don't know which is worse.

**Approved:** Yes (in BRAINSTORM — explicit deferral).

### S2: Init bootstrap is comment-scan only

**Shortcut:** The first-run codebase scan only scans for TODO/FIXME/HACK/XXX/BUG comments and empty error handlers. It does not parse ASTs or do dataflow analysis.

**Robust alternative:** Full AST-based bug-pattern scan (e.g., unwrap calls in non-test code, division without zero-check, integer overflow paths).

**Cost of shortcut:** Cold-start error points are low-confidence (severity: minor) and coarse-grained. They provide seed data but won't catch subtle bugs until real review runs accumulate.

**Approved:** Yes (in BRAINSTORM — Claude's framing says cold start is fine; data accumulates in 2-3 review runs).

### S3: No LLM adversarial classifier for error-point deduplication

**Shortcut:** Only the Phase 5.5 Haiku subagent (already dispatched) does fuzzy matching. There is no separate similarity-classifier subagent for deduplication across runs.

**Robust alternative:** A dedicated cheap-LLM similarity classifier that runs after each review run, comparing every new finding against all existing error points.

**Cost of shortcut:** Cross-run deduplication relies on the `pattern_signature` deterministic hash, which is exact-match on (module_prefix, finding_class, severity). Patterns that move modules (e.g., "time-window off-by-one" seen in `fill.rs` then `report.rs`) won't match deterministically and won't be deduplicated. They create separate error points.

**Approved:** Yes (Gemini's deterministic-first rule wins — we start simple and add LLM dedup later if needed).

---

## Implementation phases

### Phase A: Schema + validation (no behavior change)

1. Create `docs/schemas/error_points.schema.json` (JSON Schema draft-2020-12).
2. Create `scripts/validate-error-points.py` (validation script).
3. Update `docs/schemas/invariant.schema.json` — add `sighting_count`, `last_sighting`, `anchor_module`.
4. Update `scripts/validate-invariants.py` — accept new fields.
5. Create empty `docs/ERROR_POINTS.json` (init bootstrap content).

### Phase B: z-review-all Phase 5.5 extension

6. Extend Phase 5.5 of `skills/z-review-all/SKILL.md`:
   - Pre-compute deterministic pattern_signature matches before Haiku dispatch.
   - Augment Haiku prompt: add existing error points and invariants as context.
   - Haiku returns both invariant matches AND error point matches/candidates.
   - Enforce rate-limiting (max +1 frequency per error point per run, max 10 new entries).
   - Prune eligible error points after write.
   - Validate with `scripts/validate-error-points.py`.

### Phase C: z-test full rewrite

7. Rewrite `skills/z-test/SKILL.md` for dual-source pipeline:
   - Phase 0: load both registries with graceful degradation.
   - Phase 1: rank both sources, interleave at configured ratio.
   - Phase 2: draft entries from both sources.
   - Phase 2.5: adversarial counterexamples for both sources.
   - Phase 3: consultants receive both sources.
   - Phase 4: merge + dedupe across sources.
   - Phase 6: write TESTS.md with dual-source fields.
   - Phase 7: cross-link into TASKS.md AND update ERROR_POINTS.json tests_targeting.

### Phase D: Archive + docs

8. Rename `skills/z-test/SKILL.md` → archive as `skills/z-test-invariant/SKILL.md` (with updated frontmatter).
9. Update `AGENTS.md` routing table entry for z-test.
10. Re-export z-test prompt for pi (`exports/pi/prompts/z-test.md`) — if export mechanism exists.

---

## How this plan respects DRY / KISS / SOLID

**DRY:** The Phase 5.5 Haiku subagent handles BOTH invariant extraction and error-point extraction in a single dispatch. The z-test pipeline (Phases 0-8) is shared across all three modes — mode flags control which data sources are loaded and how ranking works, not the pipeline shape.

**KISS:** Deterministic pattern_signature matching is a 3-line hash function — no LLM, no latency. Error-point init bootstrap is a grep for 5 comment patterns. The ring-buffer on sightings caps at 20 entries — no unbounded growth. Rate-limiting is two integer caps.

**SOLID:**
- **Single Responsibility:** ERROR_POINTS.json = empirical failures. INVARIANTS.json = declared truths. z-review-all = writes both. z-test = reads both.
- **Open/Closed:** The mode flag opens the pipeline to new source types (e.g., a future `--mode coverage-gap` could add a third source) without changing the pipeline shape.
- **Liskov Substitution:** Both sources produce test-entry drafts in the same v2 format — the interleaver doesn't care which source a draft came from.
- **Interface Segregation:** ERROR_POINTS.json and INVARIANTS.json have separate schemas and separate validation scripts. Reading one never requires parsing the other.
- **Dependency Inversion:** z-test depends on the abstractions (a registry with ep_id/inv_id + ranking score + draft template), not on the concrete files.

## Files changed (summary)

| File | Action |
|------|--------|
| `skills/z-test/SKILL.md` | Full rewrite (dual-source pipeline) |
| `skills/z-test-invariant/SKILL.md` | New (archive of current z-test) |
| `docs/schemas/error_points.schema.json` | New |
| `docs/schemas/invariant.schema.json` | Edit (add 3 optional fields) |
| `docs/ERROR_POINTS.json` | New (empty + init bootstrap) |
| `scripts/validate-error-points.py` | New |
| `scripts/validate-invariants.py` | Edit (accept new fields) |
| `skills/z-review-all/SKILL.md` | Edit (extend Phase 5.5) |
| `AGENTS.md` | Edit (z-test routing description) |
| 9 files total | 5 new, 4 edited |
