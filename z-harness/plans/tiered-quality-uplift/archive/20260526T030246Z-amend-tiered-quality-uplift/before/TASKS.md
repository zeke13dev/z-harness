# TASKS — `/z-uplift`

Plan slug: `tiered-quality-uplift`. SPEC.md and PLAN.md live alongside this file. All paths absolute or repo-relative to `/Users/zeke/dev/z-harness`.

---

### [ ] T001 — Create commands/z-uplift.md skeleton with Setup + STYLE.md gate + CLI flags
- Create `commands/z-uplift.md` with full frontmatter (model: opus per /z-plan/audit convention), phase outline (Setup, Phase 0-6), CLI flag parsing block (`--components=<file>`, repeatable `--component <path>`, `--retry-bailed`, `--refresh-component <name>`, `--dimensions=<csv>` default `correctness,cleanliness,design`, `--cross-cutting=skip`, `--no-style`).
- Setup block: derive uplift slug from arguments (auto-derive kebab-case from first 2-4 words; AskUser confirm if non-obvious); resolve `$Z_HARNESS_PLAN_DIR`; pick RUN id; `mkdir -p archive/$RUN/transcripts`; log `run_start` with version blob; log providers (guarded); doc-staleness route check (same shape as `/z-plan`).
- STYLE.md gate immediately after Setup: `if [ ! -f ./STYLE.md ] && [ "$NO_STYLE" != "true" ]; then push-notify + AskUser (run /z-style-init / continue with --no-style next time / abort); log style_md_missing; halt cleanly if user picks /z-style-init`.
- Phase headers + one-paragraph description per phase (full per-phase content lands in later tasks).
- **Files:** `commands/z-uplift.md` (added)
- **Depends on:** none
- **Acceptance:** file exists, parses as valid markdown, contains all 7 CLI flags and the STYLE gate AskUser branch; `bash -n` on any embedded shell heredocs passes.
- **Complexity:** medium

### [ ] T002 — Implement Phase 1 (decomposition): polyglot detection + COMPONENTS.md + AskUser gate
- Inline python heredoc in `commands/z-uplift.md` Phase 1 that: (a) parses `Cargo.toml` `[workspace] members` (handles glob entries via `glob.glob`); (b) parses `pyproject.toml` `tool.poetry.packages` and `project.packages` via `tomllib`; (c) parses `setup.cfg` `[options] packages` via `configparser`; (d) parses `package.json` `workspaces` via `json`; (e) enumerates top-level non-hidden dirs minus denylist (`docs/`, `target/`, `node_modules/`, `dist/`, `build/`, `.git/`, `z-harness/`, `__pycache__/`, `.venv/`) and reports as `top-level-fallback`; (f) computes "unclaimed" = top-level non-denylist dirs not covered by (a)-(d).
- Compute path-derived kebab-case slug per component (basename lowercased, non-alnum→`-`); detect collisions; if any, AskUser to disambiguate per pair (offer suffix options).
- Write `$Z_HARNESS_PLAN_DIR/COMPONENTS.md` with table (Component, Path, Detection method, Slug) + Unclaimed section + edit instructions.
- Push-notify + AskUser: "Decomposition ready — review COMPONENTS.md and confirm" (proceed / abort / edit-and-confirm).
- Honor `--components=<file>` (skip auto-detect, read newline-delimited paths) and `--component <path>` (append to detected set).
- Emit `component_detected` event per row.
- **Files:** `commands/z-uplift.md` (modified)
- **Depends on:** T001
- **Acceptance:** Phase 1 heredoc, run against this repo (which has no Cargo.toml/pyproject.toml at root), produces COMPONENTS.md with all top-level dirs (commands, agents, skills, scripts, etc.) listed via `top-level-fallback`. Slug collisions trigger AskUser. CLI override flags work.
- **DOCS:** z-uplift
- **Complexity:** medium

