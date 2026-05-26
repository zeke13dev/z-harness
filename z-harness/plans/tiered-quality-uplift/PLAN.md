# PLAN — `/z-uplift`

## Goal
Ship a new top-level slash command `/z-uplift` that orchestrates one-time-or-on-demand bulk codebase quality uplift. Builds entirely on existing primitives (`auditor`, `consultant-primary`, `consultant-secondary`, `reviewer`, `/z-implement-all --tasks=` fast path, STYLE.md gate from `/z-mr-review`) — no new agents.

## Approved decisions (rationale from `archive/<run>/phase3-decisions-final.md`)
- **D1 sibling-plan layout**: each component becomes `z-harness/plans/<uplift-slug>-<component-slug>/{SPEC,PLAN,REPORT,TASKS}.md`. `/z-implement-all --tasks=` derives `$BASE` from the tasks file's parent dir, so the existing fast path Just Works.
- **D2 polyglot auto-detect + AskUser confirm**: parse Cargo workspace → pyproject/setup.cfg → package.json workspaces → top-level dir fallback; surface unclaimed dirs; CLI overrides `--components=<file>`, repeated `--component <path>`.
- **D3 reuse bundled consultants for cross-cutting** (no new agent): `consultant-primary` + `consultant-secondary` (provider-resolved at dispatch) on a curated source map + STYLE.md → `CROSS-CUTTING.md` with three-tier classification (`global-task` / `per-component-context` / `risk`).
- **D4 inline auditor dispatch** (no shell-out to `/z-audit`): `/z-uplift` directly dispatches `auditor` agents per (component × dimension), mirroring `/z-audit` Phases 2–6 in its outer loop. Intentional duplication; extract a shared subroutine when a third caller appears.
- **D5 inherit `/z-audit` bail thresholds** (>30 total or >10 CRIT-HIGH) per component; bailed components excluded from implement queue.
- **D6 sequential per-component `/z-implement-all`** with AskUser gates between each; synthetic `<slug>-cross-cutting` runs FIRST so global-task API changes precede per-component cleanup.
- **D7 MANIFEST.md is the resume authority**; no parallel state file. `--retry-bailed` / `--refresh-component <name>` flags.
- **D8 name = `/z-uplift`**.

## Non-goals
- Replacing `/z-audit` (single-component remains the right tool for ad-hoc).
- Replacing `/z-mr-review` (branch-diff scope is different).
- Polyglot dep graph (text-grep is the fallback).
- Per-component git-worktree isolation (main tree may be transiently un-buildable between gates).

## Approved shortcuts (explicit user approval at Phase 5)
- **No real dep graph on bail** — text-grep across other components for the bailed component's basename. Misses reflection / string-based references.
- **No git-worktree-per-component build isolation** — main tree may be transiently un-buildable between AskUser gates if a `global-task` API change isn't sequenced ahead of dependents. Mitigated (not eliminated) by processing `<slug>-cross-cutting` FIRST.

## Late addition (Phase 6 user request)
- **STYLE.md gate at Setup** (same shape as `/z-mr-review`): if `./STYLE.md` is missing, halt and recommend `/z-style-init`. `--no-style` flag bypasses the gate (cleanliness+design audits fall back to generic rubric). STYLE.md content is injected as authoritative rubric into per-component `cleanliness`/`design` auditor prompts and as critique input to the cross-cutting pass.

## DRY / KISS / SOLID alignment
- **DRY**: zero new agent files; reuses `auditor`, `consultant-primary`, `consultant-secondary`, `reviewer`, and `/z-implement-all --tasks=`. Reuses `/z-mr-review`'s STYLE.md gate pattern.
- **KISS**: no dep graph, no state JSON, no worktree isolation, no new agents.
- **SOLID**: orchestration / per-dimension audit / cross-LLM critique / implementation each owned by one layer.

## Ordered phases
1. **Foundation** — create `commands/z-uplift.md` skeleton (Setup, STYLE gate, phase headers, CLI flag parsing).
2. **Decomposition** — Phase 1 implementation: polyglot detection inline-python, COMPONENTS.md emission, AskUser gate, override flags, slug collision handling.
3. **Cross-cutting pass** — Phase 2 implementation: source-map curation, parallel consultant dispatch, three-tier classification merge into CROSS-CUTTING.md, synthetic `<slug>-cross-cutting` plan-dir creation when global-tasks exist.
4. **Per-component audit loop** — Phase 3 implementation: per-component output dir scaffolding (`<uplift-slug>-<component-slug>/SPEC.md`, `PLAN.md`), parallel auditor dispatch with STYLE.md (via `rubric_path`) + cross-cutting context injection, bundled consultant critique on REPORT.md, auto-bail check, text-grep dependents reporting, TASKS.md promotion, `reviewer` gate, MANIFEST state updates.
5. **Implement loop** — Phase 5 implementation: per-component AskUser gates, `/z-implement-all --tasks=` dispatch, MANIFEST state updates, abort handling. Process synthetic `<slug>-cross-cutting` first.
6. **MANIFEST + telemetry** — MANIFEST.md schema, state machine, resume logic for re-invokes, component-specific telemetry events, `--retry-bailed` / `--refresh-component` flag wiring.
7. **Docs + exports** — `docs/llm/INDEX.json` entry, `docs/llm/z-uplift.json`, `docs/human/z-uplift.md`, `skills/z-uplift/SKILL.md`, `README.md` update.
8. **Export to other IDEs** — `scripts/export-cursor.py`, `scripts/export-codex.py`, `scripts/export-agy.py` enumerate the new command; verify `Agent()` limitation comments render correctly for cursor/codex.
9. **Smoke test** — run `/z-uplift --no-style --cross-cutting=skip --component scripts` against this repo as a single-component dry run; verify decomposition output, auditor dispatch, REPORT/TASKS generation, MANIFEST state machine.

## Amendments

- **2026-05-26** (RUN 20260526T030246Z-amend-tiered-quality-uplift) — applied PLAN_AUDIT_REPORT.md blockers + majors. Agent name renames (`z-harness:gemini-consultant` / `codex-consultant` / `codex-reviewer` → `consultant-primary` / `consultant-secondary` / `reviewer`), auditor rubric contract fix (`rubric_path` not inline content), T003 path-computation fix (drop JS regex), T008 skill-pattern retarget (`skills/z-improve/` not missing `z-audit/`), STYLE-gate halt instruction, drop "edit-and-confirm" gate, define entry-file heuristic, `--dimensions` rationale surfaced, T006 `[i] implementing` resume + `--refresh-component` backup, T010 cleanup converted to manual, text-grep dependents labeled incomplete. No new tasks, no completed work disturbed, no consult required.
