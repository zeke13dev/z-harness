# PLAN — z-fix-hypothesis-driven

## Goal

Restructure the existing single `/z-debug` command into two user-facing commands (`/z-fix` light + `/z-debug` heavy hypothesis tournament) so each can specialize without the discipline-vs-ceremony compromise the current one-size-fits-all command suffers from. Operationalize the hypothesis-tournament discipline (Cursor-style: generate → discriminating test per hypothesis → orchestrator-assigned likelihood → ordinal Bayesian posterior → fix-gate requires highest posterior AND causal mechanism) using the project's existing multi-LLM consultant infrastructure.

## Non-goals

- Do not introduce a `--light` / `--heavy` flag on a single command (explicit-commands preference; matches `/z-plan` vs `/z-plan-light` precedent).
- Do not auto-route or auto-graduate `/z-fix` → `/z-debug` under the hood (each command recommends the other via early gate; no silent escalation).
- Do not introduce floating-point Bayesian probabilities (ordinal buckets only — LLMs are poorly calibrated and false precision was the top scoring risk flagged in BRAINSTORM).
- Do not change the existing `debug-hypotheses` or `light-fix` consultant modes (additive only; new modes side by side).
- Do not migrate today's `/z-debug` separate-file artifacts (PROBLEM/EVIDENCE/ISOLATION/FIX/POSTMORTEM) — they are replaced wholesale by unified DEBUG.md going forward. No back-compat shim.

## Decisions (with rationale)

### D1 — Separate commands `/z-fix` and `/z-debug` (locked in BRAINSTORM)
Two distinct user-facing commands. Mirrors `/z-plan` vs `/z-plan-light`. User picks via command name. Each has an early gate to recommend the other.

### D2 — Single unified `DEBUG.md` artifact (per BRAINSTORM User choice; Gemini caught me missing this)
All sections in one file: Problem, Evidence Inventory, Hypothesis Pool, Test Matrix, Experiment Log, Score Updates, Eliminated Alternatives, Root Cause, Fix Plan, Verification, Post-mortem. Mitigation for context bloat: subagent dispatches use surgical section extraction (Round-2 sees Hypothesis Pool only; fix consult sees Root Cause + Experiment Log).

