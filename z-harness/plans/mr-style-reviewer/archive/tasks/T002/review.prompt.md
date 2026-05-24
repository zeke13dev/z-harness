You are reviewing code that Claude just wrote for task T002: scripts/extract-dismissals.py

This is ROUND v2 — focus on whether 4 prior findings were addressed. Do NOT re-flag issues outside the delta.

Prior findings (v1):
1. BLOCKER: Snippet fallback to T-MR-NNN id (renumbered across runs → false dismissals). Fix: require `title` field, drop entries without it.
2. MAJOR: Runs sorted by mtime. Fix: sort by ISO timestamp prefix in dir name.
3. MAJOR: --global interleaves runs across slugs. Fix: group per-slug, pairwise within slug.
4. MAJOR: Custom YAML splitter doesn't track quote state. Fix: quote-aware splitting.

Verify each of the 4 fixes lands correctly. Scope: delta only.
