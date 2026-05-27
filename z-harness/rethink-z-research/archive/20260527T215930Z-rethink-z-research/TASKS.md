# TASKS — rethink-z-research v1

## T001: Write `agents/research-judge.md`
**Files:** `agents/research-judge.md` (new).
**Dependencies:** none.
**Acceptance criteria:**
- Frontmatter: `name: research-judge`, `model: opus`, `tools: Read`, description per SPEC.
- Documents inputs (host_run_id, slug, perspectives array, map_path, brainstorm_path, output_schema_version).
- Documents procedure: read perspectives + sources → extract approaches/constraints → build matrix → cite per cell or mark UNVERIFIED → synthesize 10 sections.
- Hard invariants: read-only; FORBIDDEN from new design recommendations; cite or UNVERIFIED.
- Handles `panel_perspective_count` < 3 (panel_degraded mode per SPEC).
- Self-checks output for stripped new-design proposals; emits `research_judge_temptation` in return notes.
- Status `[ ]`
**Complexity:** high
**DOCS:** agents

## T002: Document RESEARCH.md schema in research-judge.md
**Files:** `agents/research-judge.md` (extend body).
**Dependencies:** T001.
**Acceptance criteria:**
- Documents frontmatter fields verbatim per SPEC: `artifact: research`, `artifact_kind: approach_synthesis`, `schema_version: 1`, `slug`, `generated_at`, `command`, `dispatch_decision`, `source_artifacts` (with sha + generated_at per artifact), `synthesizer_models`, `status`, `tripwires_fired`.
- Documents 10 body sections in order (matrix first; mechanical rank-ordering last — explicit "no recommendation language" rule).
- Documents matrix cell format: `<VERDICT>: <citation>` with verdict enum.
- Status `[ ]`
**Complexity:** low
**DOCS:** agents

## T003: Rename `commands/z-research.md` → `commands/z-map.md`
**Files:** `commands/z-research.md` → `commands/z-map.md` (rename + content edits).
**Dependencies:** none.
**Acceptance criteria:**
- `git mv commands/z-research.md commands/z-map.md`.
- Frontmatter `name:` updated from `z-research` → `z-map`.
- Description updated: "Maps terrain with citations + cross-LLM critique. No recommendations — terrain only. See `/z-research` for synthesis across map + brainstorm."
- All in-file references to RESEARCH.md changed to MAP.md.
- All in-file mentions of "/z-research" command name changed to "/z-map".
- Preserve the `## No-recommendation invariant` section verbatim.
- Update `argument-hint` if it mentions the artifact name.
- Status `[ ]`
**Complexity:** low
**DOCS:** commands

## T004: Rename `skills/z-research/SKILL.md` → `skills/z-map/SKILL.md`
**Files:** `skills/z-research/SKILL.md` → `skills/z-map/SKILL.md` (rename + content edits).
**Dependencies:** none.
**Acceptance criteria:**
- `git mv skills/z-research/ skills/z-map/`.
- SKILL.md frontmatter + content updated to match `commands/z-map.md` (same edits as T003).
- Status `[ ]`
**Complexity:** low
**DOCS:** skills

## T005: Update `commands/z-plan.md` Setup step 9 (precontext detection + skip rules)
**Files:** `commands/z-plan.md` (edit).
**Dependencies:** T002 (need the schema defined first), T003 (need MAP.md naming finalized).
**Acceptance criteria:**
- Setup step 9 detects MAP.md, BRAINSTORM.md, AND RESEARCH.md (currently only the latter two).
- Distinguishes RESEARCH.md by `artifact_kind` frontmatter:
  - `approach_synthesis` + `status: complete` → one-way gate active; inject ONLY RESEARCH.md.
  - `map` or no `artifact_kind` field → treat as legacy MAP.md; component-file injection.
  - `incomplete` → halt + recommend re-running /z-research.
- Phase 1 skip rules rewritten:
  - One-way gate active: skip doc-fetcher iff matrix has ≥1 OK/RISKY cell citing touched file; skip Explore iff Evidence gaps section empty.
  - Gate inactive: existing Findings/Open-questions logic unchanged.
- Freshness check for MAP.md uses same regex + mtime logic as existing RESEARCH.md check.
- Status `[ ]`
**Complexity:** medium
**DOCS:** commands

