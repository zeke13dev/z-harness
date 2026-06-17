---
inclusion: manual
description: Authoring skill for the docs/llm/ memory layer. Called mandatorily from /z-debug post-mortem and /z-improve retro. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extracts into docs/human/<slug>.md.
---

You are running **z-harness `/z-suggest-memory`**. Goal: author one memory entry into `docs/llm/<slug>.json`, regenerate `docs/llm/MEMORIES-FLAT.md`, and optionally refresh the human-tier doc.

**Default outcome is Cancel.** This skill exists to capture genuinely novel anti-patterns, abandoned paths, incidents, and decision rationale. If no such signal surfaced in the calling context, the correct action is to emit zero memories and return `STATUS: skipped`. Cancel is a first-class outcome, not a fallback — do not pad to satisfy a mandatory-call rule.

## Phase 0 — Preflight

Check that `docs/llm/INDEX.json` exists in the repo root:

```bash
test -f docs/llm/INDEX.json
```

If it does not exist → return immediately:

```
STATUS: no_docs
CONCEPT:
MEMORIES_WRITTEN: 0
WROTE:
```

No further phases execute. Caller logs but does not fail.

**TAGS.txt bootstrap (idempotent).** After confirming `INDEX.json` exists, check whether `docs/llm/TAGS.txt` exists:

```bash
test -f docs/llm/TAGS.txt
```

If it does **not** exist, write it now with the same controlled-seed content that `/z-init-docs` Phase 4 writes (atomic write via tmpfile + `os.replace()`):

```bash
python3 - <<'PY'
import os

tags_path = "docs/llm/TAGS.txt"
if not os.path.exists(tags_path):
    content = """\
# Controlled tag seed — do not remove entries; add canonical aliases in section 2.
# Format:
#   Section 1: one tag per line (the controlled set).
#   Section 2 (after blank line): <canonical> = <alias1>, <alias2>
#              <canonical> must appear in section 1.
# /z-maintain-docs TAG_COLLISIONS UX writes to section 2 automatically.
correctness
perf
data-quality
schema
time-window
units
api-boundary
retry-loop
race-condition
dependency
deprecation
lossy-default
ux
observability
compliance

# Aliases: <canonical> = <alias1>, <alias2>
"""
    tmp = tags_path + ".tmp." + str(os.getpid())
    with open(tmp, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, tags_path)
    print(f"bootstrapped {tags_path}")
PY
```

This ensures the file exists before Phase 3 reads it for tag chips. The bootstrap is silent if the file already exists.

## Phase 1 — Parse arguments

Parse `$ARGUMENTS` to extract:

- `--concept <slug>` — explicit target concept (skip Phase 2 AskUserQuestion; go directly to Phase 3).
- `--concept-hints <slug>,<slug>` — comma-separated hints for the AskUserQuestion in Phase 2. If `--concept` is also set, hints are ignored.
- `--source <prefix:ref>` — pre-supplied source string (skip source collection in Phase 3).
- `--edit <slug> <index>` — edit mode: replace `memories[<index>]` for `<slug>`. Mutually exclusive with `--delete`.
- `--delete <slug> <index>` — delete mode: splice out `memories[<index>]` for `<slug>`. Mutually exclusive with `--edit`. Skips Phase 3 (collection) entirely.
- `--dry-run` — print the patch but skip the actual write in all modes.
- `--no-refresh-human` — skip Phase 7 (human-tier refresh).
- `--from-candidate-json <path>` — path to a JSON file containing a single candidate object (use `-` to read from stdin). When present, Phases 3a–3f are bypassed; the candidate object supplies `type`, `text`, `tags`, and optionally `expires` (via `review_after`). `suggested_concept_slug` is used as `--concept` if `--concept` was not also passed. `evidence_citations` are stored in the memory object's `evidence` field. `candidate_kind` is stored in the memory object's `candidate_kind` field for future analytics but does not affect validation. `rationale` is discarded. Date defaults to today unless `--date` was also passed. Phase 4 validation, Phase 5 atomic write, and Phase 6 MEMORIES-FLAT.md regeneration still run.
- `--kind routing-preference` — activates the **routing-preference mode** (see below). Must be accompanied by `--question-id`, `--value`, `--strength`, and `--scope`. Optional `--reason`. Mutually exclusive with `--edit`, `--delete`, and `--from-candidate-json`.
- `--question-id <id>` — the question_id to write a routing preference for (e.g. `workflow.audit_to_amend`). Required when `--kind routing-preference` is present.
- `--value <v>` — the preferred answer value (e.g. `amend`). Required when `--kind routing-preference` is present.
- `--strength <weak|strong|very_strong>` — signal strength of this preference. Required when `--kind routing-preference` is present.
- `--scope <global|project>` — memory scope. Required when `--kind routing-preference` is present.
- `--reason <text>` — optional one-line rationale for the preference (free text, no emojis, ≤ 200 chars).

