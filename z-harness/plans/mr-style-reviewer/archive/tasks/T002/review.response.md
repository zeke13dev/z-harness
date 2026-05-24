## Codex review: task T002

### Blockers

None.

### Major

**Fix #4 — quote-aware split breaks on apostrophes in plain scalars**
Location: `scripts/extract-dismissals.py:184` in `_split_respecting_nesting()`
Problem: The function enters quote state on any `'` character, treating apostrophes in plain YAML scalars (e.g., `Don't`, `It's`) as string delimiters. This causes commas after such text to be skipped and fields to merge incorrectly.
Test evidence: `_split_respecting_nesting("title: Don't merge this, file: src/x.rs")` returns 1 item (merged) instead of 2 (split at comma). Expected to split at the comma after `this` because `Don't` is a plain scalar, not a quoted string.
Fix: Only enter quote state when the quote is a YAML string delimiter context (immediately after `{`, `[`, `(`, `,`, `:` or at the start of the token), not on bare apostrophes within plain text.

---

**Verification of other three fixes:**

**Fix #1 (title required):** VERIFIED. Lines 258–263 check `title_raw = finding.get("title")` and skip findings where `title_raw is None` without falling back to `id`. Drop counter is incremented correctly.

**Fix #2 (ISO timestamp sort):** VERIFIED. Regex `r"^(\d{8}T\d{6}Z)"` at line 289 correctly matches ISO prefixes. Sort key tuple `(0, iso_string, 0.0)` ensures lexicographic chronological order for ISO-named runs; fallback tuple `(1, "", mtime)` handles legacy names.

**Fix #3 (--global per-slug):** VERIFIED. Function returns `dict[Path, list[Path]]` at line 413. Loop at line 487 iterates over `slug_runs.values()` and calls `extract_dismissals_from_runs()` independently per slug, never pairing runs across slug boundaries.
