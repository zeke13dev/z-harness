# z-brainstorm

> Last updated: 2026-06-19
> Covers source: commands/z-brainstorm.md, agents/ideator-clusterer.md

## Overview

`/z-brainstorm` is cheap, opt-in pre-plan ideation. It dispatches three vendor-diverse ideators (Claude, Codex, Gemini) in parallel, runs a mandatory anti-bias check, and produces a `BRAINSTORM.md` file that seeds a subsequent `/z-plan` invocation. The entire pipeline targets ≤200K tokens end-to-end. It does not produce SPEC/PLAN/TASKS — those come from `/z-plan` after the user locks in a framing.

The pipeline is organized into five phases. Phase 0 probes for scope (LIGHT/MEDIUM/HEAVY) and optionally sharpens a vague topic by auto-invoking `/z-sharpen` inline before any ideation begins. Phases 1–3 scaffold and run ideation. Phase 4 is a conversational discussion loop where the user can ask questions, challenge framings, request re-spins, combine directions, or lock in a choice. The orchestrator never auto-picks a framing — it always waits for an unambiguous signal from the user before writing `chosen_framing`.

## Key entry points

- `commands/z-brainstorm.md:1` — `/z-brainstorm` — Top-level command. Sets up slug, run-id, plan dir, run-brief; then executes Phase 0 through Phase 4 in sequence.
- `commands/z-brainstorm.md:82` — `Phase 0 — sharpen-vs-skip gate (D5)` — Heuristic check (GRILL.md present → skip; topic ≥40 chars + concrete markers → skip; topic <15 chars → sharpen; grey zone → one Haiku call). If "sharpen" wins, auto-invokes `/z-sharpen` inline to produce `GRILL.md`. Orthogonal to scope-probe: idea vagueness ≠ codebase fanout size.
- `commands/z-brainstorm.md:198` — `Phase 0 — count parse (wide N)` — Extracts ideator count N from natural-language prose (no `--wide` flag). Default N=3. "lots of / many / wide / mega" → N=6. Cap at 20. Sets `WIDE_N` for all downstream branches.
- `commands/z-brainstorm.md:536` — `Phase 1 — Scaffolding` — Assembles an identical payload for all ideators: doc-fetcher synthesis (Haiku; never reads `docs/llm/*.json` from main thread), optional Explore (gated on `Z_HARNESS_BRAINSTORM_EXPLORE=1`), MAP.md terrain (or accepted legacy RESEARCH.md), GRILL.md seed framing if present. Computes `input_hash` from all ingredients. Checkpoints to `archive/<RUN>/phase1-scaffolding.md`.
- `commands/z-brainstorm.md:632` — `Phase 2 — Parallel ideator dispatch` — Phase 2a draws up to 3 distinct personas from the `ideator` role pool (gated on `brainstorm.personas` knob; graceful degradation on underflow). Phase 2b dispatches all three ideators in one parallel message, each receiving identical scaffolding + the five-section `IDEATOR_SCHEMA`. Failure policy: 1/3 proceed, 2/3 `AskUser` (retry/proceed-with-1/abandon), 3/3 hard halt.
- `commands/z-brainstorm.md:739` — `Phase 2c — Wide mode dispatch` — Fires only when `WIDE_N > 3`. Resolves overflow model (prompt override > `brainstorm.wide_overflow_model` config > `haiku`; `cheap-mixed` is gated/no-op, fallback to haiku + inline warning). Presents a conversational cost estimate and **ends the turn** — HARD INVARIANT: no ideators dispatched until user confirms. Wave 1 is the existing Phase 2b dispatch. Overflow waves (2+) use the re-spin machinery with anti-seed divergence prompts in rotating vendor pairs. After all waves, dispatches `ideator-clusterer` (Haiku) to collapse N framings → K clusters. Cap: max 3 overflow waves (N > 9 → cap at 9, user informed).
- `commands/z-brainstorm.md:1026` — `Phase 3 — Synthesis + mandatory anti-bias check` — Parses ideator returns, runs the anti-bias check (every Claude-favoring pick needs explicit concrete justification), picks a tentative recommendation. Writes `BRAINSTORM.md` with YAML frontmatter (`chosen_framing: pending`, `ideator_personas` always written). Produces the ranked prose briefing inline and **ends the turn** (MUST NOT call `AskUserQuestion` or any further tool).
- `commands/z-brainstorm.md:1193` — `Phase 4 — HEAVY mode branch` — Parses the chunk×framing matrix from the unified `BRAINSTORM.md` (skips FAILED chunks). Presents a ranked pair briefing inline and ends the turn. Discussion loop interprets free-text reply; locks in `chosen_pair: {chunk_id, framing}` on unambiguous signal; HEAVY abandon uses `chosen_framing: abandoned` (no `chosen_pair`).
- `commands/z-brainstorm.md:1305` — `Phase 4 — LIGHT/MEDIUM discussion loop` — Interprets user's free-text reply for: ask-a-question, challenge/narrow, combine X+Y (draft synthesized framing + await confirm), re-spin (via re-spin machinery, cap 3), lock-in (write `chosen_framing` + `## User choice` verbatim), restart (archive + conversational refined-topic ask), abandon. `synthesized` is the default/expected outcome for a discussion-born hybrid.
- `commands/z-brainstorm.md:1375` — `Re-spin machinery` — Shared helper for the Phase 4 discussion loop and wide-mode overflow. Hard cap: 3 waves (fully-failed wave does not consume a cap slot). Subset is deterministic by wave number: wave1=Claude+Codex, wave2=Claude+Gemini, wave3=Codex+Gemini. Anti-seed prompt contains all prior framings + divergence instruction. Emits one-line cost note inline before dispatch. Appends `## Re-spin wave N` to `BRAINSTORM.md` (append-only). Emits `respin_wave` event.
- `agents/ideator-clusterer.md:1` — `ideator-clusterer` — Haiku subagent dispatched after all wide-mode waves complete. Reads N framing blocks from `BRAINSTORM.md`, clusters by core hypothesis / approach axis into K directions. Returns: K cluster labels + members + representative framing (verbatim), effective-diversity report, cross-cluster consensus. Read-only. Clusterer failure or K=0 → orchestrator falls back to N raw framings in the Phase 3 briefing.