### D3 — Ordinal Bayesian scoring with Codex-revised lookup table
Three priors × five likelihoods → six-level ordinal posterior. Strong-falsified always eliminates regardless of prior; strong-supported can promote any prior to `very_high`; inconclusive preserves prior. **Orchestrator alone interprets test output and assigns the likelihood bucket** (Gemini's key addition — breaks the D3/D4 deadlock and prevents consultant-consensus from contaminating result interpretation).

### D4 — 3-LLM tournament (orchestrator-Claude + Codex + Gemini) with pre-dispatch checkpoint
3-source overlap gives the prior bucket three usable levels (`3→high, 2→med, 1→low`); 2-LLM would collapse this to binary. Contamination mitigation: orchestrator writes its own Round 1 hypothesis block to `archive/<run>/round1-orchestrator.md` BEFORE dispatching the parallel consultant calls, and reads from that file (not from conversation state) during the merge step.

### D5 — Two new consultant modes, mirrored across Codex + Gemini agents
`generate-hypotheses-round1` (independent generation, Round 1 schema, `schema_version: hypothesis_round1_v1`) and `generate-hypotheses-round2-adversarial` (additions + critiques given Round-1 pool, `schema_version: hypothesis_round2_v1`). Round-2 prompt explicitly forbids agreement-only returns ("Your value is orthogonality and critique, not endorsement"). Both modes return RAW (no standard wrapper). Existing `debug-hypotheses` mode retained untouched.

### D8 — Optional post-mortem in `/z-fix`, default-off with auto-suggest
Default = NO. If Phase 8 Codex review needed >1 retry cycle, default flips to YES with prompt text "Suggesting post-mortem — simple fix may have been subtler than expected." `/z-debug` post-mortem remains mandatory (the discipline path).

### D6/D7/D9/D10/D11/D12/D13/D14 — see SPEC + decisions.md
Outlier carve-out = top 2 (D6). Isolation cycle cap = 5 (D7). Wrong-tool gate lives in Phase 0 of each command (D9). `/z-debug` auto-bail softened — multi-module / architectural / new-public-surface only, no >5-files trigger (D10). Round 2 prompt asks for BOTH orthogonality AND test-quality critique (D11). Matrix is markdown table only, schema header documented at top of Test Matrix section (D12). Implementation stays inline (D13). docs/llm/ refresh done manually in this plan; `/z-maintain-docs` verifies later (D14).

## Approved shortcuts

None. All five consult-flagged decisions resolved to robust calls. The only deviation from tentative was D2, which was a correction to align with the BRAINSTORM User choice — not a shortcut.

## Risks carried forward (per BRAINSTORM, must not be lost)

- **False confirmation at scale** (Claude) → mitigated by fix-gate's two requirements (highest posterior AND causal mechanism explaining all evidence, not "supported by a test" alone).
- **Parallel test pollution** (Codex + Gemini) → `parallel_safe: bool` per Test Matrix row; only `true` rows batch. Round 2 critique explicitly checks for false-positive `parallel_safe` tags.
- **False precision** (Codex + Gemini) → ordinal buckets only, no floating-point.
- **Context exhaustion** (Gemini) → surgical section extraction for every subagent dispatch.
- **Multi-LLM groupthink** (Codex + Gemini) → Round 2 adversarial generation; forced outlier carve-out (top 2 overlap=1 hypotheses always tested early).
- **Ceremony for trivial bugs** (Codex) → command split — users with known cause pick `/z-fix` and skip the tournament entirely.

## Ordered phases

### Phase A — Consultant agent updates (must land first; commands depend on the new modes)
1. `agents/codex-consultant.md` — add `generate-hypotheses-round1` + `generate-hypotheses-round2-adversarial` to the Modes list, the Ask templates, and the Returning section (both modes return RAW).
2. `agents/gemini-consultant.md` — mirror identical changes.

### Phase B — New `/z-fix` command + companion docs
3. `commands/z-fix.md` — new file per SPEC.
4. `docs/human/z-fix.md` — new companion doc.
5. `docs/llm/commands.json` — add z-fix concept entry.

### Phase C — `/z-debug` rewrite + companion docs
6. `commands/z-debug.md` — major rewrite per SPEC (heavy tournament pipeline, unified DEBUG.md, posterior table, orchestrator-only likelihood, EVID-NNN + H-NNN ID schemes, Evidence coverage table, Phase-visibility matrix, Round 2 table schemas, fix-gate evidence-coverage precondition, Phase 0 wrong-tool gate, softened auto-bail).
7. `docs/human/z-debug.md` — new companion doc (worked example with EVID/H IDs + posterior table + Evidence coverage table + orchestrator-likelihood sidebar + Phase-visibility matrix).
8. `docs/llm/commands.json` — update z-debug entry (`last_updated`, new `summary`).

### Phase C2 — `skills/z-debug/SKILL.md` lockstep rewrite (per Q6 review finding)
9. `skills/z-debug/SKILL.md` — parallel rewrite mirroring `commands/z-debug.md` body. Every artifact reference (PROBLEM.md / EVIDENCE.md / ISOLATION.md / POSTMORTEM.md) updated to `DEBUG.md ## Section` form. Skill metadata (frontmatter) preserved.

### Phase D — Doc index refresh
10. `docs/llm/agents.json` — update consultant entries with new modes.
11. `docs/llm/INDEX.json` — add z-fix concept; refresh `last_updated` for commands, agents, z-fix.

### Phase E — Migration audit + dependent-command refresh (expanded per Q6)
12. `commands/z-improve.md:45` — update reference to `POSTMORTEM.md` / `PROBLEM.md`. Either point to `DEBUG.md ## Post-mortem` / `DEBUG.md ## Problem` for post-rewrite runs, OR explicitly document "legacy artifacts for archive runs prior to the rewrite" (orchestrator must accept either).
13. `skills/z-improve/SKILL.md:45` — mirror change from `commands/z-improve.md`.
14. `commands/z-stats.md:97-99` — update z-debug flow descriptions and `POSTMORTEM.md` action-item language to reference `DEBUG.md ## Post-mortem`.
15. `skills/z-suggest-memory/SKILL.md:382-385` — update references to POSTMORTEM.md `Root cause` section and PROBLEM.md `Relevant concepts:` line to point to `DEBUG.md ## Post-mortem` / `DEBUG.md ## Problem`.
16. `commands/z-suggest-memory.md:2` — description references "/z-debug post-mortem" conceptually; keep as-is (no file path).
17. `README.md` — grep + refresh any `/z-debug` examples or descriptions that reference the old separate-file layout.

### Phase F — Verification
18. Self-check: `grep -rn -E "PROBLEM\.md|EVIDENCE\.md|ISOLATION\.md|POSTMORTEM\.md" commands/ skills/ docs/ README.md` — every remaining hit must be either (a) inside a section-name reference to `DEBUG.md`, or (b) explicitly tagged as a legacy-archive reference.
19. Self-check: ensure `commands/z-debug.md` and `skills/z-debug/SKILL.md` are body-equivalent (frontmatter may differ).
20. Self-check: verify `agents/codex-consultant.md` and `agents/gemini-consultant.md` are mirror-equivalent for the two new modes (mode list, Ask templates, return-shape contract).

## DRY / KISS / SOLID

(Carried verbatim from SPEC for visibility — these are non-negotiable.)
- **DRY:** `/z-fix` reuses `/z-plan-light` flow; consultant modes are mirrored single-source-of-truth across both agents.
- **KISS:** ordinal buckets not floats; markdown tables not JSON; user-picked commands not auto-routed; fixed 3×5 lookup table not computed.
- **SOLID:** single-responsibility per command/per mode; new modes added by extension; consultant agents interchangeable for every supported mode; per-mode return contracts.
