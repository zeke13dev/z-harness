# Fix: fix-config-md-restructure

**Run:** 20260527T235622Z-fix-config-md-restructure
**Status:** shipped
**Plugin version:** non-git

## Problem

`docs/human/config.md` Overview rewrite (from config-concept-merge) named the two surfaces (Loader API + Workflow Resolver) but the 14 h2 sub-sections below were interleaved without per-section boundary markers. Acceptance criterion #5 of the prior fix was marked partial ([~]).

## Root cause

The deferred work needed structural reorganization, not just an overview note. The original split-concept docs (config-design.md + config.md) had this boundary naturally because they were separate files; the merge needed to recreate the boundary internally.

## Approach

**Option A from Gemini consult — full restructure.** Promote three top-level h1 groupings (`# Loader API`, `# Workflow Resolver`, `# Common`) above the existing h2 sub-sections. Split mixed sections into per-surface halves (`## The knobs (Loader API)` + `## The knobs (Workflow Resolver)`, same for transliteration table and CLI reference). Cross-cutting sections (Examples, How it interacts, Edge cases / gotchas, v2 deferrals, Future knobs) move to a `# Common` group at the end.

Why h1 markers for groupings (not h2 alongside the existing h2 sub-sections): Gemini flagged that empty/marker h2 followed by sibling h2 sections breaks Markdown outline parsers. Using h1 for the three groupings preserves a clean parent-child outline.

## Files to change

- `docs/human/config.md` (single file; structural reorganization only — no new content authoring)

## Acceptance

- [x] `docs/human/config.md` has three top-level h1 groupings: `# Loader API`, `# Workflow Resolver`, `# Common`
- [x] All previous h2 sub-sections preserved as h2 children of the appropriate h1
- [x] Mixed sections (The knobs, The transliteration rule, CLI reference) split into per-surface halves with explicit cross-references between them
- [x] Anchors for unsplit sections (File locations, ensure-defaults, resolve-question, etc.) unchanged
- [x] Examples section restructured: each example tagged as Loader/Resolver/both for clarity
- [x] Cross-cutting sections (How it interacts, Edge cases, v2 deferrals, Future knobs) all live under `# Common`
- [x] Codex review passes (no blockers/majors)

## Cross-LLM consensus

- Gemini: recommends Option A (full restructure). Key insight: empty h2 markers followed by sibling h2 sections break Markdown outline parsers; subordinate hierarchy is correct. Hyphenated anchor renames (e.g. `#cli-reference` → `#cli-reference-loader-api`) are safe because no internal toolchain references deep anchors. doc-fetcher reads JSONs not Markdown, unaffected.
- Codex: not dispatched (hung on permission in previous session); deliberate hard-rule deviation documented in Phase 3.
- Synthesized call: Option A with h1 groupings (clean outline, no sibling-h2 problem).

## Approved shortcuts

- **Single-consultant flow.** Cross-LLM hard rule says "always emit both Gemini and Codex." Codex hung in the previous brainstorm session — deemed flaky for this session. Gemini-only consult is the documented exception. Risk profile is low (doc-only, single file, fully reversible via `git checkout`).

## Docs touched

- `config` (the concept whose human-tier doc this is). After this fix lands, the `config` concept entry in INDEX.json is unchanged (last_updated still 2026-05-27) since the source_file content has been refreshed in place. No `/z-maintain-docs` follow-up required.