## How it interacts with others

- `z-sharpen` — Auto-invoked inline at Phase 0 when the topic is vague. Produces `GRILL.md`. Phase 1c-ii ingests `GRILL.md` as seed framing injected into the scaffolding payload for all ideators.
- `commands/z-research` — Consumes `/z-brainstorm` as a downstream step after terrain discovery via `/z-map`.
- `agents/scope-probe` — Dispatched in Phase 0 (non-fast-path) to classify scope as LIGHT/MEDIUM/HEAVY and identify chunks for HEAVY fan-out.
- `agents/scope-reconciler-brainstorm` — HEAVY mode only: reconciles per-chunk BRAINSTORM.md files into the unified file that the orchestrator writes to the plan dir.
- `agents/ideator-clusterer` — Wide mode only (WIDE_N>3): collapses N ideator framings into K cluster directions for the Phase 3 ranked briefing.
- `config` — `brainstorm.personas` knob (ON by default) gates persona draw in Phase 2a. `brainstorm.wide_overflow_model` sets the model for overflow waves (default `haiku`).
- `personas-and-roles` — `resolve-persona.py random-distinct-for-role ideator --count=N` draws ideator personas in Phase 2a and for each overflow wave.
- `cost-estimation` — `pre-run-cost-gate.sh` called as a soft gate in the HEAVY path (auto-proceeds); wide-mode cost is surfaced as a conversational estimate inline (not a gate script call).
- `run-brief` — Run Brief initialized immediately after `brainstorm_run_start`; finalized in Phase 4 "In all branches". Outcome/next set from the user's Phase 4 pick.
- `active-plan-registry` — Session ID acquired via `active-plan-registry.py session-id` in Setup; plan dir resolved via `plan-path.sh resolve_plan_path`.

