# amendment-brief

> Last updated: 2026-06-24
> Covers source: scripts/amendment-brief.py, scripts/amend-gate-decision.py, skills/z-audit-plan/SKILL.md, skills/z-review-all/SKILL.md

## Overview

`amendment-brief` is the shared continuation surface for plan-audit and final-review findings that need plan-contract amendments or human judgment.

- `scripts/amend-gate-decision.py` maps the resolver envelope for `workflow.audit_to_amend` to `auto_split`, `force_ask`, or `halt`.
- `scripts/amendment-brief.py` renders a deterministic markdown brief from `corrections` (`spec_gap`) and `approach_concerns` (`premise_failure`).

`/z-audit-plan` uses both scripts in Phase 5. `/z-review-all` uses the renderer in Phase 6.6 after its own unconditional Phase 6.5 auto-amend path.

## Renderer interface

```bash
python3 scripts/amendment-brief.py payload.json
echo '{"corrections":[],"approach_concerns":[]}' | python3 scripts/amendment-brief.py
```

Input schema:

```json
{
  "corrections": [{"title": "string", "why": "string", "target": "string"}],
  "approach_concerns": [{"concern": "string", "affected": "optional", "suggestion": "optional"}]
}
```

Output always includes `Patched automatically (N corrections):`. The `Worth your eyes (M):` section appears only when `approach_concerns` is non-empty. When `affected` is absent, the prose falls back to "rework this, or proceed?".

## Gate-decision semantics

`amend-gate-decision.py` reads JSON from argv or stdin and prints a token with no trailing newline:

1. `result == halt` -> `halt`.
2. `result == skip` -> `auto_split`.
3. `source == none` -> `auto_split` (fresh-user default).
4. `source in {config,memory}` and `result in {ask,prefill}` -> `force_ask`.
5. Everything else -> `auto_split`.

In current `/z-audit-plan`, `force_ask` no longer means a popup. The command emits a prose alignment summary and records `force_ask_prose` in run-brief outcome.

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/amendment-brief.py:32` — `render_brief` — core deterministic markdown renderer.
- `scripts/amend-gate-decision.py:47` — `decide` — five-rule resolver-envelope mapping.
- `skills/z-audit-plan/SKILL.md:596` — Phase 5 gate decision — resolves `workflow.audit_to_amend` then calls `amend-gate-decision.py`.
- `skills/z-audit-plan/SKILL.md:631` — auto_split branch — auto-amends `spec_gap`, renders `premise_failure` as prose brief.
- `skills/z-audit-plan/SKILL.md:778` — force_ask branch — prose alignment summary, not `AskUserQuestion` popup.
- `skills/z-review-all/SKILL.md:821` — Phase 6.5 — auto-amends every amendment proposal regardless of severity.
- `skills/z-review-all/SKILL.md:892` — Phase 6.6 — builds renderer JSON and writes archive `amendment-brief.md`.
<!-- AUTO-END: entry-points -->

## Invariants

- `spec_gap` and `premise_failure` are canonical Class values; `correction` and `approach` are only human glosses.
- Both `/z-audit-plan` and `/z-review-all` use `scripts/amendment-brief.py` instead of duplicating output format.
- Malformed gate-decision input exits 1; orchestrators must fail safe toward user-visible handling.
- `/z-review-all` does not consult `workflow.audit_to_amend`; its Phase 6.5 auto-amend is unconditional for amendment proposals.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/amendment-brief.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
