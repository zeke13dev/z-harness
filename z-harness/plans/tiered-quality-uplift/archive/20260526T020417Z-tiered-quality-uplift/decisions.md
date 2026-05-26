# Decisions — `/z-uplift`

Goal: new top-level command for one-time-or-on-demand bulk codebase quality uplift, layered over `auditor`, `consultant-*`, `reviewer` agents and `/z-implement-all --tasks=`.

---

## D1 — Output layout / plan-dir shape
- **Decision:** Where does `/z-uplift` write its artifacts so per-component TASKS.md files are individually consumable by `/z-implement-all --tasks=…`.
- **Options:**
  - (a) `z-harness/plans/<slug>/components/<comp>/{REPORT.md,TASKS.md}` — single uplift run, components are children.
  - (b) `z-harness/plans/<slug>/` flat with `TASKS-<comp>.md` files — flat namespace.
  - (c) `z-harness/plans/<slug>-<comp>/{REPORT.md,TASKS.md,SPEC.md,PLAN.md}` — each component is its own full sibling plan, uplift writes a parent MANIFEST.
- **Tentative call:** (c). `/z-implement-all --tasks=<path>` derives `$BASE` from the tasks file's parent dir and reads SPEC/PLAN from `$BASE`. Option (a) would force a shared SPEC/PLAN at the uplift root, which doesn't match (each component has its own scope). Option (c) keeps each component a self-contained, resumable, archive-able plan. Parent `<slug>/MANIFEST.md` lists children.
- **Consult? yes** — Trigger: new public surface (directory layout is hard to rename later) + cross-module (affects how `/z-implement-all`, `/z-stats`, `/z-review-all` discover and report on uplift work).

## D2 — Component decomposition strategy
- **Decision:** How does `/z-uplift` auto-detect components before the user confirms.
- **Options:**
  - (a) Polyglot detection: parse `Cargo.toml` workspace members, `pyproject.toml`/`setup.cfg` packages, `package.json` workspaces, fall back to top-level non-hidden dirs minus a denylist (`docs/`, `target/`, `node_modules/`, `dist/`, `build/`, `.git/`, `z-harness/`).
  - (b) Rust-only first cut (Cargo workspace), defer polyglot.
  - (c) Always top-level dirs minus denylist — no language awareness.
- **Tentative call:** (a). User explicitly said "haven't been in some large projects" → polyglot matters. Detection runs in a small Haiku subagent or inline python; user confirms via AskUser before audits dispatch.
- **Consult? yes** — Trigger: affects >1 module's input format; this is the entry point everyone hits first.

## D3 — Cross-cutting pass mechanism
- **Decision:** What runs the repo-wide pre-audit pass (catches duplicated abstractions, style drift, dead code at module boundaries) and how its findings feed per-component audits.
- **Options:**
  - (a) New agent `uplift-cross-cutting` (Sonnet) — reads a curated repo source map (top-N files by churn, plus all component entry points), emits `CROSS-CUTTING.md`. Per-component auditors get this file as additional input context.
  - (b) Reuse bundled consultants (Gemini + Codex) on a curated source map → CROSS-CUTTING.md. No new agent; same pattern as `/z-review-all` Prong B without a SPEC.
  - (c) Skip the cross-cutting pass; mark each finding "cross-component" with a tag during per-component audits, reconcile after.
- **Tentative call:** (b). User explicitly wants the cross-cutting tier and we already have the two-consultant pattern — adding a new agent for this is YAGNI. CROSS-CUTTING.md becomes a read-only input handed to every per-component auditor dispatch via the auditor prompt.
- **Consult? yes** — Trigger: algorithm/architecture choice with materially different tradeoffs (one-pass-then-reuse vs no-pass) + introduces new orchestration artifact.

## D4 — Per-component audit dispatch: reuse `/z-audit` or replicate inline
- **Decision:** Does `/z-uplift` shell-invoke `/z-audit` per component, or dispatch the `auditor` agent directly inside its own orchestration.
- **Options:**
  - (a) Shell out: for each component, the orchestrator literally invokes `/z-audit --target <comp>` as a sub-skill. Maximum DRY.
  - (b) Inline replication: `/z-uplift` dispatches `auditor` agents per (component × dimension) directly, mirroring `/z-audit` Phases 2–6 inside its own outer loop.
  - (c) Extract a shared "audit-one-component" subroutine (skill or script) that both `/z-audit` and `/z-uplift` call.
