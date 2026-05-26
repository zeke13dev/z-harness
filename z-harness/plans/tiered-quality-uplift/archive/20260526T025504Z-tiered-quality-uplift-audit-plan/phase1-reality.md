# Phase 1 — Reality Check

Cross-checked SPEC.md / PLAN.md / TASKS.md claims against the actual repo state.

## BLOCKER — wrong consultant/reviewer agent names

SPEC and TASKS dispatch:
- `subagent_type="z-harness:gemini-consultant"`
- `subagent_type="z-harness:codex-consultant"`
- `subagent_type="z-harness:codex-reviewer"`

None of these agents exist. `ls agents/` shows the actual agents are:
- `consultant-primary.md` (provider-resolved primary — NOT hardcoded to Gemini)
- `consultant-secondary.md` (provider-resolved secondary — NOT hardcoded to Codex)
- `reviewer.md` (provider-resolved — NOT hardcoded to Codex)

Per `commands/z-audit.md:138-148`, the in-repo convention for `Agent(...)` calls uses bare `subagent_type` (no `z-harness:` namespace prefix), e.g. `subagent_type="consultant-primary"`. The compaction summary's "Wrong consultant agent names" note was itself wrong.

**Affected locations:**
- SPEC.md L100–L102 (cross-cutting pass dispatch)
- SPEC.md L121, L123, L126 (per-component audit dispatch + codex-reviewer)
- SPEC.md L171–172 (`agents/ — no new agents` lists wrong names)
- PLAN.md L4, L9, L23, L30 (rationale + DRY section)
- TASKS.md T003 (cross-cutting dispatch), T004 (per-component audit + reviewer)

**Fix:** rename throughout to `consultant-primary`, `consultant-secondary`, `reviewer`. Drop the `z-harness:` namespace prefix. Update descriptions to drop hardcoded "Gemini" / "Codex" labels since providers are resolved at dispatch via `scripts/resolve-provider.sh`.

## BLOCKER — `skills/z-audit/SKILL.md` does not exist (T008, SPEC `skills/z-uplift/SKILL.md` section)

SPEC L217 and TASKS T008 say "matching the existing `skills/z-audit/SKILL.md` pattern". `ls skills/` shows no `z-audit/` directory. The listed skills are: `z-amend, z-brainstorm, z-debug, z-do, z-implement-all, z-implement-next, z-improve, z-init-docs, z-maintain-docs, z-plan, z-plan-light, z-plan-split, z-research, z-review-all, z-stats, z-suggest-memory, z-test, z-update`.

**Fix:** retarget pattern to an existing skill, e.g. `skills/z-improve/SKILL.md` or `skills/z-research/SKILL.md`.

## MAJOR — `docs/llm/z-audit.json` does not exist (SPEC L194, T008)

The SPEC says `docs/llm/z-uplift.json (new)` follows the "canonical schema" implied by an existing concept. There is no `z-audit.json`. Existing examples that could anchor the schema: `docs/llm/z-fix.json`, `docs/llm/z-update.json`, `docs/llm/style-init.json`.

**Fix:** point T008 at an existing concept JSON for schema reference.

## MAJOR — `auditor` agent takes `rubric_path`, not inline rubric text

SPEC L121 prescribes injecting STYLE.md content as the rubric body into the auditor prompt. Per `agents/auditor.md` L11: the auditor's input contract is `rubric_path` (a path), not a content blob. Auditor reads the file itself.

