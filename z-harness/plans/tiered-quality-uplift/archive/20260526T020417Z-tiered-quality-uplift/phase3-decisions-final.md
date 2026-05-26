# Phase 3 — Decisions final (post-consult)

D1–D4 tentative choices held; both consultants endorsed (c, a, b, b). Findings applied with pushback:

## Accepted with refinement

### A1 — Three-tier cross-cutting classification (both LLMs)
CROSS-CUTTING.md findings classified into:
- `global-task` — needs its own plan; surfaces as a dedicated component slot in MANIFEST (`<slug>-cross-cutting/`).
- `per-component-context` — informs per-component audits as input; no direct task.
- `risk` — watch item; recorded but not actioned.

**Pushback:** consultants do the classification before they know the component decomposition. → Default any unclassifiable to `per-component-context`; per-component auditors may promote a piece of context to a local TASKS.md entry if locally actionable.

### A2 — Explicit user gate on component decomposition with orphan reporting (Gemini + Codex)
After auto-detect, present COMPONENTS.md preview with:
- Detection method per component (`cargo-workspace` / `pyproject` / `package-json-workspace` / `top-level-fallback`).
- Unclaimed-directory list (top-level dirs not covered by any detection method).
- `--components=<file>` and repeated `--component <path>` CLI overrides.

User confirms via AskUser before any audits dispatch. Slug collisions (duplicate package names across nested dirs) surface as an explicit AskUser prompt to disambiguate.

### A3 — Build-break risk mitigation via cross-cutting classification, NOT global backward-compat (Gemini)
**Pushback on Gemini's "force backward-compat":** would water down most cleanup work (legitimate dead-code removal, naming fixes). Real failure mode is narrower: public-API changes in component A breaking dependents.

→ Cross-cutting pass MUST flag cross-component public-surface changes as `global-task`. Per-component audits then have explicit context that "X public surface is touched by global-task G-001; coordinate." Per-component `/z-implement-all` runs sequentially per D6, and `global-task` work runs FIRST (so any API contract changes land before per-component cleanup).

### A4 — Cheap dependency reporting on bail (Gemini)
**Pushback on full dep graph:** polyglot dep-graph construction is a project of its own. Cheaper: when a component bails, text-grep across other components for imports/references of the bailed component's symbols/paths, and warn the user. No real graph, no language parsing.

### A5 — Explicit bail states in MANIFEST (Codex)
MANIFEST.md component states are:
- `[ ] pending` / `[~] auditing` / `[a] audited` / `[i] implementing` / `[x] done`
- `[!] bailed: <reason>` (e.g. `bailed: crit_high_volume`, `bailed: spec_problem`)
- `[s] skipped: <reason>` (user explicitly excluded)

Bailed components retain their partial REPORT.md for audit trail.

### A6 — Idempotent re-runnability (Codex)
`/z-uplift` is incremental. Re-running picks up at the next `pending` MANIFEST entry. Flags:
- `--retry-bailed` — re-attempts components in `bailed` state.
- `--refresh-component <name>` — re-runs audit for one component (overwrites REPORT/TASKS).

## Rejected with reasoning

### R1 — Bounded concurrency pool (Gemini's "50 concurrent dispatches")
Components are processed sequentially in the audit phase per D6 (which user confirmed). Per-component, audits dispatch the same `auditor` agents (1–4 dimensions in parallel) that `/z-audit` already dispatches without an explicit pool. The N×M explosion only happens if we parallelize components, which we explicitly chose not to. No pool needed.

### R2 — Stable component IDs separate from paths (Codex)
Path-derived slugs cover 95% of cases. Duplicate-package-name collisions across nested dirs are rare; collision detection at decomposition time (A2) handles them with a one-time AskUser disambiguation. A parallel ID system adds permanent complexity to MANIFEST for a rare case.

## Held unchanged
- D1 (sibling-plan layout), D2 (polyglot detection), D3 (consultant-driven cross-cutting), D4 (inline auditor dispatch).
- D5 (auto-bail thresholds), D6 (sequential implement with gates), D7 (MANIFEST is the resume authority — extended per A5/A6), D8 (name = `/z-uplift`).

## Shortcuts being taken
- **No real dep graph** (A4) — uses text-grep, will miss reflection/string-based references. User accepts in exchange for not building a polyglot dep parser.
- **No git-worktree-per-component build isolation** (rejected Gemini option) — main tree may be transiently un-buildable between AskUser gates if a global-task isn't run first or fails. Mitigated by cross-cutting classification, not eliminated.
