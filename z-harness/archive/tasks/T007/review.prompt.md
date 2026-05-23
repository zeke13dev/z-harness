## Codex Review Prompt: T007

You are reviewing code that Claude just wrote for task T007: New /z-suggest-memory skill.

**Acceptance criteria:**
- All four AskUserQuestion options for target resolution
- Create-new-concept writes minimal stubs + adds INDEX.json entry (confidence: low)
- Append/edit/delete modes mutually exclusive
- --dry-run skips write in all modes
- STATUS / CONCEPT / MEMORIES_WRITTEN / WROTE return shape

**Critical spec requirements:**
1. Phase 0: Preflight check for docs/llm/INDEX.json
2. Phase 2: EXACTLY FOUR AskUserQuestion options (with conditional collapse when no hints)
3. Phase 3: Collect type (6 enum), text (≤200 chars), tags (15 seed + free-form), source (strict regex), date, expires
4. Phase 5: Three mutually-exclusive modes (append, edit, delete) with atomic writes
5. Phase 6: Regenerate MEMORIES-FLAT.md via helper script
6. Phase 8: Return STATUS/CONCEPT/MEMORIES_WRITTEN/WROTE shape
7. Hard rules: One mutation per call, no emojis, atomic writes, Cancel is default

The implementation is SKILL.md only (328 lines of documentation).
