## T009 — Multi-IDE exports
- Cycles: 2 (v2 reviewer skipped)
- v1 found + fixed real bug: skill-vs-command ID collision in export-cursor.py/export-codex.py (would silently overwrite command export). Fix: append "-skill" on collision.
- v1 review: 1 BLOCKER (SKILL.md description 549 chars vs 250-char agy limit)
- v2: source description shortened to 245 chars; agy re-exported clean (124 files validated)
- Files: scripts/export-cursor.py, scripts/export-codex.py, skills/z-uplift/SKILL.md + 7 export artifacts (new)
- Result: [x]
