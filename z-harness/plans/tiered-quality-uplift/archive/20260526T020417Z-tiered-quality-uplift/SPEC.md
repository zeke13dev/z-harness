# SPEC — `/z-uplift`

Tiered codebase quality uplift command. Decomposes the repo into components, runs a repo-wide cross-cutting pass, dispatches per-component audits (reusing the `auditor` agent and bundled consultants), produces per-component TASKS.md files in sibling-plan layout consumable by `/z-implement-all --tasks=…`, then drives sequential per-component implementation behind AskUser gates.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/plans/tiered-quality-uplift/BRAINSTORM.md | n/a |
| RESEARCH.md | z-harness/plans/tiered-quality-uplift/RESEARCH.md | n/a |

None — fresh `/z-plan` run.

## Goals
- One-time-or-on-demand bulk quality uplift for codebases adopting z-harness.
- Cross-cutting findings surfaced once; per-component findings handled in self-contained plans.
- All work consumable via existing `/z-implement-all --tasks=` fast path; no new implementation orchestration.
- Idempotent + resumable; safe to interrupt and re-invoke.

## Non-goals
- Replacing `/z-audit` for ad-hoc single-component work — `/z-audit` remains.
- Replacing `/z-mr-review` for branch-diff quality review — different scope.
- Building a polyglot dep graph; text-grep is the fallback for dependency hints.
- Per-component git-worktree isolation; main tree may be transiently un-buildable between gates.

## Files

### `commands/z-uplift.md` (new)
Slash command spec. Phases:
- **Setup** — derive uplift slug, resolve `$Z_HARNESS_PLAN_DIR = z-harness/plans/<slug>` (parent), pick RUN id, log `run_start`, log providers, doc-staleness gate via the standard route-check pattern.
- **Setup gate — STYLE.md required** — check for `./STYLE.md` at repo root (same gate as `/z-mr-review`). If absent, push-notify and AskUser: "Run `/z-style-init` first (recommended) / continue without STYLE (cleanliness+design audits degrade to generic rubric) / abort." If the user continues without STYLE.md, log `style_md_missing` event and disable STYLE-rubric injection into auditors. If `/z-style-init` chosen, halt the run cleanly (do NOT auto-invoke) and instruct user to re-invoke `/z-uplift` afterward — same handoff pattern as the docs-staleness gate.
- **Phase 0 — Premise check** — same shape as `/z-plan` Phase 0; one-paragraph "goal accepted" if no concern surfaces.
- **Phase 1 — Decomposition** — auto-detect components (see "Component detection" below); write `COMPONENTS.md` preview; AskUser gate; honor `--components=<file>` / `--component <path>` overrides; collision detection with AskUser disambiguation.
- **Phase 2 — Cross-cutting pass** — dispatch `gemini-consultant` + `codex-consultant` in parallel on a curated source map AND STYLE.md (if present); merge findings into `CROSS-CUTTING.md` with three-tier classification (`global-task` / `per-component-context` / `risk`). Style-drift findings are explicitly called out (cite STYLE.md rule IDs). `global-task` items become a synthetic component named `<slug>-cross-cutting` inserted FIRST in MANIFEST.
- **Phase 3 — Per-component audits** — for each component in MANIFEST order: dispatch `auditor` agents per dimension in parallel (mirroring `/z-audit` Phases 2–6 inline); inject STYLE.md as the authoritative rubric for `cleanliness` and `design` dimensions (if STYLE.md present); read CROSS-CUTTING.md `per-component-context` entries as additional input; produce per-component `REPORT.md` + `TASKS.md` in sibling plan dir `z-harness/plans/<slug>-<component>/`; inherit `/z-audit`'s >30-findings / >10-CRIT-HIGH auto-bail; on bail, run cheap text-grep across other components for the bailed component's symbols/paths and warn user. Update MANIFEST per-component state after each.
- **Phase 4 — Review gate** — present the aggregated queue summary to user (component count, total tasks, bailed components, dep warnings).
- **Phase 5 — Sequential implement** — for each non-bailed component in MANIFEST order: AskUser gate (proceed / skip / abort); invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`; update MANIFEST state to `[x] done` on success.
- **Phase 6 — Finalize** — log `run_end`, push-notify, recommend `/z-maintain-docs` if any task carried a `**DOCS:**` line.

CLI flags:
- `--no-style` — bypass the STYLE.md gate (cleanliness+design audits fall back to generic rubric). Default behavior is to halt if STYLE.md is missing.
- `--components=<file>` — path to a newline-delimited list of component paths, bypasses auto-detection.
- `--component <path>` (repeatable) — explicitly include one component path.
- `--retry-bailed` — on re-invoke, re-attempts components in `bailed` state.
- `--refresh-component <name>` — re-runs audit for one component (overwrites its REPORT/TASKS); does NOT touch other components.
- `--dimensions=<csv>` — pass-through to per-component audit (default: correctness,cleanliness,design; `perf` excluded by default to keep uplift scope bounded).
- `--cross-cutting=skip` — skip Phase 2 (escape hatch for tiny repos).

### `commands/z-uplift.md` — output layout contract
```
z-harness/plans/<slug>/                              ← uplift root
├── COMPONENTS.md                                    ← decomposition preview (Phase 1)
├── CROSS-CUTTING.md                                 ← repo-wide findings (Phase 2)
├── MANIFEST.md                                      ← component table + state (resume authority)
├── archive/<RUN>/{events.jsonl,phase*.md,transcripts/}
└── (no SPEC/PLAN/TASKS at this root)

