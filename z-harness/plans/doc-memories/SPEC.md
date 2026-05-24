# SPEC: doc-memories

Enrich the z-harness two-tier docs system with curated, dated, provenance-bearing "memories" in `docs/llm/<slug>.json`, compile a ripgrep-friendly `docs/llm/MEMORIES-FLAT.md` artifact, augment `doc-fetcher` with a second-phase grep over MEMORIES-FLAT.md, add a `/z-suggest-memory` skill called mandatorily from `/z-debug` and `/z-improve` retros, and extract memories into the human tier for two-tier sync.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/doc-memories/BRAINSTORM.md | 2026-05-23T05:45:50Z |
| RESEARCH.md | n/a | n/a |

## Schemas

### Memory entry (per-concept JSON `memories[]`)

```json
{
  "type": "anti_pattern | abandoned_path | incident | performance_trap | decision_rationale | open_question",
  "text": "<=200 chars",
  "source": "incident:<slug> | spec:<plan-slug>/<run-id> | debug:<run-id> | human_review:<name>",
  "date": "YYYY-MM-DD",
  "tags": ["<kebab-case>"],
  "expires": "YYYY-MM-DD"
}
```

- `type` — required enum.
- `text` — required, ≤200 chars, no newlines.
- `source` — required string, must match the strict-prefix regex `^(incident:[a-z0-9-]+|spec:[a-z0-9-]+/[A-Za-z0-9-]+|debug:[A-Za-z0-9-]+|human_review:[A-Za-z0-9_@.-]+)$`.
- `date` — required `YYYY-MM-DD`.
- `tags` — required (may be empty array). Each tag is kebab-case, validated against the recommended controlled set OR a free-form string flagged by `/z-maintain-docs` dedup pass.
- `expires` — optional. When present and `< today`, `/z-maintain-docs` flags the memory for review. **Lifecycle:** Keep leaves `expires` untouched (the same memory will re-flag on the next stale sweep — that's intentional; persistent staleness is signal). `/z-suggest-memory --edit` may rewrite `expires` as part of the edit. Delete removes the memory entirely. No automatic extension on Keep.

### Per-concept JSON addition

The existing `docs/llm/<slug>.json` shape gains one field:

```json
{
  "concept": "...",
  "last_updated": "...",
  "source_file": ["..."],
  "confidence": "...",
  "entry_points": [...],
  "depends_on": [...],
  "consumed_by": [...],
  "invariants": [...],
  "gotchas": [...],
  "memories": []
}
```

Default `memories: []`. Files without the field stay valid (loaders treat absence as empty).

### Controlled tag set (seed)

`correctness`, `perf`, `data-quality`, `schema`, `time-window`, `units`, `api-boundary`, `retry-loop`, `race-condition`, `dependency`, `deprecation`, `lossy-default`, `ux`, `observability`, `compliance`.

Free-form additions allowed. `/z-maintain-docs` dedup pass flags near-duplicates (`perf` vs `performance` vs `speed`) for human review; never auto-merges.

### TAGS.txt — canonical tag taxonomy

**Path:** `docs/llm/TAGS.txt`

**Format:** Plain text, one entry per line. Two sections separated by a single blank line. `# ...` line-comments are allowed anywhere.

**Section 1 — Controlled seed:** one tag per line (the 15-tag controlled set listed above). Comments and blank lines within the section are allowed.

**Section 2 — Aliases:** `<canonical> = <alias1>, <alias2>` lines. `<canonical>` must appear in section 1. Multiple aliases for the same canonical tag may be listed on one line (comma-separated) or across multiple lines.

Example `docs/llm/TAGS.txt`:

```
# Controlled tag seed — do not remove entries; add aliases in section 2.
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
perf = performance, speed
```

**Bootstrap:**
- `/z-init-docs` Phase 4 writes `docs/llm/TAGS.txt` with the 15-tag controlled seed plus an empty aliases section (with a header comment explaining the two-section format).
- `/z-suggest-memory` Phase 0 checks existence and bootstraps the file if missing (idempotent — same write logic as `/z-init-docs` Phase 4).

**Atomic write:** use the tmpfile + `os.replace()` pattern (same as MEMORIES-FLAT.md).

**Consumption contract:** `doc-updater` step 3.5 reads `docs/llm/TAGS.txt` at the start of the dedup pass and builds an alias→canonical map from section 2. For every memory's `tags[]`, any alias is rewritten in-place to its canonical before the memory is written, and one `tag_aliased` log line is emitted per substitution. The shared-prefix / Levenshtein heuristic then runs only on the remaining (unresolved) tag pairs; unresolved near-duplicates are surfaced as `TAG_COLLISIONS`. Pairs already listed in section 2 are therefore **never** surfaced as `TAG_COLLISIONS` — the alias resolution happens first and is transparent to the user.

### MEMORIES-FLAT.md line format

```
[<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: t1, t2)
```

One line per memory across all concepts. Self-contained (no nested headings). Example:

```
[strategy-router] [incident 2026-04-12] [incident:slippage-spike] cache invalidated on rebal so first 3 bars use stale spreads (tags: correctness, time-window)
[strategy-router] [abandoned_path 2026-02-08] [spec:rebalance-v2/run-3] tried sliding-window EMA, killed because regime lagged 4 bars (tags: signal, perf)
```

File header (first 2 lines, always present even when zero memories):
```
# MEMORIES-FLAT.md — generated by /z-maintain-docs; do not edit by hand.
# Format: [<slug>] [<TYPE> <DATE>] [<source>] <text> (tags: ...)
```

### MEMORIES-FLAT.md regeneration — shared helper

A single Python helper at `scripts/regenerate-memories-flat.py` is called by `/z-init-docs`, `/z-maintain-docs`, and `/z-suggest-memory`. Signature:

```
python3 scripts/regenerate-memories-flat.py --repo-root <abs path> [--dry-run]
```

Behavior: scans all `<repo-root>/docs/llm/*.json` except `INDEX.json`, extracts `memories[]` from each, emits the format above sorted lex by slug then by date descending. Writes to `docs/llm/MEMORIES-FLAT.md.tmp.<pid>.<random>` then `os.replace()` to the canonical path (atomic on POSIX). Exit codes: 0 ok, 1 input error, 2 write error. `--dry-run` prints the proposed file to stdout instead of writing.

Concurrent invocations are safe via the per-process tmpfile + atomic rename pattern; the last writer wins. No file lock — full regen is idempotent given a stable on-disk JSON state.

## Per-file changes

### `agents/doc-fetcher.md`

- Add `tags` to the documented inputs (optional list of kebab-case tags; validated against controlled set; unknown tags dropped with `unknown_tag` log line).
- New step 2.5 between current step 2 (pick concepts from INDEX.json) and step 3 (read per-concept JSONs): **ripgrep MEMORIES-FLAT.md**.
  - Build query regex: `(?i)<sanitized-query-tokens>` plus optional `(?i)tags:[^)]*<tag>` constraints for any `tags` the caller passed.
  - Attempt `rg --no-line-number --no-filename '<regex>' <repo_root>/docs/llm/MEMORIES-FLAT.md` via Bash. If exit 0 and ≥1 hit, parse the leading `[<slug>]` of each match.
  - If `rg` not on PATH (exit 127), fall back to a Python word-boundary scan: Read MEMORIES-FLAT.md, for each non-header line apply `re.search(r'\b<token>\b', line, re.IGNORECASE)` for each query token, keep lines matching all tokens. Preserve file order (do NOT re-sort — file is already sorted lex by slug + date desc). Emit `rg_missing_fallback` log line once per call. Word boundaries prevent "auth" from matching "author".
  - Merge memory-hit slugs into the INDEX.json-derived slug list. Deduplicate. Cap total slugs at 3 (preserve existing 8-Read budget).
- Concept synthesis section: when the chosen concept has memories matched by the ripgrep step, include them verbatim under a `**Memories:**` subsection of the concept block. Max 3 memories per concept in the synthesis (the highest-`date` first), bounded by the existing ≤2 KB total cap. **Truncation rule:** if including all matched memories at full `text` length would push synthesis past 1500 bytes, truncate each memory `text` to ≤120 chars with `…` and emit a `synthesis_truncated` log line. Concept structural content (entry_points, depends_on, etc.) is never truncated — memories yield first.
- Hard rules updated: ripgrep is a *soft dependency* — never fail the call if `rg` is missing.

Exported interface (unchanged externally except for new optional `tags` input):
```
Inputs: query (required), repo_root (required), depth (summary|standard|deep), relevant_concepts (optional), tags (optional)
Output: same synthesis shape; concept blocks may include a **Memories:** subsection
```

### `agents/doc-updater.md`

- LLM-tier JSON contract gains `memories: []` (default empty, preserved across refreshes — doc-updater MUST round-trip existing memories from the input JSON unless the caller explicitly says otherwise).
- Human-tier markdown contract gains a `## Memories` section (rendered after `## Edge cases / gotchas`, before `## Examples`). The section ALWAYS opens with a literal HTML comment so humans don't lose edits to the next refresh:
  ```
  ## Memories

  <!-- DO NOT EDIT this section by hand — regenerated from docs/llm/<slug>.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

  - **<DATE> <TYPE>** ([<source>](#)) — <text> _(tags: t1, t2)_
  ```
  Section is omitted entirely if `memories: []`.
- Procedure step 3 amended: when reading the current LLM doc, preserve existing `memories[]` verbatim. Never invent memories during a refresh — doc-updater is a structural agent, not an authoring one. Return shape adds `MEMORIES_PRESERVED: <N>` line so callers can verify round-trip.
- New procedure step 3.5: **tag dedup pass** (only invoked when caller passes `dedup_tags: true`). Scan all `memories[].tags` across the concept; if two tags differ only by stem (`perf` / `performance`, `cache` / `caching`) per a simple shared-prefix-≥4 + Levenshtein-≤2 heuristic, include them under a `TAG_COLLISIONS` block in the return for /z-maintain-docs to surface. Do not auto-merge.
- `TAG_COLLISIONS` block return shape (when present):
  ```
  TAG_COLLISIONS:
  [
    {"concept": "<slug>", "tag_a": "perf", "tag_b": "performance", "count_a": 5, "count_b": 2},
    ...
  ]
  ```
  Empty when no collisions detected; absent entirely when `dedup_tags: false`.

### `skills/z-init-docs/SKILL.md`

- Phase 4 gains a sibling step: after writing `docs/human/INDEX.md`, also write `docs/llm/MEMORIES-FLAT.md` with just the two-line header (no memory entries — none exist yet at init).
- README mention in Phase 6 summary: `docs/llm/MEMORIES-FLAT.md (regenerated by /z-maintain-docs)`.

### `skills/z-maintain-docs/SKILL.md`

- New Phase 4.5 (after Phase 4 Apply, before Phase 5 Finalize): **regenerate MEMORIES-FLAT.md** from all current `docs/llm/<slug>.json` files. Algorithm: read each `<slug>.json`, emit one line per memory in the format above, sort lines lexicographically by `[<slug>]` then by `[<DATE>]` descending. Always overwrite the file (full regen, no incremental).
- Phase 3 (Present diffs) gains a **Stale memories** section: any memory with `expires < today` OR `date < today - $Z_HARNESS_MEMORY_STALE_DAYS` (default 547) is listed with concept slug and one-line summary. For each stale entry, an inline `AskUserQuestion` offers **Keep** (default, no change) / **Edit** (hand off to `/z-suggest-memory --edit <concept> <index>`) / **Delete** (remove from the concept JSON's `memories[]`, then regenerate MEMORIES-FLAT.md). Stale memories never auto-delete — every removal is an explicit human action recorded in the run's events.jsonl as `memory_deleted`.
- Phase 3 also surfaces `TAG_COLLISIONS` from doc-updater dedup return (when `--audit` or per-run by default in the apply pass).
- `--apply` mode regenerates MEMORIES-FLAT.md unconditionally (covers the case where a memory was edited but no source file changed).

### `skills/z-debug/SKILL.md`

- Phase 7 (Post-mortem) — insert mandatory `/z-suggest-memory` invocation **after writing POSTMORTEM.md, before the action-items AskUserQuestion**. The skill call passes `concept_hints` derived from POSTMORTEM.md "Root cause" section (slugs already mentioned in `Doc gap — <which docs/llm/ concept>`) plus PROBLEM.md `relevant_concepts` if present. The call may emit zero memories; the *call* is mandatory, the *result* is not. **Salience guidance (load-bearing — fights the "padding to satisfy the rule" failure mode flagged by Gemini):** the /z-debug skill body MUST instruct the orchestrator that the default action is **Cancel (emit zero)** unless a genuinely novel anti-pattern / abandoned path / decision rationale surfaced in the root-cause investigation. "Cancel" is a first-class outcome, not a fallback.
- PROBLEM.md template (Phase 1) gains a `Relevant concepts: <slug>, <slug>` line so /z-suggest-memory has a hint source.
- Log a `suggest_memory_called` event with `{memories_written: N, concept: <slug-or-empty>}`.

### `skills/z-improve/SKILL.md`

- Phase 7 (Apply accepted edits) — insert mandatory `/z-suggest-memory` invocation after the last edit is applied and diffs are written. `concept_hints` derived from the touched z-harness file paths (e.g. edits to `agents/foo.md` hint concept `foo`). Mandatory call, optional result. **Salience guidance:** same as /z-debug — default to **Cancel** unless a friction signal in the retro surfaced a new anti-pattern or decision rationale worth recording.
- Log a `suggest_memory_called` event same as /z-debug.

### `skills/z-suggest-memory/SKILL.md` (NEW)

```markdown
---
name: z-suggest-memory
description: Authoring skill for the docs/llm/ memory layer. Called mandatorily from /z-debug post-mortem and /z-improve retro. Validates input against the memory schema, writes to docs/llm/<slug>.json, regenerates docs/llm/MEMORIES-FLAT.md, optionally extracts into docs/human/<slug>.md.
argument-hint: [--concept <slug>] [--concept-hints <slug>,<slug>] [--source <prefix:ref>] [--edit <slug> <index>] [--delete <slug> <index>] [--dry-run]
---
```

Phases:
1. **Preflight.** Verify `docs/llm/INDEX.json` exists. If not, `STATUS: no_docs`, exit cleanly (caller logs but does not fail).
2. **Resolve target concept.** Read `concept_hints` from args. AskUserQuestion options:
   - First hint (pre-selected, recommended)
   - Other existing concept (filterable select)
   - Create new concept — skill writes a **stub** directly: empty `docs/llm/<new-slug>.json` with `{"concept": "<new-slug>", "last_updated": "<today>", "source_file": [], "confidence": "low", "entry_points": [], "depends_on": [], "consumed_by": [], "invariants": [], "gotchas": [], "memories": []}` and a stub `docs/human/<new-slug>.md` containing only `# <Title>\n\n> Stub — populate via /z-maintain-docs.`. Adds entry to `docs/llm/INDEX.json` with `confidence: low`. Does NOT invoke `/z-init-docs` (which is scoped to source-driven generation). The stub is the seed; full doc population happens later when source files exist.
   - Cancel (writes nothing, returns `STATUS: skipped, MEMORIES_WRITTEN: 0`) — **first-class outcome, default when no salient memory exists**.
3. **Collect memory.** AskUserQuestion / free-text: `type` (enum chips), `text` (≤200 chars, validated), `tags` (controlled-set chips + free-form input), `source` (caller supplies via arg or skill derives from run context — `/z-debug` passes `debug:$RUN`, `/z-improve` passes `human_review:$USER`).
4. **Validate.** Schema check: `text` length, `tags` kebab-case, `source` regex, `date` defaults to today. Reject with reason if invalid; loop back to step 3.
5. **Write.** Three mutually-exclusive modes per invocation:
   - **Append** (default) — Read `docs/llm/<slug>.json`, push to `memories[]`, atomic write.
   - **`--edit <slug> <index>`** — Read concept JSON, replace `memories[index]` with the newly-collected memory. Reject if `<index>` out of range. Increments an internal `mutation_count` event but does not version history (deletes overwrite, edits overwrite).
   - **`--delete <slug> <index>`** — Read concept JSON, splice out `memories[index]`, atomic write. Skip step 3 (collection) entirely when this flag is present.
   `--dry-run` prints the patch and skips the write in all three modes.
6. **Regenerate MEMORIES-FLAT.md** via `scripts/regenerate-memories-flat.py`.
7. **(Optional) Refresh human tier.** Spawn a `doc-updater` call in `mode: write` for the just-edited concept to re-emit the `## Memories` section. Caller decides via `--refresh-human` flag (default true).
8. **Return.**
   ```
   STATUS: ok | skipped | bad_input | no_docs
   CONCEPT: <slug>
   MEMORIES_WRITTEN: <N>
   WROTE: docs/llm/<slug>.json
          docs/llm/MEMORIES-FLAT.md
          [docs/human/<slug>.md]  // if refresh-human ran
   ```

Hard rules:
- **One mutation per invocation.** Either one append, one edit, or one delete — never combined. Callers re-invoke for additional changes.
- **No emojis** in memory text.
- **Reject** text with newlines or that exceeds 200 chars.

### `commands/z-suggest-memory.md` (NEW)

Thin router pointing to the skill — mirrors the pattern of `commands/z-brainstorm.md`.

### `README.md`

Add `/z-suggest-memory` to the skills table with one-line description.

## Invariants

- **Backward compatibility.** Every existing `docs/llm/<slug>.json` parses without modification (memories defaults to empty).
- **LLM tier is authoritative.** `docs/human/<slug>.md` `## Memories` section is regenerated from the LLM tier; human edits there are not round-tripped.
- **Mandatory call, optional result.** /z-debug and /z-improve MUST invoke /z-suggest-memory; users may emit zero memories.
- **doc-fetcher cap preserved.** ≤2 KB synthesis, ≤8 Reads. Ripgrep is a Bash subprocess, not a Read.
- **No auto-deletion of memories.** /z-maintain-docs flags stale; humans decide.
- **Ripgrep is soft.** Substring fallback when `rg` missing; never fail.

## Edge cases

- **Empty MEMORIES-FLAT.md.** First /z-init-docs run, no concepts have memories yet. File has only the two-line header; doc-fetcher's ripgrep returns zero hits — falls through to INDEX.json-only behavior unchanged.
- **Tag collision.** Author writes `tags: ["performance"]` when `perf` already exists. doc-updater dedup pass surfaces the collision in /z-maintain-docs Phase 3; human picks the canonical form. /z-suggest-memory does NOT block authoring on collision.
- **Concept doesn't exist.** /z-suggest-memory user picks "Create new concept" — hands off to /z-init-docs --scope <new-slug>, which creates `docs/llm/<new-slug>.json` (with empty memories) and `docs/human/<new-slug>.md`, then control returns to /z-suggest-memory step 3 with the new slug.
- **MEMORIES-FLAT.md not in repo yet** (caller is on a pre-doc-memories branch). doc-fetcher detects missing file, skips the ripgrep phase silently. Log line: `memories_flat_missing` (no error).
- **`source: incident:<slug>` references an incident that doesn't exist.** /z-suggest-memory does NOT validate references — too coupled. The strict-prefix regex only checks structural shape. Human is responsible for ref correctness.
- **Caller passes `tags: ["bogus-tag"]` to doc-fetcher.** Unknown tag is dropped from the ripgrep regex, `unknown_tag` log line emitted, query proceeds with remaining (or zero) tags.
- **Memory `text` exceeds 200 chars at /z-suggest-memory.** Skill rejects, prompts user to trim. No silent truncation.

## Failure modes

- **doc-fetcher Bash ripgrep call fails (non-0, non-127 exit).** Treat as zero hits, log `rg_error`, proceed. Never propagate the error.
- **MEMORIES-FLAT.md write race during /z-maintain-docs.** Atomic write via `tmp + rename` pattern.
- **doc-updater drops memories on refresh.** Detected by the new `MEMORIES_PRESERVED: <N>` return line; /z-maintain-docs Phase 3 compares N against the **baseline = pre-write count of `memories[]` in the existing `docs/llm/<slug>.json` on disk** and surfaces a `memories_lost` warning before apply. Warning is advisory (does not block apply); the contract already prohibits doc-updater from inventing memories, so this is round-trip verification.
- **doc-updater returns `STATUS: not_enough_info` or errors.** /z-maintain-docs Phase 4 skips writing this concept; the on-disk JSON (including its `memories[]`) is **left untouched** at its prior state. Memories survive by inaction — no recovery path needed. Orchestrator surfaces the skip to the user via the existing Phase 4 status block.

## Tests / acceptance

Per D11 — fixture-based unit tests under `z-harness/doc-memories/test-fixtures/` (created by T012 below):

1. **`doc-updater` fixture** — synthetic concept JSON with 3 memories; assert refresh round-trips them and human markdown contains the `## Memories` section.
2. **`doc-fetcher` fixture** — synthetic INDEX.json + MEMORIES-FLAT.md; assert query "stale spreads" returns the strategy-router slug from the ripgrep step.
3. **`doc-fetcher` ripgrep-missing fallback** — invoke via `env -i PATH=/usr/bin` (rg not on PATH); assert substring fallback returns the same slug.
4. **`/z-suggest-memory` schema rejection** — feed text >200 chars; assert STATUS: bad_input and no write.
5. **MEMORIES-FLAT.md format** — golden-file test for the line format spec.
6. **Adversarial regex fixtures.** Concept slugs containing `[`, `]`, `*`, `\`, `$`; memory `text` containing regex metacharacters and unicode; tag values with hyphens-vs-underscores. Assert both ripgrep and substring fallback return correct results (or correctly empty) without crashing. Covers Gemini's "regex drift" blocker.
7. **Concurrent regen safety.** Two `scripts/regenerate-memories-flat.py` invocations spawned simultaneously via `&`; assert the resulting file is well-formed (either run's output, never a partial mix). Validates the tmpfile + rename pattern.

No end-to-end test against a real `docs/llm/` (per ship-blind decision).
