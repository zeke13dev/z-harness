---
name: z-suggest-memory
disable-model-invocation: true
description: "User-invoked authoring skill for the docs/llm/ memory layer. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extracts into docs/human/<slug>.md."
argument-hint: "[--concept <slug>] [--concept-hints <slug>,<slug>] [--source <prefix:ref>] [--edit <slug> <index>] [--delete <slug> <index>] [--dry-run] [--no-refresh-human] [--from-candidate-json <path|-] [--kind routing-preference --question-id <id> --value <v> --strength <weak|strong|very_strong> --scope <global|project> [--reason <text>]]"
runtime: c1
driver_features_required: [ask_user, subagent]
unsupported_driver_behavior: explicit_gate
---

You are running **z-harness `/z-suggest-memory`**.

Arguments (from `$ARGUMENTS`):

$ARGUMENTS

### `--source` prefix conventions

The `--source <prefix:ref>` flag accepts these canonical prefixes:

| Prefix | Example | Set by |
|--------|---------|--------|
| `incident:<RUN_ID>` | `--source "incident:20260525T233740Z-implement"` | `/z-execute` Phase 9 and `/z-review-all` Phase 7 review-agent flow (automatic) |
| `debug:<run-id>` | `--source "debug:20260523T143012Z-my-plan"` | `/z-debug` (automatic) |
| `human_review:<username>` | `--source "human_review:zbarnett"` | `/z-improve` (automatic) |
| `spec:<plan>/<ref>` | `--source "spec:rebalance-v2/run-3"` | Manual |

The `incident:` prefix is used automatically by the review-agent flow — you do not need to supply it when invoked from `/z-execute` or `/z-review-all`.

### `--kind routing-preference` mode

When `--kind routing-preference` is present, the skill writes a structured routing-preference memory entry without any interactive collection. Required flags:

| Flag | Description | Example |
|------|-------------|---------|
| `--question-id <id>` | Registered question ID from `QUESTION_IDS` | `workflow.audit_to_amend` |
| `--value <v>` | The preferred answer for that question | `amend` |
| `--strength <s>` | Signal strength: `weak`, `strong`, or `very_strong` | `very_strong` |
| `--scope <s>` | Memory scope: `global` or `project` | `project` |
| `--reason <text>` | Optional one-line rationale (≤ 200 chars, no emojis) | `"always amend after style audit"` |

**Target file:** `docs/llm/workflow.json` for global scope; `docs/llm/workflow-<project-slug>.json` for project scope. The file is created (with INDEX.json registration) if it does not exist.

**Memory entry shape:**
```json
{
  "type": "routing-preference",
  "question_id": "<id>",
  "value": "<v>",
  "scope": "global|project",
  "strength": "weak|strong|very_strong",
  "reason": "<text>",
  "date": "<YYYY-MM-DD>",
  "project_root": "<abs-path or omitted>"
}
```

The `reason` and `project_root` fields are omitted when not applicable. MEMORIES-FLAT.md is regenerated after the write. This mode is used by the elevation proposer flow when the user accepts a proposal as a memory:strength entry.

## Phase 0 — Preflight

Run from the target repository root. If `docs/llm/INDEX.json` is absent, stop
without writing and return `STATUS: no_docs`. The executable mutation boundary
is the retained helper below; pass the already tokenized arguments without
shell evaluation:

```text
bash scripts/run-memory-review.sh author <one parsed argv element per argument>
```

This is an invocation shape, not a command to interpolate literally. Construct
an argument vector from the validated tokens; never expand raw `$ARGUMENTS` in
a shell or use `eval`.

For candidate JSON, routing-preference, edit, delete, and dry-run modes, run
that helper and return its status block verbatim. Edit takes its replacement
from `--from-candidate-json`; delete takes no candidate. Interactive append or
edit collection is completed first, serialized as one candidate JSON object,
and then passed to the same helper. Do not implement mutation mechanics in the
host prompt.

`docs/llm/TAGS.txt` is part of the memory schema. If it is absent, the helper
uses the controlled seed for validation but creates it only after all input is
valid and only during a live transaction. Bad input and dry-run never create
the tag file.

