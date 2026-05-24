---
artifact: brainstorm
slug: mr-style-reviewer
generated_at: 2026-05-23T19:24:15Z
command: /z-brainstorm Add MR-Style reviewer in addition to or separate from z-review (requires an init)
input_hash: 7c4d2e9a1b8f3506
depends_on: []
ideators:
  - claude
  - codex
  - gemini
ideator_models:
  claude: sonnet
  codex: default
  gemini: default
status: complete
chosen_framing: claude
---

# Brainstorm — MR-style code-quality reviewer

## Framing: claude

### Framing
A **diff-scoped AI-slop detector**. Reads only the delta, treats the existing codebase as ground truth, and hunts five specific AI-shaped anti-patterns: (a) defensive bloat for impossible cases, (b) test signal-to-noise (repetitive low-information tests), (c) over/under-abstraction (code length creep or missing obvious extraction), (d) name/comment hygiene (dead comments restating code, drive-by reformatting), (e) STYLE.md drift. The right surface is a new command `/z-mr-review`, not `/z-audit --dimension=style`, because audit semantics are "is this area good?" and MR semantics are "did this *change* make things worse?".

### Core hypothesis
Two standalone commands in v1, no `/z-review-all` integration yet:
- `/z-mr-review` — runs the MR reviewer over the current branch diff against `STYLE.md` (local) + global `~/.claude/STYLE.md` if present.
- `/z-style-init` — interactive STYLE.md authoring with cross-LLM critique of the draft.

Add a `--no-style` flag that forces a **conscious refusal** to run without a taste reference, rather than silently degrading to generic checks. STYLE.md is required by default; init is the friction that earns the right to keep using the tool.

### Risks
- **False negatives on legitimate defensive code** — the fatal trust-killer. If the reviewer flags a real `try/catch` around an external API as "AI slop", the user disables the tool immediately and never comes back. Mitigations: require the reviewer to cite the impossible-state claim against actual call sites, and demote uncertain findings to "discuss" rather than "must-fix".
- **STYLE.md cold-start** — without an init flow, the reviewer has nothing to anchor on and devolves to taste-essay LLM defaults.
- **Scope bleed into correctness** — once the reviewer is reading the diff, it will be tempted to call out bugs, duplicating `codex-reviewer`. Hard prompt-level prohibition required.
- **Integration-point multiplication** — bundling into `/z-review-all` now creates a coupling that's hard to undo if signal quality is poor.

### Plan implications
- Two commands (`/z-mr-review`, `/z-style-init`), one new agent (`mr-reviewer.md`).
- Findings emitted in **five explicit categories** matching the framing (defensive-bloat / test-noise / abstraction / hygiene / style-drift) — not free-form prose.
- No v1 integration into `/z-review-all`. Promote later only if measured signal > noise.
- `/z-style-init` should support three input paths: ingest existing guide, interactive Q&A, free-form natural language. All three converge to a draft that Codex + Gemini critique once before user-approval.

### What would change my mind
- If empirical use shows that the existing `auditor` with a `STYLE.md` rubric passed as `--rubric` produces equivalent finding quality, collapse this into `/z-audit --dimension=style --rubric=STYLE.md` and only keep `/z-style-init` as the novel piece.
- If users consistently want the MR review to gate merges at the same severity as correctness, fold it directly into `/z-review-all` and skip the standalone command.

---

## Framing: codex

### Framing
This should not be framed as a new "style audit" dimension. The important distinction is **reviewing the delta as an MR**, not auditing the component as a static artifact. `/z-audit cleanliness+rubric` asks: "Is this area good?" An MR-style reviewer asks: "Did this change make the codebase worse in agent-characteristic ways, even if the feature works?" The unit of review is the diff, surrounding local context, and stated task intent.

It should care about: avoidable code growth; needless abstraction or missing obvious abstraction; defensive branches for states that cannot happen; missed real boundary cases despite noisy guardrails; repetitive tests that increase line count without increasing confidence; stale comments and naming drift introduced by the patch; unrequested reformatting or churn; mismatch with `STYLE.md`. Value is strongest as a **final or near-final gate on changed code**, not as a repo audit.

