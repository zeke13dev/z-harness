# Phase 2 — Decisions

Slug: `mr-style-reviewer`. Run: `20260523T194623Z-mr-style-reviewer`.

Premise accepted (Phase 0). BRAINSTORM.md fixed the user-facing shape; this doc enumerates the implementation decisions that follow from it.

---

## D1. Command + agent file layout

**Decision:** Where do the new files live?

**Options:**
- (a) `commands/z-mr-review.md`, `commands/z-style-init.md`, `agents/mr-reviewer.md` — flat alongside existing commands/agents.
- (b) Nested under a `commands/mr/` subdir.

**Tentative call:** (a). Matches every existing convention; nesting buys nothing.

**Consult?** no. Following existing convention.

---

## D2. Multi-LLM dispatch pattern for `/z-mr-review`

**Decision:** How are the three Nitpicker voices dispatched?

**Options:**
- (a) Three parallel `Agent()` calls in one orchestrator message: Claude (`subagent_type="general-purpose"`, model `sonnet`, with Nitpicker prompt), Codex (existing `codex-consultant` in a new `MODE: mr-review`), Gemini (existing `gemini-consultant` in a new `MODE: mr-review`). Mirrors how `/z-brainstorm` already does it. Returns synthesized by orchestrator.
- (b) New dedicated `mr-reviewer.md` agent (Sonnet) that internally fans out to Codex + Gemini via CLI. Orchestrator gets one return.
- (c) Skip multi-LLM, single Sonnet `mr-reviewer` agent. Cheapest. Loses the cross-vendor signal the user explicitly asked for.

**Tentative call:** (b) — a single `mr-reviewer.md` agent (Sonnet) that does the Nitpicker review itself and internally consults Codex + Gemini via the existing consultant infra. **Why:** keeps orchestrator context lean (one return, not three), reuses the `codex-consultant` / `gemini-consultant` agents as already-built CLI wrappers, lets the agent do per-finding dedup + P0–P4 ranking in one place. Pattern matches the way `/z-review-all` and `/z-audit` already structure cross-LLM work.

**Consult?** yes. **Trigger:** affects >1 module (commands/ + agents/), defines the agent's input contract (a public surface inside z-harness), and reversibility cost is moderate (hard to change once `/z-mr-review` is in use). Articulable: ≥2 options with materially different tradeoffs (a vs b).

---

## D3. Finding output format & TASKS.md handoff

**Decision:** What does `/z-mr-review` write to disk, and how does `/z-implement-*` pick it up?

**Options:**
- (a) Write `z-harness/<slug>/MR-REVIEW.md` (P0–P4 grouped findings) AND `z-harness/<slug>/MR-TASKS.md` (TASKS.md-compatible, one task per accepted finding). User runs an interactive triage flow (`AskUserQuestion` per finding or batch by severity) inside `/z-mr-review` to choose accept/dismiss/defer; only accepted findings land in MR-TASKS.md.
- (b) Same files, but no interactive triage — write ALL findings to MR-TASKS.md with status `[ ]`, user manually edits before running `/z-implement-all`.
- (c) Reuse existing `TASKS.md` directly — append new tasks. Conflates the two artifacts; if `/z-implement-all` is already running off TASKS.md, this corrupts state. Rejected.

**Tentative call:** (a). Interactive triage at review time is the user's whole point of asking for P0–P4 ranking — they want to decide, not edit YAML later. Keep MR-TASKS.md as a separate artifact so `/z-implement-all <slug> --tasks=MR-TASKS.md` (or `--from=MR-TASKS.md`) can pick it up without crossing wires with the original plan's TASKS.md.

**Consult?** yes. **Trigger:** defines new on-disk artifact contract (MR-REVIEW.md, MR-TASKS.md), affects `/z-implement-all` flag surface, hard to rename later. ≥2 viable options.

---

## D4. `/z-style-init` Capture mechanism

**Decision:** How does the Capture step "find the most idiomatic files" in a repo?

