# Phase 0 — Premise check

## Inputs
- BRAINSTORM.md (chosen_framing: claude — scope-probe as Phase 0 of every z-* command, structural-axis discovery, command-specific synthesis, aggressive deletions of mid-flight escalation chains)
- User Phase 0 gate: **Split into 2 plans.** This plan is v1a only.

## Goal as I understand it (v1a scope)

Build a Haiku `scope-probe` subagent that runs as Phase 0 of `/z-audit` and `/z-brainstorm` (v1 pilot integrations). The probe returns a typed manifest `{mode: LIGHT|MEDIUM|HEAVY, axis, chunks, rationale, confidence}` by walking the codebase structure 2 levels deep from candidate entities in the topic, counting natural seams (named cluster dirs, distinct import profiles), and querying doc-fetcher for cluster docs. Write a calibration harness that replays the probe against 5-6 historical runs from `z-harness/archive/` and compares classifications to the routing decisions those runs actually made mid-flight.

## Explicitly out of scope for v1a
- Deletion of existing escalation chains (z-plan-light Phase 1 up-route; z-plan pre-Phase-1 Plan Route Check; z-debug mid-flight architectural bail).
- Retiring/demoting `planning-router`.
- Folding `/z-plan-split` into `/z-plan` HEAVY.
- Integration into `/z-debug`, `/z-plan`, `/z-review-all`, `/z-implement-all`.

These all move to v1b, gated on v1a calibration meeting the 4 falsifiability tripwires:
1. NOT ≥70% MEDIUM (probe overhead < prevented cost)
2. NOT HEAVY <20% (probe latency justified)
3. Synthesis produces equal-or-better output than single MEDIUM
4. Natural axis is structurally (not semantically) determinable by Haiku

## Coexistence policy (v1a → v1b transition)

While v1a ships, existing mid-flight escalation chains stay in place. The new `scope-probe` runs Phase 0 of `/z-audit` and `/z-brainstorm` only; for those two commands, mid-flight escalation logic becomes redundant in the HEAVY path but does not conflict (both can fire). v1b will surgically remove the redundancy after data confirms scope-probe's classifications align with what mid-flight escalation would have decided.

## Premise concerns checked
- **Does this solve the underlying problem?** Yes — the user's stated pain is "pay for full /z-audit then bail." Pre-flight sizing addresses exactly that. The split into v1a+v1b reduces the blast radius if the structural-axis hypothesis turns out wrong.
- **Will it work?** Conditional on tripwire 4 (Haiku can determine axis structurally). The calibration harness is the explicit test. If tripwire 4 fires, v1a still has value as an advisory hint surface and v1b is canceled rather than half-built.
- **Better path?** Codex's framing in BRAINSTORM (shared script-lib + adapters, keep mid-flight as assertions) is close to what the user just chose by picking Split. v1a is effectively Codex's spine; v1b is the Claude-pure aggressive refactor *iff calibration validates*. Best of both.

## Premise accepted

Plan v1a: scope-probe Haiku subagent + SCOPE.json schema + calibration harness against historical archive runs + /z-audit Phase 0 integration + /z-brainstorm Phase 0 integration. Deletions explicitly deferred to v1b.
