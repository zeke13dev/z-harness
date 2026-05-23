# SPEC — brainstorm-and-research

## Files touched

### NEW
- `commands/z-brainstorm.md` + `skills/z-brainstorm/SKILL.md` (mirror)
- `commands/z-research.md` + `skills/z-research/SKILL.md` (mirror)

### MODIFIED
- `agents/codex-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
- `agents/gemini-consultant.md` — add `MODE: brainstorm` and `MODE: research-review`
- `commands/z-plan.md` + `skills/z-plan/SKILL.md` — Phase 0 seed-artifact detection, collision-handling update, source-mtime freshness gate
- `README.md` — document new commands; add to flow diagram

---

## Artifact: BRAINSTORM.md

**Path:** `z-harness/<slug>/BRAINSTORM.md`

**Schema:**

```markdown
---
artifact: brainstorm
slug: <slug>
generated_at: <ISO 8601 UTC>
command: /z-brainstorm
input_hash: <sha256 of "topic\n\n<doc-fetcher synthesis>\n\n<explore findings if any>\n\n<research summary if RESEARCH.md was present>">
depends_on: <abs path to RESEARCH.md if chained, else "none">
ideators: ["claude-sonnet", "codex", "gemini"]
---

# Brainstorm: <topic>

## Topic
<verbatim user-provided topic>

## Scaffolding
**doc-fetcher synthesis:** <inline, or "skipped (no docs/llm/INDEX.json)">
**Explore findings:** <inline, or "skipped (cap=0 by default)">
**RESEARCH.md summary:** <inline if RESEARCH.md was present and ≤20 KB; extractive summary if larger; "n/a" if absent>

## Framings considered

### Framing 1 — Claude (Sonnet, fresh subagent context)
**Framing:** <one paragraph>
**Core hypothesis:** <one paragraph>
**Risks:** <one paragraph>
**Plan implications:** <one paragraph>
**What would change my mind:** <one paragraph>

### Framing 2 — Codex
<same five sections>

### Framing 3 — Gemini
<same five sections>

## Anti-bias check (mandatory)
<Synthesis comparison: section-by-section, which framing wins each dimension and why. If Claude wins overall, explicit justification against the others on concrete criteria. If Claude does not win overall, list the specific Claude elements (if any) merged into the chosen framing.>

## Orchestrator recommendation
**Recommended framing:** <which one + one-line rationale>

## User's chosen framing
<set during Phase 3 user gate; one of "Framing 1" | "Framing 2" | "Framing 3" | "Restart" | free-text>

## Free-text annotation
<user-provided refinement notes from AskUserQuestion>
```

**Invariants:**
- `input_hash` MUST be computed deterministically (same inputs → same hash) so re-runs are detectable.
- The three ideator return blocks MUST have identical section headings (`Framing`, `Core hypothesis`, `Risks`, `Plan implications`, `What would change my mind`). An ideator that returns a different shape is treated as a malformed return — orchestrator either re-prompts or records the missing sections as `<missing>` and flags in the anti-bias check.
- `User's chosen framing` is empty until the user gate completes. If user picks "Restart," BRAINSTORM.md is moved to `archive/<run>/BRAINSTORM.md.abandoned` and a fresh run starts.

---

## Artifact: RESEARCH.md

**Path:** `z-harness/<slug>/RESEARCH.md`

**Schema:**

```markdown
---
artifact: research
slug: <slug>
generated_at: <ISO 8601 UTC>
command: /z-research
input_hash: <sha256 of "question\n\n<doc-fetcher synthesis if any>">
depends_on: none
explore_calls: <integer 0-3>
---

# Research: <question>

## Question
<verbatim user-provided question>

## Findings
<bulleted list of factual statements with `file:line` citations and one-line synopses>

## Constraints discovered
<bulleted list of constraints the codebase / problem imposes; each with citation>

## Open questions
<things research could not answer; likely needs experiments / user input>

## No-recommendation
**Research does NOT pick an approach. The terrain has been mapped; the decision is downstream (`/z-brainstorm` or `/z-plan`).**

## Cross-LLM review notes (from Phase 3 consult)
**Gemini flagged:** <bullets>
**Codex flagged:** <bullets>
**Author's response:** <which gaps were filled in Phase 4, which were intentionally left, why>
```