### [ ] T003 — Implement Phase 2 (cross-cutting pass): consultant dispatch + 3-tier classification
- Phase 2 heredoc curates a source map: `git log --since="90 days ago" --name-only --format= | sort | uniq -c | sort -rn | head -50` (top-50 by churn) UNION first README/entry file per component (from COMPONENTS.md). Cap at ~100 paths.
- Dispatch `gemini-consultant` + `codex-consultant` in parallel (single message, two `Agent(...)` calls) with `MODE: cross-cutting-uplift` prompt: pass COMPONENTS.md verbatim, source map paths, STYLE.md content (if present), and ask for findings classified as `global-task` / `per-component-context` / `risk`.
- Merge returns into `$Z_HARNESS_PLAN_DIR/CROSS-CUTTING.md` with three sections (Global tasks, Per-component context, Risks). Default any unclassified finding to `per-component-context`. Style-drift findings cite STYLE rule IDs explicitly.
- If `global-task` count > 0: create `$Z_HARNESS_PLAN_DIR.replace(/<slug>$/, '<slug>-cross-cutting')/{SPEC.md,PLAN.md,TASKS.md}` (minimal SPEC pointing at CROSS-CUTTING.md; TASKS.md generated one-task-per-G-NNN with aggregated `**Files:**` lines); insert as the FIRST row in MANIFEST.md.
- Honor `--cross-cutting=skip` (write empty CROSS-CUTTING.md with note, skip dispatch, no synthetic component).
- Emit `cross_cutting_classified` event with counts.
- **Files:** `commands/z-uplift.md` (modified)
- **Depends on:** T002
- **Acceptance:** dispatch shape matches `/z-audit` Phase 4 (two parallel `Agent()` calls in one message); CROSS-CUTTING.md has the three required sections; synthetic plan dir is created only when `global-task > 0`; `--cross-cutting=skip` short-circuits cleanly.
- **REMOTE_VERIFY:** (n/a — markdown spec, no compile target)
- **Complexity:** medium

### [ ] T004 — Implement Phase 3 (per-component audit loop) with STYLE injection + cross-cutting context + bail
- For each component in MANIFEST `pending` state (excluding the synthetic `<slug>-cross-cutting` if it exists — that's audited differently, since it's hand-written):
  - Mark MANIFEST state `[~] auditing`. Emit `component_audit_start`.
  - Create per-component plan dir `z-harness/plans/<uplift-slug>-<component-slug>/` with minimal `SPEC.md` (one-paragraph: "audit-derived uplift for `<component>`; findings in REPORT.md") and `PLAN.md` (goal: address all CRITICAL+HIGH findings).
  - Extract `per-component-context` rows from CROSS-CUTTING.md that reference this component (text-match on component slug AND path).
  - Dispatch `z-harness:auditor` agents per `--dimensions` value in parallel (single message, N `Agent(...)` calls). Prompt fields: `target_path: <component path>`, `dimension: <dim>`, `rubric: <STYLE.md content if dim in {cleanliness,design} and STYLE present, else generic>`, `cross_cutting_context: <per-component context rows>`.
  - Merge per-dimension findings into `<uplift-slug>-<component-slug>/REPORT.md`.
  - Bundled consult on REPORT.md (gemini-consultant + codex-consultant in parallel) for drops + additions; apply with "one reason it might be wrong" pushback.
  - Count CRITICAL+HIGH and total findings. If `total > 30 OR crit_high > 10`: mark MANIFEST `[!] bailed: crit_high_volume`; write REPORT.md with "BAILED — exceeds /z-audit thresholds" header; run `git grep -l "<component basename>" -- <other component paths>` and append "Dependents (text-grep):" section to REPORT.md and a `Dependents warnings` section to MANIFEST.md; skip TASKS.md generation; emit `component_audit_done` with `bailed: true`; continue.
  - Otherwise: promote actionable findings to `<uplift-slug>-<component-slug>/TASKS.md` in `/z-implement-all`-consumable format (use the same task block shape as `/z-audit` Phase 5).
  - Dispatch `z-harness:codex-reviewer` over the generated TASKS.md (mandatory). Re-edit on Blocker findings.
  - Mark MANIFEST state `[a] audited`. Emit `component_audit_done`.
- **Files:** `commands/z-uplift.md` (modified)
- **Depends on:** T003
- **Acceptance:** loop iterates components, per-component plan dir is created and structured correctly, auditor dispatch is parallel, STYLE.md is passed when dim ∈ {cleanliness,design} and STYLE present, cross-cutting context is extracted by string-match, bail threshold matches `/z-audit`'s, text-grep dependents reporting runs on bail.
- **DOCS:** z-uplift
- **Complexity:** high