z-harness/plans/<slug>-cross-cutting/                ← synthetic component for global-task items (if any)
├── REPORT.md
├── TASKS.md
├── SPEC.md  (minimal: "address global-task findings from <slug>/CROSS-CUTTING.md")
└── PLAN.md

z-harness/plans/<slug>-<component>/                  ← one per real component
├── REPORT.md
├── TASKS.md
├── SPEC.md  (minimal: "audit-derived uplift for <component>; findings in REPORT.md")
└── PLAN.md
```

### Component detection (inline in `commands/z-uplift.md` Phase 1)
Implemented inline in the orchestrator (no new agent — fits in <30 lines of python). Order:
1. Parse `Cargo.toml` for `[workspace] members = […]`; resolve glob entries.
2. Parse `pyproject.toml` for `tool.poetry.packages` / `project.packages`; parse `setup.cfg` `[options] packages =`.
3. Parse `package.json` `"workspaces": […]`.
4. Top-level non-hidden dirs minus denylist (`docs/`, `target/`, `node_modules/`, `dist/`, `build/`, `.git/`, `z-harness/`, `__pycache__/`, `.venv/`).
5. Compute "unclaimed" set = top-level non-hidden dirs not covered by steps 1–4 AND not in denylist. Surface in COMPONENTS.md preview.
6. Slug collision check: any two components whose path-derived slug (basename, kebab-cased) match → AskUser disambiguates.

`COMPONENTS.md` shape:
```markdown
# Components detected — <slug>
| Component | Path | Detection method | Slug |
|-----------|------|------------------|------|
| crates/foo | crates/foo | cargo-workspace | foo |
| pkgs/api | pkgs/api | pyproject | api |
| ... |

## Unclaimed (not covered by any detection method)
- scripts/ — standalone scripts dir
- tools/ — utility binaries

To exclude a component: edit this file and remove its row before confirming.
To include an unclaimed dir: move its bullet into the table with method=`manual`.
```

### Cross-cutting pass (`commands/z-uplift.md` Phase 2)
Dispatch shape:
```
Agent(subagent_type="z-harness:gemini-consultant", description="Cross-cutting (Gemini)",
      prompt="MODE: cross-cutting-uplift\nrepo_root: <abs>\ncomponents: <COMPONENTS.md verbatim>\nsource_map: <top-50 files by churn over last 90 days, plus each component's entry file>\nAsk: list cross-component issues (duplicated abstractions, style drift, dead code at module boundaries, public-API drift). For each, classify as global-task | per-component-context | risk.")
