# Phase 1 — Context

doc-fetcher (deep) covered the surface area; no Explore dispatched.

## Key reused primitives
- `agents/auditor.md` (Sonnet) — single-dimension auditor, returns SEVERITY-tagged findings.
- `agents/consultant-primary.md` (Gemini) + `consultant-secondary.md` (Codex) — bundled cross-LLM critique; already used by `/z-audit` Phase 4.
- `agents/reviewer.md` (Codex) — safety gate over generated TASKS.md.
- `commands/z-audit.md` — orchestration template for per-component audit (dimensions, rubric, REPORT.md → TASKS.md promotion).
- `commands/z-implement-all.md` `--tasks=<path>` fast path — consumes any task file by absolute path; derives `$BASE` from parent dir, reads SPEC/PLAN from there.
- `scripts/export-*.py` — adapter pattern; new command must be exported to cursor/codex/agy.
- `docs/llm/INDEX.json` + `docs/llm/<slug>.json` + `docs/human/<slug>.md` — concept registration.

## Implications for `/z-uplift`
- Reuse `auditor` agent directly (don't shell out to `/z-audit`). Same parallel-per-dimension dispatch, but the outer loop iterates over components.
- Cross-cutting pass needs a new lightweight agent (e.g. `uplift-cross-cutting`) or just bundled consultants over a curated source-map. Consider: ad-hoc dispatch of consultants on a repo-overview is closer to `/z-review-all` Prong B without a SPEC.
- Component decomposition: detect (a) Cargo workspace members, (b) python packages from pyproject/setup.cfg, (c) fallback to top-level dirs (filtered: ignore docs/, .git/, build artifacts, hidden dirs).
- Output layout: `z-harness/plans/<slug>-uplift/components/<component>/{REPORT.md,TASKS.md}` so each per-component TASKS.md is consumable via `/z-implement-all --tasks=…`.
- Top-level MANIFEST.md tracks component status (audited / implemented / skipped).
