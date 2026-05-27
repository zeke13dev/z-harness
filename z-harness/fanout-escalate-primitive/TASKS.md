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
- Status `[x]` — done; reviewer clean
**Complexity:** low
**DOCS:** agents

## T002: Write `agents/scope-reconciler-audit.md` agent definition
**Files:** `agents/scope-reconciler-audit.md` (new).
**Dependencies:** T001.
**Acceptance criteria:**
- Frontmatter: `name: scope-reconciler-audit`, `model: sonnet`, `tools: Read, Grep, Glob`.
- Documents procedure: read N chunk findings → dedupe by (severity, normalized-evidence-line) → preserve dissent via `## Cross-chunk dissent` section → elevate cross-chunk patterns (≥2 chunks flag same issue → bump severity) → emit unified REPORT.md.
- Hard rule: never smooth over disagreement.
- Status `[x]` — done; cycle 3 wording-only fix accepted
**Complexity:** high
**DOCS:** agents

## T003: Write `agents/scope-reconciler-brainstorm.md` agent definition
**Files:** `agents/scope-reconciler-brainstorm.md` (new).
**Dependencies:** T001.
**Acceptance criteria:**
- Frontmatter: `name: scope-reconciler-brainstorm`, `model: sonnet`, `tools: Read`.
- Documents procedure: read N chunk BRAINSTORM.md files → concatenate framings under `## Chunk: <id>` headers → run cross-chunk anti-bias check → emit unified BRAINSTORM.md with `chosen_framing: pending`.
- Status `[x]` — done; cycle 2 clean
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
- Status `[x]` — done; cycle 2 clean
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
- Status `[x]` — done; reviewer clean
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
- **Cycle-2 fix:** remove unused `import os` from prior cycle-1 implementer attempt (sole blocker from review).
- Status `[x]` — done; cycle 2 trivial fix
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
- Status `[x]` — done; clean
**Complexity:** low

## T008: Add `--scope-from <chunk-spec>` flag to `/z-audit`
**Files:** `commands/z-audit.md` (edit).
**Dependencies:** T001, T004.
**Acceptance criteria:**
- New `--scope-from <chunk-spec>` argument documented in `argument-hint`.
- Flag **parsed at the TOP of /z-audit, BEFORE Setup** (slug derivation, doc-fetcher, version stamp, run_start). This is critical — recursive sub-flows must not pollute parent run's slug/events.
- Setup sanitizes `$ARGUMENTS` — `--scope-from <chunk-spec>` tokens stripped before slug derivation / doc-fetcher dispatch / target parsing.
- `<chunk-spec>` accepts: (a) bare chunk ID like `C1` resolved against parent run's SCOPE.json via `$Z_HARNESS_PARENT_RUN_ID` env var (path: `z-harness/<parent-slug>/archive/$Z_HARNESS_PARENT_RUN_ID/SCOPE.json`); or (b) absolute path with `#<chunk-id>` fragment (e.g. `/abs/path/SCOPE.json#C1`) for out-of-band invocation.
- When `--scope-from` is present, sets `SKIP_PHASE_0=true` immediately. Phase 0 is skipped entirely.
- Resolved chunk's `scope_hint` loaded into `$SCOPE_HINT`; Phase 1 uses it as the operative target.
- Anti-sprawl invariant is enforced by SKIP_PHASE_0 alone — no separate event needed. Sub-flows cannot recursively go HEAVY because Phase 0's HEAVY dispatch branch never executes.
- Status `[x]` — done; cycle 2 post-amend clean
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
- Status `[x]` — done; cycle 3 tight fix accepted
**Complexity:** high
**DOCS:** commands