**Fix:** pass `rubric_path: ./STYLE.md` (or its absolute path) instead of injecting STYLE.md text into the auditor prompt. Generic-rubric fallback when STYLE.md is missing means passing empty `rubric_path` (the auditor's existing fallback behavior). No prompt-format change needed.

## MAJOR — synthetic `<slug>-cross-cutting` path computation uses JS regex syntax (TASKS T003)

T003 L34: `$Z_HARNESS_PLAN_DIR.replace(/<slug>$/, '<slug>-cross-cutting')` is JavaScript `.replace()`. In bash/python orchestration this is meaningless. The intended sibling-dir computation is straightforward: parent dir + `${slug}-cross-cutting`.

**Fix:** replace with concrete bash/python expression, e.g. `CROSS_DIR="$(dirname "$Z_HARNESS_PLAN_DIR")/${Z_HARNESS_SLUG}-cross-cutting"`.

## MAJOR — MANIFEST resume logic does not enumerate `[i] implementing`

T006 acceptance only handles `[~] auditing` and `[a] audited`. The state machine includes `[i] implementing` (active interrupt-time state). The edge-cases section in SPEC L237 references this case but no T006 acceptance bullet describes the resume branch. Risk: re-invoke after Ctrl-C during `/z-implement-all` jumps to the wrong phase.

**Fix:** in T006, enumerate `[i] implementing` as a separate resume branch (AskUser: resume implement / mark done / mark skipped / abort, per SPEC L237).

## MAJOR — `--refresh-component` deletes user-edited TASKS.md without backup (T006)

T006: "delete its REPORT.md and TASKS.md (preserve SPEC/PLAN)". If the user has hand-edited TASKS.md to triage findings, refresh destroys their edits silently.

**Fix:** before deletion, move to `<plan-dir>/archive/<RUN>/refreshed/` (cheap insurance). Document in SPEC + T006 acceptance.

## MAJOR — T010 cleanup deletes smoke-test artifacts before user can inspect

T010 says "delete the smoke test plan dir after verification" with the task marked INTERACTIVE. Sequence risk: the orchestrator may auto-clean before the user actually inspects events.jsonl, MANIFEST.md, etc.

**Fix:** make cleanup an explicit final AskUser step ("keep / delete"), or drop the cleanup line and document manual cleanup.

## MINOR — `--dimensions` default omits `perf` (SPEC L46)

`/z-audit` runs 4 dimensions by default; `/z-uplift` defaults to 3 (drops `perf`). Intentional per SPEC ("keep uplift scope bounded") but worth a one-line rationale alongside the flag definition so users don't think it's an oversight.

## MINOR — "edit-and-confirm" gate has no defined mechanism (T002)

T002's AskUser offers "proceed / abort / edit-and-confirm". Last option implies the orchestrator pauses, user edits COMPONENTS.md, then triggers a follow-up confirm. No mechanism described.

**Fix:** either drop the option (user just aborts, edits, re-invokes), or explicitly say "edit COMPONENTS.md in another window, then re-trigger this AskUser" with a re-prompt loop.

## MINOR — "entry file" per component is undefined (SPEC L101, T003)

Cross-cutting source map includes "each component's entry file". Heuristic not specified (README.md? lib.rs? package main?). Likely fine to default to README.md or first non-test source file in the component dir, but should be stated.

## MINOR — STYLE gate has no resume mechanism documented

SPEC L31: STYLE gate halts and instructs user to run `/z-style-init`. Doesn't say "then re-invoke `/z-uplift`". One-line addition would prevent confusion.

## Confirmed valid

- `commands/z-uplift.md` does not yet exist (so T001's `Files: added` is correct).
- `/z-implement-all --tasks=<path>` fast path with `BASE` derived from parent dir — confirmed at `commands/z-implement-all.md:13` and `:21`.
- `/z-mr-review` STYLE gate at `commands/z-mr-review.md:105-115`.
- `/z-style-init` exists at `commands/z-style-init.md`.
- `/z-audit` auto-bail thresholds `>30 total OR >10 CRIT-HIGH` at `commands/z-audit.md:56-57`.
- `scripts/export-{cursor,codex,agy}.py` all exist and share `_rewrite_body`.
- `scripts/regenerate-memories-flat.py` exists.
- `_ALWAYS_ON_AGENTS` set exists in `scripts/export-agy.py:117`.
- `auditor` agent exists (`agents/auditor.md`), Sonnet, dimension-scoped, read-only.
- `docs/llm/INDEX.json` exists; existing concept JSONs available (`agents`, `commands`, `scripts`, `skills`, `z-fix`, `z-update`, …).