## Edge cases / gotchas

- **Phase 3 hard end-turn invariant.** After writing `BRAINSTORM.md` and producing the ranked briefing, the orchestrator MUST NOT call any further tool — not even Read. The next tool call comes only after the user replies in Phase 4.
- **Ambiguity guardrail (m5).** If the user's Phase 4 reply is ambiguous, ask a clarifying question conversationally — never write `chosen_framing` or `chosen_pair` on a guess.
- **Wide × HEAVY suppression (D2).** If `WIDE_N > 3` and the scope probe returns HEAVY, the HEAVY fan-out is entirely suppressed and `MODE` is downgraded to MEDIUM. The `wide_suppressed_heavy` event is emitted. These two fan-out axes never multiply.
- **Wide cost gate is conversational, not a structured gate.** The orchestrator presents an estimate inline and ends the turn. The user must send an explicit reply before any ideators are dispatched.
- **cheap-mixed is gated/no-op.** There is no verified `--model` path for codex-cli or agy. Setting `brainstorm.wide_overflow_model=cheap-mixed` triggers a fallback to `haiku` and an inline warning. The `wide_overflow_model_warn` event is emitted.
- **MAP.md vs RESEARCH.md terrain precedence.** MAP.md is the canonical artifact. RESEARCH.md is accepted only when `artifact_kind: map` or the field is absent (legacy). `artifact_kind: approach_synthesis` is explicitly skipped — it is a meta-orchestrator output, not terrain.
- **GRILL.md is included in `input_hash`.** A changed GRILL.md invalidates any stale cache hit and forces brainstorm to regenerate.
- **Re-spin append-only.** BRAINSTORM.md is never rewritten after Phase 3; all re-spin waves append under `## Re-spin wave N` headers. The file is the resumable state.
- **Parent attribution.** When `Z_HARNESS_PARENT_RUN_ID` is set (e.g. dispatched by `/z-research`), every `log-event.sh` call must include `parent_run_id` and `parent_command` fields.
- **HEAVY abandon shape.** HEAVY abandon sets `chosen_framing: abandoned` and omits `chosen_pair`. This keeps abandon detection uniform across modes in downstream consumers.
- **`ideator_personas` always written in Phase 3 frontmatter** — even when `brainstorm.personas=OFF` (all values `<none>`) or when an ideator failed (binding still recorded; the ideator appears as `<id>:failed` in `ideators`).

## Memories

<!-- DO NOT EDIT this section by hand — regenerated from docs/llm/z-brainstorm.json by doc-updater. Use /z-suggest-memory to add or edit memories. -->

_Note: no memories recorded yet._

## Examples

- Standard run: `/z-brainstorm rethink the batting order model` → auto-derives slug `rethink-batting-order`, runs Phase 0 scope probe (topic has enough specificity to skip sharpen), dispatches 3 ideators, produces ranked briefing, user replies "go with Codex framing", `chosen_framing: codex` written to `BRAINSTORM.md`.
- Wide run: `/z-brainstorm give me 6 ways to approach the auth redesign` → `WIDE_N=6`, conversational cost gate presented, on confirm: wave 1 (3 vendors) + 1 overflow wave (2 vendors) + ideator-clusterer, Phase 3 presents K cluster directions.
- Vague topic: `/z-brainstorm improve performance` → heuristic classifies as VAGUE (<15 chars, no concrete markers), `/z-sharpen` runs inline, produces `GRILL.md`, Phase 1 injects seed framing into scaffolding.
- HEAVY scope + wide request: `/z-brainstorm 5 ways to refactor the entire platform` → scope probe returns HEAVY, D2 suppression fires, `wide_suppressed_heavy` emitted, run proceeds as `WIDE_N=5 MODE=MEDIUM` (HEAVY fan-out skipped).
