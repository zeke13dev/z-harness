# SPEC — rethink-z-research v1

## Overview

Rename current `/z-research` → `/z-map` (preserving its No-recommendation invariant). Build new `/z-research` as a meta-orchestrator that intelligently dispatches `/z-map` and/or `/z-brainstorm` based on slug state, then runs an **adversarial synthesis panel** (3 vendor-diverse perspectives + final judge) to produce `RESEARCH.md` with a 10-section schema including an approach decision matrix (rows = approaches, columns = constraint classes, cells cite source or marked `UNVERIFIED`). `/z-plan` gets a one-way gate: if RESEARCH.md exists + valid, it's canonical precontext; component files (MAP.md, BRAINSTORM.md) become fallback.

## Planning Inputs

| Artifact | Path | generated_at |
|---|---|---|
| BRAINSTORM.md | z-harness/rethink-z-research/BRAINSTORM.md | 2026-05-27T21:52:22Z |
| RESEARCH.md | — | n/a (this slug IS the research design) |

## Goals

1. Rename `/z-research` → `/z-map` across all commands/skills/agents/docs/exports (12 files).
2. New `/z-research` command + skill that orchestrates Phase 0 cost-gate → intelligent dispatch decision → inline subcommand dispatch (with audit trail) → adversarial synthesis panel → 10-section RESEARCH.md.
3. New `research-judge` agent (Opus) that reads 3 panel perspectives + writes final RESEARCH.md content.
4. Extend `/z-plan` Setup step 9 with one-way gate behavior (artifact_kind frontmatter dispatch).
5. Extend `planning-router` reason codes: `needs_terrain_map` → /z-map; `needs_approach_synthesis` → /z-research; deprecated alias `needs_research` for one version cycle.

## Non-goals

- No spike/probe phase in v1 (rejected unanimously in BRAINSTORM).
- No two-step handoff for sub-command dispatch (inline + audit trail chosen).
- No automatic /z-plan invocation from /z-research (user explicitly opts in next).
- No backward-compat alias for command name `/z-research` pointing to old behavior (atomic rename per D9).

## Per-file specs

### `agents/research-judge.md` (NEW)

**Frontmatter:**
```yaml
---
name: research-judge
description: Final-judge synthesizer for /z-research. Reads N=3 adversarial-panel perspective outputs + the MAP.md + BRAINSTORM.md source artifacts; produces the final RESEARCH.md content (10 sections per SPEC) including the approach decision matrix with mandatory citations. Read-only — returns text; orchestrator writes the file. HARD INVARIANT: forbidden from proposing new design recommendations. ALLOWED: collision-flagging, framing rank-ordering by constraint-fit, evidence-gap surfacing.
tools: Read
model: opus
---
```

**Inputs (in prompt):**
- `host_run_id`
- `slug`
- `perspectives: [{name, return_path}]` — array of 3 panel perspective outputs (paths to archive files)
- `map_path` — abs path to MAP.md
- `brainstorm_path` — abs path to BRAINSTORM.md
- `output_schema_version: 1`

