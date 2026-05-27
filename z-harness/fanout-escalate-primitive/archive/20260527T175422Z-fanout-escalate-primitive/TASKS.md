# TASKS — fanout-escalate-primitive v1a

## T001: Write `agents/scope-probe.md` agent definition
**Files:** `agents/scope-probe.md` (new).
**Dependencies:** none.
**Acceptance criteria:**
- Frontmatter: `name: scope-probe`, `description`, `tools: Read, Grep, Glob`, `model: haiku`.
- Documents the 5-step procedure (parse → walk 2-deep → count seams → optional doc-fetcher → emit manifest).
- Documents the hybrid output contract: line-prefix headers (`STATUS:`/`MODE:`/`AXIS:`/`CONFIDENCE:`/`REASON_CODES:`/`REASON:`) followed by exactly one fenced JSON block containing `{chunks, seams_counted, candidates_walked}`.
- Documents all stable `REASON_CODES` values per SPEC.
- Documents the three-state graceful degradation (high-confidence pick / low-confidence + warning / no-axis refuse).
- Documents hard rules including the parser safety rule and "never invent axes outside taxonomy."
- `axis_taxonomy` is documented as a required input parameter.
- Status `[ ]`
**Complexity:** low
**DOCS:** agents

## T002: Write `agents/scope-reconciler-audit.md` agent definition
**Files:** `agents/scope-reconciler-audit.md` (new).
**Dependencies:** T001.
**Acceptance criteria:**
- Frontmatter: `name: scope-reconciler-audit`, `model: sonnet`, `tools: Read, Grep, Glob`.
- Documents procedure: read N chunk findings → dedupe by (severity, normalized-evidence-line) → preserve dissent via `## Cross-chunk dissent` section → elevate cross-chunk patterns (≥2 chunks flag same issue → bump severity) → emit unified REPORT.md.
- Hard rule: never smooth over disagreement.
- Status `[ ]`
**Complexity:** high
**DOCS:** agents

## T003: Write `agents/scope-reconciler-brainstorm.md` agent definition
**Files:** `agents/scope-reconciler-brainstorm.md` (new).
**Dependencies:** T001.
**Acceptance criteria:**
- Frontmatter: `name: scope-reconciler-brainstorm`, `model: sonnet`, `tools: Read`.
- Documents procedure: read N chunk BRAINSTORM.md files → concatenate framings under `## Chunk: <id>` headers → run cross-chunk anti-bias check → emit unified BRAINSTORM.md with `chosen_framing: pending`.
- Status `[ ]`
**Complexity:** medium
**DOCS:** agents

## T004: Document SCOPE-*.json schema
**Files:** `agents/scope-probe.md` (extend its body OR add SCHEMA.md sidecar).
**Dependencies:** T001.
**Acceptance criteria:**
- Schema documented for both the live form (`z-harness/<slug>/SCOPE-<host>.json`, namespaced) and archive form (`z-harness/<slug>/archive/<RUN>/SCOPE.json`, run-scoped).
- Required fields: `host_command`, `slug`, `last_run_id`, `last_updated`, `mode`, `axis`, `confidence`, `reason_codes`, `chunks` (array), `seams_counted`, `candidates_walked`, `scope_probe_version`.
- Optional field: `dimensions_hint` (array; populated by LIGHT in /z-audit).
- Documents archive-first write order invariant.
- Status `[ ]`
**Complexity:** low

## T005: Write `scripts/CALIBRATION.md` with rubric v1
**Files:** `scripts/CALIBRATION.md` (new).
**Dependencies:** none.
**Acceptance criteria:**
- Frontmatter with `rubric_version: 1`, `applies_to: scope-probe-calibrate.py`.
- Body documents the `classify_ground_truth(manifest, events) → LIGHT|MEDIUM|HEAVY` function spec:
  - HEAVY if events contain any `escalation_*` event OR `manifest.tasks_total >= 16`.
  - LIGHT if `tasks_total <= 5` AND `tasks_complexity.high == 0` AND no `plan_route_decision` event.
  - MEDIUM otherwise.
