MODE: plan-review

## SPEC.md + PLAN.md for MR-style code-quality reviewer

### Focus areas for critique:

1. **Agent input contract** — is the diff-chunking transparent? How does agent reconstruct context from chunked dir?
2. **Dismissal-pattern matching** — token-overlap > 0.6 robust? What happens if P0 gets demoted twice (consensus → dismissal)?
3. **Chunking mechanics** — per-file chunking may break abstraction findings that need cross-file context. Fragile?
4. **Voice failure modes** — what happens if Codex returns malformed findings? Silent drop or exit?
5. **Phase ordering** — Phase 3 (Claude-only) outputs get replaced in Phase 5 (multi-voice). Is that the intended workflow?
6. **DRY** — dismissal-extraction logic in mr-reviewer + /z-style-init --amend both scan archives. Duplicated?
7. **Integration seams** — /z-debug parses MR-REVIEW.md markdown to find P0/P1 titles. Fragile regex?
8. **Missing tasks** — Capture phase surfaces 1000-line god-object; does user get to reject files before they're used?
9. **Abstraction matching** — 'grep for similar-name symbols' is naive; will high false-positive rate on common names?
10. **Falsifiability** — >90% parity with /z-audit, >30% dismissal rate → retire. Who tracks? How measured?

Critique for: what's wrong, missing, fragile, or under-defined? Be specific and concrete. Point at exact SPEC/PLAN line/phase.
