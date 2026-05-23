# Phase 3 — Synthesis after cross-LLM consult

## Convergent picks

Both Gemini and Codex independently recommended **A / D / A / A** for the four consult-flagged decisions — matching the tentative calls. This is the strongest possible consensus signal: orthogonal LLMs, given the same decisions doc, picked the same options for the same reasons.

## One reason each might be wrong (mechanical pushback)

- **D1=A could be wrong if** stale `BRAINSTORM.md` / `RESEARCH.md` files accumulate in slug dirs and confuse later `/z-plan` runs. Mitigation: YAML frontmatter with `generated_at`; `/z-plan` Phase 0 warns if artifact is older than its source files (`mtime` check, same pattern as `docs/llm/INDEX.json` staleness gate).
- **D2=D could be wrong if** the anti-bias procedural check becomes performative — Codex flagged this. Mitigation: enforce that every ideator returns the SAME structured sections (Framing, Core hypothesis, Risks, Plan implications, "What would change my mind"). The check becomes objective: section-by-section comparison.
- **D4=A could be wrong if** users want to brainstorm without committing to a slug name. Mitigation: Codex's `--slug <slug>` flag idea — both new commands accept it; default auto-derives. Also: `/z-plan` collision detection updated to distinguish "precontext-only slug dir (continuation)" from "finished plan dir (collision)."
- **D5=A could be wrong if** RESEARCH.md routinely exceeds 20 KB. Mitigation: extractive summary preserves specifics — Gemini's nuance. Store the generated summary at `archive/<run>/research-summary-for-brainstorm.md` so ideator context is auditable.

## Enhancements to fold into SPEC.md (from consult)

1. **YAML frontmatter on artifacts:** Each `BRAINSTORM.md` / `RESEARCH.md` opens with a frontmatter block: `artifact: brainstorm|research`, `slug:`, `generated_at:`, `command:`, `input_hash:` (sha256 of the topic + scaffolding inputs), `depends_on:` (path to upstream artifact if chained). Replaces the need for a manifest file (Codex).
2. **Structured ideator return shape.** Every brainstorm ideator returns the same five-section block — makes synthesis comparable, makes the anti-bias check objective.
3. **Symmetric ideator context.** All ideators (Claude, Codex, Gemini) get the same inline scaffolding payload. Never let Claude read by reference while Codex/Gemini get inline excerpts — that creates a context-asymmetry bias.
4. **`--slug <slug>` flag on both commands.** Default to auto-derived slug; allow explicit override for intentional chaining.
5. **Extractive (not abstractive) summary** if RESEARCH.md > 20 KB. Preserve specific names, paths, constraints, file:line citations.
6. **Source attribution in SPEC.md.** `/z-plan` adds a "Planning Inputs" section to SPEC.md noting which precontext artifacts were consumed (paths + generated_at). Auditable trail.
7. **Phase 0 collision handling update.** `/z-plan` distinguishes precontext-only slug dirs (BRAINSTORM/RESEARCH present, SPEC/PLAN absent — continuation) from finished plan dirs (SPEC/PLAN present — collision).
8. **Conflict surfacing.** If RESEARCH.md and BRAINSTORM.md contradict (e.g. research found a constraint that the chosen brainstorm framing violates), `/z-plan` Phase 0 surfaces the conflict to the user before continuing.

## Confirmed picks

| Decision | Pick | One-line rationale |
|---|---|---|
| D1 — Artifact contract | A (distinct files, with YAML frontmatter) | Semantically clear schemas beat forced unification; frontmatter handles metadata needs |
| D2 — Ideator composition | D (Claude + Codex + Gemini, anti-bias via structured returns) | Diversity beats bias-elimination; procedure beats structural changes |
| D4 — Slug derivation | A (shared slug, `--slug` override) | Matches existing slug-as-task-identity pattern; explicit flag for chaining intent |
| D5 — RESEARCH.md → ideator context | A with extractive-summary fallback >20 KB | Symmetric inline context mandatory; large-doc summary stored as audit checkpoint |

Plus 4 non-consulted decisions (D3, D6, D7, D8) carried forward from `decisions.md` unchanged.
