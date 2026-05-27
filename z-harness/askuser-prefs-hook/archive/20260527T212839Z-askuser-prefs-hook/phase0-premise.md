# Phase 0 — Premise check

## Inputs

- BRAINSTORM.md (chosen_framing: codex): typed question payload + 5-tier signal strength.
- RESEARCH.md (status: complete): ~30 distinct AskUserQuestion patterns; audit→amend exists as a routing-class skip-eligible AskUser site at z-audit-plan.md:183 and z-audit-plan-style.md:384.

## Stated goal

Build a pre-AskUserQuestion preference resolver. v1 scope = the audit→amend leverage case + slug-derivation confirmation (the two highest-leverage routing-class skip-eligible patterns surfaced by research). Per the codex framing: typed question payloads, 5-tier signal strength (`hard | strong | very_strong | weak | conflict`), config-first authority, memories as soft signal.

## Premise questions

1. **Does the resolver actually solve the audit→amend friction?**
   - Friction has two components: (a) the redundant AskUserQuestion at z-audit-plan Phase 5 / z-audit-plan-style Phase 5 (research-confirmed), and (b) the slug-discovery dance inside `/z-amend` Phase 0 when invoked manually after an audit.
   - The resolver as scoped handles (a) cleanly via `workflow.after_audit = "amend"` config that auto-selects "Amend Plan (Run z-amend)" at both sites.
   - For (b) the resolver alone is **not sufficient** — `/z-amend` needs to read recent run context to auto-pin slug. That's a separate plumbing concern, not a resolver-hook concern. **Recommend out-of-scope for v1** but call it out in PLAN non-goals.

2. **Will the typed-payload approach actually work given the markdown-not-code constraint surfaced by research?**
   - AskUserQuestion sites are prose, not function calls. The resolver can't intercept a function call that doesn't exist. Two viable architectures:
     - **(arch-A) Convention.** Every skill spec invokes the resolver explicitly: "before AskUserQuestion at <question_id>, call `scripts/resolve-question.sh <question_id>`; if result is `skip`, skip; if `prefill`, present with default pre-filled; if `ask`, normal." Requires touching ~30 distinct spec patterns OR scoping v1 to just the 2-3 highest-leverage sites.
     - **(arch-B) Harness layer hook.** The Claude Code platform intercepts AskUserQuestion calls at tool-invocation time. Not in our control; requires Anthropic platform support.
   - v1 is feasible with **arch-A scoped to 2-3 sites** (audit→amend + slug-derivation). Both can be retrofitted in one round of edits.

3. **Is there a materially better path?**
   - **Alternative 1: Pass audit context directly into /z-amend** (Codex's "what would change my mind"). Skip the resolver entirely; instead make `/z-audit-plan` Phase 5 invoke `/z-amend --from <PLAN_AUDIT_REPORT.md>` directly when an env var or memory says so. **Verdict:** cleaner for THIS specific case but doesn't generalize. The resolver is a general-purpose primitive worth building once.
   - **Alternative 2: Just add CLI flags** like `--auto-amend` to `/z-audit-plan`. **Verdict:** too narrow; same problem for every other routing-class site.
   - **Alternative 3: Ship the resolver but only for slug-derivation in v1.** The slug-derivation pattern repeats across 7+ commands with identical option set; biggest leverage. **Verdict:** valid alternative. But misses the user's literal motivating example. Probably should do BOTH in v1 (slug-derivation + audit→amend) since they share infrastructure cost.

## Premise accepted

The goal as stated — pre-AskUserQuestion preference resolver per Codex framing, scoped to the audit→amend leverage case — is well-posed. v1 ships:

1. A `scripts/resolve-question.sh` (or `.py`) helper that reads typed question payload and emits `skip|prefill|ask` based on config + memory consultation.
2. A `[workflow]` section in the existing TOML config schema with at least `workflow.after_audit` and `workflow.slug_confirm_strategy`.
3. Spec-prose edits to ~3 sites: `/z-audit-plan` Phase 5, `/z-audit-plan-style` Phase 5, and the slug-derivation pattern (in `/z-plan`, `/z-fix`, `/z-debug`, `/z-brainstorm`, `/z-research`, `/z-plan-light`, `/z-uplift`).
4. A v1-scoped signal-strength model: only `hard` (config explicit → skip|prefill) and `none` (→ ask). Memory-based strong/very_strong/weak/conflict tiers deferred to v2.
5. Gemini's `/z-suggest-memory` redirect for users who try to write routing prefs as memories.

Out of scope for v1:
- `/z-amend` slug-discovery auto-pinning when invoked from audit context (separate concern; called out as non-goal).
- Memory-based signal-strength tiers (deferred — config is sufficient for the named use case).
- Halt-class bypass (spec_problem, decision_needed) — error-recovery sites are too risky.
- Multi-IDE export resolution model — Cursor/Codex/agy adapters will be a v2 concern; v1 is Claude-Code-only.
- Telemetry uniformity refactor — adding `askuser_called` events at every site is mechanical-but-pervasive; deferred.

## Caveats to surface to user before Phase 1

- The Codex framing's full 5-tier signal-strength taxonomy is over-engineered for v1. We're shipping a 2-tier resolver (`hard|none`) initially. Mention this in the decisions doc.
- The slug-derivation skip is a separate (and arguably more valuable) preference than audit→amend. Ship both or just audit→amend? Default: both, since shared infrastructure cost.
- Stable question_id strings are required. Naming them is a design decision and they're hard to rename later (public surface).