If both `--edit` and `--delete` are present → reject immediately with `STATUS: bad_input` and a clear error message.

If `--kind routing-preference` is present alongside `--edit`, `--delete`, or `--from-candidate-json` → reject immediately with `STATUS: bad_input` and a clear error message.

Mode determination:
- `--kind routing-preference` present → **routing-preference mode** (see § Routing-preference mode).
- `--delete` present → **delete mode**.
- `--edit` present → **edit mode**.
- Neither → **append mode** (default).

In delete mode, jump directly to Phase 5 (Write) after resolving the target concept from the `--delete <slug>` argument — no collection needed.

## Routing-preference mode

When `--kind routing-preference` is present, this skill writes a structured routing-preference memory entry to `docs/llm/workflow.json` (global scope) or `docs/llm/workflow-<project-slug>.json` (project scope). Normal interactive collection (Phases 2–3) and normal concept-selection flows are **bypassed entirely**. The skill jumps: Phase 0 → Phase 1 → here → Phase 4 (validation) → Phase 5 (write) → Phase 6 (MEMORIES-FLAT.md regen) → Phase 7 (human-tier refresh, unless `--no-refresh-human`) → Phase 8 (return).

### RP-1. Validate flags

All four required flags must be present: `--question-id`, `--value`, `--strength`, `--scope`. If any is missing, return `STATUS: bad_input` with message `--kind routing-preference requires --question-id, --value, --strength, and --scope`.

### RP-2. Validate `question_id`

Run the `list-question-ids` subcommand to obtain the known set:

```bash
KNOWN_IDS="$(python3 scripts/config.py list-question-ids)"
LISTQ_EXIT=$?
```

If the subprocess exits non-zero, return `STATUS: bad_input` with message `could not validate question_id: config.py list-question-ids failed (exit <N>)`.

Parse `KNOWN_IDS` as a JSON array. If `--question-id <id>` is not in the array, return `STATUS: bad_input` with message `unknown question_id "<id>"; known: <KNOWN_IDS>`.

### RP-3. Validate `strength`

`--strength` must be one of: `weak`, `strong`, `very_strong`. If not, return `STATUS: bad_input` with message `strength "<v>" is not valid; must be one of: weak, strong, very_strong`.

### RP-4. Validate `scope`

`--scope` must be `global` or `project`. If not, return `STATUS: bad_input` with message `scope "<v>" is not valid; must be global or project`.

### RP-5. Resolve target concept slug and project_root

- **Global scope:** target slug = `workflow`. `project_root = null`.
- **Project scope:** derive the project slug from `git rev-parse --show-toplevel`, then take the basename and slugify (lowercase, spaces and underscores to hyphens). Target slug = `workflow-<project-slug>`. `project_root` = the absolute path returned by `git rev-parse --show-toplevel`.

  If `git rev-parse --show-toplevel` fails (not inside a git repo), return `STATUS: bad_input` with message `--scope project requires a git repo; git rev-parse --show-toplevel failed`.

### RP-6. Ensure target file exists (create if missing)

Check whether `docs/llm/<target-slug>.json` exists:

```bash
test -f docs/llm/<target-slug>.json
```

