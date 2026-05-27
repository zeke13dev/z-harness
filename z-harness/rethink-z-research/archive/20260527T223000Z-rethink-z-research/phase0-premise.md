# Phase 0 — Premise check

## BRAINSTORM injection
chosen_framing: codex. Locked design (full detail in [BRAINSTORM.md](../BRAINSTORM.md) User choice section): rename current `/z-research` → `/z-map`; build new `/z-research` as meta-orchestrator that composes `/z-map` + `/z-brainstorm` with dynamic freshness-biased dispatch, then runs adversarial synthesis panel (or single Opus fallback), emitting RESEARCH.md with 10-section schema including approach decision matrix.

## Premise concerns checked

**Does the goal solve the underlying problem?** Yes. The user reported `/z-research` is misleading — they expected depth (how-to investigation), got terrain mapping. The BRAINSTORM decisively rejected the round-1 `/z-spike` sibling framing and locked the meta-orchestrator framing. Goal addresses exactly that.

**Will the approach work?** Conditional on three load-bearing design calls. Calling out, NOT blocking:
1. **Meta-orchestrator that dispatches slash commands is a new pattern.** `/z-uplift` already dispatches `/z-implement-all` internally, so the precedent exists, but only at single-instance scale. The new `/z-research` will dispatch `/z-map` (heavy, ≤2M tokens) AND `/z-brainstorm` (≤200K) AND a synthesis panel. Implementation must address: nested run IDs, telemetry attribution (event events.jsonl scope), cost accounting at the parent level, partial-failure semantics (what if `/z-map` errors mid-flight — abort? resume? fall back to MAP.md if existing?).
2. **Adversarial-panel synthesis is unproven.** Three vendor-diverse synthesizers + a judge is ambitious. The Codex falsifier — "if parallel synthesizers produce duplicated abstraction, drop to single Opus" — is the safety hatch. v1 should ship the single-Opus path first; adversarial panel is a v1.5 upgrade if v1 telemetry shows single-Opus output is too narrow.
3. **The rename has propagation cost.** Renaming `/z-research` → `/z-map` touches: commands/z-research.md (becomes /z-map), skills/z-research/SKILL.md (becomes /z-map), commands/z-plan.md (precontext rules), commands/z-uplift.md (route mention), commands/z-do.md (route mention), commands/z-plan-light.md (route mention), docs/human/{commands,skills}.md, docs/llm/{commands,skills,review-agent}.json + INDEX.json, README.md (command catalogue), exports/* (regenerated). Bounded but multi-file.

**Better path the user hasn't considered?** The BRAINSTORM explored 3 framings; user picked. No new paths to surface.

## Scope adjustments for v1

Given complexity + risk, **flag for the user in Phase 5**:
- **v1 ships single-Opus meta-synthesis**, not adversarial panel. Adversarial panel is a v1.5 enhancement gated on v1 telemetry.
- **v1 always-fresh dispatch** (always run /z-map and /z-brainstorm). Dynamic freshness-biased dispatch (skip if fresh MAP.md/BRAINSTORM.md exists) is a v1.5 enhancement.
- **No probe phase in v1** (already accepted in BRAINSTORM — restating for clarity).

Both v1 simplifications keep the orchestrator-only-code property intact while reducing failure surface. The rich design (adversarial panel, dynamic dispatch) lands in v1.5 once we have telemetry from v1.

## Premise accepted (post-user-clarification — full BRAINSTORM scope)

User clarified: the whole point is "more / extra brainstorming capabilities." Cutting the adversarial-panel synthesis to single-Opus would remove the actual value-add over `/z-brainstorm` and reduce /z-research to "/z-brainstorm + /z-map glued together." **Keep the full BRAINSTORM scope.**

Plan v1:
- Rename current /z-research → /z-map (preserving No-recommendation invariant inside /z-map).
- Build new /z-research as orchestrator. **Dispatch policy = intelligent decision** (not "always" and not "strictly skip-if-exists"): orchestrator inspects slug state (MAP.md present + fresh? BRAINSTORM.md present + chosen_framing? topic alignment?), proposes a dispatch plan to the user via AskUserQuestion (highly suggesting "run both" by default; surfaces a "skip" option only when an artifact exists and looks fresh + aligned).
- **Adversarial meta-synthesis panel:** three vendor-diverse synthesizers (architecture-conservative + product/workflow-expansive + failure-mode-adversarial) run in parallel; a final judge synthesizes their outputs into RESEARCH.md. The Codex falsifier ("if panel output is duplicated abstraction, drop to single Opus") becomes a v1 retrospective tripwire — fire it after v1 telemetry, not before.
- **10-section RESEARCH.md schema** including approach decision matrix (rows = approaches from BRAINSTORM, columns = constraint classes from MAP, cells cited or `UNVERIFIED`).
- **Hard invariant:** synthesis FORBIDS new design recommendations; ALLOWS only collision-flagging + framing rank-ordering.
- **/z-plan one-way gate** on RESEARCH.md.
- **Cost gate** via AskUserQuestion at invocation (3–6M tokens estimate).
- **4 falsifiability tripwires** per BRAINSTORM.
- **No spike/probe phase** in v1 (rejected unanimously).

Implementation challenge to address in SPEC: meta-orchestrator that dispatches `/z-map` + `/z-brainstorm` internally is a new pattern at this scale. Must address nested run IDs, telemetry attribution, cost accounting at parent level, partial-failure semantics (what if `/z-map` errors mid-flight). `/z-uplift` provides a precedent (dispatches `/z-implement-all`); model after it.
