# intent-schema

> Last updated: 2026-07-09
> Covers source: scripts/intent-schema.py, scripts/session-helpers.sh

## Overview

`intent-schema.py` is the schema validation and mutation engine for the two INTENT-mode artifacts: `INTENT.md` (the frozen plan contract) and `LEDGER.md` (the append-only realization trail). It enforces frontmatter requirements, validates required Markdown sections per depth level, lints acceptance criteria for non-observable language, stamps the freeze timestamp, re-opens a frozen contract for amendment, bootstraps a fresh ledger, sanity-checks a generated TASKS.md batch against the frozen criteria (Phase 8), performs the BFS termination check (per-criterion `met|unmet|unknown` + overall `done|continue` verdict), and computes the `/z-execute` final aggregate-review gate decision.

`session-helpers.sh` is a pure query helper layer for TASKS.md, SESSION.md, and metrics artifacts. It computes the done-set hash used as the resume key in `/z-execute`, lists completed task ids at a checkpoint boundary, finds the next dependency-eligible pending task, reports done/pending/in-progress/other status counts for the compaction gate, reads SESSION.md frontmatter fields, and surfaces the last `context_curated` event timestamp from the metrics log. It also wraps `intent-schema.py validate-intent` as the callable `validate_intent` shell function used by commands and agents. All functions are stdout-only, exit 0, and have no side effects.

## Key entry points

- `scripts/intent-schema.py:219` — `validate_intent(path)` — validates INTENT.md frontmatter (6 required fields) + required sections per level; returns `ValidationResult(valid, errors[])`
- `scripts/intent-schema.py:300` — `lint_criteria(path)` — scans the Acceptance checklist section for bare `runs`/`works` criteria with no observable object; returns `list[LintFailure]`
- `scripts/intent-schema.py:342` — `validate_ledger(path)` — validates LEDGER.md frontmatter (artifact, slug, intent_frozen_at); returns `ValidationResult`
- `scripts/intent-schema.py:380` — `reopen_intent(path)` — sets `frozen_at` back to `pending` for amendment; idempotent; returns `(was_reopened, "pending")`
- `scripts/intent-schema.py:442` — `freeze_intent(path)` — idempotent UTC ISO stamp into `frozen_at`; returns `(was_frozen_now, frozen_at_value)`
- `scripts/intent-schema.py:497` — `bootstrap_ledger(path, intent_frozen_at, slug)` — creates LEDGER.md with required frontmatter if absent; idempotent
- `scripts/intent-schema.py:713` — `validate_tasks(intent_path, tasks_path, current_criteria)` — Phase 8 sanity check: canonical task headings, dependency-graph acyclicity, and full current-criterion coverage (advanced or explicitly deferred)
- `scripts/intent-schema.py:865` — `evaluate_acceptance(intent_path, ledger_path, diff_path)` — per-criterion satisfaction check via LEDGER citation + non-empty diff; conservative: `unknown` treated as `unmet`; returns `AcceptanceResult`
- `scripts/intent-schema.py:1102` — `compute_aggregate_review_gate(tasks_path, workstreams_path, flags_path, execution_strategy_path)` — computes the `/z-execute` final aggregate-review required/not-required decision from 6 OR'd triggers
- `scripts/session-helpers.sh:75` — `done_set_hash(tasks_file)` — sha256 of sorted `[x]` task-ids; the canonical resume key
- `scripts/session-helpers.sh:155` — `last_done_task(tasks_file)` — id of the last `[x]` heading in file order; human hint only
- `scripts/session-helpers.sh:208` — `completed_task_ids(tasks_file)` — comma-separated ids for every `[x]` task in file order; the checkpoint-boundary completion set passed to the curator
- `scripts/session-helpers.sh:266` — `next_pending_task(tasks_file)` — first `[ ]` task whose declared deps are all in the done-set
- `scripts/session-helpers.sh:390` — `task_status_counts(tasks_file)` — prints `done=<n> pending=<n> in_progress=<n> other=<n>`; backs the compaction gate and curator `done_count`
- `scripts/session-helpers.sh:474` — `last_curated_marker(events_file)` — timestamp of most recent `context_curated` event
- `scripts/session-helpers.sh:522` — `session_frontmatter_field(session_file, field)` — scalar YAML frontmatter extractor for SESSION.md
- `scripts/session-helpers.sh:576` — `validate_intent(intent_file, [lint])` — shell wrapper delegating to `intent-schema.py`

## How it interacts with others