- Tie-break: escalation event > tasks_complexity > tasks_total.
- Versioning policy documented (rubric_version bumps invalidate prior calibration epoch trend comparisons).
- Status `[ ]`
**Complexity:** low
**DOCS:** scripts

## T006: Write `scripts/scope-probe-calibrate.py` framework
**Files:** `scripts/scope-probe-calibrate.py` (new).
**Dependencies:** T005.
**Acceptance criteria:**
- CLI flags: `--archive-root`, `--epoch N`, `--n-runs N`, `--samples-per-run N`.
- Walks `z-harness/*/archive/*/` finding runs with `manifest.json`.
- Implements `classify_ground_truth(manifest, events)` per CALIBRATION.md.
- Scope-probe dispatch shim is a stub that reads a fixture file when `--fixture-mode` is passed (for unit tests in T007 before T001 ships).
- Confusion matrix + tripwire report output.
- Emits `scripts/calibration-epoch-<N>.json` per SPEC.
- Tripwire 1 (`pct_medium >= 70`) and Tripwire 2 (`pct_heavy < 20`) cause exit code 1.
- Status `[ ]`
**Complexity:** medium
**REMOTE_VERIFY:** python3 -c "import ast; ast.parse(open('scripts/scope-probe-calibrate.py').read())"
**DOCS:** scripts

## T007: Unit-test the calibration harness against synthetic fixtures
**Files:** `scripts/test-scope-probe-calibrate.py` (new) OR inline `if __name__ == '__main__'` test block.
**Dependencies:** T006.
**Acceptance criteria:**
- Synthetic fixtures: 3 fake archive runs with hand-crafted `manifest.json` + `events.jsonl` covering one each of LIGHT/MEDIUM/HEAVY ground-truth.
- `classify_ground_truth` matches expected output on all 3.
- Harness's confusion matrix correctly counts matches.
- Tripwire detection logic fires correctly on a synthetic "all MEDIUM" replay set.
- Test exits 0 on success, 1 on failure.
- Status `[ ]`
**Complexity:** low

## T008: Add `--scope-from <chunk>` flag to `/z-audit`
**Files:** `commands/z-audit.md` (edit).
**Dependencies:** T001, T004.
**Acceptance criteria:**
- New `--scope-from <chunk-id-or-path>` argument documented in `argument-hint`.
- When `--scope-from` is present, /z-audit skips Phase 0, reads `z-harness/<slug>/archive/<RUN>/SCOPE.json`, locates the named chunk, and operates only on that chunk's `scope_hint`.
- Sub-flows triggered via `--scope-from` cannot themselves go HEAVY (anti-sprawl invariant — refuse with `scope_recursive_heavy_refused` event).
- Status `[ ]`
**Complexity:** low
**DOCS:** commands

## T009: Insert Phase 0 into `/z-audit`
**Files:** `commands/z-audit.md` (edit).
**Dependencies:** T001, T002, T004, T008.
**Acceptance criteria:**
- New "## Phase 0 — Scope probe" block inserted between Setup and Phase 1.
- Block defines `AXIS_TAXONOMY=["per_dimension","per_component","per_risk_domain","per_workflow"]` and dispatches `Agent(subagent_type="scope-probe", ...)`.
- Parses hybrid return per SPEC parser safety rule.
- Writes archive copy first (atomic tmp+rename), then live `z-harness/<slug>/SCOPE-audit.json` overwrite.
- Branches: LIGHT populates `dimensions_hint`; MEDIUM passes through; HEAVY dispatches N parallel sub-flows via `--scope-from` and then `scope-reconciler-audit`.
- Phase 1 dimension-selection block edited to consult SCOPE.json's `dimensions_hint` FIRST and auto-confirm if populated. NO double-scoping.
- All `scope_probe_*` and `scope_fanout_*` events logged per SPEC D13.
- Status `[ ]`
**Complexity:** high
**DOCS:** commands