- **Tentative call:** (b). Slash-commands aren't designed to be re-entrant from within the same harness context (each `/z-audit` call would start its own run-id, push notifications, compaction breakpoints, all stomping on the parent). The dispatch logic in `/z-audit` Phases 2–6 is ~80 lines of orchestration over reusable agents that already exist. Inline replication is the smaller violation than re-entrant slash invocation. (c) is correct long-term but premature now — extract only if a third caller appears.
- **Consult? yes** — Trigger: cross-module impact; reversibility moderate (if we pick (b) and later wish we had (c), refactor is real work).

## D5 — Auto-bail thresholds for component audits
- **Decision:** `/z-audit` auto-bails to `/z-plan` if a single-component audit returns >30 findings or >10 CRITICAL/HIGH. Does `/z-uplift` inherit this, soften it (large legacy codebases will trip it constantly), or replace it.
- **Options:**
  - (a) Inherit verbatim — components exceeding the threshold get auto-promoted from "audit" to "needs full /z-plan" in MANIFEST.md and skipped from the implement queue.
  - (b) Raise thresholds for uplift mode (e.g. 60 findings / 20 CRIT-HIGH) since legacy codebases are expected to be dense.
  - (c) Soft warn only — never bail; let the user decide per component in the review gate.
- **Tentative call:** (a). The whole point of the bail is "this needs structural work, not just task-list fixes." Uplift's value is bulk easy wins; a component that needs structural rework should be flagged loudly and excluded from the queue, not auto-implemented.
- **Consult? no** — obvious: follows existing convention; reversibility cheap (env var override).

## D6 — Sequencing inside the implement phase
- **Decision:** User chose "all audits first, then all implements". For the implement phase: parallel `/z-implement-all` across components, sequential, or user-gated each.
- **Options:**
  - (a) Sequential: one `/z-implement-all` per component, gate between each via AskUser.
  - (b) Parallel `/z-implement-all` across components (each runs its own batch internally).
  - (c) Single queue: concatenate every component's TASKS.md into one mega-list, drive one `/z-implement-all` over the union.
- **Tentative call:** (a). Parallel `/z-implement-all` across components stacks: each spawns 3 parallel implementer subagents internally → 3×N concurrent Sonnet/Opus subagents, plus N reviewer streams. Cost and orchestration blast-radius explode. (c) loses per-component isolation (a failure in component X stalls component Y's queue). Sequential with gates lets the user `/clear` between components.
- **Consult? no** — obvious from existing harness conventions; user can override sequentially-with-`--parallel-components=N` later.

## D7 — Resume/state for long uplift runs
- **Decision:** A bulk uplift over 10+ components is a multi-day, multi-`/clear` operation. How does `/z-uplift` resume.
- **Options:**
  - (a) MANIFEST.md is the authority: parses `[ ]`/`[x]`/`[skip]` per component-stage (decompose / cross-cutting / audit / implement). On re-invoke, finds next pending stage; skips completed ones.
  - (b) A `.uplift_state.json` file in the slug dir (similar to `.review_state.json`).
  - (c) Both — MANIFEST for human; state file for fast machine fast-forward.
- **Tentative call:** (a). MANIFEST is already the durable record of progress; a parallel JSON file is duplicate state with drift risk. The harness convention is "the artifact is the state" — TASKS.md `[x]` count is the durable record for `/z-implement-all`.
- **Consult? no** — follows convention.

## D8 — Naming
- **Decision:** Command name.
- **Options:**
  - (a) `/z-uplift`
  - (b) `/z-review-codebase`
  - (c) `/z-uplift-all` (parallel to `/z-implement-all`)
- **Tentative call:** (a). Short, distinct verb, doesn't collide with the existing review-family (which is diff-scoped). "Uplift" specifically connotes "bring it up to standard", which is the user's stated goal.
- **Consult? no** — naming bikeshed; pick and move.

---

## Consult-flagged summary
- **D1** (output layout)
- **D2** (decomposition strategy)
- **D3** (cross-cutting mechanism)
- **D4** (audit dispatch shape)

4 consult-flagged, under the 5 cap.