Parse `$ARGUMENTS` without using shell evaluation. The supported mutations
are append (the default), `--edit <slug> <index>`, and
`--delete <slug> <index>`; exactly one mutation is allowed. `--dry-run`
validates and previews but never creates a concept, changes JSON, updates the
index, regenerates the flat view, or refreshes human docs.

Reject incompatible modes with `STATUS: bad_input`:

- `--edit` and `--delete` together;
- `--kind routing-preference` with edit, delete, or candidate JSON;
- a missing flag value, unknown flag, non-integer index, or candidate source
  other than one file path or `-` for stdin.

## Phase 1 — Resolve the input

`--from-candidate-json <path|->` is the non-interactive review handoff. Read
exactly one JSON object. A missing/unreadable path, malformed JSON, non-object,
or missing `type`/`text` returns `STATUS: bad_input` and writes nothing. Map:

| Candidate field | Memory field |
|---|---|
| `type` | `type` |
| `text` | `text` |
| `tags` | `tags` |
| `evidence_citations` | `evidence` (omit when empty) |
| `candidate_kind` | `candidate_kind` (omit when absent) |
| `review_after` | `expires` (omit when absent) |

Discard candidate `rationale`. An explicit `--concept` wins; otherwise use
`suggested_concept_slug`. The entry date defaults independently to today's UTC
date. The source defaults independently to the valid deterministic citation
`human_review:memory-review`; an explicit `--source` wins. Candidate JSON never
dispatches another skill or any axiom path.

For `--kind routing-preference`, require `--question-id`, `--value`,
`--strength`, and `--scope`. Validate the ID against
`python3 scripts/config.py list-question-ids`; strength is `weak`, `strong`,
or `very_strong`; scope is `global` or `project`; reason is optional, one
line, emoji-free, and at most 200 characters. Global writes target
`docs/llm/workflow.json`. Project writes target
`docs/llm/workflow-<repo-basename-slug>.json` and include the absolute
`project_root`. If the target concept is absent, Phase 4 creates and registers
it atomically before appending.

Delete mode takes its concept and index from `--delete` and collects no
replacement. Edit mode takes its target from `--edit` and supplies a complete
replacement through `--from-candidate-json`. Otherwise, if neither candidate JSON nor routing-preference mode
provided a complete entry, continue interactively.

## Phase 2 — Resolve the concept

Use explicit `--concept` when present. Otherwise read the concept slugs and
summaries from `docs/llm/INDEX.json`; use `--concept-hints` only to rank the
choices.

<!-- RUNTIME-GATE: ask_user; category=decision; required for interactive concept selection. -->
Ask once to choose an existing concept, create a new kebab-case concept, or
cancel. Cancel is the recommended no-op when there is no durable lesson and
returns `STATUS: skipped`. A new slug must match
`^[a-z][a-z0-9-]{0,39}$`; do not write its stub until all entry validation has
passed and dry-run has been ruled out.

## Phase 3 — Collect and validate one memory

<!-- RUNTIME-GATE: ask_user; category=decision; required for interactive memory collection. -->
Collect the full entry in one bounded prompt where the host supports it:

- type: one of `anti_pattern`, `abandoned_path`, `incident`,
  `performance_trap`, `decision_rationale`, or `open_question`;
- text: non-empty, one line, emoji-free, at most 200 characters;
- tags: zero or more controlled tags from `docs/llm/TAGS.txt`; additional
  tags must match `^[a-z][a-z0-9-]*$`;
- source: must match
  `^(incident:[a-zA-Z0-9-]+|spec:[a-z0-9-]+/[A-Za-z0-9-]+|debug:[A-Za-z0-9-]+|human_review:[A-Za-z0-9_@.-]+)$`;
- expires: optional real calendar date in `YYYY-MM-DD` form.

Validate candidate-JSON and interactive entries identically. Reject invalid
fields with `STATUS: bad_input` and the field-specific reason; never truncate,
coerce, or partly write. Routing-preference entries instead have this shape:

```json
{
  "type": "routing-preference",
  "question_id": "<registered-id>",
  "value": "<value>",
  "scope": "global|project",
  "strength": "weak|strong|very_strong",
  "reason": "<optional>",
  "date": "<YYYY-MM-DD>",
  "project_root": "<project-scope-only-absolute-path>"
}
```

