# Phase 1 — Exploration context

## Doc-fetcher synthesis

### Rename propagation targets (current /z-research → /z-map)
- `commands/z-plan.md` lines 19, 52–54, 128–137 — Setup step 9 detects RESEARCH.md; Phase 1 skip rules.
- `commands/z-plan-light.md`, `commands/z-do.md`, `commands/z-brainstorm.md`, `commands/z-plan-split.md` — route mentions.
- `agents/planning-router.md` lines 58, 83 — route target enum + reason codes.
- `agents/consultant-primary.md`, `consultant-secondary.md` — routing language.
- `commands/z-research.md` → becomes `commands/z-map.md`.
- `skills/z-research/SKILL.md` → becomes `skills/z-map/SKILL.md`.
- Docs: `docs/llm/{commands,skills}.json`, `docs/human/{commands,skills}.md`, `docs/llm/INDEX.json` source_files lists.
- README.md command catalogue.
- exports/* regenerated.

### `/z-uplift` precedent — dispatch + nested-run pattern
- **Two-step handoff** (`commands/z-uplift.md` lines 2430–2433): orchestrator prints explicit `/z-implement-all --tasks=<path>` to user, marks MANIFEST `[i] implementing`, **exits cleanly** (does NOT wait inline). User re-invokes `/z-uplift`; resume path detects `[i]` row and continues.
- **Nested run-id** (lines 94–96): `RUN="$(date -u +%Y%m%dT%H%M%SZ)-$SLUG"`, all per-run artifacts under `archive/<RUN>/`.
- **Partial failure** (lines 2520, 2708): per-component event logging; bailed rows marked `[!] bailed:<reason>`; resume with `--retry-bailed` resets to `[ ] pending`.

### `/z-research` (current) Phase 0 cost-gate template
`commands/z-research.md` lines 88–107 — AskUserQuestion with three options (proceed / reduce / abandon). Abandon exits cleanly BEFORE Phase 0.5 (no workspace touch). Sets `EXPLORE_BUDGET` env. Logs `cost_gate_decision`. Pattern to reuse for new /z-research.

### `planning-router` agent contract
`agents/planning-router.md` — Haiku, read-only. Inputs: `current_command`, `task_or_topic`, `signals_json`, `route_chain_json`, `existing_artifacts` (optional). Outputs: line-prefix `STATUS:`, `RECOMMENDED:`, `ROUTE_CLASS:`, `CONFIDENCE:`, `REASON_CODES:`, `REASON:`. Decision rules prioritize contextual exits, terrain/approach rules, seam-based splits, file-count downrouting. Loop-prevention on route-chain depth ≥2.

### `/z-plan` RESEARCH.md consumption (the one-way gate target)
Setup step 9 (lines 52–54): freshness check on citations (regex + mtime vs `generated_at`); deleted-source detection; conflict check vs BRAINSTORM.md.
Phase 1 shortcut (lines 128–137): if RESEARCH.md non-stale AND has findings citing touched files AND zero open questions → skip BOTH doc-fetcher and Explore.

### Key implementation patterns to model after
- Two-step handoff (uplift) vs inline dispatch — design decision pending.
- Cost-gate AskUserQuestion (current /z-research Phase 0) — model verbatim for new /z-research.
- planning-router routing rules — must add reason code for "needs research-tier deep synthesis."
- MANIFEST-state resumption (uplift) — applicable if /z-research adopts two-step handoff.

## Context summary

The rename touches ~12 files (commands + agents + skills + docs + exports). The new /z-research orchestrator pattern has a strong precedent in /z-uplift's two-step handoff (print command, exit, resume on next invocation). The new /z-research must also implement: an intelligent dispatch decision (Phase 0.5) that proposes whether to run /z-map and/or /z-brainstorm based on artifact state; a cost-gate AskUserQuestion modeled after current /z-research; an adversarial-panel synthesis (3 parallel + final judge); the 10-section RESEARCH.md schema with approach decision matrix; a hard "FORBIDS new design recommendations" invariant; and /z-plan's RESEARCH.md detection logic extended to gate component-file fallback. /z-uplift provides the resumability pattern; current /z-research provides the cost-gate pattern; planning-router provides the routing-language extension target.