If it does **not** exist, create it now as a minimal stub and register it in `docs/llm/INDEX.json`:

**Create `docs/llm/<target-slug>.json`:**

```json
{
  "concept": "<target-slug>",
  "last_updated": "<today-YYYY-MM-DD>",
  "source_file": [],
  "confidence": "low",
  "entry_points": [],
  "depends_on": [],
  "consumed_by": [],
  "invariants": [],
  "gotchas": [],
  "memories": []
}
```

Write atomically (tmpfile + `os.replace()`).

**Register in `docs/llm/INDEX.json`:** read the file, append an entry, write atomically:

```json
{
  "slug": "<target-slug>",
  "source_file": [],
  "last_updated": "<today>",
  "confidence": "low",
  "depends_on": [],
  "consumed_by": [],
  "summary": "Routing preferences for workflow decisions."
}
```

If `docs/llm/INDEX.json` cannot be read or written, return `STATUS: bad_input` with message `could not register concept in INDEX.json: <error>`.

Also create a stub `docs/human/<target-slug>.md` if it does not exist:

```markdown
# <Title Case of target-slug>

> Stub — routing preference memories for workflow decisions. Populated via /z-suggest-memory --kind routing-preference.
```

Write atomically. If this write fails, log a warning to stderr but do not abort — the llm-tier write is the critical one.

### RP-7. Assemble memory entry

```json
{
  "type": "routing-preference",
  "question_id": "<question-id>",
  "value": "<value>",
  "scope": "<global|project>",
  "strength": "<weak|strong|very_strong>",
  "reason": "<reason or null>",
  "date": "<today-YYYY-MM-DD>",
  "project_root": "<abs-path or null>"
}
```

Omit `reason` from the JSON object if `--reason` was not supplied (do not include `"reason": null`). Set `project_root` to null (omitted) for global scope; set to the absolute path for project scope.

If `--dry-run` is active, print the assembled entry and target file path, then skip Phases 5–7 and return `STATUS: ok` (dry-run), `MEMORIES_WRITTEN: 0`.

### RP-8. Proceed to Phase 5 (Write)

The assembled entry is written via the **append mode** path in Phase 5 (read `docs/llm/<target-slug>.json`, push memory entry, atomic write). Then Phase 6 regenerates MEMORIES-FLAT.md, Phase 7 refreshes the human tier, and Phase 8 returns.

The return shape uses `CONCEPT: <target-slug>` and `MEMORIES_WRITTEN: 1`.

## Phase 2 — Resolve target concept

Skip this phase if `--concept <slug>` was provided (use that slug directly).

Read `docs/llm/INDEX.json` to get the list of existing concept slugs and summaries.

Parse `concept_hints` from `--concept-hints` (comma-separated slug list). The first hint is the pre-selected recommended option.

Present an `AskUserQuestion` with exactly four options:

1. **`<first-hint>` (recommended)** — use the first hint concept. Only shown if at least one hint was supplied.
2. **Other existing concept** — filterable select from the slugs in INDEX.json. User types to filter.
3. **Create new concept** — author a new stub concept (see below).
4. **Cancel** — write nothing, return `STATUS: skipped, MEMORIES_WRITTEN: 0` immediately.

If no hints were supplied, collapse options 1 and 2 into a single "Select existing concept" option.

**Cancel is the default.** The question framing must make clear that Cancel is the expected outcome when no salient memory exists.

### Create-new-concept path

If the user picks "Create new concept":

1. Ask (free-text `AskUserQuestion`) for the new concept slug (kebab-case, ≤40 chars, no spaces). Validate kebab-case format; re-ask on invalid input.
2. Write a minimal stub `docs/llm/<new-slug>.json`:
   ```json
   {
     "concept": "<new-slug>",
     "last_updated": "<today-YYYY-MM-DD>",
     "source_file": [],
     "confidence": "low",
     "entry_points": [],
     "depends_on": [],
     "consumed_by": [],
     "invariants": [],
     "gotchas": [],
     "memories": []
   }
   ```
