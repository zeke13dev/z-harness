# SPEC — postmortem-memory-nudge

## Overview

Instrument the memory-review pipeline so its current behavior becomes legible:
four explicit terminal states (`not_applicable`, `skipped_broken_context`,
`ran_empty`, `needs_user`) emitted as a dedicated `memory_review_terminal`
event from `scripts/run-memory-review.sh` and the calling SKILL.md phases.
Surface the new event in `/z-stats` Phase 4b. Push-notify the user when the
pipeline silently fails because of broken context. Wire `/z-debug` Phase 9b
to dispatch the review-agent against the Post-mortem section so the
highest-signal phase in the harness stops producing zero memories. Reconcile
the spec-or-debug input shape of the review-agent. Verify qt-bot remote has
`docs/llm/` initialized. Smoke-test `/z-improve` → `/z-suggest-memory`.

## Planning Inputs

| Artifact | Path | generated_at |
|----------|------|--------------|
| BRAINSTORM.md | z-harness/postmortem-memory-nudge/BRAINSTORM.md | 2026-05-27T04:22:38Z |
| RESEARCH.md | n/a | n/a |

## Goals (carried from BRAINSTORM Codex framing)

1. Replace the current opaque skip-and-soft-fail behavior with a four-state
   terminal taxonomy emitted as a structured event.
2. Make every Phase 9 / Phase 7 outcome visible in `/z-stats` Phase 4b.
3. Push-notify exactly once per `(slug, skip_reason)` when the pipeline
   silently fails because of broken context.
4. Wire `/z-debug` Phase 9b — the densest-signal phase in the harness — to
   dispatch the review-agent against DEBUG.md.
5. Reconcile the agent input contract so `parent_command: debug` is
   first-class.
6. Confirm qt-bot remote has `docs/llm/INDEX.json` + `docs/llm/TAGS.txt` and
   recommend `/z-init-docs` on remote if not.
7. Verify `/z-improve` → `/z-suggest-memory` actually fires end-to-end.

## Non-goals