**Options:**
- (a) Heuristic: pick N files (default 5) by combining git-blame churn (low churn = stable = idiomatic), file size band (avoid trivial + monster files), and a touched-by-multiple-authors signal (avoid single-author idiosyncratic code). Cheap, deterministic.
- (b) LLM-driven: dispatch a Sonnet subagent that reads `ls-files` output and picks idiomatic files by scanning sampled content. Higher quality, more expensive (~$0.20–$0.50 per init).
- (c) User explicitly nominates files. Simplest, puts all burden on user. Defeats the "Capture not Generate" insight.

**Tentative call:** (b) with (a) as fallback if no API key / repo too large. The whole point of Capture is to ground STYLE.md in real project taste; a Sonnet pass over candidate files is exactly the right tool. One-shot per project, cost is negligible amortized.

**Consult?** yes. **Trigger:** algorithm choice with materially different cost/quality tradeoffs; touches the success of the whole `/z-style-init` flow.

---

## D5. STYLE.md schema

**Decision:** Free-form Markdown or structured (frontmatter + sections)?

**Options:**
- (a) Free-form Markdown with conventional sections (no enforcement). Trust the user + critique loop to keep it useful.
- (b) Required frontmatter + required section headers (e.g., `## Error handling`, `## Tests`, `## Comments`, `## Naming`, `## Project-specific`). Parseable, lets the reviewer cite specific sections.
- (c) Pure structured YAML/JSON rules. Mechanically enforceable. Loses the judgment-not-rules nature of style.

**Tentative call:** (b). Required section headers but free-form prose within each. Reviewer can cite "STYLE.md: Error handling §2" in findings, which is much more legible than line-anchored citations. Frontmatter holds metadata (`generated_at`, `source: capture|interview|ingest|natural-language`).

**Consult?** yes. **Trigger:** defines a public on-disk schema, hard to rename sections later, ≥2 options with materially different long-term consequences.

---

## D6. Scope of `mr-reviewer` finding categories — fixed list vs extensible

**Decision:** Are the five finding categories (defensive-bloat, test-noise, abstraction, hygiene, style-drift) hardcoded into the agent prompt, or configurable via STYLE.md?

**Options:**
- (a) Hardcoded in the agent prompt. Five categories from BRAINSTORM.md, fixed. Simpler, predictable findings.
- (b) STYLE.md declares categories; agent dynamically enumerates them. More flexible, more complex, risk of category-explosion.

**Tentative call:** (a). The five categories were the user's explicit framing; they cover both AI slop and human slop. Adding extensibility is YAGNI at v1.

**Consult?** no. Following stated user requirement; reversible if needed.

---

## D7. Global vs local STYLE.md merge semantics

**Decision:** If both `STYLE.md` (project) and `~/.claude/STYLE.md` (global) exist, how do they combine?

**Options:**
- (a) Project STYLE.md is the only one v1 reads. Global is a documented v2 extension.
- (b) Concatenate: global section first, project section second. Project overrides on conflict by being read second.
- (c) Project STYLE.md may declare `extends: ~/.claude/STYLE.md` in frontmatter; otherwise project-only.

**Tentative call:** (a). Brainstorm explicitly tagged "global ~/.claude/STYLE.md" as v2. Keep the v1 surface minimal.

**Consult?** no. YAGNI; deferred per brainstorm.

---

## D8. Diff scope — branch diff vs working-tree diff vs PR

**Decision:** What does "the diff" mean for `/z-mr-review`?

**Options:**
- (a) `git diff <base>...HEAD` where `<base>` defaults to `main` (or `master`), `--base <ref>` overrides. Branch-vs-trunk, matches how `/z-review-all` already works.
- (b) Working-tree diff (`git diff` + untracked). Catches in-progress work but is noisy.
- (c) PR-fetch from GitHub (`gh pr diff <num>`). Adds gh dep; useful for reviewing peer PRs.

**Tentative call:** (a) as default with `--base <ref>` and `--include-untracked` flags. Mirrors `/z-review-all`. (c) deferred to v2.

**Consult?** no. Following existing `/z-review-all` convention.

---

## D9. Where does `/z-mr-review` write its findings under the slug dir?

**Decision:** When `/z-mr-review` runs, which `<slug>` does it use? There may be no active z-harness plan at all.