### [ ] T005 — Implement Phase 4 (review gate) + Phase 5 (sequential implement loop)
- Phase 4: aggregate queue summary to user (component count, total tasks, bailed components, dependents warnings). Push-notify + present plain summary, no AskUser (just informational, leads into Phase 5).
- Phase 5: process synthetic `<uplift-slug>-cross-cutting` first (if present) THEN components in MANIFEST order with state `[a] audited`:
  - AskUser per component: "Implement `<component>` (N tasks) now? proceed / skip / abort uplift".
  - On proceed: invoke `/z-implement-all --tasks=z-harness/plans/<uplift-slug>-<component-slug>/TASKS.md`. Wait for completion (this is the orchestrator's existing pause point — `/z-implement-all` may itself compaction-pause; resume on next `/z-uplift` invocation picks up the same component if not yet `[x] done`).
  - Set MANIFEST `[i] implementing` before dispatch, `[x] done` on successful completion (detect by reading the dispatched TASKS.md and confirming all `[ ]` are `[x]`), `[s] skipped: user` on user-skip, leave-as-is on abort.
  - Emit `component_implement_start` / `component_implement_done` events.
- On abort: log `run_end status: aborted_by_user`; exit cleanly. Re-invoke resumes at the same MANIFEST row.
- **Files:** `commands/z-uplift.md` (modified)
- **Depends on:** T004
- **Acceptance:** synthetic cross-cutting component is processed first (or skipped cleanly if absent); per-component AskUser gates work; MANIFEST state transitions are atomic per component; abort leaves remaining MANIFEST rows unchanged.
- **Complexity:** medium

### [ ] T006 — MANIFEST.md schema + resume logic + --retry-bailed / --refresh-component flags
- Implement MANIFEST.md emission at end of Phase 1 (initial state: all rows `[ ] pending`, synthetic `-cross-cutting` row prepended if Phase 2 added it).
- Resume logic at Setup: parse existing MANIFEST.md (if present); identify next non-terminal state; jump to corresponding phase (audit if any `[ ] pending` or `[~] auditing` rows; implement if all are `[a] audited` or terminal). Emit `resume_detected` event.
- `--retry-bailed`: change `[!] bailed: …` rows back to `[ ] pending` at Setup, then proceed normally.
- `--refresh-component <name>`: at Setup, change the matching row (by slug) to `[ ] pending` and delete its `<uplift-slug>-<component-slug>/REPORT.md` and `TASKS.md` (preserve SPEC/PLAN); proceed normally.
- Atomic MANIFEST.md updates: read full file, mutate target row, write via tmpfile + `os.replace`.
- **Files:** `commands/z-uplift.md` (modified)
- **Depends on:** T005
- **Acceptance:** MANIFEST table updates row-by-row without corruption under simulated interrupts; resume detection works (delete a `[a] audited` row's TASKS.md and re-invoke → Phase 5 still picks it up; mark `[~] auditing` and re-invoke → Phase 3 redoes it); both flags mutate only the targeted rows.
- **Complexity:** high

### [ ] T007 — Telemetry events: full component lifecycle wiring
- Audit existing `commands/z-uplift.md` for all `log-event.sh` calls; ensure every phase emits `phase_end` with `{phase, name, wall_ms, user_wait_ms}` per the standard contract.
- Verify component-specific events listed in SPEC are all emitted: `component_detected`, `component_audit_start`, `component_audit_done`, `component_implement_start`, `component_implement_done`, `cross_cutting_classified`, `style_md_missing`, `resume_detected`.
- Add `user_wait_start` / `user_wait_end` bracketing every AskUser invocation.
- **Files:** `commands/z-uplift.md` (modified)
- **Depends on:** T006
- **Acceptance:** grep `commands/z-uplift.md` for `log-event.sh` returns ≥10 distinct event names matching the SPEC list; every AskUser block is wrapped by `user_wait_start`/`user_wait_end`.
- **Complexity:** medium

### [ ] T008 — Skill wrapper + docs concept entry + README listing
- Create `skills/z-uplift/SKILL.md` matching the `skills/z-audit/SKILL.md` pattern: name `z-uplift`, description triggers on phrases like "bulk codebase quality", "uplift the codebase", "audit the whole repo", "review every component"; instructs the model to invoke `/z-uplift` and surfaces the main CLI flags.
- Add entry to `docs/llm/INDEX.json`: slug `z-uplift`, source_file `["commands/z-uplift.md", "docs/human/z-uplift.md", "skills/z-uplift/SKILL.md"]`, last_updated today, confidence high, depends_on `["commands", "agents"]`, consumed_by `[]`, summary one line.
- Create `docs/llm/z-uplift.json` in canonical schema with entry_points (commands/z-uplift.md per-phase line anchors), invariants (from SPEC's invariants section), gotchas (from SPEC's gotchas section), empty memories[].
- Create `docs/human/z-uplift.md`: 2-3 paragraphs covering what it does, when to use it vs `/z-audit` and `/z-mr-review`, the STYLE.md prerequisite, how to interpret MANIFEST states. Cite `commands/z-uplift.md:<line>` for the key phases.
- Add `/z-uplift` to `README.md` in the command list (find the existing list pattern and append a one-line entry).
- Regenerate `docs/llm/MEMORIES-FLAT.md` via `python3 scripts/regenerate-memories-flat.py --repo-root .`.
- **Files:** `skills/z-uplift/SKILL.md` (added), `docs/llm/INDEX.json` (modified), `docs/llm/z-uplift.json` (added), `docs/human/z-uplift.md` (added), `README.md` (modified), `docs/llm/MEMORIES-FLAT.md` (modified)
- **Depends on:** T001
- **Acceptance:** INDEX.json is valid JSON, `z-uplift` concept resolvable by doc-fetcher; skill loads (verify via skill listing); README lists the new command; MEMORIES-FLAT.md regenerated without error.
- **DOCS:** z-uplift
- **Complexity:** medium

### [ ] T009 — Multi-IDE export: cursor + codex + agy
- Trigger `/z-export` for all three targets after T008 lands; verify that `commands/z-uplift.md` produces:
  - `exports/cursor/.cursor/rules/z-uplift.mdc` (with `Agent()` calls replaced by limitation comments via `_rewrite_body`).
  - `exports/codex/prompts/z-uplift.md` (with same `_rewrite_body` rewrites).
  - `exports/agy/.agent/workflows/z-uplift.md` (with workflow frontmatter, 250-char description limit honored).
- Verify `skills/z-uplift/SKILL.md` produces:
  - `exports/cursor/.cursor/rules/z-uplift-skill.mdc`
  - `exports/codex/prompts/z-uplift-skill.md`
  - `exports/agy/.agent/skills/z-uplift/SKILL.md`
- Verify `exports/codex/AGENTS.md` is regenerated (no change expected since no new agents added).
- Run `bash scripts/audit-tarball.sh` if applicable; confirm exit 0.
- **Files:** `exports/cursor/.cursor/rules/z-uplift.mdc` (added), `exports/cursor/.cursor/rules/z-uplift-skill.mdc` (added), `exports/codex/prompts/z-uplift.md` (added), `exports/codex/prompts/z-uplift-skill.md` (added), `exports/agy/.agent/workflows/z-uplift.md` (added), `exports/agy/.agent/skills/z-uplift/SKILL.md` (added), `exports/codex/AGENTS.md` (regenerated)
- **Depends on:** T008
- **Acceptance:** all six export artifacts exist; `Agent()` substrings in cursor/codex outputs are wrapped in limitation comments (not raw); agy workflow frontmatter description ≤250 chars.
- **Complexity:** medium

### [ ] T010 — Smoke test against this repo
- Invoke `/z-uplift --no-style --cross-cutting=skip --component scripts` from the z-harness repo root. Verify:
  - Setup phase: slug derived, RUN dir created under `z-harness/plans/`, providers logged.
  - STYLE gate: `--no-style` bypasses (no AskUser); `style_md_missing` event NOT emitted (gate skipped, not failed).
  - Phase 1: COMPONENTS.md emitted with only `scripts/` (overridden component); user confirms.
  - Phase 2: skipped (per `--cross-cutting=skip`); CROSS-CUTTING.md is the empty-skip placeholder; no synthetic component.
  - Phase 3: one component (`scripts`) audited via 3 auditors (`correctness`, `cleanliness`, `design`); REPORT.md generated under `z-harness/plans/tiered-quality-uplift-smoke-scripts/`; TASKS.md generated (or bail if scripts/ has too many findings); codex-reviewer pass runs.
  - Phase 4: queue summary printed.
  - Phase 5: AskUser per component fires; user picks "skip" to avoid actually modifying code in the smoke test; MANIFEST shows `[s] skipped: user` for scripts.
  - Cleanup: delete the smoke test plan dir after verification.
- This task is INTERACTIVE — implementer should pause for the user to drive AskUser responses.
- **Files:** none (test only; cleanup deletes ephemeral dirs)
- **Depends on:** T009
- **Acceptance:** all phases execute, all expected events appear in `archive/<RUN>/events.jsonl`, MANIFEST transitions correctly, no exceptions or unhandled error paths.
- **Complexity:** medium