**Invariants:**
- `Findings` entries MUST cite specific `file:line` ranges. A finding without a citation is treated as a hypothesis, not a finding, and gets demoted to `Open questions`.
- `No-recommendation` section is mandatory and non-deletable. `/z-research` MUST NOT recommend an approach; if the orchestrator feels strongly enough to recommend, it logs `research_temptation` event and proceeds without recommending (so we can measure how often this constraint chafes).
- `explore_calls` is hard-capped at 3 (matching `/z-plan`'s `Z_HARNESS_MAX_EXPLORE`).

---

## Command: `/z-brainstorm <topic>`

**File:** `commands/z-brainstorm.md`
**Skill mirror:** `skills/z-brainstorm/SKILL.md`

### Frontmatter
```
---
name: z-brainstorm
description: Generate N candidate problem-framings in parallel using different model vendors (Claude + Codex + Gemini), then present to user for selection. Opt-in pre-plan exploration; feeds /z-plan as Phase 0 seed.
---
```

### CLI surface
```
/z-brainstorm <topic>           # default: auto-derived slug from topic
/z-brainstorm <topic> --slug=X  # explicit slug (for chaining)
```

### Phases

**Setup** (mirrors `/z-plan-light` Setup pattern):
1. Derive slug (auto from topic, or use `--slug=X` if provided). If slug dir exists with `BRAINSTORM.md` already, ask via AskUserQuestion: overwrite / append to a new run / abort.
2. Export `Z_HARNESS_SLUG`, pick `RUN`, mkdir, version stamp, `log-event.sh brainstorm_run_start`.
3. Read `docs/llm/INDEX.json` existence flag (note for Phase 1).
4. Check for `$BASE/RESEARCH.md` — if present, note `depends_on` path.

**Phase 1 — Scaffolding** (cheap, doc-fetcher + optional Explore):
- If `docs/llm/INDEX.json` exists, dispatch `doc-fetcher` (Haiku, one call) per the standard pattern. Capture synthesis.
- Default: NO Explore dispatch (`/z-brainstorm` is the lightest of the three precontext commands; Explore is for `/z-research`). Override via `Z_HARNESS_BRAINSTORM_EXPLORE=1` to allow one Haiku Explore for tasks where doc-fetcher returned `STATUS: no_match` or `STATUS: no_docs` and the topic clearly needs code grounding.
- If `RESEARCH.md` exists, read it. If size ≤20 KB, prepare full inline payload. If >20 KB, generate an extractive summary preserving file:line citations + constraints + open questions (no abstractive generalization), and save to `archive/<run>/research-summary-for-brainstorm.md` for audit.

**Phase 2 — Dispatch 3 ideators in parallel**:
Send ONE message with three `Agent()` calls — Claude (Sonnet, fresh subagent), Codex (codex-consultant with `MODE: brainstorm`), Gemini (gemini-consultant with `MODE: brainstorm`). All three receive:

```
MODE: brainstorm
Topic: <topic>
Scaffolding:
  doc-fetcher: <synthesis or "n/a">
  Explore: <findings or "n/a">
  Research: <inline content or extractive summary or "n/a">

Return EXACTLY this shape (five sections, all required):
  Framing: <one paragraph>
  Core hypothesis: <one paragraph>
  Risks: <one paragraph>
  Plan implications: <one paragraph>
  What would change my mind: <one paragraph>

No implementation detail. No code snippets. One paragraph each.
```

Claude ideator uses subagent_type="general-purpose" (or a new "ideator" agent if we add one; see Open question O1 in PLAN.md) with `model="sonnet"`.

**Phase 3 — Synthesis + anti-bias check**:
1. Parse the three returns. If any ideator returned malformed (missing sections), record `<missing>` for that section in BRAINSTORM.md and flag in anti-bias check.
2. Write BRAINSTORM.md with all three framings.
3. **Anti-bias check (mandatory, mechanical):** for each of the five sections, compare the three ideators' answers and note which framing wins that dimension. If Claude wins the most dimensions, explicitly justify against the others on named criteria (matches Codex's synthesis-bias guard).
4. Pick an orchestrator recommendation; record the one-line rationale.
5. Push notification: "Brainstorm ready (3 framings); user gate."
6. `AskUserQuestion` with previews — option per framing + "Restart with different topic framing" + "Abandon."

