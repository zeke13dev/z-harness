You are reviewing code that Claude just wrote for task T004: Update agents/review-agent.md input contract for parent_command: debug.

## Spec (excerpt from SPEC.md)

### agents/review-agent.md

**Existing surface (preserved):**
- Input fields: `run_dir`, `cumulative_diff_path`, `spec_path`, `tags_path`, `index_path`, `run_id`, `parent_command`
- Output: single fenced ```json block with `[0..3]` candidate objects

**Additions:**

1. Add optional input field: `debug_md_path` (string, absolute path; absent for `implement-all` and `review-all`).
2. Update the input contract section of the agent definition to state:
   > When `parent_command: debug`, `debug_md_path` is the primary artifact the agent reasons over. `spec_path` is supplementary context for recognizing affected invariants. For `implement-all` and `review-all`, `spec_path` is primary and `debug_md_path` is unset.
3. Add `debug` to the valid `parent_command` enum.
4. Add to the agent's candidate-generation guidance:
   > For `parent_command: debug`, filter candidates for generalizable invariants, root-cause patterns, and "why we didn't catch it" gaps. Single-run patches and fix-specific minutiae are NOT memories.

**Invariants (unchanged):**
- Agent never writes.
- Output is exactly one fenced JSON block.
- Hard cap of 3 candidates.
- Candidate tags must come from `TAGS.txt` unless free-form is justified.
