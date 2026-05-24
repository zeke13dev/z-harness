# Final review — mr-style-reviewer
Run: 20260524T004459Z-review
Base ref: 338e138 ("Initialize all z-harness docs")
Diff stats: 23 files changed, ~5800 net lines (4 new commands/agents/scripts + docs + telemetry)

## Verdict

**No blockers from either consultant.** Both Gemini and Codex independently concluded the implementation faithfully follows SPEC and the SPEC itself is sound. Findings are all minor doc/UX gaps and one benign frontmatter addition.

## Prong A — Implementation drift

### Severity: blocker
*(none)*

### Severity: major
- **[both] Frontmatter schema drift in MR-REVIEW.md.** Implementation adds `mode` and `by_severity` fields to the frontmatter that aren't in SPEC's frontmatter example. Both consultants noted these are benign (`/z-debug` only reads `findings_index`; YAML parsers ignore unknown fields) — but it's a spec-vs-code mismatch. **Fix:** either patch SPEC's example to include both fields, or document them as orchestrator-internal.

### Severity: minor
- **[gemini] Undocumented telemetry event `mr_dismissal_extract_failed`** — added in z-mr-review.md Step 1i as defensive logging when extract-dismissals.py fails. Not listed in SPEC's telemetry section.
- **[codex] PRE_FIX_SHA not validated by /z-debug post-mortem hook** before delegating to /z-mr-review. If the user rebases between fix and post-mortem, /z-mr-review will fail with a cryptic ref error. The hook treats this as best-effort and continues, so no breakage — but error message is confusing.
- **[codex] Homemade YAML parser in extract-dismissals.py is sufficient for narrow findings_index schema but doesn't support anchors/merges/multi-line strings.** Acknowledged as designed; documented in the parser docstring; tests cover the round-trip cases the orchestrator actually produces.
- **[codex] No explicit end-to-end round-trip test** (z-mr-review writes frontmatter → extract-dismissals.py reads it). Per-task tests cover both sides but not the integration. Synthetic fixtures in test_extract_dismissals.py mirror the orchestrator's output format, so coverage is implicit.

## Prong B — Spec gaps

### Severity: blocker
*(none — both consultants explicitly said SPEC is sound)*

### Severity: major
- **[codex] Zero-candidate case in /z-style-init Capture is unspecified.** If the heuristic prefilter excludes every file (vendored-only repos, generated-only repos), SPEC says "pick top 5" but doesn't say what happens with an empty list. Implementation handles it gracefully via the user-confirm gate (edit / re-pick / abandon), but SPEC should document this branch explicitly.

### Severity: minor
- **[codex] Binary files in the diff are silently skipped** (regex won't match, no findings emitted). Correct behavior, but not documented.
- **[codex] STYLE.md is not re-validated after creation.** If user manually corrupts it, agent still runs (just produces fewer style-drift findings). Doc gap, not code gap.
- **[codex] Jaccard ≥ 0.6 threshold has no rationale or worked example in SPEC.** Threshold is empirically chosen but un-justified in the docs.

## Consensus vs disagreement

**Both flagged (high confidence):**
- Frontmatter schema drift (mode + by_severity fields)

**Single-LLM (worth manual scrutiny):**
- All other findings are single-source. Both LLMs agreed the implementation is correct and the SPEC is sound; their majors/minors are largely complementary (Gemini focused on schema drift + telemetry; Codex focused on edge cases + doc gaps).

## What's solid (both consultants concur)
- Consensus tier-bump uses `voices_succeeded` (post-parse) as denominator — parse-failures don't penalize agreements.
- P0 is never demoted (both tier-bump and dismissal-matching paths).
- Dismissal-pattern matching: identical normalization across script and agent; Jaccard threshold consistently applied.
- Chunking strategy: per-chunk parallel + abstraction-only whole-diff pass, merged with dedup.
- Cross-LLM integration: graceful degradation on voice failures; voices_used reported.
- /z-debug post-mortem hook delegates to /z-mr-review SlashCommand (not direct agent dispatch), reads findings_index frontmatter only.
- /z-implement-all --tasks=<path> correctly handles MR-REVIEW.md as a task queue.
- All declared telemetry events are wired.
- extract-dismissals.py pytest coverage is thorough (40+ tests including round-trip fixtures).