For ordinary entries, assemble `type`, `text`, `source`, `date`, and `tags`,
plus only the optional fields supplied above. In edit mode the replacement
must pass the same complete validation as an append.

## Phase 4 — Preview or mutate atomically

Load the target concept JSON and require `memories` to be a list. For edit or
delete, require `0 <= index < len(memories)`; an invalid index returns
`STATUS: bad_input` with the current count. Append one entry, replace one
entry, or remove one entry. Never perform more than one mutation.

When a target concept must be created, prepare these changes as one logical
operation before publishing either: a minimal `docs/llm/<slug>.json` with the
standard concept fields and empty `memories`, and one INDEX entry with the
same slug, empty dependency/source lists, today's `last_updated`, low
confidence, and an honest summary. Refuse duplicate slugs.

For `--dry-run`, print the target, operation, and normalized JSON entry (or
the delete index and existing entry), then return `STATUS: ok` with
`MEMORIES_WRITTEN: 0` and an empty `WROTE` list.

For a live operation, clone the complete `docs/llm/` tree into a managed
preparation directory. Prepare the tag seed (when needed), concept JSON,
INDEX registration, and flat view there, then validate every prepared output
before publishing any canonical path. Preserve unrelated keys and existing
memory order. A successful append/edit reports one memory written; delete
reports zero.

Publication is a logical transaction. Capture a byte journal of the complete
pre-mutation memory tree, publish each prepared file through a flushed,
`fsync`ed sibling temporary followed by `os.replace`, and on any handled
replacement failure restore that journal and remove every newly created file
and temporary artifact. A failed preparation, regeneration, or publication
returns `STATUS: bad_input`, an empty `WROTE` list, and no successful writes.
Crash-atomic publication across several files and concurrent-writer locking
are outside this command's bounded contract.

## Phase 5 — Regenerate and optionally refresh

Regenerate against the prepared tree before canonical publication:

```bash
python3 scripts/regenerate-memories-flat.py --repo-root <prepared-repo-root>
```

A non-zero exit is `STATUS: bad_input` with an explicit stale-flat-view
warning and no canonical changes; never report full success while
`MEMORIES-FLAT.md` is stale.

Unless `--no-refresh-human` was supplied, refresh only the modified concept.

<!-- RUNTIME-GATE: subagent required for optional human-tier refresh. -->
After the canonical transaction commits, construct one deterministic JSON
request containing only `agent: doc-updater`, concept, absolute repository,
LLM and human paths, current source-file list, reason `memory_write`, mode
`write`, and the post-mutation memory count. Pass it on stdin to the runtime's
one-shot executable refresh bridge named by
`Z_HARNESS_MEMORY_REFRESH_DRIVER`; raw arguments are never shell-evaluated.
The bridge returns one JSON object with `status` and `memories_preserved`.

An absent or non-executable bridge reports `skipped unsupported_driver`.
Nonzero, malformed, non-object, non-`ok`, or count-mismatched responses report
`skipped updater_failed`. Report `ready` only for `status: ok` with the exact
post-mutation count. These refresh outcomes happen after the canonical
commit, so refresh failure never rolls it back. Never dispatch
`axiom-extractor`, a `z-axiom-*` skill, or another excluded production surface.

## Phase 6 — Return

Return exactly:

```text
STATUS: ok | skipped | bad_input | no_docs
CONCEPT: <slug or empty>
MEMORIES_WRITTEN: <0|1>
HUMAN_REFRESH: ready | skipped no_refresh | skipped dry_run | skipped unsupported_driver | skipped updater_failed
WROTE:
  <only paths actually written>
```

`STATUS: skipped` is the intentional no-op result. `STATUS: bad_input` and
`STATUS: no_docs` write nothing. Dry-run is `STATUS: ok`, writes nothing, and
always reports `MEMORIES_WRITTEN: 0` and `HUMAN_REFRESH: skipped dry_run`.

## Hard rules

- Cancel/no-op is valid; never manufacture a memory.
- Exactly one append, edit, or delete per invocation.
- Validate the complete prepared tree before the first canonical write; all
  writes are atomic replacements and handled partial publication rolls back.
- Never silently truncate text, accept malformed candidate JSON, or leave the
  flat memory view stale while reporting success.
- `z-suggest-memory` is the sole memory mutation path; it never approves or
  dispatches axioms.
