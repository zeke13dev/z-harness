# amendment-brief

> Last updated: 2026-07-11
> Covers source: scripts/amendment-brief.py, scripts/amend-gate-decision.py, skills/z-audit-plan/SKILL.md, skills/z-review-all/SKILL.md, skills/z-amend/SKILL.md

## Overview

`amendment-brief` is the shared continuation surface for plan-audit and final-review findings that need plan-contract amendments or human judgment.

- `scripts/amend-gate-decision.py` maps the resolver envelope for `workflow.audit_to_amend` to `auto_split`, `force_ask`, or `halt`.
- `scripts/amendment-brief.py` renders a deterministic markdown brief from `corrections` (`spec_gap`) and `approach_concerns` (`premise_failure`).

`/z-audit-plan` uses both scripts in Phase 5. `/z-review-all` uses the renderer in Phase 6.6 (a subsection of Phase 6.5) after its own severity-agnostic Phase 6.5 auto-amend path.

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

In current `/z-audit-plan`, `force_ask` no longer means a popup. The command emits a prose alignment summary and records `force_ask_prose` in run-brief outcome. Note: the script's own module docstring (`scripts/amend-gate-decision.py:17`) still describes `force_ask` as "fall back to the 3-way interactive popup" — that comment is stale relative to actual `/z-audit-plan` behavior; the token's meaning is set by the caller, not the script.

This gate (`amend-gate-decision.py`) is distinct from `/z-amend`'s own internal Phase 4 user gate described below — the two operate at different layers and neither calls the other.

## `/z-amend` Phase 4 gate (no more `--skip-user-gate` flag)