3. Write a stub `docs/human/<new-slug>.md`:
   ```markdown
   # <Title Case of new-slug>

   > Stub — populate via /z-maintain-docs.
   ```
4. Add an entry to `docs/llm/INDEX.json`:
   ```json
   {
     "slug": "<new-slug>",
     "source_file": [],
     "last_updated": "<today>",
     "confidence": "low",
     "depends_on": [],
     "consumed_by": [],
     "summary": ""
   }
   ```
   Use an atomic write (read → modify in memory → write tmpfile → `os.replace()`) so concurrent runs are safe.
5. Continue to Phase 3 with `<new-slug>` as the resolved target concept.

Do NOT invoke `/z-init-docs` — that is source-file-driven generation. The stub is the seed; full population happens when source files exist.

## Phase 3 — Collect memory

Skip this phase in **delete mode**.

**`--from-candidate-json` bypass:** When `--from-candidate-json <path>` is present, skip Phases 3a–3f entirely and instead read the candidate JSON object from `<path>` (or stdin if `<path>` is `-`). Map fields as follows:

```python
import json, sys

if candidate_json_path == "-":
    candidate = json.load(sys.stdin)
else:
    with open(candidate_json_path) as f:
        candidate = json.load(f)

# Map candidate fields to memory fields:
memory_type = candidate["type"]
memory_text = candidate["text"]
memory_tags = candidate.get("tags", [])
memory_evidence = candidate.get("evidence_citations", [])
memory_candidate_kind = candidate.get("candidate_kind")  # store for analytics; do not validate
memory_expires = candidate.get("review_after")  # optional; may be None

# Concept slug: --concept takes precedence; fall back to suggested_concept_slug
if not concept_slug:
    concept_slug = candidate.get("suggested_concept_slug")

# rationale is discarded — it is review-agent prose, not memory content

# Date: use today unless --date was also passed
if not date_override:
    from datetime import date
    memory_date = date.today().isoformat()
else:
    memory_date = date_override
```

If `--from-candidate-json` is present but the path does not exist (and is not `-`), return `STATUS: bad_input` with message `candidate JSON path not found: <path>`. If JSON parsing fails, return `STATUS: bad_input` with message `could not parse candidate JSON: <error>`. If the `type` field is missing or `text` field is missing, return `STATUS: bad_input` with message `candidate JSON missing required field: <field>`.

After mapping, proceed directly to Phase 4 with the assembled fields.

**Interactive collection (only when `--from-candidate-json` is NOT present):**

Gather the four required memory fields interactively (one `AskUserQuestion` block is preferred over multiple round-trips; group what the UI allows):

### 3a. Routing-flavored text detection (redirect gate)

Before presenting type chips or collecting any text, check whether the user has already supplied candidate text (e.g. via a `--text` flag or pre-filled context). If candidate text is available, scan it for routing-flavored patterns:

```python
import re

ROUTING_PATTERN = re.compile(
    r'\b(always|usually|every time)\b.*\b(after|before|when)\b',
    re.IGNORECASE
)

routing_match = bool(ROUTING_PATTERN.search(candidate_text)) if candidate_text else False
```

If `routing_match` is `True` **and** the candidate has no explicit `type` already set:

Surface a one-shot `AskUserQuestion`:

> **"This looks like a workflow preference. Write to `.z-harness/config.toml [workflow]` instead?"**
>
> Options:
> - **yes-config** — Write to config (see instructions below).
> - **write-as-routing-preference** — Write as a `routing-preference` memory entry.
> - **write-as-lesson-learned** — Continue with the original write path (lesson-learned memory).

**Branch on the user's choice:**

**yes-config branch:**
Gather the following via follow-up `AskUserQuestion` prompts:
1. `key` — the `workflow.*` key to set (e.g. `workflow.audit_to_amend`). Must be a dot-prefixed key under `[workflow]`.
2. `value` — the value to assign (free text; validated by `config.py set` downstream).
3. `scope` — `global` or `project`.

Then invoke (future-facing; `config.py set` is not yet shipped as of this writing — document the call for when it lands):