**Phase 4 — Finalize**:
- Save user's chosen framing + any free-text annotation into BRAINSTORM.md.
- `log-event.sh brainstorm_run_end` with `{status, tokens_spent, ideator_durations_ms, chosen_framing}`.
- Push notification with recommendation: "Run `/z-plan <slug>` (consumes this brainstorm) or run again if framing needed refinement."

### Cost guardrail
Target ≤200K tokens total. Log warning if exceeded.

### Out of scope (v1)
- Pluggable ideator list. Default is hard-coded `[claude-sonnet, codex, gemini]`; future v2 will accept `Z_HARNESS_BRAINSTORM_IDEATORS="claude-sonnet,codex,gemini,grok"` or similar.

---

## Command: `/z-research <question>`

**File:** `commands/z-research.md`
**Skill mirror:** `skills/z-research/SKILL.md`

### Frontmatter
```
---
name: z-research
description: Heavier terrain-mapping using doc-fetcher + up to 3 Explore subagents + bundled cross-LLM critique. Produces RESEARCH.md (findings, constraints, open questions, explicit no-recommendation). Opt-in pre-plan exploration.
---
```

### CLI surface
```
/z-research <question>
/z-research <question> --slug=X
```

### Phases

**Setup**: same shape as `/z-brainstorm` Setup, but `log-event.sh research_run_start`.

**Phase 0 — Cost-confirmation gate**:
Before any subagent dispatch, AskUserQuestion: "Research is the heaviest precontext command (target ≤2M tokens, up to 3 Explore subagents). Proceed?" Options: "Proceed" / "Reduce to 1 Explore" / "Abandon." Log user's pick.

**Phase 1 — doc-fetcher** (if INDEX.json exists, one call).

**Phase 2 — Up to 3 Explore subagents on distinct facets**:
- Orchestrator articulates 3 distinct facets of the question (or 1 if user reduced cap).
- Parallel dispatch (single message, multiple Agent calls).
- Each Explore is Haiku by default; orchestrator may upgrade individual calls to Sonnet for interpretation-heavy facets.

**Phase 3 — Synthesize research-note draft**:
Main thread writes the draft to `archive/<run>/research-draft.md`. MUST include:
- `Findings:` with file:line citations
- `Constraints discovered:`
- `Open questions:`
- `No-recommendation:` (mandatory)

**Phase 4 — Bundled cross-LLM critique** (`MODE: research-review` on both consultants):
Both consultants receive the draft + the question + the doc-fetcher synthesis. They return: missing findings, wrong claims, undocumented constraints. No recommendation on approach (consultants are explicitly told not to recommend in research-review mode — same as the artifact itself).

**Phase 5 — Revise draft based on critiques**:
Apply findings that hold up under "one reason it might be wrong" scrutiny. Record consultant feedback in RESEARCH.md's "Cross-LLM review notes" section. Note which gaps were filled, which were intentionally left.

**Phase 6 — Finalize**:
- Write final `RESEARCH.md` (with YAML frontmatter).
- `log-event.sh research_run_end` with `{status, tokens_spent, explore_calls, consultant_durations_ms, findings_count}`.
- Push notification with recommendation: "Run `/z-brainstorm <slug>` next (consumes this research) or run `/z-plan <slug>` directly."

### Cost guardrail
Target ≤2M tokens total. Log warning if exceeded.

---

## Consultant agent extensions

### `agents/codex-consultant.md` and `agents/gemini-consultant.md`

Add two new modes to the existing `## Modes` section:

**`MODE: brainstorm`** (Phase 2 of `/z-brainstorm`): caller hands you a topic + scaffolding (doc-fetcher synthesis + Explore findings + RESEARCH.md content if any). You are GENERATING an idea, not VALIDATING one. Return exactly five sections (Framing, Core hypothesis, Risks, Plan implications, What would change my mind), one paragraph each, no implementation detail. Use the underlying LLM's "propose an angle on this problem" capability — don't just summarize the inputs.

**`MODE: research-review`** (Phase 4 of `/z-research`): caller hands you a research-note draft + the question + the doc-fetcher synthesis. Critique for: (1) missing findings — claims that the codebase supports but the draft didn't make; (2) wrong claims — assertions contradicted by the cited source files; (3) undocumented constraints — limits the draft should have noted; (4) hypothesis creep — anywhere the draft snuck in a recommendation despite the "no-recommendation" rule. **Do not recommend an approach yourself.** Return: gaps to fill, errors to correct, no recommendation.

Both new modes follow the existing return-shape pattern (header, recommendation/critique, reasoning, tradeoffs/risks, additional considerations, raw response excerpt).

---

## `/z-plan` Phase 0 changes

**File:** `commands/z-plan.md` (and skill mirror).

### Insertion point
Immediately AFTER Setup step 9 (docs-freshness gate), BEFORE current Phase 0 (Premise check), add a new sub-step **Setup step 10 — Precontext artifact detection**:

```markdown
### 10. Precontext artifact detection

If `$BASE/BRAINSTORM.md` or `$BASE/RESEARCH.md` exists, treat the slug dir as a **continuation**, not a collision:
- Read each artifact's YAML frontmatter (`generated_at`, `input_hash`, `depends_on`).
- For RESEARCH.md: parse the `Findings:` section for `file:line` citations; for each cited file, compare its `mtime` against RESEARCH.md's `generated_at`. If any source file is newer, log `precontext_stale` event and warn the user via `AskUserQuestion`: "Source files cited in RESEARCH.md were modified after the research was written. Continue, refresh `/z-research`, or abandon?" Default: continue (warned).
- For BRAINSTORM.md: check that the user's chosen framing field is populated (otherwise the brainstorm was never finalized — recommend re-running `/z-brainstorm`).
- If BOTH artifacts exist AND they contradict (e.g. RESEARCH lists a constraint that BRAINSTORM's chosen framing violates), surface via `AskUserQuestion`: "Detected potential conflict: <one-line description>. Reconcile, abandon, or proceed acknowledging the conflict?"
- Pass the chosen framing (from BRAINSTORM) and findings (from RESEARCH) into Phase 0 (Premise check) so the orchestrator doesn't re-derive what's already established.

If neither artifact exists, proceed normally (this is the standard `/z-plan` path).
```

### Phase 0 premise-check update
Update the premise-check prose: "If a precontext artifact was loaded in Setup step 10, frame the premise check as: 'Given the chosen framing from BRAINSTORM.md (or findings from RESEARCH.md), is the user's request still well-posed? Is there any contradiction between the precontext and the current task description?' Do NOT re-litigate the framing; that's what brainstorm decided."

### Phase 1 exploration update
"If RESEARCH.md is present and fresh, **doc-fetcher and Explore are optional, not mandatory.** Use the research-note findings as scaffolding; only dispatch new Explore subagents to fill gaps the research note explicitly listed in its `Open questions:` section."

### Phase 6 SPEC.md update
Add to SPEC.md template: a `## Planning Inputs` section listing which precontext artifacts contributed (paths + `generated_at`). If neither was used, write "none — fresh /z-plan run."

### Collision-handling update
Current `/z-plan` Setup step 1 should distinguish:
- **Continuation candidate:** slug dir contains BRAINSTORM.md and/or RESEARCH.md but no SPEC.md/PLAN.md. Proceed without prompting.
- **Collision:** slug dir contains SPEC.md or PLAN.md. Prompt user via AskUserQuestion as today.

---

## README.md changes

Add the new commands to the existing command list / flow diagram. Document `Z_HARNESS_BRAINSTORM_EXPLORE` env var. Add example chain: `/z-research → /z-brainstorm → /z-plan` for the murky-problem case.

---

