# TASKS — memory-self-improve-loop

Generated from SPEC.md + PLAN.md (2026-05-25, slug `memory-self-improve-loop`, v1 review-agent).

---

## T001 — Verify `/z-suggest-memory` non-interactive batch capability

**Files touched:** `commands/z-suggest-memory.md`, `skills/z-suggest-memory/SKILL.md` (read-only verification; possibly extended in T002).

**Dependencies:** none.

**Description:** Read `commands/z-suggest-memory.md` end-to-end. Document precisely which CLI flags suppress which interactive Phase. Confirm whether `--type`, `--text`, `--tags`, `--date`, `--expires` flags exist alongside `--concept`/`--source`/`--dry-run`. If they do NOT exist, T002 is required. If they DO exist, T002 is unnecessary and TASKS.md should be amended to mark T002 SKIP.

**Acceptance criteria:**
- A short note appended to SPEC.md (under `## Known consultation gap`) documenting findings: which flags are present, which are missing.
- Decision: T002 needed (yes/no) recorded.

**Status:** `[ ]`

**Complexity:** low

---

## T002 — Extend `/z-suggest-memory` with `--from-candidate-json` flag (contingent)

**Files touched:** `commands/z-suggest-memory.md`, `skills/z-suggest-memory/SKILL.md`.

**Dependencies:** T001.

**Description:** ONLY IF T001 finds the existing flags insufficient: add a `--from-candidate-json <path>` flag (or a more complete flag set: `--type`, `--text`, `--tags`, `--date`, `--expires`) to `/z-suggest-memory` so the orchestrator can drive an accept without an interactive collection phase. The flag should:
- Read a single JSON object from the path (or stdin) matching the candidate schema in SPEC.md.
- Populate all the fields that Phases 3a-3e would otherwise collect.
- Still validate the assembled memory object against the schema.
- Still write atomically and regenerate MEMORIES-FLAT.md.
- Still respect `--dry-run`.

**Acceptance criteria:**
- New flag documented in `commands/z-suggest-memory.md` argument-hint section.
- Phases section updated to note the bypass.
- Manual dry-run test: `echo '{...candidate...}' | /z-suggest-memory --concept <slug> --from-candidate-json - --dry-run` returns `STATUS: ok (dry-run)`.
- If the flag was unnecessary per T001, this task is marked SKIP with reason "existing flags sufficient".

**Status:** `[ ]`

**Complexity:** medium

**DOCS:** z-suggest-memory

---

## T003 — Author `agents/review-agent.md`

**Files touched:** `agents/review-agent.md` (NEW).

**Dependencies:** none (no caller wired yet).