**Options:**
- (a) Always require a `--slug` flag OR an active plan dir in `z-harness/`. Writes go to `z-harness/<slug>/MR-REVIEW.md`.
- (b) If no slug given, derive one from the branch name and create `z-harness/<branch>/MR-REVIEW.md`. Auto-namespaced per branch.
- (c) Single canonical location `z-harness/mr-reviews/<timestamp>.md`, no slug coupling. Reviews are independent of plans.

**Tentative call:** (b) with (a) as override. Default behavior: branch name → slug. Lets the command run anywhere without ceremony, plays nicely with existing slug conventions, and a user mid-plan can pass `--slug=<plan-slug>` to attach findings to their active plan.

**Consult?** yes. **Trigger:** affects the user-facing surface, hard to rename later, ≥2 options with materially different ergonomics.

---

## D11. Model tiering within `mr-reviewer`

**Decision (user-raised):** Some categories need whole-repo reasoning (dead code, missed-extraction / duplication), others only need diff-chunk reasoning (hygiene, defensive-bloat against impossible-state, repetitive tests). Single-model agent is wasteful in both directions.

**Options:**
- (a) Single Sonnet pass for all five categories. Loses dead-code / duplication signal (Sonnet won't reliably spot "this helper already exists three modules over").
- (b) Two-tier inside `mr-reviewer`: **Sonnet** sub-pass for `defensive-bloat`, `test-noise`, `hygiene`, `style-drift` (per-diff-chunk, no whole-repo grep needed). **Opus** sub-pass for `abstraction` (dead-code, missed-extraction, duplication-with-existing-code) — this pass is allowed to grep the codebase for similar patterns and reason holistically about "did this new code re-implement something we already have?". Returns merge into one MR-REVIEW.md.
- (c) Always Opus. Expensive; overkill for the four diff-only categories.

**Tentative call:** (b). Matches the existing complexity-classifier philosophy (model fits the work), and the user's specific concern (dead-code + extraction need whole-codebase context) is exactly the case where Opus earns its cost. The abstraction pass also gets a "diff length must be justified — every added line should be necessary; if a similar abstraction already exists, flag it" as a hardcoded prompt rule independent of STYLE.md.

**Consult?** no. Mechanical model-tiering, follows existing pattern.

---

## Hardcoded review principles (independent of STYLE.md)

Two principles are baked into the `mr-reviewer` agent prompt regardless of STYLE.md content (user-raised):

1. **Every added line must justify itself.** Net positive diff length is suspect by default. The Opus abstraction sub-pass should specifically ask "could this change have been done with fewer lines by editing existing code instead of adding new code?"
2. **Codebase shouldn't grow without reason.** Find dead code (the change made something dead), find missed-extraction (this new helper duplicates an existing one), find redundant tests (this new test exercises the same path as N existing tests).

These go in SPEC.md as agent-prompt invariants, not STYLE.md content. STYLE.md is for project-specific taste; these are universal anti-slop principles.

---

## D10. Telemetry / event shape

**Decision:** What events does `/z-mr-review` log?

**Tentative call:** Standard `run_start`, `run_end`, `phase_end` events from `scripts/log-event.sh`. Add `mr_finding_emitted` per finding (severity, category, file), `mr_finding_triaged` per user decision (accept/dismiss/defer), `mr_style_missing` if STYLE.md not found.

**Consult?** no. Mechanical, follows existing event conventions.

---

## Summary

| ID  | Decision | Consult |
|-----|----------|---------|
| D1  | File layout | no |
| D2  | Multi-LLM dispatch pattern (single agent fans out vs 3 parallel) | **yes** |
| D3  | Output format & TASKS.md handoff | **yes** |
| D4  | `/z-style-init` Capture mechanism | **yes** |
| D5  | STYLE.md schema | **yes** |
| D6  | Categories fixed vs extensible | no |
| D7  | Global+local STYLE.md merge | no |
| D8  | Diff scope | no |
| D9  | Slug coupling for `/z-mr-review` | **yes** |
| D10 | Telemetry | no |
| D11 | Model tiering within `mr-reviewer` (Sonnet + Opus abstraction pass) | no |

**Consult-flagged: 5** (D2, D3, D4, D5, D9) — exactly at the 5-cap. No need to split.