## Non-goals (out of scope)

- Pluggable ideator model list — future v2.
- Auto-detection of "this task needs precontext" inside `/z-plan` — keep opt-in.
- A `/z-brainstorm-light` or `/z-research-light` mini-variant.
- Real-time / streaming ideator returns. They land all at once when the parallel Agent batch finishes.
- Removing the `Z_HARNESS_RETRY_UPGRADE` deprecation note (separate concern; per-task-model-selection is the right place).
- Resolving the underlying `commands/` vs `skills/` mirror duplication (flagged in per-task-model-selection retro; out of scope here).

---

## Acceptance

- `commands/z-brainstorm.md` + `skills/z-brainstorm/SKILL.md` exist, are byte-identical aside from `name:` frontmatter and blank-line conventions, document all phases above.
- `commands/z-research.md` + `skills/z-research/SKILL.md` exist with same parity.
- `agents/codex-consultant.md` and `agents/gemini-consultant.md` have new `MODE: brainstorm` and `MODE: research-review` entries in the `## Modes` section, following the existing pattern.
- `commands/z-plan.md` and `skills/z-plan/SKILL.md` have new Setup step 10 (precontext detection), updated Phase 0 / Phase 1 / Phase 6 prose, and updated collision-handling rule.
- `README.md` documents the new commands and the chain.
- Test invocation: running `/z-research test-question` writes a `RESEARCH.md` with valid frontmatter and the mandatory `No-recommendation` section. Running `/z-brainstorm test-topic` after a `RESEARCH.md` exists in the same slug includes that RESEARCH content in each ideator's prompt.
- All Codex review blockers/majors resolved.

## Clarifications from Phase 7 review

These supersede earlier prose where they conflict.

### Consultant return shape (NEW MODES)

`MODE: brainstorm` and `MODE: research-review` are the FIRST consultant modes that do not use the standard wrapper (Recommendation / Reasoning / Tradeoffs / Additional considerations / Raw excerpt). They return raw content:

- `brainstorm`: returns exactly the 5 sections (Framing / Core hypothesis / Risks / Plan implications / What would change my mind), one paragraph each. No wrapper.
- `research-review`: returns gaps-to-fill, errors-to-correct, undocumented constraints. No "recommendation" line — explicitly forbidden in this mode.

The consultant agent files must call this out: "For modes brainstorm and research-review, return raw content per the mode's prescribed shape. Do NOT wrap in the standard return shape."

### `input_hash` algorithm

```
input_hash = sha256(canonicalize(
    topic + "\n---\n" +
    doc_fetcher_synthesis_or_empty + "\n---\n" +
    explore_findings_or_empty + "\n---\n" +
    research_content_or_empty
))
```
where `canonicalize()` strips leading/trailing whitespace and collapses internal whitespace runs to single spaces. Output is the first 16 hex chars of the digest (truncation acceptable for collision detection at our scale).

### Ideator failure policy

- **1 of 3 ideators fails:** proceed with 2 framings. BRAINSTORM.md frontmatter records `ideators: ["claude-sonnet", "codex", "gemini:failed"]`. Anti-bias check prose explicitly notes "Comparison is 2-way due to ideator failure." `ideator_failed` event logged with `{vendor, error}`.
- **2 of 3 fail:** halt + AskUserQuestion (retry all / proceed-with-1 / abandon). Default focus: retry.
- **3 of 3 fail:** hard halt, `total_ideator_failure` event, push-notify, exit non-zero.

### Restart vs Abandon (in /z-brainstorm Phase 3 user gate)

- **Restart:** existing BRAINSTORM.md moved to `archive/<run>/BRAINSTORM.md.previous-<N>` (N = next available integer), user prompted for refined topic, new RUN id begins, fresh artifact written.
- **Abandon:** BRAINSTORM.md frontmatter updated with `status: abandoned`, file kept in slug dir, `brainstorm_run_end` logged with `status: abandoned`, exit.

### Source-mtime freshness edge cases