**Description:** Create the Haiku subagent file per SPEC.md "agents/review-agent.md" section. Frontmatter, Role, Inputs-from-caller, Procedure (with the four `candidate_kind` signal patterns adapted from Hermes), Output contract (single fenced ```json block schema), Hard rules. No caller wires this in yet — file is inert until T005.

**Acceptance criteria:**
- File exists with required frontmatter (`name`, `description`, `tools`, `model: haiku`).
- Frontmatter description ≤1024 chars.
- Output-contract section shows the exact JSON schema from SPEC.md.
- Hard-rules section explicitly states "no write tools; do not call /z-suggest-memory directly".
- Naming-anti-pattern bans lifted from Hermes documented in body (no PR-number, no library-alone, no session-specific, no negative-capability, no model-specific).

**Status:** `[ ]`

**Complexity:** low

**DOCS:** review-agent

---

## T004 — Author `scripts/run-memory-review.sh`

**Files touched:** `scripts/run-memory-review.sh` (NEW).

**Dependencies:** none (callers added in T005, T006).

**Description:** Implement the shell helper per SPEC.md "scripts/run-memory-review.sh" section. Skip-conditions check (empty diff, all_tasks_skipped — NOT halted-early), cumulative diff capture (truncate to 5000 lines), TAGS.txt presence check, STATUS line output, exit 0 on all paths.

**Acceptance criteria:**
- `bash scripts/run-memory-review.sh <RUN> implement-all` prints `STATUS: ready` and three absolute paths when conditions are met.
- Prints `STATUS: skipped empty_diff` and exits 0 when there is no diff.
- Prints `STATUS: skipped all_tasks_skipped` and exits 0 when TASKS.md exists with zero `[x]`.
- Prints `STATUS: skipped tags_missing` when `docs/llm/TAGS.txt` is absent.
- chmod +x set.
- Manual smoke-test with a synthetic RUN_DIR confirms each branch.

**Status:** `[ ]`

**Complexity:** medium

---

## T005 — Wire Phase 9 into `commands/z-implement-all.md`

**Files touched:** `commands/z-implement-all.md`.

**Dependencies:** T003, T004 (agent + helper exist).

**Description:** Insert a new `## Phase 9 — Memory review (auto)` section after the existing Finalize block (after the existing primary-deliverable push-notify) and before "Hard rules". Body follows SPEC.md /z-implement-all section exactly: helper invocation, STATUS parse, Agent dispatch with full prompt, JSON parse with fenced-block extraction, malformed-output soft-skip, empty-candidates quiet exit, candidate persistence to `$RUN_DIR/memory-candidates.jsonl`, `review_agent_call` event emit, sequential AskUserQuestion per candidate (max 3 candidates × 4 options: Accept / Edit / Skip-with-reason / Skip-all-remaining), per-Accept `/z-suggest-memory` dispatch, final `phase_end` accounting.

**Acceptance criteria:**
- New Phase 9 section present at the right insertion point (after Finalize push-notify, before Hard rules).
- All event-kind names match SPEC.md (`memory_candidates_ready`, `review_agent_call`, `review_agent_failed`, `review_agent_malformed`, `review_candidate_skipped`, `review_skip_all`).
- Skip path emits `phase_end` with `skipped: true, skip_reason: <reason>` and exits phase quietly (no notification).
- `/z-suggest-memory` dispatch uses `--source "incident:<RUN>"` and the flags identified in T001/T002.

**Status:** `[ ]`

**Complexity:** high

---

## T006 — Wire new Phase into `commands/z-review-all.md`

**Files touched:** `commands/z-review-all.md`.

**Dependencies:** T003, T004.

**Description:** Insert a new `## Phase 7 — Memory review (auto)` section after Phase 6's `.review_state.json` cleanup and after the existing Phase 6 push-notify, before Hard rules. Body identical to T005 EXCEPT `parent_command: review-all` in the Agent dispatch and `spec_path: $BASE/SPEC.md` (which exists post-/z-plan).

**Acceptance criteria:**
- New Phase 7 section present at the right insertion point.
- Body structurally identical to /z-implement-all Phase 9 (same event emissions, same skip-logic, same dispatch shape).
- Differs only in `parent_command` literal and any /z-review-all-specific phrasing.

**Status:** `[ ]`

**Complexity:** high

---

## T007 — Mirror command additions in `skills/z-implement-all/SKILL.md` and `skills/z-review-all/SKILL.md`

**Files touched:** `skills/z-implement-all/SKILL.md`, `skills/z-review-all/SKILL.md`.

**Dependencies:** T005, T006.

**Description:** These skill files are bundled copies of the commands. Mirror the new phase additions verbatim into both skill files at the equivalent insertion points.

**Acceptance criteria:**
- Diff between command and skill file (modulo skill-file frontmatter / preamble) shows the new phase content matches.
- No accidental drift in event-kind names or schema text.

**Status:** `[ ]`

**Complexity:** low

---

## T008 — Extend `commands/z-stats.md` Phase 4 + new Phase 4b

**Files touched:** `commands/z-stats.md`, `skills/z-stats/SKILL.md`.

**Dependencies:** none (works against any future events; backward-compatible).

**Description:** In Phase 4 (Recent halts), extend the jq filter to also include `kind == "review_agent_failed"` and `kind == "review_agent_malformed"`. Add a new Phase 4b "Recent memory-review activity":
```bash
jq -c 'select(.kind == "review_agent_call")' "$METRICS" | tail -10
```
Output format: `<ts> review-agent <parent_command>: candidates=<N> accepted=<A> tokens=<input>/<output>`.

**Acceptance criteria:**
- Phase 4 jq filter extended; existing halt-event detection still works.
- Phase 4b inserted between Phase 4 and Phase 5.
- Both command and skill file updated.
- /z-stats run against a metrics.jsonl containing review_agent_call events produces the new line(s).

**Status:** `[ ]`

**Complexity:** low

**DOCS:** z-stats

---

## T009 — Document `--source "incident:<RUN>"` convention in `/z-suggest-memory`

**Files touched:** `commands/z-suggest-memory.md`, `skills/z-suggest-memory/SKILL.md`.

**Dependencies:** none.

**Description:** Documentation-only addition: in the `--source` flag docs, add an example showing `--source "incident:<RUN_ID>"` is the canonical prefix used by the review-agent flow. No code change; the existing source-prefix regex already accepts `incident:`.

**Acceptance criteria:**
- Both files have the new example block.
- No code changes.

**Status:** `[ ]`

**Complexity:** low

**DOCS:** z-suggest-memory

---

## T010 — Author `docs/human/review-agent.md`

**Files touched:** `docs/human/review-agent.md` (NEW).

**Dependencies:** T003.

**Description:** Human-tier doc per SPEC.md. Cover: what the agent is, when it fires (end of /z-implement-all and /z-review-all), what user sees (the AskUser prompts), what gets persisted (memory-candidates.jsonl per-run; /z-suggest-memory writes on accept), how to debug a failure (`/z-stats` Phase 4, `events.jsonl` filter for `review_agent_failed`), the v1 limitation (no per-call wall-clock timeout — ctrl-c is the escape).

**Acceptance criteria:**
- File exists and is readable.
- Cross-links to `/z-suggest-memory`, `/z-implement-all`, `/z-review-all`, `/z-stats` docs.
- Explicitly lists the six v1 deferrals from PLAN.md non-goals.

**Status:** `[ ]`

**Complexity:** low

---

## T011 — Author `docs/llm/review-agent.json` + update `docs/llm/INDEX.json`

**Files touched:** `docs/llm/review-agent.json` (NEW), `docs/llm/INDEX.json`.

**Dependencies:** T003.

**Description:** Add LLM-tier concept entry per SPEC.md fields. Update `docs/llm/INDEX.json` to register the new `review-agent` concept in the `concepts` array, bump `generated_at` to the current UTC time, and ensure `last_updated` on the new concept matches.

**Acceptance criteria:**
- `docs/llm/review-agent.json` is valid JSON; passes existing schema if any.
- `INDEX.json` includes the new concept with all required fields (`slug`, `source_file`, `last_updated`).
- `memories: []` (empty initially — review-agent itself will hopefully populate it later).
- Manual doc-fetcher dispatch with `query: "review-agent"` returns the new concept.

**Status:** `[ ]`

**Complexity:** low

---

## T012 — Re-run multi-IDE exports

**Files touched:** `exports/agy/.agent/rules/z-harness-review-agent.md` (NEW), `exports/agy/.agent/skills/...`, `exports/agy/.agent/workflows/...`, equivalent under `exports/codex/` and `exports/cursor/`.

**Dependencies:** T003, T005, T006, T007, T008, T009.

**Description:** Run `scripts/export-agy.py`, `scripts/export-codex.py`, `scripts/export-cursor.py` so the new agent file and updated commands/skills propagate to `exports/{agy,codex,cursor}/`. These scripts already handle the file set; just need to re-run after the source files exist.

**Acceptance criteria:**
- All three export scripts complete without error.
- `exports/agy/.agent/rules/z-harness-review-agent.md` exists.
- `exports/agy/.agent/workflows/z-implement-all.md` includes the new phase.
- `exports/agy/.agent/workflows/z-review-all.md` includes the new phase.
- Equivalent files updated under `exports/codex/` and `exports/cursor/`.

**Status:** `[ ]`

**Complexity:** low

---

## T013 — End-to-end smoke test

**Files touched:** none (manual / scripted verification).

**Dependencies:** T005, T006, T007, T008, T011, T012.

**Description:** On a throwaway plan slug (e.g. `smoke-memory-review`), run `/z-implement-all` against a trivial TASKS.md with one no-op task. Verify:
1. Phase 9 fires (or skips with `STATUS: skipped empty_diff` if the no-op truly produces no diff — pick a task that touches one file).
2. `review_agent_call` event written to events.jsonl.
3. `$RUN_DIR/memory-candidates.jsonl` written if candidates >0.
4. AskUser prompt presented and Accept dispatches `/z-suggest-memory` correctly.
5. `/z-stats` Phase 4b shows the new event.

Repeat for `/z-review-all` on a small completed plan.

**Acceptance criteria:**
- All 5 verification points pass for /z-implement-all.
- Equivalent verification passes for /z-review-all.
- Cost observation captured: token-spend for the Haiku review-agent call is logged and visible in /z-stats Phase 3.

**Status:** `[ ]`

**Complexity:** medium

---

## Summary

- 13 tasks. Target was 10-20 — within range.
- 2 tasks (T001, T002) are a verify-then-maybe-extend pair (T002 may SKIP).
- 4 tasks are doc/export propagation (T009, T010, T011, T012).
- 4 tasks are core implementation (T003, T004, T005, T006).
- 1 task is the test-the-skill mirror (T007).
- 1 task is telemetry surfacing (T008).
- 1 task is end-to-end smoke test (T013).

No `REMOTE_VERIFY` tags — z-harness is local-only; no Rust/Python-on-remote in this plan.