```bash
python3 scripts/config.py set <key> <value> [--scope=global|project]
```

Return `STATUS: ok` with `MEMORIES_WRITTEN: 0` and a note that the value was written to config. Do not proceed to memory write phases.

**write-as-routing-preference branch:**
Redirect into the `--kind routing-preference` flow. Gather the required flags interactively:
1. `question_id` — the question_id to write a preference for (e.g. `workflow.audit_to_amend`). Present available IDs from `python3 scripts/config.py list-question-ids` as chips.
2. `value` — the preferred answer value.
3. `strength` — one of `weak`, `strong`, `very_strong`.
4. `scope` — `global` or `project`.
5. `reason` (optional) — one-line rationale.

Once all flags are gathered, proceed as if invoked with `--kind routing-preference --question-id <id> --value <v> --strength <s> --scope <sc> [--reason <r>]` (jump to § Routing-preference mode → RP-1).

**write-as-lesson-learned branch:**
Continue with the original write path silently (proceed to Phase 3b below as normal).

**Detection-fail or detection-irrelevant (no match, or candidate text not yet available):**
Continue with Phase 3b silently. Do not surface the redirect question.

### 3b. Type (enum chips)

Present chips for:
- `anti_pattern`
- `abandoned_path`
- `incident`
- `performance_trap`
- `decision_rationale`
- `open_question`

User must pick exactly one. No free-form type.

### 3c. Text

Free-text input. Constraints (validated in Phase 4; show them inline in the question):
- ≤ 200 characters.
- No newlines (single line only).
- No emojis.

### 3d. Tags

Read `docs/llm/TAGS.txt` to obtain the controlled chip set. Parse section 1 (lines before the first blank separator line, ignoring `#` comments and blank lines within the section):

```python
controlled_tags = []
in_section1 = True
for line in open("docs/llm/TAGS.txt"):
    line = line.rstrip()
    if not line:
        in_section1 = False  # blank line = section separator
        break
    if not line.startswith("#"):
        controlled_tags.append(line)
```

If `TAGS.txt` is missing (Phase 0 bootstrap should have created it, but as a safeguard), fall back to the hard-coded 15-tag list:

`correctness`, `perf`, `data-quality`, `schema`, `time-window`, `units`, `api-boundary`, `retry-loop`, `race-condition`, `dependency`, `deprecation`, `lossy-default`, `ux`, `observability`, `compliance`

Present the controlled set as multi-select chips (zero or more may be selected). Also allow free-form additional tags (comma-separated; each must be kebab-case). Free-form tags are accepted and written as-is; `/z-maintain-docs` dedup pass surfaces near-duplicates for human review later.

### 3e. Source

If `--source <prefix:ref>` was supplied in Phase 1, use it (skip source collection).

Otherwise, prompt for source. The source must match:

```
^(incident:[a-z0-9-]+|spec:[a-z0-9-]+/[A-Za-z0-9-]+|debug:[A-Za-z0-9-]+|human_review:[A-Za-z0-9_@.-]+)$
```

Show examples: `incident:slippage-spike`, `spec:rebalance-v2/run-3`, `debug:20260523T143012Z-my-plan`, `human_review:zbarnett`.

The `incident:<RUN_ID>` prefix is the canonical form used by the review-agent flow. For example:

```
--source "incident:20260525T233740Z-implement"
```

The `/z-implement-all` Phase 9 and `/z-review-all` Phase 7 review-agent passes supply this prefix automatically when dispatching `/z-suggest-memory` — you do not need to set it manually when invoked from those flows.

If calling context is `/z-debug`, the source is pre-filled as `debug:<run-id>` (caller passes via `--source`).
If calling context is `/z-improve`, the source is pre-filled as `human_review:<username>` (caller passes via `--source`).

### 3f. Date

Default to today (`YYYY-MM-DD`). Not editable by user during collection — always uses today. (Editable later via `--edit` if needed.)

### 3g. Expires (optional)

Offer an optional expiry date field (`YYYY-MM-DD`). Leave blank to omit the field. A future `/z-maintain-docs` pass will flag the memory when `expires < today`.

