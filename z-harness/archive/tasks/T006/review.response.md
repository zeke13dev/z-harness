## Codex Review Output

### Findings

**BLOCKER #1: `mr_run_end` omits `by_category`**

Line 603-620 of commands/z-mr-review.md logs `mr_run_end` with `by_severity`, voices, and dismissal matches, but not `by_category`. SPEC.md line 352 requires `mr_run_end {slug, run_id, total_findings, by_severity, by_category, voices_succeeded, voices_failed}`, and agents/mr-reviewer.md line 259-260 returns a `by_category` summary. The command must aggregate categories from parsed findings and include `by_category` in the event payload.

**MAJOR #1: T006 performs chunk splitting before "T009 pending" error**

Line 259 enters the per-chunk split flow and writes chunk files before the later guard errors at line 388. T006 acceptance criteria requires per-chunk mode to error with "chunking pending T009" immediately; doing chunking first means large diffs waste compute on file writes before the controlled error. Move the T009 guard to Step 1h immediately after MODE is set, before any chunk generation.

### Checks Passed

- Agent dispatch includes all 12 required contract fields: slug, run_id, slug_dir, base, base_sha, diff_path, style_path, dismissed_signatures_path, voices_available, mode, chunk_meta, deep
- JSON extraction handles malformed/absent blocks with explicit error path and log
- findings_index shape: id, severity, category, file, title (correct)
- Dual write uses same MR_REVIEW_CONTENT for both canonical and archive snapshot
