# intent-schema

> Last updated: 2026-06-24
> Covers source: scripts/intent-schema.py, scripts/session-helpers.sh

## Overview

`intent-schema.py` is the schema validation and mutation engine for the two INTENT-mode artifacts: `INTENT.md` (the frozen plan contract) and `LEDGER.md` (the append-only realization trail). It enforces frontmatter requirements, validates required Markdown sections per depth level, lints acceptance criteria for non-observable language, stamps the freeze timestamp, re-opens a frozen contract for amendment, bootstraps a fresh ledger, and performs the BFS termination check (per-criterion `met|unmet|unknown` + overall `done|continue` verdict).

`session-helpers.sh` is a pure query helper layer for TASKS.md and SESSION.md artifacts. It computes the done-set hash used as the resume key in `/z-execute`, finds the next dependency-eligible pending task, reads SESSION.md frontmatter fields, and surfaces the last `context_curated` event timestamp from the metrics log. It also wraps `intent-schema.py validate-intent` as the callable `validate_intent` shell function used by commands and agents. All functions are stdout-only, exit 0, and have no side effects.

## Key entry points

- `scripts/intent-schema.py:216` — `validate_intent(path)` — validates INTENT.md frontmatter (6 required fields) + required sections per level; returns `ValidationResult(valid, errors[])`
- `scripts/intent-schema.py:297` — `lint_criteria(path)` — scans the Acceptance checklist section for bare `runs`/`works` criteria with no observable object; returns `list[LintFailure]`
- `scripts/intent-schema.py:339` — `validate_ledger(path)` — validates LEDGER.md frontmatter (artifact, slug, intent_frozen_at); returns `ValidationResult`
- `scripts/intent-schema.py:439` — `freeze_intent(path)` — idempotent UTC ISO stamp into `frozen_at`; returns `(was_frozen_now, frozen_at_value)`
- `scripts/intent-schema.py:377` — `reopen_intent(path)` — sets `frozen_at` back to `pending` for amendment; idempotent; returns `(was_reopened, "pending")`
- `scripts/intent-schema.py:494` — `bootstrap_ledger(path, intent_frozen_at, slug)` — creates LEDGER.md with required frontmatter if absent; idempotent
- `scripts/intent-schema.py:635` — `evaluate_acceptance(intent_path, ledger_path, diff_path)` — per-criterion satisfaction check via LEDGER citation + non-empty diff; conservative: `unknown` treated as `unmet`; returns `AcceptanceResult`
- `scripts/session-helpers.sh:66` — `done_set_hash(tasks_file)` — sha256 of sorted `[x]` task-ids; the canonical resume key
- `scripts/session-helpers.sh:197` — `next_pending_task(tasks_file)` — first `[ ]` task whose declared deps are all in the done-set
- `scripts/session-helpers.sh:321` — `last_curated_marker(events_file)` — timestamp of most recent `context_curated` event
- `scripts/session-helpers.sh:369` — `session_frontmatter_field(session_file, field)` — scalar YAML frontmatter extractor for SESSION.md
- `scripts/session-helpers.sh:423` — `validate_intent(intent_file, [lint])` — shell wrapper delegating to `intent-schema.py`

## How it interacts with others

- `adaptive-intent` — the primary consumer; `freeze_intent`, `bootstrap_ledger`, `evaluate_acceptance`, and `reopen_intent` are all called from `/z-execute` and `/z-amend` during the INTENT-mode BFS loop
- `commands` — `/z-plan`, `/z-execute`, and `/z-amend` shell-invoke `intent-schema.py` directly for freeze, lint, validate, and evaluate-acceptance; `/z-execute` also calls session-helpers for `done_set_hash`, `next_pending_task`, `session_frontmatter_field`, and `last_curated_marker`
- `session-handoff` — `session-helpers.sh` is the shared hash contract between the context-curator agent (writer) and `/z-execute` (reader); both MUST use `done_set_hash` via the helper rather than re-implementing it inline
- `agents` — `task-tree-generator` documents that its TASKS.md output format must be parseable by `session-helpers.sh`; `context-curator` explicitly calls `done_set_hash` and `next_pending_task` via the helper

## Edge cases / gotchas

- `evaluate_acceptance` is conservative by design: if the LEDGER cites a criterion but no cumulative diff is provided (or the diff is empty), the criterion is `unknown`, which counts as `unmet` for the overall verdict. This prevents false "done" verdicts when only a test helper was touched.
- `done_set_hash` supports two TASKS.md formats: inline `` `[x]` `` backtick status on a `## T001 —` heading, and a bare `- [x]` list item preceding the heading. Both must produce identical hashes or resume silently never fires.
- `freeze_intent` is frontmatter-aware but falls back to a `re.sub` on the full file if the `frozen_at` line is not found inside the parsed frontmatter block. A second fallback inserts the field before the closing `---` delimiter.
- `reopen_intent` operates only on the YAML frontmatter block and never touches body text, even if the body contains a line matching `frozen_at:`.
- `bootstrap_ledger` is a creation-only operation: if the LEDGER.md already exists with any content, it returns `False` without modification.
- The lint heuristic for non-observable criteria uses a two-phase regex: first detect the bare verb (`runs`/`works`), then verify that what follows is only filler words. Criterion text like "runs and exits 0" passes; bare "runs" fails.
- Level semantics: quick (L1) requires only the Acceptance checklist section; standard (L2) and deep (L3) additionally require `## Not doing` and `## Consider for this`.
- `validate_intent` accepts `planning_mode` values of `intent` or `full`; any other value is an error.

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/intent-schema.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded yet._

## Examples

- Validate an INTENT.md before freezing: `python3 scripts/intent-schema.py validate-intent z-harness/plans/my-plan/INTENT.md`
- Lint criteria: `python3 scripts/intent-schema.py lint-criteria z-harness/plans/my-plan/INTENT.md`
- Freeze at implement-all start: `python3 scripts/intent-schema.py freeze-intent z-harness/plans/my-plan/INTENT.md`
- Bootstrap ledger after freeze: `python3 scripts/intent-schema.py bootstrap-ledger z-harness/plans/my-plan/LEDGER.md 2026-06-19T12:00:00Z my-plan`
- BFS termination check: `python3 scripts/intent-schema.py evaluate-acceptance INTENT.md LEDGER.md cumulative.diff`
- Re-open for amendment: `python3 scripts/intent-schema.py reopen-intent z-harness/plans/my-plan/INTENT.md`
- Get resume key from shell: `bash scripts/session-helpers.sh done_set_hash z-harness/plans/my-plan/TASKS.md`
- Validate from shell with lint: `bash scripts/session-helpers.sh validate_intent z-harness/plans/my-plan/INTENT.md lint`
