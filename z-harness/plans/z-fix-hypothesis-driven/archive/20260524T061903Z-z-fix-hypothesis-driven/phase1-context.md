# Phase 1 — Exploration

## Doc-fetcher synthesis (deep)

**Plugin layout:**
- `commands/z-<name>.md` — slash command definitions (frontmatter `description` + `argument-hint`; body is procedure).
- `agents/<name>.md` — subagent system prompts (frontmatter `name`/`description`/`tools`/`model`).
- `docs/human/<concept>.md` — human-readable docs.
- `docs/llm/INDEX.json` — concept registry (metadata: slug, source_file[], last_updated, confidence, depends_on[], consumed_by[], summary).
- `docs/llm/<concept>.json` — per-concept token-compact docs (entry_points, invariants, gotchas, memories).
- `scripts/log-event.sh`, `scripts/version.sh` — telemetry/versioning utilities.

**Command conventions:**
- Every command derives a kebab-case slug, exports `Z_HARNESS_SLUG`, namespaces output under `z-harness/<slug>/`.
- Run-frozen archives at `z-harness/<slug>/archive/<run-id>/` with `events.jsonl`, `transcripts/`, `phase<N>.md` checkpoints.
- `/z-plan-light` produces a single `FIX.md` artifact (replaces SPEC/PLAN/TASKS for small fixes).

**Consultant agents (codex-consultant.md, gemini-consultant.md):**
- Caller signals mode via `MODE: <name>` prefix.
- Existing modes: `bundled-decisions`, `plan-review`, `light-fix`, `debug-hypotheses`, `brainstorm`, `research-review`, `doc-audit`, `test-cases`, `mr-review`.
- Standard return wrapper for analytical modes (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). Raw return (no wrapper) for `brainstorm`, `research-review`, `mr-review`.
- Must archive prompt+response under `z-harness/archive/<run>/transcripts/NNN-<agent>-<mode>.{prompt,response}.md` and log a `consult` event.
- Model: Haiku for both.

## Current /z-debug structure (commands/z-debug.md, 343 lines)

8 phases:
- P1 PROBLEM.md — clarifying questions, expected vs actual, reproducibility, recent changes.
- P2 EVIDENCE.md — repro + captured output + relevant logs/DB state.
- P3 Hypothesize — 2-3 ranked hypotheses with supporting/refuting evidence + test-design.
- P4 Bundled cross-LLM consult — both consultants in `debug-hypotheses` mode; re-rank.
- P5 ISOLATION.md — test top hypothesis, one cycle = one experiment, cap 3 cycles.
- P6 Root cause + fix — reuses `/z-plan-light` Phases 3-9 (consult `light-fix`, write FIX.md, inline implement, Codex review).
- P7 POSTMORTEM.md — mandatory preventative analysis; optional `/z-mr-review` integration; convert action items to tasks or `/z-test` follow-ups.
- P8 Finalize — log debug_run_end.

Auto-bail thresholds: multi-module/architectural, >5 files, new public surface, >3 hypothesis cycles, broader design flaw.

## Gap to close (per BRAINSTORM.md User choice)

Current `/z-debug` will become the **heavy hypothesis-tournament** path. Net changes from today:

- **P3 split into P3a + P3b** (Round 1 independent generation, Round 2 adversarial). Today: orchestrator alone proposes 2-3; new: 3 LLMs each propose 3-5 then critique others.
- **New artifact `MATRIX.md`** (or extend ISOLATION.md) — discriminating-test matrix with `{claim, proposed_by, overlap_count, prediction_if_true, prediction_if_false, discriminating_test, cost, parallel_safe, prior_bucket, posterior_bucket, status}`.
- **Ranking rule** — consensus-first by overlap_count, **plus** forced outlier carve-out (always include top 1-2 unique-to-one-model hypotheses regardless of overlap).
- **Scoring** — ordinal Bayesian (prior bucket from overlap_count, likelihood bucket from test result, posterior via fixed lookup table). NO floating-point probabilities.
- **Isolation cycle cap** — 3 → 3-5.
- **Fix gate** — requires highest posterior AND written causal mechanism explaining all evidence.
- **New consultant modes** — `generate-hypotheses-round1`, `generate-hypotheses-round2-adversarial` added to BOTH `codex-consultant` and `gemini-consultant`.
- **Early gate** — if user describes "I think I know what's wrong," recommend `/z-fix`.

## New `/z-fix` (light) needs

Net-new command. Structurally a re-skinned `/z-plan-light` with bug framing:

- Captures problem + repro (P1+P2 condensed).
- User-stated hypothesis (single).
- One bundled `light-fix` consult (already exists) — but the sanity-check question is "*does the user's proposed cause explain all observed symptoms?*", not "what's the best fix design?".
- Implement inline + non-negotiable Codex review.
- Early gate: if scope feels wrong (multiple unknowns, no clear hypothesis), exit with `"recommend /z-debug"`.
- Likely NO POSTMORTEM (`/z-fix` is for the known-cause path; post-mortem is the discipline of `/z-debug`). Or: optional, scaled-down version.

## Files to touch (initial estimate)

1. `commands/z-debug.md` — major rewrite for heavy tournament path.
2. `commands/z-fix.md` — net-new file.
3. `agents/codex-consultant.md` — add 2 modes.
4. `agents/gemini-consultant.md` — add 2 modes (mirror).
5. `docs/llm/commands.json` — update z-debug entry, add z-fix entry.
6. `docs/llm/agents.json` — update consultant entries with new modes.
7. `docs/llm/INDEX.json` — update concept timestamps; ensure new files indexed.
8. `docs/human/z-fix.md` — net-new human doc.
9. `docs/human/z-debug.md` — refresh if it exists (need to check).

(~8-9 files. Cross-module impact = no, all within the plugin.)