- Timestamps normalized to UTC ISO 8601 with milliseconds.
- Symlinks: follow them (target's mtime is authoritative).
- Deleted file referenced by RESEARCH.md citation: `precontext_source_deleted` event (severity higher than mtime-stale), warn user separately from regular staleness warning.
- Citation range (`file.rs:120-145`): check if ANY line in range was modified — use min-line + file mtime as the comparison.
- Citation parse failure: `precontext_freshness_check_failed` event, fail-open (continue without warning rather than blocking the user).

### Citation regex

```regex
[A-Za-z0-9_./-]+\.(rs|py|md|ts|tsx|js|jsx|json|toml|yaml|yml|sh|sql)(:\d+(-\d+)?)?
```

Extensionless paths (Makefile, Dockerfile, CHANGELOG) handled via an allowlist scan: a fixed list of well-known extensionless filenames matched against `[A-Za-z0-9_./-]+/(Makefile|Dockerfile|CHANGELOG|LICENSE)`. Markdown-link form `[label](path:line)` is handled by extracting the inner path from the link's URL portion before applying the regex.

### Phase 1 boundary in /z-plan when precontext present

- Skip `doc-fetcher` iff RESEARCH.md is non-stale AND its `Findings:` section has ≥1 entry citing a file in the task's likely-touched set (heuristic: same top-level dir as a file already mentioned in the task description or BRAINSTORM's chosen framing).
- Skip `Explore` iff RESEARCH.md is non-stale AND its `Open questions:` section is empty.

### Mirror task collapse

Each `commands/<x>.md` + `skills/<x>/SKILL.md` pair is ONE task — the implementer writes both files in the same dispatch. The task's acceptance criteria includes a byte-near-identity check (`diff` showing only `name:` frontmatter and blank-line differences).

### Telemetry alignment

Use the existing `log-event.sh consult` payload shape: `{llm, mode, prompt_chars, response_chars, wall_ms, transcript}`. Token counts are NOT in spec — `/z-stats` can approximate via char ratio. New event types added for the new commands: `brainstorm_run_start`, `brainstorm_run_end`, `research_run_start`, `research_run_end`, `ideator_failed`, `total_ideator_failure`, `precontext_stale`, `precontext_source_deleted`, `precontext_freshness_check_failed`, `research_temptation`.

### Known v1 limitations

- **No wall-clock timeout on subagents.** `Agent()` doesn't expose a per-call timeout. If an ideator hangs, the user must ctrl-c the orchestrator. Future v2 candidate.
- **doc-fetcher not cached.** Running `/z-brainstorm` then `/z-research` on the same slug dispatches doc-fetcher twice. Future v2 candidate.

### Acceptance criteria additions (negative-case coverage)

Each command's acceptance MUST cover:
- Precontext-only continuation (slug dir has BRAINSTORM/RESEARCH only, no SPEC/PLAN — should be treated as continuation, not collision).
- Finished-plan collision (slug dir has SPEC/PLAN — should prompt user as today).
- Stale-source warning (citation file mtime newer than RESEARCH.md `generated_at`).
- Unfinalized brainstorm (BRAINSTORM.md exists but `User's chosen framing:` is empty — `/z-plan` should recommend re-running brainstorm).
- Both-artifact conflict (RESEARCH constraint + BRAINSTORM framing contradict — should surface to user).
- Ideator failure modes (1/3, 2/3, 3/3 fail).

## DRY / KISS / SOLID

- **DRY:** consultant `MODE: brainstorm` and `MODE: research-review` extend the existing multi-mode pattern rather than forking new agents. YAML frontmatter is consistent across both artifact types. `--slug` flag uses the same parsing as existing commands' arg handling.
- **KISS:** distinct artifacts (Option A) over forced unification. Hard cap of 3 ideators / 3 Explores rather than configurable; opt-in env vars exist but defaults are sane.
- **SOLID — Single Responsibility:** `/z-brainstorm` does ideation, `/z-research` does mapping, `/z-plan` does planning. Each writes its own artifact; consumers read others' artifacts but don't redefine them.
- **SOLID — Open/Closed:** `/z-plan` Phase 0 extends to handle precontext without changing the rest of the planner. Consultant modes extend without modifying existing modes.
