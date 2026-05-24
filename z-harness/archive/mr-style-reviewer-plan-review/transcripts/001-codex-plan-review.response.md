## Codex consultation: MR-style reviewer SPEC+PLAN plan review

**Core finding:** 12 concrete fragilities identified, ranging from impossible agent inputs (dismissal detection) to underspecified contracts (chunking, consultant output schema). The plan is high-level; the SPEC glosses over several mechanics that will cause either implementation failure or silent quality degradation.

**Most severe issues:**
1. **Dismissal detection is architecturally impossible** (finding #1) — agent receives archive snapshots but cannot infer deletion without the edited MR-REVIEW.md or precomputed signatures. Agent contract is incomplete.
2. **Chunked diff contract is contradictory** (finding #2) — no manifest format, chunk naming, ordering, or binary/rename handling. Agent behavior will be non-repeatable for large MRs.
3. **Per-file chunking hides cross-file findings** (finding #3) — abstraction/style-drift findings often need call sites, related files, test pairing. Per-file isolation may silence legitimate findings before merge happens.
4. **Dismissal demotion can bury P0s** (finding #4) — single-voice P0 + dismissal match = P2. No severity floors defined. Compound demotion rules are ordered but not specified.
5. **Token-overlap heuristic is underspecified** (finding #5) — no normalization, stopword handling, path/category weighting, or protection against boilerplate clustering.

**Moderate fragilities:**
- Malformed consultant output has no parser/validation schema or error recovery path (finding #6)
- Phase 3 (Claude-only) milestone outputs are not marked as temporary; tests could accidentally lock single-voice behavior (finding #7)
- Capture heuristic allows selection of legacy 800-line god-objects; no user reject step before drafting (finding #8)
- Abstraction symbol-matching is too naive; overmatch on common names like `format()`, undermatch on semantic duplicates (finding #9)

**Integration & operationalization issues:**
- `/z-debug` markdown parsing is fragile — coupling post-mortem to heading format without structured frontmatter (finding #10)
- Archive-scanning logic duplicated in two places without shared helper (finding #11 — violates stated DRY goal)
- Falsifiability criteria (>90% parity, >30% dismissal) are documented but not operationalized — no metric tracking, no dismissal-rate denominator, no retirement task (finding #12)

**Recommendation:** Before Phase 1 starts, resolve:
1. **Agent input contract:** Orchestrator precomputes dismissed-finding signatures (from archive + edited MR-REVIEW.md diff), passes both archive paths and computed-dismissals to mr-reviewer. Or: agent receives edited MR-REVIEW.md paths alongside archives.
2. **Chunking manifest:** Define per-file chunk format (metadata, ordering, manifest header), chunk naming scheme, diff reconstruction instructions. Or: keep full diff in-memory if ≤150k tokens (covers most real MRs), defer large-diff chunking to v2.
3. **Dismissal demotion floor:** Specify whether P0/P1 skip dismissal demotion, or if a P0 can drop to P2. Define demotion order (consensus first, then dismissal, or vice versa).
4. **Token-overlap:** Specify normalization (lowercase, punctuation), stopword list, category/path weighting, and overmatching guards (e.g., skip matches on <3 word bodies).
5. **Capture reject step:** Add a user-review checkpoint after Sonnet ranks files but before reading them. Show user the 5 picked files; allow "replace this one" or "swap in a different type."
6. **Consultant schema:** Define finding JSON schema; mk parser + validation; add `mr_voice_failed` condition for malformed output.
7. **Abstraction matching:** Define symbol extraction (language-aware, or regex by extension), confidence threshold (e.g., match only if Levenshtein < 3 or semantic sim > 0.8), suppression rules for common names.
8. **Falsifiability:** Add a telemetry hook to track user-deleted findings (requires parsing edited MR-REVIEW.md after user approval, before handing off to implement-all). Compute dismissal rate = deleted / total. Add a v2-phase task to report quarterly.
9. **DRY (archive scanning):** Extract `dismissal_extractor(archive_path) → [(category, normalized_text, file_path_prefix), ...]` into a common utility; share between `mr-reviewer` and `/z-style-init --amend`.
10. **Phase 3/5 boundary:** Clarify that Phase 3 output is internal milestone; Phase 5 must preserve MR-REVIEW.md output contract and add voice tags + consensus tier-bump to each finding.

**Remaining OK:** Def Schema (STYLE.md, rule IDs, output format) is well-specified. Five-category taxonomy is clear. Telemetry events are well-named.