### Core hypothesis
A **standalone MR-quality agent with STYLE.md as one input**, optionally invoked by `/z-review-all`. The agent shape must differ from `auditor.md`:
- Input: cumulative diff, touched files, task/spec summary, optional `STYLE.md`, selected surrounding code.
- Output: **MR-like verdict** — `must fix before merge`, `should fix if cheap`, `ignore`. This blocking/non-blocking primitive is what makes it feel like a code review instead of a lint report.
- Explicitly suppress preference nits unless tied to project style, maintainability, or future bug risk.
- Hunts **agent fingerprints**, not generic cleanliness: over-broad try/catch, speculative null checks, duplicated test matrices without semantic variation, comments restating code, helper names encoding implementation instead of domain, code that grew because the agent avoided editing existing abstractions, unrelated formatting churn.

`STYLE.md` is the local constitution, not the reviewer. Single command (`/z-code-review` or `/z-quality-review`) with `--init-style` sub-flag rather than a separate init command.

### Risks
- **Duplicating existing gates** trains users to ignore review output entirely.
- **Style-lawyering** — low-signal nits after implementation are worse than useless; they add friction at the highest-cost moment.
- **Overfitting STYLE.md into a checklist** — good style is judgment (naming, abstraction thresholds, testing philosophy, error-handling posture); reducing it to mechanical rules yields a worse-than-deterministic linter.
- **Final-gate timing** — if it only runs after `/z-review-all`, broad quality issues surface when the implementation context is cold and expensive to revise.
- **Cross-LLM critique during STYLE.md init becoming taste essays** rather than concrete project rules.

### Plan implications
- Build the init subflow **first** — reviewer quality depends on a project-local target.
- Artifacts: `STYLE.md` (human-readable), optionally `.z-harness/style-source.md` for provenance, one slash command (`/z-style-init` or `/z-quality-init`), one reviewer agent (`mr-quality-reviewer.md`).
- Init supports three paths (ingest existing guide / interactive Q&A / free-form natural language) → draft → Codex + Gemini critique once → revise → user approval.
- Runtime: standalone `/z-quality-review` for explicit MR review of current diff; optional `/z-review-all --quality` flag or config default; later bundle into `/z-review-all` only after signal quality proven.
- Default emit only blockers + majors; verbose mode for minors.

### What would change my mind
- Collapse into `/z-audit --dimension=cleanliness --rubric=STYLE.md` if the desired output is a broad component assessment rather than diff review.
- Bundle directly into `/z-review-all` if users treat quality findings as merge-blocking at the same severity as correctness drift.
- Standalone only if expected use is iterative (review → clean up patch → re-review → then correctness gate).
- Skip the new agent entirely if `auditor.md` can be cheaply extended with a "diff mode" + changed-file context + MR-style output.
- Skip STYLE.md init if the plugin grows a reliable project-doc discovery layer that can synthesize style expectations from code, docs, linters, and tests with sufficient precision.

---

## Framing: gemini

### Framing
The fundamental problem isn't that AI agents write *incorrect* code; it's that they write **AI-flavored** code. Hyper-defensive error handling, tautological "1+1=2" tests, over-commenting the obvious, gradual drift from the project's idiomatic terseness. The existing `/z-audit cleanliness/design` is too generic and academic — it operates like a static-analysis tool looking for standard code smells. An MR-style reviewer must be an **aggressively opinionated, adversarial persona** ("the Senior Nitpicker") explicitly tuned to hunt and eradicate AI-generated cruft, forcing the codebase back to a human-like, idiomatic baseline. Name the threat: **"Agent-Slop"**.

### Core hypothesis
The MR reviewer should **not** be an add-on to `/z-audit`. It must be an **integrated, unavoidable gatekeeper fused directly into `/z-review-all`** as a mandatory cross-LLM "Vibe Check" phase. Instead of a generic audit report, it emits **PR-review-style line comments** targeting specific line numbers against an interactive `STYLE.md`. A new `/z-init-style` command uses Gemini to **interview the user and analyze the project's most idiomatic existing files** to draft a STYLE.md grounded in reality — a **Capture** tool, not a Generator. Bold placement: run the slop check *before* the expensive correctness checks in `/z-review-all`, short-circuiting Codex/Gemini correctness review if the code fails the slop test.

