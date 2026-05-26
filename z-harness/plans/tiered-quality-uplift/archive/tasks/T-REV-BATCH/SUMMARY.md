## T-REV-BATCH (T-REV-001..007) — Apply /z-review-all fixes

- Approach: Bundled into one implementer dispatch (file-overlap dedup made serial-only; user accepted bundling).
- Cycles: 2
- v1 review: 1 BLOCKER + 2 MAJOR
  - BLOCKER: T-REV-003 regex didn't match auditor's `### [SEVERITY]` markdown header — would have disabled CRIT-HIGH auto-bail in real runs.
  - MAJOR: T-REV-005 fixed MAX_PASSES=5 cap instead of true while-loop
  - MAJOR: T-REV-005 SLUG_RE accepted `foo--bar`/`foo-`
- v2: all 3 fixed. v2 review CLEAN — no blockers, no majors.
- Files: commands/z-uplift.md (+74 net lines)
- Diff: 282 lines

Deferred to skip-flagged amendments:
- T-REV-008 [s]: SPEC amendment for auditor output format — requires /z-amend (slash-command nesting constraint)
- T-REV-009 [s]: SPEC amendment for cross-cutting parser format — requires /z-amend

Both can be applied via a direct `/z-amend` invocation in a fresh session.