## Phase 4 — Validate

Validate all collected fields. On any failure, report the specific error and loop back to Phase 3 (re-collect only the failing field if possible):

| Field | Rule | Error message |
|-------|------|---------------|
| `text` | ≤ 200 chars | `text exceeds 200 characters (<N> chars); trim and resubmit` |
| `text` | no newlines | `text contains a newline; memory must be a single line` |
| `text` | no emojis | `text contains an emoji; memories must be plain ASCII/Unicode text without emoji` |
| `tags` | each tag is kebab-case (`^[a-z][a-z0-9-]*$`) | `tag "<tag>" is not kebab-case; use lowercase letters, digits, and hyphens only` |
| `source` | matches regex above | `source "<src>" does not match the required format` |
| `date` | `YYYY-MM-DD` format | `date "<d>" is not YYYY-MM-DD` |
| `expires` | `YYYY-MM-DD` format (when present) | `expires "<d>" is not YYYY-MM-DD` |
| `type` | one of the six enum values | `type "<t>" is not a valid memory type` |

After validation passes, assemble the memory object:

```json
{
  "type": "<type>",
  "text": "<text>",
  "source": "<source>",
  "date": "<YYYY-MM-DD>",
  "tags": ["<tag1>", "<tag2>"],
  "expires": "<YYYY-MM-DD>"
}
```

Omit `expires` if not provided.

When `--from-candidate-json` was used, also include the following fields if present:
- `"evidence": ["path/to/file:42", ...]` — from `evidence_citations` in the candidate (omit if empty list).
- `"candidate_kind": "<kind>"` — from `candidate_kind` in the candidate (omit if absent). Stored verbatim for future analytics; not validated against an enum.

If `--dry-run` is present, print the assembled memory object and the target file path, then skip Phases 5–7 and emit the return shape with `STATUS: ok` (dry-run) and `MEMORIES_WRITTEN: 0`. Do NOT write any files.

## Phase 5 — Write

Three mutually exclusive modes. **Exactly one mutation per invocation.**

### Append mode (default)

1. Read `docs/llm/<slug>.json`.
2. Push the new memory object to the end of `memories[]`.
3. Write atomically:
   ```python
   import json, os, tempfile
   data = json.load(open(path))
   data.setdefault("memories", []).append(memory)
   tmp = path + ".tmp." + str(os.getpid())
   with open(tmp, "w") as f:
       json.dump(data, f, indent=2)
       f.write("\n")
       f.flush()
       os.fsync(f.fileno())
   os.replace(tmp, path)
   ```

### Edit mode (`--edit <slug> <index>`)

1. Read `docs/llm/<slug>.json`.
2. Validate that `<index>` is within range `[0, len(memories) - 1]`. If out of range, return `STATUS: bad_input` with message `index <N> out of range (concept has <M> memories)`.
3. Replace `memories[<index>]` with the newly collected and validated memory object.
4. Write atomically (same pattern as append).

### Delete mode (`--delete <slug> <index>`)

1. Read `docs/llm/<slug>.json`.
2. Validate that `<index>` is within range. If out of range, return `STATUS: bad_input`.
3. Splice out `memories[<index>]`:
   ```python
   data["memories"].pop(index)
   ```
4. Write atomically (same pattern).
5. Log the deletion:
   ```bash
   bash "${ANTIGRAVITY_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/log-event.sh" "docs" memory_deleted \
     "$(printf '{"concept":"%s","index":%d,"text_preview":"%s"}' "<slug>" <N> "<first 60 chars of deleted text>")"
   ```

If `--dry-run` is active, skip the actual write in all three modes (already handled in Phase 4; this is a belt-and-suspenders note).

## Phase 6 — Regenerate MEMORIES-FLAT.md

Call the shared regeneration helper:

```bash
python3 scripts/regenerate-memories-flat.py --repo-root "$(pwd)"
```

If the script exits non-zero, surface the error to the user and halt. Do not silently continue with a potentially stale MEMORIES-FLAT.md.

