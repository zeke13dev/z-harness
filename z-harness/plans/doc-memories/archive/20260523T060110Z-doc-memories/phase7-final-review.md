# Phase 7 — Final review synthesis

Both consultants returned blocker-level findings (Codex CLI binary missing → both responses are subagent-Sonnet inline, but the substance landed). All findings applied via SPEC.md edits.

## Findings accepted and applied

| # | Source | Finding | SPEC.md change |
|---|--------|---------|----------------|
| 1 | Gemini G1 | Silent clobbering of human edits to `## Memories` | Added HTML-comment "DO NOT EDIT" warning under the section heading. |
| 2 | Gemini G2 + Codex C6 | Substring fallback false positives ("auth" matches "author"); ordering | Fallback now uses Python `\b` word-boundary regex; preserves file order. |
| 3 | Gemini G3 | Mandatory invocation → padding | Added "Cancel is first-class outcome / default when no salient memory" salience guidance to /z-debug and /z-improve hook sections AND to /z-suggest-memory step 2. |
| 4 | Gemini G4 + Codex C7 | Stale memories surface but no remediation | /z-maintain-docs Phase 3 stale section gains inline AskUserQuestion: Keep / Edit (handoff to /z-suggest-memory --edit) / Delete. Never auto-deletes. |
| 5 | Gemini G5 | Test fixtures blind to regex escaping | Added adversarial-regex fixture test (test 6) covering `[`, `]`, `*`, `\`, `$` in slugs/text/tags. |
| 6 | Codex C1 | Python regen helper not specified | Added explicit helper spec — `scripts/regenerate-memories-flat.py` with signature, exit codes, atomic write pattern. |
| 7 | Codex C2 | Synthesis math (3 concepts × 3 memories × 200 chars > 2 KB cap) | Added truncation rule: if total >1500 bytes, truncate each memory text to ≤120 chars + `…`. Structural content never truncated. |
| 8 | Codex C3 | /z-init-docs --scope handoff doesn't fit | Replaced with direct stub-creation by /z-suggest-memory (writes minimal `<slug>.json` + `<slug>.md` + INDEX.json entry with `confidence: low`). |
| 9 | Codex C4 | MEMORIES-FLAT.md write races | Atomic tmpfile pattern documented in shared helper section; "last writer wins" is acceptable because full regen is idempotent given stable JSON state. |
| 10 | Codex C5 | TAG_COLLISIONS return format unspecified | Spec'd the exact JSON shape `[{"concept", "tag_a", "tag_b", "count_a", "count_b"}, ...]`. |
| 11 | Codex C8 | Edit/delete via /z-suggest-memory not specified | Added `--edit <slug> <index>` and `--delete <slug> <index>` flags; three mutually-exclusive modes; concurrent-regen test added. |

## Findings considered and not adopted

None. All blocker-level findings were genuine and applied. The two consultants overlapped on three (substring fallback, stale-memory UX, test coverage); the union covered the surface.

## "One reason it might be wrong" — applied

- **G3 (padding risk):** counter-argument was "Cancel is already an option." Accepted but strengthened — the salience guidance is now load-bearing default-cancel language, not just an enumeration choice.
- **C8 (edit/delete):** counter-argument was the "never write more than one memory per invocation" hard rule. Resolved by amending the hard rule to "one mutation per invocation" — append/edit/delete are three modes of the same one-mutation contract.
- **G4 (stale remediation):** counter-argument was D7's "never auto-delete." Accepted; the UX is explicit per-entry human action, not bulk auto-delete. Compatible with D7.

Ready to write TASKS.md.