### Risks
- **Subjective blocking** — "style" and "AI cruft" are highly subjective; an overly aggressive reviewer triggers infinite refactor loops (`/z-amend` edit-war) over comment phrasing that stalls delivery.
- **Style Guide Hallucination / compliance theater** — STYLE.md becomes a write-only document that nobody internalizes and the reviewer just enforces literally.
- **Workflow bloat** — injecting an intensive review phase into `/z-review-all` adds significant latency and token cost to an already heavy operation.
- **Orchestration bloat / user confusion** — if the only difference from `/z-audit --cleanliness` is the prompt text, users won't understand which tool to reach for.
- **Falsifiability thresholds**: >90% finding parity with auditor → fold; >30% user-rejection rate on findings → noise generator, retire.

### Plan implications
- `/z-init-style` as a **standalone interactive Capture** flow: analyzes repo for idiomatic patterns, interviews user, drafts STYLE.md with explicit anti-patterns.
- Build `mr-reviewer.md` as a new agent prompt **entirely distinct from `auditor.md`** — assumes correctness, hyper-focused on brevity, idiom, defensive-boilerplate elimination.
- Modify `/z-review-all`: inject `mr-reviewer.md` as a **parallel pass alongside correctness checks** (or pre-gate before them), emit direct line-level action items rather than a generalized report.
- Redefine `/z-audit`: strictly scope its `cleanliness` / `design` dimensions to **structural patterns** (SOLID, DI, layering) to prevent overlap with the MR reviewer's stylistic focus.

### What would change my mind
- If empirical testing shows that feeding a detailed STYLE.md to the existing `auditor.md` via `/z-audit --dimension=cleanliness --rubric=STYLE.md` effectively eliminates AI code smells without a specialized prompt or persona, the overhead of a distinct MR reviewer is unjustified.

---

## Anti-bias check

Section-by-section comparison. Where Claude wins, an explicit justification is required.

- **Framing.** Tie between Claude and Codex on operational precision (both correctly identify diff-vs-audit as the load-bearing distinction). Gemini wins on **naming force** ("Agent-Slop", "Senior Nitpicker") which is genuinely useful for adoption and self-documentation, and on naming the threat model explicitly. **Gemini wins this section.**
- **Core hypothesis.** Codex's **blocking / non-blocking / ignore verdict primitive** is the only proposal that gives the reviewer a UX that feels like real code review. Claude and Gemini both miss this. **Codex wins.**
- **Risks.** Claude wins on **false negatives on legitimate defensive code** — the most likely reason users disable the tool. **Explicit justification (Claude bias check):** Codex named adjacent risks (style-lawyering, duplicating gates) and Gemini named adjacent risks (subjective blocking, edit-war loops), but neither named the specific failure mode where a *correct* defensive pattern around an external API gets flagged as slop. That single false-positive at first use destroys trust permanently — it is the highest-severity risk and only Claude surfaced it. Gemini's edit-war / hallucination risks are strong runners-up. **Claude wins.**
- **Plan implications.** Gemini's **"Capture not Generate"** insight for `/z-style-init` (analyze idiomatic files in the repo to ground STYLE.md in actual project reality) is materially better than Claude's interactive-Q&A and Codex's three-paths-merging-to-draft. Without Capture, STYLE.md is just an LLM's idea of good style. **Gemini wins.**
- **What would change my mind.** Codex provides the **most numerous and operational** fallback paths (5 distinct collapse conditions vs Claude's 2 vs Gemini's 1). Gemini provides **measurable falsifiability thresholds** (>90% parity, >30% rejection) which is more rigorous. Call it a tie.

**Tally**: Gemini 2, Codex 1, Claude 1, Tie 1. No systematic Claude bias — Claude won exactly one section (Risks) with a documented concrete justification.

## Orchestrator recommendation

**Codex framing** as the structural base, amended with the two best non-Codex insights:
- Adopt Codex's **standalone command** + **blocking / non-blocking / ignore verdict UX** + **three STYLE.md authoring paths** + **agent-fingerprints taxonomy**.
- Replace Codex's init-as-flag with Gemini's **Capture-based `/z-style-init` as its own command** (analyze idiomatic files in repo first, then interview user, then critique). Capture is the load-bearing insight.
- Adopt Claude's **`--no-style` forcing function** (refuse to run without STYLE.md unless explicitly opted out) and **five-category finding taxonomy** for output structure.
- **Defer `/z-review-all` integration to v2.** Gemini's pre-correctness-gate placement is interesting but premature — prove signal quality on the standalone command before coupling. Promote if signal proves out.