If `--dry-run` is active, call the helper with `--dry-run` (prints to stdout but does not write):

```bash
python3 scripts/regenerate-memories-flat.py --repo-root "$(pwd)" --dry-run
```

## Phase 7 — Optional human-tier refresh

Unless `--no-refresh-human` was passed, spawn a `doc-updater` subagent in `mode: write` for the just-modified concept:

```
<!-- agent dispatch / skill invocation not supported in Kiro; see CAPABILITIES.md -->
  subagent_type="doc-updater",
  description="Refresh human tier for <slug> after memory write",
  prompt="concept: <slug>\nhuman_path: docs/human/<slug>.md\nllm_path: docs/llm/<slug>.json\nsource_files: <source_file list from slug.json or empty>\nreason: memory_write\nmode: write\nrepo_root: <abs path>"
)
```

This re-emits the `## Memories` section in `docs/human/<slug>.md` so the human tier stays in sync. doc-updater must round-trip existing memories (the `MEMORIES_PRESERVED` check).

If doc-updater returns `MEMORIES_PRESERVED: <N>` where N does not match the expected count after the write, surface a warning:
```
WARNING: doc-updater preserved <N> memories but <M> were expected. Check docs/llm/<slug>.json manually.
```

Skip this phase if `--dry-run` is active or if `--no-refresh-human` is set.

## Phase 8 — Return

Emit the return shape:

```
STATUS: ok | skipped | bad_input | no_docs
CONCEPT: <slug or empty>
MEMORIES_WRITTEN: <N>
WROTE:
  docs/llm/<slug>.json
  docs/llm/MEMORIES-FLAT.md
  [docs/human/<slug>.md]
```

- `STATUS: ok` — memory written (or deleted/edited) successfully.
- `STATUS: skipped` — user picked Cancel; nothing written.
- `STATUS: bad_input` — validation failed or invalid index; nothing written.
- `STATUS: no_docs` — preflight failed; nothing written.
- `MEMORIES_WRITTEN` is 1 for append and edit, 0 for delete and skipped and bad_input and no_docs.
- `WROTE` lists actual files modified; omit any file that was not written (e.g. omit `docs/human/<slug>.md` if `--no-refresh-human` or if `--dry-run` skipped the write).

In `--dry-run` mode, `MEMORIES_WRITTEN` is always 0 even when STATUS is ok.

## Hard rules

- **One mutation per invocation.** Append, edit, or delete — never combined. Callers re-invoke for additional changes.
- **No emojis** in memory `text`.
- **Reject text with newlines** or text exceeding 200 characters — no silent truncation.
- **Atomic writes only.** Always write via tmpfile + `os.replace()`. Never truncate the canonical JSON file in place.
- **Cancel is the default outcome.** This skill must not manufacture memories to satisfy a mandatory-call contract. Salience over completeness.
- **Never read `docs/llm/*.json` from main thread** beyond what is required for this skill's write operation. Do not dispatch doc-fetcher from this skill.
- **Source regex is structural only.** Do not validate whether the referenced incident/spec/debug run actually exists — that is the author's responsibility.

## Calling context notes (for /z-debug and /z-improve)

When invoked from `/z-debug` Phase 7:
- `concept_hints` come from `DEBUG.md ## Post-mortem` "Root cause" section (slugs in `Doc gap — <slug>` lines) plus `DEBUG.md ## Problem` `Relevant concepts:` line.
- `--source debug:<run-id>` is pre-filled by the caller.
- Salience guidance (prominent, load-bearing): **Default to Cancel** unless a genuinely novel anti-pattern, abandoned path, or decision rationale surfaced during root-cause investigation. A retro that produced no new institutional learning should emit zero memories.

When invoked from `/z-improve` Phase 7:
- `concept_hints` come from touched z-harness file paths (e.g. edits to `agents/foo.md` hint concept `foo`).
- `--source human_review:<username>` is pre-filled by the caller.
- Same salience guidance: **Default to Cancel** unless friction during the retro surfaced something worth recording.