Agent(subagent_type="z-harness:codex-consultant", description="Cross-cutting (Codex)", prompt="<same body>")
```

Merge into `CROSS-CUTTING.md`:
```markdown
# Cross-cutting findings — <slug>
## Global tasks (need dedicated plan)
- G-001 — [HIGH] <subject> — files: a, b, c
## Per-component context (inform audits)
- C-001 — affects <component-name> — <context>
## Risks (watch items)
- R-001 — <subject> — <evidence>
```

If `global-task` count > 0 → synthetic component `<slug>-cross-cutting` inserted at top of MANIFEST. Its TASKS.md is hand-written from `global-task` entries (one task per G-NNN), with `**Files:**` lines aggregating affected paths.

### Per-component audit (`commands/z-uplift.md` Phase 3)
For each component in MANIFEST `pending` state:
1. Mark MANIFEST state `[~] auditing`.
2. Dispatch one `z-harness:auditor` subagent per `--dimensions` value in parallel; prompt includes `target_path`, `dimension`, and `cross_cutting_context` (the verbatim `per-component-context` entries from CROSS-CUTTING.md that reference this component).
3. Merge per-dimension findings into `<slug>-<component>/REPORT.md`.
4. Bundled consult: `gemini-consultant` + `codex-consultant` in parallel on REPORT.md (drops + additions). Same shape as `/z-audit` Phase 4.
5. Auto-bail check: count CRITICAL+HIGH and total findings. If >10 CRIT-HIGH OR >30 total → mark MANIFEST `[!] bailed: crit_high_volume` (or `bailed: spec_problem` for STATUS: spec_problem from auditor); write partial REPORT.md; run cheap text-grep `git grep -l "<component-basename>"` across other components, append "Dependents (text-grep):" section to REPORT.md; skip TASKS.md generation; continue to next component.
6. Otherwise: promote findings to `<slug>-<component>/TASKS.md` in `/z-implement-all`-consumable format. Write minimal SPEC.md + PLAN.md.
7. Dispatch one `z-harness:codex-reviewer` over the generated TASKS.md (mandatory safety gate). On `Blocker`, re-edit in-place.
8. Mark MANIFEST state `[a] audited`.

### Sequential implement (`commands/z-uplift.md` Phase 5)
For each component with state `[a] audited`:
1. AskUser: proceed / skip this component / abort uplift.
2. If proceed: invoke `/z-implement-all --tasks=z-harness/plans/<slug>-<component>/TASKS.md`. Wait for completion.
3. On completion: mark MANIFEST `[x] done`.
4. On user-skip: mark MANIFEST `[s] skipped: user`.
5. On abort: mark MANIFEST state for this and remaining components left unchanged; log `run_end status: aborted_by_user`; exit.

Synthetic `<slug>-cross-cutting` is processed FIRST so any global-task API changes land before per-component cleanup.

### `commands/z-uplift.md` — MANIFEST.md shape
```markdown
# Uplift MANIFEST — <slug>

Generated: <iso>
Run: <run-id>
Detection: <auto | manual | mixed>

| State | Component | Slug | Audit findings | Bail reason | TASKS.md |
|-------|-----------|------|----------------|-------------|----------|
| [x] done | <slug>-cross-cutting | (global) | 4 (2 HIGH) | — | z-harness/plans/<slug>-cross-cutting/TASKS.md |
| [a] audited | crates/foo | foo | 8 (1 HIGH) | — | z-harness/plans/<slug>-foo/TASKS.md |
| [!] bailed | crates/legacy | legacy | 35 (12 CRIT) | crit_high_volume | (partial REPORT.md only) |
| [ ] pending | pkgs/api | api | — | — | — |