## T010: Insert Phase 0 into `/z-brainstorm`
**Files:** `commands/z-brainstorm.md` (edit).
**Dependencies:** T001, T003, T004.
**Acceptance criteria:**
- New "## Phase 0 — Scope probe" block inserted as the **literal first action after Setup, BEFORE Plan Route Check, BEFORE Phase 1 scaffolding**. (Earlier draft "between Plan Route Check and Phase 1" was wrong — see PLAN.md Amendments section.)
- Block defines `AXIS_TAXONOMY=["per_vendor","per_framing"]`.
- Dispatches scope-probe, parses hybrid return per SPEC parser safety rule, writes SCOPE archive + live `SCOPE-brainstorm.json`.
- scope-probe dispatches doc-fetcher internally — Phase 0 does NOT need Phase 1's doc-fetcher to have run.
- HEAVY branch: dispatch N parallel `/z-brainstorm` sub-flows, passing `$Z_HARNESS_PARENT_RUN_ID`. Each sub-flow skips Phase 0 + Plan Route Check, scopes to its chunk's `scope_hint`, runs Phase 1 + Phase 2 + **Phase 3 (synthesis)** to produce its own `chunks/<chunk-id>/BRAINSTORM.md`. Skips its own Phase 4 (parent owns the user-pick gate).
- After sub-flows return, dispatch `scope-reconciler-brainstorm` to merge per-chunk BRAINSTORM.md files into top-level unified BRAINSTORM.md (chunk-major per T003's contract).
- HEAVY's parent-level Phase 4 chunk-selection branch is implemented separately in T016 (not in scope here).
- LIGHT/MEDIUM: pass through unchanged.
- Status `[x]` — done; cycle 2 post-SPEC-retraction clean
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
- Status `[x]` — done; timestamp bumped to full datetime
**Complexity:** medium
**DOCS:** agents

## T012: Refresh commands docs after /z-audit + /z-brainstorm edits
**Files:** `docs/llm/commands.json` (regenerate), `docs/human/commands.md` (regenerate).
**Dependencies:** T009, T010, T016.
**Acceptance criteria:**
- Run `/z-maintain-docs --scope commands --apply`.
- Both tiers reflect the new Phase 0 sections and the `--scope-from` flag.
- `last_updated` bumped.
- Status `[x]` — done; commands docs regenerated
**Complexity:** medium
**DOCS:** commands

## T013: Refresh scripts docs after calibration harness lands
**Files:** `docs/llm/scripts.json` (regenerate), `docs/human/scripts.md` (regenerate).
**Dependencies:** T006, T007.
**Acceptance criteria:**
- Run `/z-maintain-docs --scope scripts --apply`.
- `scripts/scope-probe-calibrate.py` and `scripts/CALIBRATION.md` documented in both tiers.
- Status `[x]` — done; reviewer skipped (mechanical doc regen)
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
- Status `[x]` — done; calibration data generated (stub dispatcher; Tripwire 2 fired as expected)
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
- Status `[x]` — done; signoff written; v1a SHIPPED, v1b GATED
**Complexity:** medium

## T016: Add HEAVY-mode chunk-selection branch to `/z-brainstorm` Phase 4
**Files:** `commands/z-brainstorm.md` (edit).
**Dependencies:** T010 (Phase 0 must exist first; this layers on top).
**Acceptance criteria:**
- `/z-brainstorm` Phase 4 (the final user-pick gate) gets a new branch that fires ONLY when SCOPE-brainstorm.json indicates `MODE: HEAVY` for this run.
- HEAVY branch presents user with a `(chunk_id, framing)` selection matrix: e.g. "C1: claude / C1: codex / C1: gemini / C2: claude / C2: codex / C2: gemini" (per chunk × per ideator).
- AskUserQuestion presents up to N×3 options (capped at 12 — if >12, present chunks first, then framing per picked chunk in a follow-up Q).
- User's pick is stored as `chosen_pair: {chunk_id, framing}` in the top-level unified BRAINSTORM.md frontmatter (replacing `chosen_framing: claude|codex|gemini` for HEAVY runs).
- LIGHT/MEDIUM Phase 4 unchanged — still picks claude/codex/gemini only.
- Document the picked-pair as the seed for any downstream `/z-plan` invocation.
- Status `[x]` — done; 3 inline fixes from review; #1 needs /z-plan update follow-up
**Complexity:** medium
**DOCS:** commands