Rationale: Codex's verdict UX is what makes this feel like a real code review and not a static-analysis dump; Capture is what makes STYLE.md authentic instead of generic; `--no-style` protects against silent quality regression. Gemini's "fuse into /z-review-all" is the right v2 destination, not the right v1 starting point. User is free to override.

---

## User choice

**Picked framing: Claude (two standalone commands)**, hybridized with selected pieces of Codex and Gemini. User overrode the orchestrator's Codex recommendation in favor of the cleaner Claude shape to avoid polluting `/z-review-all`.

### Final shape carried into /z-plan

**Surface (Claude's structure).** Two standalone slash commands:
- `/z-mr-review` — runs the MR-style code-quality reviewer over the current branch diff.
- `/z-style-init` — interactive STYLE.md authoring with cross-LLM critique.

No v1 coupling into `/z-review-all`. The workflow position is **after `/z-implement-*` and before any correctness review** — fix quality first, then run correctness. The MR review should be *suggested* (push-notify / next-step hint) at the end of `/z-implement-all`, not auto-invoked.

**Reviewer mechanics (multi-agent diff review, Gemini's persona).** The `/z-mr-review` command dispatches **multiple cross-LLM agents in parallel** (Claude + Codex + Gemini) over the diff, each adopting the **"Senior Nitpicker"** persona from Gemini's framing. Each agent emits findings; results are deduplicated and surfaced together. This is the same fan-out pattern `/z-review-all` already uses, but pointed at quality instead of correctness.

**Finding taxonomy (Claude's five categories — expanded).** Findings are emitted in explicit categories, not free-form prose. **Scope is not just AI slop — also "regular human slop"**: dead code, copy-paste, drift, hygiene problems that humans introduce too. Categories:
- Defensive bloat / impossible-state guards
- Test signal-to-noise (repetitive low-information tests)
- Abstraction problems (length creep, missing extraction, gratuitous indirection)
- Name & comment hygiene (dead comments, restate-the-code comments, drive-by reformatting, sloppy names)
- STYLE.md drift (local STYLE.md + global `~/.claude/STYLE.md` if present)

**STYLE.md init (Gemini's Capture-first insight).** `/z-style-init` is not pure interactive Q&A. It is a **Capture-first** flow: analyze the most idiomatic existing files in the repo, then interview the user, then optionally ingest an existing style guide, then draft STYLE.md, then cross-LLM critique (Codex + Gemini) for omissions, then user approval. Three input paths converge: ingest existing / Capture+interview / natural language.

**Finding severity (P0–P4 ranking, user-driven triage).** Each finding is ranked P0 through P4. The reviewer does not gate or block — it presents the ranked list and the user picks which to address. Suggested rubric:
- **P0** — would actively cause future bugs or maintenance pain (e.g. silent except-pass over a real failure mode, abstraction collapse).
- **P1** — clear quality regression vs the rest of the codebase (e.g. defensive bloat against impossible state, dead AI-generated comment scaffolding).
- **P2** — STYLE.md violation or noticeable idiom drift.
- **P3** — minor hygiene (stale comments, naming oddities, redundant tests).
- **P4** — taste-only nits.

**STYLE.md is a hard prerequisite.** `/z-mr-review` requires a project STYLE.md. If absent, it refuses to run and points the user at `/z-style-init`. There is no `--no-style` escape hatch — running the reviewer without a style reference produces generic LLM-default opinions, which is exactly the failure mode we are trying to avoid. The init flow is a one-time setup cost paid before any review work.

### Open questions to resolve in /z-plan
- Should `/z-mr-review` dedupe across the three LLM voices, or surface them separately for the user to read each persona's take? (Recommendation: surface separately first; dedup if signal-to-noise demands it.)
- How should P0–P4 findings be presented for triage? (Likely: grouped by severity, with a per-finding "address / dismiss / defer" action, written into a TASKS.md-compatible artifact so `/z-implement-*` can pick up accepted fixes.)
- Where does global `~/.claude/STYLE.md` get authored? Out of scope for v1, but `/z-style-init --global` is the obvious extension.
- Scope-bleed enforcement: hard prompt-level prohibition against finding correctness bugs (those belong in `codex-reviewer` / `/z-review-all`). The mr-reviewer agent prompt must explicitly say "assume correctness; defer to correctness reviewers for bugs."