## Dependents warnings (post-bail)
- crates/legacy bailed; text-grep references found in: crates/foo, pkgs/api
```

States: `[ ] pending` `[~] auditing` `[a] audited` `[i] implementing` `[x] done` `[!] bailed: <reason>` `[s] skipped: <reason>`.

Resume: on re-invoke, orchestrator parses MANIFEST, identifies next non-terminal state, resumes at the matching phase (audit or implement). `--retry-bailed` and `--refresh-component <name>` mutate states accordingly.

### `commands/z-uplift.md` — telemetry contract
Standard `phase_end` events per phase. Component-specific events:
- `component_detected` — payload: `{slug, path, method, unclaimed: bool}`
- `component_audit_start` — `{component, dimensions}`
- `component_audit_done` — `{component, findings_total, findings_crit_high, bailed, bail_reason}`
- `component_implement_start` — `{component, task_count}`
- `component_implement_done` — `{component, completed, halted}`
- `cross_cutting_classified` — `{global_tasks, per_component_context, risks}`

### `agents/` — no new agents
Reuses existing: `auditor`, `gemini-consultant`, `codex-consultant`, `codex-reviewer`. No agent file additions.

### `scripts/export-cursor.py`, `scripts/export-codex.py`, `scripts/export-agy.py`
Add `z-uplift` to the enumerated source list. The shared `_rewrite_body` mechanism handles Agent() limitation comments per target.

### `scripts/export-agy.py` — `_ALWAYS_ON_AGENTS` set
No change. `z-uplift` is a command, not an agent. The agents it dispatches (`auditor`, `codex-reviewer`) are already in the always-on set; the consultants are model_decision per existing convention.

### `docs/llm/INDEX.json`
Add new concept entry:
```json
{
  "slug": "z-uplift",
  "source_file": ["commands/z-uplift.md", "docs/human/z-uplift.md"],
  "last_updated": "2026-05-25",
  "confidence": "high",
  "depends_on": ["commands", "agents", "z-audit", "skills"],
  "consumed_by": [],
  "summary": "Tiered bulk codebase quality uplift: decompose into components, repo-wide cross-cutting pass, per-component audits, sequential implement via /z-implement-all."
}
```

### `docs/llm/z-uplift.json` (new)
Canonical schema: entry_points, invariants, gotchas, empty memories[].

Invariants:
- STYLE.md gate runs at Setup (same shape as `/z-mr-review`'s STYLE gate); without `--no-style`, missing STYLE.md halts and recommends `/z-style-init`. With `--no-style`, audits proceed but cleanliness+design fall back to the generic rubric.
- STYLE.md content is injected as authoritative rubric into `cleanliness` and `design` `auditor` prompts; auditors cite STYLE rule IDs in findings.
- `commands/z-uplift.md` MUST mirror `/z-audit` Phases 2–6 inline (intentional duplication); divergence is a bug.
- Per-component output dir is `z-harness/plans/<uplift-slug>-<component-slug>/`; SPEC/PLAN/TASKS live there; `/z-implement-all --tasks=` reads SPEC/PLAN from that dir.
- MANIFEST.md is the resume authority; no parallel state file.
- Components processed sequentially in MANIFEST order; synthetic `-cross-cutting` first if it exists.
- Auto-bail thresholds match `/z-audit`'s (>30 total OR >10 CRIT-HIGH) per component; bailed components excluded from implement queue and not retried unless `--retry-bailed`.
- `auditor` agent is the only audit primitive; no shell-out to `/z-audit`.

Gotchas:
- Main tree may be transiently un-buildable between AskUser gates if a `global-task` API change lands and dependents are not yet updated; mitigated by processing `<slug>-cross-cutting` first.
- Text-grep dependency reporting on bail misses reflection / string-based imports.
- Polyglot detection misses unconventional layouts; `--components=<file>` is the escape hatch.
- COMPONENTS.md is read at AskUser confirmation; subsequent edits to that file after confirmation have no effect until `--refresh-component` or re-decompose.

### `docs/human/z-uplift.md` (new)
2–3 paragraphs: what the command does, when to use it (legacy codebase adopting z-harness; quarterly cleanup), how it differs from `/z-audit` (single-component) and `/z-mr-review` (branch-diff). File:line citations into `commands/z-uplift.md`.

### `skills/z-uplift/SKILL.md` (new)
Skill wrapper matching the existing `skills/z-audit/SKILL.md` pattern: name, description triggering on "bulk codebase quality" / "uplift" / "audit the whole repo" phrases; instructs the model to invoke `/z-uplift` and surfaces flags.

### `README.md`
Add `/z-uplift` to the command list with one-line description.

## Behavior invariants
- Idempotent: re-invoking `/z-uplift` with no flags resumes at the next non-terminal MANIFEST state.
- Read-only during Phase 1–4; only Phase 5 (`/z-implement-all` dispatches) writes code.
- Per-component output paths never collide across uplift runs because slug includes both uplift-slug and component-slug.
- No automatic retry of bailed components — `--retry-bailed` is explicit user opt-in.
- Cross-cutting pass is skippable via `--cross-cutting=skip`; default ON.

## DRY / KISS / SOLID
- **DRY:** Reuses `auditor`, `gemini-consultant`, `codex-consultant`, `codex-reviewer` agents — no new agent files. Reuses `/z-implement-all --tasks=` fast path verbatim. Intentional duplication of `/z-audit` Phases 2–6 inline is the SOLID/single-caller exception (extract when a third caller appears).
- **KISS:** No dep graph (text-grep), no git-worktree isolation, no parallel state file, no new agents, no new orchestration primitives. Sibling-plan layout reuses existing `/z-implement-all` discovery; no path special-casing.
- **SOLID:** `/z-uplift` does decomposition + orchestration. `auditor` does dimension-scoped finding. Consultants do critique. `/z-implement-all` does implementation. Single responsibility per layer.

## Edge cases
- Repo with no detectable components (no Cargo/pyproject/package.json, only one top-level src/) → COMPONENTS.md shows the single src/ as a fallback component; user can `--component <subpath>` to subdivide.
- All components bail → MANIFEST shows nothing in `[a] audited` state; Phase 5 has nothing to do; recommend user run `/z-plan` on the bailed components individually.
- User re-invokes mid-implement (Ctrl-C during Phase 5) → MANIFEST shows last component `[i] implementing`. Re-invoke detects this, asks user: resume with `/z-implement-all` on this component / mark `[s] skipped` / mark `[x] done` (if they finished manually) / abort.
- Slug collision (two components with identical basename) → AskUser disambiguates at Phase 1; user picks a suffix per component.
- Empty repo (no top-level dirs after denylist) → error out at Phase 1 with "no components detected; pass --component <path>".