## T006: Update `agents/planning-router.md` (new reason codes + deprecation alias)
**Files:** `agents/planning-router.md` (edit).
**Dependencies:** T003.
**Acceptance criteria:**
- Add reason codes: `needs_terrain_map` (recommends `/z-map`), `needs_approach_synthesis` (recommends new `/z-research`).
- `needs_research` becomes a deprecated alias for `needs_terrain_map` for one version cycle. Documented deprecation note in the agent body.
- Decision rules: previous logic recommending `/z-research` for "terrain uncertain" now recommends `/z-map`. New rule: if `signals_json.has_map_and_brainstorm: true` AND `signals_json.approach_uncertain: true` → recommends `/z-research`.
- Status `[ ]`
**Complexity:** low
**DOCS:** agents

## T007: Update sub-command Setup to honor `$Z_HARNESS_PARENT_RUN_ID`
**Files:** `commands/z-map.md` + `commands/z-brainstorm.md` + `skills/z-map/SKILL.md` + `skills/z-brainstorm/SKILL.md` (edits).
**Dependencies:** T003, T004.
**Acceptance criteria:**
- Setup phase reads `$Z_HARNESS_PARENT_RUN_ID` and `$Z_HARNESS_PARENT_COMMAND` env vars (if set).
- When set, all subsequent log-event.sh payloads from the sub-command include `parent_run_id` and `parent_command` fields.
- Backward compatible: env vars absent → no attribution fields, same as today.
- Documented in both command and skill files.
- Status `[ ]`
**Complexity:** medium
**DOCS:** commands, skills

## T008: Update `commands/z-brainstorm.md` Phase 1c ingestion
**Files:** `commands/z-brainstorm.md` + `skills/z-brainstorm/SKILL.md` (edits).
**Dependencies:** T003.
**Acceptance criteria:**
- Phase 1c (RESEARCH.md ingestion) renamed to "MAP.md ingestion."
- Reads MAP.md (renamed) first.
- Backward-compat: if MAP.md absent, check for legacy `RESEARCH.md` with `artifact_kind: map` (or no artifact_kind) → treat as MAP.md.
- Explicitly skip new RESEARCH.md with `artifact_kind: approach_synthesis` (not useful as brainstorm scaffolding).
- Status `[ ]`
**Complexity:** low
**DOCS:** commands, skills

## T009: Write `commands/z-research.md` (NEW orchestrator)
**Files:** `commands/z-research.md` (new file, replacing the renamed one).
**Dependencies:** T001, T002, T003, T004, T007.
**Acceptance criteria:**
- Frontmatter per SPEC: `name: z-research`, description (meta-orchestrator), `argument-hint`.
- Phase 0 (dispatch decision): reads MAP_STATE + BRAINSTORM_STATE via freshness algorithm (git log timestamp vs frontmatter generated_at); uses 4-bucket decision matrix; AskUserQuestion with strong-default; logs `research_dispatch_decision`.
- Phase 0.5 (cost gate): estimate computed from dispatch_decision; AskUser proceed/change/abandon; logs `research_cost_gate_decision`.
- Phase 1 (subcommand dispatch): sets `Z_HARNESS_PARENT_RUN_ID` + `Z_HARNESS_PARENT_COMMAND` env vars; dispatches /z-map and/or /z-brainstorm via Agent(); extracts sub-run id from emitted events; creates symlink `archive/$RUN/subruns/<sub>` → `archive/<sub-run>/`; logs `research_subcommand_complete`.
- Phase 2 (adversarial panel): dispatches general-purpose (Opus) + consultant-primary + consultant-secondary in parallel via single message; each with perspective-specific MODE prompt; handles 1/3 + 2/3 + 3/3 fail per /z-brainstorm pattern; provider-unavailable counted as fail; captures per-perspective return to `archive/$RUN/panel/<perspective>.md`.
- Phase 3 (judge): dispatches `research-judge` Agent with paths; writes RESEARCH.md atomically (tmp+rename); logs `research_judge_complete`.
- Phase 4 (finalize): self-check; automated tripwire evaluation (`research_high_unverified_rate`, `research_panel_degraded`, `research_judge_temptation`); push-notify with `/z-plan` recommendation.
- Status `[ ]`
**Complexity:** high
**DOCS:** commands