- `adaptive-intent` — the primary consumer; `freeze_intent`, `bootstrap_ledger`, `evaluate_acceptance`, `reopen_intent`, and `validate_tasks` are all called from `/z-plan`, `/z-execute`, and `/z-amend` during the INTENT-mode BFS loop
- `commands` — `/z-plan` shell-invokes `validate-tasks` at Phase 8 (and `task-tree-generator` self-checks against the same helper before returning); `/z-execute` invokes `freeze-intent`, `evaluate-acceptance`, and `aggregate-review-gate`, and calls session-helpers for `done_set_hash`, `completed_task_ids`, `next_pending_task`, `task_status_counts`, `session_frontmatter_field`, and `last_curated_marker`
- `session-handoff` — `session-helpers.sh` is the shared hash/status contract between the context-curator agent (writer) and `/z-execute` (reader); both MUST use `done_set_hash`/`task_status_counts`/`completed_task_ids` via the helper rather than re-implementing them inline
- `agents` — `task-tree-generator` documents that its TASKS.md output format must pass `intent-schema.py validate-tasks`; `context-curator` explicitly calls `task_status_counts` (for `done_count`) and consumes `completed_task_ids`/`last_gate_task_id` via the helper

## Edge cases / gotchas

- `evaluate_acceptance` is conservative by design: if the LEDGER cites a criterion but no cumulative diff is provided (or the diff is empty), the criterion is `unknown`, which counts as `unmet` for the overall verdict. This prevents false "done" verdicts when only a test helper was touched.
- `done_set_hash` supports two TASKS.md formats: inline `` `[x]` `` backtick status on a `## T001 —` heading, and a bare `- [x]` list item preceding the heading. Both must produce identical hashes or resume silently never fires.
- `freeze_intent` is frontmatter-aware but falls back to a `re.sub` on the full file if the `frozen_at` line is not found inside the parsed frontmatter block. A second fallback inserts the field before the closing `---` delimiter.
- `reopen_intent` operates only on the YAML frontmatter block and never touches body text, even if the body contains a line matching `frozen_at:`.
- `bootstrap_ledger` is a creation-only operation: if the LEDGER.md already exists with any content, it returns `False` without modification.
- The lint heuristic for non-observable criteria uses a two-phase regex: first detect the bare verb (`runs`/`works`), then verify that what follows is only filler words. Criterion text like "runs and exits 0" passes; bare "runs" fails.
- Level semantics: quick (L1) requires only the Acceptance checklist section; standard (L2) and deep (L3) additionally require `## Not doing` and `## Consider for this`.
- `validate_intent` accepts `planning_mode` values of `intent` or `full`; any other value is an error.
- `validate_tasks` requires the literal em-dash `**Depends on:** —` on every task; a non-`—` value is flagged as an error even though its referenced ids are still parsed into the dependency graph for cycle detection — so a bad-format dependency line can still surface a real cycle error alongside the format error.
- `compute_aggregate_review_gate` treats missing, unreadable, or structurally invalid `workstreams.json`/execution-strategy input as its own trigger (`metadata_missing_or_invalid`) rather than silently skipping the check — an absent workstreams file on a completed run forces aggregate-review required.
- `task_status_counts`, `completed_task_ids`, and `last_done_task` were added to `session-helpers.sh` since the previous doc snapshot; `task_status_counts` backs `check-compaction.sh` and the context-curator's `done_count` field, `completed_task_ids` backs the curator's checkpoint-boundary prompt payload, and `last_done_task` currently has no known caller (kept as a human-hint helper).

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/intent-schema.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

- **2026-06-29 correctness** ([incident:20260629T182649Z-review](#)) — INTENT-mode final review is only meaningful after LEDGER.md exists and is flushed; absence blocks realized-decision/deviation review, not just reporting polish. _(tags: correctness, observability)_

## Examples

- Validate an INTENT.md before freezing: `python3 scripts/intent-schema.py validate-intent z-harness/plans/my-plan/INTENT.md`
- Lint criteria: `python3 scripts/intent-schema.py lint-criteria z-harness/plans/my-plan/INTENT.md`
- Freeze at implement-all start: `python3 scripts/intent-schema.py freeze-intent z-harness/plans/my-plan/INTENT.md`
- Bootstrap ledger after freeze: `python3 scripts/intent-schema.py bootstrap-ledger z-harness/plans/my-plan/LEDGER.md 2026-06-19T12:00:00Z my-plan`
- Phase 8 TASKS.md sanity check: `python3 scripts/intent-schema.py validate-tasks INTENT.md TASKS.md 1,3`
- BFS termination check: `python3 scripts/intent-schema.py evaluate-acceptance INTENT.md LEDGER.md cumulative.diff`
- Aggregate-review gate: `python3 scripts/intent-schema.py aggregate-review-gate TASKS.md workstreams.json flags.md execution-strategy.md`
- Re-open for amendment: `python3 scripts/intent-schema.py reopen-intent z-harness/plans/my-plan/INTENT.md`
- Get resume key from shell: `bash scripts/session-helpers.sh done_set_hash z-harness/plans/my-plan/TASKS.md`
- Get checkpoint completion set: `bash scripts/session-helpers.sh completed_task_ids z-harness/plans/my-plan/TASKS.md`
- Get compaction-gate status counts: `bash scripts/session-helpers.sh task_status_counts z-harness/plans/my-plan/TASKS.md`
- Validate from shell with lint: `bash scripts/session-helpers.sh validate_intent z-harness/plans/my-plan/INTENT.md lint`
