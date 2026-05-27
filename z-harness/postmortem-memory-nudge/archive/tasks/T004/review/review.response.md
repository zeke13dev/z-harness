## Codex Review: T004

### Major

**Procedure Step 1 does not mention `debug_md_path`** (/Users/zeke/dev/z-harness/agents/review-agent.md:29).
The diff added `debug_md_path` to inputs, documented it as primary for debug runs (lines 25-26), and added step 6 guidance for debug filtering. However, step 1 of the Procedure still reads only `events.jsonl`, `cumulative_diff_path`, `spec_path`, `tags_path`, `index_path` — it omits `debug_md_path` entirely, creating ambiguity about whether the agent should read this new primary artifact when `parent_command: debug`.

**Fix:** Update step 1 to branch on `parent_command`. Suggested wording:
"1. Read `events.jsonl` from `run_dir`, `cumulative_diff_path`, `tags_path`, and `index_path`. If `parent_command: debug`, also read `debug_md_path` (primary) and `spec_path` if non-empty. Otherwise read `spec_path` (primary). Enumerate existing concept slugs from `index_path` before suggesting a slug in step 3 — prefer matching an existing slug over coining a new one."

### Verification

All acceptance criteria are met:
- `debug` added to `parent_command` enum ✓
- `debug_md_path` documented as optional, absolute, absent for implement-all/review-all ✓
- Artifact primacy contract explicit (lines 25-26) ✓
- Empty `spec_path` documented as "no SPEC available — treat run as self-contained" ✓
- Debug candidate guidance with generalizable invariants, root-cause patterns, catch gaps; excludes single-run patches ✓
