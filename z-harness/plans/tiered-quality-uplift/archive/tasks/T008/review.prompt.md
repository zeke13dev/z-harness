You are reviewing code that Claude just wrote for task T008: Skill wrapper + docs concept entry + README listing.

Spec (excerpt from SPEC.md):
- INDEX.json is valid JSON, z-uplift concept resolvable by doc-fetcher
- skill loads (skills/z-uplift/SKILL.md present with correct frontmatter)
- README lists the new command
- MEMORIES-FLAT.md regenerated without error

Acceptance criteria:
- INDEX.json is valid JSON, z-uplift concept resolvable by doc-fetcher
- skill loads (skills/z-uplift/SKILL.md present with correct frontmatter)
- README lists the new command
- MEMORIES-FLAT.md regenerated without error

Diff (primary artifact):

Files added:
- skills/z-uplift/SKILL.md (3.1 KB)
- docs/llm/z-uplift.json (3.7 KB)
- docs/human/z-uplift.md (3.5 KB)

Files modified:
- README.md (added /z-uplift to "Audit, debug, review" section; added external-lookup agent)
- docs/llm/INDEX.json (added z-uplift concept entry, updated timestamp)
- docs/llm/MEMORIES-FLAT.md (regenerated)

Key content from z-uplift.json (the LLM concept doc):

```json
{
  "concept": "z-uplift",
  "last_updated": "2026-05-25",
  "covers_spec": "z-harness/plans/tiered-quality-uplift/SPEC.md",
  "source_files": [
    "commands/z-uplift.md",
    "docs/human/z-uplift.md",
    "skills/z-uplift/SKILL.md"
  ],
  "confidence": "high",
  "entry_points": [
    {
      "file": "commands/z-uplift.md",
      "line": 65,
      "symbol": "Setup",
      "kind": "module",
      "summary": "Derive uplift slug, resolve plan dir, pick run ID, log run_start, doc-staleness gate."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 143,
      "symbol": "STYLE.md gate",
      "kind": "gate",
      "summary": "Require STYLE.md at repo root; halt and recommend /z-style-init if missing unless --no-style passed."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 215,
      "symbol": "Phase 0",
      "kind": "phase",
      "summary": "Premise check — one-paragraph goal confirmation, same shape as /z-plan Phase 0."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 231,
      "symbol": "Phase 1",
      "kind": "phase",
      "summary": "Decomposition — auto-detect components, write COMPONENTS.md, AskUser gate, honor --components/--component overrides, slug collision check."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 699,
      "symbol": "Phase 2",
      "kind": "phase",
      "summary": "Cross-cutting pass — dispatch consultant-primary + consultant-secondary in parallel on source map + STYLE.md; merge into CROSS-CUTTING.md with global-task / per-component-context / risk classification."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 1218,
      "symbol": "Phase 3",
      "kind": "phase",
      "summary": "Per-component audits — dispatch auditor per dimension in parallel, bundled consult, auto-bail check (>30 total OR >10 CRIT-HIGH), produce REPORT.md + TASKS.md in sibling plan dir, reviewer gate."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 1823,
      "symbol": "Phase 4",
      "kind": "phase",
      "summary": "Review gate — present aggregated queue summary (component count, total tasks, bailed components, dep warnings) to user."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 1963,
      "symbol": "Phase 5",
      "kind": "phase",
      "summary": "Sequential implement — AskUser gate per component, invoke /z-implement-all --tasks=, update MANIFEST state."
    },
    {
      "file": "commands/z-uplift.md",
      "line": 2301,
      "symbol": "Phase 6",
      "kind": "phase",
      "summary": "Finalize — log run_end, push-notify, recommend /z-maintain-docs if any task carried a **DOCS:** line."
    }
  ]
}
```

SKILL.md frontmatter (verified present):
```
---
name: z-uplift
description: Bulk codebase quality uplift...
argument-hint: [--no-style] [--components=<file>] [--component <path>] [--retry-bailed] [--refresh-component <name>] [--dimensions=<csv>] [--cross-cutting=skip]
---
```

README addition (verified):
✓ /z-uplift entry added to "### Audit, debug, review" section
✓ Correct description and flags listed

Verification results:
✓ INDEX.json valid JSON
✓ z-uplift.json valid JSON
✓ skill file present with correct frontmatter
✓ README entry present
✓ MEMORIES-FLAT.md header present
✓ INDEX.json has correct "source_files" field name (plural, per schema)

Actual phase headings in commands/z-uplift.md (grep results):
- Phase 0 at line 454 (diff says 215 — WRONG)
- Phase 1 at line 470 (diff says 231 — WRONG)
- Phase 2 at line 938 (diff says 699 — WRONG)
- Phase 3 at line 1457 (diff says 1218 — WRONG)
- Phase 4 at line 2062 (diff says 1823 — WRONG)
- Phase 5 at line 2202 (diff says 1963 — WRONG)
- Phase 6 at line 2540 (diff says 2301 — WRONG)

The "STYLE.md gate" entry_point (line 143) does not correspond to a section heading—the text at line 143 is mid-sentence explanatory content. Line 257 discusses the gate conceptually.

Scrutinize rigorously:
1. Are the line numbers in entry_points accurate?
2. Do they actually point to section headings or the start of the described content?
3. Is the doc structure schema-compliant per style-init.json requirements?
4. Are there correctness issues or truncated content?

Report findings (blockers and majors only):