**Procedure:**
1. Read all 3 perspective outputs + MAP.md + BRAINSTORM.md.
2. Extract approaches from BRAINSTORM.md (each ideator's Plan implications + Core hypothesis).
3. Extract constraint classes from MAP.md (e.g. API surface, concurrency, persistence, performance, deployment — pick top 4–6 most relevant constraint groupings).
4. Build approach decision matrix: rows × columns. Each cell = verdict (`OK | BLOCKS | RISKY | UNVERIFIED`) + 1-line citation (`<file>:<section> — <snippet>`). Cells without citation are mandatorily marked `UNVERIFIED`.
5. Extract cross-artifact contradictions: where map evidence contradicts ideator assumptions; cite both sides.
6. Synthesize the 10 sections (see RESEARCH.md schema below).
7. Self-check: scan output for new design proposals. If any found, strip them and emit a `research_judge_temptation` event in the return notes.

**Hard rules:**
- Read-only. Never edits files. Returns RESEARCH.md content as response text.
- Cite MAP.md or BRAINSTORM.md per claim. Uncited claims → `UNVERIFIED`.
- FORBIDDEN: proposing new design, adding architectural recommendations, picking a winner approach.
- ALLOWED: rank-ordering by constraint-fit (deterministic from matrix); collision-flagging (mechanical from contradictions section); evidence-gap surfacing (mechanical from UNVERIFIED count).

### Synthesis panel dispatch (NOT a new agent — uses existing consultant proxies for real vendor diversity)

**Critical fix from Phase 7 review:** Earlier draft proposed a new `research-synthesizer` agent with `model: opus` — that's Anthropic-only, not vendor-diverse. Real vendor diversity requires using the existing provider-proxy agents (`consultant-primary`, `consultant-secondary`) which resolve to actual third-party CLIs at runtime, plus `general-purpose` (Sonnet/Opus) for the Anthropic perspective.

**Panel composition (per-perspective dispatch):**
- **architecture-conservative perspective** → dispatched via `Agent(subagent_type="general-purpose", model="opus", ...)`. The Anthropic/Claude perspective.
- **product/workflow-expansive perspective** → dispatched via `Agent(subagent_type="consultant-primary", ...)`. Resolves to whichever provider the user has bound to consultant_primary in providers.json (typically Codex).
- **failure-mode-adversarial perspective** → dispatched via `Agent(subagent_type="consultant-secondary", ...)`. Resolves to whichever provider the user has bound to consultant_secondary (typically Gemini).

Each is invoked with `MODE: research-synthesis-<perspective>` and the same input shape:
- `host_run_id`, `slug`, `perspective`, `map_path`, `brainstorm_path`

Each returns the 4-block analysis (Approach scoring / Constraint emphasis / Contradictions noticed / Citations) per the panel contract below.

**Provider-unavailable fallback:** if `consultant-primary` or `consultant-secondary` returns `bad_input` because the provider CLI is unavailable, log `research_panel_provider_unavailable {perspective, provider}` and proceed with the other two perspectives (treat as 1/3 fail per D11). Hard-coded Opus is NOT the fallback — that loses the vendor diversity that the panel exists to provide.

**Per-perspective prompt structure:**
- **architecture-conservative:** "Which framings are most compatible with existing patterns? What's the lowest-risk implementation path given MAP.md constraints? Cite MAP.md or BRAINSTORM.md per claim."
- **product/workflow-expansive:** "Which framings open the most user-facing capability? What does each framing enable that others don't? Cite both artifacts per claim."
- **failure-mode-adversarial:** "What fails first in each framing? Where does each accumulate hidden coupling, debt, or fragility? Cite both artifacts per claim."

Each return must contain:
- `## Approach scoring` (per BRAINSTORM approach, this perspective's verdict)
- `## Constraint emphasis` (which MAP.md constraints this perspective considers load-bearing)
- `## Contradictions noticed` (where this perspective disagrees with the others or with stated assumptions)
- `## Citations` (file:section refs)

Same No-new-design invariant as research-judge: forbidden from proposing new approaches; allowed only to score, emphasize, and contradict.

### `agents/research-synthesizer.md` (NEW — DEPRECATED in v1 by Phase 7 review)

~~The original SPEC proposed this agent with `model: opus`.~~ Per Phase 7 review (vendor diversity is fake with a single-model agent), this is REPLACED by dispatching the three perspectives via existing `general-purpose` + `consultant-primary` + `consultant-secondary` (see panel composition above). **No new `agents/research-synthesizer.md` file is created.**

**Inputs:** `host_run_id`, `slug`, `perspective: architecture_conservative | product_expansive | failure_mode_adversarial`, `map_path`, `brainstorm_path`.

**Procedure (per perspective):**
- **architecture_conservative:** which framings are most compatible with existing patterns? what's the lowest-risk implementation path given MAP.md constraints?
- **product_expansive:** which framings open the most user-facing capability? what does each framing enable that the others don't?
- **failure_mode_adversarial:** what fails first in each framing? where does each framing accumulate hidden coupling, debt, or fragility?

Each returns:
- `## Approach scoring` (per BRAINSTORM approach, this perspective's verdict)
- `## Constraint emphasis` (which MAP.md constraints this perspective considers load-bearing)
- `## Contradictions noticed` (where this perspective disagrees with the others or with stated assumptions)
- `## Citations` (file:section refs)

**Hard rules:**
- Same No-new-design invariant as research-judge.
- Caller's `perspective` parameter determines lens; agent must NOT bleed perspectives.

### `commands/z-map.md` (RENAMED from commands/z-research.md)

Atomic rename. All current content preserved. Header changes from `/z-research` to `/z-map`; artifact references change from `RESEARCH.md` to `MAP.md`. The `## No-recommendation` invariant stays inside /z-map verbatim.

Frontmatter `description:` updated to "Maps terrain with citations + cross-LLM critique. No recommendations — terrain only. See `/z-research` for synthesis across map + brainstorm."

### `commands/z-research.md` (NEW — replaces renamed file)

**Frontmatter:**
```yaml
---
name: z-research
description: Higher-order meta-orchestrator. Composes /z-map (terrain) and /z-brainstorm (framings), then runs adversarial synthesis panel (3 perspectives + judge) producing RESEARCH.md with 10-section schema including approach decision matrix. Cost 3–6M tokens; AskUser cost gate at invocation.
argument-hint: <research-topic> [--slug=<kebab>]
---
```

**Phases:**

**Setup:** standard slug derivation, archive setup, version stamp, run_start. Note `RUN` for nested sub-folders.

**Phase 0 — Dispatch decision (intelligent, user-driven):**
1. Read slug dir state. Compute:
   - **MAP_STATE** = `absent` | `fresh` | `stale`. **Algorithm (Gemini graft):** if no MAP.md → `absent`. Else read MAP.md frontmatter `generated_at`; get most-recent git commit timestamp on `$Z_HARNESS_PLAN_DIR/MAP.md` source files via `git log -1 --format=%cI -- <file>`; if any cited source file's commit timestamp > `generated_at` → `stale`; else → `fresh`. Untracked uncommitted changes in cited files are NOT counted (avoid spurious staleness from in-flight work).
   - **BRAINSTORM_STATE** = `absent` | `complete` | `incomplete`. **Algorithm:** if no BRAINSTORM.md → `absent`. Else parse frontmatter `status:` field — if `complete` AND (`chosen_framing` present OR `chosen_pair` present) → `complete`; else → `incomplete`.
2. **Dispatch decision matrix (4-bucket simplification per Gemini graft):**
   - `MAP=absent|stale` + `BRAINSTORM=absent|incomplete` → suggest **"Run both"**.
   - `MAP=absent|stale` + `BRAINSTORM=complete` → suggest **"Run /z-map, reuse BRAINSTORM"**.
   - `MAP=fresh` + `BRAINSTORM=absent|incomplete` → suggest **"Reuse MAP, run /z-brainstorm"**.
   - `MAP=fresh` + `BRAINSTORM=complete` → suggest **"Reuse both, synthesize directly"**.
3. AskUserQuestion presents the suggested dispatch + 3 options:
   - **Confirm suggested** (default — single click)
   - **Override** (free-text: which to skip / which to force)
   - **Abandon**
4. Log `research_dispatch_decision {map: <ran|reused|skipped|abandoned>, brainstorm: <ran|reused|skipped|abandoned>}`.

**Phase 0.5 — Cost gate:**
1. Compute estimate based on dispatch decision:
   - /z-map run: +2M
   - /z-brainstorm run: +200K
   - Synthesis panel (3 perspectives @ ~1M each): +3M
   - Judge: +0.5M
2. AskUserQuestion: "Estimated cost: <N> tokens. Proceed / Change dispatch (loops to Phase 0) / Abandon."
3. Log `research_cost_gate_decision`.

**Phase 1 — Subcommand dispatch (inline, with audit contract):**

**Sub-run audit contract (addresses Phase 7 Codex finding):**

The orchestrator cannot mutate a sub-command's internal RUN id (each sub-command derives its own from `date -u +%Y%m%dT%H%M%SZ`). Audit attribution uses the **child-emits-event-with-parent-attribution** pattern, NOT a shared run-id:

1. Orchestrator exports `Z_HARNESS_PARENT_RUN_ID=<orchestrator's RUN>` and `Z_HARNESS_PARENT_COMMAND=/z-research` into the Agent() dispatch environment.
2. Sub-command's Setup detects `$Z_HARNESS_PARENT_RUN_ID` and includes `parent_run_id` field in every `log-event.sh` payload it emits. (Existing `log-event.sh` already accepts arbitrary JSON; no script changes needed — just sub-command Setup must read the env var and include the field.)
3. After the sub-command completes, orchestrator captures the sub-command's RUN id from the return (each skill emits `run_start` and `run_end` events to its own events.jsonl; orchestrator reads the live `Z_HARNESS_PLAN_DIR/archive/<sub-run>/events.jsonl` to extract the sub-run id).
4. Orchestrator creates a **symlink** `archive/$RUN/subruns/<sub-command>` → `archive/<sub-run>/` (cross-link, not copy — preserves single source of truth + appears in parent's audit tree).
5. Orchestrator emits `research_subcommand_complete {sub, status, sub_run_id, sub_archive_path}`.

For each sub-command marked "ran" in dispatch_decision:
1. Mkdir `archive/$RUN/subruns/` (parent dir only; the symlink lands inside).
2. Set `Z_HARNESS_PARENT_RUN_ID=$RUN` and `Z_HARNESS_PARENT_COMMAND=/z-research` in the dispatch env.
3. Dispatch via Agent() invoking the underlying skill code (fresh subagent context).
4. After return, extract the sub-run id from the sub-command's emitted run_start event.
5. Symlink `archive/$RUN/subruns/<sub-command>` → `archive/<sub-run>/`.
6. Verify resulting MAP.md or BRAINSTORM.md was written by the sub-command (live artifact in `$Z_HARNESS_PLAN_DIR` with a frontmatter check: required `artifact:` field present + content > 100 bytes).
7. Emit `research_subcommand_complete {sub, status, sub_run_id, sub_archive_path}`.

**Sub-command Setup change required:** /z-map and /z-brainstorm skills' Setup must be edited to read `$Z_HARNESS_PARENT_RUN_ID` and include it in their log-event payloads (one new task). Backward-compatible — env var absent means no attribution field, same as today.

**Phase 2 — Adversarial synthesis panel:**
1. Dispatch 3 `research-synthesizer` agents in parallel, one per perspective (architecture_conservative, product_expansive, failure_mode_adversarial). Vendor assignment per D4 (static round-robin: Claude-conservative, Codex-expansive, Gemini-adversarial — but Opus-tier for all to keep depth).
2. Failure semantics per D11: match /z-brainstorm pattern (1/3 fail → proceed with 2 + judge; 2/3 fail → AskUser; 3/3 → halt).
3. Capture each perspective's return to `archive/$RUN/panel/<perspective>.md`.
4. Emit `research_panel_lane_complete {perspective}` per return.

**Phase 3 — Judge synthesis:**
1. Dispatch `research-judge` agent with paths to 3 panel returns + MAP.md + BRAINSTORM.md.
2. Judge returns full RESEARCH.md content as text.
3. Orchestrator writes RESEARCH.md atomically (tmp+rename).
4. Emit `research_judge_complete`.

**Phase 4 — Finalize:**

1. Self-check RESEARCH.md: required frontmatter fields present, 10 sections present, at least N×M matrix cells filled (where N=approaches, M=constraint classes).

2. **Automated tripwires (v1 — fire at finalize time):**
   - **`research_high_unverified_rate`** — if >50% of matrix cells marked `UNVERIFIED`, log the tripwire + suggest re-running /z-map with refined topic. Does NOT halt; advisory only.
   - **`research_panel_degraded`** — if `panel_perspective_count < 3`, log + suggest user inspect synthesis quality before consuming.
   - **`research_judge_temptation`** — if judge return notes flag stripped new-design proposals, log + surface to user (synthesis layer attempted to recommend; quality concern).

3. **Post-launch tripwires (BRAINSTORM T1–T4 — telemetry only; require N>1 production runs to evaluate):**
   - T1: `/z-plan` ignores constraint columns (manual review post-3-runs).
   - T2: users expect code sketches (manual review post-feedback).
   - T3: panel output redundant (manual review of first 3 panel outputs).
   - T4: trivial synthesis (manual review of first 3 RESEARCH.md outputs against hypothetical single-Opus baseline).
   - If any fire, follow-up `/z-amend` proposes adjustments per PLAN.md Phase F.

4. Push-notify per policy. Recommended next: `/z-plan <task>` to consume RESEARCH.md as canonical precontext.

### `skills/z-map/SKILL.md` (RENAMED from skills/z-research/SKILL.md)

Atomic rename matching commands/z-map.md.

### `skills/z-research/SKILL.md` (NEW — replaces renamed file)

Mirror of commands/z-research.md procedure with skill-style formatting.

### `commands/z-plan.md` (EDIT)

**Setup step 9 amendment (Phase 7 Codex grafts: detect MAP.md + rewrite skip rules for new schema):**

1. Detect MAP.md, BRAINSTORM.md, AND RESEARCH.md as precontext artifacts. (Previously only BRAINSTORM.md + RESEARCH.md — MAP.md added because the rename means standalone /z-map runs need to be visible to /z-plan.)
2. Distinguish RESEARCH.md by `artifact_kind` frontmatter:
   - **`artifact_kind: approach_synthesis`** (new RESEARCH.md from new /z-research) + `status: complete` → **one-way gate active.** Inject ONLY RESEARCH.md as precontext; skip MAP.md + BRAINSTORM.md injection.
   - **`artifact_kind: map`** (legacy old-RESEARCH.md not yet renamed) → treat as MAP.md per the next bullet (file existence check + freshness).
   - **No `artifact_kind` field** → treat as legacy MAP.md per existing behavior (component-file injection).
   - **`status: incomplete`** → halt and recommend re-running /z-research.
3. **Phase 1 skip rules rewritten for new schema (Codex graft — old rules used `Findings:` / `Open questions:` sections that don't exist in new RESEARCH.md):**
   - **When one-way gate is active** (new RESEARCH.md):
     - Skip doc-fetcher iff RESEARCH.md `## Approach decision matrix` section has ≥1 cell with `OK` or `RISKY` verdict citing a file in task's likely-touched set.
     - Skip Explore iff RESEARCH.md `## Evidence gaps` section is empty (no UNVERIFIED cells aggregated).
   - **When one-way gate inactive** (legacy MAP.md or component-file mode): skip rules unchanged — use existing `Findings:` / `Open questions:` logic on MAP.md.
4. Inject sources: RESEARCH.md content + frontmatter when gate active; OR MAP.md + BRAINSTORM.md component files when gate inactive.

### `agents/planning-router.md` (EDIT)

**Reason code additions:**
- `needs_terrain_map` → recommends `/z-map`. Triggered by "what does the codebase look like" signals.
- `needs_approach_synthesis` → recommends `/z-research`. Triggered by "both terrain AND approach uncertain" or "have map + brainstorm but need synthesized matrix" signals.
- `needs_research` (DEPRECATED ALIAS): keep for one version cycle; emit warning + map to `needs_terrain_map`. Drop in next major.

**Decision rules update:** existing logic that picked `/z-research` based on "terrain uncertain" now picks `/z-map`. New rule: if `signals_json.has_map_and_brainstorm: true` AND `signals_json.approach_uncertain: true` → `needs_approach_synthesis` → `/z-research`.

### `commands/z-uplift.md`, `commands/z-do.md`, `commands/z-brainstorm.md`, `commands/z-plan-light.md`, `commands/z-plan-split.md` (EDITS)

Rename references: any string mention of `/z-research` that pointed to the OLD terrain-mapping behavior becomes `/z-map`. Any new references to the meta-orchestrator stay as `/z-research`.

**`/z-brainstorm` Phase 1c special case (Phase 7 Codex graft):** Phase 1c currently ingests `RESEARCH.md` as terrain scaffolding. After rename, that file is now `MAP.md`. Update `/z-brainstorm` Phase 1c to: (1) ingest `MAP.md` (renamed) first; (2) if MAP.md absent, check for legacy `RESEARCH.md` with `artifact_kind: map` (or no artifact_kind) as backward-compat for pre-rename plans; (3) explicitly skip new RESEARCH.md with `artifact_kind: approach_synthesis` (that's a synthesis output, not raw terrain — not useful as brainstorm scaffolding).

### Rename surface verification step (Phase 7 Codex graft)

After all rename edits land, run a post-implementation verification grep:

```bash
rg -n "/z-research|z-research|RESEARCH\.md|needs_research" --type md --type json -g '!z-harness/**' -g '!docs/llm/MEMORIES-FLAT.md'
```

Each hit must be classified:
- Refers to NEW `/z-research` (meta-orchestrator) — leave as-is.
- Refers to old behavior (terrain map) — rename to `/z-map` / `MAP.md` / `needs_terrain_map`.
- Deprecated alias mention (router `needs_research` for one cycle) — leave with explicit deprecation comment.

Specifically check:
- `.agent/workflows/*.md` — likely contains exported references; will be regenerated via `scripts/export-agy.py` but verify post-regen.
- `exports/{cursor,codex,agy}/**` — regenerated; verify post-regen.
- `skills/z-uplift/SKILL.md` — verify (low confidence; may not reference but check).
- `commands/z-export.md` — verify the export adapter knows about the renamed source files.

### `docs/llm/{commands,skills,agents}.json` + `docs/human/{commands,skills,agents}.md` (REGEN)

Doc-updater regenerates after rename + new file additions.

### `docs/llm/INDEX.json` (EDIT)

- `commands` entry: source_files updated (z-research.md still present but content is new; z-map.md added).
- `skills` entry: same shape.
- `agents` entry: add `research-judge.md` + `research-synthesizer.md`.

### `README.md` (EDIT)

Command catalogue: rename `/z-research` to `/z-map` in the old description; add new `/z-research` entry describing the synthesis orchestrator.

### `exports/{cursor,codex,agy}/*` (REGEN)

Regenerated from updated sources via `scripts/export-*.py`.

## RESEARCH.md schema (lead with matrix; 10 sections)

**Frontmatter:**
```yaml
---
artifact: research
artifact_kind: approach_synthesis
schema_version: 1
slug: <slug>
generated_at: <ISO 8601>
command: /z-research <args>
dispatch_decision:
  map: <ran|reused|skipped|abandoned>
  brainstorm: <ran|reused|skipped|abandoned>
source_artifacts:
  - path: MAP.md
    sha: <git-sha or content-hash>
    generated_at: <ISO>
  - path: BRAINSTORM.md
    sha: <git-sha or content-hash>
    generated_at: <ISO>
synthesizer_models:
  conservative: claude-opus
  expansive: codex (provider-resolved)
  adversarial: gemini (provider-resolved)
  judge: opus
status: complete | abandoned
tripwires_fired: []
---
```

**Body sections (in order):**
1. **`## Approach decision matrix`** (HEADLINE) — markdown table; rows = approaches from BRAINSTORM; columns = constraint classes from MAP. Cells: `<VERDICT>: <citation>` where verdict ∈ `OK | BLOCKS | RISKY | UNVERIFIED`.
2. **`## Cross-artifact contradictions`** — bullets where MAP evidence contradicts BRAINSTORM assumptions; each cites both sides.
3. **`## Design axes`** — 3–5 dimensions organizing the solution space (extracted from synthesis).
4. **`## Terrain summary (extractive from MAP.md)`** — bullets directly quoted from MAP.md findings/constraints.
5. **`## Brainstorm frame space (extractive from BRAINSTORM.md)`** — bullets directly quoted from BRAINSTORM.md framings.
6. **`## High-leverage options`** — approaches that hit the most OK cells with fewest RISKY/BLOCKS.
7. **`## Rejected / weak framings`** — approaches with majority BLOCKS or RISKY; rationale per rejection.
8. **`## Evidence gaps`** — UNVERIFIED cells aggregated; suggested follow-up /z-map runs to close them.
9. **`## Adversarial perspectives summary`** — 1-paragraph synthesis of what each of the 3 synthesizer perspectives emphasized.
10. **`## Mechanical rank-ordering for /z-plan handoff`** (renamed from "Recommended next-command inputs" per Phase 7 Codex narrower-wording graft) — a deterministic sort of approaches by `(BLOCKS desc, RISKY desc, UNVERIFIED desc, OK desc)` from the matrix; constraints whose column has ≥2 BLOCKS cells listed as "mandate as invariant"; UNVERIFIED axes listed as "open questions for user decision." **No recommendation language** ("we suggest...", "the best approach...") — only mechanical aggregation from the matrix.

## Invariants

1. New `/z-research` produces ONLY `artifact_kind: approach_synthesis`. Never writes MAP.md or BRAINSTORM.md content directly (sub-commands own those).
2. Synthesis (research-judge AND research-synthesizer agents) FORBIDDEN from proposing new design recommendations. Only collision-flagging, rank-ordering, evidence-gap surfacing allowed.
3. Every approach decision matrix cell MUST have either a citation OR be marked `UNVERIFIED`. No silent gaps.
4. `/z-plan` one-way gate: when RESEARCH.md with `artifact_kind: approach_synthesis` + `status: complete` exists, it is canonical precontext. Component files (MAP.md, BRAINSTORM.md) are NOT injected.
5. Sub-command dispatch in /z-research Phase 1 is inline (via Agent()) BUT each sub-run gets its own `archive/$RUN/subruns/<sub>/` for audit trail.
6. Adversarial synthesis panel = 3 vendor-diverse perspectives. Vendor assignment static (Claude=conservative, Codex=expansive, Gemini=adversarial). Judge always Opus.
7. Cost gate ALWAYS runs before Phase 1 dispatch. No silent execution at 3–6M token scale.

## Edge cases / error handling

- **MAP.md exists but `artifact_kind` field missing** (pre-rename legacy file): treat as `artifact_kind: map` (the old behavior). Log `legacy_map_artifact_detected`.
- **Sub-command failure mid-dispatch:** abort current /z-research run; preserve the partial artifacts; recommend user inspect + re-invoke. Don't try to "fix" the failed sub-command.
- **Synthesizer perspective failure:** match /z-brainstorm 1/2/3-fail pattern.
- **Judge failure or empty return:** halt, preserve panel outputs, surface to user.
- **Panel returns fewer than 3 perspectives (1/3 or 2/3 fail):** orchestrator passes `perspectives: [<only-successful>]` to research-judge (array-length-variable). Judge handles N=2 by emitting the matrix with 2-perspective citations + a `panel_degraded: true` frontmatter field. N=1 case (after 2/3 fail + user AskUser → proceed-with-1) emits `panel_degraded: true` + `panel_perspective_count: 1` + a warning prepended to the `## Adversarial perspectives summary` section.
- **`/z-plan` finds RESEARCH.md with corrupt frontmatter:** fall back to component-file injection + warn user.
- **`/z-research` invoked when no topic provided:** AskUser; do NOT auto-invent.

## DRY / KISS / SOLID

- **DRY:** RESEARCH.md schema definition lives once (in this SPEC + agents/research-judge.md). Sub-command dispatch reuses existing /z-map and /z-brainstorm skill code unchanged. Cost-gate pattern reused from current /z-research (now /z-map).
- **KISS:** v1 ships inline dispatch (no two-step ceremony). 3 perspectives is the minimum diversity floor. Judge is Opus; no model-tier debate. AskUser at dispatch + cost-gate keeps user in control with strong defaults.
- **SOLID:**
  - *Single responsibility:* research-synthesizer = one perspective, research-judge = merge + emit, /z-research orchestrator = dispatch + cost gate.
  - *Open/closed:* perspectives are caller-parameterized; new perspectives can be added by extending the orchestrator's panel dispatch without modifying the agent.
  - *Liskov:* /z-map and /z-brainstorm interfaces unchanged after rename; /z-research consumes their existing contracts.
  - *Interface segregation:* /z-plan's one-way gate consumes only RESEARCH.md frontmatter + body sections; doesn't peek into component artifacts.
  - *Dependency inversion:* /z-plan depends on RESEARCH.md schema (versioned), not on /z-research's internal implementation.