- No new `/z-postmortem` skill. (Gemini's brainstorm proposal rejected.)
- No Haiku→Sonnet model upgrade for review-agent. (Deferred until
  instrumentation shows the agent is reaching execution and producing zero
  candidates.)
- No auto-run policy. (Codex framing: measure first.)
- No retroactive event migration. (`/z-stats` Phase 4b reads both shapes.)
- No candidate-quality UX redesign.

## Per-file detailed spec

### `scripts/run-memory-review.sh`

**Existing surface (preserved):**
- Args: `<RUN> <parent_command>`
- Stdout line 1: `STATUS: ready | STATUS: skipped <reason>`
- Stdout lines 2-4 (when ready): absolute paths to cumulative.diff, SPEC.md, TAGS.txt
- Exit 0 always

**Additions:**

1. Accept `parent_command: debug` as a third valid value (alongside
   `implement-all`, `review-all`). For `debug`, skip the
   `all_tasks_skipped` check (no TASKS.md `[x]` semantics apply), and
   additionally require `$BASE/DEBUG.md` to exist and contain
   `status: shipped` in its frontmatter. If absent, emit
   `STATUS: skipped debug_not_shipped` and the corresponding terminal event.
2. Emit a `memory_review_terminal` event at every exit path (replacing the
   inconsistent `phase_end`/`review_agent_failed` emissions). Payload:
   ```json
   {
     "state": "not_applicable|skipped_broken_context|ran_empty|needs_user",
     "skip_reason": "<one of the STATUS suffixes>|null",
     "parent_command": "implement-all|review-all|debug",
     "candidates": 0,
     "accepted": 0,
     "slug": "<$Z_HARNESS_SLUG or null>"
   }
   ```
   The script emits the event with `candidates: 0` and `accepted: 0` for
   the skip states it owns. The orchestrator updates the event (or emits a
   second one) for `ran_empty` and `needs_user` after agent dispatch and
   user gate respectively.
3. STATUS → terminal-state mapping (script-owned):
   | STATUS | state | skip_reason |
   |---|---|---|
   | `skipped empty_diff` | `not_applicable` | `empty_diff` |
   | `skipped all_tasks_skipped` | `not_applicable` | `all_tasks_skipped` |
   | `skipped debug_not_shipped` | `not_applicable` | `debug_not_shipped` |
   | `skipped tags_missing` | `skipped_broken_context` | `tags_missing` |
   | `skipped no_plan_dir` | `skipped_broken_context` | `no_plan_dir` |
   | `skipped missing_args` | `skipped_broken_context` | `missing_args` |
   | `ready` | (orchestrator emits later) | null |
4. For `parent_command: debug` and `STATUS: ready`, additionally emit a
   **fifth** stdout line: the absolute path to DEBUG.md. Lines 1-4 remain
   the existing contract (STATUS / cumulative.diff / SPEC.md / TAGS.txt).
   Line 5 is debug-only. Orchestrators MUST parse defensively:
   ```bash
   mapfile -t LINES < <(bash scripts/run-memory-review.sh "$RUN" "$PARENT")
   STATUS="${LINES[0]}"
   DIFF="${LINES[1]:-}"
   SPEC_PATH="${LINES[2]:-}"
   TAGS_PATH="${LINES[3]:-}"
   DEBUG_MD="${LINES[4]:-}"   # empty unless parent_command == debug
   ```
5. **spec_path conditional emission.** If `$BASE/SPEC.md` does not exist
   (fresh `/z-debug` runs may have no SPEC), emit an empty line for line 3
   rather than the path. The agent prompt documents that empty
   `spec_path` means "no SPEC available; treat the run as self-contained."
6. Stop emitting `review_agent_failed` from this script for `tags_missing`.
   That event kind is reserved for actual agent-dispatch failures owned by
   the orchestrator.

7. **Gate change for `parent_command: debug`** (replaces earlier frontmatter
   draft). DEBUG.md has no YAML frontmatter; instead, before the helper
   reads `$BASE/DEBUG.md` at all, the orchestrator caller (Phase 10 of
   `/z-debug`) is responsible for invoking this helper only on the
   `status: shipped` finalize branch. The helper itself only checks that
   `$BASE/DEBUG.md` **exists and is readable** (`[[ -r "$DEBUG_MD" ]]`); if
   not, emit `STATUS: skipped debug_md_missing` (terminal state:
   `not_applicable`). The "shipped vs abandoned" gate moves to the caller.

**Invariants:**
- Always exit 0 (skip is success).
- One `memory_review_terminal` event per invocation (the script's exit), no more, no less.
- Never write outside `$BASE/archive/$RUN/`.
- Never mutate INDEX.json or memory files.

**Edge cases:**
- `$Z_HARNESS_SLUG` unset: include `"slug": null` in the event.
- `$ANTIGRAVITY_PLUGIN_ROOT` and `$CLAUDE_PLUGIN_ROOT` both unset:
  `LOG_EVENT` resolves to `$REPO_ROOT/scripts/log-event.sh` (current
  fallback, unchanged).
- DEBUG.md with no frontmatter: `grep -E '^status:[[:space:]]*shipped'` is
  used; absence treated as not shipped.

---

### `agents/review-agent.md`

**Existing surface (preserved):**
- Input fields: `run_dir`, `cumulative_diff_path`, `spec_path`, `tags_path`,
  `index_path`, `run_id`, `parent_command`
- Output: single fenced ```json block with `[0..3]` candidate objects

**Additions:**

1. Add optional input field: `debug_md_path` (string, absolute path; absent
   for `implement-all` and `review-all`).
2. Update the input contract section of the agent definition to state:
   > When `parent_command: debug`, `debug_md_path` is the primary artifact
   > the agent reasons over. `spec_path` is supplementary context for
   > recognizing affected invariants. For `implement-all` and `review-all`,
   > `spec_path` is primary and `debug_md_path` is unset.
3. Add `debug` to the valid `parent_command` enum.
4. Add to the agent's candidate-generation guidance:
   > For `parent_command: debug`, filter candidates for generalizable
   > invariants, root-cause patterns, and "why we didn't catch it" gaps.
   > Single-run patches and fix-specific minutiae are NOT memories.

**Invariants (unchanged):**
- Agent never writes.
- Output is exactly one fenced JSON block.
- Hard cap of 3 candidates.
- Candidate tags must come from `TAGS.txt` unless free-form is justified.

---

### `skills/z-implement-all/SKILL.md` (Phase 9 wiring)

**Changes:**

1. Read both `STATUS:` line AND the new contract of `run-memory-review.sh`:
   the script now owns terminal-event emission for skip states. Phase 9
   itself emits the terminal event ONLY for the post-dispatch states
   (`ran_empty`, `needs_user`).
2. After review-agent dispatch (and after the user-gate loop, if any),
   emit EXACTLY ONE `memory_review_terminal` event per invocation. The
   helper script also emits at most one (for skip states it owns).
   Net total per invocation: exactly one. (Earlier draft of "emit two
   events for the needs_user path" was rejected as it breaks downstream
   row-counting.) The mid-phase signal that "candidates exist and user
   gate is pending" remains the existing `memory_candidates_ready`
   push-notify event, which is distinct from `memory_review_terminal`.

   - Agent returns `[]` → emit terminal with `state: ran_empty`,
     `candidates: 0`, `accepted: 0`.
   - Agent returns ≥1 candidate, after gate loop completes → emit terminal
     with `state: needs_user`, `candidates: N`, `accepted: <final count>`.
3. Push-notify policy (D11):
   - For `state: skipped_broken_context`: push-notify the user
     ("Memory review skipped on `<slug>`: `<skip_reason>`. Fix to re-enable
     memory candidates."), deduped per `(slug, skip_reason)` for the
     remainder of the session. Honor `Z_HARNESS_NOTIFY=off`.
   - For `state: not_applicable`: no push-notify (legitimately nothing to
     learn from).
   - For `state: ran_empty`: no push-notify.
   - For `state: needs_user`: keep the existing `memory_candidates_ready`
     push-notify.
4. Dedup implementation: maintain `$BASE/.notify-dedup-session` (per-slug,
   per-top-level-command) as a file with `<slug>:<skip_reason>` lines
   appended. The top-level command (`/z-implement-all`, `/z-review-all`,
   `/z-debug`) **clears this file at the start of its invocation** (`rm -f
   "$BASE/.notify-dedup-session"`) so that genuine re-occurrences of the
   same skip across separate runs each get one notify. Within a single
   top-level invocation, subsequent Phase 9 / Phase 7 / Phase 9b fires
   with the same `(slug, skip_reason)` are silenced. Before push-notify,
   grep the file; skip if match exists. After push-notify, append.

**Invariants:**
- Orchestrator never re-runs `run-memory-review.sh` on the same RUN.
- The two events emitted by the orchestrator (initial `needs_user` and
  post-gate `needs_user` with final `accepted`) both carry the same
  `parent_command` and `slug`; consumers de-dup on the second one.

---

### `skills/z-review-all/SKILL.md` (Phase 7 wiring)

Same changes as `skills/z-implement-all/SKILL.md` Phase 9. The
`parent_command: review-all` is already in use and unchanged.

---

### `skills/z-debug/SKILL.md` — Phase 10 internal step (memory review)

**Location:** Inside Phase 10 (Finalize), after the existing `debug_run_end`
event is logged, **only on the `status: shipped` branch.** This replaces
the earlier "Phase 9b between Phase 9 and Phase 10" design — DEBUG.md has
no YAML frontmatter so the previous gate didn't work. The "shipped vs
abandoned" gate now lives in Phase 10's existing branch.

**Behavior:**

1. **Branch gate:** Run only when Phase 10 has logged
   `debug_run_end` with `status: shipped`. Skip silently on `status:
   abandoned` (no telemetry — abandoned debug sessions intentionally
   produce no memory candidates).
2. **Clear dedup file at top of Phase 10:** `rm -f
   "$BASE/.notify-dedup-session"`. (Each top-level `/z-debug` invocation
   gets a fresh notify de-dup state.)
3. **Helper call:** `bash scripts/run-memory-review.sh "$RUN" "debug"`.
   Parse with `mapfile -t LINES`. STATUS in `LINES[0]`, DEBUG.md path in
   `LINES[4]`.
4. **Skip path:** If `STATUS: skipped *`, the helper has already emitted
   the terminal event. Honor the D11 push-notify policy via the dedup
   file.
5. **Ready path:** Dispatch review-agent with `parent_command: debug` and
   the input fields: `cumulative_diff_path`, `spec_path` (may be empty
   string), `tags_path`, `debug_md_path` (from `LINES[4]`).
6. **Candidate handling:** Same AskUserQuestion loop as Phase 9, capped at
   3 candidates. Source string: `incident:debug-<slug>-<RUN>`.
7. **Telemetry:** Single `memory_review_terminal` event after the user
   gate (matches D2 invariant of one event per invocation).

**Edge cases:**
- DEBUG.md missing or unreadable → helper emits `STATUS: skipped
  debug_md_missing` (terminal state `not_applicable`).
- `/z-debug` invoked in a slug-dir that already had `/z-implement-all`
  Phase 9 fire: the dedup file is cleared at Phase 10 entry so re-firing
  the same `(slug, skip_reason)` will notify again. That's correct — a
  separate top-level command warrants a fresh notify decision.
- `/z-debug` aborted before Phase 10: the memory-review step never fires,
  no events emitted.

**Phase 9b naming note:** The earlier draft called this "Phase 9b." Because
the gate moved into Phase 10, this is now an internal step within
Phase 10. Existing references to "Phase 9b" in this SPEC are kept for
search continuity but the implementation lives in Phase 10.

---

### `skills/z-stats/SKILL.md` — Phase 4b update

**Changes:**

1. Phase 4b currently reads `review_agent_call` events. Extend to also read
   `memory_review_terminal` events.
2. Add a "Memory review terminal states (last 10 runs)" section to the
   Phase 4b output:
   ```
   Memory review terminal states (last 10 runs across all parents):
     needs_user           4    (of which accepted: 6 memories)
     ran_empty            2
     not_applicable       3    (empty_diff: 2, all_tasks_skipped: 1)
     skipped_broken_context 1    (tags_missing: 1)
   ```
3. Cross-parent: group by `parent_command` if `--by-parent` flag is passed
   (defer the flag itself to a future task if scope grows; basic
   aggregation is in-scope now).
4. Read both old and new event shapes (D12). Null-safe defaults required —
   old `phase_end` events may be missing fields. For backward compat:
   - `phase_end` with `name == "memory_review"` and `skip_reason` field
     present → treat as `state: not_applicable` (for
     `empty_diff`/`all_tasks_skipped`) or `state: skipped_broken_context`
     (for `tags_missing`).
   - `phase_end` with `name == "memory_review"` and NO `skip_reason` →
     treat as `state: ran_empty, skip_reason: null` (best-effort
     interpretation; can't recover further detail).
   - `review_agent_failed` with `reason: tags_missing` → treat as
     `state: skipped_broken_context, skip_reason: tags_missing`.
   - All other `review_agent_failed` or `review_agent_malformed` events
     are NOT remapped to terminal states — they remain orthogonal failure
     classes and are surfaced separately in Phase 4b's "Agent failures"
     subsection.

5. **"Last 10 runs" definition.** "Run" = unique `run` field value
   (e.g., `20260527T045853Z-postmortem-memory-nudge`). The aggregation jq:
   ```bash
   jq -s 'map(select(.kind == "memory_review_terminal"))
          | group_by(.run)
          | map({run: .[0].run, ts: .[0].ts, terminal: .[-1]})
          | sort_by(.ts) | reverse | .[0:10]' \
     z-harness/metrics.jsonl
   ```
   When multiple terminal events for the same `run` exist (shouldn't
   happen per the one-event-per-invocation invariant, but defensive),
   prefer the last one as authoritative.

---

### `commands/z-debug.md`

Mirror the `skills/z-debug/SKILL.md` Phase 9b additions. Per the
canonical-source convention from doc-fetcher (SKILL.md is canonical),
keep the changes in lockstep.

---

### qt-bot remote check (one-shot probe — no in-repo file)

Implementation lives in the qt-bot-remote skill invocation at task time;
no in-repo artifact. Acceptance: SSH command runs, returns presence/absence
of `~/dev/qt-bot/docs/llm/INDEX.json` and `~/dev/qt-bot/docs/llm/TAGS.txt`,
recommendation text emitted to the user.

---

### `/z-improve` smoke-test (one-shot manual run — no in-repo file)

Implementation: at finalize, run `/z-improve postmortem-memory-nudge` and
verify a `suggest_memory_called` event lands in
`z-harness/postmortem-memory-nudge/archive/<RUN>-improve/events.jsonl`.
Acceptance: event exists with non-empty `concept` field.

## DRY / KISS / SOLID

- **DRY:** Single helper (`run-memory-review.sh`) handles all three
  `parent_command` values via a small switch. No sibling helpers.
- **KISS:** The 4-state taxonomy is a flat enum, not a hierarchy. One
  event kind, one payload schema, one consumer in `/z-stats`. Push-notify
  uses a flat dedup file, not a database.
- **SOLID (single-responsibility):** The helper script owns skip-decision
  logic and emits one terminal event. The orchestrator owns post-dispatch
  state. The review-agent owns candidate generation. `/z-stats` owns
  aggregation. No layer reaches across.

## Invariants summary

1. **Exactly one `memory_review_terminal` event per Phase 9 / Phase 7 /
   Phase 10-memory-review-step invocation.** Either the helper script
   emits it (skip path) OR the orchestrator emits it (after user gate),
   never both. Downstream consumers can count rows safely.
2. Push-notify on `skipped_broken_context` honors `Z_HARNESS_NOTIFY=off`
   and dedups per `(slug, skip_reason)` for the lifetime of one top-level
   command invocation. Dedup file (`$BASE/.notify-dedup-session`) is
   cleared at the start of each `/z-implement-all` / `/z-review-all` /
   `/z-debug` invocation.
3. The `/z-debug` memory-review step fires only on Phase 10's `status:
   shipped` branch (gated in the caller, not the helper).
4. `agents/review-agent.md` accepts `parent_command: debug` and the
   optional `debug_md_path` input. `spec_path` may be empty for fresh
   debug runs; agent prompt handles that case. No breaking change to
   existing `implement-all` / `review-all` callers.
5. No memory is written without the orchestrator dispatching
   `/z-suggest-memory --from-candidate-json` — the single-writer invariant
   is preserved.
6. `run-memory-review.sh` stdout contract is forward-compatible: lines 1-4
   are fixed (STATUS / cumulative.diff / SPEC.md / TAGS.txt), line 5 is
   debug-only (DEBUG.md). Orchestrator parses with defensive `mapfile`.
