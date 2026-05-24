# Decisions to consult on: /z-mr-review + /z-style-init

Context: Building MR-style code-quality reviewer in z-harness Claude Code plugin. BRAINSTORM.md is settled. Reviewer assumes correctness; targets code-quality slop (AI-shaped and human-shaped). Findings ranked P0-P4, user triages, never blocks.

Background from brainstorm: multi-agent dispatch (Claude + Codex + Gemini), five-category findings (defensive bloat / test noise / abstraction / hygiene / style drift), Capture-first STYLE.md init, standalone /z-mr-review + /z-style-init commands (no v1 /z-review-all coupling).

---

## D2: Multi-LLM dispatch pattern

**Options:**
- (a) Three parallel Agent() calls from orchestrator (Claude general-purpose + codex-consultant + gemini-consultant)
- (b) Single mr-reviewer.md agent (Sonnet) that internally fans out to Codex + Gemini via CLI, dedup + rank in one place, returns one consolidated output to orchestrator
- (c) Single Sonnet agent, no cross-LLM

**User's call:** (b). Cleaner orchestrator return; dedup + ranking happens in one place; reuses existing codex-consultant / gemini-consultant agents as CLI wrappers.

---

## D3: Output format & TASKS.md handoff

**Plan:** Write z-harness/<slug>/MR-REVIEW.md (P0-P4 grouped findings) and z-harness/<slug>/MR-TASKS.md (TASKS.md-shape, one entry per accepted finding). Interactive triage inside /z-mr-review — user batches accept/dismiss/defer per severity tier. /z-implement-all picks up via `--tasks=MR-TASKS.md` flag.

**User's call:** Separate MR-TASKS.md (don't append to plan's TASKS.md — would corrupt in-flight implement state). Interactive triage inline rather than "edit YAML afterward".

---

## D4: /z-style-init Capture mechanism

**How to find the "most idiomatic files" in a repo for STYLE.md grounding.**

**Options:**
- (a) Heuristic (low churn, mid-size, multi-author files)
- (b) Sonnet subagent scans candidate files
- (c) User nominates files

**User's call:** (b) with (a) as fallback. One-shot per project, cost amortized.

---

## D5: STYLE.md schema

**Options:**
- (a) Free-form Markdown
- (b) Required section headers (`## Error handling`, `## Tests`, `## Comments`, `## Naming`, `## Project-specific`) + frontmatter, free-form prose within
- (c) Pure structured YAML rules

**User's call:** (b). Reviewer can cite "STYLE.md: Error handling §2". Frontmatter holds `generated_at` + `source: capture|interview|ingest|natural-language`.

---

## D9: Slug coupling for /z-mr-review

**How does /z-mr-review decide where to write findings?**

**Options:**
- (a) Require --slug or active plan dir
- (b) Default to current git branch name as slug, allow --slug override to attach to an active plan
- (c) Single canonical mr-reviews/<timestamp>.md location

**User's call:** (b). Works anywhere without ceremony; mid-plan user can attach with --slug=<plan-slug>.

---

## D11 (informational, not consult-flagged):

Two-tier model inside mr-reviewer: Sonnet for defensive-bloat, test-noise, hygiene, style-drift (per-diff-chunk); **Opus** for the abstraction category (whole-repo grep, dead-code detection, missed-extraction). Hardcoded principle: "every added line must justify itself; net positive diff length is suspect; if a similar abstraction exists, flag duplication."

**Question:** Is this tiering the right cut? Or is Opus overkill / Sonnet sufficient for abstraction too?

---

## Consult prompt

You are critiquing decisions for the MR-style reviewer. For each flagged decision (D2, D3, D4, D5, D9), recommend with reasoning, tradeoffs, and missed considerations. Flag any interactions between decisions or shortcuts being taken. Flag any missing decision that should have been raised.

Be concrete and terse. Flag what the user is wrong about more than what is right. For D11, be direct on the model-tiering question.
