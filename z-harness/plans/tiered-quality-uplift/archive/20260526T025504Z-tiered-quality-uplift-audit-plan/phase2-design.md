# Phase 2 — Design Audit

Reviewed SPEC/PLAN/TASKS against KISS/DRY/SOLID, performance, defensive bloat, and security.

## KISS / DRY (broadly clean)

- Zero new agent files — strong DRY adherence. The plan correctly identifies that `auditor`, `consultant-*`, `reviewer` cover the per-component pipeline and that orchestration can live inline.
- Sibling-plan layout (`<uplift-slug>-<component>/`) reuses `/z-implement-all --tasks=` verbatim — no path-rewriting, no special-casing. Elegant.
- Intentional inline duplication of `/z-audit` Phases 2–6: acknowledged in PLAN D4 with the "extract when a third caller appears" exit criterion. Acceptable. Future risk: drift between `/z-audit` and `/z-uplift` if `/z-audit`'s dispatch shape changes. Mitigation: an invariant in `z-uplift.json` says "must mirror /z-audit Phases 2–6 inline" — could be enforced with a CI shape-check, but that's YAGNI for now.

## SOLID

- Clean responsibility split: orchestrator decomposes + sequences, `auditor` finds, consultants critique, `/z-implement-all` implements. Each layer has one reason to change.
- Component output dir = single-purpose plan dir. Good.
- One concern: the orchestrator owns *both* decomposition heuristics AND per-component lifecycle. ~10 distinct phases in one command. Likely fine for a slash-command (they tend to be long-form), but a future `/z-uplift` v2 may want decomposition extracted into a script (`scripts/detect-components.py`) for testability — not now.

## Defensive bloat / over-engineering

- **Telemetry envelope is heavy:** 8 component-lifecycle events + standard `phase_end` per phase + `user_wait_start`/`user_wait_end` around every AskUser. For a long-running command this is reasonable (resume analysis needs the trail), but T007's acceptance bullet "grep returns ≥10 distinct event names" reads like a metric for metric's sake. Suggest reframing: only require events actually consumed downstream by `/z-stats` or resume logic.
- **MANIFEST state machine has 6 states + 2 reason-bearing variants.** Acceptable; each maps to a distinct UX moment. No simplification recommended.
- **`--retry-bailed` + `--refresh-component`**: two flags doing similar things (re-run audit for some subset). Could be one flag `--refresh <slug|bailed|all>`. Minor.

## Performance / cost

- **Per-component cost is real.** For each component: N auditors (default 3) × Sonnet + 2 consultants (one of which may be Codex or Gemini paid) + 1 reviewer pass. For a repo with 20 components, that's 60+ Sonnet auditor runs plus 60+ provider-routed consults plus 20 reviewer runs. The user's "all audits first, then all implements" choice serializes this in calendar time but not cost. Worth a one-line callout in `docs/human/z-uplift.md` so users understand the spend profile before invoking.
- **Cross-cutting source map: top-50 by churn over 90 days.** Reasonable. The `git log --since="90 days ago" --name-only` pipe is cheap. No issue.
- **Sequential component implements** are explicitly chosen (PLAN D6) to avoid the N×M parallel-implementer blast radius. Good call.

## Concurrency / state

- MANIFEST.md as sole authority + atomic rewrites (read full → mutate → tmpfile → `os.replace`) is the right pattern. T006 calls it out explicitly. Two interrupting `/z-uplift` invocations would race on MANIFEST — out of scope but worth one-line note "only one /z-uplift per repo at a time" in SPEC.
- Cross-cutting `global-task` runs FIRST in MANIFEST — addresses the Gemini-flagged build-break risk from the earlier consult. Sound.

## Security / validation

- All inputs are file paths / CLI flag values. No untrusted user input feeds into shell commands beyond standard `git grep` / `git log` patterns. Component slugs are derived from path basenames (no injection surface).
- `--components=<file>` reads a user-supplied file path. Should `realpath`-resolve and stay within repo root (don't follow symlinks out of the tree). Minor hardening, not a blocker.

## Style adherence

- SPEC follows existing /z-* phase shape and structure. No emoji. No CLAUDE.md violations noticed.
- Plan uses tasks-with-acceptance-criteria shape consumable by `/z-implement-all`. Good.
- One inconsistency: TASKS T008's `Files:` lists `skills/z-uplift/SKILL.md`, but SPEC L185 `source_file` for the INDEX.json entry only lists 2 files. Either is fine — pick one and align.

## Recommendations summary

1. **Add resume documentation for STYLE gate halt** — minor, prevents UX confusion.
2. **Document cost profile in `docs/human/z-uplift.md`** — sets user expectations before they invoke against a 20-component repo.
3. **Consider folding `--retry-bailed` / `--refresh-component` into a single `--refresh <target>` flag** — surface area reduction.
4. **Add "only one /z-uplift per repo at a time" guard or note** — MANIFEST race prevention.
5. **Re-think T007 acceptance** — drop the "≥10 distinct event names" metric in favor of explicit consumption-driven event list.
