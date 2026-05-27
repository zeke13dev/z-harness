Here is the critique of the proposed spec:

**1. Wire-format / event-shape mistakes**
- **Double terminal events:** Emitting a SECOND `memory_review_terminal` event makes it an intermediate state-update, not a terminal event. This breaks downstream `jq` row-counting (1 run = 2 terminal events). Instead, emit `memory_review_pending` (or `needs_user`) before the gate, and only emit the true `memory_review_terminal` when the user finishes.
- **Missing tokens in stats:** `/z-stats` Phase 4b currently prints `tokens=<input>/<output>`. If it switches to reading `memory_review_terminal`, that event MUST include `subagent_input_tokens` and `subagent_output_tokens`. Otherwise, `/z-stats` will require a nasty `jq` join with the `review_agent_call` event.

**2. Missing edge cases in `run-memory-review.sh`**
- **Fragile `DEBUG.md` gate:** `DEBUG.md` does NOT have a `status: shipped` frontmatter field—it's a plain markdown file. You cannot gate on frontmatter. You must either gate on the existence of `## Post-mortem` inside the file or let the orchestrator handle the `debug_run_end` state.
- **Stdout line collision:** Line 4 is currently `$TAGS_FILE`. If `parent_command:debug` emits `DEBUG.md` on line 4, it breaks the parser contract in existing callers. Append `DEBUG.md` to line 5 instead.
- **Double-logging skips:** If `run-memory-review.sh` emits the new `memory_review_terminal` for skips, and the orchestrator *also* emits it, you get duplicates. The orchestrator should own ALL terminal logging based on the script's `STATUS: skipped` stdout.

**3. `/z-debug` Phase 9b integration risks**
- **Wrong base ref:** `run-memory-review.sh` guesses the base ref (`origin/main` or `HEAD~5`). For `/z-debug`, this is wrong and will pull in unrelated workspace changes. It MUST be passed `$PRE_FIX_SHA` (captured in `z-debug` Phase 7) to generate an accurate `cumulative.diff`.
- **Phase 9b placement:** `/z-debug` Phase 9 ends with blocking `AskUserQuestion` loops (converting action items, running `/z-mr-review`). If 9b runs after 9, it is delayed by user interaction. It should run concurrently with MR review or automatically in Phase 10 before `debug_run_end`.

**4. `/z-stats` backward-compat parsing risks**
- **Complex jq:** Re-mapping old `phase_end` (which lacks tokens/candidates) and `review_agent_failed` into the new 4 explicit states in a single `awk/jq` pipeline will be gnarly. You need to ensure the legacy parser gracefully defaults missing `accepted` or `tokens` fields without dropping rows.

**5. Anything breaking existing Phase 9 callers**
- **Swallowing tags_missing:** The spec says "Stop emitting `review_agent_failed` for tags_missing" in the script. `z-implement-all` Phase 9 currently maps `STATUS: skipped tags_missing` to `phase_end {skipped: true}`. It needs to be updated to map to the new `skipped_broken_context` terminal state, otherwise it will just exit silently without a terminal event.