`/z-amend` used to accept a `--skip-user-gate` flag that let programmatic callers (`/z-audit-plan`'s `auto_split` branch, `/z-review-all` Phase 6.5) bypass its interactive completed-task confirmation. That flag has been removed corpus-wide.

`/z-amend` Phase 4 (`skills/z-amend/SKILL.md:164`) now decides for itself, from its own Phase 3 impact analysis: it reads the **Touched-but-completed tasks** line written to `amendment.md`.

- **List is `none` (empty)** — auto-proceed straight to Phase 5, no ask. Emits `amend_user_gate_autoproceed` with `{"reason":"no_completed_tasks_touched"}`.
- **List is non-empty** (one or more `[x]` tasks touched) — presents `amendment.md` conversationally (Approve / Revise / Abandon), then walks each touched-but-completed task individually for a disposition (add superseding task / re-open / leave alone). This is never an `AskUserQuestion` popup.

Both `/z-audit-plan`'s `auto_split` branch and `/z-review-all`'s Phase 6.5 already filter out any finding that touches a `[x]` completed task before ever calling `/z-amend` (the "completed-task guard" in each caller). So when either caller invokes `/z-amend`, the Touched-but-completed list is guaranteed empty and Phase 4 auto-proceeds — the same effective non-interactive behavior the old flag used to force, now derived from the amendment's own impact analysis instead of a caller-supplied flag.

## `/z-review-all` Phase 6.5 auto-amend scope

Phase 6.5 does not consult `workflow.audit_to_amend` or `amend-gate-decision.py` at all — it auto-amends unconditionally across severities (blocker/major/minor) for any REVIEW-TASKS.md task with `**Disposition:** amendment_proposal`. It explicitly excludes:

- tasks whose `**Class:**` is `completed_task_contradiction` (routed as `superseding_task`, left for user disposition — these touch already-completed work),
- `candidate_task` (implementation_drift) items, which are never auto-implemented and stay as fixup tasks for the user to review before `/z-execute`.

Because completed-task-touching findings are excluded upstream, the plain `/z-amend "<amendment text>"` call in Phase 6.5 always lands on an empty Touched-but-completed list and auto-proceeds without asking (see the Phase 4 gate section above).

## Key entry points

<!-- AUTO-START: entry-points -->
- `scripts/amendment-brief.py:32` — `render_brief` — core deterministic markdown renderer.
- `scripts/amend-gate-decision.py:47` — `decide` — five-rule resolver-envelope mapping.
- `skills/z-audit-plan/SKILL.md:644` — Phase 5 gate decision — resolves `workflow.audit_to_amend` then calls `amend-gate-decision.py`.
- `skills/z-audit-plan/SKILL.md:679` — auto_split branch — auto-amends `spec_gap`, renders `premise_failure` as prose brief.
- `skills/z-audit-plan/SKILL.md:828` — force_ask branch — prose alignment summary, not `AskUserQuestion` popup.
- `skills/z-amend/SKILL.md:164` — Phase 4 — User gate — reads the Touched-but-completed tasks list from `amendment.md`; auto-proceeds when empty, otherwise presents Approve/Revise/Abandon plus per-task disposition conversationally.
- `skills/z-review-all/SKILL.md:910` — Phase 6.5 auto-amend — auto-amends every `amendment_proposal` disposition task (all severities) via plain `/z-amend "<text>"`; skips `completed_task_contradiction` and `implementation_drift`; relies on `/z-amend`'s own Phase 4 gate auto-proceeding since the completed-task guard already ran upstream.
- `skills/z-review-all/SKILL.md:981` — Phase 6.6 amendment brief (subsection of Phase 6.5) — builds `corrections` + `approach_concerns` JSON and writes archive `amendment-brief.md` via the shared renderer.
<!-- AUTO-END: entry-points -->

## How it interacts with others

- `config` — `/z-audit-plan`'s Phase 5 gate decision resolves `workflow.audit_to_amend` via `scripts/config.py resolve-question`, and the resulting envelope is what `amend-gate-decision.py` classifies.
- `z-audit-plan` — consumes both scripts: gate decision in Phase 5, then the renderer for the `auto_split` branch's `premise_failure` prose brief.
- `z-review-all` — consumes only the renderer (`amendment-brief.py`), in Phase 6.6, after its own unconditional-by-severity Phase 6.5 auto-amend logic (no gate-decision call).
- `z-amend` — both `z-audit-plan`'s `auto_split` branch and `z-review-all`'s Phase 6.5 invoke `/z-amend` directly (no flag); its own Phase 4 gate autoproceeds because both callers already excluded completed-task-touching findings before calling it.

## Invariants

- `spec_gap` and `premise_failure` are canonical Class values; `correction` and `approach` are only human glosses.
- Both `/z-audit-plan` and `/z-review-all` use `scripts/amendment-brief.py` instead of duplicating output format.
- Malformed gate-decision input exits 1; orchestrators must fail safe toward user-visible handling.
- `/z-review-all` Phase 6.5 does not consult `workflow.audit_to_amend` or call `amend-gate-decision.py`; its auto-amend is severity-agnostic for `amendment_proposal` disposition tasks, excluding `completed_task_contradiction` and `implementation_drift` items.
- `/z-amend` has no `--skip-user-gate` flag; its Phase 4 gate is decided entirely by whether its own Phase 3 impact analysis produced a non-empty Touched-but-completed tasks list.

## Edge cases / gotchas

- `amend-gate-decision.py` prints its token without a trailing newline.
- `source==none` is a common fresh-install path and auto-splits.
- `amendment-brief.py`'s `target` field is an artifact path/gloss, not necessarily an absolute path.
- A missing `approach_concerns` list is treated as empty and omits the "Worth your eyes" section.
- `amend-gate-decision.py`'s own module docstring is stale about what `force_ask` means downstream (see Gate-decision semantics above) — don't trust the script comment over the calling skill's actual branch behavior.
- Phase 6.6 in `z-review-all/SKILL.md` is a `###` subsection of Phase 6.5, not a standalone `##` phase — don't expect a top-level phase header when grepping for it.
- `--skip-user-gate` is gone from `/z-amend` and from every caller. If you see it referenced anywhere (old docs, old plan artifacts), it's stale — the current mechanism is the caller pre-filtering completed-task-touching findings so `/z-amend`'s Phase 4 finds an empty list and auto-proceeds.
- The gate-decision resolver (`amend-gate-decision.py`, `workflow.audit_to_amend`) and `/z-amend`'s Phase 4 completed-task gate are two independent gates at different layers; don't conflate them.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/amendment-brief.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded for this concept yet._