## T010: Write `skills/z-research/SKILL.md` (NEW orchestrator)
**Files:** `skills/z-research/SKILL.md` (new file, replacing the renamed one).
**Dependencies:** T009.
**Acceptance criteria:**
- Mirror of `commands/z-research.md` in skill format (phases + procedure).
- Same Phase 0/0.5/1/2/3/4 structure.
- Status `[ ]`
**Complexity:** medium
**DOCS:** skills

## T011: Update routing references in other commands
**Files:** `commands/z-uplift.md`, `commands/z-do.md`, `commands/z-plan-light.md`, `commands/z-plan-split.md` (edits).
**Dependencies:** T003, T006.
**Acceptance criteria:**
- Replace `/z-research` mentions that pointed to OLD terrain-mapping behavior with `/z-map`.
- Any new references to meta-orchestrator stay `/z-research`.
- Reason code references updated: `needs_research` → `needs_terrain_map` (or `needs_approach_synthesis` if context fits).
- Status `[ ]`
**Complexity:** low
**DOCS:** commands

## T012: Update INDEX.json + regenerate agents docs
**Files:** `docs/llm/INDEX.json`, `docs/llm/agents.json`, `docs/human/agents.md`, `docs/llm/MEMORIES-FLAT.md` (regen via doc-updater).
**Dependencies:** T001, T002.
**Acceptance criteria:**
- INDEX.json `agents` concept entry: add `agents/research-judge.md` to source_files.
- Dispatch doc-updater (mode: write) for `agents` concept.
- Bump `last_updated` past current source mtimes (full datetime).
- Run `scripts/regenerate-memories-flat.py`.
- Status `[ ]`
**Complexity:** medium
**DOCS:** agents

## T013: Regenerate commands + skills docs
**Files:** `docs/llm/commands.json`, `docs/llm/skills.json`, `docs/human/commands.md`, `docs/human/skills.md` (regen).
**Dependencies:** T003, T004, T005, T006, T007, T008, T009, T010, T011.
**Acceptance criteria:**
- INDEX.json `commands` and `skills` concept entries: rename `z-research.md` → `z-map.md` in source_files; add new `z-research.md` (the orchestrator).
- Dispatch doc-updater (mode: write) for both concepts.
- Bump `last_updated`.
- Status `[ ]`
**Complexity:** medium
**DOCS:** commands, skills

## T014: Update README.md command catalogue
**Files:** `README.md` (edit).
**Dependencies:** T003, T009.
**Acceptance criteria:**
- Rename `/z-research` to `/z-map` in the catalogue for the terrain-mapping description.
- Add new `/z-research` entry describing the synthesis meta-orchestrator.
- Update any usage examples that mention `/z-research`.
- Status `[ ]`
**Complexity:** low
**DOCS:** commands

## T015: Regenerate IDE exports
**Files:** `exports/cursor/*`, `exports/codex/*`, `exports/agy/*`.
**Dependencies:** T013.
**Acceptance criteria:**
- Run `scripts/export-cursor.py`, `scripts/export-codex.py`, `scripts/export-agy.py`.
- Verify post-regen content matches the renamed commands/skills.
- Verify `.agent/workflows/z-research.md` and any related export files are regenerated correctly.
- Status `[ ]`
**Complexity:** low

## T016: Post-implementation rename verification grep
**Files:** none (verification only). May produce edits to any files showing missed references.
**Dependencies:** T003, T004, T005, T006, T007, T008, T009, T010, T011, T012, T013, T014, T015.
**Acceptance criteria:**
- Run `rg -n "/z-research|z-research|RESEARCH\\.md|needs_research" --type md --type json -g '!z-harness/**' -g '!docs/llm/MEMORIES-FLAT.md' -g '!exports/**' > /tmp/rename-leftover.txt`.
- Classify each hit: (a) NEW /z-research (orchestrator) — leave; (b) OLD /z-research terrain — must rename; (c) deprecated alias `needs_research` — leave with comment.
- Fix any class (b) misses inline.
- Re-run grep until class (b) hits = 0.
- Document any remaining class (a) and class (c) hits in archive note for audit.
- Status `[ ]`
**Complexity:** medium