## T010: Insert Phase 0 into `/z-brainstorm`
**Files:** `commands/z-brainstorm.md` (edit).
**Dependencies:** T001, T003, T004.
**Acceptance criteria:**
- New "## Phase 0 — Scope probe" block inserted between Plan Route Check and Phase 1 scaffolding.
- Block defines `AXIS_TAXONOMY=["per_vendor","per_framing"]`.
- Dispatches scope-probe, parses return, writes SCOPE archive + live `SCOPE-brainstorm.json`.
- HEAVY branch: dispatches N parallel `/z-brainstorm` sub-flows; uses `scope-reconciler-brainstorm` for merge. LIGHT/MEDIUM: pass through unchanged.
- Status `[ ]`
**Complexity:** medium
**DOCS:** commands

## T011: Update INDEX.json to register 3 new agents
**Files:** `docs/llm/INDEX.json` (edit), `docs/llm/agents.json` (regenerate via doc-updater), `docs/human/agents.md` (regenerate).
**Dependencies:** T001, T002, T003.
**Acceptance criteria:**
- `agents` concept entry in INDEX.json adds `agents/scope-probe.md`, `agents/scope-reconciler-audit.md`, `agents/scope-reconciler-brainstorm.md` to `source_files`.
- Run `/z-maintain-docs --scope agents --apply` to regenerate the two-tier docs.
- `last_updated` field bumped past current source mtimes.
- MEMORIES-FLAT.md regenerated.
- Status `[ ]`
**Complexity:** medium
**DOCS:** agents

## T012: Refresh commands docs after /z-audit + /z-brainstorm edits
**Files:** `docs/llm/commands.json` (regenerate), `docs/human/commands.md` (regenerate).
**Dependencies:** T009, T010.
**Acceptance criteria:**
- Run `/z-maintain-docs --scope commands --apply`.
- Both tiers reflect the new Phase 0 sections and the `--scope-from` flag.
- `last_updated` bumped.
- Status `[ ]`
**Complexity:** medium
**DOCS:** commands

## T013: Refresh scripts docs after calibration harness lands
**Files:** `docs/llm/scripts.json` (regenerate), `docs/human/scripts.md` (regenerate).
**Dependencies:** T006, T007.
**Acceptance criteria:**
- Run `/z-maintain-docs --scope scripts --apply`.
- `scripts/scope-probe-calibrate.py` and `scripts/CALIBRATION.md` documented in both tiers.
- Status `[ ]`
**Complexity:** low
**DOCS:** scripts

## T014: Run calibration epoch 1 against current archive
**Files:** `scripts/calibration-epoch-1.json` (output), `z-harness/fanout-escalate-primitive/archive/<RUN>/calibration-stdout.log`.
**Dependencies:** T009, T010, T011, T012, T013 (all integration tasks done so the harness can dispatch real scope-probe calls).
**Acceptance criteria:**
- Command: `python3 scripts/scope-probe-calibrate.py --epoch 1 --n-runs 6 --samples-per-run 3`.
- Output JSON includes confusion matrix, pct_heavy, pct_medium, pct_light, per-run replay details with majority-vote classification.
- Stdout report cleanly indicates which (if any) tripwires fired.
- Note: this task NEVER auto-passes — its purpose is to GENERATE data for T015 to evaluate.
- Status `[ ]`
**Complexity:** high

## T015: Evaluate calibration epoch 1 + tune thresholds + manual gate signoffs
**Files:** `agents/scope-probe.md` (edit thresholds if needed), `z-harness/fanout-escalate-primitive/CALIBRATION-EPOCH-1-SIGNOFF.md` (new).
**Dependencies:** T014.
**Acceptance criteria:**
- Inspect epoch 1's confusion matrix. If mis-classifications cluster on threshold boundaries, propose tuned thresholds. If tuned, re-run as epoch 2.
- Document automated tripwires status (pass/fire) in `CALIBRATION-EPOCH-1-SIGNOFF.md`.
- Conduct manual gate A (synthesis quality on one HEAVY run): write findings to signoff doc.
- Conduct manual gate B (semantic vs structural axis): inspect REASON_CODES across replays; tally structural vs low-confidence/no-evidence; document tally.
- Signoff doc concludes with one of: `v1a SHIPPED, v1b GREENLIT`, `v1a SHIPPED, v1b NEEDS RESCOPE`, or `v1a NOT READY — failure mode <X>`.
- Status `[ ]`
**Complexity:** medium
